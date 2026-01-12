package com.mypalantir.meta;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonGetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * 数据源映射配置
 * 定义 ObjectType 如何映射到数据库表
 */
public class DataSourceMapping {
    /**
     * 数据源连接 ID，引用 data_sources 中的配置
     */
    @JsonProperty("connection_id")
    private String connectionId;

    /**
     * 数据库表名
     */
    @JsonProperty("table")
    private String table;

    /**
     * 主键列名（用于唯一标识实例）
     */
    @JsonProperty("id_column")
    private String idColumn;

    /**
     * 源对象ID列名（用于 LinkType，表示 source_type 的 ID）
     * 例如：对于"持有" link type，source_id_column 为 "vehicle_id"
     */
    @JsonProperty("source_id_column")
    private String sourceIdColumn;

    /**
     * 目标对象ID列名（用于 LinkType，表示 target_type 的 ID）
     * 例如：对于"持有" link type，target_id_column 为 "media_id"
     */
    @JsonProperty("target_id_column")
    private String targetIdColumn;

    /**
     * LinkType 映射模式：
     * - "foreign_key": 外键模式，关系信息存储在目标表中（通过外键）
     * - "relation_table": 关系表模式，使用独立的中间表存储关系
     * - null: 自动检测模式（如果 table 与目标表的 table 相同，则为外键模式）
     */
    @JsonProperty("link_mode")
    private String linkMode;

    /**
     * 属性映射：ObjectType/LinkType 属性名 -> 数据库列名
     * 例如：{"车牌号": "plate_number", "车辆类型": "vehicle_type"}
     * 对于 LinkType，还可以映射 link type 的属性，如 {"绑定时间": "bind_time", "绑定状态": "bind_status"}
     */
    @JsonProperty("field_mapping")
    private Map<String, String> fieldMapping;

    @JsonGetter("connection_id")
    public String getConnectionId() {
        return connectionId;
    }

    public void setConnectionId(String connectionId) {
        this.connectionId = connectionId;
    }

    @JsonGetter("table")
    public String getTable() {
        return table;
    }

    public void setTable(String table) {
        this.table = table;
    }

    @JsonGetter("id_column")
    public String getIdColumn() {
        return idColumn;
    }

    public void setIdColumn(String idColumn) {
        this.idColumn = idColumn;
    }

    @JsonGetter("source_id_column")
    public String getSourceIdColumn() {
        return sourceIdColumn;
    }

    public void setSourceIdColumn(String sourceIdColumn) {
        this.sourceIdColumn = sourceIdColumn;
    }

    @JsonGetter("target_id_column")
    public String getTargetIdColumn() {
        return targetIdColumn;
    }

    public void setTargetIdColumn(String targetIdColumn) {
        this.targetIdColumn = targetIdColumn;
    }

    @JsonGetter("link_mode")
    public String getLinkMode() {
        return linkMode;
    }

    public void setLinkMode(String linkMode) {
        this.linkMode = linkMode;
    }

    @JsonGetter("field_mapping")
    public Map<String, String> getFieldMapping() {
        return fieldMapping;
    }

    public void setFieldMapping(Map<String, String> fieldMapping) {
        this.fieldMapping = fieldMapping;
    }

    /**
     * 根据 ObjectType 属性名获取数据库列名
     */
    public String getColumnName(String propertyName) {
        if (fieldMapping == null) {
            return null;
        }
        return fieldMapping.get(propertyName);
    }

    /**
     * 根据数据库列名获取 ObjectType 属性名（反向查找）
     */
    public String getPropertyName(String columnName) {
        if (fieldMapping == null || columnName == null) {
            return null;
        }
        return fieldMapping.entrySet().stream()
            .filter(entry -> columnName.equals(entry.getValue()))
            .map(Map.Entry::getKey)
            .findFirst()
            .orElse(null);
    }

    /**
     * 检查是否有数据源映射配置
     * 对于 ObjectType：需要 connectionId, table, idColumn
     * 对于 LinkType：需要 connectionId, table, sourceIdColumn, targetIdColumn（不需要 idColumn）
     */
    public boolean isConfigured() {
        if (connectionId == null || connectionId.isEmpty() || table == null || table.isEmpty()) {
            return false;
        }
        
        // 如果有 sourceIdColumn 和 targetIdColumn，说明这是 LinkType 的配置
        if (sourceIdColumn != null && !sourceIdColumn.isEmpty() 
            && targetIdColumn != null && !targetIdColumn.isEmpty()) {
            return true; // LinkType 配置有效
        }
        
        // 否则，需要 idColumn（ObjectType 配置）
        return idColumn != null && !idColumn.isEmpty();
    }

    /**
     * 判断 LinkType 是否为外键模式
     * @param targetObjectType 目标 ObjectType（用于自动检测模式）
     * @return true 表示外键模式，false 表示关系表模式
     */
    public boolean isForeignKeyMode(ObjectType targetObjectType) {
        // 如果显式指定了 link_mode，直接使用
        if (linkMode != null) {
            return "foreign_key".equalsIgnoreCase(linkMode);
        }
        
        // 自动检测：如果 table 与目标表的 table 相同，则为外键模式
        if (targetObjectType != null && targetObjectType.getDataSource() != null) {
            DataSourceMapping targetMapping = targetObjectType.getDataSource();
            return table != null && table.equals(targetMapping.getTable());
        }
        
        // 默认返回 false（关系表模式）
        return false;
    }
}

