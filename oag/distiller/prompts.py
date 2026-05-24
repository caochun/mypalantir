from __future__ import annotations

from pathlib import Path

import yaml

# ============================================================
# Phase 0: Document Preparation (unchanged)
# ============================================================

DOC_SUMMARY_PROMPT = """\
阅读以下文档内容，用一句话概括这份文档的核心内容和用途。
要求：不超过50字，说明文档类型（法规/标准/规程等）、覆盖的主要内容。

文档名: {filename}

---
{content}
---

请直接输出一句话概括，不要加前缀。"""


DISCOURSE_DOC_PROMPT = """\
你是一个文档结构分析专家。分析以下文档的整体论述结构。

文档名: {filename}
摘要: {summary}

章节列表:
{chapter_list}

请判断:
1. **文档类型** (doc_type): regulation(法规条例) / standard(技术标准) / procedure(操作规程) / guideline(指南/预案)
2. **核心主题** (core_topics): {core_topic_count}个关键主题词，概括文档涉及的核心业务领域
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

★ 技术标准/规范类文档的特殊标注规则：
- 含有分级表、损伤等级、分类标准的内容 → definition 或 enumeration，不是 background
- 含有"应"、"宜"、"不得"等规范性用语的技术要求 → rule，不是 background
- 含有操作步骤、检查方法、施工工艺的内容 → procedure，不是 background
- 只有纯粹的"总则/范围/引用标准"才标 background

{chunks_text}

对每个片段输出 discourse_type 和一句话 topic（不超过10字）。

输出 JSON:
```json
{{"chunks": [{{"index": 0, "discourse_type": "...", "topic": "..."}}]}}
```

请输出 JSON："""


# ============================================================
# Phase 1: Domain & Workflow Analysis (NEW)
# ============================================================

WORKFLOW_ANALYSIS_PROMPT = """\
你是一个领域建模专家。你正在分析业务文档，为一个 LLM Agent 系统（OAG）设计领域模型。

## OAG 系统简介

OAG Agent 通过以下方式工作：
1. 理解用户问题
2. 查询**实体数据**（如路段、桥梁、设备库存）
3. 查**规则表**获取判断依据（如损伤分级标准、抢通技术选用规则）
4. 执行**业务操作**并写入记录（如检查记录、方案记录、调度记录）
5. 组织回答

关键：Agent 的能力完全取决于 ontology 中定义了哪些对象和函数。你现在的任务是分析业务流程，为后续 ontology 设计打基础。

## 任务

分析以下业务文档，回答三个问题：

### 1. 这个领域有哪些业务工作流？

每个工作流是一条完整的业务链路（从触发到结束）。描述：
- 触发条件
- 步骤序列：每一步做什么、查什么、产出什么
- 关键决策点：在哪一步需要查规则表做判断

### 2. 文档中有哪些"分级标准/条件映射/选用规则"？

这些是 Agent 需要查表才能获得的判断依据，不能硬编码在函数里。

### 3. Agent 需要查询哪些实体数据？

这些是外部系统提供的数据，Agent 通过查询获得。

## 已有 OAG domain 的工作流参考

{few_shot_workflow}

## 文档摘要

{doc_summaries}

## 文档内容

{doc_content}

## 输出格式

```json
{{
  "domain_scope": "一句话描述领域范围",
  "workflows": [
    {{
      "name": "工作流名称",
      "trigger": "触发条件",
      "steps": [
        {{
          "name": "步骤名称",
          "action": "做什么（一句话）",
          "queries_entities": ["需要查询的实体名称（中文）"],
          "consults_rules": ["需要查的规则/标准名称（中文）"],
          "produces_record": "产出什么记录（中文，若无则null）",
          "decision": "决策描述（若有）",
          "source": "章节号"
        }}
      ]
    }}
  ],
  "rule_tables": [
    {{
      "name": "规则/标准名称（中文）",
      "pattern": "条件→结论 的模式描述",
      "source": "章节号/表号",
      "dimensions": ["输入维度1", "输入维度2"],
      "result": "输出结果字段"
    }}
  ],
  "entities": [
    {{
      "name": "实体名称（中文）",
      "description": "一句话说明",
      "source": "章节号"
    }}
  ]
}}
```

请输出 JSON："""


