/* =====================================================================
   C vs R WINNER CHECK  -  8 queries (Oracle)
   ---------------------------------------------------------------------
   FROM_FG tells us which feed a row came from:
     C = Corporate        (primary feed)       -> schema CERD_CORPORATE
     R = Reconciliation   (gap-fill feed)      -> schema CERD_CORP_CR

   Decision: FROM_FG is DISPLAY ONLY. It does not change which row wins.
   The dedup rules pick the winner first; then we look at its FROM_FG.
     C wins = good
     R wins = needs attention

   Each table has 4 queries built on the same base:
     Base     - the dedup result only, no FROM_FG check
     Option A - every winning row + FG_CHECK (the schema name)
     Option B - only the winning rows where R won
     Option C - a count of winners per schema
   ===================================================================== */


/* =====================================================================
   TABLE 1: REFDBO.CERD_INSTRUMENT
   ---------------------------------------------------------------------
   Rules:
     - No filter: every row is considered.
     - Dedup: one row per instrument (ID_IMNT).
         * Latest LRI_EFF_UNTIL_DT wins.                      (spec)
         * If tied, newest LRI_EFF_ASOF_DT wins.              (added tie-breaker)
   ===================================================================== */

-- ---------------------------------------------------------------------
-- 1.0 CERD_INSTRUMENT - base dedup only (no FROM_FG check)
-- ---------------------------------------------------------------------
WITH ranked AS (
    -- Step 1: number each instrument's rows, best row = 1
    SELECT i.*,
           ROW_NUMBER() OVER (
               PARTITION BY i.id_imnt                -- one pile per instrument
               ORDER BY i.lri_eff_until_dt DESC,     -- latest until-date first (spec)
                        i.lri_eff_asof_dt  DESC      -- tie-breaker: newest as-of date
           ) AS rn
    FROM refdbo.cerd_instrument i
)
-- Step 2: keep only row 1 of each pile (the winner)
SELECT id_imnt, nm_imnt, dt_expy_imnt, status, tx_imnt, id_typ_imnt,
       cpn_type, is_perpetual, dt_issue, id_ccy_issue, id_ctry_issuer,
       id_brady, id_mult_ccy, id_reg144a, id_regs, is_sinkable,
       is_convertible, id_issuer, is_index, rt_cpn, dt_default,
       from_fg, lri_eff_asof_dt, lri_eff_until_dt
FROM ranked
WHERE rn = 1;


-- ---------------------------------------------------------------------
-- 1A. CERD_INSTRUMENT - all winners with FG_CHECK
-- ---------------------------------------------------------------------
WITH ranked AS (
    -- Step 1: number each instrument's rows, best row = 1
    SELECT i.*,
           ROW_NUMBER() OVER (
               PARTITION BY i.id_imnt                -- one pile per instrument
               ORDER BY i.lri_eff_until_dt DESC,     -- latest until-date first (spec)
                        i.lri_eff_asof_dt  DESC      -- tie-breaker: newest as-of date
           ) AS rn
    FROM refdbo.cerd_instrument i
),
winners AS (
    -- Step 2: keep only row 1 of each pile (the winner)
    SELECT id_imnt, nm_imnt, dt_expy_imnt, status, tx_imnt, id_typ_imnt,
           cpn_type, is_perpetual, dt_issue, id_ccy_issue, id_ctry_issuer,
           id_brady, id_mult_ccy, id_reg144a, id_regs, is_sinkable,
           is_convertible, id_issuer, is_index, rt_cpn, dt_default,
           from_fg, lri_eff_asof_dt, lri_eff_until_dt
    FROM ranked
    WHERE rn = 1
)
-- Step 3: show every winner and the schema its row came from
SELECT w.*,
       CASE w.from_fg
            WHEN 'C' THEN 'CERD_CORPORATE'
            WHEN 'R' THEN 'CERD_CORP_CR'
       END AS fg_check
FROM winners w
ORDER BY w.id_imnt;


