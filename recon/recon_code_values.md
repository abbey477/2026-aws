# Recon: CERD_CORPORATE.CODE_VALUES vs REFDBO.CODE_VALUES

Compares rows between the two replicated tables and writes a per-key comparison result to `RECON_RESULT_CODE_VALUES`. Runs on a schedule via `DBMS_SCHEDULER`.

## Design summary

- **Source of truth:** `CERD_CORPORATE.CODE_VALUES` (`_CC` columns)
- **Compared against:** `REFDBO.CODE_VALUES` (`_RD` columns)
- **Join key (composite):** `ID_TYP_CODE`, `ID_CODE` (backs the unique index `CODE_VALUES_KEY`)
- **Shared columns compared:** `TX_CODE`, `ID_TYP_CODE_GBL`, `ID_CODE_MAX`, `ID_CODE_VAL`, `DT_CHG_GRD`, `ID_DEL_GRD`, `ID_OWN_GRD`
- **Excluded (REFDBO-only, not in source of truth):** `LRI_EFF_ASOF_DT`, `LRI_EFF_UNTIL_DT`
- **Lag cutoff:** 2 hours (`SYSDATE - 120/1440`) applied on both sides, so mid-flight replicating rows aren't compared
- **Case handling:** all text values `UPPER()`-cased before hashing/comparing
- **Hash:** `ORA_HASH` over concatenated shared columns with `NVL(..., '__NULL__')` sentinels for null-safety
- **Result shape:** one row per key per run, with `_CC` / `_RD` / `_STATUS` triplets per column

---

## Step 1 — Create the result table

Run once per environment.

```sql
CREATE TABLE RECON_RESULT_CODE_VALUES
(
    BATCH_ID                TIMESTAMP        NOT NULL,
    RUN_DATE                DATE             NOT NULL,

    ID_TYP_CODE             VARCHAR2(8 CHAR) NOT NULL,
    ID_CODE                 VARCHAR2(8 CHAR) NOT NULL,

    ROW_HASH_CC              NUMBER,
    ROW_HASH_RD              NUMBER,
    ROW_HASH_STATUS          VARCHAR2(10),

    TX_CODE_CC               VARCHAR2(35 CHAR),
    TX_CODE_RD               VARCHAR2(35 CHAR),
    TX_CODE_STATUS           VARCHAR2(10),

    ID_TYP_CODE_GBL_CC       VARCHAR2(8 CHAR),
    ID_TYP_CODE_GBL_RD       VARCHAR2(8 CHAR),
    ID_TYP_CODE_GBL_STATUS   VARCHAR2(10),

    ID_CODE_MAX_CC           VARCHAR2(8 CHAR),
    ID_CODE_MAX_RD           VARCHAR2(8 CHAR),
    ID_CODE_MAX_STATUS       VARCHAR2(10),

    ID_CODE_VAL_CC           NUMBER(10),
    ID_CODE_VAL_RD           NUMBER(10),
    ID_CODE_VAL_STATUS       VARCHAR2(10),

    DT_CHG_GRD_CC            DATE,
    DT_CHG_GRD_RD            DATE,
    DT_CHG_GRD_STATUS        VARCHAR2(10),

    ID_DEL_GRD_CC            VARCHAR2(1 CHAR),
    ID_DEL_GRD_RD            VARCHAR2(1 CHAR),
    ID_DEL_GRD_STATUS        VARCHAR2(10),

    ID_OWN_GRD_CC            NUMBER(5),
    ID_OWN_GRD_RD            NUMBER(5),
    ID_OWN_GRD_STATUS        VARCHAR2(10)
);

CREATE INDEX IX_RRCV_BATCH_ID ON RECON_RESULT_CODE_VALUES (BATCH_ID);
CREATE INDEX IX_RRCV_KEY ON RECON_RESULT_CODE_VALUES (ID_TYP_CODE, ID_CODE);
```

### Column groups at a glance

