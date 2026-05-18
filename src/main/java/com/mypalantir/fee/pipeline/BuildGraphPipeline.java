package com.mypalantir.fee.pipeline;

import com.mypalantir.reasoning.function.builtin.AbstractBuiltinFunction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.util.*;

/**
 * E1-E6 路网有向边生成管道。
 * 从收费单元、收费站、不可达规则生成 FEE_CONTIGUITY 表的有向边。
 */
public class BuildGraphPipeline extends AbstractBuiltinFunction {

    private static final Logger logger = LoggerFactory.getLogger(BuildGraphPipeline.class);
    private final String jdbcUrl;

    public BuildGraphPipeline(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @Override
    public String getName() {
        return "build_graph";
    }

    @Override
    public Object execute(List<Object> args) {
        try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "")) {
            List<Map<String, Object>> units = queryAll(conn, "FEE_TOLL_UNIT");
            List<Map<String, Object>> stations = queryAll(conn, "FEE_TOLL_STATION");
            List<Map<String, Object>> rules = queryAll(conn, "FEE_NO_CONTIGUITY_RULE");

            try (Statement stmt = conn.createStatement()) {
                stmt.executeUpdate("DELETE FROM \"FEE_CONTIGUITY\"");
            }

            String lastver = units.isEmpty() ? "" : str(units.get(0), "LASTVER");
            List<Edge> edges = new ArrayList<>();

            // E1: 收费单元→收费单元
            for (Map<String, Object> a : units) {
                String aEndId = str(a, "ENDORGID");
                int aEndType = intVal(a, "ENDORGTYPE");
                String aOppositeId = str(a, "OPPOSITEID");
                String aId = str(a, "TOLLINTERVALID");
                int aMiles = intVal(a, "ACTUALLENGTH");
                int aChargeMiles = intVal(a, "CHARGELENGTH");

                for (Map<String, Object> b : units) {
                    String bId = str(b, "TOLLINTERVALID");
                    if (bId.equals(aId)) continue;
                    if (aOppositeId != null && bId.equals(aOppositeId)) continue;

                    String bStartId = str(b, "STARTORGID");
                    int bStartType = intVal(b, "STARTORGTYPE");

                    if (aEndId != null && aEndId.equals(bStartId) && aEndType == bStartType) {
                        edges.add(new Edge(aId, 0, bId, 0, aMiles, aChargeMiles, false, null));
                    }
                }
            }

            // E2: 收费站→收费单元 (station is start of unit)
            for (Map<String, Object> u : units) {
                int startType = intVal(u, "STARTORGTYPE");
                if (startType != 1) continue;
                String startOrgId = str(u, "STARTORGID");
                String uId = str(u, "TOLLINTERVALID");

                for (Map<String, Object> s : stations) {
                    String sId = str(s, "STATIONID");
                    int useStatus = intVal(s, "USESTATUS");
                    if (useStatus != 2) continue;

                    if (sId.equals(startOrgId)) {
                        edges.add(new Edge(sId, 1, uId, 0, 0, 0, false, null));
                    }
                }
            }

            // E3: 收费单元→收费站 (station is end of unit)
            for (Map<String, Object> u : units) {
                int endType = intVal(u, "ENDORGTYPE");
                if (endType != 1) continue;
                String endOrgId = str(u, "ENDORGID");
                String uId = str(u, "TOLLINTERVALID");
                int miles = intVal(u, "ACTUALLENGTH");
                int chargeMiles = intVal(u, "CHARGELENGTH");

                for (Map<String, Object> s : stations) {
                    String sId = str(s, "STATIONID");
                    if (sId.equals(endOrgId)) {
                        edges.add(new Edge(uId, 0, sId, 1, miles, chargeMiles, false, null));
                    }
                }
            }

            // E4: 标记不可达边 (contiguityType=1)
            int invalidated = 0;
            for (Map<String, Object> rule : rules) {
                int cType = intVal(rule, "CONTIGUITYTYPE");
                if (cType != 1) continue;
                String enId = str(rule, "ENROADNODEID");
                int enType = intVal(rule, "ENROADNODETYPE");
                String exId = str(rule, "EXROADNODEID");
                int exType = intVal(rule, "EXROADNODETYPE");

                for (Edge e : edges) {
                    if (e.enNodeId.equals(enId) && e.enNodeType == enType
                            && e.exNodeId.equals(exId) && e.exNodeType == exType) {
                        e.invalid = true;
                        e.ruleId = "E4";
                        invalidated++;
                    }
                }
            }

            // E5: 强制补充边 (contiguityType=2 or 3)
            for (Map<String, Object> rule : rules) {
                int cType = intVal(rule, "CONTIGUITYTYPE");
                if (cType != 2 && cType != 3) continue;
                String enId = str(rule, "ENROADNODEID");
                int enType = intVal(rule, "ENROADNODETYPE");
                String exId = str(rule, "EXROADNODEID");
                int exType = intVal(rule, "EXROADNODETYPE");

                boolean exists = edges.stream().anyMatch(e ->
                        e.enNodeId.equals(enId) && e.enNodeType == enType
                                && e.exNodeId.equals(exId) && e.exNodeType == exType && !e.invalid);
                if (!exists) {
                    edges.add(new Edge(enId, enType, exId, exType, 0, 0, false, "E5"));
                }
            }

            // E6: 去重 (keep first occurrence)
            Set<String> seen = new HashSet<>();
            List<Edge> deduped = new ArrayList<>();
            for (Edge e : edges) {
                String key = e.enNodeId + "|" + e.enNodeType + "|" + e.exNodeId + "|" + e.exNodeType;
                if (seen.add(key)) {
                    deduped.add(e);
                }
            }

            String insertSql = "INSERT INTO \"FEE_CONTIGUITY\" " +
                    "(\"EN_ROAD_NODE_ID\", \"EN_ROAD_NODE_TYPE\", \"EX_ROAD_NODE_ID\", \"EX_ROAD_NODE_TYPE\", " +
                    "\"MILES\", \"CHARGE_MILES\", \"INVALID\", \"RULE_ID\", \"LASTVER\") " +
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";
            try (PreparedStatement ps = conn.prepareStatement(insertSql)) {
                for (Edge e : deduped) {
                    ps.setString(1, e.enNodeId);
                    ps.setInt(2, e.enNodeType);
                    ps.setString(3, e.exNodeId);
                    ps.setInt(4, e.exNodeType);
                    ps.setInt(5, e.miles);
                    ps.setInt(6, e.chargeMiles);
                    ps.setBoolean(7, e.invalid);
                    ps.setString(8, e.ruleId);
                    ps.setString(9, lastver);
                    ps.addBatch();
                }
                ps.executeBatch();
            }

            logger.info("BuildGraph: {} edges created, {} invalidated", deduped.size(), invalidated);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("edges_created", deduped.size());
            result.put("edges_invalidated", invalidated);
            return result;
        } catch (Exception e) {
            logger.error("BuildGraph failed", e);
            return Map.of("error", e.getMessage());
        }
    }

    private static class Edge {
        String enNodeId;
        int enNodeType;
        String exNodeId;
        int exNodeType;
        int miles;
        int chargeMiles;
        boolean invalid;
        String ruleId;

        Edge(String enNodeId, int enNodeType, String exNodeId, int exNodeType,
             int miles, int chargeMiles, boolean invalid, String ruleId) {
            this.enNodeId = enNodeId;
            this.enNodeType = enNodeType;
            this.exNodeId = exNodeId;
            this.exNodeType = exNodeType;
            this.miles = miles;
            this.chargeMiles = chargeMiles;
            this.invalid = invalid;
            this.ruleId = ruleId;
        }
    }

    private List<Map<String, Object>> queryAll(Connection conn, String table) throws SQLException {
        List<Map<String, Object>> rows = new ArrayList<>();
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery("SELECT * FROM \"" + table + "\"")) {
            ResultSetMetaData meta = rs.getMetaData();
            int colCount = meta.getColumnCount();
            while (rs.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= colCount; i++) {
                    row.put(meta.getColumnName(i), rs.getObject(i));
                }
                rows.add(row);
            }
        }
        return rows;
    }

    private String str(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v != null ? v.toString() : null;
    }

    private int intVal(Map<String, Object> m, String key) {
        Object v = m.get(key);
        if (v instanceof Number) return ((Number) v).intValue();
        if (v instanceof String) {
            try { return Integer.parseInt((String) v); } catch (NumberFormatException e) { return 0; }
        }
        return 0;
    }
}
