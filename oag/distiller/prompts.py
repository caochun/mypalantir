from __future__ import annotations

from pathlib import Path

import yaml

DOC_SUMMARY_PROMPT = """\
阅读以下文档内容，用一句话概括这份文档的核心内容和用途。
要求：不超过50字，说明文档类型（法规/标准/规程等）、覆盖的主要内容。

文档名: {filename}

---
{content}
---

请直接输出一句话概括，不要加前缀。"""

CONCEPT_DISCOVERY_PROMPT = """\
你是一个领域建模专家，正在为一个 LLM Agent 系统构建领域本体（ontology）。

## 背景

OAG（Ontology Augmented Generation）系统中，ontology 定义了 LLM Agent 的"世界模型"：
- **对象类型（objects）**：在 SQLite 中建表存储结构化数据，Agent 可以通过 `query(对象名, 条件)` 查询
- **函数（functions）**：Agent 可以调用的领域操作，每个函数有参数签名和业务规则提示（hint）
- Agent 的推理流程是：理解问题 → 查询相关对象 → 调用函数计算 → 组织回答

## 任务

从以下业务文档中识别应该建模为**独立对象类型**的核心概念。

## ★ 对象必须分为三类

### A 类：领域实体对象
现实世界中的"东西"——设施、人员、设备、事件等。Agent 通过 `get_xxx` 或 `query` 获取实例数据。
- 例：RoadSegment（路段）、Bridge（桥梁）、Drone（无人机）、DroneOperator（操控员）

### B 类：业务规则/标准对象 ← **最容易被遗漏，请特别注意**
文档中的**分级标准、分类规则、条件→结论映射表、选用规则**。它们不是实体而是"查表才能得到的判断依据"。Agent 通过 `lookup_xxx` 或 `query` 查表获取规则，而不是把规则硬写在函数里。

识别方法——文档中出现以下模式时，应建为 B 类对象：
- 分级/分类表：如"损伤等级分为I/II/III级"→ DamageGradeStandard
- 条件→结论映射：如"道路等级+交通量→隧道重要等级"→ TunnelImportanceLevel
- 选用规则：如"设施类型+灾损类型→抢通技术"→ ClearanceTechniqueRule
- 法规中的条件约束：如"无人机类别→是否需要适航许可/执照/运营合格证"→ DroneClassRule
- 审批规则：如"场景→提前申请时间+审批机构"→ FlightApprovalRule

### C 类：业务过程/产物对象
Agent 在执行业务流程时**写入**的记录——检查记录、方案、调度单、报告等。这些对象串联起完整的业务流程。

识别方法——思考 Agent 需要跟踪哪些"中间产物"：
- 检查/评估记录：如 FacilityInspection（设施检查记录）
- 方案/计划：如 ClearancePlan（抢通方案，含候选/执行/完成状态）
- 调度/分配记录：如 ResourceDispatch（资源调度单）
- 审批/合规记录：如 FlightApproval、ComplianceCheck
- 报告：如 EventReport（灾情报告：首报/续报/终报）

## 不应成为独立对象的情况

- **总是作为某个对象的一个字段**（如"事件等级"是 Event 的属性）→ 归为属性
- **纯计算公式**（如距离评分公式）→ 放在函数 hint 中
- **法规原文逐条**（法规本身不是数据表）→ 从中提炼 B 类规则对象

## 已有 OAG domain 的粒度参考

以下是其他领域的 ontology 对象列表，仅供参考**命名风格和粒度感觉**。它们属于不同的业务领域，不要把它们的对象纳入当前领域。

{few_shot_examples}

## 文档摘要

{doc_summaries}

## 文档核心内容

{doc_content}

## 输出格式

请以 JSON 格式输出，包含两个数组。**每个对象必须标注 category**：

```json
{{
  "objects": [
    {{
      "name": "PascalCase对象名",
      "category": "entity|rule|process",
      "summary": "一句话描述（中文，说明这个对象是什么、有什么关键特征）",
      "source": "来源文档名 + 章节号",
      "reasoning": "属于 A/B/C 哪类，为什么 Agent 需要独立查询它"
    }}
  ],
  "maybe_attributes": [
    {{
      "name": "候选名称",
      "reason": "为什么它可能是属性而非独立对象",
      "suggested_parent": "建议归属的对象名"
    }}
  ]
}}
```

请输出 JSON："""