-- ---------------------------------------------------------------------
-- 1B. CERD_INSTRUMENT - only instruments where R won
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT i.*,
           ROW_NUMBER() OVER (
               PARTITION BY i.id_imnt
               ORDER BY i.lri_eff_until_dt DESC,
                        i.lri_eff_asof_dt  DESC
           ) AS rn
    FROM refdbo.cerd_instrument i
),
winners AS (
    SELECT id_imnt, nm_imnt, dt_expy_imnt, status, tx_imnt, id_typ_imnt,
           cpn_type, is_perpetual, dt_issue, id_ccy_issue, id_ctry_issuer,
           id_brady, id_mult_ccy, id_reg144a, id_regs, is_sinkable,
           is_convertible, id_issuer, is_index, rt_cpn, dt_default,
           from_fg, lri_eff_asof_dt, lri_eff_until_dt
    FROM ranked
    WHERE rn = 1
)
-- Filter AFTER the winner is picked: only winners from the R feed
SELECT w.*
FROM winners w
WHERE w.from_fg = 'R'
ORDER BY w.id_imnt;


-- ---------------------------------------------------------------------
-- 1C. CERD_INSTRUMENT - count of winners per schema
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT i.id_imnt,
           i.from_fg,
           ROW_NUMBER() OVER (
               PARTITION BY i.id_imnt
               ORDER BY i.lri_eff_until_dt DESC,
                        i.lri_eff_asof_dt  DESC
           ) AS rn
    FROM refdbo.cerd_instrument i
)
SELECT from_fg,
       CASE from_fg
            WHEN 'C' THEN 'CERD_CORPORATE'
            WHEN 'R' THEN 'CERD_CORP_CR'
       END      AS fg_check,
       COUNT(*) AS records
FROM ranked
WHERE rn = 1                     -- count winners only
GROUP BY from_fg
ORDER BY from_fg;


/* =====================================================================
   TABLE 2: REFDBO.CERD_EXCHANGE_IMNT_ALT_ID
   ---------------------------------------------------------------------
   Rules (filters run first, then the dedup):
     Rule 1 - ID_TYP_ALT_IMNT IN ('P','N','I','S','Z','C')
              keep only CUSIP, VALOR, ISIN, SEDOL, Common, CERD codes
     Rule 2 - ID_VIEW_FLAG = 'Y'
              keep only rows switched on
     Rule 3 - LENGTH(ID_IMNT_ALT) <= 25
              drop codes too long for the target column
     Rule 4 - LRI_EFF_UNTIL_DT = 9999-12-31
              keep only current rows (history rows are dropped)
     Rule 5 - Dedup: one row per code (type + value)
         * Smallest ID_IMNT wins.                             (spec)
         * If tied, smallest ID_EXCH wins.                    (added tie-breaker)
         * If still tied, newest LRI_EFF_ASOF_DT wins.        (added tie-breaker)
   ===================================================================== */

-- ---------------------------------------------------------------------
-- 2.0 CERD_EXCHANGE_IMNT_ALT_ID - base dedup only (no FROM_FG check)
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT a.*,
           ROW_NUMBER() OVER (
               PARTITION BY a.id_typ_alt_imnt, a.id_imnt_alt   -- Rule 5: one pile per code
               ORDER BY a.id_imnt,                             -- smallest instrument first (spec)
                        a.id_exch,                             -- tie-breaker: smallest exchange
                        a.lri_eff_asof_dt DESC                 -- tie-breaker: newest as-of date
           ) AS rn
    FROM refdbo.cerd_exchange_imnt_alt_id a
    WHERE a.id_typ_alt_imnt IN ('P','N','I','S','Z','C')       -- Rule 1: allowed code types
      AND a.id_view_flag = 'Y'                                 -- Rule 2: switched on
      AND LENGTH(a.id_imnt_alt) <= 25                          -- Rule 3: fits in 25 chars
      AND a.lri_eff_until_dt = DATE '9999-12-31'               -- Rule 4: current rows only
)
SELECT id_imnt, id_typ_alt_imnt, id_exchange_key, id_imnt_alt, id_exch,
       id_view_flag, from_fg, lri_eff_asof_dt, lri_eff_until_dt
FROM ranked
WHERE rn = 1;                                                  -- keep the winner of each pile


