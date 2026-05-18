package com.mypalantir.reasoning;

import com.mypalantir.config.Config;
import com.mypalantir.meta.*;
import com.mypalantir.reasoning.cel.CelEvaluator;
import com.mypalantir.reasoning.engine.ForwardChainEngine;
import com.mypalantir.reasoning.engine.InferenceResult;
import com.mypalantir.reasoning.function.FunctionRegistry;
import com.mypalantir.reasoning.function.builtin.*;
import com.mypalantir.reasoning.swrl.SWRLParser;
import com.mypalantir.reasoning.swrl.SWRLRule;
import com.mypalantir.service.QueryService;
import com.mypalantir.query.QueryExecutor;
import org.springframework.stereotype.Service;

import jakarta.annotation.PostConstruct;
import java.util.*;

/**
 * 推理服务：整合 CEL 求值器、函数框架、SWRL 解析器和前向链引擎。
 */
@Service
public class ReasoningService {

    private final Loader loader;
    private final QueryService queryService;
    private final FunctionRegistry functionRegistry;
    private final CelEvaluator celEvaluator;
    private final Config config;

    private List<SWRLRule> parsedRules;
    private Map<String, String> functionDisplayNames = Map.of();

    public ReasoningService(Loader loader, QueryService queryService, FunctionRegistry functionRegistry, Config config) {
        this.loader = loader;
        this.queryService = queryService;
        this.functionRegistry = functionRegistry;
        this.celEvaluator = new CelEvaluator();
        this.config = config;
    }

    @PostConstruct
    public void initialize() {
        // 注册内置函数
        registerBuiltinFunctions();

        // 解析 SWRL 规则
        try {
            OntologySchema schema = loader.getSchema();
            SWRLParser parser = new SWRLParser(schema, functionRegistry);
            this.parsedRules = parser.parseAll(schema);
            System.out.println("Parsed " + parsedRules.size() + " SWRL rules");

            // 构建函数显示名映射
            if (schema.getFunctions() != null) {
                Map<String, String> names = new HashMap<>();
                for (FunctionDef fd : schema.getFunctions()) {
                    if (fd.getDisplayName() != null) {
                        names.put(fd.getName(), fd.getDisplayName());
                    }
                }
                this.functionDisplayNames = names;
            }

            // 检查未注册的 builtin 函数
            List<String> missing = functionRegistry.getMissingBuiltins(schema);
            if (!missing.isEmpty()) {
                System.err.println("WARNING: Missing builtin functions: " + missing);
            }
        } catch (Exception e) {
            System.err.println("Failed to initialize reasoning service: " + e.getMessage());
            this.parsedRules = List.of();
        }
    }

    private void registerBuiltinFunctions() {
        if ("fee".equals(config.getOntologyModel())) {
            // fee 模型的函数由 FeeService 注册
            return;
        }
        functionRegistry.register(new IsSingleProvinceEtc());
        functionRegistry.register(new IsObuBillingMode1());
        functionRegistry.register(new CheckRouteConsistency());
        functionRegistry.register(new DetectDuplicateIntervals());
        functionRegistry.register(new CheckGantryHexContinuity());
        functionRegistry.register(new CheckGantryCountComplete());
        functionRegistry.register(new DetectLateUpload());
        functionRegistry.register(new CheckFeeDetailConsistency());
        functionRegistry.register(new CheckRoundingMismatch());
        functionRegistry.register(new CheckBalanceContinuity());
    }

