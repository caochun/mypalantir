# OAG 本体元模型规范

> 本文档描述 OAG（Ontology-Agent-Graph）系统的本体元模型——即如何用 YAML 定义一个业务领域的本体，以及每个构造的语义、字段和运行时行为。
>
> 元模型定义在 `agent/oag/schema.py`，领域本体定义在 `domains/<name>/ontology.yaml`。

---

## 总体结构

一个本体（`Ontology`）由五层构成：

```yaml
name: "领域名称"
description: "领域说明"

objects:     # 概念层 — 领域中的实体类型
links:       # 关系层 — 实体间的关联
functions:   # 行为层 — 可执行的操作
rules:       # 规则层 — 确定性判断逻辑
workflows:   # 流程层 — 多步业务流程
```

这五层的设计原则：**LLM 做规划和语义理解，确定性系统做计算和校验**。规则由引擎执行而非 LLM 推理，前置条件由运行时校验而非 LLM 自行判断，状态转换由系统拦截而非依赖 LLM 记住合法路径。

---

## 一、概念层：objects

定义领域中的实体类型和属性。运行时会为每个 object 创建 SQLite 表。

### ObjectTypeDef

| 字段 | 类型 | 说明 |
|------|------|------|
| `kind` | str | 对象分类：`entity`（业务实体）/ `rule_table`（规则配置表）/ `lookup_table`（查询参考表）/ `config` |
| `description` | str | 详细描述，会出现在 inspect 结果中 |
| `summary` | str | 一行摘要，出现在 system prompt 的对象列表中 |
| `properties` | dict[str, PropertyDef] | 属性定义 |
| `data_source` | str | 数据来源：`external_api`（外部接口）/ `agent_generated`（智能体产出）/ `human_confirmed`（人工确认） |
| `mutability` | str | 可变性：`read_only`（只读）/ `append_only`（仅追加）/ `mutable`（可读写） |
| `status_transitions` | dict[str, list[str]] | 状态机：每个状态可以转换到哪些目标状态 |
| `excluded_functions` | list[str] | 对此类型全局不可调用的函数列表 |
| `constraints` | list[ObjectConstraint] | 条件性约束，在特定状态下禁止调用某些函数 |

### PropertyDef

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | str | 数据类型：`str` / `int` / `float` / `bool` |
| `required` | bool | 是否必填。第一个 `required: true` 的属性会被作为业务主键 |
| `description` | str | 属性描述 |
| `default` | Any | 默认值 |

### ObjectConstraint

条件性行为约束，表达"在特定状态下不能做什么"。

| 字段 | 类型 | 说明 |
|------|------|------|
| `when` | dict[str, Any] | 触发条件，如 `{status: "维护中"}` |
| `excluded_functions` | list[str] | 此条件下不可调用的函数 |
| `reason` | str | 原因说明 |

### 运行时行为

- **mutability 校验**：`validate_mutate()` 在执行 mutate 前检查——`read_only` 对象拒绝任何写入，`append_only` 对象拒绝 update/delete
- **状态转换校验**：update 操作修改 status 字段时，检查 old_status → new_status 是否在 `status_transitions` 的合法路径中
- **排斥约束校验**：`check_constraints()` 在函数调用前检查目标对象类型是否在 `excluded_functions` 中
- **system prompt 展示**：对象列表中展示 mutability 标签、状态流转、排斥约束

### 示例

```yaml
Drone:
  kind: entity
  data_source: external_api
  mutability: read_only
  summary: "无人机(单机，按drone_id查)"
  status_transitions:
    可用: [任务中, 维护中]
    任务中: [可用]
    维护中: [可用]
    故障: [维护中]
  constraints:
    - when: {status: "维护中"}
      excluded_functions: [dispatch_drone]
      reason: "维护中的无人机不可派遣"
  properties:
    drone_id: {type: str, required: true, description: "无人机编号"}
    status: {type: str, description: "状态: 可用/任务中/维护中/故障"}
    # ...

AccidentEvent:
  kind: entity
  data_source: agent_generated
  mutability: append_only
  excluded_functions: [inspect_facility, plan_recon_mission]
  # ...
```

---

## 二、关系层：links

定义对象之间的关联关系，支持通过 `query_links` 工具进行关系查询。

### LinkDef

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | str | 源对象类型名 |
| `target` | str | 目标对象类型名 |
| `join` | dict[str, str] | 连接键，如 `{source_key: event_id, target_key: event_id}` |
| `description` | str | 关系描述 |
| `link_type` | str | 关系语义类型（见下表） |
| `cardinality` | str | 基数约束：`1..1` / `1..n` / `0..n` / `0..1` |

