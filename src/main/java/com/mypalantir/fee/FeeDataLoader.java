package com.mypalantir.fee;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.IOException;
import java.sql.*;
import java.util.List;
import java.util.Map;

public class FeeDataLoader {

    private static final Logger logger = LoggerFactory.getLogger(FeeDataLoader.class);
    private final ObjectMapper objectMapper = new ObjectMapper();

    public void loadAll(String jdbcUrl, String dataDir) throws SQLException, IOException {
        try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "")) {
            loadJsonFile(new File(dataDir, "G0002370010路段站1.sql"), "FEE_TOLL_STATION",
                    null,
                    "ID", row -> row.getOrDefault("ID", row.get("STATIONID")).toString(),
                    conn);

            loadJsonFile(new File(dataDir, "G0002370010路段收费单元-0506.sql"), "FEE_TOLL_UNIT",
                    null, null, null, conn);

            loadJsonFile(new File(dataDir, "费率.sql"), "FEE_BASE_RATE",
                    null, "ID", row -> row.get("RATECODE") + "_" + row.get("VC"),
                    conn);

            loadJsonFile(new File(dataDir, "不可达1.sql"), "FEE_NO_CONTIGUITY_RULE",
                    null, "ID", row -> row.get("ENROADNODEID") + "_" + row.get("EXROADNODEID"),
                    conn);

            loadSpecialTimeDiscount(new File(dataDir, "特殊时段-0506.sql"), conn);
        }
    }

    @FunctionalInterface
    interface IdGenerator {
        String generate(Map<String, Object> row);
    }

    private void loadJsonFile(File file, String tableName, Map<String, String> fieldMapping,
                              String syntheticIdColumn, IdGenerator idGenerator,
                              Connection conn) throws IOException, SQLException {
        if (!file.exists()) {
            logger.warn("Data file not found: {}", file.getAbsolutePath());
            return;
        }

        try (Statement stmt = conn.createStatement()) {
            ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM \"" + tableName + "\"");
            rs.next();
            if (rs.getInt(1) > 0) {
                logger.info("Table {} already has data, skipping", tableName);
                return;
            }
        }

        List<Map<String, Object>> records = objectMapper.readValue(file,
                new TypeReference<List<Map<String, Object>>>() {});

        if (records.isEmpty()) return;

        ResultSet columns;
        try (Statement stmt = conn.createStatement()) {
            columns = conn.getMetaData().getColumns(null, null, tableName, null);
        }
        Map<String, String> columnTypes = new java.util.LinkedHashMap<>();
        try (ResultSet cols = conn.getMetaData().getColumns(null, null, tableName, null)) {
            while (cols.next()) {
                columnTypes.put(cols.getString("COLUMN_NAME"), cols.getString("TYPE_NAME"));
            }
        }

        int inserted = 0;
        for (Map<String, Object> record : records) {
            Map<String, Object> row = new java.util.LinkedHashMap<>();

            if (syntheticIdColumn != null && idGenerator != null) {
                row.put(syntheticIdColumn, idGenerator.generate(record));
            }

            for (Map.Entry<String, String> colEntry : columnTypes.entrySet()) {
                String colName = colEntry.getKey();
                if (syntheticIdColumn != null && colName.equals(syntheticIdColumn) && !record.containsKey(colName)) {
                    continue;
                }

                String jsonKey = colName;
                if (fieldMapping != null && fieldMapping.containsKey(colName)) {
                    jsonKey = fieldMapping.get(colName);
                }

                Object value = record.get(jsonKey);
                if (value == null && !colName.equals(jsonKey)) {
                    value = record.get(colName);
                }
                if (value != null) {
                    row.put(colName, value);
                }
            }

            if (row.isEmpty()) continue;

            StringBuilder sql = new StringBuilder("INSERT INTO \"" + tableName + "\" (");
            StringBuilder vals = new StringBuilder("VALUES (");
            List<Object> params = new java.util.ArrayList<>();
            boolean first = true;
            for (Map.Entry<String, Object> entry : row.entrySet()) {
                if (!first) { sql.append(", "); vals.append(", "); }
                sql.append("\"").append(entry.getKey()).append("\"");
                vals.append("?");
                params.add(entry.getValue());
                first = false;
            }
            sql.append(") ").append(vals).append(")");

            try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
                for (int i = 0; i < params.size(); i++) {
                    Object val = params.get(i);
                    if (val == null) {
                        ps.setNull(i + 1, Types.VARCHAR);
                    } else if (val instanceof Number) {
                        if (val instanceof Integer) ps.setInt(i + 1, (Integer) val);
                        else if (val instanceof Long) ps.setLong(i + 1, (Long) val);
                        else if (val instanceof Double) ps.setDouble(i + 1, (Double) val);
                        else ps.setString(i + 1, val.toString());
                    } else {
                        ps.setString(i + 1, val.toString());
                    }
                }
                ps.executeUpdate();
                inserted++;
            }
        }
        logger.info("Loaded {} records into {}", inserted, tableName);
    }

    private void loadSpecialTimeDiscount(File file, Connection conn) throws IOException, SQLException {
        if (!file.exists()) {
            logger.warn("Data file not found: {}", file.getAbsolutePath());
            return;
        }

        try (Statement stmt = conn.createStatement()) {
            ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM \"FEE_SPECIAL_TIME_DISCOUNT\"");
            rs.next();
            if (rs.getInt(1) > 0) {
                logger.info("Table FEE_SPECIAL_TIME_DISCOUNT already has data, skipping");
                return;
            }
        }

        List<Map<String, Object>> records = objectMapper.readValue(file,
                new TypeReference<List<Map<String, Object>>>() {});

        String sql = "INSERT INTO \"FEE_SPECIAL_TIME_DISCOUNT\" " +
                "(\"TOLLINTERVALID\", \"STARTDATE\", \"ENDDATE\", \"STARTHOUR\", \"ENDHOUR\", " +
                "\"VEHILCETYPE\", \"CPCDISCOUNT\", \"ETCDISCOUNT\", \"FLAG\", \"LASTVER\", \"VERUSETIME\") " +
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

        int inserted = 0;
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            for (Map<String, Object> r : records) {
                ps.setString(1, str(r, "TOLLINTERVALID"));
                ps.setString(2, str(r, "STARTDATE"));
                ps.setString(3, str(r, "ENDDATE"));
                ps.setObject(4, r.get("STARTHOUR"), Types.INTEGER);
                ps.setObject(5, r.get("ENDHOUR"), Types.INTEGER);
                ps.setString(6, str(r, "VEHILCETYPE"));
                ps.setObject(7, r.get("CPCDISCOUNT"), Types.INTEGER);
                ps.setObject(8, r.get("ETCDISCOUNT"), Types.INTEGER);
                ps.setObject(9, r.get("FLAG"), Types.INTEGER);
                ps.setString(10, str(r, "LASTVER"));
                ps.setString(11, str(r, "VERUSETIME"));
                ps.addBatch();
                inserted++;
            }
            ps.executeBatch();
        }
        logger.info("Loaded {} records into FEE_SPECIAL_TIME_DISCOUNT", inserted);
    }

    private String str(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v != null ? v.toString() : null;
    }
}
