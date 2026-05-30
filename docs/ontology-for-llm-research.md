# 面向 LLM 的业务领域本体建模：调研报告

> 核心问题：我们对业务进行本体建模（领域建模），什么样的本体模型适合让 LLM 理解、推理、生成？
>
> 调研时间：2026-05-29

---

## 一、背景：为什么传统本体不适合 LLM

传统本体工程（OWL/RDF）依赖描述逻辑推理（subsumption、consistency checking），而 LLM 不具备这类形式推理能力。LLM 擅长的是：

- 从结构化 schema 中做**模式匹配和选择**
- 理解**自然语言约束**和前置条件
- 按模板**生成结构化输出**
- 在 well-described 的选项空间中做**规划**

研究表明，形式推理必须由外部 reasoner 完成，LLM 只负责理解语义和选择行为 [1]。因此面向 LLM 的本体需要是 **prompt-native** 的——其表示格式本身可直接嵌入 prompt 被 LLM 理解。

---

## 二、适合 LLM 的本体应有的基本结构

综合 KnowAgent [2]、Agent-as-a-Graph [3] 和 PDDL 规划研究，理想的 LLM-native 本体模型应有四层分离：

### 2.1 概念层（What exists）

领域中的实体类型和属性定义。每个对象类型应有：
- 类型化属性（typed properties）
- 自然语言描述（description/summary）
- 对象分类（entity / rule_table / lookup_table 等）

这一层相当于传统本体中的 TBox（术语层），但以 YAML/JSON Schema 而非 OWL 表达。

### 2.2 关系层（How things connect）

对象之间的关联关系。除了基本的 join key，还应包含语义方向性和基数（详见第三节）。

### 2.3 行为层（What can be done）

领域中可执行的操作（functions）和确定性规则（rules）。关键设计原则是**将确定性计算与 LLM 判断分开**——rules 由引擎确定性执行，functions 由 LLM 规划调用。这与 "LLM as World Model" [4] 的方向一致。

### 2.4 流程层（In what order）

业务流程的步骤定义、分支条件和触发机制。

---

## 三、当前模型缺失的本体构造

以下是研究文献中被认为重要、但在我们当前 ontology.yaml / schema.py 元模型中未覆盖的维度。

### 3.1 前置条件与后置效果（Preconditions & Effects）

**研究依据：**

PDDL 规划领域的核心概念。"LLMs as World Models" [4] 和 PDDL-INSTRUCT [5] 明确证明：LLM 在 precondition-effect 结构**显式给出**时规划准确率显著提高，而仅靠自然语言描述推断时错误率很高。DIGGER (EMNLP 2025) [6] 报告 GPT-4 从自然语言生成 PDDL 计划的准确率仅 35%。

Generating Consistent PDDL Domains [7] 进一步强调 action consistency——action A 的 effect 必须能满足 action B 的 precondition，这种一致性校验对可靠规划至关重要。

**当前缺失：**

我们的 functions 有 `depends_on` 和 `hint`，但前/后置条件是自然语言混在 description 里的。例如 `dispatch_drone` 的前置条件 `ComplianceCheck.overall_result=通过 AND FlightApproval.approval_status=已批准` 散落在 `ReconMission.description`、`dispatch_drone.description` 等多处。

**建议的结构化表达：**

```yaml
dispatch_drone:
  preconditions:
    - {object: ComplianceCheck, field: overall_result, value: "通过"}
    - {object: FlightApproval, field: approval_status, value: "已批准"}
  effects:
    - {object: Drone, field: status, set_to: "任务中"}
    - {object: ReconMission, field: status, set_to: "执行中"}
```

**优先级：极高** — 直接影响规划正确性。

---

### 3.2 状态机 / 生命周期（State Machines）

**研究依据：**

Generating Consistent PDDL Domains [7] 强调 action consistency——action 之间的状态变换必须形成合法路径。LASP (RSS 2024) [8] 的规划系统中，对象状态是 action 前置条件的核心组成部分。LLM-Augmented Symbolic Planning 的五个角色之一就是 "cause analyzer"——分析状态转换链。

