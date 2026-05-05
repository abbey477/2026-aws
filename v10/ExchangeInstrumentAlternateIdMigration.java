import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

/**
 * Streaming migration for ExchangeInstrumentAlternateId (Sybase -> Oracle).
 *
 * <p>Replaces the previous "load entire ResultSet into a List" pattern with a
 * streaming read + buffered batch write. Memory stays bounded at ~BATCH_SIZE
 * rows instead of holding all 1M+ rows in a List.
 *
 * <p>Two mapping variants are provided so the team can A/B them on the same
 * data and pick based on accuracy and measured performance:
 * <ul>
 *   <li>{@link #migrateByIndex()} — reads ResultSet columns positionally
 *       ({@code rs.getString(2)}). Faster, but the SELECT column order must
 *       match the mapper.</li>
 *   <li>{@link #migrateByName()} — reads ResultSet columns by name
 *       ({@code rs.getString("ID_TYP_ALT_IMNT")}). More readable and robust
 *       to SELECT reordering, but incurs a per-cell name lookup.</li>
 * </ul>
 * Both variants share {@link #flush(MigrationStats, List, String, ColumnMapper)}
 * and produce identical Oracle output.
 *
 * <p>Logging:
 * <ul>
 *   <li>INFO — start/end of each table migration with totals (rows, batches,
 *       wall time, throughput rows/sec).</li>
 *   <li>DEBUG — per-batch completion (batch number, size, elapsed ms, rolling
 *       row count). Switch the logger to DEBUG when investigating slowdowns.</li>
 * </ul>
 */
@Slf4j
public class ExchangeInstrumentAlternateIdMigration {

    private static final int FETCH_SIZE = 2000;   // jconn4 rows-per-round-trip
    private static final int BATCH_SIZE = 5000;   // rows per Oracle batch flush

    /** Column list, single source of truth — used by both variants. */
    private static final String SELECT_SQL =
            "SELECT ID_IMNT, ID_TYP_ALT_IMNT, ID_EXCHANGE_KEY, ID_IMNT_ALT, " +
            "       ID_EXCH, ID_VIEW_FLAG, DT_CHG_GRD, ID_DEL_GRD, ID_OWN_GRD " +
            "FROM EXCH_INST_ALT_ID";

    /** Used in log lines so it's easy to grep one table's progress out of a multi-table run. */
    private static final String TABLE_LABEL = "EXCH_INST_ALT_ID";

    private final JdbcTemplate sybaseJdbcTemplate;
    private final JdbcTemplate oracleJdbcTemplate;

    /**
     * Wires the two JdbcTemplates and configures the Sybase reader for streaming.
     *
     * <p>The Sybase template's fetch size is set here, once. Without this, jconn4
     * defaults to a very small fetch size and pulls rows in tiny network round-trips,
     * which negates the benefit of the {@link RowCallbackHandler} streaming approach.
     *
     * <p>Note: setting fetch size on the template affects every query that uses it.
     * If this template is shared with other code paths that expect the default
     * behavior, inject a dedicated migration-only template instead.
     *
     * @param sybaseJdbcTemplate template bound to the Sybase DataSource (HikariPool-1)
     * @param oracleJdbcTemplate template bound to the Oracle DataSource (HikariPool-2)
     */
    public ExchangeInstrumentAlternateIdMigration(JdbcTemplate sybaseJdbcTemplate,
                                                  JdbcTemplate oracleJdbcTemplate) {
        this.sybaseJdbcTemplate = sybaseJdbcTemplate;
        this.oracleJdbcTemplate = oracleJdbcTemplate;

        // CRITICAL: without this jconn4 uses a tiny default fetch size
        // and you won't see streaming benefit. Set once.
        this.sybaseJdbcTemplate.setFetchSize(FETCH_SIZE);
    }

    /**
     * Variant A — positional (by-index) mapping.
     *
     * <p>Each {@code rs.getX(i)} call resolves directly to a column slot with no
     * metadata lookup. This is the fastest mapping option in the JDBC API but
     * couples the mapper to the SELECT column order.
     */
    public void migrateByIndex() {
        log.info("[{}] Starting migration (variant=byIndex, fetchSize={}, batchSize={})",
                TABLE_LABEL, FETCH_SIZE, BATCH_SIZE);
        final long startNanos = System.nanoTime();

        oracleJdbcTemplate.update("TRUNCATE TABLE TEMP_EXCH_INST_ALT_ID");
        log.debug("[{}] Target truncated", TABLE_LABEL);

        final String insertSql = EXCH_INST_ALT_ID.getInsertExpr();
        final ColumnMapper<ExchangeInstrumentAlternateId> columnMapper = new ColumnMapper<>();
        final List<ExchangeInstrumentAlternateId> buffer = new ArrayList<>(BATCH_SIZE);
        final MigrationStats stats = new MigrationStats();

        sybaseJdbcTemplate.query(SELECT_SQL, (RowCallbackHandler) rs -> {
            ExchangeInstrumentAlternateId row = new ExchangeInstrumentAlternateId();
            // Indices MUST match SELECT_SQL column order above.
            row.setID_IMNT(          rs.getObject(1, Integer.class));
            row.setID_TYP_ALT_IMNT(  rs.getString(2));
            row.setID_EXCHANGE_KEY(  rs.getObject(3, Integer.class));
            row.setID_IMNT_ALT(      rs.getString(4));
            row.setID_EXCH(          rs.getObject(5, Integer.class));
            row.setID_VIEW_FLAG(     rs.getString(6));
            row.setDT_CHG_GRD(       rs.getTimestamp(7));
            row.setID_DEL_GRD(       rs.getString(8));
            row.setID_OWN_GRD(       rs.getObject(9, Integer.class));
            buffer.add(row);

            if (buffer.size() >= BATCH_SIZE) {
                flush(stats, buffer, insertSql, columnMapper);
            }
        });

        if (!buffer.isEmpty()) {
            flush(stats, buffer, insertSql, columnMapper);
        }

        logCompletion("byIndex", stats, startNanos);
    }

