package com.mypalantir.agent;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mypalantir.config.Config;
import com.mypalantir.service.LLMService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.function.Consumer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * ReAct 诊断 Agent 服务。
 * 核心循环：Thought → Action → Observation → Thought → ... → Answer
 * 支持流式回调，每步完成时通知调用方。
 */
@Service
public class AgentService {

    private static final Logger logger = LoggerFactory.getLogger(AgentService.class);
    private static final int MAX_STEPS = 15;

    private final LLMService llmService;
    private final AgentTools agentTools;
    private final AgentMemoryService memoryService;
    private final Config config;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public AgentService(LLMService llmService, AgentTools agentTools, AgentMemoryService memoryService, Config config) {
        this.llmService = llmService;
        this.agentTools = agentTools;
        this.memoryService = memoryService;
        this.config = config;
    }

    /**
     * SSE 事件类型
     */
    public record AgentEvent(String type, Map<String, Object> data) {
        public static AgentEvent step(AgentResponse.AgentStep step, int stepIndex) {
            Map<String, Object> d = new LinkedHashMap<>(step.toMap());
            d.put("step", stepIndex);
            return new AgentEvent("step", d);
        }

        public static AgentEvent answer(String answer) {
            return new AgentEvent("answer", Map.of("answer", answer));
        }

        public static AgentEvent error(String message) {
            return new AgentEvent("error", Map.of("message", message));
        }
    }

    /**
     * 流式执行 ReAct 循环，每步通过回调通知
     */
    public void chatStream(String userMessage, String sessionId, Consumer<AgentEvent> onEvent) {
        String systemPrompt = buildSystemPrompt();
        StringBuilder conversation = new StringBuilder();

        // 从记忆中加载对话历史
        if (sessionId != null) {
            var history = memoryService.getMessages(sessionId);
            if (!history.isEmpty()) {
                conversation.append("对话历史:\n");
                for (var msg : history) {
                    if (msg instanceof dev.langchain4j.data.message.UserMessage um) {
                        conversation.append("用户: ").append(um.singleText()).append("\n");
                    } else if (msg instanceof dev.langchain4j.data.message.AiMessage am) {
                        conversation.append("助手: ").append(am.text()).append("\n");
                    }
                }
                conversation.append("\n");
            }
        }

        conversation.append("用户问题: ").append(userMessage).append("\n\n");
        conversation.append("请开始你的推理。\n");

        long totalStart = System.currentTimeMillis();
        logger.info("=== Agent start === systemPrompt length={}, userMessage length={}",
                systemPrompt.length(), userMessage.length());

        int stepIndex = 0;
        int toolCallCount = 0;
        for (int i = 0; i < MAX_STEPS; i++) {
            String llmResponse;
            long llmStart = System.currentTimeMillis();
            try {
                logger.info("Step {}: calling LLM, conversation length={}", i + 1, conversation.length());
                llmResponse = llmService.chat(systemPrompt, conversation.toString());
            } catch (LLMService.LLMException e) {
                logger.error("LLM call failed at step {}: {} ({}ms)", i + 1, e.getMessage(),
                        System.currentTimeMillis() - llmStart);
                onEvent.accept(AgentEvent.error("LLM 调用失败: " + e.getMessage()));
                return;
            }
            long llmElapsed = System.currentTimeMillis() - llmStart;

            logger.info("Step {}: LLM response length={}, LLM耗时={}ms", i + 1, llmResponse.length(), llmElapsed);

            String thought = extractSection(llmResponse, "Thought");
            String answer = extractSection(llmResponse, "Answer");

            if (answer != null) {
                // 发送最终思考步骤
                if (thought != null) {
                    stepIndex++;
                    AgentResponse.AgentStep step = new AgentResponse.AgentStep(thought, null, null);
                    onEvent.accept(AgentEvent.step(step, stepIndex));
                }
                long totalElapsed = System.currentTimeMillis() - totalStart;
                logger.info("=== Agent finished === 总耗时={}ms, 步数={}, 工具调用={}次", totalElapsed, i + 1, toolCallCount);
                saveToMemory(sessionId, userMessage, answer);
                onEvent.accept(AgentEvent.answer(answer));
                return;
            }

            String actionJson = extractSection(llmResponse, "Action");
            if (actionJson == null) {
                saveToMemory(sessionId, userMessage, llmResponse);
                onEvent.accept(AgentEvent.answer(llmResponse));
                return;
            }

            // 解析工具调用
            String toolName = null;
            Map<String, Object> toolArgs = null;
            try {
                Map<String, Object> action = objectMapper.readValue(actionJson, new TypeReference<>() {});
                toolName = (String) action.get("tool");
                @SuppressWarnings("unchecked")
                Map<String, Object> args = (Map<String, Object>) action.get("args");
                toolArgs = args;
            } catch (Exception e) {
                logger.warn("Failed to parse action JSON: {}", actionJson);
                stepIndex++;
                AgentResponse.AgentStep step = new AgentResponse.AgentStep(thought, "parse_error", Map.of("raw", actionJson));
                step.setObservation("Action JSON 格式错误，请按格式输出。");
                onEvent.accept(AgentEvent.step(step, stepIndex));
                conversation.append(llmResponse).append("\nObservation: Action JSON 格式错误，请按格式输出。\n\n");
                continue;
            }

            // 发送 thought+action 事件（observation 待填充）
            stepIndex++;
            AgentResponse.AgentStep step = new AgentResponse.AgentStep(thought, toolName, toolArgs);

            // 先发送 thought + action（标记 observation 为 pending）
            onEvent.accept(AgentEvent.step(step, stepIndex));

            // 执行工具
            toolCallCount++;
            long toolStart = System.currentTimeMillis();
            String observation = agentTools.executeTool(toolName, toolArgs != null ? toolArgs : Map.of());
            long toolElapsed = System.currentTimeMillis() - toolStart;
            logger.info("Step {}: tool={}, observation length={}, 工具耗时={}ms", i + 1, toolName, observation.length(), toolElapsed);

            if (observation.length() > 3000) {
                observation = observation.substring(0, 3000) + "\n...(结果已截断)";
            }

            step.setObservation(observation);
            // 发送带 observation 的完整步骤
            onEvent.accept(AgentEvent.step(step, stepIndex));

            conversation.append(llmResponse).append("\nObservation: ").append(observation).append("\n\n");
        }

        long totalElapsed = System.currentTimeMillis() - totalStart;
        logger.info("=== Agent finished === 总耗时={}ms, 达到最大步数", totalElapsed);
        onEvent.accept(AgentEvent.error("达到最大推理步数(" + MAX_STEPS + ")"));
    }

