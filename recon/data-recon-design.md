# Data Reconciliation Design
## Schema A vs Schema B — Oracle

---

## Overview

Schema A is the **source of truth** (Priority 1).  
Schema B data must be validated against Schema A (Priority 2).

---

## Sample Tables

### schemaA.employees

| emp_id | dept | salary | location |
|--------|------|--------|----------|
| E001   | HR   | 50000  | LONDON   |
| E002   | IT   | 60000  | PARIS    |
| E003   | IT   | 55000  | NULL     |
| E004   | HR   | 52000  | BERLIN   |
| E005   | NULL | 48000  | ROME     |
| E006   | FIN  | 70000  | MADRID   |

### schemaB.employees

| emp_id | dept | salary | location  |
|--------|------|--------|-----------|
| E001   | HR   | 50000  | LONDON    |
| E002   | IT   | 65000  | PARIS     |
| E003   | IT   | 55000  | NULL      |
| E004   | HR   | 52000  | AMSTERDAM |
| E005   | NULL | 48000  | ROME      |
| E007   | OPS  | 45000  | OSLO      |

**Unique key columns:** `emp_id`, `dept`  
**Value columns:** `salary`, `location`

---

## Null Handling

All null values are replaced with `'__NULL__'` before comparison using `COALESCE`.

```sql
COALESCE(column_name, '__NULL__')
```

This ensures:
- NULL in A and NULL in B → MATCH
- NULL in A and value in B → MISMATCH
- Value in A and NULL in B → MISMATCH

---

## Approach 1 — MD5 Hash Compare

### Purpose
Fast overall picture. One row per employee. Tells you MATCH or MISMATCH but not which column differs.

### Query

```sql
WITH hash_a AS (
    SELECT
        emp_id,
        dept,
        MD5(
            COALESCE(emp_id,   '__NULL__') || '|' ||
            COALESCE(dept,     '__NULL__') || '|' ||
            COALESCE(salary,   '__NULL__') || '|' ||
            COALESCE(location, '__NULL__')
        ) AS row_hash
    FROM schemaA.employees
),
hash_b AS (
    SELECT
        emp_id,
        dept,
        MD5(
            COALESCE(emp_id,   '__NULL__') || '|' ||
            COALESCE(dept,     '__NULL__') || '|' ||
            COALESCE(salary,   '__NULL__') || '|' ||
            COALESCE(location, '__NULL__')
        ) AS row_hash
    FROM schemaB.employees
)
SELECT
    COALESCE(a.emp_id, b.emp_id)    AS emp_id,
    COALESCE(a.dept,   b.dept)      AS dept,
    a.row_hash                      AS hash_a,
    b.row_hash                      AS hash_b,
    CASE
        WHEN a.row_hash IS NULL          THEN 'ROGUE IN B'
        WHEN b.row_hash IS NULL          THEN 'MISSING IN B'
        WHEN a.row_hash = b.row_hash     THEN 'MATCH'
        ELSE                                  'MISMATCH'
    END                             AS status
FROM hash_a a
FULL OUTER JOIN hash_b b
    ON  a.emp_id = b.emp_id
    AND a.dept   = b.dept
ORDER BY status
```

### Sample Result

| emp_id | dept | hash_a     | hash_b     | status       |
|--------|------|------------|------------|--------------|
| E001   | HR   | a7f3c9d1.. | a7f3c9d1.. | MATCH        |
| E003   | IT   | b2e4f1a8.. | b2e4f1a8.. | MATCH        |
| E005   | NULL | c9d2e3b7.. | c9d2e3b7.. | MATCH        |
| E002   | IT   | d4a1f9c2.. | e8b3d2f1.. | MISMATCH     |
| E004   | HR   | f1c8e2a4.. | a3d7b9e1.. | MISMATCH     |
| E006   | FIN  | e2b7d4c9.. | NULL       | MISSING IN B |
| E007   | OPS  | NULL       | f9a2c1d8.. | ROGUE IN B   |

### Summary

| status       | count |
|--------------|-------|
| MATCH        | 3     |
| MISMATCH     | 2     |
| MISSING IN B | 1     |
| ROGUE IN B   | 1     |

---

## Approach 2 — Column Compare

### Purpose
Full troubleshooting detail. One row per employee showing every column value and status side by side. Tells you exactly which column differs.

### Query