**当前缺失：**

多个对象有 `status` 字段（如 `ReconMission`: 计划中/审批中/执行中/数据处理/完成/取消），但合法的状态转换路径没有在本体中表达。LLM 需要从多段 description 文本中"猜"出合法路径。

**建议的结构化表达：**

```yaml
ReconMission:
  status_transitions:
    计划中: [审批中, 取消]
    审批中: [执行中, 取消]
    执行中: [数据处理, 取消]
    数据处理: [完成]
```

对应的 schema.py 元模型扩展：

```python
class ObjectTypeDef(BaseModel):
    kind: str = "entity"
    description: str = ""
    summary: str = ""
    properties: dict[str, PropertyDef] = {}
    status_transitions: dict[str, list[str]] = {}  # 新增
```

**优先级：高** — 可被 harness 用于运行时拦截非法状态转换。

---

### 3.3 否定知识 / 排斥约束（Negative Knowledge）

**研究依据：**

Ontology-Grounded LLM Construction [1] 指出 **class disjointness** 和 **domain/range constraints** 对减少幻觉至关重要。形式推理模块通过检测违反类不相交性、值域约束和逻辑公理的行为，可以拒绝或降低 LLM 输出的置信度 (Zhao et al., 2025)。

Ali et al. (2026) 在临床问答中通过 RDF/OWL 本体约束将幻觉率从 63% 降至 1.7%。

**当前缺失：**

我们的 ontology 里有重要的否定知识，但全部散落在 description 自然语言中：
- "AccidentEvent 不涉及设施损伤检查（不适用 inspect_facility）"
- "status=维护中 的无人机不可派遣"
- "自然灾害事件需要无人机；交通事故不需要"

这些**不能做什么**的知识对 LLM 来说比**能做什么**更容易遗漏。

**建议的结构化表达：**

```yaml
AccidentEvent:
  excluded_functions: [inspect_facility, plan_recon_mission]
  exclusion_reason: "事故不涉及设施损伤检查和无人机侦测"

Drone:
  constraints:
    - when: {field: status, value: "维护中"}
      excluded_functions: [dispatch_drone]
      reason: "维护中的无人机不可派遣"
```

**优先级：高** — LLM 对"不适用"场景最容易产生幻觉。

---

### 3.4 时间约束与期限（Temporal Constraints）

**研究依据：**

LASP (RSS 2024) [8] 的规划系统中，时间窗口是 action 的一等公民属性。在应急领域，时间约束直接影响决策优先级和合规性。

**当前缺失：**

我们的 `hint` 里有"首报要快（2小时内）"、`ResponseLevelRule` 有 `time_limit_hours`，但时间约束没有结构化地关联到 function 或 workflow step 上。

**建议的结构化表达：**

```yaml
generate_event_report:
  temporal_constraints:
    - when: {report_type: "首报"}
      deadline: "event_time + 2h"
    - when: {report_type: "续报"}
      deadline: "首报时间 + 24h"

emergency_response:
  steps:
    - name: 启动应急响应
      sla: "接报后 30min"
```

**优先级：高** — 应急场景的核心需求。

---

### 3.5 因果关系 vs 数据关联（Causal Links）

**研究依据：**

LLM-empowered Knowledge Graph Construction [9] 中，因果关系（A *causes* B, A *enables* B, A *prevents* B）被作为知识图谱的一等公民。Graphusion (Yang et al., 2024) 通过引入因果推理和逻辑一致性增强了图融合质量。Ontology-Grounded RAG 方法使用超图（hypergraph）表示，其中超边封装了植根于本体概念的事实簇，如 `("Soybean rust", causes, "yield loss")`。

**当前缺失：**

我们的 `links` 只表达数据关联（join key），不表达因果方向。`warning_has_defense` 和 `disaster_has_inspections` 在结构上看起来同类，但语义完全不同——前者是因果触发，后者是包含关系。

**建议的结构化表达：**

