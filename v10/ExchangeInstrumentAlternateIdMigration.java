import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

/**
 * Streaming migration for ExchangeInstrumentAlternateId (Sybase -> Oracle).
 *
 * Replaces:
 *     List<ExchangeInstrumentAlternateId> rows = sybaseJdbcTemplate.query(sql, new BeanPropertyRowMapper<>(...));
 *     oracleJdbcTemplate.batchUpdate(insertSql, rows, 5000, columnMapper::setParameters);
 *
 * with a streaming read + buffered batch write. Memory stays bounded at
 * ~BATCH_SIZE rows instead of holding all 1M+ rows in a List.
 */
public class ExchangeInstrumentAlternateIdMigration {

    private static final int FETCH_SIZE = 2000;   // jconn4 rows-per-round-trip
    private static final int BATCH_SIZE = 5000;   // rows per Oracle batch flush

    private final JdbcTemplate sybaseJdbcTemplate;
    private final JdbcTemplate oracleJdbcTemplate;

    /**
     * Wires the two JdbcTemplates and configures the Sybase reader for streaming.
     *
     * <p>The Sybase template's fetch size is set here, once. Without this, jconn4
     * defaults to a very small fetch size and pulls rows in tiny network round-trips,
     * which negates the benefit of the {@link RowCallbackHandler} streaming approach
     * used in {@link #migrate()}.
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
     * Migrates all rows from Sybase {@code EXCH_INST_ALT_ID} into Oracle
     * {@code TEMP_EXCH_INST_ALT_ID} using a streaming read and buffered batch writes.
     *
     * <p>Flow:
     * <ol>
     *   <li>Truncate the Oracle target table.</li>
     *   <li>Open a streaming SELECT against Sybase. Spring invokes the
     *       {@link RowCallbackHandler} per row as jconn4 yields it; rows are NOT
     *       collected into a List by the framework.</li>
     *   <li>Each row is hand-mapped by index into a {@code ExchangeInstrumentAlternateId}
     *       and appended to an in-memory buffer.</li>
     *   <li>When the buffer reaches {@link #BATCH_SIZE}, it is flushed to Oracle via
     *       {@code batchUpdate} and cleared, keeping memory bounded.</li>
     *   <li>After the ResultSet is exhausted, any leftover rows are flushed.</li>
     * </ol>
     *
     * <p>The column order in the SELECT must match the index order used in the
     * mapping lambda below — they are read positionally for speed.
     *
     * <p>Reader/writer overlap: while {@code batchUpdate} is executing on the Oracle
     * connection, jconn4 continues prefetching the next chunk of rows on the Sybase
     * connection. Because the two pools are independent, this happens for free
     * without explicit threading.
     *
     * <p>Transactionality: this method is intentionally NOT annotated with
     * {@code @Transactional}. Each {@code batchUpdate} commits on its own (Hikari
     * autoCommit defaults to true), which keeps Oracle UNDO bounded per batch
     * rather than accumulating across the entire 1M+ row migration.
     */
    public void migrate() {
        // 1. Truncate the Oracle target (same as your current code)
        oracleJdbcTemplate.update("TRUNCATE TABLE TEMP_EXCH_INST_ALT_ID");

        // 2. Stream from Sybase -> buffer -> flush to Oracle
        // Column order in SELECT must match the order we read by index below.
        final String selectSql =
                "SELECT ID_IMNT, ID_TYP_ALT_IMNT, ID_EXCHANGE_KEY, ID_IMNT_ALT, " +
                "       ID_EXCH, ID_VIEW_FLAG, DT_CHG_GRD, ID_DEL_GRD, ID_OWN_GRD " +
                "FROM EXCH_INST_ALT_ID";

        final String insertSql = EXCH_INST_ALT_ID.getInsertExpr();
        final ColumnMapper<ExchangeInstrumentAlternateId> columnMapper = new ColumnMapper<>();

        final List<ExchangeInstrumentAlternateId> buffer = new ArrayList<>(BATCH_SIZE);

        sybaseJdbcTemplate.query(selectSql, (RowCallbackHandler) rs -> {
            ExchangeInstrumentAlternateId row = new ExchangeInstrumentAlternateId();
            // Read by index — same semantics as BeanPropertyRowMapper but without reflection.
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
                flush(buffer, insertSql, columnMapper);
            }
        });

        // 3. Flush leftover rows after the ResultSet is exhausted
        if (!buffer.isEmpty()) {
            flush(buffer, insertSql, columnMapper);
        }
    }

    /**
     * Flushes the current buffer of rows to Oracle in a single batch and clears it.
     *
     * <p>Called both from inside the streaming callback (when the buffer fills up
     * to {@link #BATCH_SIZE}) and once after the ResultSet is exhausted (to drain
     * any remaining rows that didn't fill a final batch).
     *
     * <p>{@link List#clear()} drops references but retains the underlying array
     * capacity, so subsequent fills don't trigger re-allocation.
     *
     * @param buffer        rows pending insert; cleared on return
     * @param insertSql     parameterized INSERT statement for Oracle
     * @param columnMapper  binds a row's fields to the PreparedStatement parameters
     */
    private void flush(List<ExchangeInstrumentAlternateId> buffer,
                       String insertSql,
                       ColumnMapper<ExchangeInstrumentAlternateId> columnMapper) {
        oracleJdbcTemplate.batchUpdate(
                insertSql,
                buffer,
                BATCH_SIZE,
                columnMapper::setParameters
        );
        buffer.clear(); // free references; ArrayList keeps capacity, no re-alloc next round
    }
}
