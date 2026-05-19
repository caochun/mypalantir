# hv_access — 高压(10kV)接入方案设计

> OAG 框架下"接口数据 + 业务编排"模式的参考实现，配套记录建模过程与设计思考。

## 1. 业务背景

10kV 高压接入方案设计是电力配网的核心业务之一。客户提出新装 / 增容 / 临时用电申请，业务人员需要：

1. 在客户红线周边搜索合适的电源点（馈线上的杆塔、开关站、环网柜）
2. 套用《配网 3 号文》等硬约束筛选合格的电源点
3. 按用户重要性等级（特级 / 一级 / 二级 / 临时 / 非重要）组合电源拓扑：
   - 单电源 / 双电源（跨变电站）/ 双回路（跨母线）/ 多电源（3 路含应急）
4. 当电源点超载或容量不足时，评估**负荷划接**（通过联络开关转移负荷）或**变电站新出线**作为救济
5. 按距离 / 容量 / 可靠性三维加权评分，最终输出供业务人员选择的若干套方案

数据来源于已有的"电网一张图"接口（生产环境）。本仓库用 mock JSON 模拟。

完整业务规则见同目录 `spec.md`（pandoc 转出的 markdown 版业务规则说明书）。

## 2. 文件结构

```
domains/hv_access/
├── README.md                 本文件
├── spec.md                   业务规则说明书(pandoc 转出)
├── media/                    spec.md 的配图
├── ontology.yaml             本体定义: 16 对象 + 4 link + 18 函数
├── __init__.py
├── data/
│   ├── importance_level_map.json   行业→重要性等级映射规则(35 条，落库)
│   ├── source_requirement.json     (负荷,等级)→电源结构要求(8 条，落库)
│   ├── access_request.json         样例申请: 新装/临时(4 条，落库)
│   ├── expand_request.json         样例申请: 增容(1 条，落库)
│   ├── substation.json             mock 电网数据(不落库，走接口)
│   ├── main_transformer.json
│   ├── busbar.json
│   ├── feeder.json
│   ├── access_point.json
│   ├── feeder_tie_switch.json
│   └── transformer_tie_switch.json
└── functions/
    ├── __init__.py           注册所有函数 + 数据装载映射
    ├── interfaces.py         7 个接口包装(mock 实现)
    ├── lookups.py            2 个规则反查
    ├── _helpers.py           跨业务函数的共享工具(拓扑遍历等)
    ├── search.py             search_sources: 扩散搜索
    ├── filter.py             filter_sources: 7 条硬约束
    ├── transfer.py           transfer_feeder_load / transfer_transformer_load
    ├── new_feeder.py         new_feeder: 变电站新出线评估
    ├── compose.py            compose_plans: 拓扑组合
    ├── score.py              score_plans: 三维评分
    └── finalize.py           finalize_plans: 按运行方式去重
```

## 3. 本体的分层架构

ontology.yaml 中的 16 个对象按**数据来源**分为三层：

```
┌─ 电网对象(7 个) ─────────────── 外部接口数据，框架建空表，所有查询走 get_xxx 函数
│  Substation, MainTransformer, Busbar, Feeder, AccessPoint,
│  FeederTieSwitch, TransformerTieSwitch
└──────────────────────────────

┌─ 业务规则对象(2 个) ──────────── 稳定配置数据，落库可 query 也可 lookup_*
│  ImportanceLevelMap     行业编码→重要性等级
│  SourceRequirement      (负荷,等级)→电源结构要求
└──────────────────────────────

┌─ 业务过程对象(7 个) ──────────── 智能体推理产物，落库供查询/审计
│  AccessRequest          接入申请(新装/临时)
│  ExpandRequest          接入申请(增容)
│  AccessPlan             候选/最终/淘汰方案
│  FeederLoadTransfer     馈线间负荷划接建议
│  TransformerLoadTransfer 主变间负荷划接建议
│  NewFeederSuggestion    变电站新出线建议
│  NoSolutionVerdict      无可用方案判定
└──────────────────────────────
```