```yaml
links:
  warning_triggers_defense:
    source: WeatherWarning
    target: DefenseResponse
    join: {source_key: warning_id, target_key: warning_id}
    link_type: causal        # 新增：causal / contains / enables / prevents
    description: 预警触发防御响应

  disaster_has_inspections:
    source: DisasterEvent
    target: FacilityInspection
    join: {source_key: event_id, target_key: event_id}
    link_type: contains
    cardinality: "1..n"       # 新增
    required_for: [generate_clearance_plans]  # 新增
    description: 灾害事件下的设施检查记录
```

**优先级：中高** — 帮助 LLM 区分"查数据"和"理解因果"。

---

### 3.6 角色与权限（Role Ontology）

**研究依据：**

FAOS 架构 [10]（2026）提出企业 Agent 系统需要三层本体：**Role Ontology**、**Domain Ontology**、**Interaction Ontology**。

其中 Role Ontology 定义：
- 谁有权执行什么操作
- 在什么条件下
- 承担什么责任

这些 ontological constraints 被用于"bound the stochastic behavior of LLM agents within formally defined operational envelopes"。

**当前缺失：**

我们的模型完全没有角色概念。`dispatch_drone` 谁有权批准？不同响应级别（一级/二级/三级/四级）对应不同的负责机构和审批权限，`ResponseLevelRule` 里有 `responsible_org`，但没有关联到 function 的执行权限。

**建议的结构化表达：**

```yaml
roles:
  county_emergency_office:
    level: IV
    can_execute: [set_traffic_control, dispatch_resources]
    cannot_execute: [assess_event_level_to_I]

  provincial_emergency_dept:
    level: II
    can_execute: [all]
    approval_for: [dispatch_drone, set_traffic_control]
```

**优先级：中** — 取决于系统是否需要多角色协作。

---

### 3.7 数据来源与可观测性（Data Provenance）

**研究依据：**

FAOS [10] 提出 agent 需要知道数据的**来源和可信度**。Salesforce 的双本体架构 [11] 区分 Descriptive Ontology（业务语义）和 Structural Ontology（数据在哪、怎么取），认为分离两层可以让 LLM 先理解业务意图再映射到数据操作。

**当前缺失：**

我们的对象隐含分为"外部接口数据"和"智能体写入产物"（在 YAML 注释中标注），但没有在元模型中结构化。`kind` 区分了 entity/rule_table/lookup_table，但没有区分：
- **数据源类型**：external_api / agent_generated / human_confirmed
- **可变性**：immutable / append_only / mutable
- **可信度**：factual / inferred / estimated

**建议的结构化表达：**

```yaml
RoadSegment:
  kind: entity
  data_source: external_api     # 新增
  mutability: read_only         # 新增
  description: ...

FacilityInspection:
  kind: entity
  data_source: agent_generated  # 新增
  mutability: append_only       # 新增
  requires_review: true         # 新增
  description: ...
```

**优先级：中** — 帮助 LLM 和 harness 区分可信数据与需审核的推断结果。

---

### 3.8 交互协议（Interaction Ontology）

**研究依据：**

FAOS [10] 的 Interaction Ontology 定义 agent 与外部系统/人类的交互模式：什么时候需要人工确认、什么时候可以自主执行、信息流向谁。

**当前缺失：**

我们的 harness.py 里有 `requires_confirmation` 的概念（`ToolMeta`），但这是硬编码在运行时的，不是本体的一部分。哪些操作需要人工审批、在什么条件下可以自动执行，这些是领域知识而非系统配置。

**建议的结构化表达：**

```yaml
dispatch_drone:
  interaction:
    requires_human_approval: true
    approval_role: flight_authority
    autonomous_if: {scenario: "应急抢险"}  # S3第29条允许快速审批
```

**优先级：中** — 使审批逻辑从 harness 硬编码变为本体驱动。

---

### 3.9 描述本体 vs 结构本体分离（Descriptive vs Structural）

**研究依据：**

Salesforce Agentforce 的双本体架构 [11]：
- **描述本体（Descriptive Ontology）**：业务语义——一个概念在业务中意味着什么（如"premium support entitlement"意味着什么条件组合）
- **结构本体（Structural Ontology）**：数据在哪里、怎么取、字段间怎么关联

