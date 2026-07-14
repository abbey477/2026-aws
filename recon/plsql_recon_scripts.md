# PL/SQL Recon Scripts — CODE_VALUES Table Pair

Reference notes and working scripts for comparing `CERD_CORPORATE.CODE_VALUES` (source) against `REFDBO.CODE_VALUES` (destination) using a row-hash comparison technique. Use these as templates for the remaining 7 table pairs.

---

## How the Recon Logic Works

1. **Fingerprint every row** in the source table by concatenating its important columns into one string and hashing it with `ORA_HASH`.
2. **Fingerprint every row** in the destination table the same way.
3. **Join** the two fingerprint sets on the business key (`ID_TYP_CODE`, `ID_CODE`) using a `FULL OUTER JOIN`, so rows missing on either side are also captured — not just rows that exist in both.
4. **Count** the outcomes:
   - `MATCH_COUNT` — row exists in both, hashes are identical
   - `MISMATCH_COUNT` — row exists in both, but hashes differ (something changed)
   - `MISSING_IN_DEST_COUNT` — row exists in source, but not in destination
   - `MISSING_IN_SOURCE_COUNT` — row exists in destination, but not in source

---

## Key Concepts / Notes

| Concept | Notes |
|---|---|
| `TRUNC(SYSDATE)` | Returns today's date at midnight (00:00:00). Used as the lower bound of the "today's changes" filter. |
| `SYSDATE - 120/1440` | Subtracts 120 minutes (2 hours) from the current time. `1440` = minutes in a day, so `minutes/1440` converts minutes into a fraction of a day for date arithmetic. |
| ⚠️ Known quirk | Between midnight and 2 AM, `SYSDATE - 120/1440` still points to *yesterday*, while `TRUNC(SYSDATE)` points to *today*. This makes the date range logically impossible for the first 2 hours of each day, so the query silently returns **zero rows** during that window. Worth confirming this script isn't scheduled to run in that window, or the dead zone should be fixed. |
| `NVL(column, '~')` | "If `column` is `NULL`, use `'~'` instead." Prevents `NULL` values from breaking the hash or the join. `COALESCE` does the same thing and works with more than 2 arguments, but `NVL` is simpler for this use case (always exactly 2 arguments). |
| `ORA_HASH(...)` | Turns a concatenated string into a single number — a fast "fingerprint" for comparing many columns at once instead of comparing them one by one. |
| `FULL OUTER JOIN` with `NVL(...) = NVL(...)` | Makes the join **NULL-safe** — without this, two `NULL` values on the join key would never match (`NULL = NULL` is `NULL`, not `TRUE`, in SQL), causing false "missing" results. |
| `LRI_EFF_UNTIL_DT = DATE '9999-12-31'` | A common "end of time" sentinel value meaning "this record is currently active / has no expiry." Filters destination rows down to only currently-effective records. |
| `WITH cc AS (...), rd AS (...)` | A CTE (Common Table Expression) — lets you name a subquery once and reference it later, instead of repeating or nesting it inline. Improves readability for two-source comparisons like this. |
| `COUNT(CASE WHEN condition THEN 1 END)` | A pattern for getting multiple different counts from one query — counts a row as `1` only if the condition is true, otherwise counts nothing. |
| `SELECT ... INTO v_variable` | PL/SQL syntax for storing a query result into a variable, instead of returning it as rows. Required inside a `BEGIN...END` block. |
| `EXCEPTION WHEN OTHERS THEN ROLLBACK; ...` | Safety net — if anything fails mid-script, undo any partial changes and print the actual error instead of crashing silently. |
| `DBMS_OUTPUT.PUT_LINE(...)` | Prints text to the console. Must have **DBMS Output enabled** in Toad (bottom tab) or nothing will show. |

---

## Script 1 — Display Only

Calculates and prints the recon result. **Nothing is saved.** Use this first to sanity-check numbers before logging a run.