### link_type 取值

| 值 | 语义 | 示例 |
|----|------|------|
| `contains` | 包含/组成关系，source 拥有 target | 灾害事件包含检查记录 |
| `enables` | 依赖/前置关系，source 的存在使 target 可以被创建 | 侦测任务需要飞行审批 |
| `causal` | 因果关系，source 直接导致 target 产生 | （当前 drone 域暂无真正的因果关系） |
| `prevents` | 阻止关系，source 的存在阻止 target | （预留，尚无使用场景） |

### 运行时行为

- **system prompt 展示**：非 `contains` 类型的 link 会在关系列表中额外标注语义类型和基数
- **query_links 工具**：基于 join key 执行 SQL 关联查询

### 示例

```yaml
links:
  disaster_has_inspections:
    source: DisasterEvent
    target: FacilityInspection
    join: {source_key: event_id, target_key: event_id}
    link_type: contains
    cardinality: "1..n"
    description: 灾害事件下的设施检查记录

  mission_has_approval:
    source: ReconMission
    target: FlightApproval
    join: {source_key: mission_id, target_key: mission_id}
    link_type: enables
    cardinality: "1..1"
    description: 侦测任务需要飞行审批
```

---

## 三、行为层：functions

定义领域中可执行的操作。每个 function 会被注册为 LLM 可调用的工具（tool）。

### FunctionDef

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | str | 详细描述 |
| `summary` | str | 一行摘要，出现在 system prompt 和工具列表中 |
| `group` | str | 功能分组，如"事件与检查"、"资源调度" |
| `params` | dict[str, FunctionParam] | 参数定义 |
| `function_type` | str | 函数类型：`business`（业务操作，需确认）/ `lookup`（查询）/ `get`（获取） |
| `depends_on` | list[str] | 依赖的其他函数，调用前会自动确保依赖已执行 |
| `hint` | str | 详细执行规则，首次调用该函数后注入到 LLM 上下文中 |
| `writes_to` | list[str] | 写入的对象类型列表，标记为非只读工具 |
| `involves_objects` | list[str] | 涉及的对象类型（信息性，不影响执行） |
| `preconditions` | list[Precondition] | 前置条件，调用前由运行时校验 |
| `effects` | list[Effect] | 后置效果，声明执行后的状态变更 |
| `temporal_constraints` | list[TemporalConstraint] | 时间约束 / SLA |

### Precondition

声明函数可执行的前提条件。运行时在调用前检查，不满足则返回错误提示。

| 字段 | 类型 | 说明 |
|------|------|------|
| `object` | str | 对象类型名 |
| `field` | str | 字段名 |
| `operator` | str | 比较算子：`eq` / `ne` / `in` / `exists` / `not_exists` |
| `value` | Any | 期望值 |

### Effect

声明函数执行后的状态变更。当前仅用于 system prompt 展示，供 LLM 理解函数的副作用。

| 字段 | 类型 | 说明 |
|------|------|------|
| `object` | str | 被变更的对象类型 |
| `field` | str | 被变更的字段 |
| `set_to` | Any | 变更目标值 |

### TemporalConstraint

时间约束，声明函数在特定条件下的完成期限。通过 `check_sla` 工具供 LLM 查询。

| 字段 | 类型 | 说明 |
|------|------|------|
| `when` | dict[str, str] | 触发条件，如 `{report_type: "首报"}`。空 dict 表示所有情况 |
| `deadline` | str | 相对时间表达式，如 `"event_time + 2h"` |
| `sla` | str | 人类可读的 SLA 描述，如 `"事件发生后2小时内完成首报"` |

### FunctionParam

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | str | 参数类型：`str` / `int` / `float` |
| `description` | str | 参数描述 |
| `default` | Any | 默认值，有默认值的参数在工具调用时可选 |

### 运行时行为

- **前置条件校验**：`check_constraints()` 在函数调用前查 store，验证 preconditions 是否满足
- **hint 注入**：首次调用函数后，hint 内容追加到工具结果中，给 LLM 提供详细执行规则
- **system prompt 展示**：有 preconditions 的函数标注 `requires: [...]`，有 temporal_constraints 的标注 `SLA: ...`
- **工具注册**：每个 function 自动生成 OpenAI function-calling schema，`function_type=business` 或 `writes_to` 非空的工具标记为需要用户确认