```sql
SELECT
    COALESCE(a.emp_id, b.emp_id)    AS emp_id,
    CASE
        WHEN a.emp_id IS NULL        THEN 'ROGUE IN B'
        WHEN b.emp_id IS NULL        THEN 'MISSING IN B'
        ELSE                              'MATCH'
    END                             AS emp_id_status,

    COALESCE(a.dept, b.dept)        AS dept,
    CASE
        WHEN a.dept IS NULL          THEN 'ROGUE IN B'
        WHEN b.dept IS NULL          THEN 'MISSING IN B'
        ELSE                              'MATCH'
    END                             AS dept_status,

    a.salary                        AS salary_a,
    b.salary                        AS salary_b,
    CASE
        WHEN a.emp_id IS NULL                          THEN 'ROGUE IN B'
        WHEN b.emp_id IS NULL                          THEN 'MISSING IN B'
        WHEN COALESCE(a.salary,  '__NULL__')
           = COALESCE(b.salary,  '__NULL__')           THEN 'MATCH'
        ELSE                                                'MISMATCH'
    END                             AS salary_status,

    a.location                      AS location_a,
    b.location                      AS location_b,
    CASE
        WHEN a.emp_id IS NULL                          THEN 'ROGUE IN B'
        WHEN b.emp_id IS NULL                          THEN 'MISSING IN B'
        WHEN COALESCE(a.location, '__NULL__')
           = COALESCE(b.location, '__NULL__')          THEN 'MATCH'
        ELSE                                                'MISMATCH'
    END                             AS location_status

FROM schemaA.employees a
FULL OUTER JOIN schemaB.employees b
    ON  a.emp_id = b.emp_id
    AND a.dept   = b.dept
ORDER BY emp_id
```

### Sample Result

| emp_id | emp_id_status | dept | dept_status  | salary_a | salary_b | salary_status | location_a | location_b | location_status |
|--------|---------------|------|--------------|----------|----------|---------------|------------|------------|-----------------|
| E001   | MATCH         | HR   | MATCH        | 50000    | 50000    | MATCH         | LONDON     | LONDON     | MATCH           |
| E002   | MATCH         | IT   | MATCH        | 60000    | 65000    | MISMATCH      | PARIS      | PARIS      | MATCH           |
| E003   | MATCH         | IT   | MATCH        | 55000    | 55000    | MATCH         | NULL       | NULL       | MATCH           |
| E004   | MATCH         | HR   | MATCH        | 52000    | 52000    | MATCH         | BERLIN     | AMSTERDAM  | MISMATCH        |
| E005   | MATCH         | NULL | MATCH        | 48000    | 48000    | MATCH         | ROME       | ROME       | MATCH           |
| E006   | MISSING IN B  | FIN  | MISSING IN B | 70000    | NULL     | MISSING IN B  | MADRID     | NULL       | MISSING IN B    |
| E007   | ROGUE IN B    | OPS  | ROGUE IN B   | NULL     | 45000    | ROGUE IN B    | NULL       | OSLO       | ROGUE IN B      |

---

## Status Definitions

| status       | meaning                                      | priority   |
|--------------|----------------------------------------------|------------|
| MATCH        | row and value identical in both schemas      | —          |
| MISMATCH     | row exists in both but column value differs  | investigate|
| MISSING IN B | row exists in A but not in B                 | Priority 1 |
| ROGUE IN B   | row exists in B but not in A                 | Priority 2 |

---

## How The Two Approaches Work Together

```
Approach 1  →  run on all rows
               quick summary
               how many match, mismatch, missing, rogue

Approach 2  →  run on all rows
               full column detail
               exactly which column differs per row

Both run independently on full table.
Results compared for confidence.

If Approach 1 shows 2 mismatches
and Approach 2 also shows 2 mismatches
→ high confidence in results
```

---

## Design Decisions

| decision                  | choice                          | reason                            |
|---------------------------|---------------------------------|-----------------------------------|
| null handling             | COALESCE with `'__NULL__'`      | consistent null comparison        |
| row identity              | concatenate all columns with `\|` | no primary key available          |
| join type                 | FULL OUTER JOIN                 | captures missing and rogue rows   |
| key columns               | emp_id, dept                    | unique index columns              |
| processing                | one table at a time             | isolation, progress visibility    |
| schema A                  | source of truth                 | priority 1                        |

---

*Next step: Java reads ResultSet and produces final report per table.*