# ============================================================
# Phase 2: Concept Discovery (workflow-driven)
# ============================================================

CONCEPT_DISCOVERY_PROMPT = """\
你是一个领域建模专家，正在为 OAG（Ontology Augmented Generation）Agent 系统设计领域本体。

## OAG 对象类型系统

OAG 中的对象类型分为严格的三类：

### A 类：领域实体对象
现实世界中客观存在的"东西"——基础设施、人员、设备、物资等。
- 特征：有固定的内在属性（名称、位置、结构、类型），不随业务事件改变
- Agent 通过 `get_xxx(id)` 或空间搜索查询
- ★ 不包含动态状态属性（如损伤等级、当前管制措施——这些属于 C 类检查/评估记录）

### B 类：业务规则/标准对象（查表对象）
文档中的分级标准、分类规则、条件→结论映射表、选用规则。
- 特征：是"查表才能得到的判断依据"，存储为 SQLite 表，Agent 通过 `lookup_xxx()` 查询
- 识别模式：分级表、矩阵表、条件→结论映射、选用规则
- ★ 规则应该存在 B 类对象中通过查表获取，不能硬写在函数 hint 里

### C 类：业务过程/记录对象
Agent 执行业务操作时**写入**的记录。串联起完整的业务流程。
- 特征：由 Agent 创建，有状态流转（如 candidate→executing→completed）
- 通过 event_id/plan_id 等 ID 串联成业务链
- ★ 每个主要业务步骤应该有对应的过程记录

## 业务工作流分析结果

以下是从文档中分析出的业务流程（Phase 1 产出）：

{workflow_analysis}

## 任务

根据上述工作流分析 + 以下文档内容，推导出完整的对象列表。

### 推导规则：
1. 工作流中每个 `queries_entities` → 至少一个 A 类对象
2. 工作流中每个 `consults_rules` + `rule_tables` 中每条 → 至少一个 B 类对象
3. 工作流中每个 `produces_record` → 至少一个 C 类对象
4. 从文档中检查是否有遗漏的 B 类规则（分级表、矩阵、选用规则等）

### 不应成为独立对象的情况：
- 总是作为某对象的一个字段 → 归为属性
- 纯计算公式 → 放在函数 hint 中
- 装备/物资的分类体系 → 作为 EquipmentStock/MaterialStock 的属性
- 通信设备、车辆等支撑工具 → 除非有独立查询场景，否则不需要独立对象

## 已有 OAG domain 的粒度参考

{few_shot_objects}

## 文档摘要

{doc_summaries}

## 文档核心内容

{doc_content}

## 输出格式

```json
{{
  "objects": [
    {{
      "name": "PascalCase对象名",
      "category": "entity|rule|process",
      "summary": "一句话描述（简洁、操作导向，如'路段(公路基本单元，按桩号搜)'）",
      "source": "来源文档名 + 章节号",
      "reasoning": "属于 A/B/C 哪类，对应工作流中的哪个环节",
      "workflow_role": "在工作流中的角色：queries/consults/produces 对应的步骤名"
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


# ============================================================
# Phase 3: Attribute Enrichment
# ============================================================

ATTRIBUTE_ENRICHMENT_PROMPT = """\
你是一个领域建模专家，正在为 OAG Agent 系统丰富对象的属性定义。

## 背景

OAG 中每个对象类型在 SQLite 中建表，属性即列。Agent 通过 `query(对象名, "条件")` 查询数据。

## ★ 属性分配铁律

