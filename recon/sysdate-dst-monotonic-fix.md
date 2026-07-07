# SYSDATE, DST, and the Job Watermark Bug

## The Problem

The application used `SYSDATE` (or a formatted-timestamp-as-number) as a "last run" watermark, picking `MAX(timestamp)` to determine the next job cycle's starting point.

Oracle's `SYSDATE`:
- Returns a `DATE` (year/month/day/hour/minute/second only — **no time zone offset stored**).
- Reflects the **database server's OS clock**, not the Java application server's clock.
- Is evaluated entirely by Oracle when the SQL text `SYSDATE` is parsed — Java only sends the SQL text, it never computes the value itself.

### Why this breaks once a year

Every November, when the New York server's clock falls back (2:00 AM EDT → 1:00 AM EST), the **1:00–1:59 AM hour occurs twice**. Since `DATE` stores no offset, both occurrences produce **identical values** (e.g., `01:30:00`).

Consequences:
- `MAX(run_timestamp)` can pick the wrong row as "latest."
- Elapsed-time / duration math can go negative.
- `ORDER BY run_timestamp` can produce incorrect sequencing.
- Windowed queries (`WHERE event_time > lastRunTime`) can **silently skip records** that occurred during the second pass of the repeated hour.

This is a real, known limitation — not specific to how the Java code was written.

## The Fix: A Monotonic Sequence Column

Instead of trusting a clock reading to always increase, use an Oracle `SEQUENCE`, which Oracle guarantees is strictly increasing regardless of DST, NTP adjustments, or clock changes.

### SQL Setup

```sql
-- Sequence: starts at a 14-digit number, never cycles
CREATE SEQUENCE job_run_seq
  START WITH 10000000000000    -- smallest 14-digit number
  INCREMENT BY 1
  NOCACHE
  NOCYCLE
  MAXVALUE 99999999999999;     -- largest 14-digit number

-- Table
CREATE TABLE job_runs (
  id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_seq       NUMBER(14) NOT NULL,
  run_timestamp DATE DEFAULT SYSDATE NOT NULL
);

CREATE UNIQUE INDEX idx_job_runs_run_seq ON job_runs(run_seq);
```

**Range check:** `99999999999999 - 10000000000000 + 1 = 90,000,000,000,000` (90 trillion) possible values — effectively unlimited (~2.85 million years even at one run per second, continuously).

### Insert

```sql
INSERT INTO job_runs (run_seq, run_timestamp)
VALUES (job_run_seq.NEXTVAL, SYSDATE);
```

### Get the last run (watermark lookup)

```sql
SELECT run_seq, run_timestamp
FROM job_runs
WHERE run_seq = (SELECT MAX(run_seq) FROM job_runs);
```

## Java (Plain JDBC) Test Snippet

```java
import java.sql.*;

public class JobRunSequenceTest {

    private static final String URL  = "jdbc:oracle:thin:@//your-db-host:1521/your-service-name";
    private static final String USER = "your_user";
    private static final String PASS = "your_password";

    public static void main(String[] args) throws SQLException {
        try (Connection conn = DriverManager.getConnection(URL, USER, PASS)) {
            insertJobRun(conn);
            printLastRun(conn);
        }
    }

    private static void insertJobRun(Connection conn) throws SQLException {
        String sql = "INSERT INTO job_runs (run_seq, run_timestamp) " +
                     "VALUES (job_run_seq.NEXTVAL, SYSDATE)";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            int rows = ps.executeUpdate();
            System.out.println("Inserted rows: " + rows);
        }
    }

    private static void printLastRun(Connection conn) throws SQLException {
        String sql = "SELECT run_seq, run_timestamp " +
                     "FROM job_runs " +
                     "WHERE run_seq = (SELECT MAX(run_seq) FROM job_runs)";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            if (rs.next()) {
                long runSeq = rs.getLong("run_seq");
                Timestamp runTimestamp = rs.getTimestamp("run_timestamp");
                System.out.println("Last run_seq: " + runSeq);
                System.out.println("Last run_timestamp: " + runTimestamp);
            } else {
                System.out.println("No rows found.");
            }
        }
    }
}
```

## Quick SQL-Only Sanity Check

```sql
INSERT INTO job_runs (run_seq, run_timestamp) VALUES (job_run_seq.NEXTVAL, SYSDATE);
INSERT INTO job_runs (run_seq, run_timestamp) VALUES (job_run_seq.NEXTVAL, SYSDATE);
INSERT INTO job_runs (run_seq, run_timestamp) VALUES (job_run_seq.NEXTVAL, SYSDATE);

SELECT * FROM job_runs ORDER BY run_seq;
```

`run_seq` should increase by exactly 1 each time, regardless of what `run_timestamp` shows.

## Summary / Next Steps

| Item | Status |
|---|---|
| Root cause | `SYSDATE`/`DATE` has no time zone offset; ambiguous during Nov DST fall-back hour |
| Immediate fix | Add `run_seq` (Oracle `SEQUENCE`) as the authoritative "last run" watermark |
| Follow-up (optional) | Consider migrating `run_timestamp` to `TIMESTAMP WITH TIME ZONE` or storing UTC, to also protect the "process records since last run" windowing logic from the same DST edge case |