    /**
     * 同步版本（保留向后兼容）
     */
    public AgentResponse chat(String userMessage) {
        return chat(userMessage, null);
    }

    public AgentResponse chat(String userMessage, String sessionId) {
        List<AgentResponse.AgentStep> steps = new ArrayList<>();
        final String[] finalAnswer = {null};

        chatStream(userMessage, sessionId, event -> {
            switch (event.type()) {
                case "step" -> {
                    String thought = (String) event.data().get("thought");
                    String tool = (String) event.data().get("tool");
                    @SuppressWarnings("unchecked")
                    Map<String, Object> args = (Map<String, Object>) event.data().get("args");
                    String obs = (String) event.data().get("observation");
                    if (obs != null) {
                        // 只在有 observation 时添加（避免重复）
                        AgentResponse.AgentStep s = new AgentResponse.AgentStep(thought, tool, args);
                        s.setObservation(obs);
                        // 替换或添加
                        int idx = (int) event.data().get("step") - 1;
                        while (steps.size() <= idx) steps.add(null);
                        steps.set(idx, s);
                    }
                }
                case "answer" -> finalAnswer[0] = (String) event.data().get("answer");
                case "error" -> finalAnswer[0] = (String) event.data().get("message");
            }
        });

        steps.removeIf(Objects::isNull);
        return new AgentResponse(finalAnswer[0] != null ? finalAnswer[0] : "未能得出结论", steps);
    }

    private void saveToMemory(String sessionId, String userMessage, String answer) {
        if (sessionId != null && answer != null) {
            memoryService.addUserMessage(sessionId, userMessage);
            memoryService.addAiMessage(sessionId, answer);
        }
    }

    private String extractSection(String text, String sectionName) {
        Pattern pattern = Pattern.compile(sectionName + ":\\s*(.*?)(?=\\n(?:Thought|Action|Answer|Observation):|$)",
                Pattern.DOTALL);
        Matcher matcher = pattern.matcher(text);
        if (matcher.find()) {
            return matcher.group(1).trim();
        }
        return null;
    }