**A类实体对象：只放内在/静态属性**
- ✓ 放：id, name, type, structure_type, location, lng, lat, length, width, height
- ✗ 不放：damage_grade, current_status, traffic_control_measure
- 理由：损伤等级和管制措施是业务事件的结果，属于 C 类检查/评估记录，不是实体本身的固有属性

**B类规则对象：放查询维度 + 结果值**
- ✓ 放：facility_type, damage_grade（查询键，required=true）+ damage_degree, access_decision（结果值）
- 理由：这是一张查表，输入维度 → 输出结果

**C类过程对象：放 event_id + 步骤特有字段 + status**
- ✓ 放：event_id（关联事件）, facility_id（关联设施）, damage_summary, overall_damage_grade, status
- 理由：过程记录跟踪业务状态

## 当前对象模型

{current_schema}

## 任务

阅读以下文档片段，为上述对象发现和补充属性。

对每个发现的属性，给出：
- **属性名**：snake_case，简洁明确
- **类型**：str / int / float / bool 之一
- **required**：是否为查询主键（如 station_id, bridge_id, rule_id）
- **描述**：含单位、取值范围、枚举值等具体信息
- **来源**：文档名 + 章节号

## 重要原则

- 只提取文档中**明确提到**的属性，不要推断
- 优先提取有具体取值范围或枚举值的属性
- ★ 检查属性是否放对了类型（静态属性不要放在动态对象上，反之亦然）

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
      "category": "entity|rule|process",
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

## 当前 schema

{current_schema}

## 任务

审查上述 schema，找出需要合并或删除的冗余对象。

## 判断标准

**应该合并**（仅限以下情况）：
- 两个对象描述完全相同的概念（不同名字）
- 一个对象是另一个对象的枚举值，而非独立概念

**绝对不合并**：
- B类规则/标准对象（即使属性名与其他对象相同）
- C类过程记录对象（即使与其他对象有字段交集）
- 有独立查询场景的实体对象

如果不确定 → 保留。

## 输出格式

```json
{{
  "actions": [
    {{
      "type": "merge|remove|remove_property",
      "source": "被合并/删除的对象名",
      "target": "合并目标（merge时）",
      "object": "对象名（remove/remove_property时）",
      "property": "属性名（remove_property时）",
      "reason": "理由"
    }}
  ]
}}
```

只输出确定需要修改的部分。如果无需修改，输出空 actions 数组。
请输出 JSON："""


KEYWORD_GENERATION_PROMPT = """\
以下对象在领域文档中目前没有找到属性。请为每个对象生成 5-8 个搜索关键词，用于在文档中定位与该对象相关的段落。

关键词要求：
- 包含中文同义词、近义词、上下位词
- 包含文档中可能使用的术语
- 不要只用对象名本身

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


# ============================================================
# Phase 4: Relationship Discovery (workflow-driven)
# ============================================================

RELATIONSHIP_DISCOVERY_PROMPT = """\
你是一个领域建模专家，正在为 OAG Agent 系统发现对象间的关联关系。

## 背景

OAG 中的关系（links）定义了对象间的关联。Agent 通过 `query_links(源对象名, 关系名, 条件)` 做跨对象查询。

## ★ 关系设计原则：工作流驱动

关系的设计应该**以业务流程为核心**，而不是看哪些字段名相同。

### 1. 工作流关系（最重要）
事件 → 检查记录、事件 → 方案、方案 → 调度单——这些是业务流程中的因果关系。
- 通常通过 event_id, plan_id 等流程 ID 连接
- 方向：从触发者到被触发的记录

### 2. 实体归属关系
储备点 → 装备库存、路段 → 桥梁——这些是实体间的包含/归属关系。
- 通过实体 ID（如 depot_id, segment_id）连接

### 3. 规则引用关系（谨慎）
只在确实有查表场景时才建立。不要因为两个对象有同名字段就建关系。

## 关系格式

```yaml
关系名:
  source: 源对象
  target: 目标对象
  join: {{source_key: 源字段, target_key: 目标字段}}
  description: 关系描述
```

## 已有的工作流分析

{workflow_analysis}

## 当前对象模型

{current_schema}

{few_shot_links}

## 文档内容

{doc_content}

## 任务

1. **先从工作流推导关系**：事件→检查、事件→方案、方案→调度、事件→管制、事件→报告等
2. **再从文档发现实体关系**：归属、包含等
3. 如果 join key 需要的属性不存在，在 missing_properties 中列出

## 输出格式

```json
{{
  "links": [
    {{
      "name": "snake_case关系名",
      "source": "源对象名",
      "target": "目标对象名",
      "source_key": "源字段",
      "target_key": "目标字段",
      "description": "关系描述",
      "link_type": "workflow|ownership|reference",
      "source_doc": "来源"
    }}
  ],
  "missing_properties": [
    {{
      "object": "对象名",
      "property": "属性名",
      "type": "str",
      "description": "属性描述",
      "reason": "为哪个关系服务"
    }}
  ]
}}
```

请输出 JSON："""