    /**
     * 对单个 Passage 执行推理
     */
    public InferenceResult inferPassage(String passageId) throws Exception {
        // 1. 查询 Passage 实例数据
        Map<String, Object> passage = queryInstance("Passage", passageId);
        if (passage == null) {
            throw new IllegalArgumentException("Passage not found: " + passageId);
        }

        // 2. 查询关联数据
        Map<String, List<Map<String, Object>>> linkedData = new LinkedHashMap<>();
        linkedData.put("passage_has_gantry_transactions", queryLinkedInstances("Passage", passageId, "passage_has_gantry_transactions"));
        linkedData.put("passage_has_split_details", queryLinkedInstances("Passage", passageId, "passage_has_split_details"));
        linkedData.put("passage_has_details", queryLinkedInstances("Passage", passageId, "passage_has_details"));

        // 查询出口交易和介质信息（供 IsSingleProvinceEtc/IsObuBillingMode1 使用）
        List<Map<String, Object>> exitTxList = queryLinkedInstances("Passage", passageId, "passage_has_exit");
        if (!exitTxList.isEmpty()) {
            passage.put("_exit_transaction", exitTxList.get(0));
        }

        // 查询入口交易，再从入口交易查询车辆和收费站
        List<Map<String, Object>> entryTxList = queryLinkedInstances("Passage", passageId, "passage_has_entry");
        if (!entryTxList.isEmpty()) {
            Map<String, Object> entryTx = entryTxList.get(0);
            String entryTxId = String.valueOf(entryTx.get("id"));

            // 从入口交易查车辆
            List<Map<String, Object>> vehicles = queryLinkedInstances("EntryTransaction", entryTxId, "entry_involves_vehicle");
            linkedData.put("entry_involves_vehicle", vehicles);

            // 从入口交易查收费站
            List<Map<String, Object>> stations = queryLinkedInstances("EntryTransaction", entryTxId, "entry_at_station");
            linkedData.put("entry_at_station", stations);

            // 从入口交易获取介质信息（EntryTransaction 表本身包含 MEDIATYPE/CARDNET 列）
            Map<String, Object> mediaPseudo = new LinkedHashMap<>();
            mediaPseudo.put("media_type", entryTx.get("media_type"));
            mediaPseudo.put("card_net", entryTx.get("card_net"));
            passage.put("_media", mediaPseudo);
        } else {
            linkedData.put("entry_involves_vehicle", List.of());
            linkedData.put("entry_at_station", List.of());
        }

        // 3. 计算衍生属性
        Map<String, Object> derivedValues = computeDerivedProperties(passage, linkedData);

        // 4. 执行前向链推理
        ForwardChainEngine engine = new ForwardChainEngine(functionRegistry, parsedRules, functionDisplayNames);
        return engine.infer(passage, linkedData, derivedValues);
    }

    /**
     * 批量推理
     */
    public List<Map<String, Object>> inferBatch(int limit) throws Exception {
        // 查询所有 Passage
        Map<String, Object> queryMap = new HashMap<>();
        queryMap.put("from", "Passage");
        queryMap.put("select", List.of("id", "pass_id"));
        queryMap.put("limit", limit);

        QueryExecutor.QueryResult result = queryService.executeQuery(queryMap);
        List<Map<String, Object>> results = new ArrayList<>();

        for (Map<String, Object> row : result.getRows()) {
            String passageId = String.valueOf(row.get("id"));
            try {
                InferenceResult ir = inferPassage(passageId);
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("passage_id", passageId);
                entry.put("result", ir.toMap());
                results.add(entry);
            } catch (Exception e) {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("passage_id", passageId);
                entry.put("error", e.getMessage());
                results.add(entry);
            }
        }
        return results;
    }