### 示例

```yaml
dispatch_drone:
  summary: "调派无人机执行任务"
  description: "合规检查通过且飞行审批批准后，调派无人机执行侦测任务"
  group: "无人机侦测"
  preconditions:
    - {object: ComplianceCheck, field: overall_result, operator: eq, value: "通过"}
    - {object: FlightApproval, field: approval_status, operator: eq, value: "已批准"}
  effects:
    - {object: Drone, field: status, set_to: "任务中"}
    - {object: ReconMission, field: status, set_to: "执行中"}
  params:
    mission_id: {type: str, description: "任务编号"}

generate_event_report:
  summary: "生成灾情信息报告"
  temporal_constraints:
    - when: {report_type: "首报"}
      deadline: "event_time + 2h"
      sla: "事件发生后2小时内完成首报"
    - when: {report_type: "续报"}
      deadline: "首报时间 + 24h"
      sla: "首报后24小时内出续报"
  params:
    event_id: {type: str, description: "事件编号"}
    report_type: {type: str, default: "首报", description: "报告类型: 首报/续报/终报"}
```

---

## 四、规则层：rules

定义确定性的判断逻辑。规则由 RuleEngine 编译为 Python 函数并确定性执行，**LLM 不应自行推理规则逻辑**。

### RuleDef

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | str | 规则描述 |
| `rule_type` | str | 规则类型：`classification`（分类）/ `judgment`（判断）/ `qualification`（资质判定）/ `threshold`（阈值） |
| `applies_to` | list[str] | 适用的对象类型列表 |
| `conditions` | list[RuleCondition] | 条件列表，按顺序匹配，首个匹配的条件生效 |
| `result_field` | str | 结果写入的字段名 |
| `source` | str | 规则来源（如法规条号） |

### RuleCondition

| 字段 | 类型 | 说明 |
|------|------|------|
| `field` | str | 要检查的字段名 |
| `operator` | str | 算子：`eq` / `ne` / `gt` / `gte` / `lt` / `lte` / `in` / `between` / `like` |
| `value` | Any | 比较值 |
| `result` | Any | 匹配时的结果值 |

### 运行时行为

- RuleEngine 在初始化时将所有规则编译为 Python 函数
- LLM 通过 `apply_rule` / `apply_rule_batch` 工具调用规则
- 规则执行结果作为 JSON 返回，LLM 可据此决定下一步行动
- system prompt 中明确提示"使用 apply_rule 工具，不要自己推理规则逻辑"

### 示例

```yaml
rules:
  damage_to_access:
    description: "损伤等级→通行建议"
    rule_type: classification
    applies_to: [FacilityInspection]
    result_field: access_recommendation
    conditions:
      - {field: overall_damage_grade, operator: eq, value: "I", result: "观察通行"}
      - {field: overall_damage_grade, operator: eq, value: "II", result: "限制通行并加强观测"}
      - {field: overall_damage_grade, operator: eq, value: "III", result: "禁止通行并实施抢通"}

  drone_weight_classification:
    description: "按最大起飞重量分类无人机"
    rule_type: classification
    applies_to: [Drone]
    result_field: category
    source: "S3第二条"
    conditions:
      - {field: max_takeoff_weight_kg, operator: lte, value: 0.25, result: "微型"}
      - {field: max_takeoff_weight_kg, operator: lte, value: 7, result: "轻型"}
      - {field: max_takeoff_weight_kg, operator: lte, value: 25, result: "小型"}
      - {field: max_takeoff_weight_kg, operator: lte, value: 150, result: "中型"}
      - {field: max_takeoff_weight_kg, operator: gt, value: 150, result: "大型"}
```

---

## 五、流程层：workflows

定义多步业务流程，包含步骤序列、分支条件和时间约束。

### WorkflowDef

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | str | 工作流描述 |
| `trigger` | str | 触发条件描述 |
| `steps` | list[WorkflowStep] | 步骤列表 |
| `involves_objects` | list[str] | 涉及的对象类型 |

### WorkflowStep

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 步骤名称 |
| `function` | str | 要调用的函数名，空字符串表示人工步骤 |
| `description` | str | 步骤描述 |
| `next` | str \| dict[str, str] | 下一步。字符串表示固定下一步，dict 表示条件分支 |
| `sla` | str | 此步骤的时限要求 |

### 运行时行为

- LLM 通过 `start_workflow` 工具启动或推进工作流
- 运行时维护每个工作流的当前步骤状态
- system prompt 中展示完整的步骤序列、分支和 SLA
- 步骤的 SLA 通过 `check_sla` 工具暴露给 LLM