```sql
--------------------------------------------------------------------------
-- SCRIPT 1: DISPLAY ONLY
-- Compares CERD_CORPORATE.CODE_VALUES (source)
--      vs. REFDBO.CODE_VALUES (destination)
-- Prints the result to screen — does NOT save anything
--------------------------------------------------------------------------

DECLARE
    v_match_count             NUMBER;
    v_mismatch_count          NUMBER;
    v_missing_in_dest_count   NUMBER;
    v_missing_in_source_count NUMBER;

BEGIN

    ----------------------------------------------------------------------
    -- STEP 1: Define cc (source) and rd (destination) fingerprints
    ----------------------------------------------------------------------
    WITH cc AS (
        SELECT
            ID_TYP_CODE, ID_CODE,
            ORA_HASH(
                TX_CODE                              || '|' ||
                NVL(ID_TYP_CODE_GBL, '~')            || '|' ||
                NVL(ID_CODE_MAX, '~')                || '|' ||
                NVL(TO_CHAR(ID_CODE_VAL), '~')       || '|' ||
                TO_CHAR(DT_CHG_GRD,'YYYYMMDDHH24MISS') || '|' ||
                ID_DEL_GRD                           || '|' ||
                TO_CHAR(ID_OWN_GRD)
            ) AS row_hash
        FROM CERD_CORPORATE.CODE_VALUES
        WHERE DT_CHG_GRD >= TRUNC(SYSDATE)
        AND   DT_CHG_GRD <= SYSDATE - 120/1440
    ),
    rd AS (
        SELECT
            ID_TYP_CODE, ID_CODE,
            ORA_HASH(
                TX_CODE                              || '|' ||
                NVL(ID_TYP_CODE_GBL, '~')            || '|' ||
                NVL(ID_CODE_MAX, '~')                || '|' ||
                NVL(TO_CHAR(ID_CODE_VAL), '~')       || '|' ||
                TO_CHAR(DT_CHG_GRD,'YYYYMMDDHH24MISS') || '|' ||
                ID_DEL_GRD                           || '|' ||
                TO_CHAR(ID_OWN_GRD)
            ) AS row_hash
        FROM REFDBO.CODE_VALUES
        WHERE DT_CHG_GRD >= TRUNC(SYSDATE)
        AND   DT_CHG_GRD <= SYSDATE - 120/1440
        AND   LRI_EFF_UNTIL_DT = DATE '9999-12-31'
    )

    ----------------------------------------------------------------------
    -- STEP 2: Compare cc and rd, count the outcomes into variables
    ----------------------------------------------------------------------
    SELECT
        COUNT(CASE WHEN cc.row_hash = rd.row_hash THEN 1 END),

        COUNT(CASE
                WHEN cc.ID_TYP_CODE IS NOT NULL
                 AND rd.ID_TYP_CODE IS NOT NULL
                 AND cc.row_hash <> rd.row_hash
                THEN 1 END),

        COUNT(CASE WHEN rd.ID_TYP_CODE IS NULL THEN 1 END),

        COUNT(CASE WHEN cc.ID_TYP_CODE IS NULL THEN 1 END)

    INTO
        v_match_count,
        v_mismatch_count,
        v_missing_in_dest_count,
        v_missing_in_source_count

    FROM cc
    FULL OUTER JOIN rd
        ON  NVL(cc.ID_TYP_CODE, '~') = NVL(rd.ID_TYP_CODE, '~')
        AND NVL(cc.ID_CODE, '~')     = NVL(rd.ID_CODE, '~');

    ----------------------------------------------------------------------
    -- STEP 3: Print the result — nothing is saved
    ----------------------------------------------------------------------
    DBMS_OUTPUT.PUT_LINE('--- Recon Result: CODE_VALUES ---');
    DBMS_OUTPUT.PUT_LINE('Matches: '            || v_match_count);
    DBMS_OUTPUT.PUT_LINE('Mismatches: '         || v_mismatch_count);
    DBMS_OUTPUT.PUT_LINE('Missing in Dest: '    || v_missing_in_dest_count);
    DBMS_OUTPUT.PUT_LINE('Missing in Source: '  || v_missing_in_source_count);

END;
/
```