### 3.1 为什么电网对象不入库

- 真实电网数据量大，不可能 dump 进本地 sqlite
- 状态字段（负载率/可开放容量/线损率）实时性强，本地缓存会与生产数据不一致
- 空间查询由接口承担（"给坐标+半径，返回范围内"），不重复实现索引

代价：ontology 中定义的属性 LLM 只能通过 `get_xxx` 函数中转获取，不能直接 query。每个电网对象的 description 第一句话明确告诉 LLM 用哪个函数。

### 3.2 为什么规则也是对象

`ImportanceLevelMap` 和 `SourceRequirement` 本质是查表配置，可以单纯当成查询函数实现。但建模成对象的好处：

1. LLM 可以直接 query 浏览全集（"查所有特级行业"）
2. 跟 `lookup_*` 函数互补（精准查 vs 浏览）
3. 业务规则的可见性更强 — 用户能看到完整规则表

## 4. 关键建模决策

### 4.1 删除顶层 `generate_plans` 函数

最初的设计有个 `generate_plans(request_id)` 一键函数，硬编码了流程：

```
new_request:    search → filter → compose → score → finalize
expand_request: filter(原点) → transfer_load
force_new:      new_feeder
```

后来删了。理由：

- OAG 框架的核心理念是**让 LLM 看到声明式的世界模型，自己编排流程** — 顶层硬编码绕过了这个能力
- spec 第五章要求"PDF 预览展示模型思考过程" — 一键函数让中间过程不可见
- LLM 自由编排时反而更聪明：会跳过冗余 lookup（看 request 已带等级时）、会主动尝试多条救济路径

实证：删除后，LLM 完整跑通 R001-R005 五个场景，部分场景比硬编码版本更细致。

### 4.2 接口包装函数 = 薄包装层

`interfaces.py` 中 7 个 `get_*` 函数都是对外部"电网一张图"接口的薄包装。**接口签名（参数、返回值结构）就是 ontology 对象字段的镜像**。

生产对接时只需替换 `interfaces.py`（mock JSON 读取 → HTTP 调用），ontology 和业务编排函数零改动。这是分层带来的稳定性。

### 4.3 6 个 `list_all_*` 函数仅供 UI 使用，不暴露 LLM

电网对象因为不入库，UI 数据面板查 sqlite 会返回空。为了 UI 演示，加了 6 个无参的 `list_all_*` 函数（直接读 mock JSON 全集）。

但这些函数在 ontology.yaml 中**不定义 FunctionDef**，仅在 `functions/__init__.py` 中注册到 registry。结果：

- `agent.py:387` 跳过无 fdef 的函数 → LLM 工具列表里看不到
- `/function/{name}` 端点依赖 `registry.has()` → UI 能直接调

未来对接真接口时，`list_all_*` 整体删除（生产环境无"列全部"操作）。

## 5. 三次"运行时约束 → 结构约束"重构

ontology 演进中，三处反模式被识别并消除：**用某个字段的值来决定其它字段的语义/适用流程**。这种"运行时 discriminator"在严格的对象建模中是异味，应该用类型分派替代。

### 5.1 重构一：AccessRequest 拆分

**反模式**：用 `business_type` 字段值（新装/增容/临时）决定：
- `original_point_id` 字段是否必填（增容时必填）
- `search_sources` 函数是否适用（增容场景不用）
- 整个流程分支

**重构**：拆为两个独立对象。

```yaml
AccessRequest:        # 新装/临时
  request_id, customer_name, capacity_kva, importance_level, business_type, ...

ExpandRequest:        # 增容
  request_id, customer_name, capacity_kva, importance_level, ...
  original_point_id (required: true)      ← 物理上不可缺失
  original_capacity_kva (required: true)
```

**收益**：
- 字段必填性由 schema 强制，不再靠运行时检查
- LLM 调 `get_request` 看 `request_type` 字段即知分支，比看 `business_type` 字符串值更结构化
- `search_sources` 的"仅适用于新装/临时"约束变得自然（接受 AccessRequest 的 ID）