| Group | Columns |
|---|---|
| Identity | `BATCH_ID` (shared across all rows of one run), `RUN_DATE` |
| Key | `ID_TYP_CODE`, `ID_CODE` |
| Overall | `ROW_HASH_CC`, `ROW_HASH_RD`, `ROW_HASH_STATUS` |
| TX_CODE | `TX_CODE_CC`, `TX_CODE_RD`, `TX_CODE_STATUS` |
| ID_TYP_CODE_GBL | `ID_TYP_CODE_GBL_CC`, `ID_TYP_CODE_GBL_RD`, `ID_TYP_CODE_GBL_STATUS` |
| ID_CODE_MAX | `ID_CODE_MAX_CC`, `ID_CODE_MAX_RD`, `ID_CODE_MAX_STATUS` |
| ID_CODE_VAL | `ID_CODE_VAL_CC`, `ID_CODE_VAL_RD`, `ID_CODE_VAL_STATUS` |
| DT_CHG_GRD | `DT_CHG_GRD_CC`, `DT_CHG_GRD_RD`, `DT_CHG_GRD_STATUS` |
| ID_DEL_GRD | `ID_DEL_GRD_CC`, `ID_DEL_GRD_RD`, `ID_DEL_GRD_STATUS` |
| ID_OWN_GRD | `ID_OWN_GRD_CC`, `ID_OWN_GRD_RD`, `ID_OWN_GRD_STATUS` |

---

## Step 2 — Create the recon procedure

Run once per environment. `CREATE OR REPLACE` means you can re-run it safely to update the logic later.

```sql
CREATE OR REPLACE PROCEDURE RUN_RECON_CODE_VALUES
AS
    v_batch_id   TIMESTAMP := SYSTIMESTAMP;
    v_run_date   DATE      := SYSDATE;
BEGIN

    INSERT INTO RECON_RESULT_CODE_VALUES
    (
        BATCH_ID, RUN_DATE,
        ID_TYP_CODE, ID_CODE,
        ROW_HASH_CC, ROW_HASH_RD, ROW_HASH_STATUS,
        TX_CODE_CC, TX_CODE_RD, TX_CODE_STATUS,
        ID_TYP_CODE_GBL_CC, ID_TYP_CODE_GBL_RD, ID_TYP_CODE_GBL_STATUS,
        ID_CODE_MAX_CC, ID_CODE_MAX_RD, ID_CODE_MAX_STATUS,
        ID_CODE_VAL_CC, ID_CODE_VAL_RD, ID_CODE_VAL_STATUS,
        DT_CHG_GRD_CC, DT_CHG_GRD_RD, DT_CHG_GRD_STATUS,
        ID_DEL_GRD_CC, ID_DEL_GRD_RD, ID_DEL_GRD_STATUS,
        ID_OWN_GRD_CC, ID_OWN_GRD_RD, ID_OWN_GRD_STATUS
    )
    WITH cc_hash AS (
        SELECT
            ID_TYP_CODE, ID_CODE,
            UPPER(TX_CODE)              AS TX_CODE,
            UPPER(ID_TYP_CODE_GBL)      AS ID_TYP_CODE_GBL,
            UPPER(ID_CODE_MAX)          AS ID_CODE_MAX,
            ID_CODE_VAL, DT_CHG_GRD,
            UPPER(ID_DEL_GRD)           AS ID_DEL_GRD,
            ID_OWN_GRD,
            ORA_HASH(
                NVL(UPPER(TX_CODE), '__NULL__') || '|' ||
                NVL(UPPER(ID_TYP_CODE_GBL), '__NULL__') || '|' ||
                NVL(UPPER(ID_CODE_MAX), '__NULL__') || '|' ||
                NVL(TO_CHAR(ID_CODE_VAL), '__NULL__') || '|' ||
                NVL(TO_CHAR(DT_CHG_GRD, 'YYYYMMDDHH24MISS'), '__NULL__') || '|' ||
                NVL(UPPER(ID_DEL_GRD), '__NULL__') || '|' ||
                NVL(TO_CHAR(ID_OWN_GRD), '__NULL__')
            ) AS ROW_HASH
        FROM CERD_CORPORATE.CODE_VALUES
        WHERE DT_CHG_GRD <= SYSDATE - (120/1440)
    ),
    rd_hash AS (
        SELECT
            ID_TYP_CODE, ID_CODE,
            UPPER(TX_CODE)              AS TX_CODE,
            UPPER(ID_TYP_CODE_GBL)      AS ID_TYP_CODE_GBL,
            UPPER(ID_CODE_MAX)          AS ID_CODE_MAX,
            ID_CODE_VAL, DT_CHG_GRD,
            UPPER(ID_DEL_GRD)           AS ID_DEL_GRD,
            ID_OWN_GRD,
            ORA_HASH(
                NVL(UPPER(TX_CODE), '__NULL__') || '|' ||
                NVL(UPPER(ID_TYP_CODE_GBL), '__NULL__') || '|' ||
                NVL(UPPER(ID_CODE_MAX), '__NULL__') || '|' ||
                NVL(TO_CHAR(ID_CODE_VAL), '__NULL__') || '|' ||
                NVL(TO_CHAR(DT_CHG_GRD, 'YYYYMMDDHH24MISS'), '__NULL__') || '|' ||
                NVL(UPPER(ID_DEL_GRD), '__NULL__') || '|' ||
                NVL(TO_CHAR(ID_OWN_GRD), '__NULL__')
            ) AS ROW_HASH
        FROM REFDBO.CODE_VALUES
        WHERE DT_CHG_GRD <= SYSDATE - (120/1440)
    )
    SELECT
        v_batch_id, v_run_date,
        COALESCE(cc.ID_TYP_CODE, rd.ID_TYP_CODE),
        COALESCE(cc.ID_CODE, rd.ID_CODE),

        cc.ROW_HASH, rd.ROW_HASH,
        CASE WHEN NVL(cc.ROW_HASH, -1) = NVL(rd.ROW_HASH, -1)
                  AND cc.ROW_HASH IS NOT NULL AND rd.ROW_HASH IS NOT NULL
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.TX_CODE, rd.TX_CODE,
        CASE WHEN NVL(cc.TX_CODE, '__NULL__') = NVL(rd.TX_CODE, '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.ID_TYP_CODE_GBL, rd.ID_TYP_CODE_GBL,
        CASE WHEN NVL(cc.ID_TYP_CODE_GBL, '__NULL__') = NVL(rd.ID_TYP_CODE_GBL, '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.ID_CODE_MAX, rd.ID_CODE_MAX,
        CASE WHEN NVL(cc.ID_CODE_MAX, '__NULL__') = NVL(rd.ID_CODE_MAX, '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.ID_CODE_VAL, rd.ID_CODE_VAL,
        CASE WHEN NVL(TO_CHAR(cc.ID_CODE_VAL), '__NULL__') = NVL(TO_CHAR(rd.ID_CODE_VAL), '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.DT_CHG_GRD, rd.DT_CHG_GRD,
        CASE WHEN NVL(TO_CHAR(cc.DT_CHG_GRD,'YYYYMMDDHH24MISS'), '__NULL__')
                  = NVL(TO_CHAR(rd.DT_CHG_GRD,'YYYYMMDDHH24MISS'), '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.ID_DEL_GRD, rd.ID_DEL_GRD,
        CASE WHEN NVL(cc.ID_DEL_GRD, '__NULL__') = NVL(rd.ID_DEL_GRD, '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END,

        cc.ID_OWN_GRD, rd.ID_OWN_GRD,
        CASE WHEN NVL(TO_CHAR(cc.ID_OWN_GRD), '__NULL__') = NVL(TO_CHAR(rd.ID_OWN_GRD), '__NULL__')
             THEN 'MATCH' ELSE 'MISMATCH' END

    FROM cc_hash cc
    FULL OUTER JOIN rd_hash rd
        ON cc.ID_TYP_CODE = rd.ID_TYP_CODE
       AND cc.ID_CODE     = rd.ID_CODE;

    COMMIT;

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;

END RUN_RECON_CODE_VALUES;
/
```