当 agent 处理查询时，先查描述本体理解业务意图，再查结构本体定位数据，最后用描述本体应用业务规则。

**当前缺失：**

我们的 `ObjectTypeDef` 把两者混在一起——既描述业务语义（description/summary），又定义数据结构（properties/kind）。在当前规模下这不是瓶颈，但随着领域复杂度增加，分离这两层可以让 LLM 先理解"业务意图"再映射到"数据操作"。

**优先级：低（当前规模不紧迫）** — 架构层面的长期演进方向。

---

## 四、Ontology 的 Token Budget 问题

除了本体内容的完备性，还有一个实践问题：**如何向 LLM 注入本体**。

### 4.1 渐进式本体注入（Progressive Ontology Prompting）

Progressive Ontology Prompting (IJCAI-25) [12] 提出：不要一次性给全部 ontology，而是按需逐步展开。直接 prompting 包含完整 KG schema 的方法会忽略概念间的上下文相关性，导致不完整的标注。

具体策略：
- **Step 1**：给 LLM 一个 summary 视图——所有 objects 的 summary + 所有 functions 的 summary
- **Step 2**：当 LLM 选择了某个 function，再展开该 function 的 params、hint、preconditions 及相关 objects 的完整 properties
- **Step 3**：执行时再注入相关 rules 的 conditions

### 4.2 Workflow 作为规划模板（Workflow Binding）

两种策略：
1. **Workflow 作为硬约束**：LLM 必须严格按 workflow 步骤执行（适合合规性要求高的场景）
2. **Workflow 作为 soft guidance**：LLM 参考 workflow 但可灵活调整（适合创造性场景）

当触发条件匹配某个 workflow 时，harness 可切换到 "guided mode"——把 workflow steps 作为 plan template 注入 prompt，LLM 只需决定每步的参数和是否跳过/分支，而不需从零构建计划。

---

## 五、优先级总结

| 优先级 | 缺失构造 | 影响 |
|--------|---------|------|
| **极高** | 前置/后置条件 (3.1) | LLM 无法可靠判断 action 可用性，直接影响规划正确性 |
| **高** | 状态机 (3.2) | 非法状态转换无法被拦截 |
| **高** | 否定知识 (3.3) | LLM 对"不适用"场景最容易产生幻觉 |
| **高** | 时间约束 (3.4) | 应急场景的核心需求，无法自动检查 SLA 超时 |
| **中高** | 因果关系 (3.5) | links 语义模糊，LLM 无法区分因果与包含 |
| **中** | 角色/权限 (3.6) | 合规性无法结构化验证 |
| **中** | 数据来源 (3.7) | LLM 不知道哪些数据可信、哪些需审核 |
| **中** | 交互协议 (3.8) | 审批逻辑硬编码在 harness 中不灵活 |
| **低** | 描述/结构分离 (3.9) | 架构层面的长期演进方向 |

---

## 六、参考文献

1. **Ontology-Grounded LLM Construction** — Emergent Mind Survey (2024-2025). 综述了本体约束 LLM 输出的方法，包括形式推理模块检测违规、ontology-grounded RAG、置信度评分等。\
   https://www.emergentmind.com/topics/ontology-grounded-llm-construction

2. **KnowAgent: Knowledge-Augmented Planning for LLM-Based Agents** — arXiv, 2024. 提出通过外部 action knowledge base 增强 LLM agent 的规划能力，解决 LLM 内在知识不足的问题。\
   https://arxiv.org/pdf/2403.03101

3. **Agent-as-a-Graph: Knowledge Graph-Based Tool and Agent Retrieval for LLM Multi-Agent Systems** — arXiv, 2025. 用知识图谱结构化工具和 agent 的能力描述，解决大规模 MCP 工具检索问题。\
   https://arxiv.org/pdf/2511.18194

4. **Making Large Language Models into World Models with Precondition and Effect Knowledge** — arXiv, Sept 2024. 将 LLM 作为世界模型，核心是让 LLM 可靠地理解 action 的前置条件和效果。\
   https://arxiv.org/pdf/2409.12278