### 5.2 重构二：TieSwitch 拆分

**反模式**：`TieSwitch.scope`（feeder/transformer）决定 `source_id` / `target_id` 指向哪种对象（馈线 ID 还是主变 ID）。

**重构**：拆为 `FeederTieSwitch`（source/target_feeder_id）和 `TransformerTieSwitch`（source/target_transformer_id）。

附带函数也拆：
- `get_tie_switches(scope, source_id)` → `get_feeder_tie_switches(source_feeder_id)` + `get_transformer_tie_switches(source_transformer_id)`
- `transfer_load(scope, source_id, ...)` → `transfer_feeder_load` + `transfer_transformer_load`

**收益**：
- 字段类型明确，编辑时不会误填
- LLM 看 filter 失败的 F1（馈线超载）/F7（主变超载）直接选对应救济函数，无 scope 字符串歧义

### 5.3 重构三：PlanIssue 拆分

**反模式**：`PlanIssue.issue_type`（load_transfer/new_feeder/no_solution）决定 source_id/target_id 的含义，且 no_solution 时这两个字段为空。

**重构**：按业务语义拆为 4 个独立对象：

| 对象 | 关键字段 |
|---|---|
| FeederLoadTransfer | source_feeder_id, target_feeder_id, switch_id, transfer_capacity_kva |
| TransformerLoadTransfer | source_transformer_id, target_transformer_id, switch_id, transfer_capacity_kva |
| NewFeederSuggestion | substation_id, transformer_id, distance_m, load_rate, openable_capacity |
| NoSolutionVerdict | reason, searched_radius_m（无 source/target，干净） |

**收益**：
- 每个对象字段语义独立，业务系统消费时不需要"先判类型再判字段含义"
- NoSolutionVerdict 字段干净，不再有空 source/target

**代价**：4 种对象 × 2 种 Request = 8 条 link 关系。决定**不建 link**（issue 通过 request_id 字段关联，LLM 直接用 query+filter 而不是 query_links）。

## 6. 声明式 vs 过程性 — cheat sheet 实验

ontology 早期版本在 `description` 顶部塞了一份"标准推理流程"小抄，类似：

```
新装/临时: lookup_importance_level → search_sources → filter_sources → ...
增容: filter_sources(原点) → transfer_load(失败时)
强制新出线: new_feeder
```

这种"流程图"是**过程性指引**。后来通过实验发现：

### 6.1 实验 1：完全删除 cheat sheet

只保留每个对象/函数自己的描述，把流程隐藏到对象/函数的语义里。

**结果**：R001/R002/R004 标准流程跑通，但 R003（增容）走偏 —— LLM 不知道增容应该跳过 search。

**原因**：业务策略（"增容跳过 search"）不是结构推理能得出的。结构上 search_sources 接受 request_id 参数，LLM 看不出对 ExpandRequest 不该调用。

### 6.2 实验 2：在被约束方写最少策略

最终选择：约束写在**被约束的函数自身的 description 里**。例如：

```yaml
search_sources:
  description: "电源点空间搜索...接受 AccessRequest 的 request_id(增容请用 ExpandRequest 流程)"
```

加这一句话，R003 立刻识别出"我用 ExpandRequest，不该调 search_sources"。

### 6.3 关键洞察

**结构知识 vs 业务策略**是两类不同性质的知识：

| 类型 | 举例 | 能否声明式表达 |
|---|---|---|
| 结构知识 | "compose_plans 写入 AccessPlan 表，所以 score_plans 应在它之后" | ✓ 通过函数副作用 + 输入输出名匹配 |
| 业务策略 | "增容场景跳过 search_sources" | ✗ 必须显式描述，但可以**附在被约束的对象/函数上** |

OAG 框架的 declarative-first 理念在**结构知识**上完全有效；**业务策略**必须显式，但好的实践是把它绑在**最相关的字段或函数描述里**（语义匹配度最高），而不是放在外部的全局 cheat sheet。