    /**
     * Variant B — by-name mapping.
     *
     * <p>Each {@code rs.getX("COL_NAME")} call performs a (driver-cached)
     * case-insensitive lookup against the ResultSetMetaData to resolve the
     * column index. Slightly slower per cell, more readable, robust to SELECT
     * column reordering.
     */
    public void migrateByName() {
        log.info("[{}] Starting migration (variant=byName, fetchSize={}, batchSize={})",
                TABLE_LABEL, FETCH_SIZE, BATCH_SIZE);
        final long startNanos = System.nanoTime();

        oracleJdbcTemplate.update("TRUNCATE TABLE TEMP_EXCH_INST_ALT_ID");
        log.debug("[{}] Target truncated", TABLE_LABEL);

        final String insertSql = EXCH_INST_ALT_ID.getInsertExpr();
        final ColumnMapper<ExchangeInstrumentAlternateId> columnMapper = new ColumnMapper<>();
        final List<ExchangeInstrumentAlternateId> buffer = new ArrayList<>(BATCH_SIZE);
        final MigrationStats stats = new MigrationStats();

        sybaseJdbcTemplate.query(SELECT_SQL, (RowCallbackHandler) rs -> {
            ExchangeInstrumentAlternateId row = new ExchangeInstrumentAlternateId();
            // Resolved by column name — order-independent.
            row.setID_IMNT(          rs.getObject("ID_IMNT", Integer.class));
            row.setID_TYP_ALT_IMNT(  rs.getString("ID_TYP_ALT_IMNT"));
            row.setID_EXCHANGE_KEY(  rs.getObject("ID_EXCHANGE_KEY", Integer.class));
            row.setID_IMNT_ALT(      rs.getString("ID_IMNT_ALT"));
            row.setID_EXCH(          rs.getObject("ID_EXCH", Integer.class));
            row.setID_VIEW_FLAG(     rs.getString("ID_VIEW_FLAG"));
            row.setDT_CHG_GRD(       rs.getTimestamp("DT_CHG_GRD"));
            row.setID_DEL_GRD(       rs.getString("ID_DEL_GRD"));
            row.setID_OWN_GRD(       rs.getObject("ID_OWN_GRD", Integer.class));
            buffer.add(row);

            if (buffer.size() >= BATCH_SIZE) {
                flush(stats, buffer, insertSql, columnMapper);
            }
        });

        if (!buffer.isEmpty()) {
            flush(stats, buffer, insertSql, columnMapper);
        }

        logCompletion("byName", stats, startNanos);
    }

    /**
     * Flushes the current buffer of rows to Oracle in a single batch, clears the
     * buffer, and updates running stats.
     *
     * <p>Logs at DEBUG per batch — at INFO this would be 200+ lines for a 1M row
     * table, which drowns the logs. Bump the logger to DEBUG when troubleshooting.
     *
     * @param stats        running counters to update
     * @param buffer       rows pending insert; cleared on return
     * @param insertSql    parameterized INSERT statement for Oracle
     * @param columnMapper binds a row's fields to PreparedStatement parameters
     */
    private void flush(MigrationStats stats,
                       List<ExchangeInstrumentAlternateId> buffer,
                       String insertSql,
                       ColumnMapper<ExchangeInstrumentAlternateId> columnMapper) {
        final int rowsInThisBatch = buffer.size();
        final long batchStartNanos = System.nanoTime();

        oracleJdbcTemplate.batchUpdate(
                insertSql,
                buffer,
                BATCH_SIZE,
                columnMapper::setParameters
        );

        final long batchElapsedMs = (System.nanoTime() - batchStartNanos) / 1_000_000;
        stats.batchCount++;
        stats.totalRows += rowsInThisBatch;

        log.debug("[{}] Batch {} complete — rows={}, elapsedMs={}, totalRowsSoFar={}",
                TABLE_LABEL, stats.batchCount, rowsInThisBatch, batchElapsedMs, stats.totalRows);

        buffer.clear(); // free references; ArrayList keeps capacity, no re-alloc next round
    }

    /**
     * Emits the end-of-table summary at INFO level, including throughput.
     */
    private void logCompletion(String variant, MigrationStats stats, long startNanos) {
        final long totalElapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
        final double seconds = Math.max(totalElapsedMs / 1000.0, 0.001); // avoid div-by-zero
        final long rowsPerSec = (long) (stats.totalRows / seconds);

        log.info("[{}] Migration complete (variant={}) — totalRows={}, batches={}, elapsedMs={}, throughput={} rows/sec",
                TABLE_LABEL, variant, stats.totalRows, stats.batchCount, totalElapsedMs, rowsPerSec);
    }

    /** Mutable counters for one migration run. Not thread-safe — single-threaded callback. */
    private static final class MigrationStats {
        long totalRows = 0;
        int batchCount = 0;
    }
}