5. **PDDL-INSTRUCT: Teaching LLMs to Plan via Logical Chain-of-Thought Instruction Tuning** — arXiv, 2025. 通过 instruction tuning 显式教 LLM 按 precondition-effect 结构推理，显著提升规划性能。\
   https://arxiv.org/pdf/2509.13351

6. **DIGGER: LLM-based Open Domain Planning by Leveraging Entity-Attribute Knowledge** — EMNLP 2025 Findings. 报告 GPT-4 从自然语言生成 PDDL 计划准确率仅 35%，提出用 entity-attribute 知识弥补。\
   https://aclanthology.org/2025.findings-emnlp.138.pdf

7. **Generating Consistent PDDL Domains with Large Language Models** — arXiv, April 2024. 提出 LLM 生成 PDDL 时的一致性检查方法，确保 action 间的 precondition-effect 一致性。\
   https://arxiv.org/html/2404.07751v1

8. **LASP: LLM-Augmented Symbolic Planning** — RSS 2024. LLM 在规划中扮演五个角色（cause analyzer、precondition generator 等），与符号规划器协作。\
   https://www.roboticsproceedings.org/rss20/p037.pdf

9. **LLM-empowered Knowledge Graph Construction: A Survey** — arXiv, Oct 2025. 综述了 LLM 驱动的知识图谱构建，包括因果推理、本体学习、schema-based 与 open 方法。\
   https://arxiv.org/html/2510.20345v1

10. **FAOS: Ontology-Constrained Neural Reasoning in Enterprise Agentic Systems** — arXiv, 2026. 提出三层本体架构（Role / Domain / Interaction Ontology）约束企业 LLM agent 的行为边界。\
    https://arxiv.org/abs/2604.00555

11. **AI Agent Ontologies Bridge Business-Data Divide** (Salesforce Agentforce) — StartupHub.ai, Nov 2025. 提出 Descriptive Ontology（业务语义）+ Structural Ontology（数据结构）的双本体架构。\
    https://www.startuphub.ai/ai-news/ai-research/2025/ai-agent-ontologies-bridge-business-data-divide/

12. **A Progressive Ontology Prompting and Dual-LLM Framework** — IJCAI-25. 提出渐进式本体 prompting，通过遍历相邻本体节点迭代生成，避免一次性注入完整 schema 导致的信息丢失。\
    https://www.ijcai.org/proceedings/2025/1078.pdf

13. **LLMs4OL 2024/2025: Large Language Models for Ontology Learning Challenge** — ISWC 2024 / TIB-OP 2025. 评估 LLM 在 term typing、taxonomy discovery、relation extraction 上的表现，发现 prompt 设计对结果影响巨大。\
    https://arxiv.org/pdf/2409.10146 \
    https://www.tib-op.org/ojs/index.php/ocp/article/view/2913

14. **Understanding the Planning of LLM Agents: A Survey** — arXiv, Feb 2024. 首个从规划能力角度系统分析 LLM agent 的综述，分类为五个方向。\
    https://arxiv.org/pdf/2402.02716

15. **Automating the Generation of Prompts for LLM-based Action Choice in PDDL Planning** — arXiv, updated May 2025. 将 PDDL predicate 和 action schema 自动转换为自然语言 prompt snippet。\
    https://arxiv.org/html/2311.09830v4

16. **Reasoning about Affordances: Causal and Compositional Reasoning in LLMs** — arXiv, Feb 2025. 测试 LLM 对对象 affordance 的推理能力，发现 LLM 可能依赖记忆模式而非真正的因果推理。\
    https://arxiv.org/pdf/2502.16606

17. **KG-LLM-Papers** — GitHub (zjukg). 持续维护的 KG + LLM 集成论文列表，涵盖 MKGL (NeurIPS 2024)、UrbanKGent (NeurIPS 2024)、TrustUQA (AAAI 2025) 等。\
    https://github.com/zjukg/KG-LLM-Papers