### 示例

```yaml
workflows:
  emergency_response:
    description: "公路交通应急处置全流程"
    trigger: "灾情发生或接报"
    involves_objects: [DisasterEvent, FacilityInspection, ClearancePlan]
    steps:
      - name: 启动应急响应
        description: "接报→疏散→安全措施→上报"
        sla: "接报后30分钟"
      - name: 无人机侦测
        function: plan_recon_mission
        next: 设施检查
      - name: 通行评估
        function: evaluate_traffic
        next: {通过: 信息报送, 不通过: 绕行方案}
      - name: 信息报送
        function: generate_event_report
        sla: "首报2小时内"
```

---

## 元模型与运行时的关系

本体元模型定义的数据通过以下运行时组件消费：

| 元模型构造 | 消费者 | 作用 |
|-----------|--------|------|
| objects.properties | Store | 建表、类型校验 |
| objects.mutability | OntologyRuntime.validate_mutate() | 拦截非法写入 |
| objects.status_transitions | OntologyRuntime.validate_mutate() | 拦截非法状态转换 |
| objects.excluded_functions | OntologyRuntime.check_constraints() | 拦截不适用的函数调用 |
| objects.constraints | OntologyRuntime.check_constraints() | 条件性排斥校验 |
| links | Store.query_links() | 关系查询 |
| functions.params | ToolRegistry | 生成工具参数 schema |
| functions.preconditions | OntologyRuntime.check_constraints() | 调用前校验 |
| functions.effects | OntologyRuntime.build_system_prompt() | 告知 LLM 副作用 |
| functions.hint | OntologyRuntime.inject_hint() | 首次调用后注入规则 |
| functions.temporal_constraints | OntologyRuntime.check_sla() | SLA 查询 |
| rules.conditions | RuleEngine | 编译为确定性函数 |
| workflows.steps | OntologyRuntime.start_workflow() | 流程推进 |
| workflows.steps.sla | OntologyRuntime.check_sla() | SLA 查询 |

---

## 附录：完整字段速查

```
Ontology
├── name: str
├── description: str
├── objects: dict[str, ObjectTypeDef]
│   ├── kind: str
│   ├── description: str
│   ├── summary: str
│   ├── data_source: str
│   ├── mutability: str
│   ├── properties: dict[str, PropertyDef]
│   │   ├── type: str
│   │   ├── required: bool
│   │   ├── description: str
│   │   └── default: Any
│   ├── status_transitions: dict[str, list[str]]
│   ├── excluded_functions: list[str]
│   └── constraints: list[ObjectConstraint]
│       ├── when: dict[str, Any]
│       ├── excluded_functions: list[str]
│       └── reason: str
├── links: dict[str, LinkDef]
│   ├── source: str
│   ├── target: str
│   ├── join: dict[str, str]
│   ├── description: str
│   ├── link_type: str
│   └── cardinality: str
├── functions: dict[str, FunctionDef]
│   ├── description: str
│   ├── summary: str
│   ├── group: str
│   ├── function_type: str
│   ├── depends_on: list[str]
│   ├── hint: str
│   ├── writes_to: list[str]
│   ├── involves_objects: list[str]
│   ├── params: dict[str, FunctionParam]
│   │   ├── type: str
│   │   ├── description: str
│   │   └── default: Any
│   ├── preconditions: list[Precondition]
│   │   ├── object: str
│   │   ├── field: str
│   │   ├── operator: str
│   │   └── value: Any
│   ├── effects: list[Effect]
│   │   ├── object: str
│   │   ├── field: str
│   │   └── set_to: Any
│   └── temporal_constraints: list[TemporalConstraint]
│       ├── when: dict[str, str]
│       ├── deadline: str
│       └── sla: str
├── rules: dict[str, RuleDef]
│   ├── description: str
│   ├── rule_type: str
│   ├── applies_to: list[str]
│   ├── result_field: str
│   ├── source: str
│   └── conditions: list[RuleCondition]
│       ├── field: str
│       ├── operator: str
│       ├── value: Any
│       └── result: Any
└── workflows: dict[str, WorkflowDef]
    ├── description: str
    ├── trigger: str
    ├── involves_objects: list[str]
    └── steps: list[WorkflowStep]
        ├── name: str
        ├── function: str
        ├── description: str
        ├── next: str | dict[str, str]
        └── sla: str
```