ATTRIBUTE_ENRICHMENT_PROMPT = """\
你是一个领域建模专家，正在为 OAG（Ontology Augmented Generation）系统丰富对象的属性定义。

## 背景

OAG 中每个对象类型在 SQLite 中建表，属性即列。Agent 通过 `query(对象名, "条件")` 查询数据。
属性定义的质量直接影响 Agent 的查询能力。

## 当前对象模型

{current_schema}

## 任务

阅读以下文档片段，为上述对象发现和补充属性。

对每个发现的属性，给出：
- **属性名**：snake_case，简洁明确
- **类型**：str / int / float / bool 之一
- **required**：是否为业务唯一标识（如 station_id, bridge_id 等主键字段）
- **描述**：含单位、取值范围、枚举值等具体信息，要足够具体让 Agent 能正确使用
- **来源**：文档名 + 章节号/表号

## 重要原则

- 只提取文档中**明确提到**的属性，不要推断或补全
- 优先提取有**具体取值范围或枚举值**的属性（如"损伤等级分为I/II/III级"）
- 属性描述中应包含枚举值的含义（如"1=在用, 2=停用"）
- 如果文档中发现了新的对象类型（Phase 1 遗漏的），也可以提出

## 文档内容

{doc_content}

## 输出格式

```json
{{
  "updates": [
    {{
      "object": "已有对象名",
      "new_properties": [
        {{
          "name": "snake_case属性名",
          "type": "str|int|float|bool",
          "required": false,
          "description": "属性描述（中文，含枚举值/单位/范围）",
          "source": "文档名 + 章节号"
        }}
      ]
    }}
  ],
  "new_objects": [
    {{
      "name": "PascalCase对象名",
      "summary": "一句话描述",
      "source": "来源",
      "properties": [
        {{
          "name": "属性名",
          "type": "str",
          "required": false,
          "description": "描述"
        }}
      ]
    }}
  ]
}}
```

请输出 JSON："""


SCHEMA_CONSOLIDATION_PROMPT = """\
你是一个领域建模专家，正在审查一个 OAG ontology schema 的质量。

## 背景

OAG（Ontology Augmented Generation）系统中，每个对象类型在 SQLite 中建表存储。Agent 通过 query() 查表获取信息。
这个 schema 是通过逐份文档迭代生成的，可能存在少量冗余。你的任务是做**最小化清理**，只处理明显的重复。

## 判断标准——什么应该合并/删除

**应该合并的情况**（仅限以下几种）：
- 两个对象**名称不同但描述完全相同的概念**，如 FlightPlanApproval 和 FlightApproval 描述的是同一件事
- 一个对象是另一个对象的**枚举值**而非独立概念，如 AgriculturalDrone 只是 Drone 的一种 class_name 值

**绝对不应该合并/删除的情况**：

1. **规则/标准类对象**：如 DamageGradeStandard（损伤分级标准）、TrafficControlRule（管制规则）、ClearanceTechniqueRule（抢通技术选用）。
   这些是**查询表**，Agent 需要 query() 来查规则，即使其属性看起来像另一个对象的字段。
   - 反例：DamageGradeStandard 有 damage_grade 属性，Bridge 也有 damage_grade 属性 → 不应合并！前者是"分级标准表"，后者是"当前状态值"。

2. **流程记录类对象**：如 FlightLog（飞行日志）、MaintenanceRecord（维护记录）、EventReport（灾情报告）。
   即使其属性与父实体有交集，它们代表独立的业务事件，需要独立存储和查询。
   - 反例：FlightLog 有 flight_duration，FlightPlan 也有 planned_duration → 不应合并！一个是计划，一个是实际记录。

3. **独立实体对象**：如 DroneOperator、AirspaceZone、WeatherWarning。
   即使它们被其他对象引用，只要有独立的查询场景（"查所有操控员"、"查某区域空域"），就应保留。
   - 反例：DroneOperator 的 license_info 在 FlightPlan 中也有引用 → 不应合并！操控员是独立可查询的实体。

4. **证书/资质类对象**：如 AirworthinessCertificate、OperationCertificate、TypeCertificate。
   证书有独立的生命周期（颁发、过期、吊销），不应降级为实体属性。

## 示例

假设 schema 中有：

```
### EmergencyEquipmentCategory
  summary: 装备分类标准
  - category_name: str — 分类名称
  - weight_class: str — 重量等级

### EquipmentStock
  summary: 装备库存
  - equipment_name: str — 装备名称
  - quantity: int — 数量
  - weight_class: str — 重量等级
```

✅ 应该合并：EmergencyEquipmentCategory → EquipmentStock（分类信息可以作为库存的属性，没有独立查询场景）

再假设：

```
### DamageGradeStandard
  summary: 损伤分级标准(设施类型+等级→通行建议)
  - facility_type: str — 设施类型(road/bridge/tunnel)
  - grade: str — 损伤等级(1-5)
  - description: str — 等级描述
  - traffic_advice: str — 通行建议

### Bridge
  summary: 桥梁
  - damage_grade: str — 当前损伤等级
```

❌ 不应合并：DamageGradeStandard 是独立查询表（query("DamageGradeStandard", facility_type="bridge", grade="3")），Bridge.damage_grade 只是引用它的结果。

再假设：

```
### FlightLog
  summary: 飞行日志记录
  - drone_id: str — 无人机ID
  - flight_duration: float — 实际飞行时长
  - takeoff_time: str — 起飞时间

### FlightPlan
  summary: 飞行计划
  - drone_id: str — 无人机ID
  - planned_duration: float — 计划飞行时长
```

❌ 不应合并：FlightLog 是事后记录，FlightPlan 是事前计划，虽然有相同字段但代表不同阶段的业务数据。

## 当前 schema

{current_schema}

## 任务

审查上述 schema，仅输出**必要的**合并/删除建议。宁可保留可疑对象，不可误删有独立查询价值的对象。

如果不确定某对象是否应删除，**保留它**。

## 输出格式

```json
{{
  "actions": [
    {{
      "type": "merge",
      "source": "被合并的对象名",
      "target": "合并到的目标对象名",
      "reason": "合并理由"
    }},
    {{
      "type": "remove",
      "object": "要删除的对象名",
      "reason": "删除理由（如应降级为属性）"
    }},
    {{
      "type": "remove_property",
      "object": "对象名",
      "property": "要删除的重复属性名",
      "reason": "与哪个属性重复"
    }}
  ]
}}
```

只输出确定需要修改的部分。如果 schema 质量良好无需修改，输出空 actions 数组。
请输出 JSON："""


