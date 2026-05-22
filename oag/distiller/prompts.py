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

## 判断标准：什么该成为独立对象

一个概念应该成为独立对象，当且仅当它满足以下条件之一：
1. **有多条实例记录**，且 Agent 需要按条件查询它们（如"查找某区域的桥梁"、"列出某类别的无人机"）
2. **需要与其他对象建立关联**，Agent 推理时需要跨对象关联查询（如"该路段上的桥梁损伤情况"）
3. **是查表才能得到的判断标准**，Agent 需要查询该表来做决策（如"根据损伤等级判断通行建议"）

以下情况**不应**成为独立对象：
- **只在函数执行时内部使用的计算规则**（如公式、算法步骤）→ 放在函数的 hint 中
- **总是作为某个对象的一个字段存在的属性**（如"事件等级"是 EmergencyEvent 的一个字段）
- **法规原文**（法规本身不是数据表，其中的规则要么提炼为独立的标准/规则对象，要么嵌入函数 hint）
- **一次性的动作或流程**（如"合规检查"如果没有历史记录需要查询，就不需要独立建模）

## 已有 OAG domain 的粒度参考

以下是其他领域的 ontology 对象列表，仅供参考**命名风格和粒度感觉**。它们属于不同的业务领域，不要把它们的对象纳入当前领域。

{few_shot_examples}

## 文档摘要

{doc_summaries}

## 文档核心内容

{doc_content}

## 输出格式

请以 JSON 格式输出，包含两个数组：

```json
{{
  "objects": [
    {{
      "name": "PascalCase对象名",
      "summary": "一句话描述（中文，说明这个对象是什么、有什么关键特征）",
      "source": "来源文档名 + 章节号",
      "reasoning": "满足上述哪条判断标准，为什么 Agent 需要独立查询它"
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
2. 查询相关对象（query）
3. 调用函数执行计算/判断/处理
4. 组织回答

每个函数有：
- **summary**：一行概括（出现在 Agent 的 system prompt 中）
- **description**：详细说明（Agent 调用 inspect() 时看到）
- **group**：业务分组
- **params**：输入参数
- **depends_on**：前置依赖函数（自动执行）
- **hint**：执行时的业务规则提示（Phase 5 再详细填充）

函数格式示例（来自 fee domain）：
```yaml
find_path:
  summary: "Dijkstra 搜最小 MTC 费额路径"
  group: "业务流程"
  description: "Dijkstra搜索入口站到出口站的最小MTC费额路径"
  depends_on: [compute_fees]
  params:
    en_station_id: {{type: str, description: "入口站编号"}}
    ex_station_id: {{type: str, description: "出口站编号"}}
    vehicle_type: {{type: int, description: "车型代码"}}
```

## 当前对象模型

{current_schema}

## 当前关系

{current_links}

## 文档内容

{doc_content}

## 任务

从文档中识别可以实现为函数的业务操作/计算/判断流程。

## 函数粒度判断

- 一个函数应该做**一件明确的事**，不要把多个独立操作塞进一个函数
- 如果一个操作通过简单的 query + LLM 推理就能完成，不需要成为函数
- 函数适合：需要多步计算、需要遍历数据、需要执行特定算法、需要写入新数据的操作
- 考虑 Agent 会怎么使用这个函数——参数是否合理？输出是否有用？

## 输出格式

```json
{{
  "functions": [
    {{
      "name": "snake_case函数名",
      "summary": "一行概括（中文）",
      "group": "业务分组名",
      "description": "详细说明（中文）",
      "depends_on": ["前置函数名"],
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
hint 的质量直接决定 Agent 的计算/判断是否正确。

hint 格式规范（参考已有 domain）：
```
R1: 条件 → 规则描述。
R2: 条件 → 规则描述。
注意: 例外情况或特殊说明。
```
- 每条规则以编号开头（R1/R2/...）
- 公式用 `=` 表示
- 单位在括号中标注
- "注意"标记例外情况

## 函数定义

{function_def}

## 涉及的对象类型

{related_objects}

## 相关文档内容

{doc_content}

## 任务

从文档中提取该函数执行时需要遵循的所有业务规则。

## 重要原则

- **只提取文档中明确写的规则**，不要推断或补全
- 公式中的单位、精度要求（如"四舍五入到元"）不能遗漏
- 使用对象属性的**准确名称**（与 ontology 一致）
- 规则要足够具体，让 LLM 能直接按规则执行

## 输出格式

```json
{{
  "hint": "R1: 规则描述。\\nR2: 规则描述。\\n注意: ...",
  "summary_optimized": "优化后的一行 summary（让 LLM 在 system prompt 中一眼理解函数用途）",
  "description_optimized": "优化后的 description（让 LLM 调用 inspect() 后获得完整理解）"
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
