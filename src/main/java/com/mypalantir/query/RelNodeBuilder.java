package com.mypalantir.query;

import com.mypalantir.meta.DataSourceMapping;
import com.mypalantir.meta.LinkType;
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
import org.apache.calcite.rel.core.JoinRelType;
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
        
        // 3. 构建 JOIN（如果有 links 查询）
        if (query.getLinks() != null && !query.getLinks().isEmpty()) {
            for (OntologyQuery.LinkQuery linkQuery : query.getLinks()) {
                scan = buildJoin(scan, linkQuery, objectType);
            }
        }
        
        // 4. 构建 Project（SELECT）
        // 注意：如果有 JOIN，需要处理来自多个表的字段
        // 收集所有要选择的字段：主表的字段 + 关联表的字段
        List<String> allSelectFields = new ArrayList<>();
        if (query.getSelect() != null && !query.getSelect().isEmpty()) {
            allSelectFields.addAll(query.getSelect());
        }
        // 添加关联表的 select 字段
        if (query.getLinks() != null && !query.getLinks().isEmpty()) {
            for (OntologyQuery.LinkQuery linkQuery : query.getLinks()) {
                if (linkQuery.getSelect() != null && !linkQuery.getSelect().isEmpty()) {
                    allSelectFields.addAll(linkQuery.getSelect());
                }
            }
        }
        if (!allSelectFields.isEmpty()) {
            scan = buildProject(scan, allSelectFields, objectType, query.getLinks());
        }
        
        // 5. 构建 Sort（ORDER BY）
        if (query.getOrderBy() != null && !query.getOrderBy().isEmpty()) {
            scan = buildSort(scan, query.getOrderBy(), objectType, dataSourceMapping);
        }
        
        // 6. 构建 Limit
        if (query.getLimit() != null && query.getLimit() > 0) {
            scan = buildLimit(scan, query.getLimit(), query.getOffset());
        }
        
        return scan;
    }

    /**
     * 构建 TableScan
     * 注意：这个方法不会修改 relBuilder 的状态，因为它会先 clear 再 build
     */
    private RelNode buildTableScan(String tableName) {
        // 创建一个临时的 RelBuilder 来构建 TableScan，避免影响当前的 relBuilder 状态
        RelBuilder tempBuilder = RelBuilder.create(frameworkConfig);
        tempBuilder.scan(tableName);
        return tempBuilder.build();
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
     * @param input 输入 RelNode
     * @param selectFields 要选择的字段列表（可能包含主表和关联表的字段）
     * @param objectType 主对象类型
     * @param links 关联查询列表（用于确定字段来自哪个表）
     */
    private RelNode buildProject(RelNode input, List<String> selectFields, ObjectType objectType, 
                                 List<OntologyQuery.LinkQuery> links) {
        relBuilder.clear();
        relBuilder.push(input);
        
        RelDataType rowType = input.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        List<RexNode> projects = new ArrayList<>();
        List<String> fieldNames = new ArrayList<>();
        
        // 如果没有指定 select 字段，直接返回（不进行 Project）
        if (selectFields == null || selectFields.isEmpty()) {
            return input;
        }
        
        // 构建字段名到索引的映射（基于 JOIN 后的行类型）
        Map<String, Integer> fieldIndexMap = buildFieldIndexMap(objectType, links, rowType);
        
        for (String propertyName : selectFields) {
            Integer fieldIndex = fieldIndexMap.get(propertyName);
            if (fieldIndex != null && fieldIndex >= 0 && fieldIndex < rowType.getFieldCount()) {
                try {
                    RexInputRef inputRef = rexBuilder.makeInputRef(
                        rowType.getFieldList().get(fieldIndex).getType(),
                        fieldIndex
                    );
                    projects.add(inputRef);
                    fieldNames.add(propertyName);
                } catch (Exception e) {
                    // 如果字段索引无效，跳过该字段
                    System.err.println("Warning: Failed to create input ref for field '" + propertyName + "' at index " + fieldIndex + ": " + e.getMessage());
                    continue;
                }
            } else {
                // 字段未找到，记录警告
                System.err.println("Warning: Field '" + propertyName + "' not found in row type. Available fields: " + 
                    rowType.getFieldList().stream().map(f -> f.getName()).collect(java.util.stream.Collectors.joining(", ")));
            }
        }
        
        // 如果没有有效的字段，返回所有字段
        if (projects.isEmpty()) {
            // 返回所有字段
            for (int i = 0; i < rowType.getFieldCount(); i++) {
                projects.add(rexBuilder.makeInputRef(rowType.getFieldList().get(i).getType(), i));
                fieldNames.add(rowType.getFieldList().get(i).getName());
            }
        }
        
        if (!projects.isEmpty()) {
            relBuilder.project(projects, fieldNames);
        }
        
        return relBuilder.build();
    }
    
    /**
     * 构建字段名到索引的映射
     * 根据 JOIN 后的行类型结构，找到每个字段的索引
     */
    private Map<String, Integer> buildFieldIndexMap(ObjectType objectType, 
                                                    List<OntologyQuery.LinkQuery> links,
                                                    RelDataType rowType) {
        Map<String, Integer> fieldMap = new java.util.HashMap<>();
        List<org.apache.calcite.rel.type.RelDataTypeField> fields = rowType.getFieldList();
        
        // 遍历所有字段，根据字段名匹配属性名
        for (int i = 0; i < fields.size(); i++) {
            String fieldName = fields.get(i).getName();
            if (fieldName == null) {
                continue;
            }
            
            // 主表的 id 字段
            if ("id".equalsIgnoreCase(fieldName) && !fieldMap.containsKey("id")) {
                fieldMap.put("id", i);
                continue;
            }
            
            // 主表属性字段
            if (objectType.getProperties() != null) {
                for (Property prop : objectType.getProperties()) {
                    if (prop.getName().equals(fieldName) && !fieldMap.containsKey(prop.getName())) {
                        fieldMap.put(prop.getName(), i);
                        break;
                    }
                }
            }
            
            // 关联表字段（link type 属性和目标表属性）
            if (links != null) {
                for (OntologyQuery.LinkQuery linkQuery : links) {
                    try {
                        LinkType linkType = loader.getLinkType(linkQuery.getName());
                        
                        // Link type 的属性
                        if (linkType.getProperties() != null) {
                            for (Property linkProp : linkType.getProperties()) {
                                if (linkProp.getName().equals(fieldName) && !fieldMap.containsKey(linkProp.getName())) {
                                    fieldMap.put(linkProp.getName(), i);
                                    break;
                                }
                            }
                        }
                        
                        // 目标表的属性
                        if (linkQuery.getSelect() != null) {
                            ObjectType targetObjectType = loader.getObjectType(linkType.getTargetType());
                            if (targetObjectType.getProperties() != null) {
                                for (Property targetProp : targetObjectType.getProperties()) {
                                    if (targetProp.getName().equals(fieldName) && !fieldMap.containsKey(targetProp.getName())) {
                                        fieldMap.put(targetProp.getName(), i);
                                        break;
                                    }
                                }
                            }
                        }
                    } catch (Loader.NotFoundException e) {
                        // 跳过无效的 link type
                        continue;
                    }
                }
            }
        }
        
        return fieldMap;
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
     * 构建 JOIN 查询
     * @param leftInput 左表（主表，如车辆表）
     * @param linkQuery 关联查询
     * @param sourceObjectType 源对象类型（如"车辆"）
     * @return JOIN 后的 RelNode
     */
    private RelNode buildJoin(RelNode leftInput, OntologyQuery.LinkQuery linkQuery, 
                             ObjectType sourceObjectType) throws Exception {
        // 1. 获取 LinkType
        LinkType linkType;
        try {
            linkType = loader.getLinkType(linkQuery.getName());
        } catch (Loader.NotFoundException e) {
            throw new IllegalArgumentException("Link type '" + linkQuery.getName() + "' not found");
        }
        
        // 2. 验证 direction：对于 directed link，只能从 source 查询到 target
        if ("directed".equals(linkType.getDirection())) {
            if (!linkType.getSourceType().equals(sourceObjectType.getName())) {
                throw new IllegalArgumentException("Cannot query link type '" + linkQuery.getName() + 
                    "' from object type '" + sourceObjectType.getName() + 
                    "'. This is a directed link and can only be queried from source type '" + 
                    linkType.getSourceType() + "'");
            }
        }
        
        // 3. 检查 LinkType 是否有 data_source 配置
        if (linkType.getDataSource() == null || !linkType.getDataSource().isConfigured()) {
            throw new IllegalArgumentException("Link type '" + linkQuery.getName() + "' does not have data source configured");
        }
        
        DataSourceMapping linkMapping = linkType.getDataSource();
        
        // 4. 获取目标 ObjectType
        ObjectType targetObjectType;
        try {
            targetObjectType = loader.getObjectType(linkType.getTargetType());
        } catch (Loader.NotFoundException e) {
            throw new IllegalArgumentException("Target object type '" + linkType.getTargetType() + "' not found");
        }
        
        // 5. 获取目标 ObjectType 的 data_source
        DataSourceMapping targetMapping = targetObjectType.getDataSource();
        if (targetMapping == null || !targetMapping.isConfigured()) {
            throw new IllegalArgumentException("Target object type '" + linkType.getTargetType() + "' does not have data source configured");
        }
        
        // 6. 获取源 ObjectType 的 data_source
        DataSourceMapping sourceMapping = sourceObjectType.getDataSource();
        if (sourceMapping == null || !sourceMapping.isConfigured()) {
            throw new IllegalArgumentException("Source object type '" + sourceObjectType.getName() + "' does not have data source configured");
        }
        
        // 7. 扫描中间表（vehicle_media）
        // 注意：中间表在 Schema 中使用表名（小写），与 mapping.getTable() 一致
        String linkTableName = linkMapping.getTable();  // 小写表名，与 Schema 中的名称一致
        RelNode linkTableScan = buildTableScan(linkTableName);
        
        // 准备第一个 JOIN
        relBuilder.clear();
        relBuilder.push(leftInput);  // 左表（车辆表）
        relBuilder.push(linkTableScan);  // 中间表
        
        // 8. 构建第一个 JOIN 条件：vehicles.vehicle_id = vehicle_media.vehicle_id
        RelDataType leftRowType = leftInput.getRowType();
        RelDataType linkRowType = linkTableScan.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        
        // 找到源对象 ID 字段在左表中的索引（通常是第一个字段 "id"）
        int leftIdIndex = 0;  // "id" 字段通常是第一个
        
        // 找到 source_id_column 在中间表中的索引
        String sourceIdColumn = linkMapping.getSourceIdColumn();
        int linkSourceIdIndex = findFieldIndexInRowType(sourceIdColumn, linkRowType);
        if (linkSourceIdIndex < 0) {
            throw new IllegalArgumentException("Source ID column '" + sourceIdColumn + "' not found in link table '" + linkTableName + "'");
        }
        
        // 左表的 ID 字段引用（索引 0）
        RexNode leftIdRef = rexBuilder.makeInputRef(
            leftRowType.getFieldList().get(leftIdIndex).getType(), 
            leftIdIndex
        );
        
        // 中间表的 source_id 字段引用（索引 = 左表字段数 + 中间表字段索引）
        RexNode linkSourceIdRef = rexBuilder.makeInputRef(
            linkRowType.getFieldList().get(linkSourceIdIndex).getType(),
            leftRowType.getFieldCount() + linkSourceIdIndex
        );
        
        RexNode joinCondition1 = rexBuilder.makeCall(
            org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
            leftIdRef,
            linkSourceIdRef
        );
        
        // 9. 执行第一个 JOIN（LEFT JOIN）
        relBuilder.join(JoinRelType.LEFT, joinCondition1);
        RelNode firstJoin = relBuilder.build();
        
        // 获取第一个 JOIN 后的行类型（用于计算字段偏移）
        RelDataType firstJoinRowType = firstJoin.getRowType();
        
        // 10. 扫描目标表（media）
        RelNode targetTableScan = buildTableScan(linkType.getTargetType());
        
        // 准备第二个 JOIN
        relBuilder.clear();
        relBuilder.push(firstJoin);  // 第一个 JOIN 的结果
        relBuilder.push(targetTableScan);  // 目标表
        
        // 11. 构建第二个 JOIN 条件：vehicle_media.media_id = media.media_id
        RelDataType targetRowType = targetTableScan.getRowType();
        String targetIdColumn = linkMapping.getTargetIdColumn();
        int linkTargetIdIndex = findFieldIndexInRowType(targetIdColumn, linkRowType);
        if (linkTargetIdIndex < 0) {
            throw new IllegalArgumentException("Target ID column '" + targetIdColumn + "' not found in link table '" + linkTableName + 
                "'. Available fields: " + linkRowType.getFieldList().stream()
                    .map(f -> f.getName()).collect(java.util.stream.Collectors.joining(", ")));
        }
        
        int targetIdIndex = 0;  // 目标表的 "id" 字段通常是第一个
        
        // 计算当前字段偏移量（第一个 JOIN 后的字段数）
        int currentFieldCount = firstJoinRowType.getFieldCount();
        
        // 中间表的 target_id 字段引用（在第一个 JOIN 后的行类型中）
        // 需要找到 target_id 字段在第一个 JOIN 后的行类型中的索引
        int linkTargetIdIndexInFirstJoin = findFieldIndexInRowType(targetIdColumn, firstJoinRowType);
        if (linkTargetIdIndexInFirstJoin < 0) {
            throw new IllegalArgumentException("Target ID column '" + targetIdColumn + "' not found in first join result. " +
                "Available fields: " + firstJoinRowType.getFieldList().stream()
                    .map(f -> f.getName()).collect(java.util.stream.Collectors.joining(", ")));
        }
        
        RexNode linkTargetIdRef = rexBuilder.makeInputRef(
            firstJoinRowType.getFieldList().get(linkTargetIdIndexInFirstJoin).getType(),
            linkTargetIdIndexInFirstJoin
        );
        
        // 目标表的 id 字段引用
        RexNode targetIdRef = rexBuilder.makeInputRef(
            targetRowType.getFieldList().get(targetIdIndex).getType(),
            currentFieldCount + targetIdIndex
        );
        
        RexNode joinCondition2 = rexBuilder.makeCall(
            org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
            linkTargetIdRef,
            targetIdRef
        );
        
        // 12. 执行第二个 JOIN（LEFT JOIN）
        relBuilder.join(JoinRelType.LEFT, joinCondition2);
        RelNode finalJoin = relBuilder.build();
        
        return finalJoin;
    }
    
    /**
     * 在 RelDataType 中查找字段索引（通过数据库列名）
     */
    private int findFieldIndexInRowType(String columnName, RelDataType rowType) {
        List<org.apache.calcite.rel.type.RelDataTypeField> fields = rowType.getFieldList();
        String upperColumnName = columnName.toUpperCase();
        for (int i = 0; i < fields.size(); i++) {
            String fieldName = fields.get(i).getName();
            if (fieldName != null && fieldName.toUpperCase().equals(upperColumnName)) {
                return i;
            }
        }
        return -1;
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
        
        // 首先检查是否是 id 字段
        if ("id".equals(propertyName) && !fields.isEmpty()) {
            // id 字段在索引 0
            return 0;
        }
        
        // 然后查找属性字段
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

