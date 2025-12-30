package com.mypalantir.query;

import java.util.List;
import java.util.Map;

/**
 * Ontology 查询 DSL 的 Java 表示
 * 类似 GraphQL 的查询结构
 */
public class OntologyQuery {
    /**
     * 查询的根对象类型
     */
    private String from;
    
    /**
     * 查询条件（where 子句）
     */
    private Map<String, Object> where;
    
    /**
     * 要选择的字段列表
     */
    private List<String> select;
    
    /**
     * 关联查询（通过 link types）
     */
    private List<LinkQuery> links;
    
    /**
     * 限制返回数量
     */
    private Integer limit;
    
    /**
     * 偏移量
     */
    private Integer offset;
    
    /**
     * 排序
     */
    private List<OrderBy> orderBy;

    public String getFrom() {
        return from;
    }

    public void setFrom(String from) {
        this.from = from;
    }

    public Map<String, Object> getWhere() {
        return where;
    }

    public void setWhere(Map<String, Object> where) {
        this.where = where;
    }

    public List<String> getSelect() {
        return select;
    }

    public void setSelect(List<String> select) {
        this.select = select;
    }

    public List<LinkQuery> getLinks() {
        return links;
    }

    public void setLinks(List<LinkQuery> links) {
        this.links = links;
    }

    public Integer getLimit() {
        return limit;
    }

    public void setLimit(Integer limit) {
        this.limit = limit;
    }

    public Integer getOffset() {
        return offset;
    }

    public void setOffset(Integer offset) {
        this.offset = offset;
    }

    public List<OrderBy> getOrderBy() {
        return orderBy;
    }

    public void setOrderBy(List<OrderBy> orderBy) {
        this.orderBy = orderBy;
    }

    /**
     * 关联查询
     */
    public static class LinkQuery {
        /**
         * Link type 名称
         */
        private String name;
        
        /**
         * 要选择的字段列表
         */
        private List<String> select;
        
        /**
         * 嵌套的关联查询
         */
        private List<LinkQuery> links;
        
        /**
         * 查询条件
         */
        private Map<String, Object> where;

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public List<String> getSelect() {
            return select;
        }

        public void setSelect(List<String> select) {
            this.select = select;
        }

        public List<LinkQuery> getLinks() {
            return links;
        }

        public void setLinks(List<LinkQuery> links) {
            this.links = links;
        }

        public Map<String, Object> getWhere() {
            return where;
        }

        public void setWhere(Map<String, Object> where) {
            this.where = where;
        }
    }

    /**
     * 排序
     */
    public static class OrderBy {
        private String field;
        private String direction; // ASC or DESC

        public OrderBy() {
        }

        public OrderBy(String field, String direction) {
            this.field = field;
            this.direction = direction;
        }

        public String getField() {
            return field;
        }

        public void setField(String field) {
            this.field = field;
        }

        public String getDirection() {
            return direction;
        }

        public void setDirection(String direction) {
            this.direction = direction;
        }
    }
}

