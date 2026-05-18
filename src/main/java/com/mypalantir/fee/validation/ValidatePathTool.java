package com.mypalantir.fee.validation;

import com.mypalantir.reasoning.function.builtin.AbstractBuiltinFunction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.util.*;

/**
 * V1-V5 路径验证工具。
 * 验证 MinimumFeePath 的正确性并写入 FEE_VALIDATION_ERROR。
 */
public class ValidatePathTool extends AbstractBuiltinFunction {

    private static final Logger logger = LoggerFactory.getLogger(ValidatePathTool.class);
    private final String jdbcUrl;

    public ValidatePathTool(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @Override
    public String getName() {
        return "validate_path";
    }

    @Override
    public Object execute(List<Object> args) {
        if (args.isEmpty()) return Map.of("error", "需要参数: path_id");

        long pathId;
        if (args.get(0) instanceof Number) {
            pathId = ((Number) args.get(0)).longValue();
        } else {
            pathId = Long.parseLong(args.get(0).toString());
        }

        try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "")) {
            Map<String, Object> path = queryPath(conn, pathId);
            if (path == null) return Map.of("error", "路径不存在: " + pathId);

            String unitsStr = (String) path.get("TOLL_INTERVALS_GROUP");
            String mfeeStr = (String) path.get("CHARGEFEE_GROUP");
            String efeeStr = (String) path.get("CHARGEFEE95_GROUP");
            int totalFee = ((Number) path.get("TOTAL_FEE")).intValue();
            int totalFee95 = ((Number) path.get("TOTAL_FEE95")).intValue();

            String[] units = unitsStr != null && !unitsStr.isEmpty() ? unitsStr.split(",") : new String[0];
            int[] mfees = parseInts(mfeeStr);
            int[] efees = parseInts(efeeStr);

            List<Map<String, Object>> errors = new ArrayList<>();

            // V1: 相邻单元连通性
            Set<String> validEdges = loadValidEdges(conn);
            for (int i = 0; i < units.length - 1; i++) {
                String edgeKey = units[i] + "|0->" + units[i + 1] + "|0";
                if (!validEdges.contains(edgeKey)) {
                    errors.add(Map.of("rule_id", "V1",
                            "message", "相邻单元 " + units[i] + " → " + units[i + 1] + " 之间无有效边"));
                }
            }

            // V2: MTC总费额验证
            int sumMfee = Arrays.stream(mfees).sum();
            int expectedTotalFee = (int) (Math.floor((double) sumMfee / 100 + 0.5) * 100);
            if (totalFee != expectedTotalFee) {
                errors.add(Map.of("rule_id", "V2",
                        "message", "MTC总费额不一致: 期望=" + expectedTotalFee + ", 实际=" + totalFee));
            }

            // V3: ETC总费额验证
            int sumEfee = Arrays.stream(efees).sum();
            int expectedFee95 = (int) Math.min(sumEfee, Math.floor((double) sumMfee / 100) * 100 * 0.95);
            expectedFee95 = (int) (Math.floor((double) expectedFee95 / 100 + 0.5) * 100);
            if (totalFee95 != expectedFee95) {
                errors.add(Map.of("rule_id", "V3",
                        "message", "ETC总费额不一致: 期望=" + expectedFee95 + ", 实际=" + totalFee95));
            }

            // V4: 三个序列长度一致
            if (units.length != mfees.length || units.length != efees.length) {
                errors.add(Map.of("rule_id", "V4",
                        "message", "序列长度不一致: units=" + units.length +
                                ", mfees=" + mfees.length + ", efees=" + efees.length));
            }

            // V5: 同门架下单元连续 (检查gantryId分组)
            Map<String, String> unitToGantry = loadUnitGantryMapping(conn);
            for (int i = 0; i < units.length - 1; i++) {
                String g1 = unitToGantry.get(units[i]);
                String g2 = unitToGantry.get(units[i + 1]);
                if (g1 != null && g2 != null && g1.equals(g2)) {
                    // Same gantry - they should be adjacent (which they are by definition)
                    // But check if there are other units of same gantry not in sequence
                }
            }
            // V5 extended: all units sharing a gantry should appear as a contiguous block
            Map<String, List<Integer>> gantryPositions = new LinkedHashMap<>();
            for (int i = 0; i < units.length; i++) {
                String g = unitToGantry.get(units[i]);
                if (g != null) {
                    gantryPositions.computeIfAbsent(g, k -> new ArrayList<>()).add(i);
                }
            }
            for (Map.Entry<String, List<Integer>> entry : gantryPositions.entrySet()) {
                List<Integer> positions = entry.getValue();
                if (positions.size() > 1) {
                    for (int i = 1; i < positions.size(); i++) {
                        if (positions.get(i) - positions.get(i - 1) != 1) {
                            errors.add(Map.of("rule_id", "V5",
                                    "message", "门架 " + entry.getKey() + " 下的收费单元不连续"));
                            break;
                        }
                    }
                }
            }

            // 写入验证错误
            try (Statement stmt = conn.createStatement()) {
                stmt.executeUpdate("DELETE FROM \"FEE_VALIDATION_ERROR\" WHERE \"PATH_ID\" = " + pathId);
            }

            boolean validationFailed = !errors.isEmpty();
            if (validationFailed) {
                String insertSql = "INSERT INTO \"FEE_VALIDATION_ERROR\" (\"PATH_ID\", \"RULE_ID\", \"MESSAGE\") VALUES (?, ?, ?)";
                try (PreparedStatement ps = conn.prepareStatement(insertSql)) {
                    for (Map<String, Object> err : errors) {
                        ps.setLong(1, pathId);
                        ps.setString(2, (String) err.get("rule_id"));
                        ps.setString(3, (String) err.get("message"));
                        ps.addBatch();
                    }
                    ps.executeBatch();
                }

                try (PreparedStatement ps = conn.prepareStatement(
                        "UPDATE \"FEE_MINIMUM_FEE_PATH\" SET \"VALIDATION_FAILED\" = TRUE WHERE \"ID\" = ?")) {
                    ps.setLong(1, pathId);
                    ps.executeUpdate();
                }
            }

            logger.info("ValidatePath: pathId={}, errors={}", pathId, errors.size());
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("path_id", pathId);
            result.put("validation_failed", validationFailed);
            result.put("error_count", errors.size());
            result.put("errors", errors);
            return result;
        } catch (Exception e) {
            logger.error("ValidatePath failed", e);
            return Map.of("error", e.getMessage());
        }
    }

    private Map<String, Object> queryPath(Connection conn, long pathId) throws SQLException {
        String sql = "SELECT * FROM \"FEE_MINIMUM_FEE_PATH\" WHERE \"ID\" = " + pathId;
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            if (!rs.next()) return null;
            ResultSetMetaData meta = rs.getMetaData();
            Map<String, Object> row = new LinkedHashMap<>();
            for (int i = 1; i <= meta.getColumnCount(); i++) {
                row.put(meta.getColumnName(i), rs.getObject(i));
            }
            return row;
        }
    }

    private Set<String> loadValidEdges(Connection conn) throws SQLException {
        Set<String> edges = new HashSet<>();
        String sql = "SELECT \"EN_ROAD_NODE_ID\", \"EN_ROAD_NODE_TYPE\", " +
                "\"EX_ROAD_NODE_ID\", \"EX_ROAD_NODE_TYPE\" FROM \"FEE_CONTIGUITY\" WHERE \"INVALID\" = FALSE";
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            while (rs.next()) {
                String key = rs.getString(1) + "|" + rs.getInt(2) + "->" + rs.getString(3) + "|" + rs.getInt(4);
                edges.add(key);
            }
        }
        return edges;
    }

    private Map<String, String> loadUnitGantryMapping(Connection conn) throws SQLException {
        Map<String, String> mapping = new HashMap<>();
        String sql = "SELECT \"TOLLINTERVALID\", \"GANTRYID\" FROM \"FEE_TOLL_UNIT\"";
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            while (rs.next()) {
                String unitId = rs.getString(1);
                String gantryId = rs.getString(2);
                if (gantryId != null) {
                    mapping.put(unitId, gantryId);
                }
            }
        }
        return mapping;
    }

    private int[] parseInts(String s) {
        if (s == null || s.isEmpty()) return new int[0];
        String[] parts = s.split(",");
        int[] result = new int[parts.length];
        for (int i = 0; i < parts.length; i++) {
            try {
                result[i] = Integer.parseInt(parts[i].trim());
            } catch (NumberFormatException e) {
                result[i] = 0;
            }
        }
        return result;
    }
}
