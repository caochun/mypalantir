# OAG Domain Distiller: 从业务文档到可运行领域模型

## 1. 问题定义

OAG 的每个 domain 需要一份 `ontology.yaml`（对象类型、属性、关系、函数签名与业务规则）、配套的 Python 函数实现、以及数据映射。当前这一过程完全依赖人工：阅读规范文档 → 手工设计 ontology → 编写函数 → 调试验证。hv_access 和 road_emergency 两个领域的开发经验表明，这个过程耗时且高度依赖建模者对领域和 OAG 框架的双重理解。

**Domain Distiller 的目标**：给定一组领域业务文档（法规、技术标准、规范等），通过 LLM 驱动的多阶段 pipeline + 人机协作，半自动地生成可运行的 OAG domain。

## 2. 核心认识

### 2.1 OAG ontology 不是数据 schema

传统的 schema 发现工具（如 Schema-Miner）关心的是"这个领域有哪些数据字段"。OAG ontology 的本质是 **LLM 的世界模型** —— 它要回答的不只是"有什么"，还有"怎么关联"和"能做什么"。

| 层次 | 内容 | 消费者 |
|------|------|--------|
| 概念层 | 对象类型、属性 | LLM system prompt + SQLite |
| 关系层 | 对象间关联 | LLM 跨实体推理 + query_links |
| 操作层 | 函数签名、参数、依赖链 | LLM tool-calling 规划 |
| 规则层 | 函数 hint 中的业务规则 | LLM 执行决策 + 结果解读 |

这四层的抽取难度递增，所需方法各异，不能用同一个 prompt 一次性提取。

### 2.2 验证标准与传统不同

Schema-Miner 用 BLEU/BERTScore 衡量不同 LLM 输出的 schema 一致性。OAG 有更直接的验证方式：**把生成的 ontology 交给 OAG Agent，让它回答领域问题**。Agent 的推理质量就是 ontology 质量的最终度量。

这形成了独特的闭环：LLM_A 从文档生成世界模型 → LLM_B 用这个世界模型推理 → 推理失败暴露模型缺陷 → 回去修正。

### 2.3 可借鉴的已有工作

