package com.mypalantir.fee.tool;

import com.mypalantir.reasoning.function.builtin.AbstractBuiltinFunction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.util.*;

/**
 * Dijkstra 最小费额路径搜索。
 * 从入口站到出口站搜索最小MTC费额路径。
 */
public class FindPathTool extends AbstractBuiltinFunction {

    private static final Logger logger = LoggerFactory.getLogger(FindPathTool.class);
    private final String jdbcUrl;

    public FindPathTool(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @Override
    public String getName() {
        return "find_path";
    }

    @Override
    public Object execute(List<Object> args) {
        if (args.size() < 3) return Map.of("error", "需要参数: en_station_id, ex_station_id, vehicle_type");

        String enStationId = args.get(0).toString();
        String exStationId = args.get(1).toString();
        int vehicleType;
        if (args.get(2) instanceof Number) {
            vehicleType = ((Number) args.get(2)).intValue();
        } else {
            vehicleType = Integer.parseInt(args.get(2).toString());
        }

        try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "")) {
            Map<String, List<GraphEdge>> graph = buildGraph(conn, vehicleType);

            // nodeKey = nodeId + "|" + nodeType (1=station, 0=unit)
            String startKey = enStationId + "|1";
            String endKey = exStationId + "|1";

            if (!graph.containsKey(startKey)) {
                return Map.of("error", "入口站 " + enStationId + " 在图中没有出边");
            }

            // Dijkstra
            Map<String, Integer> dist = new HashMap<>();
            Map<String, String> prev = new HashMap<>();
            Map<String, GraphEdge> prevEdge = new HashMap<>();
            PriorityQueue<int[]> pq = new PriorityQueue<>(Comparator.comparingInt(a -> a[0]));
            Map<String, Integer> nodeIndex = new HashMap<>();
            List<String> nodeList = new ArrayList<>(graph.keySet());
            for (int i = 0; i < nodeList.size(); i++) {
                nodeIndex.put(nodeList.get(i), i);
                dist.put(nodeList.get(i), Integer.MAX_VALUE);
            }
            if (!dist.containsKey(endKey)) {
                dist.put(endKey, Integer.MAX_VALUE);
            }

            dist.put(startKey, 0);
            pq.offer(new int[]{0, nodeIndex.getOrDefault(startKey, -1)});

            Set<String> visited = new HashSet<>();
            while (!pq.isEmpty()) {
                int[] cur = pq.poll();
                int curDist = cur[0];
                int curIdx = cur[1];
                if (curIdx < 0 || curIdx >= nodeList.size()) continue;
                String curKey = nodeList.get(curIdx);

                if (visited.contains(curKey)) continue;
                visited.add(curKey);

                if (curKey.equals(endKey)) break;

                List<GraphEdge> neighbors = graph.getOrDefault(curKey, List.of());
                for (GraphEdge edge : neighbors) {
                    String nextKey = edge.toNodeId + "|" + edge.toNodeType;
                    if (!nodeIndex.containsKey(nextKey)) {
                        nodeIndex.put(nextKey, nodeList.size());
                        nodeList.add(nextKey);
                        dist.put(nextKey, Integer.MAX_VALUE);
                    }
                    int newDist = curDist + edge.weight;
                    if (newDist < dist.get(nextKey)) {
                        dist.put(nextKey, newDist);
                        prev.put(nextKey, curKey);
                        prevEdge.put(nextKey, edge);
                        pq.offer(new int[]{newDist, nodeIndex.get(nextKey)});
                    }
                }
            }

            if (dist.getOrDefault(endKey, Integer.MAX_VALUE) == Integer.MAX_VALUE) {
                return Map.of("error", "从 " + enStationId + " 到 " + exStationId + " 无可达路径");
            }

            // 回溯路径
            List<String> path = new ArrayList<>();
            String cur = endKey;
            while (cur != null && !cur.equals(startKey)) {
                path.add(cur);
                cur = prev.get(cur);
            }
            path.add(startKey);
            Collections.reverse(path);

            // 提取收费单元序列和费用
            List<String> tollUnits = new ArrayList<>();
            List<Integer> mfees = new ArrayList<>();
            List<Integer> efees = new ArrayList<>();
            int totalMileage = 0;

            Map<String, int[]> rateParams = loadRateParams(conn, vehicleType);

            for (int i = 1; i < path.size(); i++) {
                GraphEdge edge = prevEdge.get(path.get(i));
                if (edge != null && edge.tollUnitId != null) {
                    tollUnits.add(edge.tollUnitId);
                    int[] params = rateParams.getOrDefault(edge.tollUnitId, new int[]{0, 0, 0});
                    mfees.add(params[1]);
                    efees.add(params[2]);
                    totalMileage += edge.chargeMiles;
                }
            }

            // 计算总费额 (§6 公式: 四舍五入到分再取整到元再×100)
            int sumMfee = mfees.stream().mapToInt(Integer::intValue).sum();
            int sumEfee = efees.stream().mapToInt(Integer::intValue).sum();
            int totalFee = (int) (Math.floor((double) sumMfee / 100 + 0.5) * 100);
            int totalFee95 = (int) Math.min(sumEfee, Math.floor((double) sumMfee / 100) * 100 * 0.95);
            totalFee95 = (int) (Math.floor((double) totalFee95 / 100 + 0.5) * 100);

            // 写入数据库
            String lastver = "";
            String insertSql = "INSERT INTO \"FEE_MINIMUM_FEE_PATH\" " +
                    "(\"EN_STATION_ID\", \"EX_STATION_ID\", \"VEHICLE_TYPE\", " +
                    "\"TOLL_INTERVALS_GROUP\", \"CHARGEFEE_GROUP\", \"CHARGEFEE95_GROUP\", " +
                    "\"TOTAL_FEE\", \"TOTAL_FEE95\", \"TOTAL_MILEAGE\", \"VALIDATION_FAILED\", \"LASTVER\") " +
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

            long pathId;
            try (PreparedStatement ps = conn.prepareStatement(insertSql, Statement.RETURN_GENERATED_KEYS)) {
                ps.setString(1, enStationId);
                ps.setString(2, exStationId);
                ps.setInt(3, vehicleType);
                ps.setString(4, String.join(",", tollUnits));
                ps.setString(5, joinInts(mfees));
                ps.setString(6, joinInts(efees));
                ps.setInt(7, totalFee);
                ps.setInt(8, totalFee95);
                ps.setInt(9, totalMileage);
                ps.setBoolean(10, false);
                ps.setString(11, lastver);
                ps.executeUpdate();
                ResultSet keys = ps.getGeneratedKeys();
                keys.next();
                pathId = keys.getLong(1);
            }

            logger.info("FindPath: {} -> {}, vc={}, totalFee={}, totalFee95={}, units={}",
                    enStationId, exStationId, vehicleType, totalFee, totalFee95, tollUnits.size());

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("path_id", pathId);
            result.put("en_station_id", enStationId);
            result.put("ex_station_id", exStationId);
            result.put("vehicle_type", vehicleType);
            result.put("toll_units", tollUnits);
            result.put("mfee_list", mfees);
            result.put("efee_list", efees);
            result.put("total_fee", totalFee);
            result.put("total_fee95", totalFee95);
            result.put("total_mileage", totalMileage);
            return result;
        } catch (Exception e) {
            logger.error("FindPath failed", e);
            return Map.of("error", e.getMessage());
        }
    }

    private Map<String, List<GraphEdge>> buildGraph(Connection conn, int vehicleType) throws SQLException {
        Map<String, List<GraphEdge>> graph = new HashMap<>();
        Map<String, int[]> rateParams = loadRateParams(conn, vehicleType);

        String sql = "SELECT * FROM \"FEE_CONTIGUITY\" WHERE \"INVALID\" = FALSE";
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            while (rs.next()) {
                String enId = rs.getString("EN_ROAD_NODE_ID");
                int enType = rs.getInt("EN_ROAD_NODE_TYPE");
                String exId = rs.getString("EX_ROAD_NODE_ID");
                int exType = rs.getInt("EX_ROAD_NODE_TYPE");
                int miles = rs.getInt("MILES");
                int chargeMiles = rs.getInt("CHARGE_MILES");

                String fromKey = enId + "|" + enType;

                // 边的 tollUnitId: 如果 from 是收费单元(type=0), 则 tollUnitId = enId
                // 否则如果 to 是收费单元(type=0), 则 tollUnitId = exId
                String tollUnitId = null;
                if (enType == 0) {
                    tollUnitId = enId;
                }

                int weight = 0;
                if (tollUnitId != null) {
                    int[] params = rateParams.get(tollUnitId);
                    if (params != null) {
                        weight = params[1]; // mfee as weight
                    }
                }

                GraphEdge edge = new GraphEdge(exId, exType, tollUnitId, weight, miles, chargeMiles);
                graph.computeIfAbsent(fromKey, k -> new ArrayList<>()).add(edge);
            }
        }
        return graph;
    }

    private Map<String, int[]> loadRateParams(Connection conn, int vehicleType) throws SQLException {
        Map<String, int[]> params = new HashMap<>();
        String sql = "SELECT * FROM \"FEE_PROVINCE_RATE_PARAM\" WHERE \"VEHICLE_TYPE\" = " + vehicleType;
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            while (rs.next()) {
                String uid = rs.getString("TOLL_INTERVAL_ID");
                int fee = rs.getInt("FEE");
                int mfee = rs.getInt("MFEE");
                int efee = rs.getInt("EFEE");
                params.put(uid, new int[]{fee, mfee, efee});
            }
        }
        return params;
    }

    private String joinInts(List<Integer> list) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(list.get(i));
        }
        return sb.toString();
    }

    private static class GraphEdge {
        String toNodeId;
        int toNodeType;
        String tollUnitId;
        int weight;
        int miles;
        int chargeMiles;

        GraphEdge(String toNodeId, int toNodeType, String tollUnitId, int weight, int miles, int chargeMiles) {
            this.toNodeId = toNodeId;
            this.toNodeType = toNodeType;
            this.tollUnitId = tollUnitId;
            this.weight = weight;
            this.miles = miles;
            this.chargeMiles = chargeMiles;
        }
    }
}