RELATIONSHIP_DISCOVERY_PROMPT = """\
你是一个领域建模专家，正在为 OAG（Ontology Augmented Generation）系统发现对象间的关联关系。

## 背景

OAG 中的关系（links）定义了对象间的关联方式。Agent 通过 `query_links(源对象名, 关系名, 条件)` 做跨对象查询。
每个关系必须通过**具体的字段**连接两个对象，不是抽象的"相关"。

关系格式示例（来自 fee domain）：
```yaml
unit_has_rate_params:
  source: TollUnit
  target: ProvinceRateParam
  join: {{source_key: toll_interval_id, target_key: toll_interval_id}}
  description: 收费单元的计费参数
```

## 当前对象模型

{current_schema}

## 文档内容

{doc_content}

## 任务

从文档和对象模型中识别对象间的关联关系。每个关系给出：
- **关系名**：snake_case，格式为 `源对象_has/belongs_to/contains_目标对象`
- **源对象和目标对象**：必须是上述对象模型中已有的对象名
- **join key**：源对象和目标对象通过哪个字段关联。字段必须在对应对象的属性中已存在（或明确应该存在）
- **描述**：用自然语言先描述关系（如"收费单元属于某条收费公路"），再给出技术定义

## 应该考虑的关系类型

- **归属关系**：A 属于 B（如桥梁属于某路段、装备属于某储备点）
- **引用/查表关系**：A 的某个字段引用 B 的记录（如检查结果引用损伤等级标准）
- **触发/产出关系**：A 触发 B（如灾害事件触发应急响应、检查产出抢通方案）
- **执行关系**：A 执行 B（如队伍执行调度任务、操控员执行飞行任务）
- **空间关联**：A 和 B 在同一位置（如路段上有桥梁和隧道）

请系统地检查每对有潜在关联的对象，尽可能全面地发现关系。

## 重要原则

- 关系必须通过具体字段连接，不能是抽象的"相关"
- 如果 join key 需要的属性在对象中尚不存在，在 missing_properties 中列出需要补充的属性
- 不要创造文档中没有依据的关系

## 输出格式

```json
{{
  "links": [
    {{
      "name": "snake_case关系名",
      "source": "源对象名",
      "target": "目标对象名",
      "source_key": "源对象的关联字段",
      "target_key": "目标对象的关联字段",
      "description": "关系描述",
      "source_doc": "来源文档 + 章节号"
    }}
  ],
  "missing_properties": [
    {{
      "object": "对象名",
      "property": "需要补充的属性名",
      "type": "str|int|float|bool",
      "description": "属性描述",
      "reason": "为什么需要这个属性（为哪个关系服务）"
    }}
  ]
}}
```

请输出 JSON："""


