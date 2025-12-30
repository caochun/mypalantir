package com.mypalantir.util;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

/**
 * 验证 H2 数据库中的数据
 */
public class H2DataVerifier {
    public static void main(String[] args) {
        String jdbcUrl = "jdbc:h2:file:./data/h2/mypalantir";
        String username = "sa";
        String password = "";

        try {
            Class.forName("org.h2.Driver");
            try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
                 Statement stmt = conn.createStatement()) {

                System.out.println("=== 车辆与通行介质关联关系 ===\n");
                
                String sql = "SELECT " +
                    "v.vehicle_id, " +
                    "v.plate_number, " +
                    "v.vehicle_type, " +
                    "v.owner_name, " +
                    "m.media_number, " +
                    "m.media_type, " +
                    "m.issue_date " +
                    "FROM vehicles v " +
                    "LEFT JOIN media m ON v.obu_id = m.media_id " +
                    "ORDER BY v.plate_number";
                
                try (ResultSet rs = stmt.executeQuery(sql)) {
                    System.out.printf("%-10s %-12s %-12s %-10s %-15s %-10s %-12s%n", 
                        "车辆ID", "车牌号", "车辆类型", "车主", "介质编号", "介质类型", "发行日期");
                    System.out.println("----------------------------------------------------------------------------");
                    
                    while (rs.next()) {
                        System.out.printf("%-10s %-12s %-12s %-10s %-15s %-10s %-12s%n",
                            rs.getString("vehicle_id"),
                            rs.getString("plate_number"),
                            rs.getString("vehicle_type"),
                            rs.getString("owner_name"),
                            rs.getString("media_number"),
                            rs.getString("media_type"),
                            rs.getString("issue_date"));
                    }
                }
                
                System.out.println("\n=== 统计信息 ===");
                try (ResultSet rs = stmt.executeQuery("SELECT COUNT(*) AS cnt FROM vehicles")) {
                    if (rs.next()) {
                        System.out.println("车辆总数: " + rs.getInt("cnt"));
                    }
                }
                try (ResultSet rs = stmt.executeQuery("SELECT COUNT(*) AS cnt FROM media")) {
                    if (rs.next()) {
                        System.out.println("通行介质总数: " + rs.getInt("cnt"));
                    }
                }
                try (ResultSet rs = stmt.executeQuery("SELECT COUNT(*) AS cnt FROM vehicles WHERE obu_id IS NOT NULL")) {
                    if (rs.next()) {
                        System.out.println("已关联OBU的车辆数: " + rs.getInt("cnt"));
                    }
                }
                
                // 验证一对一关系（每个车辆最多一个OBU，每个OBU最多被一个车辆使用）
                System.out.println("\n=== 一对一关系验证 ===");
                try (ResultSet rs = stmt.executeQuery(
                    "SELECT obu_id, COUNT(*) AS cnt FROM vehicles WHERE obu_id IS NOT NULL GROUP BY obu_id HAVING COUNT(*) > 1")) {
                    if (rs.next()) {
                        System.out.println("✗ 发现违反一对一关系的记录！");
                    } else {
                        System.out.println("✓ 一对一关系验证通过：每个车辆最多关联一个OBU");
                    }
                }
                
                try (ResultSet rs = stmt.executeQuery(
                    "SELECT m.media_id, COUNT(v.vehicle_id) AS cnt FROM media m " +
                    "LEFT JOIN vehicles v ON m.media_id = v.obu_id " +
                    "GROUP BY m.media_id HAVING COUNT(v.vehicle_id) > 1")) {
                    if (rs.next()) {
                        System.out.println("✗ 发现违反一对一关系的记录！");
                    } else {
                        System.out.println("✓ 一对一关系验证通过：每个OBU最多被一个车辆使用");
                    }
                }
            }
        } catch (ClassNotFoundException | SQLException e) {
            System.err.println("Error: " + e.getMessage());
            e.printStackTrace();
        }
    }
}