---

## Script 2 — Write to Table

Same calculation as Script 1, but saves the result as one row into `RECON_SUMMARY` instead of just printing it.

### Table Definition (create once)

```sql
CREATE TABLE RECON_SUMMARY (
    RUN_DATE       TIMESTAMP  DEFAULT SYSTIMESTAMP,
    SOURCE_TABLE   VARCHAR2(100)   NOT NULL,
    DEST_TABLE     VARCHAR2(100)   NOT NULL,
    MATCH_COUNT    NUMBER,
    MISMATCH_COUNT NUMBER,
    MISSING_IN_DEST_COUNT   NUMBER,
    MISSING_IN_SOURCE_COUNT NUMBER
);
```

- `RUN_DATE` uses `TIMESTAMP` (not `DATE`) for fractional-second precision — avoids collisions if multiple recon runs happen within the same second (e.g. scripting all 8 pairs in a loop).
- No sequence/primary key — kept intentionally simple. Every run just adds a new row, building a history over time.

### Script

```sql
--------------------------------------------------------------------------
-- SCRIPT 2: WRITE TO TABLE
-- Compares CERD_CORPORATE.CODE_VALUES (source)
--      vs. REFDBO.CODE_VALUES (destination)
-- Saves the result into RECON_SUMMARY
--------------------------------------------------------------------------

DECLARE
    v_match_count             NUMBER;
    v_mismatch_count          NUMBER;
    v_missing_in_dest_count   NUMBER;
    v_missing_in_source_count NUMBER;

BEGIN

    ----------------------------------------------------------------------
    -- STEP 1: Define cc (source) and rd (destination) fingerprints
    ----------------------------------------------------------------------
    WITH cc AS (
        SELECT
            ID_TYP_CODE, ID_CODE,
            ORA_HASH(
                TX_CODE                              || '|' ||
                NVL(ID_TYP_CODE_GBL, '~')            || '|' ||
                NVL(ID_CODE_MAX, '~')                || '|' ||
                NVL(TO_CHAR(ID_CODE_VAL), '~')       || '|' ||
                TO_CHAR(DT_CHG_GRD,'YYYYMMDDHH24MISS') || '|' ||
                ID_DEL_GRD                           || '|' ||
                TO_CHAR(ID_OWN_GRD)
            ) AS row_hash
        FROM CERD_CORPORATE.CODE_VALUES
        WHERE DT_CHG_GRD >= TRUNC(SYSDATE)
        AND   DT_CHG_GRD <= SYSDATE - 120/1440
    ),
    rd AS (
        SELECT
            ID_TYP_CODE, ID_CODE,
            ORA_HASH(
                TX_CODE                              || '|' ||
                NVL(ID_TYP_CODE_GBL, '~')            || '|' ||
                NVL(ID_CODE_MAX, '~')                || '|' ||
                NVL(TO_CHAR(ID_CODE_VAL), '~')       || '|' ||
                TO_CHAR(DT_CHG_GRD,'YYYYMMDDHH24MISS') || '|' ||
                ID_DEL_GRD                           || '|' ||
                TO_CHAR(ID_OWN_GRD)
            ) AS row_hash
        FROM REFDBO.CODE_VALUES
        WHERE DT_CHG_GRD >= TRUNC(SYSDATE)
        AND   DT_CHG_GRD <= SYSDATE - 120/1440
        AND   LRI_EFF_UNTIL_DT = DATE '9999-12-31'
    )

    ----------------------------------------------------------------------
    -- STEP 2: Compare cc and rd, count the outcomes into variables
    ----------------------------------------------------------------------
    SELECT
        COUNT(CASE WHEN cc.row_hash = rd.row_hash THEN 1 END),

        COUNT(CASE
                WHEN cc.ID_TYP_CODE IS NOT NULL
                 AND rd.ID_TYP_CODE IS NOT NULL
                 AND cc.row_hash <> rd.row_hash
                THEN 1 END),

        COUNT(CASE WHEN rd.ID_TYP_CODE IS NULL THEN 1 END),

        COUNT(CASE WHEN cc.ID_TYP_CODE IS NULL THEN 1 END)

    INTO
        v_match_count,
        v_mismatch_count,
        v_missing_in_dest_count,
        v_missing_in_source_count

    FROM cc
    FULL OUTER JOIN rd
        ON  NVL(cc.ID_TYP_CODE, '~') = NVL(rd.ID_TYP_CODE, '~')
        AND NVL(cc.ID_CODE, '~')     = NVL(rd.ID_CODE, '~');

    ----------------------------------------------------------------------
    -- STEP 3: Save the result into RECON_SUMMARY
    ----------------------------------------------------------------------
    INSERT INTO RECON_SUMMARY (
        SOURCE_TABLE,
        DEST_TABLE,
        MATCH_COUNT,
        MISMATCH_COUNT,
        MISSING_IN_DEST_COUNT,
        MISSING_IN_SOURCE_COUNT
    )
    VALUES (
        'CERD_CORPORATE.CODE_VALUES',
        'REFDBO.CODE_VALUES',
        v_match_count,
        v_mismatch_count,
        v_missing_in_dest_count,
        v_missing_in_source_count
    );

    COMMIT;

    DBMS_OUTPUT.PUT_LINE('Saved to RECON_SUMMARY successfully.');

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        DBMS_OUTPUT.PUT_LINE('Recon FAILED: ' || SQLERRM);

END;
/
```

