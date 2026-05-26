# OAG — Ontology Augmented Generation

LLM 在结构化世界模型上规划工具调用，确定性计算产出结果。

## 核心理念

OAG 不是 RAG（检索文本让 LLM 总结），而是让 LLM 作为**决策引擎**，在一个结构化的本体模型（Ontology）上编排工具调用，所有业务计算由确定性代码执行。

```
用户问题 → Harness（上下文组装/工具过滤）
              → LLM（决定调哪个工具、传什么参数）
              → Harness（权限检查/执行/截断/审计/缓存）
              → 工具执行（SQL 查询 / 规则引擎 / 业务函数）
              → 结果喂回 LLM → 决定下一步 → ... → 最终回答
```

## 架构设计（v2）

v2 架构借鉴 [Claude Code](https://claude.ai/claude-code) 的设计思想，引入 Harness 层作为 LLM 和执行之间的确定性中间层。

### 分层架构

```
┌──────────────────────────────────────────────────┐
│                    用户 / 前端                     │
├──────────────────────────────────────────────────┤
│  API 层 (api.py)         CLI (cli.py)            │
├──────────────────────────────────────────────────┤
│  Orchestrator (orchestrator.py)                   │
│    └─ Agent Loop（动态工具调用循环）                 │
├──────────────────────────────────────────────────┤
│  Harness 层 (harness.py) — 确定性中间层            │
│  ├─ Hook 系统    — pre/post_tool_call 拦截         │
│  ├─ 权限检查     — 写操作需用户确认                  │
│  ├─ 结果截断     — 防止超长结果消耗 token            │
│  ├─ 审计日志     — 记录每次工具调用                  │
│  ├─ 工具缓存     — 只读工具同参数不重复执行           │
│  ├─ 规则引擎     — 声明式规则编译为确定性函数          │
│  ├─ 上下文管理   — token 估算 + 自动压缩             │
│  ├─ Stop hook    — 回复完成度自检                   │
│  └─ Worker 派遣  — 多智能体并行执行                  │
├──────────────────────────────────────────────────┤
│  工具执行层                                        │
│  ├─ 内置工具     — query/count/inspect/describe     │
│  ├─ 规则工具     — apply_rule/apply_rule_batch      │
│  ├─ 业务函数     — 领域注册的 Python 函数            │
│  └─ Worker 工具  — dispatch_workers 并行子智能体     │
├──────────────────────────────────────────────────┤
│  数据层                                           │
│  ├─ Ontology     — YAML 定义的世界模型              │
│  ├─ Store        — SQLite 数据存储                  │
│  └─ Session      — 会话历史持久化                   │
└──────────────────────────────────────────────────┘
```

### 元模型（v2）

OAG 的本体用 YAML 定义，v2 元模型包含 5 个一级概念：

| 概念 | 说明 | 示例 |
|---|---|---|
| **objects** | 对象类型，带 `kind` 字段区分用途 | `Bridge {kind: entity}`, `DroneClassRule {kind: rule_table}` |
| **links** | 对象间关系 | `disaster_has_inspections: DisasterEvent → FacilityInspection` |
| **functions** | 可调用的业务函数 | `inspect_facility`, `plan_recon_mission` |
| **rules** | 确定性可执行规则（不需要 LLM 推理） | `drone_weight_classification: 重量→类别` |
| **workflows** | 显式工作流（引导 Agent 执行步骤） | `emergency_response: 11 步应急处置流程` |

Object 的 `kind` 字段：
- `entity` — 业务实体（多实例、增删改）
- `rule_table` — 规则表（固定条目、不变，Harness 可缓存）
- `lookup_table` — 参考数据（原文检索）

### 关键机制

| 机制 | 说明 |
|---|---|
| **动态 Agent Loop** | LLM 调工具→看结果→决定下一步，天然支持动态分支 |
| **Harness 层** | LLM 和工具之间的确定性中间层，控制权限/截断/审计/缓存 |
| **规则引擎** | 声明式规则编译为 Python 函数，Agent 调 `apply_rule` 而非自己推理 |
| **Workflow 引导** | 工作流定义在 system prompt 中引导 Agent 步骤顺序 |
| **写操作确认** | `writes_to` 非空的函数触发前端确认对话框 |
| **多智能体** | `dispatch_workers` 派遣多个 Worker 并行执行独立子任务 |
| **Stop hook** | Agent 回复后自检完成度，回复过短或有未处理错误则补充 |
| **循环中压缩** | 每 5 轮检查 token，超阈值自动压缩历史 |
| **工具缓存** | 只读工具同参数调用直接返回缓存 |
| **业务校验** | post_tool_call hook 对写操作结果做规则性校验 |

## 快速开始

### 环境要求

- Python 3.11+
- 一个 OpenAI 兼容的 LLM API（本地或远程）

### 安装

```bash
git clone https://github.com/caochun/mypalantir.git
cd mypalantir
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 设置 LLM API 地址和模型名
```

`.env` 文件：

```
LLM_API_KEY=your-api-key
LLM_API_URL=http://localhost:8090/v1
LLM_MODEL=your-model-name
```

### 启动服务

```bash
# 多域模式（自动挂载 domains/ 下所有领域）
oag serve --port 18000

# 单域模式
DOMAIN=domains/drone oag serve --port 18000
```

### CLI 对话

```bash
oag chat
```

### 访问前端

打开 `http://localhost:18000/d/drone/`

## 领域建模

### 目录结构

```
domains/drone/
├── ontology.yaml      # 本体定义（v2 元模型）
├── data/              # JSON 数据文件
│   ├── disaster_event.json
│   ├── drone.json
│   ├── damage_grade_standard.json
│   └── ...
├── functions/         # Python 函数实现
│   ├── __init__.py    # 函数注册
│   ├── _helpers.py    # 工具函数
│   ├── interfaces.py  # 接口/查询函数
│   └── ...
├── prompts.json       # 示例提问
└── *.md               # 源文档
```

### ontology.yaml 示例

```yaml
name: drone
description: "公路交通应急处置与无人机侦测"

objects:
  Bridge:
    kind: entity
    summary: "桥梁"
    properties:
      bridge_id: {type: str, required: true}
      name: {type: str}
      span_m: {type: float}

  DroneClassRule:
    kind: rule_table
    summary: "无人机分类标准(S3第2条)"
    properties:
      category: {type: str, required: true}
      max_takeoff_weight_range: {type: str}

rules:
  drone_weight_classification:
    description: "按最大起飞重量分类无人机"
    rule_type: classification
    applies_to: [Drone]
    result_field: category
    conditions:
      - {field: max_takeoff_weight_kg, operator: lte, value: 0.25, result: "微型"}
      - {field: max_takeoff_weight_kg, operator: lte, value: 7, result: "轻型"}
      - {field: max_takeoff_weight_kg, operator: lte, value: 25, result: "小型"}

workflows:
  emergency_response:
    description: "公路交通应急处置全流程"
    trigger: "灾情发生或接报"
    steps:
      - {name: 无人机侦测, function: plan_recon_mission, next: 设施检查}
      - {name: 设施检查, function: inspect_facility, next: 事件评估}
      - name: 通行评估
        function: evaluate_traffic
        next: {通过: 信息报送, 不通过: 绕行方案}

functions:
  inspect_facility:
    summary: "对设施进行检查评估"
    group: "检查与评估"
    function_type: business
    writes_to: [FacilityInspection]
    params:
      event_id: {type: str}
      facility_type: {type: str}
      facility_id: {type: str}

links:
  disaster_has_inspections:
    source: DisasterEvent
    target: FacilityInspection
    join: {source_key: event_id, target_key: event_id}
```

## 已有领域

| 领域 | 说明 | Objects | Functions | Rules | Workflows |
|---|---|---|---|---|---|
| **drone** | 公路应急 + 无人机侦测 | 42 | 53 | 4 | 3 |
| **road_emergency** | 公路交通应急抢通 | 42 | 53 | 0 | 0 |
| **fee** | 高速公路费率管理 | 6 | 8 | 0 | 0 |
| **hv_access** | 高压接入方案设计 | 5 | 6 | 0 | 0 |

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/d/{domain}/agent/chat` | POST | 对话（同步） |
| `/d/{domain}/agent/chat/stream` | GET | 对话（SSE 流式） |
| `/d/{domain}/agent/confirm` | POST | 确认写操作 |
| `/d/{domain}/agent/history` | GET | 会话历史 |
| `/d/{domain}/schema` | GET | 完整本体 |
| `/d/{domain}/schema/objects` | GET | 对象列表（含 kind） |
| `/d/{domain}/schema/rules` | GET | 规则列表 |
| `/d/{domain}/schema/workflows` | GET | 工作流列表 |
| `/d/{domain}/schema/functions` | GET | 函数列表 |
| `/d/{domain}/query` | POST | 直接查询 |
| `/d/{domain}/function/{name}` | POST | 直接调用函数 |
| `/d/{domain}/audit` | GET | 审计日志 |
| `/domains` | GET | 所有领域列表 |

## 项目结构

```
mypalantir/
├── oag/                    # 核心框架（~6200 行 Python）
│   ├── schema.py           # 元模型定义（v2: objects/links/functions/rules/workflows）
│   ├── harness.py          # Harness 层（权限/截断/审计/缓存/Stop hook）
│   ├── agent.py            # Agent Loop（动态工具调用循环）
│   ├── orchestrator.py     # 编排器（路由到 Agent）
│   ├── hooks.py            # Hook 系统（pre/post_tool_call + 业务校验）
│   ├── context.py          # 上下文管理（token 估算/自动压缩）
│   ├── rules.py            # 规则引擎（声明式规则→确定性函数）
│   ├── worker.py           # Worker 多智能体（并行子任务）
│   ├── events.py           # 事件类型定义
│   ├── store.py            # SQLite 数据层
│   ├── registry.py         # 函数注册表
│   ├── loader.py           # 领域加载器
│   ├── api.py              # FastAPI 服务
│   ├── cli.py              # Click CLI
│   ├── planner.py          # Planner（保留，当前未启用）
│   ├── executor.py         # Executor（保留，当前未启用）
│   ├── reviewer.py         # Reviewer（能力已迁移到 hook）
│   ├── static/index.html   # 前端（单文件，含动态时间线 + Worker 卡片）
│   └── distiller/          # Distiller（文档→本体提取 pipeline）
├── domains/                # 领域目录
│   ├── drone/              # 公路应急 + 无人机（v2 元模型）
│   ├── road_emergency/     # 公路应急（v1）
│   ├── fee/                # 费率管理
│   └── hv_access/          # 高压接入
└── .env                    # 环境配置
```

## 设计思想

OAG v2 的架构设计借鉴了 Claude Code（Anthropic 的 CLI agent，51 万行 TypeScript）的核心理念：

1. **Harness > LLM** — LLM 是不可信的决策者，harness 做一切确定性工作
2. **动态 > 静态** — Agent loop 天然支持动态分支，不做预先规划
3. **元信息驱动运行时** — `writes_to`/`kind`/`function_type` 不是装饰，是权限/缓存/调度的控制依据
4. **渐进降级** — 上下文压缩从轻到重逐级触发
5. **规则确定性** — 能用规则引擎的不用 LLM 推理

## License

MIT
