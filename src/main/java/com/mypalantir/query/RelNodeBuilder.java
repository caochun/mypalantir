package com.mypalantir.query;

import com.mypalantir.meta.DataSourceMapping;
import com.mypalantir.meta.Loader;
import com.mypalantir.meta.ObjectType;
import com.mypalantir.meta.Property;
import com.mypalantir.query.schema.OntologySchemaFactory;
import org.apache.calcite.jdbc.CalciteConnection;
import org.apache.calcite.plan.RelOptPlanner;
import org.apache.calcite.plan.volcano.VolcanoPlanner;
import org.apache.calcite.rel.RelCollation;
import org.apache.calcite.rel.RelCollations;
import org.apache.calcite.rel.RelFieldCollation;
import org.apache.calcite.rel.RelNode;
import org.apache.calcite.rel.core.Sort;
import org.apache.calcite.rel.logical.LogicalTableScan;
import org.apache.calcite.rel.type.RelDataType;
import org.apache.calcite.rel.type.RelDataTypeFactory;
import org.apache.calcite.rex.RexBuilder;
import org.apache.calcite.rex.RexInputRef;
import org.apache.calcite.rex.RexNode;
import org.apache.calcite.schema.SchemaPlus;
import org.apache.calcite.sql.SqlKind;
import org.apache.calcite.sql.type.SqlTypeName;
import org.apache.calcite.tools.FrameworkConfig;
import org.apache.calcite.tools.Frameworks;
import org.apache.calcite.tools.RelBuilder;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 将 OntologyQuery 直接构建为 RelNode
 */
public class RelNodeBuilder {
    private final Loader loader;
    private final OntologySchemaFactory schemaFactory;
    SchemaPlus rootSchema;  // package-private for access from QueryExecutor
    FrameworkConfig frameworkConfig;  // package-private for access from QueryExecutor
    private RelBuilder relBuilder;

    public RelNodeBuilder(Loader loader) {
        this.loader = loader;
        this.schemaFactory = new OntologySchemaFactory(loader);
    }

    /**
     * 初始化
     */
    public void initialize() throws SQLException {
        // 创建 Calcite Schema
        rootSchema = schemaFactory.createCalciteSchema();
        
        // 创建 FrameworkConfig
        frameworkConfig = Frameworks.newConfigBuilder()
            .defaultSchema(rootSchema)
            .build();
        
        // 创建 RelBuilder
        relBuilder = RelBuilder.create(frameworkConfig);
    }

    /**
     * 将 OntologyQuery 构建为 RelNode
     */
    public RelNode buildRelNode(OntologyQuery query) throws Exception {
        if (rootSchema == null) {
            initialize();
        }

        // 获取 ObjectType
        ObjectType objectType;
        try {
            objectType = loader.getObjectType(query.getFrom());
        } catch (Loader.NotFoundException e) {
            throw new IllegalArgumentException("Object type '" + query.getFrom() + "' not found");
        }

        DataSourceMapping dataSourceMapping = objectType.getDataSource();

        // 1. 构建 TableScan
        RelNode scan = buildTableScan(query.getFrom());
        
        // 2. 构建 Filter（WHERE）
        if (query.getWhere() != null && !query.getWhere().isEmpty()) {
            scan = buildFilter(scan, query.getWhere(), objectType, dataSourceMapping);
        }
        
        // 3. 构建 Project（SELECT）
        if (query.getSelect() != null && !query.getSelect().isEmpty()) {
            scan = buildProject(scan, query.getSelect(), objectType);
        }
        
        // 4. 构建 Sort（ORDER BY）
        if (query.getOrderBy() != null && !query.getOrderBy().isEmpty()) {
            scan = buildSort(scan, query.getOrderBy(), objectType, dataSourceMapping);
        }
        
        // 5. 构建 Limit
        if (query.getLimit() != null && query.getLimit() > 0) {
            scan = buildLimit(scan, query.getLimit(), query.getOffset());
        }
        
        return scan;
    }

    /**
     * 构建 TableScan
     */
    private RelNode buildTableScan(String tableName) {
        relBuilder.clear();
        relBuilder.scan(tableName);
        return relBuilder.build();
    }

    /**
     * 构建 Filter（WHERE 条件）
     */
    private RelNode buildFilter(RelNode input, Map<String, Object> where, 
                               ObjectType objectType, DataSourceMapping dataSourceMapping) {
        relBuilder.clear();
        relBuilder.push(input);
        
        RelDataType rowType = input.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        List<RexNode> conditions = new ArrayList<>();
        
        for (Map.Entry<String, Object> entry : where.entrySet()) {
            String propertyName = entry.getKey();
            Object value = entry.getValue();
            
            // 找到属性在行类型中的索引
            int fieldIndex = findFieldIndex(propertyName, objectType, rowType);
            if (fieldIndex < 0) {
                continue; // 跳过不存在的字段
            }
            
            // 构建 RexInputRef（列引用）
            RexInputRef inputRef = rexBuilder.makeInputRef(rowType.getFieldList().get(fieldIndex).getType(), fieldIndex);
            
            // 构建 RexNode（常量值）
            RexNode literal = buildLiteral(rexBuilder, value, rowType.getFieldList().get(fieldIndex).getType());
            
            // 构建等值条件
            RexNode condition = rexBuilder.makeCall(
                org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
                inputRef,
                literal
            );
            
            conditions.add(condition);
        }
        
        // 组合所有条件（AND）
        if (!conditions.isEmpty()) {
            RexNode combinedCondition = conditions.size() == 1 
                ? conditions.get(0)
                : rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.AND, conditions);
            relBuilder.filter(combinedCondition);
        }
        
