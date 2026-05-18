package com.mypalantir.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mypalantir.config.Config;
import com.mypalantir.meta.*;
import com.mypalantir.reasoning.ReasoningService;
import com.mypalantir.reasoning.engine.InferenceResult;
import com.mypalantir.reasoning.function.FunctionRegistry;
import com.mypalantir.query.OntologyQuery;
import com.mypalantir.service.NaturalLanguageQueryService;
import com.mypalantir.service.QueryService;
import com.mypalantir.query.QueryExecutor;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Agent 工具集：提供 ReAct agent 可调用的工具。
 */
@Component
public class AgentTools {

    private final ReasoningService reasoningService;
    private final QueryService queryService;
    private final NaturalLanguageQueryService nlqService;
    private final Config config;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public AgentTools(ReasoningService reasoningService, QueryService queryService,
                      NaturalLanguageQueryService nlqService, Config config) {
        this.reasoningService = reasoningService;
        this.queryService = queryService;
        this.nlqService = nlqService;
        this.config = config;
    }

    /**
     * 执行工具调用
     */
    public String executeTool(String toolName, Map<String, Object> args) {
        try {
            return switch (toolName) {
                case "query_instance" -> queryInstance(args);
                case "query_links" -> queryLinks(args);
                case "search_rules" -> searchRules(args);
                case "call_function" -> callFunction(args);
                case "run_inference" -> runInference(args);
                case "query_data" -> queryData(args);
                case "build_graph", "compute_fees", "find_path", "validate_path" -> executePipelineTool(toolName, args);
                default -> "未知工具: " + toolName;
            };
        } catch (Exception e) {
            return "工具执行错误: " + e.getMessage();
        }
    }

    /**
     * 查询实例数据
     * args: { "type": "Passage", "id": "PASS_LATE_001" }
     */
    private String queryInstance(Map<String, Object> args) throws Exception {
        String type = (String) args.get("type");
        String id = (String) args.get("id");
        if (type == null || id == null) return "缺少参数 type 或 id";

        Map<String, Object> instance = reasoningService.queryInstance(type, id);
        if (instance == null) return type + " " + id + " 不存在";
        return objectMapper.writeValueAsString(instance);
    }

    /**
     * 查询关联数据
     * args: { "type": "Passage", "id": "PASS_LATE_001", "link": "passage_has_gantry_transactions" }
     */
    private String queryLinks(Map<String, Object> args) throws Exception {
        String type = (String) args.get("type");
        String id = (String) args.get("id");
        String link = (String) args.get("link");
        if (type == null || id == null || link == null) return "缺少参数 type, id 或 link";

        List<Map<String, Object>> data = reasoningService.queryLinkedInstances(type, id, link);
        return objectMapper.writeValueAsString(data);
    }

    /**
     * 搜索规则
     * args: { "keyword": "obu_split" }
     */
    private String searchRules(Map<String, Object> args) throws Exception {
        String keyword = (String) args.get("keyword");
        if (keyword == null) return "缺少参数 keyword";

        List<Map<String, Object>> rules = reasoningService.searchRules(keyword);
        if (rules.isEmpty()) return "未找到匹配的规则";
        return objectMapper.writeValueAsString(rules);
    }

