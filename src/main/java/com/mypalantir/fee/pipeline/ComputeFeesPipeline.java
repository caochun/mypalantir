package com.mypalantir.fee.pipeline;

import com.mypalantir.reasoning.function.builtin.AbstractBuiltinFunction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.util.*;

/**
 * R1-R3 计费参数生成管道。
 * 为每个(收费单元, 车型)计算 fee/mfee/efee 并写入 FEE_PROVINCE_RATE_PARAM。
 */
public class ComputeFeesPipeline extends AbstractBuiltinFunction {

    private static final Logger logger = LoggerFactory.getLogger(ComputeFeesPipeline.class);
    private final String jdbcUrl;

    public ComputeFeesPipeline(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @Override
    public String getName() {
        return "compute_fees";
    }

    @Override
    public Object execute(List<Object> args) {
        String vehicleTypesStr = args.isEmpty() ? "1,2,3,4,11,12,13,14,15,16" : args.get(0).toString();
        List<Integer> vehicleTypes = new ArrayList<>();
        for (String s : vehicleTypesStr.split(",")) {
            vehicleTypes.add(Integer.parseInt(s.trim()));
        }

        try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "")) {
            List<Map<String, Object>> units = queryAll(conn, "FEE_TOLL_UNIT");
            List<Map<String, Object>> rates = queryAll(conn, "FEE_BASE_RATE");
            List<Map<String, Object>> discounts = queryAll(conn, "FEE_SPECIAL_TIME_DISCOUNT");

            try (Statement stmt = conn.createStatement()) {
                stmt.executeUpdate("DELETE FROM \"FEE_PROVINCE_RATE_PARAM\"");
            }

            Map<String, Map<Integer, Double>> rateMap = new HashMap<>();
            for (Map<String, Object> r : rates) {
                String rateCode = str(r, "RATECODE");
                int vc = intVal(r, "VC");
                double vcRate = doubleVal(r, "VCRATE");
                rateMap.computeIfAbsent(rateCode, k -> new HashMap<>()).put(vc, vcRate);
            }

            Map<String, List<Map<String, Object>>> discountByUnit = new HashMap<>();
            for (Map<String, Object> d : discounts) {
                String uid = str(d, "TOLLINTERVALID");
                discountByUnit.computeIfAbsent(uid, k -> new ArrayList<>()).add(d);
            }

            String insertSql = "INSERT INTO \"FEE_PROVINCE_RATE_PARAM\" " +
                    "(\"TOLL_INTERVAL_ID\", \"VEHICLE_TYPE\", \"FEE\", \"MFEE\", \"EFEE\", \"RATE_SOURCE\", \"LASTVER\") " +
                    "VALUES (?, ?, ?, ?, ?, ?, ?)";

            int paramsCreated = 0;
            int r3Errors = 0;

            try (PreparedStatement ps = conn.prepareStatement(insertSql)) {
                for (Map<String, Object> unit : units) {
                    String unitId = str(unit, "TOLLINTERVALID");
                    String rateCode = str(unit, "RATECODE");
                    int chargeLength = intVal(unit, "CHARGELENGTH");
                    String lastver = str(unit, "LASTVER");

                    Map<Integer, Double> vcRates = rateMap.get(rateCode);
                    if (vcRates == null) {
                        r3Errors++;
                        logger.warn("R3: No BaseRate for rateCode={} (unit={})", rateCode, unitId);
                        continue;
                    }

                    for (int vc : vehicleTypes) {
                        Double vcRate = vcRates.get(vc);
                        if (vcRate == null) {
                            r3Errors++;
                            continue;
                        }

                        // R1: 计算基础费额
                        int fee;
                        int rateCodeVal;
                        try {
                            rateCodeVal = Integer.parseInt(rateCode);
                        } catch (NumberFormatException e) {
                            rateCodeVal = 0;
                        }

                        if (rateCodeVal < 50) {
                            fee = (int) Math.round(vcRate * chargeLength);
                        } else {
                            fee = (int) Math.round(vcRate);
                        }

                        // R2: 计算 mfee/efee
                        int mfee;
                        int efee;
                        String rateSource;

                        List<Map<String, Object>> unitDiscounts = discountByUnit.get(unitId);
                        Map<String, Object> fullDayDiscount = findFullDayDiscount(unitDiscounts, vc);

                        if (fullDayDiscount != null) {
                            int cpcDiscount = intVal(fullDayDiscount, "CPCDISCOUNT");
                            int etcDiscount = intVal(fullDayDiscount, "ETCDISCOUNT");
                            mfee = (int) Math.round(fee * (1000.0 - cpcDiscount) / 1000.0);
                            efee = (int) Math.round(fee * (1000.0 - etcDiscount) / 1000.0);
                            rateSource = "discount";
                        } else {
                            mfee = fee;
                            efee = (int) Math.round(fee * 0.95);
                            rateSource = "default";
                        }

                        ps.setString(1, unitId);
                        ps.setInt(2, vc);
                        ps.setInt(3, fee);
                        ps.setInt(4, mfee);
                        ps.setInt(5, efee);
                        ps.setString(6, rateSource);
                        ps.setString(7, lastver);
                        ps.addBatch();
                        paramsCreated++;
                    }
                }
                ps.executeBatch();
            }

            logger.info("ComputeFees: {} params created, {} R3 errors", paramsCreated, r3Errors);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("params_created", paramsCreated);
            result.put("r3_errors", r3Errors);
            return result;
        } catch (Exception e) {
            logger.error("ComputeFees failed", e);
            return Map.of("error", e.getMessage());
        }
    }

    private Map<String, Object> findFullDayDiscount(List<Map<String, Object>> discounts, int vc) {
        if (discounts == null) return null;
        for (Map<String, Object> d : discounts) {
            int startHour = intVal(d, "STARTHOUR");
            int endHour = intVal(d, "ENDHOUR");
            if (startHour == 0 && endHour == 24) {
                String vType = str(d, "VEHILCETYPE");
                if (vType != null && vType.equals(String.valueOf(vc))) {
                    return d;
                }
            }
        }
        return null;
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

    private double doubleVal(Map<String, Object> m, String key) {
        Object v = m.get(key);
        if (v instanceof Number) return ((Number) v).doubleValue();
        if (v instanceof String) {
            try { return Double.parseDouble((String) v); } catch (NumberFormatException e) { return 0; }
        }
        return 0;
    }
}