-- ---------------------------------------------------------------------
-- 2A. CERD_EXCHANGE_IMNT_ALT_ID - all winners with FG_CHECK
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT a.*,
           ROW_NUMBER() OVER (
               PARTITION BY a.id_typ_alt_imnt, a.id_imnt_alt   -- Rule 5: one pile per code
               ORDER BY a.id_imnt,                             -- smallest instrument first (spec)
                        a.id_exch,                             -- tie-breaker: smallest exchange
                        a.lri_eff_asof_dt DESC                 -- tie-breaker: newest as-of date
           ) AS rn
    FROM refdbo.cerd_exchange_imnt_alt_id a
    WHERE a.id_typ_alt_imnt IN ('P','N','I','S','Z','C')       -- Rule 1: allowed code types
      AND a.id_view_flag = 'Y'                                 -- Rule 2: switched on
      AND LENGTH(a.id_imnt_alt) <= 25                          -- Rule 3: fits in 25 chars
      AND a.lri_eff_until_dt = DATE '9999-12-31'               -- Rule 4: current rows only
),
winners AS (
    SELECT id_imnt, id_typ_alt_imnt, id_exchange_key, id_imnt_alt, id_exch,
           id_view_flag, from_fg, lri_eff_asof_dt, lri_eff_until_dt
    FROM ranked
    WHERE rn = 1                                               -- keep the winner of each pile
)
SELECT w.*,
       CASE w.from_fg
            WHEN 'C' THEN 'CERD_CORPORATE'
            WHEN 'R' THEN 'CERD_CORP_CR'
       END AS fg_check
FROM winners w
ORDER BY w.id_imnt, w.id_typ_alt_imnt, w.id_imnt_alt;


-- ---------------------------------------------------------------------
-- 2B. CERD_EXCHANGE_IMNT_ALT_ID - only codes where R won
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT a.*,
           ROW_NUMBER() OVER (
               PARTITION BY a.id_typ_alt_imnt, a.id_imnt_alt
               ORDER BY a.id_imnt,
                        a.id_exch,
                        a.lri_eff_asof_dt DESC
           ) AS rn
    FROM refdbo.cerd_exchange_imnt_alt_id a
    WHERE a.id_typ_alt_imnt IN ('P','N','I','S','Z','C')
      AND a.id_view_flag = 'Y'
      AND LENGTH(a.id_imnt_alt) <= 25
      AND a.lri_eff_until_dt = DATE '9999-12-31'
),
winners AS (
    SELECT id_imnt, id_typ_alt_imnt, id_exchange_key, id_imnt_alt, id_exch,
           id_view_flag, from_fg, lri_eff_asof_dt, lri_eff_until_dt
    FROM ranked
    WHERE rn = 1
)
-- Filter AFTER the winner is picked: only winners from the R feed
SELECT w.*
FROM winners w
WHERE w.from_fg = 'R'
ORDER BY w.id_imnt, w.id_typ_alt_imnt, w.id_imnt_alt;


-- ---------------------------------------------------------------------
-- 2C. CERD_EXCHANGE_IMNT_ALT_ID - count of winners per schema
-- ---------------------------------------------------------------------
WITH ranked AS (
    SELECT a.from_fg,
           ROW_NUMBER() OVER (
               PARTITION BY a.id_typ_alt_imnt, a.id_imnt_alt
               ORDER BY a.id_imnt,
                        a.id_exch,
                        a.lri_eff_asof_dt DESC
           ) AS rn
    FROM refdbo.cerd_exchange_imnt_alt_id a
    WHERE a.id_typ_alt_imnt IN ('P','N','I','S','Z','C')
      AND a.id_view_flag = 'Y'
      AND LENGTH(a.id_imnt_alt) <= 25
      AND a.lri_eff_until_dt = DATE '9999-12-31'
)
SELECT from_fg,
       CASE from_fg
            WHEN 'C' THEN 'CERD_CORPORATE'
            WHEN 'R' THEN 'CERD_CORP_CR'
       END      AS fg_check,
       COUNT(*) AS codes
FROM ranked
WHERE rn = 1                     -- count winners only
GROUP BY from_fg
ORDER BY from_fg;