    private String buildSystemPrompt() {
        if ("fee".equals(config.getOntologyModel())) {
            return buildFeeSystemPrompt();
        }
        return buildTollSystemPrompt();
    }

    private String buildTollSystemPrompt() {
        return """
            你是高速公路收费拆分异常诊断助手。你可以回答用户的一般性问题，也可以帮助诊断拆分异常。

            ## 判断用户意图

            根据用户的**动词/意图**判断模式，而不是仅看是否提到了ID：

            1. **一般性问题**（"你是谁"、"什么是拆分"等）→ 直接用 Answer 回答，不调用工具。
            2. **数据查询**（"查询"、"查看"、"显示"、"列出" + 数据）→ 使用 query_data 或 query_instance/query_links 获取数据后直接展示，不进入诊断流程。
               - 例："查询 PASS_LATE_001 的路径明细"、"查看所有通行记录"、"显示门架交易数据"
            3. **诊断排查**（"为什么"、"诊断"、"排查"、"分析异常原因"）→ 进入诊断模式，按诊断步骤逐步调用工具。
               - 例："帮我查一下 PASS_LATE_001 为什么拆分异常"、"排查 PASS_LATE_001 的异常原因"

            **关键区别：** 提到具体ID不等于要诊断。"查询 PASS_LATE_001 的门架交易"是数据查询，"PASS_LATE_001 为什么异常"才是诊断。

            ## 可用工具

            """ + agentTools.getToolDescriptions() + """

            ## 输出格式

            每次回复只包含以下格式之一：

            格式A - 调用工具：
            Thought: 分析当前已知信息，说明发现了什么、为什么要做下一步（2-3句）
            Action: {"tool": "工具名", "args": {参数}}

            格式B - 回答/结论：
            Thought: 总结
            Answer: 回答内容

            ## 数据模型（用于理解工具参数）

            - Passage（通行路径）关联：passage_has_gantry_transactions, passage_has_split_details, passage_has_entry, passage_has_exit

            ## 推理要求

            - 根据用户意图自主决定调用哪些工具、调用顺序和调用次数
            - 数据查询类请求：获取数据后直接展示
            - 诊断类请求：先获取数据，再用 search_rules 检索相关诊断规则了解异常判定逻辑，然后根据规则选择合适的 call_function 验证假设
            - Thought 中要体现分析推理过程（发现了什么、推测什么原因、为什么要做下一步），而不仅仅是"我要调用某工具"
            - 每次只输出一个 Action
            - 给出最终结论前，确保已经充分调查（有数据支撑你的结论）
            """;
    }

    private String buildFeeSystemPrompt() {
        return """
            你是高速公路费率管理助手。你可以回答用户关于费率、收费单元、路网的问题，也可以执行费率计算管道。

            ## 核心概念

            - 收费站(TollStation): 高速公路收费站
            - 收费单元(TollUnit): 两个节点之间的收费区间，有费率代码(rateCode)和计费里程
            - 基础费率(BaseRate): 按(费率代码, 车型)定义的单价
            - 路网有向边(Contiguity): E1-E6规则生成的路网连通图
            - 省级计费参数(ProvinceRateParam): R1-R3规则生成的每个(单元,车型)的fee/mfee/efee
            - 最小费额路径(MinimumFeePath): Dijkstra搜索的最短费额路径

            ## 工作流程

            完整的费率计算需要按以下顺序执行管道：
            1. build_graph → 生成路网有向边
            2. compute_fees → 计算各单元的计费参数
            3. find_path → Dijkstra搜索最小费额路径
            4. validate_path → 验证路径结果

            当用户问"从A到B多少钱"时，你需要依次调用上述4个工具。
            如果路网和费率已经生成过，可以直接从find_path开始。

            ## 可用工具

            """ + agentTools.getToolDescriptions() + """

            ## 输出格式

            每次回复只包含以下格式之一：

            格式A - 调用工具：
            Thought: 分析当前已知信息，说明发现了什么、为什么要做下一步（2-3句）
            Action: {"tool": "工具名", "args": {参数}}

            格式B - 回答/结论：
            Thought: 总结
            Answer: 回答内容

            ## 推理要求

            - 根据用户意图自主决定调用哪些工具、调用顺序和调用次数
            - Thought 中要体现分析推理过程
            - 每次只输出一个 Action
            - 费率计算结果请以清晰的格式展示(MTC费额、ETC费额、途经单元等)
            """;
    }
}