# ============================================================
# Phase 5: Function Design (workflow-driven)
# ============================================================

FUNCTION_DESIGN_PROMPT = """\
你是一个领域建模专家，正在为 OAG Agent 系统设计领域函数。

## OAG 函数体系

OAG 中的函数分为三层：

### 第一层：业务编排函数 ← 最重要
对应业务工作流中的每个**主要步骤**。这些函数有副作用——会写入 C 类过程记录。

设计原则：
- 每个工作流步骤 → 一个业务函数
- 函数的 `depends_on` 反映工作流的先后顺序
- 函数的 `writes_to` 标注写入哪个 C 类对象
- hint 引用 lookup 函数获取规则，不硬编码规则

### 第二层：规则查询函数（lookup_xxx）
每个 B 类规则对象至少对应一个 lookup 函数。业务函数通过调用 lookup 获取规则。

### 第三层：数据查询函数（get_xxx）
每个 A 类实体对象至少对应一个 get 函数。

## 业务工作流分析

{workflow_analysis}

## 当前对象模型

{current_schema}

## 当前关系

{current_links}

{few_shot_functions}

## 文档内容

{doc_content}

## 任务

### Step 1: 为每个工作流步骤设计业务编排函数

参考工作流分析中的 steps，为每个主要步骤设计一个函数。注意：
- summary 要简洁，说明做什么和写入什么
- depends_on 反映前置步骤
- writes_to 标注写入的 C 类对象
- involves_objects 列出涉及的所有对象（查询的 + 写入的 + 规则的）

### Step 2: 为每个 B 类规则对象生成 lookup 函数

用 B 类对象的 required 属性作为查询参数。

### Step 3: 为每个 A 类实体对象生成 get 函数

用实体的主键作为查询参数。

## 输出格式

```json
{{
  "functions": [
    {{
      "name": "snake_case函数名",
      "function_type": "business|lookup|get",
      "summary": "一行概括（简洁、操作导向）",
      "group": "业务分组名",
      "description": "详细说明：输入来源 → 处理逻辑 → 输出去向（写入哪个对象）",
      "depends_on": ["前置函数名"],
      "writes_to": ["写入的 C 类对象名"],
      "params": [
        {{
          "name": "参数名",
          "type": "str|int|float|bool",
          "description": "参数描述",
          "default": null
        }}
      ],
      "involves_objects": ["涉及的对象名"],
      "source": "来源文档 + 章节号"
    }}
  ]
}}
```

请输出 JSON："""


# ============================================================
# Phase 6: Rule Extraction & Hint Writing
# ============================================================