    /**
     * 计算衍生属性
     */
    private Map<String, Object> computeDerivedProperties(Map<String, Object> passage,
                                                          Map<String, List<Map<String, Object>>> linkedData) {
        Map<String, Object> derived = new LinkedHashMap<>();

        try {
            OntologySchema schema = loader.getSchema();
            ObjectType passageType = schema.getObjectTypes().stream()
                .filter(ot -> "Passage".equals(ot.getName()))
                .findFirst()
                .orElse(null);

            if (passageType != null && passageType.getProperties() != null) {
                for (Property prop : passageType.getProperties()) {
                    if (prop.isDerived() && prop.getExpr() != null) {
                        try {
                            Object value = celEvaluator.evaluate(prop.getExpr(), passage, linkedData);
                            derived.put(prop.getName(), value);
                        } catch (Exception e) {
                            System.err.println("Failed to evaluate derived property '" + prop.getName() + "': " + e.getMessage());
                        }
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("Failed to compute derived properties: " + e.getMessage());
        }

        return derived;
    }

    /**
     * 查询单个实例
     */
    public Map<String, Object> queryInstance(String objectType, String id) {
        try {
            Map<String, Object> queryMap = new HashMap<>();
            queryMap.put("from", objectType);
            queryMap.put("select", List.of("*"));
            queryMap.put("where", Map.of("id", id));
            queryMap.put("limit", 1);

            QueryExecutor.QueryResult result = queryService.executeQuery(queryMap);
            return result.getRows().isEmpty() ? null : result.getRows().get(0);
        } catch (Exception e) {
            System.err.println("Failed to query instance: " + e.getMessage());
            return null;
        }
    }

    /**
     * 查询关联实例（直接查询目标表，避免 link API 的结果扁平化问题）
     * @param sourceType 源对象类型名称
     * @param sourceId 源对象ID
     * @param linkName 关联关系名称
     */
    public List<Map<String, Object>> queryLinkedInstances(String sourceType, String sourceId, String linkName) {
        try {
            OntologySchema schema = loader.getSchema();
            LinkType linkType = schema.getLinkTypes().stream()
                .filter(lt -> linkName.equals(lt.getName()))
                .findFirst()
                .orElse(null);

            if (linkType == null) return List.of();

            String targetType = linkType.getTargetType();
            DataSourceMapping linkDs = linkType.getDataSource();
            if (linkDs == null || !linkDs.isConfigured()) return List.of();

            // 判断 cardinality 决定 FK 方向
            if ("many-to-one".equals(linkType.getCardinality())) {
                // FK 在源表中：先查源实例获取 FK 值，再按 target_id_column 查目标
                return queryManyToOneLink(sourceType, sourceId, targetType, linkDs);
            } else {
                // FK 在目标表中（one-to-many）：按 source_id_column 在目标表中查
                String fkProperty = determineForeignKeyProperty(linkType, sourceType);
                if (fkProperty == null) {
                    System.err.println("Cannot determine FK property for link " + linkName);
                    return List.of();
                }

                Map<String, Object> queryMap = new HashMap<>();
                queryMap.put("from", targetType);
                queryMap.put("select", List.of("*"));
                queryMap.put("where", Map.of(fkProperty, sourceId));

                QueryExecutor.QueryResult result = queryService.executeQuery(queryMap);
                return result.getRows();
            }
        } catch (Exception e) {
            System.err.println("Failed to query linked instances for " + linkName + ": " + e.getMessage());
            return List.of();
        }
    }

    /**
     * 处理 many-to-one 链接：FK 在源表中
     * 1. 查源实例获取 source_id_column 对应的属性值
     * 2. 在目标表中按 target_id_column 查找
     */
    private List<Map<String, Object>> queryManyToOneLink(String sourceType, String sourceId,
                                                          String targetType, DataSourceMapping linkDs) {
        String sourceIdColumn = linkDs.getSourceIdColumn();
        String targetIdColumn = linkDs.getTargetIdColumn();
        if (sourceIdColumn == null || targetIdColumn == null) return List.of();

        // 查找源类型中映射到 source_id_column 的属性名
        String sourceFkProperty = findPropertyForColumn(sourceType, sourceIdColumn);
        if (sourceFkProperty == null) return List.of();

        // 查询源实例获取 FK 值
        Map<String, Object> sourceInstance = queryInstance(sourceType, sourceId);
        if (sourceInstance == null) return List.of();

        Object fkValue = sourceInstance.get(sourceFkProperty);
        if (fkValue == null) return List.of();

        // 查找目标类型中映射到 target_id_column 的属性名
        String targetProperty = findPropertyForColumn(targetType, targetIdColumn);
        if (targetProperty == null) return List.of();

        // 查询目标类型
        try {
            Map<String, Object> queryMap = new HashMap<>();
            queryMap.put("from", targetType);
            queryMap.put("select", List.of("*"));
            queryMap.put("where", Map.of(targetProperty, fkValue.toString()));

            QueryExecutor.QueryResult result = queryService.executeQuery(queryMap);
            return result.getRows();
        } catch (Exception e) {
            System.err.println("Failed to query target for many-to-one link: " + e.getMessage());
            return List.of();
        }
    }

    /**
     * 查找对象类型中映射到指定数据库列的属性名
     */
    private String findPropertyForColumn(String typeName, String columnName) {
        try {
            ObjectType objectType = loader.getSchema().getObjectTypes().stream()
                .filter(ot -> typeName.equals(ot.getName()))
                .findFirst()
                .orElse(null);
            if (objectType == null) return null;

            DataSourceMapping ds = objectType.getDataSource();
            if (ds == null) return null;

            // 检查是否是 ID 列
            if (columnName.equalsIgnoreCase(ds.getIdColumn())) {
                return "id";
            }

            // 在属性映射中查找
            if (objectType.getProperties() != null) {
                for (Property prop : objectType.getProperties()) {
                    String colName = ds.getColumnName(prop.getName());
                    if (colName != null && colName.equalsIgnoreCase(columnName)) {
                        return prop.getName();
                    }
                }
                // 属性名直接匹配列名
                for (Property prop : objectType.getProperties()) {
                    if (prop.getName().equalsIgnoreCase(columnName)) {
                        return prop.getName();
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("Error finding property for column " + columnName + ": " + e.getMessage());
        }
        return null;
    }

    /**
     * 根据 link 定义确定目标表中的外键属性名
     */
    private String determineForeignKeyProperty(LinkType linkType, String sourceType) {
        // 对于 foreign_key 模式，source_id_column 是目标表中引用源表ID的列名
        // 需要将数据库列名映射回目标类型的属性名
        DataSourceMapping linkDs = linkType.getDataSource();
        if (linkDs == null || !linkDs.isConfigured()) return null;

        String sourceIdColumn = linkDs.getSourceIdColumn();
        if (sourceIdColumn == null) return null;

        // 查找目标类型中哪个属性映射到这个列
        String targetTypeName = linkType.getTargetType();
        try {
            ObjectType targetObjectType = loader.getSchema().getObjectTypes().stream()
                .filter(ot -> targetTypeName.equals(ot.getName()))
                .findFirst()
                .orElse(null);

            if (targetObjectType == null) return null;

            DataSourceMapping targetDs = targetObjectType.getDataSource();
            if (targetDs == null) return null;

            // 检查是否是 ID 列
            if (sourceIdColumn.equalsIgnoreCase(targetDs.getIdColumn())) {
                return "id";
            }

            // 在属性映射中查找
            if (targetObjectType.getProperties() != null) {
                for (Property prop : targetObjectType.getProperties()) {
                    String columnName = targetDs.getColumnName(prop.getName());
                    if (columnName != null && columnName.equalsIgnoreCase(sourceIdColumn)) {
                        return prop.getName();
                    }
                }
            }

            // 如果目标表列名与属性名相同（如 SplitDetail 的 pass_id）
            if (targetObjectType.getProperties() != null) {
                for (Property prop : targetObjectType.getProperties()) {
                    if (prop.getName().equalsIgnoreCase(sourceIdColumn)) {
                        return prop.getName();
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("Error determining FK property: " + e.getMessage());
        }
        return null;
    }

    /**
     * 获取已解析的规则数量
     */
    public int getParsedRuleCount() {
        return parsedRules != null ? parsedRules.size() : 0;
    }

    /**
     * 获取已注册的函数名
     */
    public Set<String> getRegisteredFunctions() {
        return functionRegistry.getFunctionNames();
    }

    /**
     * 按关键词搜索规则
     */
    public List<Map<String, Object>> searchRules(String keyword) {
        if (parsedRules == null) return List.of();
        String kw = keyword.toLowerCase();
        List<Map<String, Object>> results = new ArrayList<>();
        OntologySchema schema = loader.getSchema();
        List<com.mypalantir.meta.Rule> ruleDefs = schema.getRules();

        for (SWRLRule rule : parsedRules) {
            String name = rule.getName() != null ? rule.getName() : "";
            String displayName = rule.getDisplayName() != null ? rule.getDisplayName() : "";
            // 查找 YAML 中的 description
            String description = "";
            String expr = "";
            if (ruleDefs != null) {
                for (com.mypalantir.meta.Rule rd : ruleDefs) {
                    if (name.equals(rd.getName())) {
                        description = rd.getDescription() != null ? rd.getDescription() : "";
                        expr = rd.getExpr() != null ? rd.getExpr() : "";
                        break;
                    }
                }
            }
            if (name.toLowerCase().contains(kw) ||
                displayName.toLowerCase().contains(kw) ||
                description.toLowerCase().contains(kw)) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("name", name);
                m.put("displayName", displayName);
                m.put("description", description);
                m.put("expr", expr);
                results.add(m);
            }
        }
        return results;
    }

    public FunctionRegistry getFunctionRegistry() {
        return functionRegistry;
    }

    public Loader getLoader() {
        return loader;
    }
}
