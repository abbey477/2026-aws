# Job Watermark: File-Based Monotonic Counter (v1)

## Why `SYSDATE` / `DATE` Can't Be Used as the Watermark

`SYSDATE` returns a `DATE` value with **no time zone offset stored** — just year/month/day/hour/minute/second. Once a year, when the server's clock falls back for Daylight Saving Time (e.g., 2:00 AM EDT → 1:00 AM EST in New York), the **1:00–1:59 AM hour occurs twice**. Both occurrences produce identical `SYSDATE` values.

This breaks any logic that assumes time only moves forward:
- `MAX(run_timestamp)` can pick the wrong "last run."
- `WHERE event_time > lastRunTime` windowing can silently skip records processed during the second pass of the repeated hour.
- Elapsed-time math can go negative.

**Decision:** don't use `SYSDATE`/`DATE` for watermark/ordering logic at all. Use a value that has nothing to do with the clock.

## v1 Approach: File-Based Counter

A local file stores the last-used number. Each run reads it, increments it, and writes it back **atomically** (write to temp file, then rename) so a crash mid-write can't corrupt the counter.

- No dependency on Oracle privileges to create a `SEQUENCE` — usable immediately.
- Self-heals if the file is lost, by reseeding from `MAX(run_seq)` already stored in the database.
- `run_timestamp` (`SYSDATE`) is still stored, but treated as **display/audit only** — never used in comparison or ordering logic.

### Known limitations (why this is v1, not the final design)

| Risk | Impact |
|---|---|
| Multiple concurrent job instances | **Not safe** without extra locking — file-based counters assume a single writer at a time |
| File deleted/corrupted | Self-heals via DB reseed (see below), but only if the DB row history is intact |
| Job runs on a different server later | Counter file must exist on whichever machine executes the job, or must be reseeded |
| No automatic backup | Lives outside the database; not covered by DB backup/restore |

### Planned v2

Replace the file with a native Oracle `SEQUENCE` once `CREATE SEQUENCE` privileges are available — guarantees monotonic values at the database level, safe under concurrency, and requires no file management. See "v2: Oracle Sequence" section below.

---

## SQL: Table Setup

```sql
CREATE TABLE job_runs (
  id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_seq       NUMBER(14) NOT NULL,
  run_timestamp DATE DEFAULT SYSDATE NOT NULL  -- display/audit only, never used for comparisons
);

CREATE UNIQUE INDEX idx_job_runs_run_seq ON job_runs(run_seq);
```

## Java: File-Based Monotonic Counter

```java
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;

public class FileBasedRunCounter {

    private static final long START_VALUE = 10000000000000L; // 14-digit floor
    private final Path counterFile;
    private final Connection conn; // used only for reseed fallback

    public FileBasedRunCounter(Path counterFile, Connection conn) {
        this.counterFile = counterFile;
        this.conn = conn;
    }

    /**
     * Reads the last value (or reseeds from the DB if the file is missing),
     * increments it, persists the new value atomically, and returns it.
     */
    public synchronized long nextValue() throws IOException, SQLException {
        long current = readCurrent();
        long next = current + 1;
        writeAtomic(next);
        return next;
    }

    private long readCurrent() throws IOException, SQLException {
        if (Files.exists(counterFile)) {
            String content = Files.readString(counterFile, StandardCharsets.UTF_8).trim();
            if (!content.isEmpty()) {
                return Long.parseLong(content);
            }
        }
        // File missing or empty -> reseed from DB
        long reseeded = reseedFromDb();
        writeAtomic(reseeded); // persist immediately so the file exists going forward
        return reseeded;
    }

    private long reseedFromDb() throws SQLException {
        String sql = "SELECT MAX(run_seq) AS max_seq FROM job_runs";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            if (rs.next()) {
                long dbMax = rs.getLong("max_seq");
                if (!rs.wasNull() && dbMax > 0) {
                    return dbMax;
                }
            }
        }
        return START_VALUE - 1; // no rows yet -> fresh start (next value will be START_VALUE)
    }

    private void writeAtomic(long value) throws IOException {
        Path tempFile = counterFile.resolveSibling(counterFile.getFileName() + ".tmp");
        Files.writeString(tempFile, Long.toString(value), StandardCharsets.UTF_8);
        Files.move(tempFile, counterFile,
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE);
    }
}
```

## Java: Usage in the Job

```java
import java.nio.file.Paths;
import java.sql.*;

public class JobRunner {

    private static final String URL  = "jdbc:oracle:thin:@//your-db-host:1521/your-service-name";
    private static final String USER = "your_user";
    private static final String PASS = "your_password";

    public static void main(String[] args) throws Exception {
        try (Connection conn = DriverManager.getConnection(URL, USER, PASS)) {

            FileBasedRunCounter counter =
                new FileBasedRunCounter(Paths.get("job_run_counter.txt"), conn);

            long runSeq = counter.nextValue();

            String sql = "INSERT INTO job_runs (run_seq, run_timestamp) VALUES (?, SYSDATE)";
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                ps.setLong(1, runSeq);
                ps.executeUpdate();
            }

            System.out.println("This run's seq value: " + runSeq);

            // Get the last run's watermark for the next cycle:
            printLastRun(conn);
        }
    }

    private static void printLastRun(Connection conn) throws SQLException {
        String sql = "SELECT run_seq, run_timestamp " +
                     "FROM job_runs " +
                     "WHERE run_seq = (SELECT MAX(run_seq) FROM job_runs)";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            if (rs.next()) {
                System.out.println("Last run_seq: " + rs.getLong("run_seq"));
                System.out.println("Last run_timestamp (display only): " + rs.getTimestamp("run_timestamp"));
            }
        }
    }
}
```

## Quick Test

1. Run the SQL to create `job_runs`.
2. Run `JobRunner` a few times in a row (or loop the insert).
3. Confirm `run_seq` increases by exactly 1 each time — including if you delete `job_run_counter.txt` between runs (it should reseed from `MAX(run_seq)` in the table rather than restarting at the floor value).

---

## v2: Oracle Sequence (future migration)

Once `CREATE SEQUENCE` is available, replace the file counter with a native sequence — same table/column design, no file management, safe under concurrent job instances.

```sql
CREATE SEQUENCE job_run_seq
  START WITH 10000000000000
  INCREMENT BY 1
  NOCACHE
  NOCYCLE
  MAXVALUE 99999999999999;
```

```sql
INSERT INTO job_runs (run_seq, run_timestamp)
VALUES (job_run_seq.NEXTVAL, SYSDATE);
```

Migration note: seed the sequence to start above the current `MAX(run_seq)` from the file-based v1 data, so there's no collision:

```sql
SELECT MAX(run_seq) FROM job_runs; -- e.g. returns 10000000042
-- then create the sequence with START WITH 10000000043 (or higher)
```

## Summary

| | v1 (now) | v2 (later) |
|---|---|---|
| Source of monotonic value | Local file, self-heals from DB | Oracle `SEQUENCE` |
| Safe with concurrent job instances | No | Yes |
| Requires DB privileges to set up | No | Yes (`CREATE SEQUENCE`) |
| `run_timestamp` role | Display/audit only, never used for comparisons | Same |
