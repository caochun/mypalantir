# Distiller v2 改进计划

基于 vs 域生成结果与手工 ontology 的对比分析，distiller v2 在结构设计上已接近手工质量（对象分类、函数架构、关系完整性），但在运行时可用性上仍有差距。以下是按优先级排列的改进项。

## P0: 属性回填 pass — 从函数使用场景反推缺失属性

**问题**: 规范文档描述业务规则，不描述数据接口。distiller 能提取"损伤分级标准的维度"，但提取不出"EmergencyDepot 需要 lng/lat 坐标"。导致实体缺坐标、库存对象缺 quantity/unit、队伍缺 available 状态。

**改法**: Phase 5（函数设计）之后加一轮 LLM 审查 — 遍历每个函数的参数和执行逻辑，反推其涉及的对象缺少哪些属性。例如 `dispatch_resources` 需要"按距离搜索最近储备点"，则 EmergencyDepot 必须有 lng/lat。

**同时注入元模型约定**:
- 有地理位置的实体必须有 lng/lat
- 库存类对象（Stock/Inventory）必须有 quantity 和 unit
- 人员/队伍类对象必须有 available 状态字段
- 事件/记录类对象必须有时间戳字段

**涉及文件**: `attribute.py` 或新建 `attribute_backfill.py`，`pipeline.py`（在 Phase 5 后插入）

## P0: 空间查询函数 — 从坐标属性自动推导

**问题**: 生成的 get 函数全是 `get_xxx(id)` 模式。Agent 无法按距离搜索资源（缺 `get_depots_in_range`、`get_rescue_teams_in_range`、`get_affected_facilities`），资源调度流程断裂。

**改法**: Phase 5 prompt 加元规则 — "如果 A 类实体有 lng/lat 属性，除 `get_xxx(id)` 外还应生成 `get_xxx_in_range(lng, lat, radius_km)` 空间搜索函数；如果实体有 parent_id 类外键，应生成 `get_xxx_by_parent(parent_id)` 批量查询函数"。

**涉及文件**: `prompts.py`（FUNCTION_DESIGN_PROMPT 增加规则）

## P1: 工作流粒度 — 决策分支独立成步骤

**问题**: Phase 1 工作流分析把方案评分（score_plans）、绕行方案（generate_detour）、次生灾害监测（monitor_secondary_disaster）归到了其他步骤的子逻辑里，没有独立成步骤。导致 Phase 2 推导不出对应的 C 类对象和业务函数。

**改法**: Phase 1 prompt 增加规则:
- "决策分支应独立成步骤" — 如"当 III 级且无法抢通时生成绕行方案"是独立步骤
- "并行活动独立建模" — 监测、管制是与主流程并行的活动，不是子步骤
- "评估/评分是独立步骤" — 方案评分（时效40%+安全30%+经济30%）应独立

**涉及文件**: `prompts.py`（WORKFLOW_ANALYSIS_PROMPT 增加规则）

## P1: C 类过程对象查漏

**问题**: 缺 DetourPlan、SecondaryDisasterMonitoring、TrafficControl 三个在规范中有明确章节支撑的过程对象。

**改法**: 与上一条同源。Phase 1 工作流粒度改进后，Phase 2 应能自动推导出这些对象。另外在 Phase 7 质量检查中增加: "规范中有独立章节描述的业务活动，应有对应的 C 类过程对象"。

**涉及文件**: `prompts.py`, `assemble.py`（质量检查增加规则）

## P2: Hint 章节引用精确度

**问题**: 生成版 hint 的 R1/R2/R3 结构化格式好，但规则引用不够具体（如缺少"6.2.5条"、"7.2.5条1"这样的精确引用）。手工版在这方面更强。

**改法**: Phase 6 prompt 强调"hint 中引用规则时必须标注具体章节号和条款号"。同时在 `_select_relevant_content` 中优先选择含章节号的 chunk。

**涉及文件**: `prompts.py`（RULE_EXTRACTION_PROMPT）, `rule.py`
