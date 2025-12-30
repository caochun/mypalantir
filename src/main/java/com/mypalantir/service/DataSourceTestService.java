package com.mypalantir.service;

import com.mypalantir.meta.DataSourceConfig;
import com.mypalantir.meta.Loader;
import org.springframework.stereotype.Service;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.Map;

/**
 * 数据源连接测试服务
 */
@Service
public class DataSourceTestService {
    private final Loader loader;

    public DataSourceTestService(Loader loader) {
        this.loader = loader;
    }

    /**
     * 测试数据源连接
     */
    public TestResult testConnection(String dataSourceId) {
        try {
            DataSourceConfig config = loader.getDataSourceById(dataSourceId);
            return testConnection(config);
        } catch (Loader.NotFoundException e) {
            return TestResult.failure("Data source not found: " + dataSourceId);
        }
    }

    /**
     * 测试数据源连接
     */
    public TestResult testConnection(DataSourceConfig config) {
        String jdbcUrl = config.getJdbcUrl() != null && !config.getJdbcUrl().isEmpty()
            ? config.getJdbcUrl()
            : config.buildJdbcUrl();

        String username = config.getUsername();
        String password = config.getPassword() != null ? config.getPassword() : "";

        // 处理环境变量（简单处理，实际可以使用 Spring 的 Environment）
        password = resolveEnvironmentVariable(password);
        username = resolveEnvironmentVariable(username);

        Connection connection = null;
        try {
            // 加载 JDBC 驱动
            loadDriver(config.getType());

            // 尝试连接
            connection = DriverManager.getConnection(jdbcUrl, username, password);

            // 执行简单查询验证连接
            boolean isValid = connection.isValid(5); // 5秒超时

            if (isValid) {
                // 获取数据库元信息
                String databaseProductName = connection.getMetaData().getDatabaseProductName();
                String databaseProductVersion = connection.getMetaData().getDatabaseProductVersion();
                String driverName = connection.getMetaData().getDriverName();
                String driverVersion = connection.getMetaData().getDriverVersion();

                Map<String, String> metadata = new HashMap<>();
                metadata.put("databaseProductName", databaseProductName);
                metadata.put("databaseProductVersion", databaseProductVersion);
                metadata.put("driverName", driverName);
                metadata.put("driverVersion", driverVersion);

                return TestResult.success("Connection successful", metadata);
            } else {
                return TestResult.failure("Connection is not valid");
            }
        } catch (SQLException e) {
            return TestResult.failure("Connection failed: " + e.getMessage());
        } catch (ClassNotFoundException e) {
            return TestResult.failure("JDBC driver not found: " + e.getMessage());
        } catch (Exception e) {
            return TestResult.failure("Unexpected error: " + e.getMessage());
        } finally {
            if (connection != null) {
                try {
                    connection.close();
                } catch (SQLException e) {
                    // 忽略关闭连接时的错误
                }
            }
        }
    }

    /**
     * 加载 JDBC 驱动
     */
    private void loadDriver(String dbType) throws ClassNotFoundException {
        switch (dbType != null ? dbType.toLowerCase() : "") {
            case "postgresql":
            case "postgres":
                Class.forName("org.postgresql.Driver");
                break;
            case "mysql":
                Class.forName("com.mysql.cj.jdbc.Driver");
                break;
            case "h2":
                Class.forName("org.h2.Driver");
                break;
            case "oracle":
                Class.forName("oracle.jdbc.driver.OracleDriver");
                break;
            case "sqlserver":
            case "mssql":
                Class.forName("com.microsoft.sqlserver.jdbc.SQLServerDriver");
                break;
            default:
                throw new ClassNotFoundException("Unsupported database type: " + dbType);
        }
    }

    /**
     * 解析环境变量（简单实现）
     * 实际应该使用 Spring Environment 或 System.getenv()
     */
    private String resolveEnvironmentVariable(String value) {
        if (value == null) {
            return "";
        }
        // 简单处理：如果值包含 ${VAR} 格式，尝试从环境变量获取
        if (value.startsWith("${") && value.endsWith("}")) {
            String varName = value.substring(2, value.length() - 1);
            String envValue = System.getenv(varName);
            return envValue != null ? envValue : value;
        }
        return value;
    }

    /**
     * 测试结果
     */
    public static class TestResult {
        private final boolean success;
        private final String message;
        private final Map<String, String> metadata;

        private TestResult(boolean success, String message, Map<String, String> metadata) {
            this.success = success;
            this.message = message;
            this.metadata = metadata != null ? metadata : new HashMap<>();
        }

        public static TestResult success(String message, Map<String, String> metadata) {
            return new TestResult(true, message, metadata);
        }

        public static TestResult failure(String message) {
            return new TestResult(false, message, null);
        }

        public boolean isSuccess() {
            return success;
        }

        public String getMessage() {
            return message;
        }

        public Map<String, String> getMetadata() {
            return metadata;
        }
    }
}

