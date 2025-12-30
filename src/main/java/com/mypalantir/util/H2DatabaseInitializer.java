package com.mypalantir.util;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;

/**
 * H2 数据库初始化工具
 */
public class H2DatabaseInitializer {
    public static void main(String[] args) {
        String jdbcUrl = "jdbc:h2:file:./data/h2/mypalantir";
        String username = "sa";
        String password = "";
        String sqlFile = args.length > 0 ? args[0] : "scripts/init_h2_tables.sql";

        try {
            // 加载 H2 驱动
            Class.forName("org.h2.Driver");

            // 连接数据库
            try (Connection conn = DriverManager.getConnection(jdbcUrl, username, password);
                 Statement stmt = conn.createStatement()) {

                // 读取 SQL 文件
                String sql = readSqlFile(sqlFile);
                
                // 执行 SQL（按分号分割）
                String[] statements = sql.split(";");
                for (String statement : statements) {
                    statement = statement.trim();
                    if (!statement.isEmpty() && !statement.startsWith("--")) {
                        try {
                            stmt.execute(statement);
                            System.out.println("✓ Executed: " + statement.substring(0, Math.min(50, statement.length())) + "...");
                        } catch (SQLException e) {
                            // 忽略已存在的表错误
                            if (!e.getMessage().contains("already exists")) {
                                System.err.println("✗ Error executing: " + statement.substring(0, Math.min(50, statement.length())));
                                System.err.println("  " + e.getMessage());
                            }
                        }
                    }
                }

                // 验证数据
                System.out.println("\n=== 数据验证 ===");
                try (var rs = stmt.executeQuery("SELECT COUNT(*) AS cnt FROM vehicles")) {
                    if (rs.next()) {
                        System.out.println("车辆数量: " + rs.getInt("cnt"));
                    }
                }
                try (var rs = stmt.executeQuery("SELECT COUNT(*) AS cnt FROM media")) {
                    if (rs.next()) {
                        System.out.println("通行介质数量: " + rs.getInt("cnt"));
                    }
                }

                System.out.println("\n✓ 数据库初始化完成！");
            }
        } catch (ClassNotFoundException e) {
            System.err.println("H2 Driver not found: " + e.getMessage());
            System.exit(1);
        } catch (SQLException e) {
            System.err.println("Database error: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        } catch (IOException e) {
            System.err.println("File error: " + e.getMessage());
            System.exit(1);
        }
    }

    private static String readSqlFile(String filePath) throws IOException {
        StringBuilder sql = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(filePath))) {
            String line;
            while ((line = reader.readLine()) != null) {
                // 跳过注释行
                if (!line.trim().startsWith("--") || line.trim().isEmpty()) {
                    sql.append(line).append("\n");
                }
            }
        }
        return sql.toString();
    }
}