    /**
     * 调用诊断函数
     * args: { "passage_id": "PASS_LATE_001", "function": "check_route_consistency" }
     * 内部自动准备函数所需的参数数据
     */
    private String callFunction(Map<String, Object> args) throws Exception {
        String passageId = (String) args.get("passage_id");
        String funcName = (String) args.get("function");
        if (passageId == null || funcName == null) return "缺少参数 passage_id 或 function";

        FunctionRegistry registry = reasoningService.getFunctionRegistry();
        if (!registry.hasFunction(funcName)) return "函数 " + funcName + " 未注册";

        // 准备 Passage 实例数据（与 inferPassage 类似）
        Map<String, Object> passage = reasoningService.queryInstance("Passage", passageId);
        if (passage == null) return "Passage " + passageId + " 不存在";

        // 查询关联数据
        List<Map<String, Object>> gantryTxs = reasoningService.queryLinkedInstances("Passage", passageId, "passage_has_gantry_transactions");
        List<Map<String, Object>> splitDetails = reasoningService.queryLinkedInstances("Passage", passageId, "passage_has_split_details");
        List<Map<String, Object>> exitTxList = reasoningService.queryLinkedInstances("Passage", passageId, "passage_has_exit");
        List<Map<String, Object>> entryTxList = reasoningService.queryLinkedInstances("Passage", passageId, "passage_has_entry");

        // 补充 _exit_transaction 和 _media
        if (!exitTxList.isEmpty()) {
            passage.put("_exit_transaction", exitTxList.get(0));
        }
        if (!entryTxList.isEmpty()) {
            Map<String, Object> entryTx = entryTxList.get(0);
            Map<String, Object> mediaPseudo = new LinkedHashMap<>();
            mediaPseudo.put("media_type", entryTx.get("media_type"));
            mediaPseudo.put("card_net", entryTx.get("card_net"));
            passage.put("_media", mediaPseudo);
        }

        // 根据函数签名确定参数
        List<Object> funcArgs = buildFunctionArgs(funcName, passage, gantryTxs, splitDetails);

        Object result = registry.call(funcName, funcArgs);
        return funcName + " → " + result;
    }

    /**
     * 根据函数名构建参数列表
     */
    private List<Object> buildFunctionArgs(String funcName, Map<String, Object> passage,
                                            List<Map<String, Object>> gantryTxs,
                                            List<Map<String, Object>> splitDetails) {
        return switch (funcName) {
            case "is_single_province_etc", "is_obu_billing_mode1" ->
                List.of(passage);
            case "check_route_consistency", "check_fee_detail_consistency" ->
                List.of(splitDetails, gantryTxs);
            case "detect_duplicate_intervals", "check_gantry_hex_continuity",
                 "check_gantry_count_complete", "check_balance_continuity" ->
                List.of(gantryTxs);
            case "check_rounding_mismatch" ->
                List.of(gantryTxs, 0.95);
            case "detect_late_upload" -> {
                // 需要 pro_split_time 参数
                Object proSplitTime = null;
                if (!splitDetails.isEmpty()) {
                    proSplitTime = splitDetails.get(0).get("pro_split_time");
                }
                yield List.of(gantryTxs, proSplitTime != null ? proSplitTime : "");
            }
            default -> List.of(passage);
        };
    }

    /**
     * 自然语言数据查询
     * args: { "query": "查询所有拆分异常的Passage" }
     */
    private String queryData(Map<String, Object> args) throws Exception {
        String query = (String) args.get("query");
        if (query == null) return "缺少参数 query";

        try {
            OntologyQuery ontologyQuery = nlqService.convertToQuery(query);
            Map<String, Object> queryMap = nlqService.convertToMap(ontologyQuery);
            QueryExecutor.QueryResult result = queryService.executeQuery(queryMap);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("columns", result.getColumns());
            resp.put("rowCount", result.getRowCount());
            resp.put("rows", result.getRows());
            return objectMapper.writeValueAsString(resp);
        } catch (NaturalLanguageQueryService.NaturalLanguageQueryException e) {
            return "查询失败: " + e.getMessage();
        }
    }

    /**
     * 执行完整推理
     * args: { "passage_id": "PASS_LATE_001" }
     */
    private String runInference(Map<String, Object> args) throws Exception {
        String passageId = (String) args.get("passage_id");
        if (passageId == null) return "缺少参数 passage_id";

        InferenceResult result = reasoningService.inferPassage(passageId);
        return objectMapper.writeValueAsString(result.toMap());
    }

    /**
     * 执行费率管道工具
     */
    private String executePipelineTool(String toolName, Map<String, Object> args) throws Exception {
        FunctionRegistry registry = reasoningService.getFunctionRegistry();
        if (!registry.hasFunction(toolName)) return "函数 " + toolName + " 未注册";

        List<Object> funcArgs = new ArrayList<>();
        switch (toolName) {
            case "build_graph" -> funcArgs.add(args.getOrDefault("version_id", ""));
            case "compute_fees" -> funcArgs.add(args.getOrDefault("vehicle_types", "1,2,3,4,11,12,13,14,15,16"));
            case "find_path" -> {
                funcArgs.add(args.get("en_station_id"));
                funcArgs.add(args.get("ex_station_id"));
                funcArgs.add(args.get("vehicle_type"));
            }
            case "validate_path" -> funcArgs.add(args.get("path_id"));
        }

        Object result = registry.call(toolName, funcArgs);
        return objectMapper.writeValueAsString(result);
    }