### Manual smoke test

```sql
EXEC RUN_RECON_CODE_VALUES;
```

### Result verification

```sql
-- Latest batch
SELECT MAX(BATCH_ID) FROM RECON_RESULT_CODE_VALUES;

-- Counts for latest batch
SELECT ROW_HASH_STATUS, COUNT(*)
  FROM RECON_RESULT_CODE_VALUES
 WHERE BATCH_ID = (SELECT MAX(BATCH_ID) FROM RECON_RESULT_CODE_VALUES)
 GROUP BY ROW_HASH_STATUS;

-- Which specific rows mismatched, and on which column
SELECT ID_TYP_CODE, ID_CODE, TX_CODE_STATUS, ID_CODE_VAL_STATUS
  FROM RECON_RESULT_CODE_VALUES
 WHERE BATCH_ID = (SELECT MAX(BATCH_ID) FROM RECON_RESULT_CODE_VALUES)
   AND ROW_HASH_STATUS = 'MISMATCH';
```

---

## Step 3 — Schedule it via DBMS_SCHEDULER

### 3.1 Prerequisite: `CREATE JOB` privilege

Ask your DBA to confirm your account has it. If missing:

```sql
GRANT CREATE JOB TO <your_schema>;
```

### 3.2 Create the scheduled job

Run once. This registers the job; the scheduler takes over from there.

