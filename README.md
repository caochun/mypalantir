# MyPalantir

MyPalantir 是一个基于 OAG（Ontology Augmented Generation）的多领域智能体应用。
根项目负责把 OAG Agent 运行时、领域数据、HTTP API、CLI 和静态 Web 页面组装起来；
核心 Agent 引擎位于 `agent` 子项目，领域模型与数据位于 `domains` 子项目。

OAG 的核心思想是：让 LLM 在结构化本体上规划工具调用，由确定性代码执行查询、规则、
工作流和业务函数。LLM 负责“下一步做什么”，runtime 负责“事情怎么可靠地做”。

```text
用户 / Web / CLI
  -> FastAPI / CLI
  -> OAG Agent
  -> Harness
  -> LLM 选择工具
  -> 工具执行管线
  -> ObjectRepository / RuleEngine / Workflow / 业务函数
  -> 工具结果回到 LLM
  -> 最终回答或继续调用工具
```

## 仓库组成

```text
mypalantir/
  app/
    api.py              # FastAPI 应用工厂，多领域挂载
    cli.py              # oag 命令行入口
  static/
    home.html           # 多领域首页
    index.html          # 单领域对话与 schema 页面
  tests/                # 根项目集成测试
  docs/                 # 设计和进展文档
  agent/                # OAG Agent 运行时子项目
  domains/              # 领域模型、数据和业务函数子项目
    tools/ontology_builder/
                         # 从业务文档生成 ontology.yaml 的维护工具
  claude-code/          # 设计参考子模块
  pyproject.toml
  uv.lock
```

`agent`、`domains` 和 `claude-code` 是 git submodule。首次克隆建议使用：

```bash
git clone --recurse-submodules git@github.com:caochun/mypalantir.git
cd mypalantir
```

如果已经克隆但没有拉取子模块：

```bash
git submodule update --init --recursive
```

## 快速开始

### 1. 环境要求

- Python 3.11+
- `uv`
- 一个 OpenAI 兼容的 LLM API

### 2. 安装依赖

```bash
uv sync
```

根项目通过 `pyproject.toml` 以 editable 方式引用本地 `agent` 子项目：

```toml
[tool.uv.sources]
oag = { path = "./agent", editable = true }
```

### 3. 配置 LLM

在根目录创建 `.env`：

```env
LLM_API_KEY=sk-placeholder
LLM_API_URL=http://localhost:8090/v1
LLM_MODEL=qwen3.5-plus
```

可选配置：

```env
# 单领域模式使用；不设置时默认挂载 domains/ 下所有领域
DOMAIN=domains/hv_access
```

### 4. 启动服务

多领域模式：

```bash
uv run oag serve --port 18000
```

单领域模式：

```bash
DOMAIN=domains/hv_access uv run oag serve --port 18000
```

访问：

- 多领域首页：`http://localhost:18000/`
- 单领域页面：`http://localhost:18000/d/hv_access/`

### 5. CLI

交互式对话：

```bash
DOMAIN=domains/hv_access uv run oag chat
```

查看领域信息：

```bash
DOMAIN=domains/hv_access uv run oag info
```

直接调用领域函数：

```bash
DOMAIN=domains/hv_access uv run oag call get_access_points lng=121.47 lat=31.23 radius_m=1000
```

## 领域系统

每个领域目录至少包含：

```text
domains/{domain}/
  ontology.yaml
  data/
  functions/
    __init__.py
  prompts.json
```

`ontology.yaml` 描述对象、关系、函数、规则、工作流和对象数据源。`functions/` 负责把
YAML 中声明的函数绑定到 Python 实现，并按需注册 resolver 或自定义 adapter。`data/`
存放 JSON、SQLite 数据库或其他领域私有数据文件。

当前仓库包含这些领域：

| 领域 | 路径 | 说明 |
|---|---|---|
| `drone` | `domains/drone` | 公路应急与无人机侦测 |
| `hv_access` | `domains/hv_access` | 高压接入方案设计 |
| `fee` | `domains/fee` | 高速公路费率计算 |
| `icf` | `domains/icf` | ICF 相关领域模型 |

## API

多领域模式下，每个领域挂载在 `/d/{domain}` 下。

| Endpoint | Method | 说明 |
|---|---|---|
| `/` | GET | 多领域首页 |
| `/domains` | GET | 已挂载领域列表 |
| `/d/{domain}/` | GET | 单领域页面 |
| `/d/{domain}/prompts` | GET | 示例问题 |
| `/d/{domain}/schema` | GET | 完整 ontology |
| `/d/{domain}/schema/objects` | GET | 对象列表 |
| `/d/{domain}/schema/functions` | GET | 函数列表 |
| `/d/{domain}/schema/rules` | GET | 规则列表 |
| `/d/{domain}/schema/workflows` | GET | 工作流列表 |
| `/d/{domain}/query` | POST | 直接查询对象实例 |
| `/d/{domain}/function/{name}` | POST | 直接调用领域函数 |
| `/d/{domain}/agent/chat` | POST | Agent 同步对话 |
| `/d/{domain}/agent/chat/stream` | GET | Agent SSE 流式对话 |
| `/d/{domain}/agent/confirm` | POST | 确认或拒绝待确认工具 |
| `/d/{domain}/agent/history` | GET | 会话历史或会话列表 |
| `/d/{domain}/audit` | GET | 工具审计日志 |

示例：

```bash
curl -X POST http://localhost:18000/d/hv_access/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"帮我查询 R001 的接入方案"}'
```

