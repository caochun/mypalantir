package com.mypalantir.query.schema;

import com.mypalantir.meta.DataSourceMapping;
import com.mypalantir.meta.ObjectType;
import com.mypalantir.meta.Property;
import org.apache.calcite.DataContext;
import org.apache.calcite.linq4j.Enumerable;
import org.apache.calcite.linq4j.Linq4j;
import org.apache.calcite.rel.type.RelDataType;
import org.apache.calcite.rel.type.RelDataTypeFactory;
import org.apache.calcite.schema.ScannableTable;
import org.apache.calcite.schema.impl.AbstractTable;
import org.apache.calcite.sql.type.SqlTypeName;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 基于 JDBC 的 Ontology Table
 * 将 ObjectType 映射到数据库表
 * 实现 ScannableTable 接口，支持扫描查询
 */
public class JdbcOntologyTable extends OntologyTable implements ScannableTable {
    private final DataSourceMapping mapping;
    private final Connection connection;

    public JdbcOntologyTable(ObjectType objectType, DataSourceMapping mapping, Connection connection) {
        super(objectType);
        this.mapping = mapping;
        this.connection = connection;
    }

    @Override
    protected RelDataType buildRowType(RelDataTypeFactory typeFactory) {
        List<RelDataTypeFactory.Builder> builder = new ArrayList<>();
        RelDataTypeFactory.Builder typeBuilder = typeFactory.builder();

        // 定义 UTF-8 字符集和排序规则（复用）
        org.apache.calcite.sql.SqlCollation collation = org.apache.calcite.sql.SqlCollation.COERCIBLE;

        // 添加 ID 字段（VARCHAR 类型，指定 UTF-8 字符集）
        RelDataType varcharType = typeFactory.createSqlType(
            SqlTypeName.VARCHAR,
            org.apache.calcite.rel.type.RelDataType.PRECISION_NOT_SPECIFIED
        );
        // 为 VARCHAR 类型指定 UTF-8 字符集和排序规则
        RelDataType idType = typeFactory.createTypeWithCharsetAndCollation(
            varcharType,
            java.nio.charset.StandardCharsets.UTF_8,
            collation
        );
        typeBuilder.add("id", idType);

        // 添加所有属性字段
        if (objectType.getProperties() != null) {
            for (Property prop : objectType.getProperties()) {
                SqlTypeName sqlType = mapPropertyTypeToSqlType(prop.getDataType());
                RelDataType fieldType;
                
                // 对于字符串类型，指定 UTF-8 字符集和排序规则
                if (sqlType == SqlTypeName.VARCHAR || sqlType == SqlTypeName.CHAR) {
                    RelDataType baseType = typeFactory.createSqlType(
                        sqlType,
                        org.apache.calcite.rel.type.RelDataType.PRECISION_NOT_SPECIFIED
                    );
                    fieldType = typeFactory.createTypeWithCharsetAndCollation(
                        baseType,
                        java.nio.charset.StandardCharsets.UTF_8,
                        collation
                    );
                } else {
                    fieldType = typeFactory.createSqlType(sqlType);
                }
                
                typeBuilder.add(prop.getName(), fieldType);
            }
        }

        return typeBuilder.build();
    }

    /**
     * 将 Property 的 data_type 映射到 SQL 类型
     */
    private SqlTypeName mapPropertyTypeToSqlType(String dataType) {
        if (dataType == null) {
            return SqlTypeName.VARCHAR;
        }
        
        switch (dataType.toLowerCase()) {
            case "string":
                return SqlTypeName.VARCHAR;
            case "int":
            case "integer":
                return SqlTypeName.INTEGER;
            case "float":
            case "double":
                return SqlTypeName.DOUBLE;
            case "date":
                return SqlTypeName.DATE;
            case "datetime":
            case "timestamp":
                return SqlTypeName.TIMESTAMP;
            case "boolean":
            case "bool":
                return SqlTypeName.BOOLEAN;
            default:
                return SqlTypeName.VARCHAR;
        }
    }

    /**
     * 获取数据库表名
     */
    public String getTableName() {
        return mapping.getTable();
    }

    /**
     * 获取 ID 列名
     */
    public String getIdColumnName() {
        return mapping.getIdColumn();
    }