RULE_EXTRACTION_PROMPT = """\
你是一个领域建模专家，正在为 OAG Agent 函数编写执行指引（hint）。

## Hint 的作用

Agent 首次调用函数时看到 hint，据此理解执行逻辑。好的 hint 让 Agent 知道该怎么做，但不把整本法规塞进去。

## ★ Hint 写法因函数类型而异

### 业务编排函数（最重要）

hint 应说明：
1. 调用哪些 lookup 函数获取规则
2. 关键决策逻辑（如"三项取最大等级"、"任何一项III级则整体III级"）
3. 副作用：写入哪个对象

示例：
```
根据设施类型采用不同检查标准(规范6.2/7.2/8.2):
路段: 路基本体+边坡+支挡结构三项取最大等级(6.2.5)
桥梁: 整体稳定性+承载能力+通行能力三项取最大等级(7.2.5)
损伤等级I→正常通行，II→限制通行，III→禁止通行
任何一项评定为III级者，整体为III级禁止通行(7.2.5条1)
```

```
R1: 调用 lookup_clearance_technique 获取可用技术。
R2: 根据 FacilityInspection 的损伤等级和类型选择最适技术。
R3: 评分维度：时效性40% + 安全性30% + 经济性30%。
副作用: 写入 ClearancePlan 记录(status=candidate)。
```

### lookup 函数

hint 说明查询逻辑和返回字段含义。不要罗列规则数据（那些存在 B 类对象里）。

示例：
```
根据 facility_type 和 damage_grade 查询 DamageGradeStandard 表。
返回: damage_degree(损伤程度)、description(损伤描述)、access_decision(通行建议)。
```

### get 函数

hint 通常为空或简短说明返回字段。

## 函数定义

{function_def}

## 涉及的对象类型

{related_objects}

## 相关文档内容

{doc_content}

## 任务

为该函数提取执行指引（hint），并优化 summary 和 description。

## 重要原则

- **只提取文档中明确写的规则**，不要推断
- **规则数据不写进 hint**——如果有 15 个分级条目，应该存在 B 类对象中通过 lookup 查询
- hint 要引导式：告诉 Agent 调用什么、判断什么、写入什么
- 使用属性的**准确名称**
- 公式的单位、精度不能遗漏

## 输出格式

```json
{{
  "hint": "R1: 规则描述。\\nR2: 规则描述。\\n副作用: ...",
  "summary_optimized": "优化后的 summary（极简、操作导向，如'对设施进行检查评估'）",
  "description_optimized": "优化后的 description（含输入来源、输出去向、副作用，不要重复 summary）"
}}
```

请输出 JSON："""


# ============================================================
# Phase 7: Assembly & Optimization
# ============================================================

SUMMARY_OPTIMIZATION_PROMPT = """\
你是一个 LLM prompt 优化专家。以下是一个 OAG 领域本体中的对象和函数列表。

OAG Agent 的 system prompt 中只展示 summary 字段。Agent 需要在一行内理解每个对象/函数的核心作用，决定是否需要进一步 inspect()。

## 当前 summary 列表

{items}

## 任务

为每个 item 重写 summary 和 description：

### summary 要求（极简、操作导向）：
- 好：`路段(公路基本单元，按桩号搜)`
- 好：`损伤分级标准(设施类型+等级→通行建议)`
- 好：`对设施进行检查评估`
- 差：`公路路段实体，包含桩号、等级、坐标等基础信息，是灾情定位和抢通作业的基本单元。`
- 差：`路基路面受损程度分级标准，根据损毁特征映射到 I/II/III 级，并给出通行建议（正常/限制/禁止）。`

### description 要求（与 summary 不同）：
- 对象 description：说明数据来源和查询方式（如"外部接口数据，请用 get_xxx 查询"）
- 函数 description：说明输入来源→处理→输出去向，不重复 summary

## 风格参考

{few_shot_summaries}

## 输出格式

```json
{{
  "optimized": [
    {{
      "name": "对象或函数名",
      "summary": "优化后的 summary",
      "description": "优化后的 description（与 summary 不同）"
    }}
  ]
}}
```

请输出 JSON："""