## 7. 渐进式披露 — Anthropic Skills 启发

随着 ontology 细化到 16 对象 + 18 函数，原始 system prompt 膨胀到 ~10000 字（~3500 tokens）。Token 不是瓶颈（Gemma 26B 有 262K context），但 **LLM 注意力分散** 成了问题。

### 7.1 双层信息暴露

为 `ObjectTypeDef` 和 `FunctionDef` 加 `summary` 字段：

```yaml
filter_sources:
  summary: "套用 7 条硬约束筛选电源点(批量或单点)"   # 默认 prompt 显示
  description: "对候选电源点套用..."                # 完整描述
  hint: "约束规则: F1...F7... Rejected 含义对应..." # 详细规则
  params: {...}
```

默认 system prompt 中**只渲染 summary**，完整定义通过两种机制按需浮出：

### 7.2 机制 A：inspect 工具（主动）

新增工具 `inspect(name)`，返回任何函数或对象的完整定义。LLM 在需要细节时主动调用。

实测：**LLM 在测试中 0 次主动调 inspect**。它默认认为 summary 够用。inspect 工具主要作为给用户/调试的备用入口存在。

### 7.3 机制 B：自动注入（被动，主要起作用）

修改 `_execute_tool`：

1. **首次调用某函数时**，在 result 末尾自动附加该函数的 `hint`
2. **当 result 含 `*_type=ObjectName` 字段**且对应已知对象时，自动附加对象的完整 description

具体效果：

- LLM 调 `get_request("R003")` → 结果 `request_type=ExpandRequest`
- 框架自动注入 `[对象 ExpandRequest 的完整定义]`（包含"不适用 search_sources"等流程提示）
- LLM 第一次看到就理解了流程

- LLM 调 `filter_sources(...)` → 结果含 rejected reasons
- 框架自动注入 `[函数 filter_sources 的详细规则]`（含 F1-F7 含义 + 对应救济类型）
- LLM 后续决策时已经知道完整规则

### 7.4 数据

| 阶段 | system prompt 字数 | 备注 |
|---|---|---|
| 初版（含 cheat sheet） | ~10000 | 流程小抄 + 全 hint |
| 删 cheat sheet | ~8000 | 散布过程性指引到各 hint |
| Z 重构后（更细致） | 10674 | 对象数从 9 到 16 |
| 渐进式披露 | **2518** | -76%，summary only |

LLM 接触到的总信息量没减少（hint 被自动注入），但**默认 prompt 的信息密度提高了**。

### 7.5 与 Anthropic Skills 的对应关系

| Skills 设计 | OAG 实现 |
|---|---|
| skill menu (name + description) | summary 列表 |
| skill body 按需加载 | inspect 工具 / 自动注入 |
| skill 资源被加载到 context | hint / description 注入到 tool result |
| 用户/LLM 决定激活哪个 skill | LLM 调函数 → 框架自动激活该函数的细节 |

OAG 在 LLM **不主动** inspect 时仍能让信息浮出 —— 这是对原始 Skill 模式的一个改进。

## 8. 测试场景（R001-R005）

5 个测试申请覆盖主要业务分支：

| 申请 | 客户 | 容量 | 等级 | 业务类型 | 预期流程 |
|---|---|---|---|---|---|
| R001 | 示范医院 | 5000 kVA | 一级负荷/一级 | 新装 | 标准 6 步 → 3 套双电源方案 |
| R002 | 嘉定大学 | 3000 kVA | 二级负荷/二级 | 新装 | 标准 6 步 → 1 套单电源方案 |
| R003 | 时代商超 | 8000kVA(原 3000) | 二级负荷/二级 | 增容 | 跳过 search → filter(AP005) → 文字救济建议 |
| R004 | 云端数据中心 | 18000 kVA | 一级负荷/特级 | 新装 | 标准流程 → filter 全失败 → new_feeder 兜底 |
| R005 | 国庆灯光秀 | 1500 kVA | 二级负荷/临时 | 临时 | 标准 6 步 → 1 套单电源方案 |

