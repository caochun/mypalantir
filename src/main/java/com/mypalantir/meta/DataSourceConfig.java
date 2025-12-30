package com.mypalantir.meta;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * 数据源连接配置
 * 定义如何连接到外部数据库
 */
public class DataSourceConfig {
    @JsonProperty("id")
    private String id;

    @JsonProperty("type")
    private String type;  // postgresql, mysql, oracle, etc.

    @JsonProperty("host")
    private String host;

    @JsonProperty("port")
    private int port;

    @JsonProperty("database")
    private String database;

    @JsonProperty("username")
    private String username;

    @JsonProperty("password")
    private String password;

    @JsonProperty("jdbc_url")
    private String jdbcUrl;

    @JsonProperty("properties")
    private Map<String, Object> properties;

    @JsonIgnore
    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    @JsonIgnore
    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    @JsonIgnore
    public String getHost() {
        return host;
    }

    public void setHost(String host) {
        this.host = host;
    }

    @JsonIgnore
    public int getPort() {
        return port;
    }

    public void setPort(int port) {
        this.port = port;
    }

    @JsonIgnore
    public String getDatabase() {
        return database;
    }

    public void setDatabase(String database) {
        this.database = database;
    }

    @JsonIgnore
    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    @JsonIgnore
    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    @JsonIgnore
    public String getJdbcUrl() {
        return jdbcUrl;
    }

    public void setJdbcUrl(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @JsonIgnore
    public Map<String, Object> getProperties() {
        return properties;
    }

    public void setProperties(Map<String, Object> properties) {
        this.properties = properties;
    }

    /**
     * 构建 JDBC URL（如果未提供 jdbc_url）
     */
    public String buildJdbcUrl() {
        if (jdbcUrl != null && !jdbcUrl.isEmpty()) {
            return jdbcUrl;
        }

        // 根据类型构建默认 JDBC URL
        switch (type != null ? type.toLowerCase() : "") {
            case "postgresql":
            case "postgres":
                return String.format("jdbc:postgresql://%s:%d/%s", host, port, database);
            case "mysql":
                return String.format("jdbc:mysql://%s:%d/%s", host, port, database);
            case "oracle":
                return String.format("jdbc:oracle:thin:@%s:%d:%s", host, port, database);
            case "sqlserver":
            case "mssql":
                return String.format("jdbc:sqlserver://%s:%d;databaseName=%s", host, port, database);
            case "h2":
                // H2 支持多种模式：file, mem, tcp
                // 如果 host 是 "file" 或 "mem"，使用对应的模式
                if ("file".equalsIgnoreCase(host) || host == null || host.isEmpty()) {
                    // 文件模式：jdbc:h2:file:./data/h2/database
                    return String.format("jdbc:h2:file:./data/h2/%s", database);
                } else if ("mem".equalsIgnoreCase(host)) {
                    // 内存模式：jdbc:h2:mem:database
                    return String.format("jdbc:h2:mem:%s", database);
                } else {
                    // TCP 模式：jdbc:h2:tcp://host:port/database
                    return String.format("jdbc:h2:tcp://%s:%d/%s", host, port, database);
                }
            default:
                throw new IllegalArgumentException("Unsupported database type: " + type);
        }
    }
}