        return relBuilder.build();
    }

    /**
     * 构建 Project（SELECT）
     */
    private RelNode buildProject(RelNode input, List<String> selectFields, ObjectType objectType) {
        relBuilder.clear();
        relBuilder.push(input);
        
        RelDataType rowType = input.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        List<RexNode> projects = new ArrayList<>();
        List<String> fieldNames = new ArrayList<>();
        
        for (String propertyName : selectFields) {
            int fieldIndex = findFieldIndex(propertyName, objectType, rowType);
            if (fieldIndex >= 0) {
                RexInputRef inputRef = rexBuilder.makeInputRef(
                    rowType.getFieldList().get(fieldIndex).getType(),
                    fieldIndex
                );
                projects.add(inputRef);
                fieldNames.add(propertyName);
            }
        }
        
        if (!projects.isEmpty()) {
            relBuilder.project(projects, fieldNames);
        }
        
        return relBuilder.build();
    }

    /**
     * 构建 Sort（ORDER BY）
     */
    private RelNode buildSort(RelNode input, List<OntologyQuery.OrderBy> orderByList,
                             ObjectType objectType, DataSourceMapping dataSourceMapping) {
        relBuilder.clear();
        relBuilder.push(input);
        
        RelDataType rowType = input.getRowType();
        List<RelFieldCollation> fieldCollations = new ArrayList<>();
        
        for (OntologyQuery.OrderBy orderBy : orderByList) {
            String propertyName = orderBy.getField();
            int fieldIndex = findFieldIndex(propertyName, objectType, rowType);
            
            if (fieldIndex >= 0) {
                RelFieldCollation.Direction direction = "DESC".equalsIgnoreCase(orderBy.getDirection())
                    ? RelFieldCollation.Direction.DESCENDING
                    : RelFieldCollation.Direction.ASCENDING;
                
                fieldCollations.add(new RelFieldCollation(fieldIndex, direction));
            }
        }
        
        if (!fieldCollations.isEmpty()) {
            RelCollation collation = RelCollations.of(fieldCollations);
            relBuilder.sort(collation);
        }
        
        return relBuilder.build();
    }

    /**
     * 构建 Limit
     */
    private RelNode buildLimit(RelNode input, Integer limit, Integer offset) {
        relBuilder.clear();
        relBuilder.push(input);
        
        if (offset != null && offset > 0) {
            relBuilder.limit(offset, limit);
        } else {
            relBuilder.limit(0, limit);
        }
        
        return relBuilder.build();
    }

    /**
     * 查找字段在行类型中的索引
     */
    private int findFieldIndex(String propertyName, ObjectType objectType, RelDataType rowType) {
        // 行类型的第一列是 id，然后是属性
        // 需要根据属性名找到对应的索引
        
        List<org.apache.calcite.rel.type.RelDataTypeField> fields = rowType.getFieldList();
        
        // 跳过 id 字段（索引 0）
        if (objectType.getProperties() != null) {
            int propertyIndex = 0;
            for (Property prop : objectType.getProperties()) {
                if (prop.getName().equals(propertyName)) {
                    // 索引 = 1 (id) + propertyIndex
                    int fieldIndex = 1 + propertyIndex;
                    if (fieldIndex < fields.size()) {
                        return fieldIndex;
                    }
                }
                propertyIndex++;
            }
        }
        
        return -1;
    }

    /**
     * 构建字面量
     */
    private RexNode buildLiteral(RexBuilder rexBuilder, Object value, RelDataType type) {
        if (value == null) {
            return rexBuilder.makeNullLiteral(type);
        }
        
        SqlTypeName sqlTypeName = type.getSqlTypeName();
        
        switch (sqlTypeName) {
            case VARCHAR:
            case CHAR:
                // 使用 NlsString 确保 Unicode 字符（如中文）正确处理
                // 指定字符集为 UTF-8，避免编码错误
                // 使用 COERCIBLE collation 确保与列类型匹配
                org.apache.calcite.sql.SqlCollation collation = org.apache.calcite.sql.SqlCollation.COERCIBLE;
                org.apache.calcite.util.NlsString nlsString = new org.apache.calcite.util.NlsString(
                    value.toString(),
                    "UTF-8",
                    collation
                );
                return rexBuilder.makeLiteral(nlsString, type, false);
            case INTEGER:
                if (value instanceof Number) {
                    return rexBuilder.makeLiteral(
                        ((Number) value).longValue(),
                        type,
                        false
                    );
                }
                break;
            case DOUBLE:
            case FLOAT:
                if (value instanceof Number) {
                    return rexBuilder.makeLiteral(
                        ((Number) value).doubleValue(),
                        type,
                        false
                    );
                }
                break;
            case BOOLEAN:
                if (value instanceof Boolean) {
                    return rexBuilder.makeLiteral((Boolean) value, type, false);
                }
                break;
            case DATE:
            case TIMESTAMP:
                // 日期类型需要特殊处理
                return rexBuilder.makeLiteral(value.toString(), type, false);
            default:
                return rexBuilder.makeLiteral(value.toString(), type, false);
        }
        
        // 默认转换为字符串
        return rexBuilder.makeLiteral(value.toString(), type, false);
    }

    /**
     * 关闭资源
     */
    public void close() throws SQLException {
        schemaFactory.closeConnections();
    }
}

