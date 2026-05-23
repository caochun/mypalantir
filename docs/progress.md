# Domain Distiller Progress

## 当前状态

Pipeline 已实现 Phase 0-6，在 drone 域上完成了端到端测试。

### 已完成

- Phase 0: 文档准备 + 语篇分析（discourse analysis）
- Phase 1: 概念发现（三类对象：entity/rule/process）
- Phase 2: 属性丰富
- Phase 3: 关系发现
- Phase 4: 函数发现
- Phase 5: 规则提取 + Prompt 优化
- Phase 6: 组装 ontology + 模板函数自动生成

### 各域状态

| 域 | ontology 产出方式 | 当前状态 |
|---|---|---|
| fee | 手工 | 已上线 |
| hv_access | 手工 | 已上线 |
| road_emergency | Claude Code 手工提取 | 48 个对象，已上线 |
| drone | pipeline 自动 | Phase 0-6 完成（gemma 本地模型），Phase 0-1 完成（DeepSeek V4 Pro） |

## 已发现的问题

### 1. DeepSeek discourse 标注将技术标准文档全部标为 background

**现象**：用 DeepSeek V4 Pro 跑 drone 域时，Phase 0 的 discourse 分析将两篇公路技术标准文档（`公路交通应急处置技术规范.md`、`公路交通应急抢通技术规程.md`）的全部 chunk（共 193 个）标为 `background`，没有识别出任何 definition/rule/enumeration。

**对比**：同一批文档中，法规类文档（S3 暂行条例、S4 CCAR-92）的标注分布合理——rule/definition 类型占比 30-75%。

| 文档 | chunks | definition | rule | enumeration | background |
|---|---|---|---|---|---|
| S1 应急预案 | 304 | 6 | 31 | 7 | 248 |
| S3 暂行条例 | 8 | 1 | 5 | 0 | 2 |
| S4 CCAR-92 | 213 | 6 | 27 | 0 | 180 |
| 公路交通应急处置技术规范 | 97 | 0 | 0 | 0 | **97** |
| 公路交通应急抢通技术规程 | 96 | 0 | 0 | 0 | **96** |

**影响链**：
1. discourse 全标 background → `filter_chunks_by_type` 排序无效果，公路内容在概念发现 prompt 中靠后
2. Phase 1 概念发现 prompt 共 130743 字，DeepSeek 对长 prompt 后部注意力衰减
3. 最终 Phase 1 只产出 19 个对象（全部围绕无人机法规），完全丢失公路基础设施实体

**对比 gemma 本地模型**：同域 Phase 1 产出 26 个对象，覆盖了公路部分（RoadSegment/Bridge/Tunnel/EmergencyDepot 等）。

**根因分析**：
- **discourse 标注质量**：DeepSeek 对技术标准类文档（大量表格、分级条件、技术要求）的语篇类型识别存在偏差，倾向将规程/规范类内容标为 background
- **长文本注意力衰减**：13 万字 prompt 中，模型选择性忽略了非主题（公路）部分的内容

**可能的改进方向**：
- discourse prompt 增加技术标准类文档的标注示例
- 概念发现改为分文档多轮提取（类似 Schema-Miner 的逐篇迭代策略），避免单次超长 prompt
- 对 discourse 标注结果增加质量检查（如某文档全部标为同一类型时发出警告）

## Token 用量记录

| 模型 | 域 | 阶段 | prompt tokens | completion tokens |
|---|---|---|---|---|
| DeepSeek V4 Pro | drone | Phase 0-1 | 188,041 | 68,980 |