FUNCTION_DISCOVERY_PROMPT = """\
你是一个领域建模专家，正在为 OAG（Ontology Augmented Generation）系统发现领域函数。

## 背景

OAG 中的函数（functions）是 LLM Agent 可以调用的领域操作。Agent 的推理流程：
1. 理解用户问题
2. 查询相关对象（query）或调用 lookup 函数查规则
3. 调用业务编排函数执行计算/判断/处理
4. 组织回答

每个函数有：
- **summary**：一行概括（出现在 Agent 的 system prompt 中）
- **description**：详细说明，包括输入、输出和副作用（Agent 调用 inspect() 时看到）
- **group**：业务分组
- **params**：输入参数
- **depends_on**：前置依赖函数
- **hint**：执行时的业务规则提示（Phase 5 再详细填充）
- **writes_to**：该函数会写入哪些对象类型（副作用）

## ★ 函数必须分为三类

### 1. 接口查询函数（get_xxx）
查询领域实体（A类对象）的详情或空间搜索。一个实体对象至少对应一个 get 函数。
- 例：`get_bridge_status(bridge_id)` → 查桥梁信息
- 例：`get_drones_in_range(lng, lat, radius_km)` → 空间搜索无人机

### 2. 规则查询函数（lookup_xxx）← **必须为每个 B 类规则对象生成**
查询规则/标准对象（B类对象）。每个 B 类对象至少对应一个 lookup 函数。规则应该存在对象中通过 lookup 查表，**不要把规则硬写在业务函数的 hint 里**。
- 例：`lookup_damage_grade(facility_type, damage_grade)` → 查损伤分级标准
- 例：`lookup_clearance_technique(facility_type, damage_type)` → 查抢通技术选用
- 例：`lookup_drone_class(category)` → 查无人机分类标准

### 3. 业务编排函数
串联业务流程的操作——检查评估、方案生成、资源调度、报告生成等。这类函数有明确的**输入→处理→输出（写入 C 类对象）**。hint 应引用 lookup 函数获取规则，而不是把规则硬编码。
- 例：`inspect_facility(event_id, facility_id)` → 检查设施损伤，写入 FacilityInspection
- 例：`generate_clearance_plans(event_id)` → 根据检查记录+抢通技术规则，生成候选方案

## 当前对象模型

{current_schema}

## 当前关系

{current_links}

## 文档内容

{doc_content}

## 任务

从文档和对象模型中发现函数。特别注意：
1. 为每个 category=rule 的对象生成对应的 `lookup_xxx` 函数
2. 思考业务流程中 Agent 需要执行哪些**有副作用**的操作（写入检查记录、生成方案、调度资源等）
3. 设计函数时考虑**调用链**——哪些函数必须在其他函数之后执行（用 depends_on 表达）

## 输出格式

```json
{{
  "functions": [
    {{
      "name": "snake_case函数名",
      "function_type": "get|lookup|business",
      "summary": "一行概括（中文）",
      "group": "业务分组名",
      "description": "详细说明（中文），包括输入来源、输出去向和副作用",
      "depends_on": ["前置函数名"],
      "writes_to": ["该函数写入的 C 类对象名"],
      "params": [
        {{
          "name": "参数名",
          "type": "str|int|float|bool",
          "description": "参数描述",
          "default": null
        }}
      ],
      "involves_objects": ["涉及的对象类型名"],
      "source": "来源文档 + 章节号"
    }}
  ]
}}
```

请输出 JSON："""