    /**
     * 获取工具描述（用于 system prompt）
     */
    public String getToolDescriptions() {
        if ("fee".equals(config.getOntologyModel())) {
            return getFeeToolDescriptions();
        }
        return getTollToolDescriptions();
    }

    private String getTollToolDescriptions() {
        return """
            1. query_instance - 查询实例基本数据
               参数: {"type": "类型名", "id": "实例ID"}
               示例: {"type": "Passage", "id": "PASS_LATE_001"}

            2. query_links - 查询关联数据
               参数: {"type": "类型", "id": "ID", "link": "关联名"}
               关联: passage_has_gantry_transactions(门架交易), passage_has_split_details(拆分明细), passage_has_entry(入口交易), passage_has_exit(出口交易)

            3. search_rules - 搜索SWRL诊断规则
               参数: {"keyword": "关键词"}

            4. call_function - 调用诊断函数
               参数: {"passage_id": "通行路径ID", "function": "函数名"}
               可用函数:
               - is_single_province_etc: 判断是否单省ETC交易
               - is_obu_billing_mode1: 判断OBU计费方式
               - check_route_consistency: 检查拆分路径与门架路径一致性
               - detect_duplicate_intervals: 检测门架收费单元重复
               - check_gantry_hex_continuity: 检查门架HEX编码连续性
               - check_gantry_count_complete: 检查门架数量完整性
               - detect_late_upload: 检测门架延迟上传
               - check_fee_detail_consistency: 检查费用明细一致性
               - check_rounding_mismatch: 检查四舍五入差异
               - check_balance_continuity: 检查卡内余额连续性

            5. run_inference - 执行完整规则引擎推理（一次性返回所有规则结果）
               参数: {"passage_id": "通行路径ID"}

            6. query_data - 用自然语言查询本体数据（支持过滤、聚合、排序等）
               参数: {"query": "自然语言查询，如：查询所有拆分异常的Passage"}
               示例: {"query": "显示入口站为S0085的所有Passage"}
               适用场景: 需要按条件批量查询、统计、筛选数据时使用
            """;
    }

    private String getFeeToolDescriptions() {
        return """
            1. query_instance - 查询实例基本数据
               参数: {"type": "类型名", "id": "实例ID"}
               类型: TollStation(收费站), TollUnit(收费单元), BaseRate(基础费率), Contiguity(路网边), ProvinceRateParam(计费参数), MinimumFeePath(最小费额路径)

            2. query_links - 查询关联数据
               参数: {"type": "类型", "id": "ID", "link": "关联名"}
               关联: unit_has_rate_params, unit_has_base_rate, unit_has_discounts, path_has_errors

            3. query_data - 用自然语言查询本体数据
               参数: {"query": "自然语言查询"}

            4. build_graph - 路网生成(E1-E6)：从收费单元/站/不可达规则生成路网有向边
               参数: {"version_id": "版本标识(可选)"}
               注意: 必须先执行此工具才能进行路径搜索

            5. compute_fees - 计费参数生成(R1-R3)：为每个(收费单元,车型)计算fee/mfee/efee
               参数: {"vehicle_types": "车型列表(逗号分隔), 如: 1,2,3,4"}
               注意: 必须在build_graph之后执行

            6. find_path - 最小费额路径搜索(Dijkstra)
               参数: {"en_station_id": "入口站编号", "ex_station_id": "出口站编号", "vehicle_type": 车型代码}
               注意: 必须在compute_fees之后执行

            7. validate_path - 路径验证(V1-V5)
               参数: {"path_id": "路径记录ID"}
               验证规则: V1连通性, V2 MTC总额, V3 ETC总额, V4序列长度, V5门架连续性
            """;
    }
}