```sql
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'JOB_RECON_CODE_VALUES',
        job_type        => 'STORED_PROCEDURE',
        job_action      => 'RUN_RECON_CODE_VALUES',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY; INTERVAL=2',   -- every 2 hours
        enabled         => TRUE,
        comments        => 'CODE_VALUES recon: CERD_CORPORATE vs REFDBO'
    );
END;
/
```

**Common `repeat_interval` alternatives:**

| Cadence | `repeat_interval` |
|---|---|
| Every 2 hours | `'FREQ=HOURLY; INTERVAL=2'` |
| Every 6 hours | `'FREQ=HOURLY; INTERVAL=6'` |
| Daily at 2 AM | `'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0'` |
| Weekdays only, 2 AM | `'FREQ=DAILY; BYDAY=MON,TUE,WED,THU,FRI; BYHOUR=2'` |

### 3.3 Verify the job registered

```sql
SELECT JOB_NAME, ENABLED, STATE, NEXT_RUN_DATE
  FROM USER_SCHEDULER_JOBS
 WHERE JOB_NAME = 'JOB_RECON_CODE_VALUES';
```

`ENABLED = TRUE` and a populated `NEXT_RUN_DATE` mean the scheduler has accepted the job.

### 3.4 Force an immediate test run (optional)

Runs the job once right now, without affecting the recurring schedule.

```sql
BEGIN
    DBMS_SCHEDULER.RUN_JOB('JOB_RECON_CODE_VALUES');
END;
/
```

### 3.5 Review run history

```sql
SELECT LOG_DATE, STATUS, ACTUAL_START_DATE, RUN_DURATION, ERROR#, ADDITIONAL_INFO
  FROM USER_SCHEDULER_JOB_RUN_DETAILS
 WHERE JOB_NAME = 'JOB_RECON_CODE_VALUES'
 ORDER BY LOG_DATE DESC;
```

- `STATUS = SUCCEEDED` — the procedure ran and committed
- `STATUS = FAILED` — the procedure raised an error; `ADDITIONAL_INFO` holds the `SQLERRM`

### 3.6 Ongoing operations

```sql
-- Pause the job (stops future runs; keeps history)
BEGIN DBMS_SCHEDULER.DISABLE('JOB_RECON_CODE_VALUES'); END;
/

-- Resume
BEGIN DBMS_SCHEDULER.ENABLE('JOB_RECON_CODE_VALUES'); END;
/

-- Change schedule without dropping the job
BEGIN
    DBMS_SCHEDULER.SET_ATTRIBUTE(
        name      => 'JOB_RECON_CODE_VALUES',
        attribute => 'repeat_interval',
        value     => 'FREQ=HOURLY; INTERVAL=4'
    );
END;
/

-- Remove entirely
BEGIN DBMS_SCHEDULER.DROP_JOB('JOB_RECON_CODE_VALUES'); END;
/
```

---

## Deployment order (per environment)

1. Run **Step 1** — creates the result table (do this once, ever)
2. Run **Step 2** — creates/replaces the procedure
3. Run `EXEC RUN_RECON_CODE_VALUES;` — smoke test that it works
4. Verify the results table has rows for the latest `BATCH_ID`
5. Run **Step 3.2** — schedule it
6. Run **Step 3.3** — confirm registration
7. (Optional) **Step 3.4** to force one scheduled-style run

---

## Notes

- **`BATCH_ID` is a single `SYSTIMESTAMP`** captured at the start of each run. Every row inserted by one run shares the same `BATCH_ID`, so `WHERE BATCH_ID = (SELECT MAX(BATCH_ID) ...)` reliably grabs "the latest run's results."
- **Exception handling:** any failure inside the procedure triggers `ROLLBACK` (so no partial rows are kept) followed by `RAISE`, which propagates to `DBMS_SCHEDULER` and marks that run as `FAILED` in `USER_SCHEDULER_JOB_RUN_DETAILS`.
- **Lag cutoff placement:** the `SYSDATE - 120/1440` filter is on `DT_CHG_GRD` on both sides of the join. If replication uses a different column for arrival time, that filter should move to whichever column represents "when this row landed."
- **Retention:** this design appends to the results table every run and never deletes. Over time it grows. If retention becomes an issue, add a periodic cleanup like `DELETE FROM RECON_RESULT_CODE_VALUES WHERE BATCH_ID < SYSTIMESTAMP - INTERVAL '30' DAY;` as its own scheduled job.