RULE_EXTRACTION_PROMPT = """\
你是一个领域建模专家，正在为 OAG 系统中的函数提取详细的业务规则。

## 背景

OAG Agent 调用函数时会看到函数的 hint 字段，其中包含执行该函数需要遵循的业务规则。

### ★ hint 的写法取决于函数类型

**lookup 函数**（查规则表的函数）：hint 应说明查表逻辑和返回字段的含义。具体的规则数据存储在对应的规则对象中，不需要在 hint 里重复罗列。
```
根据 facility_type 和 damage_grade 查询 DamageGradeStandard 表。
返回: damage_degree(损伤程度)、description(损伤描述)、access_decision(通行建议)。
```

**业务编排函数**（有副作用的函数）：hint 应说明处理流程和判断逻辑。如果需要查表，应引用 lookup 函数，而不是把表中的规则硬写在 hint 里。
```
R1: 调用 lookup_damage_grade 获取各部位损伤等级。
R2: 路段整体等级 = max(路基路面, 路基防护, 路基支挡) 三项取最大。
R3: 损伤等级I→观察通行，II→限制通行，III→禁止通行。
副作用: 写入 FacilityInspection 记录。
```

**get 函数**（查实体的函数）：hint 通常为空或简短说明返回字段。

## 函数定义

{function_def}

## 涉及的对象类型

{related_objects}

## 相关文档内容

{doc_content}

## 任务

从文档中提取该函数执行时需要遵循的业务规则。

## 重要原则

- **只提取文档中明确写的规则**，不要推断或补全
- **不要把应存在规则对象中的数据写进 hint**。如果某个规则有多条分支（如 15 个不同等级的判定），它应该存在规则对象中通过 lookup 查询，hint 只写"调用 lookup_xxx 获取"
- hint 应该简洁、引导式，不是把整本法规塞进去
- 使用对象属性的**准确名称**（与 ontology 一致）
- 公式中的单位、精度要求不能遗漏

## 输出格式

```json
{{
  "hint": "R1: 规则描述。\\nR2: 规则描述。\\n注意: ...",
  "summary_optimized": "优化后的一行 summary（让 LLM 在 system prompt 中一眼理解函数用途）",
  "description_optimized": "优化后的 description（含输入来源、输出去向、副作用）"
}}
```

请输出 JSON："""


KEYWORD_GENERATION_PROMPT = """\
以下对象在领域文档中目前没有找到属性。请为每个对象生成 5-8 个搜索关键词，用于在文档中定位与该对象相关的段落。

关键词要求：
- 包含中文同义词、近义词、上下位词
- 包含文档中可能使用的术语（如法规用语、标准用语）
- 不要只用对象名本身，要想到文档作者会怎么描述这个概念

对象列表：
{objects_info}

输出 JSON 格式：
```json
{{
  "keywords": {{
    "对象名": ["关键词1", "关键词2", ...]
  }}
}}
```

请输出 JSON："""


def load_few_shot_objects(domains_dir: str | Path) -> str:
    domains_dir = Path(domains_dir)
    lines = []
    for domain_name in ("fee", "road_emergency"):
        ontology_path = domains_dir / domain_name / "ontology.yaml"
        if not ontology_path.exists():
            continue
        with open(ontology_path) as f:
            data = yaml.safe_load(f)
        objects = data.get("objects", {})
        lines.append(f"### {domain_name} domain ({len(objects)} 个对象)")
        for name, obj in objects.items():
            summary = obj.get("summary", obj.get("description", ""))
            lines.append(f"- **{name}**: {summary}")
        lines.append("")
    return "\n".join(lines)


DISCOURSE_DOC_PROMPT = """\
你是一个文档结构分析专家。分析以下文档的整体论述结构。

文档名: {filename}
摘要: {summary}

章节列表:
{chapter_list}

请判断:
1. **文档类型** (doc_type): regulation(法规条例) / standard(技术标准) / procedure(操作规程) / guideline(指南/预案)
2. **核心主题** (core_topics): 3-5个关键主题词，概括文档涉及的核心业务领域
3. **章节角色** (chapter_roles): 每个章节的论述功能

章节角色可选值:
- background: 总则、目的、范围、编制依据等背景性内容
- definition: 术语定义、分类标准、概念界定
- rule: 规则、条件、约束、禁止/允许事项
- procedure: 操作步骤、流程、响应程序
- enumeration: 列举、分类表、参数表
- organization: 组织架构、职责分工

输出 JSON:
```json
{{"doc_type": "...", "core_topics": ["...", "..."], "chapter_roles": [{{"section": "章节名", "role": "..."}}]}}
```

请输出 JSON："""


DISCOURSE_CHUNK_PROMPT = """\
你是一个语篇分析专家。为以下 {count} 个文本片段标注语篇类型。

可选类型:
- definition: 定义术语、分类标准、概念界定（如"XX是指..."、分类表）
- rule: 规则、条件约束、禁止/允许事项（如"应当..."、"不得..."、条件→结果）
- procedure: 操作步骤、流程描述（如"第一步..."、响应流程）
- example: 示例、案例、附录数据
- background: 背景、目的、范围、一般性描述
- enumeration: 列举项目、参数表、分级表

{chunks_text}

对每个片段输出 discourse_type 和一句话 topic（不超过10字）。

输出 JSON:
```json
{{"chunks": [{{"index": 0, "discourse_type": "...", "topic": "..."}}]}}
```

请输出 JSON："""
