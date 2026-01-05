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
import org.apache.calcite.rex.RexLiteral;
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
import java.util.stream.Collectors;

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
        
        // 2. 先构建 JOIN（如果有 links 查询）- 必须在 filter 之前，因为 filter 可能需要访问关联表的字段
        if (query.getLinks() != null && !query.getLinks().isEmpty()) {
            for (OntologyQuery.LinkQuery linkQuery : query.getLinks()) {
                scan = buildJoin(scan, linkQuery, objectType);
            }
        }
        
        // 3. 构建 Filter（WHERE 或 filter 表达式）- 在 JOIN 之后执行，可以访问关联表的字段
        if (query.getFilter() != null && !query.getFilter().isEmpty()) {
            // 新格式：表达式数组
            scan = buildExpressionFilter(scan, query.getFilter(), objectType, query.getLinks());
        } else if (query.getWhere() != null && !query.getWhere().isEmpty()) {
            // 旧格式：Map<String, Object>
            scan = buildFilter(scan, query.getWhere(), objectType, dataSourceMapping);
        }
        
        // 4. 构建 Aggregate（如果有 group_by 或 metrics）
        if ((query.getGroupBy() != null && !query.getGroupBy().isEmpty()) || 
            (query.getMetrics() != null && !query.getMetrics().isEmpty())) {
            scan = buildAggregate(scan, query.getGroupBy(), query.getMetrics(), objectType, query.getLinks());
        } else {
            // 5. 构建 Project（SELECT）- 仅在非聚合查询时执行
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
        }
        
        // 6. 构建 Sort（ORDER BY）
        if (query.getOrderBy() != null && !query.getOrderBy().isEmpty()) {
            scan = buildSort(scan, query.getOrderBy(), objectType, dataSourceMapping);
        }
        
        // 7. 构建 Limit
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
        
        // 2. 判断查询方向：是从 source 端还是 target 端查询
        boolean isFromSource = linkType.getSourceType().equals(sourceObjectType.getName());
        boolean isFromTarget = linkType.getTargetType().equals(sourceObjectType.getName());
        
        if (!isFromSource && !isFromTarget) {
            throw new IllegalArgumentException("Link type '" + linkQuery.getName() + 
                "' is not connected to object type '" + sourceObjectType.getName() + 
                "'. Link connects '" + linkType.getSourceType() + "' to '" + linkType.getTargetType() + "'");
        }
        
        // 3. 验证 direction：对于 directed link，只能从 source 查询到 target
        if ("directed".equals(linkType.getDirection()) && isFromTarget) {
            throw new IllegalArgumentException("Cannot query directed link '" + linkQuery.getName() + 
                "' from target side. This is a directed link and can only be queried from source type '" + 
                linkType.getSourceType() + "'");
        }
        
        // 4. 检查 LinkType 是否有 data_source 配置
        if (linkType.getDataSource() == null || !linkType.getDataSource().isConfigured()) {
            throw new IllegalArgumentException("Link type '" + linkQuery.getName() + "' does not have data source configured");
        }
        
        DataSourceMapping linkMapping = linkType.getDataSource();
        
        // 5. 确定实际的 source 和 target（根据查询方向）
        ObjectType actualSourceType, actualTargetType;
        DataSourceMapping actualSourceMapping, actualTargetMapping;
        
        if (isFromSource) {
            // 从 source 端查询：source -> target
            actualSourceType = sourceObjectType;
            try {
                actualTargetType = loader.getObjectType(linkType.getTargetType());
            } catch (Loader.NotFoundException e) {
                throw new IllegalArgumentException("Target object type '" + linkType.getTargetType() + "' not found");
            }
        } else {
            // 从 target 端查询：target -> source（仅适用于 undirected link）
            actualSourceType = sourceObjectType;  // 当前查询的起始对象（target）
            try {
                actualTargetType = loader.getObjectType(linkType.getSourceType());  // 要查询到的对象（source）
            } catch (Loader.NotFoundException e) {
                throw new IllegalArgumentException("Source object type '" + linkType.getSourceType() + "' not found");
            }
        }
        
        // 6. 获取数据源映射
        actualSourceMapping = actualSourceType.getDataSource();
        if (actualSourceMapping == null || !actualSourceMapping.isConfigured()) {
            throw new IllegalArgumentException("Source object type '" + actualSourceType.getName() + "' does not have data source configured");
        }
        
        actualTargetMapping = actualTargetType.getDataSource();
        if (actualTargetMapping == null || !actualTargetMapping.isConfigured()) {
            throw new IllegalArgumentException("Target object type '" + actualTargetType.getName() + "' does not have data source configured");
        }
        
        // 7. 判断 LinkType 映射模式（基于实际的 target）
        boolean isForeignKeyMode = linkMapping.isForeignKeyMode(actualTargetType);
        
        if (isForeignKeyMode) {
            // 外键模式：直接 JOIN 目标表（目标表中包含外键）
            return buildForeignKeyJoin(leftInput, actualSourceType, actualTargetType, 
                                      linkMapping, actualTargetMapping, isFromSource);
        } else {
            // 关系表模式：通过中间表 JOIN
            return buildRelationTableJoin(leftInput, actualSourceType, actualTargetType, 
                                         linkType, linkMapping, actualTargetMapping, isFromSource);
        }
    }

    /**
     * 构建外键模式的 JOIN（直接 JOIN 目标表，目标表中包含外键）
     * 例如：收费站 JOIN 收费记录（通过 toll_records.station_id）
     * 
     * @param leftInput 左表（当前查询的起始对象表）
     * @param sourceObjectType 源对象类型（当前查询的起始对象）
     * @param targetObjectType 目标对象类型（要查询到的对象）
     * @param linkMapping LinkType 的数据源映射
     * @param targetMapping 目标对象的数据源映射
     * @param isFromSource 是否从 source 端查询（true：从 source 查询到 target，false：从 target 查询到 source）
     * @return JOIN 后的 RelNode
     */
    private RelNode buildForeignKeyJoin(RelNode leftInput, ObjectType sourceObjectType,
                                        ObjectType targetObjectType,
                                        DataSourceMapping linkMapping,
                                        DataSourceMapping targetMapping,
                                        boolean isFromSource) throws Exception {
        relBuilder.clear();
        relBuilder.push(leftInput);
        
        // 扫描目标表（外键就在这个表中）
        RelNode targetTableScan = buildTableScan(targetObjectType.getName());
        relBuilder.push(targetTableScan);
        
        RelDataType leftRowType = leftInput.getRowType();
        RelDataType targetRowType = targetTableScan.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        
        // 源表的 ID 字段（索引 0）
        int leftIdIndex = 0;
        RexNode leftIdRef = rexBuilder.makeInputRef(
            leftRowType.getFieldList().get(leftIdIndex).getType(),
            leftIdIndex
        );
        
        // 根据查询方向确定 JOIN 条件
        RexNode joinCondition;
        if (isFromSource) {
            // 从 source 查询到 target：source_table.id = target_table.source_id_column
            String sourceIdColumn = linkMapping.getSourceIdColumn();
            if (sourceIdColumn == null || sourceIdColumn.isEmpty()) {
                throw new IllegalArgumentException("Source ID column is not configured for foreign key mode link type");
            }
            
            // 在目标表的行类型中查找外键字段
            int targetForeignKeyIndex = findFieldIndexInRowType(sourceIdColumn, targetRowType);
            if (targetForeignKeyIndex < 0) {
                String propertyName = targetMapping.getPropertyName(sourceIdColumn);
                if (propertyName != null) {
                    targetForeignKeyIndex = findFieldIndexInRowType(propertyName, targetRowType);
                }
            }
            
            if (targetForeignKeyIndex < 0) {
                throw new IllegalArgumentException("Foreign key column '" + sourceIdColumn + 
                    "' not found in target table '" + targetObjectType.getName() + 
                    "'. Available fields: " + targetRowType.getFieldList().stream()
                        .map(f -> f.getName()).collect(java.util.stream.Collectors.joining(", ")));
            }
            
            RexNode targetForeignKeyRef = rexBuilder.makeInputRef(
                targetRowType.getFieldList().get(targetForeignKeyIndex).getType(),
                leftRowType.getFieldCount() + targetForeignKeyIndex
            );
            
            joinCondition = rexBuilder.makeCall(
                org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
                leftIdRef,
                targetForeignKeyRef
            );
        } else {
            // 从 target 查询到 source：target_table.id = source_table.source_id_column
            // 注意：在外键模式中，外键在 target 表中，所以从 target 查询到 source 时，
            // 需要找到 source 表中对应的外键字段（实际上 source 表就是 target 表，因为外键在 target 表中）
            // 但这种情况在外键模式中不常见，因为外键模式通常是一对多关系，总是从 source 查询到 target
            // 这里为了完整性，我们假设外键在 target 表中，从 target 查询时，需要找到 source 表
            // 但实际上，外键模式从 target 端查询可能没有意义，因为外键在 target 表中
            throw new IllegalArgumentException("Foreign key mode does not support querying from target side. " +
                "The foreign key is in the target table, so queries should start from the source side.");
        }
        
        relBuilder.join(JoinRelType.LEFT, joinCondition);
        return relBuilder.build();
    }

    /**
     * 构建关系表模式的 JOIN（通过中间表，两次 JOIN）
     * 例如：车辆 JOIN vehicle_media JOIN 通行介质（从 source 查询）
     * 或：通行介质 JOIN vehicle_media JOIN 车辆（从 target 查询）
     * 
     * @param leftInput 左表（当前查询的起始对象表）
     * @param sourceObjectType 源对象类型（当前查询的起始对象）
     * @param targetObjectType 目标对象类型（要查询到的对象）
     * @param linkType LinkType
     * @param linkMapping LinkType 的数据源映射
     * @param targetMapping 目标对象的数据源映射
     * @param isFromSource 是否从 source 端查询（true：从 source 查询到 target，false：从 target 查询到 source）
     * @return JOIN 后的 RelNode
     */
    private RelNode buildRelationTableJoin(RelNode leftInput, ObjectType sourceObjectType,
                                          ObjectType targetObjectType,
                                          LinkType linkType,
                                          DataSourceMapping linkMapping,
                                          DataSourceMapping targetMapping,
                                          boolean isFromSource) throws Exception {
        // 扫描中间表（例如：vehicle_media）
        String linkTableName = linkMapping.getTable();
        RelNode linkTableScan = buildTableScan(linkTableName);
        
        RelDataType leftRowType = leftInput.getRowType();
        RelDataType linkRowType = linkTableScan.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        
        // 左表的 ID 字段（索引 0）
        int leftIdIndex = 0;
        RexNode leftIdRef = rexBuilder.makeInputRef(
            leftRowType.getFieldList().get(leftIdIndex).getType(),
            leftIdIndex
        );
        
        if (isFromSource) {
            // 从 source 查询到 target：source JOIN link_table JOIN target
            // 第一个 JOIN：source_table.id = link_table.source_id_column
            String sourceIdColumn = linkMapping.getSourceIdColumn();
            int linkSourceIdIndex = findFieldIndexInRowType(sourceIdColumn, linkRowType);
            if (linkSourceIdIndex < 0) {
                throw new IllegalArgumentException("Source ID column '" + sourceIdColumn + "' not found in link table '" + linkTableName + "'");
            }
            
            RexNode linkSourceIdRef = rexBuilder.makeInputRef(
                linkRowType.getFieldList().get(linkSourceIdIndex).getType(),
                leftRowType.getFieldCount() + linkSourceIdIndex
            );
            
            RexNode joinCondition1 = rexBuilder.makeCall(
                org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
                leftIdRef,
                linkSourceIdRef
            );
            
            relBuilder.clear();
            relBuilder.push(leftInput);
            relBuilder.push(linkTableScan);
            relBuilder.join(JoinRelType.LEFT, joinCondition1);
            RelNode firstJoin = relBuilder.build();
            RelDataType firstJoinRowType = firstJoin.getRowType();
            
            // 第二个 JOIN：link_table.target_id_column = target_table.id
            RelNode targetTableScan = buildTableScan(targetObjectType.getName());
            String targetIdColumn = linkMapping.getTargetIdColumn();
            int linkTargetIdIndex = findFieldIndexInRowType(targetIdColumn, linkRowType);
            if (linkTargetIdIndex < 0) {
                throw new IllegalArgumentException("Target ID column '" + targetIdColumn + "' not found in link table '" + linkTableName + "'");
            }
            
            int linkTargetIdIndexInFirstJoin = findFieldIndexInRowType(targetIdColumn, firstJoinRowType);
            if (linkTargetIdIndexInFirstJoin < 0) {
                throw new IllegalArgumentException("Target ID column '" + targetIdColumn + "' not found in first join result");
            }
            
            RexNode linkTargetIdRef = rexBuilder.makeInputRef(
                firstJoinRowType.getFieldList().get(linkTargetIdIndexInFirstJoin).getType(),
                linkTargetIdIndexInFirstJoin
            );
            
            RelDataType targetRowType = targetTableScan.getRowType();
            int targetIdIndex = 0;
            RexNode targetIdRef = rexBuilder.makeInputRef(
                targetRowType.getFieldList().get(targetIdIndex).getType(),
                firstJoinRowType.getFieldCount() + targetIdIndex
            );
            
            RexNode joinCondition2 = rexBuilder.makeCall(
                org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
                linkTargetIdRef,
                targetIdRef
            );
            
            relBuilder.clear();
            relBuilder.push(firstJoin);
            relBuilder.push(targetTableScan);
            relBuilder.join(JoinRelType.LEFT, joinCondition2);
            return relBuilder.build();
        } else {
            // 从 target 查询到 source：target JOIN link_table JOIN source
            // 第一个 JOIN：target_table.id = link_table.target_id_column
            String targetIdColumn = linkMapping.getTargetIdColumn();
            int linkTargetIdIndex = findFieldIndexInRowType(targetIdColumn, linkRowType);
            if (linkTargetIdIndex < 0) {
                throw new IllegalArgumentException("Target ID column '" + targetIdColumn + "' not found in link table '" + linkTableName + "'");
            }
            
            RexNode linkTargetIdRef = rexBuilder.makeInputRef(
                linkRowType.getFieldList().get(linkTargetIdIndex).getType(),
                leftRowType.getFieldCount() + linkTargetIdIndex
            );
            
            RexNode joinCondition1 = rexBuilder.makeCall(
                org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
                leftIdRef,
                linkTargetIdRef
            );
            
            relBuilder.clear();
            relBuilder.push(leftInput);
            relBuilder.push(linkTableScan);
            relBuilder.join(JoinRelType.LEFT, joinCondition1);
            RelNode firstJoin = relBuilder.build();
            RelDataType firstJoinRowType = firstJoin.getRowType();
            
            // 第二个 JOIN：link_table.source_id_column = source_table.id
            RelNode sourceTableScan = buildTableScan(targetObjectType.getName());  // 注意：targetObjectType 实际上是 source（要查询到的对象）
            String sourceIdColumn = linkMapping.getSourceIdColumn();
            int linkSourceIdIndex = findFieldIndexInRowType(sourceIdColumn, linkRowType);
            if (linkSourceIdIndex < 0) {
                throw new IllegalArgumentException("Source ID column '" + sourceIdColumn + "' not found in link table '" + linkTableName + "'");
            }
            
            int linkSourceIdIndexInFirstJoin = findFieldIndexInRowType(sourceIdColumn, firstJoinRowType);
            if (linkSourceIdIndexInFirstJoin < 0) {
                throw new IllegalArgumentException("Source ID column '" + sourceIdColumn + "' not found in first join result");
            }
            
            RexNode linkSourceIdRef = rexBuilder.makeInputRef(
                firstJoinRowType.getFieldList().get(linkSourceIdIndexInFirstJoin).getType(),
                linkSourceIdIndexInFirstJoin
            );
            
            RelDataType sourceRowType = sourceTableScan.getRowType();
            int sourceIdIndex = 0;
            RexNode sourceIdRef = rexBuilder.makeInputRef(
                sourceRowType.getFieldList().get(sourceIdIndex).getType(),
                firstJoinRowType.getFieldCount() + sourceIdIndex
            );
            
            RexNode joinCondition2 = rexBuilder.makeCall(
                org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS,
                linkSourceIdRef,
                sourceIdRef
            );
            
            relBuilder.clear();
            relBuilder.push(firstJoin);
            relBuilder.push(sourceTableScan);
            relBuilder.join(JoinRelType.LEFT, joinCondition2);
            return relBuilder.build();
        }
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
            case BIGINT:
                if (value instanceof Number) {
                    return rexBuilder.makeLiteral(
                        ((Number) value).longValue(),
                        type,
                        false
                    );
                } else if (value instanceof String) {
                    // 尝试将字符串解析为数字
                    try {
                        long longValue = Long.parseLong((String) value);
                        return rexBuilder.makeLiteral(longValue, type, false);
                    } catch (NumberFormatException e) {
                        // 如果解析失败，抛出异常
                        throw new IllegalArgumentException("Cannot convert string '" + value + "' to integer for field type " + type);
                    }
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
                } else if (value instanceof String) {
                    // 尝试将字符串解析为数字
                    try {
                        double doubleValue = Double.parseDouble((String) value);
                        return rexBuilder.makeLiteral(doubleValue, type, false);
                    } catch (NumberFormatException e) {
                        throw new IllegalArgumentException("Cannot convert string '" + value + "' to double for field type " + type);
                    }
                }
                break;
            case BOOLEAN:
                if (value instanceof Boolean) {
                    return rexBuilder.makeLiteral((Boolean) value, type, false);
                } else if (value instanceof String) {
                    // 尝试将字符串解析为布尔值
                    String str = ((String) value).toLowerCase().trim();
                    if ("true".equals(str) || "1".equals(str) || "yes".equals(str)) {
                        return rexBuilder.makeLiteral(true, type, false);
                    } else if ("false".equals(str) || "0".equals(str) || "no".equals(str)) {
                        return rexBuilder.makeLiteral(false, type, false);
                    } else {
                        throw new IllegalArgumentException("Cannot convert string '" + value + "' to boolean");
                    }
                }
                break;
            case DATE:
                // DATE 类型：使用 java.sql.Date
                if (value instanceof String) {
                    String dateStr = (String) value;
                    try {
                        java.sql.Date date = java.sql.Date.valueOf(dateStr);
                        return rexBuilder.makeLiteral(date, type, false);
                    } catch (IllegalArgumentException e) {
                        throw new IllegalArgumentException("Invalid date format: " + dateStr + ". Expected format: YYYY-MM-DD");
                    }
                } else if (value instanceof java.sql.Date) {
                    return rexBuilder.makeLiteral((java.sql.Date) value, type, false);
                } else {
                    try {
                        java.sql.Date date = java.sql.Date.valueOf(value.toString());
                        return rexBuilder.makeLiteral(date, type, false);
                    } catch (IllegalArgumentException e) {
                        throw new IllegalArgumentException("Cannot convert '" + value + "' to DATE");
                    }
                }
            case TIMESTAMP:
                // TIMESTAMP 类型：Calcite 的 makeLiteral 期望 Long（时间戳毫秒数）
                // 我们需要将字符串解析为 Timestamp，然后获取毫秒数
                if (value instanceof String) {
                    String dateStr = (String) value;
                    // 确保日期时间格式正确
                    if (dateStr.length() <= 10) {
                        // 只有日期部分，添加时间部分
                        dateStr = dateStr + " 00:00:00";
                    }
                    // 解析为 Timestamp 对象，然后获取毫秒数
                    try {
                        java.sql.Timestamp timestamp = java.sql.Timestamp.valueOf(dateStr);
                        long timestampMillis = timestamp.getTime();
                        // 使用 Long（时间戳毫秒数）创建字面量，但指定类型为 TIMESTAMP
                        return rexBuilder.makeLiteral(timestampMillis, type, false);
                    } catch (IllegalArgumentException e) {
                        throw new IllegalArgumentException("Invalid timestamp format: " + dateStr + 
                            ". Expected format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS. Error: " + e.getMessage());
                    }
                } else if (value instanceof java.sql.Timestamp) {
                    // 获取时间戳毫秒数
                    long timestampMillis = ((java.sql.Timestamp) value).getTime();
                    return rexBuilder.makeLiteral(timestampMillis, type, false);
                } else if (value instanceof java.sql.Date) {
                    // 获取时间戳毫秒数
                    long timestampMillis = ((java.sql.Date) value).getTime();
                    return rexBuilder.makeLiteral(timestampMillis, type, false);
                } else if (value instanceof Number) {
                    // 如果已经是数字，直接使用
                    long timestampMillis = ((Number) value).longValue();
                    return rexBuilder.makeLiteral(timestampMillis, type, false);
                } else {
                    // 转换为字符串再解析
                    String dateStr = value.toString();
                    if (dateStr.length() <= 10) {
                        dateStr = dateStr + " 00:00:00";
                    }
                    try {
                        java.sql.Timestamp timestamp = java.sql.Timestamp.valueOf(dateStr);
                        long timestampMillis = timestamp.getTime();
                        return rexBuilder.makeLiteral(timestampMillis, type, false);
                    } catch (IllegalArgumentException e) {
                        throw new IllegalArgumentException("Cannot convert '" + value + "' to TIMESTAMP: " + e.getMessage());
                    }
                }
            default:
                // 对于未知类型，尝试使用字符串
                // 但需要检查类型是否支持字符串
                if (sqlTypeName == SqlTypeName.VARCHAR || sqlTypeName == SqlTypeName.CHAR) {
                    // 字符串类型，使用 NlsString
                    org.apache.calcite.sql.SqlCollation defaultCollation = org.apache.calcite.sql.SqlCollation.COERCIBLE;
                    org.apache.calcite.util.NlsString defaultNlsString = new org.apache.calcite.util.NlsString(
                        value.toString(),
                        "UTF-8",
                        defaultCollation
                    );
                    return rexBuilder.makeLiteral(defaultNlsString, type, false);
                } else {
                    // 对于其他类型，尝试使用字符串（Calcite 可能会自动转换）
                    // 但如果类型不匹配，会抛出异常
                    try {
                        return rexBuilder.makeLiteral(value.toString(), type, false);
                    } catch (Exception e) {
                        throw new IllegalArgumentException("Cannot convert value '" + value + "' (type: " + 
                            value.getClass().getSimpleName() + ") to field type " + sqlTypeName + 
                            ". Original error: " + e.getMessage());
                    }
                }
        }
        
        // 如果所有 case 都 break 了（没有返回），说明类型不匹配
        throw new IllegalArgumentException("Cannot convert value '" + value + "' (type: " + 
            value.getClass().getSimpleName() + ") to field type " + type.getSqlTypeName());
    }

    /**
     * 构建表达式过滤器（新格式：filter 表达式数组）
     * 例如：[["=", "province", "江苏"], ["between", "hasTollRecords.charge_time", "2024-01-01", "2024-01-31"]]
     */
    private RelNode buildExpressionFilter(RelNode input, List<Object> filterExpressions,
                                         ObjectType rootObjectType, List<OntologyQuery.LinkQuery> links) throws Exception {
        relBuilder.clear();
        relBuilder.push(input);
        
        RelDataType rowType = input.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        FieldPathResolver pathResolver = new FieldPathResolver(loader);
        List<RexNode> conditions = new ArrayList<>();
        
        for (Object expr : filterExpressions) {
            if (!(expr instanceof List)) {
                throw new IllegalArgumentException("Filter expression must be an array: " + expr);
            }
            
            @SuppressWarnings("unchecked")
            List<Object> exprList = (List<Object>) expr;
            if (exprList.isEmpty()) {
                continue;
            }
            
            RexNode condition = buildFilterExpression(exprList, rowType, rootObjectType, links, pathResolver, rexBuilder);
            if (condition != null) {
                conditions.add(condition);
            }
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
     * 构建单个过滤表达式
     */
    private RexNode buildFilterExpression(List<Object> expr, RelDataType rowType, ObjectType rootObjectType,
                                         List<OntologyQuery.LinkQuery> links, FieldPathResolver pathResolver,
                                         RexBuilder rexBuilder) throws Exception {
        if (expr.isEmpty()) {
            return null;
        }
        
        String operator = expr.get(0).toString();
        
        // 处理逻辑运算符
        if ("and".equalsIgnoreCase(operator)) {
            List<RexNode> conditions = new ArrayList<>();
            for (int i = 1; i < expr.size(); i++) {
                if (expr.get(i) instanceof List) {
                    @SuppressWarnings("unchecked")
                    List<Object> subExpr = (List<Object>) expr.get(i);
                    RexNode condition = buildFilterExpression(subExpr, rowType, rootObjectType, links, pathResolver, rexBuilder);
                    if (condition != null) {
                        conditions.add(condition);
                    }
                }
            }
            if (conditions.isEmpty()) {
                return null;
            }
            return conditions.size() == 1 
                ? conditions.get(0)
                : rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.AND, conditions);
        } else if ("or".equalsIgnoreCase(operator)) {
            List<RexNode> conditions = new ArrayList<>();
            for (int i = 1; i < expr.size(); i++) {
                if (expr.get(i) instanceof List) {
                    @SuppressWarnings("unchecked")
                    List<Object> subExpr = (List<Object>) expr.get(i);
                    RexNode condition = buildFilterExpression(subExpr, rowType, rootObjectType, links, pathResolver, rexBuilder);
                    if (condition != null) {
                        conditions.add(condition);
                    }
                }
            }
            if (conditions.isEmpty()) {
                return null;
            }
            return conditions.size() == 1 
                ? conditions.get(0)
                : rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.OR, conditions);
        }
        
        // 处理比较运算符
        if (expr.size() < 3) {
            throw new IllegalArgumentException("Filter expression must have at least 3 elements: " + expr);
        }
        
        String fieldPath = expr.get(1).toString();
        Object value = expr.size() > 2 ? expr.get(2) : null;
        
        // 解析字段路径
        FieldPathResolver.FieldPath fieldPathResult = pathResolver.resolve(fieldPath, rootObjectType, links);
        
        // 找到字段在行类型中的索引
        int fieldIndex = findFieldIndexByPath(fieldPathResult, rowType);
        if (fieldIndex < 0) {
            // 输出所有可用字段以便调试
            String availableFields = rowType.getFieldList().stream()
                .map(f -> f.getName())
                .collect(java.util.stream.Collectors.joining(", "));
            throw new IllegalArgumentException("Field '" + fieldPath + "' (property: '" + 
                fieldPathResult.getPropertyName() + "') not found in row type. Available fields: " + availableFields);
        }
        
        RexInputRef inputRef = rexBuilder.makeInputRef(
            rowType.getFieldList().get(fieldIndex).getType(),
            fieldIndex
        );
        
        // 获取字段类型
        RelDataType fieldType = rowType.getFieldList().get(fieldIndex).getType();
        
        // 根据运算符构建条件
        switch (operator.toLowerCase()) {
            case "=":
            case "eq":
                RexNode literal = buildLiteral(rexBuilder, value, fieldType);
                return rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.EQUALS, inputRef, literal);
            
            case ">":
            case "gt":
                literal = buildLiteral(rexBuilder, value, rowType.getFieldList().get(fieldIndex).getType());
                return rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.GREATER_THAN, inputRef, literal);
            
            case ">=":
            case "gte":
                literal = buildLiteral(rexBuilder, value, rowType.getFieldList().get(fieldIndex).getType());
                return rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.GREATER_THAN_OR_EQUAL, inputRef, literal);
            
            case "<":
            case "lt":
                literal = buildLiteral(rexBuilder, value, rowType.getFieldList().get(fieldIndex).getType());
                return rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.LESS_THAN, inputRef, literal);
            
            case "<=":
            case "lte":
                literal = buildLiteral(rexBuilder, value, rowType.getFieldList().get(fieldIndex).getType());
                return rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.LESS_THAN_OR_EQUAL, inputRef, literal);
            
            case "between":
                if (expr.size() < 4) {
                    throw new IllegalArgumentException("BETWEEN expression requires 4 elements: " + expr);
                }
                Object value1 = expr.get(2);
                Object value2 = expr.get(3);
                RelDataType fieldTypeForBetween = rowType.getFieldList().get(fieldIndex).getType();
                RexNode literal1 = buildLiteral(rexBuilder, value1, fieldTypeForBetween);
                RexNode literal2 = buildLiteral(rexBuilder, value2, fieldTypeForBetween);
                RexNode geCondition = rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.GREATER_THAN_OR_EQUAL, inputRef, literal1);
                RexNode leCondition = rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.LESS_THAN_OR_EQUAL, inputRef, literal2);
                return rexBuilder.makeCall(org.apache.calcite.sql.fun.SqlStdOperatorTable.AND, geCondition, leCondition);
            
            default:
                throw new IllegalArgumentException("Unsupported filter operator: " + operator);
        }
    }
    
    /**
     * 根据字段路径找到字段在行类型中的索引
     * 注意：JOIN 后的字段名就是属性名，不是完整路径
     */
    private int findFieldIndexByPath(FieldPathResolver.FieldPath fieldPath, RelDataType rowType) {
        String propertyName = fieldPath.getPropertyName();
        List<org.apache.calcite.rel.type.RelDataTypeField> fields = rowType.getFieldList();
        
        // 首先尝试精确匹配属性名
        for (int i = 0; i < fields.size(); i++) {
            String fieldName = fields.get(i).getName();
            if (propertyName.equals(fieldName)) {
                return i;
            }
        }
        
        // 如果精确匹配失败，尝试忽略大小写匹配
        for (int i = 0; i < fields.size(); i++) {
            String fieldName = fields.get(i).getName();
            if (propertyName.equalsIgnoreCase(fieldName)) {
                return i;
            }
        }
        
        return -1;
    }
    
    /**
     * 构建聚合查询（GROUP BY + 聚合函数）
     */
    private RelNode buildAggregate(RelNode input, List<String> groupBy, List<Object> metrics,
                                   ObjectType rootObjectType, List<OntologyQuery.LinkQuery> links) throws Exception {
        relBuilder.clear();
        relBuilder.push(input);
        
        RelDataType rowType = input.getRowType();
        RexBuilder rexBuilder = relBuilder.getRexBuilder();
        FieldPathResolver pathResolver = new FieldPathResolver(loader);
        
        // 构建分组字段
        List<RexNode> groupByNodes = new ArrayList<>();
        List<String> groupByNames = new ArrayList<>();
        if (groupBy != null && !groupBy.isEmpty()) {
            for (String fieldPath : groupBy) {
                FieldPathResolver.FieldPath fieldPathResult = pathResolver.resolve(fieldPath, rootObjectType, links);
                int fieldIndex = findFieldIndexByPath(fieldPathResult, rowType);
                if (fieldIndex < 0) {
                    throw new IllegalArgumentException("Group by field '" + fieldPath + "' not found");
                }
                RexInputRef inputRef = rexBuilder.makeInputRef(
                    rowType.getFieldList().get(fieldIndex).getType(),
                    fieldIndex
                );
                groupByNodes.add(inputRef);
                groupByNames.add(fieldPathResult.getPropertyName());
            }
        }
        
        // 构建聚合函数
        List<RelBuilder.AggCall> aggregateCalls = new ArrayList<>();
        List<String> aggregateNames = new ArrayList<>();
        if (metrics != null && !metrics.isEmpty()) {
            for (Object metricObj : metrics) {
                if (!(metricObj instanceof List)) {
                    throw new IllegalArgumentException("Metric must be an array: " + metricObj);
                }
                
                @SuppressWarnings("unchecked")
                List<Object> metric = (List<Object>) metricObj;
                if (metric.size() < 2) {
                    throw new IllegalArgumentException("Metric must have at least 2 elements: " + metric);
                }
                
                String function = metric.get(0).toString().toLowerCase();
                String fieldPath = metric.get(1).toString();
                String alias = metric.size() > 2 ? metric.get(2).toString() : null;
                
                // 解析字段路径
                FieldPathResolver.FieldPath fieldPathResult = pathResolver.resolve(fieldPath, rootObjectType, links);
                int fieldIndex = findFieldIndexByPath(fieldPathResult, rowType);
                if (fieldIndex < 0) {
                    throw new IllegalArgumentException("Metric field '" + fieldPath + "' not found");
                }
                
                // 使用 field() 方法获取字段引用
                org.apache.calcite.rex.RexNode fieldNode = relBuilder.field(fieldIndex);
                
                // 获取字段类型
                RelDataType fieldType = rowType.getFieldList().get(fieldIndex).getType();
                
                // 构建聚合函数调用
                RelBuilder.AggCall aggregateCall;
                switch (function) {
                    case "sum":
                        // 对于 SUM 函数，如果字段类型是 DECIMAL 或可能返回 DECIMAL（如数据库列是 DECIMAL），
                        // 先转换为 DOUBLE 再求和，避免 BigDecimal 无法转换为 Double 的错误
                        org.apache.calcite.rex.RexNode sumFieldNode = fieldNode;
                        SqlTypeName fieldSqlType = fieldType.getSqlTypeName();
                        if (fieldSqlType == SqlTypeName.DECIMAL || fieldSqlType == SqlTypeName.DOUBLE || fieldSqlType == SqlTypeName.FLOAT) {
                            // 将数值类型转换为 DOUBLE，确保 SUM 返回 DOUBLE 而不是 DECIMAL
                            RelDataType doubleType = relBuilder.getTypeFactory().createSqlType(SqlTypeName.DOUBLE);
                            sumFieldNode = rexBuilder.makeCast(doubleType, fieldNode, false);
                        }
                        aggregateCall = relBuilder.aggregateCall(
                            org.apache.calcite.sql.fun.SqlStdOperatorTable.SUM,
                            sumFieldNode
                        );
                        break;
                    case "avg":
                        // 对于 AVG 函数，也转换为 DOUBLE
                        org.apache.calcite.rex.RexNode avgFieldNode = fieldNode;
                        SqlTypeName avgFieldSqlType = fieldType.getSqlTypeName();
                        if (avgFieldSqlType == SqlTypeName.DECIMAL || avgFieldSqlType == SqlTypeName.DOUBLE || avgFieldSqlType == SqlTypeName.FLOAT) {
                            RelDataType doubleType = relBuilder.getTypeFactory().createSqlType(SqlTypeName.DOUBLE);
                            avgFieldNode = rexBuilder.makeCast(doubleType, fieldNode, false);
                        }
                        aggregateCall = relBuilder.aggregateCall(
                            org.apache.calcite.sql.fun.SqlStdOperatorTable.AVG,
                            avgFieldNode
                        );
                        break;
                    case "count":
                        aggregateCall = relBuilder.aggregateCall(
                            org.apache.calcite.sql.fun.SqlStdOperatorTable.COUNT,
                            fieldNode
                        );
                        break;
                    case "min":
                        aggregateCall = relBuilder.aggregateCall(
                            org.apache.calcite.sql.fun.SqlStdOperatorTable.MIN,
                            fieldNode
                        );
                        break;
                    case "max":
                        aggregateCall = relBuilder.aggregateCall(
                            org.apache.calcite.sql.fun.SqlStdOperatorTable.MAX,
                            fieldNode
                        );
                        break;
                    default:
                        throw new IllegalArgumentException("Unsupported aggregate function: " + function);
                }
                
                // 如果有别名，使用 as() 方法设置别名
                String finalAlias = alias != null ? alias : function + "_" + fieldPathResult.getPropertyName();
                aggregateCall = aggregateCall.as(finalAlias);
                
                aggregateCalls.add(aggregateCall);
                aggregateNames.add(finalAlias);
            }
        }
        
        // 如果没有分组字段，只有聚合函数，也需要构建 Aggregate
        if (!groupByNodes.isEmpty() || !aggregateCalls.isEmpty()) {
            if (!groupByNodes.isEmpty()) {
                // 有分组字段
                relBuilder.aggregate(
                    relBuilder.groupKey(groupByNodes),
                    aggregateCalls.toArray(new RelBuilder.AggCall[0])
                );
            } else {
                // 只有聚合函数，没有分组
                relBuilder.aggregate(
                    relBuilder.groupKey(),
                    aggregateCalls.toArray(new RelBuilder.AggCall[0])
                );
            }
        }
        
        return relBuilder.build();
    }

    /**
     * 关闭资源
     */
    public void close() throws SQLException {
        schemaFactory.closeConnections();
    }
}