    /**
     * 根据属性名获取数据库列名
     */
    public String getColumnName(String propertyName) {
        return mapping.getColumnName(propertyName);
    }

    /**
     * 获取 JDBC 连接
     */
    public Connection getConnection() {
        return connection;
    }

    /**
     * 获取数据源映射
     */
    public DataSourceMapping getMapping() {
        return mapping;
    }

    /**
     * 实现 ScannableTable 接口，扫描表数据
     */
    @Override
    public Enumerable<Object[]> scan(DataContext root) {
        try {
            // 构建 SQL 查询
            // 注意：这里使用数据库表名和列名，然后通过 AS 别名映射回 Ontology 属性名
            String sql = buildSelectSql();
            
            // 执行查询
            List<Object[]> rows = new ArrayList<>();
            try (Statement stmt = connection.createStatement();
                 ResultSet rs = stmt.executeQuery(sql)) {
                
                while (rs.next()) {
                    Object[] row = buildRow(rs);
                    rows.add(row);
                }
            }
            
            return Linq4j.asEnumerable(rows);
        } catch (Exception e) {
            throw new RuntimeException("Failed to scan table: " + e.getMessage(), e);
        }
    }

    /**
     * 构建 SELECT SQL 语句
     */
    private String buildSelectSql() {
        StringBuilder sql = new StringBuilder("SELECT ");
        
        // H2 数据库默认将未加引号的标识符转换为大写
        // 但如果我们使用引号，则保持原始大小写
        // 为了兼容，我们使用大写列名（H2 的默认行为）
        String idColumn = mapping.getIdColumn().toUpperCase();
        sql.append(quoteIdentifier(idColumn)).append(" AS id");
        
        // 添加所有属性列
        if (objectType.getProperties() != null) {
            for (Property prop : objectType.getProperties()) {
                String columnName = mapping.getColumnName(prop.getName());
                if (columnName != null) {
                    // 使用大写列名（H2 的默认行为）
                    sql.append(", ").append(quoteIdentifier(columnName.toUpperCase()))
                       .append(" AS ").append(quoteIdentifier(prop.getName()));
                } else {
                    // 如果没有映射，直接使用属性名作为列名（用于外键列，如 vehicle_id, media_id）
                    sql.append(", ").append(quoteIdentifier(prop.getName().toUpperCase()))
                       .append(" AS ").append(quoteIdentifier(prop.getName()));
                }
            }
        }
        
        // H2 数据库默认将未加引号的标识符转换为大写
        // 但如果我们使用引号，则保持原始大小写
        // 为了兼容，我们使用大写表名（H2 的默认行为）
        String tableName = mapping.getTable().toUpperCase();
        sql.append(" FROM ").append(quoteIdentifier(tableName));
        
        return sql.toString();
    }

    /**
     * 构建行数据
     * 注意：返回的数组顺序必须与 buildRowType() 中定义的字段顺序完全一致
     */
    private Object[] buildRow(ResultSet rs) throws Exception {
        List<Object> row = new ArrayList<>();
        
        // 1. ID（索引 0）
        row.add(rs.getString("id"));
        
        // 2. 属性（按 objectType.getProperties() 的顺序）
        if (objectType.getProperties() != null) {
            for (Property prop : objectType.getProperties()) {
                String columnName = mapping.getColumnName(prop.getName());
                if (columnName != null) {
                    // 使用属性名作为别名从 ResultSet 中获取值
                    Object value = rs.getObject(prop.getName());
                    row.add(value);
                } else {
                    // 如果没有映射，可能是外键列（如 vehicle_id, media_id）
                    // 尝试直接使用属性名作为列名
                    try {
                        Object value = rs.getObject(prop.getName());
                        row.add(value);
                    } catch (Exception e) {
                        // 如果获取失败，返回 null
                        row.add(null);
                    }
                }
            }
        }
        
        return row.toArray();
    }

    /**
     * 引用标识符（根据数据库类型）
     */
    private String quoteIdentifier(String identifier) {
        // H2 使用双引号，并且标识符会被转换为大写（除非使用引号）
        // 为了保持大小写，我们使用双引号
        return "\"" + identifier + "\"";
    }
}