SSE 示例：

```bash
curl -N 'http://localhost:18000/d/hv_access/agent/chat/stream?session_id=demo&message=查询变电站'
```

## Repository / Adapter 数据访问

OAG 不再把领域对象默认导入本地兼容 Store。`load_domain()` 会创建
`ObjectRepository`，它根据每个对象的 `source.type` 路由数据访问：

- `json_file`：每次查询直接读取领域目录下的 JSON 文件，适合 hv_access 这类本地 JSON 数据。
- `sqlite_table`：访问已有 SQLite 数据库表或视图，不建表、不导入。
- `resolver`：对象级自定义查询逻辑，适合多表聚合、HTTP API、算法结果或跨系统组合视图。
- 自定义 adapter：领域函数包可通过 `registry.register_adapter()` 扩展一类数据源。

领域业务函数接收的是 `repository`，通过 `query`、`query_by_id`、`insert_record`、
`update_record` 等统一接口访问对象。数据源实现只负责读写数据；可变性、状态流转、
工具确认和审计仍由 Agent runtime 的工具执行管线处理。

## 根项目架构

根项目是应用装配层，主要负责三件事：

1. 加载一个或多个领域。
2. 为每个领域创建 OAG Agent 和 FastAPI 子应用。
3. 暴露统一的 HTTP、SSE、CLI 和静态页面入口。

```text
app.cli
  -> 读取 .env
  -> 选择单领域或多领域模式
  -> 调用 app.api.create_app/create_multi_app
  -> uvicorn.run()

app.api
  -> load_domain(domain_dir)
  -> OpenAI client
  -> Harness + Agent
  -> FastAPI routes
  -> static/index.html
```

`agent` 子项目内部承担真正的智能体 runtime：

- prompt 分层装配
- tool schema 构建与缓存
- 工具输入校验
- 工具执行超时与取消语义
- 大工具结果持久化
- 历史协议自检与修复
- 上下文压缩
- 用户确认流程
- 工具错误与最终回答一致性检查
- worker/subagent 执行

更详细的 Agent 架构见 [agent/README.md](agent/README.md)。

`domains/tools/ontology_builder` 提供领域构建工具。根项目保留 `oag distill`
命令作为入口，用于从业务文档半自动生成领域 ontology。

## OAG 运行模型

OAG 和传统 RAG 的重点不同：

- RAG 常见路径是“检索文本 -> 让 LLM 总结”。
- OAG 的路径是“结构化本体 -> LLM 选择工具 -> 确定性 runtime 执行 -> LLM 整合结果”。

这带来几个约束：

- 规则应写成可执行规则，而不是让模型自由推理。
- 写操作必须经过策略管线；是否需要用户确认由工具策略、对象来源和可变性共同决定。
- 工具结果需要可审计、可缓存、可截断或落盘。
- 会话历史必须满足 OpenAI tool-call 协议。
- 大 ontology 默认只注入摘要，详情通过 `inspect` 按需获取。

## 开发命令

运行根项目测试：

```bash
uv run pytest
```

运行 agent 子项目测试：

```bash
cd agent
uv run pytest
uv run python -m compileall -q oag
```

查看当前 submodule 指针：

```bash
git submodule status
```

更新 submodule：

```bash
git submodule update --init --recursive
```

## 文档

- [agent/README.md](agent/README.md)：OAG Agent runtime 架构和使用方式。
- [domains/README.md](domains/README.md)：领域库维护说明。
- [domains/metamodel-spec.md](domains/metamodel-spec.md)：OAG 本体元模型规范。
- [domains/modeling-guide.md](domains/modeling-guide.md)：从业务文档到 ontology 的建模指南。
- [docs/ontology-for-llm-research.md](docs/ontology-for-llm-research.md)：Ontology for LLM 研究笔记。
- [docs/domain-distiller-design.md](docs/domain-distiller-design.md)：领域构建工具设计。
- [docs/progress.md](docs/progress.md)：项目进展。
- [docs/todo.md](docs/todo.md)：后续任务。

## 常见问题

### 服务启动后没有领域

确认 `domains` 子模块已初始化，并且每个领域目录下有 `ontology.yaml`：

```bash
git submodule update --init --recursive
find domains -maxdepth 2 -name ontology.yaml
```

### 单领域页面路径是什么

多领域模式下使用 `/d/{domain}/`，例如：

```text
http://localhost:18000/d/hv_access/
```

单领域模式下根路径 `/` 就是该领域页面。

### 写操作为什么需要确认

OAG 把写入和业务副作用放在工具策略管线里处理，但不会简单地“一有写入就确认”。
`mutate create` 写入 `data_source: agent_generated` 且 `mutability: append_only` 的对象时，
可以作为 Agent 生成的中间产物直接执行；`writes_to` 全部指向这类对象的领域函数也可以
跳过确认。

写入可变对象、更新或删除、写入人工/外部来源对象、破坏性操作、未知写入目标以及部分
用户交互工具仍会触发确认。前端或调用方需要调用 `/agent/confirm` 继续或拒绝。

### 如何新增领域

1. 在 `domains/{name}` 创建 `ontology.yaml`。
2. 在 `functions/__init__.py` 注册 Python 函数。
3. 可选：在 `data/` 放初始化 JSON 数据。
4. 运行 `DOMAIN=domains/{name} uv run oag info` 检查加载结果。
5. 运行 `DOMAIN=domains/{name} uv run oag serve --port 18000` 启动单领域服务。
