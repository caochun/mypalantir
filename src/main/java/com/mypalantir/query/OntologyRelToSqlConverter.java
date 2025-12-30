package com.mypalantir.query;

import com.mypalantir.meta.DataSourceMapping;
import com.mypalantir.meta.Loader;
import com.mypalantir.meta.ObjectType;
import com.mypalantir.query.schema.JdbcOntologyTable;
import com.mypalantir.query.schema.OntologyTable;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.core.TableScan;
import org.apache.calcite.rel.rel2sql.RelToSqlConverter;
import org.apache.calcite.sql.SqlDialect;
import org.apache.calcite.sql.SqlNode;

import java.util.HashMap;
import java.util.Map;

/**
 * 自定义的 RelToSqlConverter
 * 在将 RelNode 转换为 SQL 时，自动将 Ontology 表名和列名映射为数据库实际表名和列名
 * 
 * 设计理念：
 * - RelNode 保持使用 Ontology 概念（逻辑层）
 * - SQL 生成时映射为数据库名称（物理层）
 */
public class OntologyRelToSqlConverter extends RelToSqlConverter {
    private final Loader loader;
    private final SqlDialect dialect;
    // 缓存 ObjectType 名称到 DataSourceMapping 的映射
    private final Map<String, DataSourceMapping> objectTypeMappingCache = new HashMap<>();
    
    public OntologyRelToSqlConverter(SqlDialect dialect, Loader loader) {
        super(dialect);
        this.dialect = dialect;
        this.loader = loader;
    }
    
    /**
     * 重写 visit 方法，在访问 TableScan 时缓存映射信息
     */
    @Override
    public Result visit(RelNode e) {
        // 如果是 TableScan，尝试获取映射信息
        if (e instanceof TableScan) {
            TableScan scan = (TableScan) e;
            org.apache.calcite.plan.RelOptTable relOptTable = scan.getTable();
            if (relOptTable != null) {
                org.apache.calcite.schema.Table calciteTable = relOptTable.unwrap(org.apache.calcite.schema.Table.class);
                
                // 如果是 OntologyTable，获取映射信息并缓存
                if (calciteTable instanceof OntologyTable) {
                    OntologyTable ontologyTable = (OntologyTable) calciteTable;
                    ObjectType objectType = ontologyTable.getObjectType();
                    String objectTypeName = objectType.getName();
                    
                    // 获取 DataSourceMapping
                    DataSourceMapping mapping = null;
                    if (ontologyTable instanceof JdbcOntologyTable) {
                        mapping = ((JdbcOntologyTable) ontologyTable).getMapping();
                    } else {
                        mapping = objectType.getDataSource();
                    }
                    
                    if (mapping != null && mapping.isConfigured()) {
                        // 缓存映射信息，供后续使用
                        objectTypeMappingCache.put(objectTypeName, mapping);
                    }
                }
            }
        }
        
        // 调用父类方法
        return super.visit(e);
    }
    
    /**
     * 获取替换后的 SQL
     * 在调用 visitRoot 后，使用此方法获取映射后的 SQL
     */
    public String getMappedSql(Result result) {
        SqlNode sqlNode = result.asStatement();
        String sql = sqlNode.toSqlString(dialect).getSql();
        
        // 替换所有缓存的表名和列名
        for (Map.Entry<String, DataSourceMapping> entry : objectTypeMappingCache.entrySet()) {
            String objectTypeName = entry.getKey();
            DataSourceMapping mapping = entry.getValue();
            
            // 替换表名
            String dbTableName = mapping.getTable().toUpperCase();
            sql = replaceTableName(sql, objectTypeName, dbTableName);
            
            // 替换列名（需要 ObjectType 信息）
            try {
                ObjectType objectType = loader.getObjectType(objectTypeName);
                sql = replaceColumnNames(sql, objectType, mapping);
            } catch (Loader.NotFoundException ex) {
                // 忽略
            }
        }
        
        return sql;
    }
    
    /**
     * 替换 SQL 中的表名
     */
    private String replaceTableName(String sql, String ontologyTableName, String dbTableName) {
        // 替换带引号的表名
        sql = sql.replaceAll("(?i)\"" + java.util.regex.Pattern.quote(ontologyTableName) + "\"", 
                            "\"" + dbTableName + "\"");
        // 替换不带引号的表名（在 FROM 子句中）
        sql = sql.replaceAll("(?i)\\b" + java.util.regex.Pattern.quote(ontologyTableName) + "\\b", 
                            "\"" + dbTableName + "\"");
        return sql;
    }
    
    /**
     * 替换列名
     */
    private String replaceColumnNames(String sql, ObjectType objectType, DataSourceMapping mapping) {
        // 替换属性列名
        if (objectType.getProperties() != null) {
            for (com.mypalantir.meta.Property prop : objectType.getProperties()) {
                String propertyName = prop.getName();
                String columnName = mapping.getColumnName(propertyName);
                if (columnName != null) {
                    String dbColumnName = columnName.toUpperCase();
                    // 替换带引号的列名
                    sql = sql.replaceAll("\"" + java.util.regex.Pattern.quote(propertyName) + "\"", 
                                        "\"" + dbColumnName + "\"");
                    // 替换不带引号的列名
                    sql = sql.replaceAll("(?i)\\b" + java.util.regex.Pattern.quote(propertyName) + "\\b", 
                                        "\"" + dbColumnName + "\"");
                }
            }
        }
        
        // 替换 ID 列名
        String idColumnName = mapping.getIdColumn().toUpperCase();
        sql = sql.replaceAll("(?i)\"id\"", "\"" + idColumnName + "\"");
        sql = sql.replaceAll("(?i)\\bid\\b", "\"" + idColumnName + "\"");
        
        return sql;
    }
}