LLM 行为观察：

- 主流程（R001/R002/R005）几乎 100% 稳定通过
- 分支识别（R003 走增容路径）依赖自动注入 ExpandRequest description
- 救济场景（R003/R004 filter 失败后）LLM 倾向**给文字建议**而非自动调救济函数。这跟 spec 第五章"展示思考过程，由人决策"的理念一致 —— 不强行让 AI 替代业务人员决策

## 9. 启动与使用

### 9.1 环境

```bash
cd /Users/chun/Develop/mypalantir
echo "DOMAIN=domains/hv_access" >> .env
echo "LLM_API_URL=https://your-endpoint/v1" >> .env
echo "LLM_API_KEY=sk-xxx" >> .env
echo "LLM_MODEL=your-model" >> .env

uv sync   # 装依赖
```

### 9.2 命令行

```bash
DOMAIN=domains/hv_access uv run python -m oag.cli info
DOMAIN=domains/hv_access uv run python -m oag.cli chat       # 交互式 chat
DOMAIN=domains/hv_access uv run python -m oag.cli call <fn>  # 直接调函数
DOMAIN=domains/hv_access uv run python -m oag.cli serve      # Web UI / REST API
```

Web UI 访问 `http://localhost:8000` —— 包括对话面板和对象数据面板（电网对象通过 `list_all_*` fallback 显示）。

### 9.3 编程接口

```python
from dotenv import load_dotenv
load_dotenv()
from oag.loader import load_domain
from oag.agent import Agent
import os

ontology, store, registry = load_domain("domains/hv_access")
agent = Agent(ontology, store, registry, {
    "api_url": os.getenv("LLM_API_URL"),
    "api_key": os.getenv("LLM_API_KEY"),
    "model": os.getenv("LLM_MODEL"),
    "max_turns": 20,
})

# 流式
for ev in agent.chat_stream("R003 增容能不能做？"):
    print(ev)

# 直接调函数
result = registry.call("filter_sources",
                       request_id="R003",
                       point_ids="AP005",
                       per_path_capacity_kva=5000)
```

## 10. 未来工作

| 方向 | 价值 | 难度 |
|---|---|---|
| 真接口对接（替换 interfaces.py 为 HTTP 调用） | 上生产 | 中（接口字段对齐） |
| pytest 测试沉淀（R001-R005 工具序列固化） | 防回归 | 低 |
| 框架加 `external: true` 字段消除电网对象"用 get_xxx 不要用 query"提示 | 进一步清洁 ontology | 中（改框架） |
| PDF 输出（spec 第五章要求） | 业务交付 | 中（加 PDF 生成 + 路径走向数据） |
| 复用本范式建另一领域（低压接入 / 分布式光伏） | 验证可复用性 | 中 |

## 11. 关键洞察总结

如果只能记住几条，是这些：

1. **数据来源分层 = 框架职责分层**：电网接口 / 配置规则 / 推理产物分别用三种数据获取策略（接口 mock / 落库装载 / 函数写入），代码相应分层
2. **类型分派 > 字段分派**：能用对象类型表达的业务分支，不要用字段值表达。LLM 看类型比看字符串值的信号强度大
3. **业务策略放在被约束方**：跨函数的业务约束，写在被约束的函数 / 对象自身的 description 上，语义匹配度最高
4. **声明式优先，但承认例外**：90%+ 的流程能从结构推出来，剩下的业务策略明示就好；不必为了 100% 声明式而做奇怪的间接表达
5. **渐进式披露 + 自动注入**：用 summary 缩短默认上下文，靠"按使用自动浮出 hint"而非"按需主动 inspect"来恢复信息完整性 —— LLM 不会主动按需，但会被动接受
6. **AI 给文字建议比自动决策更稳健**：物理操作（如负荷划接）的最终拍板应该留给人，LLM 输出"建议什么"已经足够价值
