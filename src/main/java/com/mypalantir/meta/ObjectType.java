package com.mypalantir.meta;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonGetter;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

public class ObjectType {
    @JsonProperty("name")
    private String name;

    @JsonProperty("display_name")
    private String displayName;

    @JsonProperty("description")
    private String description;

    @JsonProperty("base_type")
    private String baseType;

    @JsonProperty("properties")
    private List<Property> properties;

    @JsonProperty("data_source")
    private DataSourceMapping dataSource;

    @JsonIgnore
    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    @JsonGetter("display_name")
    public String getDisplayName() {
        return displayName;
    }

    public void setDisplayName(String displayName) {
        this.displayName = displayName;
    }

    @JsonIgnore
    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    @JsonIgnore
    public String getBaseType() {
        return baseType;
    }

    public void setBaseType(String baseType) {
        this.baseType = baseType;
    }

    @JsonIgnore
    public List<Property> getProperties() {
        return properties;
    }

    public void setProperties(List<Property> properties) {
        this.properties = properties;
    }

    @JsonGetter("data_source")
    public DataSourceMapping getDataSource() {
        return dataSource;
    }

    public void setDataSource(DataSourceMapping dataSource) {
        this.dataSource = dataSource;
    }

    /**
     * 检查是否有数据源配置
     */
    @JsonIgnore
    public boolean hasDataSource() {
        return dataSource != null && dataSource.isConfigured();
    }
}