| 项目 | 借鉴点 | 局限 |
|------|--------|------|
| [Schema-Miner](https://github.com/sciknoworg/schema-miner) (ESWC 2025) | 三阶段迭代精炼；每次只消化一份文档；人机协作架构 | 只做属性发现，不涉及关系和函数 |
| [NOMAD](https://arxiv.org/abs/2511.22409) (Manchester 2025) | 多 Agent 分工协作；任务分解降低复杂度 | 面向 UML 类图，不覆盖业务规则 |
| [Automating DDD](https://arxiv.org/pdf/2603.26244) (2026) | LLM 辅助提取限界上下文、术语表 | 误差累积严重，后期步骤不可靠 |
| [OntoKGen](https://arxiv.org/abs/2412.00608) (ASU 2024) | 迭代式 CoT 提取 + 交互式 UI 确认 | 输出为 Neo4j 图谱，非 OAG 格式 |

**共识**：分步比一步到位靠谱；人机交互不可省；实体抽取已接近人类水平，关系和规则仍是难点。

## 3. 设计原则

**P1: 分层抽取** — 概念、关系、函数、规则分别用不同策略提取，不混为一步。

**P2: 迭代精炼** — 每份文档迭代处理，带着上一轮结果读新文档，而非一次性输入所有文档。

**P3: 生成即验证** — 每个阶段输出后立即用 OAG Agent 试跑，用推理结果反馈模型质量。

**P4: 原文溯源** — 每个模型元素记录来源文档和位置，便于人工审查和后续维护。

**P5: 输出直接可用** — 不输出中间格式再转换，直接生成 `ontology.yaml` + 函数骨架 + 数据映射。

**P6: 现有 domain 作为 few-shot** — fee、hv_access、road_emergency 三个已有 domain 是最好的输出格式范例。

## 4. Pipeline 设计

### 总览

```
文档集合
  │
  ▼
Phase 0: 文档准备
  │  分块、结构识别、摘要索引
  ▼
Phase 1: 概念发现
  │  识别核心实体类型 → objects 草案
  │  [人工确认: 粒度、命名、有无遗漏]
  ▼
Phase 2: 属性丰富
  │  逐份文档迭代，为每个对象发现属性
  │  [人工确认: 类型、必填、描述准确性]
  ▼
Phase 3: 关系发现
  │  识别对象间关联 → links 草案
  │  [人工确认: 方向、join key、描述]
  ▼
Phase 4: 业务流程 / 函数发现
  │  识别领域操作、参数、依赖链 → functions 草案
  │  [人工确认: 函数拆分粒度、依赖关系]
  ▼
Phase 5: 规则提取
  │  为每个函数提取详细规则 → hint
  │  [人工确认: 逐条对照原文]
  ▼
Phase 6: Prompt 工程优化
  │  重写 summary/description/hint，使其对 LLM 推理最友好
  ▼
Phase 7: 闭环验证
  │  启动 OAG Agent → 试答领域问题 → 分析失败 → 回到对应 Phase 修正
  ▼
可运行的 OAG Domain
  ├── ontology.yaml
  ├── functions/*.py (骨架)
  ├── data/ (映射配置)
  └── prompts.json
```

### Phase 0: 文档准备

**输入**：一组业务文档（PDF/Word/Markdown）

**处理**：
- 文档格式转换为纯文本/Markdown
- 结构识别：标题层级、表格、公式、流程图描述
- 分块：按章节/条款切分，保留层级上下文
- 生成文档摘要索引：每份文档一句话概括内容，供后续阶段按需引用

**输出**：文档索引 + 结构化分块

**关键考虑**：
- 中文法规/标准通常有明确的章节编号（如 §4.2.1），利用这个结构做分块
- 表格（如费率表、等级对照表）需要特殊处理，它们通常是属性和规则的重要来源
- 图片中的流程图如果能用多模态 LLM 解读会很有价值

### Phase 1: 概念发现

**输入**：文档索引 + 最核心的 1-2 份规范文档

**LLM 任务**：
```
给定以下领域文档，识别其中的核心实体/概念。
每个实体给出：
- 名称（PascalCase，如 TollStation）
- 一句话描述（summary）
- 来源（文档名 + 章节号）

参考已有 OAG domain 的粒度（few-shot 示例）：
[附上 fee/ontology.yaml 的 objects 部分作为示例]
```

**输出**：objects 初稿（只有名称和 summary，没有属性细节）

**人工交互点**：
- 粒度是否合适？（太粗 → 拆分，太细 → 合并）
- 命名是否清晰？
- 有无重要遗漏？
- 有些概念可能是属性而非独立对象 → 调整

**难点与策略**：
- LLM 倾向于过度细分。提示中应强调"只提取 LLM 推理时需要独立操作的核心概念"
- 可以让 LLM 同时输出"候选概念"和"可能是属性而非独立对象的概念"，由人判断

### Phase 2: 属性丰富

**输入**：Phase 1 确认后的 objects + 逐份文档

**LLM 任务**（对每份文档重复）：
```
当前领域模型中已有以下对象类型：
[当前 objects 状态]

阅读以下文档片段，判断：
1. 已有对象是否需要新增属性？
2. 已有属性的描述是否需要补充/修正？
3. 是否发现了新的对象类型？

对每个新属性，给出：
- 属性名（snake_case）
- 类型（str/int/float/bool）
- 是否必填（业务唯一标识 → required: true）
- 描述（含单位、取值范围、枚举值等）
- 来源（文档名 + 章节号）
```

**迭代策略**：Schema-Miner 式逐篇处理。每篇文档处理完后更新 schema，下一篇看到的是更新后的版本。

**人工交互点**：每 3-5 篇文档后暂停，人工审查增量变更。

### Phase 3: 关系发现

**输入**：属性丰富后的 objects + 文档

**LLM 任务**：
```
已有以下对象类型及其属性：
[当前 objects 状态]

从文档中识别对象间的关联关系。每个关系给出：
- 关系名称（如 unit_has_rate_params）
- 源对象和目标对象
- 通过哪个字段关联（source_key, target_key）
- 关系描述

注意：关系必须通过具体字段连接，不是抽象的"相关"。

参考示例：
[附上 fee/ontology.yaml 的 links 部分]
```

**难点与策略**：
- 关系的方向性容易搞错 → 让 LLM 用自然语言先描述关系（"收费单元属于某条收费公路"），再转化为 source/target
- join key 的准确性至关重要 → 必须人工验证
- 有些关系是"计算产出"关系（如 compute_fees 产出 ProvinceRateParam），这类关系在 Phase 4 可能更容易识别

### Phase 4: 业务流程 / 函数发现

**输入**：完整的 objects + links + 流程类文档（操作规程、处置规范等）

**LLM 任务**：
```
已有以下领域模型：
[objects + links]

从文档中识别可执行的业务操作/计算/流程。每个操作给出：
- 函数名（snake_case）
- summary（一行概括做什么）
- group（业务分组）
- 输入参数（名称、类型、描述）
- 依赖哪些其他函数（depends_on）
- 操作涉及哪些对象类型
- 来源（文档名 + 章节号）

参考已有 domain 的函数设计粒度：
[附上 fee/ontology.yaml 或 road_emergency/ontology.yaml 的 functions 部分]
```

**关键判断**（需要人工参与）：
- 函数粒度：太粗（一个函数做太多事 → LLM 调用时参数复杂）vs 太细（函数太多 → LLM 规划困难）
- 依赖链设计：哪些函数应该自动触发前置依赖？哪些应该让 LLM 自行规划？
- 有些"操作"可能不需要成为函数，通过 query + LLM 推理就能完成

### Phase 5: 规则提取

**输入**：Phase 4 确认后的 functions + 规则/标准文档的具体条款

**LLM 任务**（对每个函数单独执行）：
```
以下是函数 {function_name} 的定义：
{function 的 summary 和 params}

该函数涉及以下对象类型：
{相关 objects 的完整定义}

从以下文档中提取该函数执行时需要遵循的业务规则：
{对应的文档条款}

规则格式要求：
- 每条规则编号（R1, R2, ...）
- 必须包含: 条件、计算方式/判断逻辑
- 使用属性的准确名称（与 ontology 中一致）
- 不要泛化或推断，只提取文档中明确写的规则
```

**这是最需要人工把关的阶段**：
- 规则的准确性直接影响 Agent 的计算结果
- LLM 可能"补全"文档没有明确说的规则 → 必须逐条核对
- 公式中的单位、精度要求（如"四舍五入到元"）容易被忽略

**策略**：
- 对每个函数，先让 LLM 列出"我认为相关的文档段落"，人确认后再提取规则
- 规则提取后，让另一个 LLM 实例做"规则审查"（类似 NOMAD 的多 Agent 分工）

### Phase 6: Prompt 工程优化

**输入**：完整的 ontology 草案

**任务**：优化所有面向 LLM 的文本（summary、description、hint），使其在 OAG Agent 的 system prompt 中发挥最大效果。

具体包括：
- **summary** 要在一行内让 LLM 明白这个对象/函数的核心作用（system prompt 中只展示 summary）
- **description** 要让 LLM 调用 inspect() 后获得完整理解（渐进式披露的第二层）
- **hint** 要让 LLM 在首次调用函数时获得足够的规则指导（渐进式披露的第三层）
- 检查术语一致性：同一个概念在不同位置的名称是否统一

这一步可以用 LLM 自动优化 + 人工审查。

### Phase 7: 闭环验证

**方法**：
1. 用生成的 ontology.yaml 启动 OAG Agent
2. 准备一组测试问题（覆盖查询、计算、多步推理等场景）
3. 运行 Agent 回答，记录：
   - Agent 调用了哪些工具？顺序是否合理？
   - 函数依赖链是否正确触发？
   - 结果是否正确？
   - Agent 是否在不该猜测的地方猜测了？（说明 ontology 信息不足）
   - Agent 是否调了不必要的工具？（说明 summary/description 有歧义）
4. 根据失败模式定位 ontology 缺陷，回到对应 Phase 修正

**测试问题的来源**：
- 人工编写的典型业务问题
- 从文档中提取的示例场景
- Phase 4 中 LLM 可以附带生成"这个函数应该能回答什么问题"

## 5. ontology.yaml 格式演进建议

在构建 Distiller 的过程中，ontology.yaml 本身可能需要一些演进来更好地支持自动化生成和维护。

### 5.1 增加 source（出处溯源）

```yaml
objects:
  Bridge:
    summary: "桥梁基础信息"
    description: ...
    source: "公路交通应急处置技术规范 §4.2"
    properties:
      span_length:
        type: float
        description: "跨径(米)"
        source: "表4.2.1"
```

**价值**：人工审查时可直接定位原文；规则变更时知道影响范围；Distiller 自动填写。

### 5.2 把数据映射纳入 ontology

当前 DATA_FILES 和 FIELD_MAPPINGS 在 Python 的 `functions/__init__.py` 中。建议纳入 ontology.yaml：

```yaml
objects:
  TollStation:
    ...
    data_source:
      file: toll_station.json
      field_mapping:
        STATIONID: station_id
        NAME: name
        TYPE: type
        USESTATUS: use_status
```

**价值**：ontology 成为自包含的领域描述；Distiller 可以在有原始数据时自动推断映射。

### 5.3 增加 examples / test_cases

```yaml
functions:
  find_path:
    ...
    examples:
      - question: "从A收费站到B收费站，客车一型的通行费是多少？"
        input: {en_station_id: "S001", ex_station_id: "S042", vehicle_type: 1}
        expect: "返回路径和费额"
```

**价值**：Phase 7 闭环验证的自动化素材；LLM inspect() 时看到示例有助于理解函数语义。

### 5.4 hint 的软结构化

保持自由文本（对生成端 LLM 友好），但约定格式规范：

```yaml
hint: >
  R1: 条件 → 规则描述。
  R2: 条件 → 规则描述。
  注意: ...
```

不强制 JSON 结构化（增加生成难度），但约定：
- 每条规则以编号开头（R1/V1/E1）
- 公式用 `=` 表示
- 单位在括号中标注
- "注意"标记例外情况

## 6. 技术方案选型

### 6.1 LLM 接口

复用 OAG 已有的 OpenAI 兼容接口（支持 qwen、本地模型等），不引入额外依赖。通过 .env 配置，与 OAG 主体共享 LLM 配置。

### 6.2 实现形态

作为 OAG 的一个子命令实现：

```bash
oag distill --docs ./raw_docs/ --output ./domains/new_domain/
oag distill --stage 1 --docs ./raw_docs/
oag distill --stage 2 --schema ./domains/new_domain/ontology.yaml --docs ./raw_docs/
oag distill --verify --domain ./domains/new_domain/
```

### 6.3 人机交互方式

两种模式：
- **CLI 交互模式**：每个阶段完成后在终端展示结果，等待用户确认/修改
- **文件编辑模式**：每个阶段输出中间 YAML，用户用编辑器修改后继续下一阶段

### 6.4 Few-shot 管理

已有的三个 domain（fee、hv_access、road_emergency）作为 few-shot 示例库。Distiller 根据当前 Phase 自动选择对应部分：
- Phase 1 → 展示已有 domain 的 objects 名称和 summary
- Phase 3 → 展示已有 domain 的 links 结构
- Phase 4 → 展示已有 domain 的 functions 设计

## 7. 可行性评估与实施路径

### 7.1 各阶段可行性预估

| Phase | 自动化可行性 | 依据 |
|-------|-------------|------|
| Phase 0 文档准备 | 高 | 成熟的 PDF/文本处理工具 |
| Phase 1 概念发现 | 高 | LLM 实体识别已接近人类水平 |
| Phase 2 属性丰富 | 高 | Schema-Miner 已验证此路径 |
| Phase 3 关系发现 | 中 | 方向性和 join key 易出错 |
| Phase 4 函数发现 | 中 | 粒度判断需要经验 |
| Phase 5 规则提取 | 中-低 | 忠实度要求极高，LLM 易"补全" |
| Phase 6 Prompt 优化 | 高 | LLM 擅长改写文本 |
| Phase 7 闭环验证 | 高 | 已有 OAG Agent 基础设施 |

### 7.2 建议的实施顺序

**第一步：验证可行性（Phase 1-2）**

用 hv_access 的原始文档作为输入，看 Distiller 能自动恢复多少已有 ontology 中的 objects 和属性。与人工结果对比，量化 LLM 的抽取质量。

**第二步：补齐核心能力（Phase 3-5）**

在第一步验证可行后，逐步加入关系发现和函数/规则抽取。这是最有挑战的部分，可能需要多轮 prompt 迭代。

**第三步：打通闭环（Phase 6-7）**

接入 OAG Agent 做验证，形成"生成 → 试用 → 修正"的完整循环。

**第四步：产品化**

CLI 交互、进度记录、增量更新（文档变更后只更新受影响的部分）。

## 8. 开放问题

1. **函数实现的自动生成**：ontology.yaml 中的函数定义只是签名和规则。实际的 Python 实现能否也自动生成？至少骨架代码（函数签名 + 参数解析 + 注释）是可行的，核心逻辑可能需要人工编写或 LLM 辅助。

2. **增量更新**：法规/标准会修订。当源文档变更时，如何最小化地更新 ontology，而非重新生成？需要 source 溯源字段的支持。

3. **多文档冲突**：不同文档对同一概念的描述可能不一致。Distiller 如何处理？标记冲突让人判断？还是自动选择更权威的来源？

4. **从 ontology 到可运行 domain 的最后一公里**：即使 ontology.yaml 完美生成了，还需要 Python 函数实现和测试数据。这部分的自动化程度决定了整体工具的实用价值。

5. **评估指标**：如何系统地评估生成的 ontology 质量？除了 Phase 7 的 Agent 试用，是否需要更形式化的指标？