---

## Sample `RECON_SUMMARY` Output

| RUN_DATE | SOURCE_TABLE | DEST_TABLE | MATCH_COUNT | MISMATCH_COUNT | MISSING_IN_DEST_COUNT | MISSING_IN_SOURCE_COUNT |
|---|---|---|---|---|---|---|
| 13-JUL-26 14.52.10.384291 | CERD_CORPORATE.CODE_VALUES | REFDBO.CODE_VALUES | 1520 | 3 | 1 | 0 |
| 13-JUL-26 14.53.42.912004 | CERD_CORPORATE.CUSTOMER_MASTER | REFDBO.CUSTOMER_MASTER | 8420 | 0 | 0 | 2 |
| 14-JUL-26 09.10.33.556012 | CERD_CORPORATE.CODE_VALUES | REFDBO.CODE_VALUES | 1518 | 1 | 0 | 0 |

Because every run is timestamped and appended (never overwritten), this table doubles as a **history log** — useful for spotting whether mismatches are trending up or down over time for a given pair.

---

## Reusing These Scripts for the Other 7 Table Pairs

Both scripts follow a copy-and-swap pattern. For each new pair, only these need to change:

1. The two `FROM` table names inside the `cc` and `rd` CTEs (Step 1)
2. The two string literals in Script 2's `INSERT ... VALUES (...)` (Step 3)

Everything else — the hash logic, `NVL` handling, `FULL OUTER JOIN`, and counting — stays the same, since it's the same recon pattern applied to different source/destination tables.

**Suggested workflow per pair:**
1. Run **Script 1** first to sanity-check the numbers for that pair.
2. Once satisfied, run **Script 2** to log the official result into `RECON_SUMMARY`.

---

## PL/SQL Quick Reference (from this session)

| Java-ish concept | PL/SQL equivalent |
|---|---|
| `System.out.println()` | `DBMS_OUTPUT.PUT_LINE()` |
| `if / else` | `IF ... THEN ... ELSE ... END IF;` |
| local variable | `v_x NUMBER := 5;` |
| try/catch | `EXCEPTION WHEN ... THEN` |
| String | `VARCHAR2` |
| Date/time | `DATE` (second precision) or `TIMESTAMP` (fractional-second precision) |
