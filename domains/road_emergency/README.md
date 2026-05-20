# road_emergency — 公路交通应急处置（含无人机侦测）

> OAG 框架下"基础设施应急 + 无人机全生命周期 + 法规合规"的声明式本体实现。

## 1. 业务背景

公路交通突发事件（自然灾害/交通事故）发生后，需要快速完成灾情侦测、设施检查、损伤评估、抢通方案制定、资源调度和交通管制。无人机作为应急侦测的核心手段，其出动受《无人驾驶航空器飞行管理暂行条例》(S3)和《民用无人驾驶航空器运行安全管理规则》(S4/CCAR-92)约束。

本域将上述全链路建模为 OAG 本体，让 LLM 在结构化世界模型上自主规划工具调用，确定性计算产出方案。

规范依据：
- 《公路交通应急处置技术规范》(JTG XXX—XXXX)
- 《公路交通应急抢通技术规程》(JTG/T 6410—2025)
- 《交通运输综合应急预案》等 5 项(2026)
- 《无人驾驶航空器飞行管理暂行条例》(国务院令第 761 号)
- 《民用无人驾驶航空器运行安全管理规则》(CCAR-92)

## 2. 文件结构

```
domains/road_emergency/
├── README.md                    本文件
├── ontology.yaml                本体定义: 50 对象 + 15 link + 55 函数
├── prompts.json                 5 组 18 个示例场景
├── data/                        34 个 JSON 数据文件
│   ├── 基础设施(7): road_segment/bridge/tunnel/emergency_depot/rescue_team/equipment_stock/material_stock
│   ├── 无人机资产(4): drone/drone_operator/drone_base/airspace_zone
│   ├── 应急规则(10): damage_grade_standard/event_level_standard/clearance_technique_rule/...
│   ├── 无人机法规(9): drone_class_rule/operator_license_rule/airspace_rule/s3_regulation(63条)/s4_regulation(56条)/...
│   ├── 预警(2): weather_warning/defense_response_level_rule
│   └── 事件(2): disaster_event(3条)/accident_event(2条)
└── functions/                   16 个 Python 文件
    ├── __init__.py              注册中心 + 数据装载映射
    ├── interfaces.py            接口包装(mock): 基础设施/无人机/预警查询
    ├── _helpers.py              共享工具: parse_csv/get_event_detail/next_id
    ├── lookups.py               19 个规则查询函数
    ├── inspect.py               设施现场检查评估
    ├── assess.py                事件等级综合评估
    ├── plan.py                  抢通方案生成
    ├── score.py                 方案三维评分
    ├── dispatch.py              资源调度
    ├── control.py               交通管制
    ├── evaluate.py              通行评估
    ├── detour.py                绕行方案
    ├── recon.py                 无人机侦测任务(规划/调派/数据采集)
    ├── compliance.py            合规检查/飞行审批/空域冲突
    ├── patrol.py                日常巡检排班
    ├── maintenance.py           无人机维护记录
    ├── warning.py               防御响应/巡检加密
    ├── report.py                灾情信息报告(首报/续报/终报)
    └── airspace_coord.py        多部门空域协调
```

## 3. 本体的分层架构

ontology.yaml 中的 50 个对象按数据来源分为三层：

```
┌─ 外部接口对象(12 个) ────────── 外部接口数据，框架建空表，所有查询走 get_xxx 函数
│  公路: RoadSegment, Bridge, Tunnel, EmergencyDepot, RescueTeam, EquipmentStock, MaterialStock
│  无人机: Drone, DroneOperator, DroneBase, AirspaceZone
│  预警: WeatherWarning
└──────────────────────────────

┌─ 业务规则对象(20 个) ────────── 稳定配置数据，落库可 query 也可 lookup_*
│  应急规则(10): DamageGradeStandard, EventLevelStandard, ClearanceTechniqueRule,
│               TrafficControlRule, TunnelImportanceLevel/DifficultyMatrix/TargetMatrix,
│               BridgeTypeSelection, ResponseLevelRule, DefenseResponseLevelRule
│  无人机法规(9): DroneClassRule, OperatorLicenseRule, OperationClassRule, AirspaceRule,
│               FlightApprovalRule, EmergencyFlightRule, PreflightCheckRule,
│               DroneMaintenanceRule, PayloadTypeRule
│  法规原文(2): S3Regulation(63条), S4Regulation(56条)
└──────────────────────────────

┌─ 业务过程对象(18 个) ────────── 智能体推理产物，落库供查询/审计
│  事件: DisasterEvent, AccidentEvent
│  应急处置: FacilityInspection, ClearancePlan, ResourceDispatch,
│           TrafficControl, TrafficEvaluation, DetourPlan
│  无人机侦测: ReconMission, FlightApproval, ComplianceCheck, ReconData,
│             PatrolSchedule, AirspaceConflict, DroneMaintenanceLog
│  预警报告: DefenseResponse, EventReport, AirspaceCoordination
└──────────────────────────────
```

## 4. 关键建模决策

### 4.1 DisasterEvent / AccidentEvent 拆分

最初设计为单一 `EmergencyEvent`，用 `event_type` 字段（自然灾害/交通事故）区分。后发现字段值决定了整条处理路径：

- 自然灾害：需要 inspect_facility、plan_recon_mission、generate_clearance_plans
- 交通事故：不涉及设施检查，关注事故清障

这是典型的"运行时约束 → 结构约束"反模式（同 hv_access 的 AccessRequest/ExpandRequest 拆分）。

拆分后：
- `DisasterEvent`: disaster_type(地震/暴雨/泥石流/滑坡等), affected_segment_ids
- `AccidentEvent`: accident_type(抛锚/碰撞/翻车等), vehicle_type, cargo_type, casualty_info

`get_event` 搜索双表，返回 `event_type` 字段。`plan_recon_mission` 在函数内部直接拒绝 AccidentEvent——类型约束由 schema 强制，不依赖 LLM 判断。

### 4.2 声明式建模——无流程编排

本体中**不包含任何流程描述**。LLM 从函数的输入/输出语义自行推断调用顺序。

数据依赖通过两种方式表达：

1. **函数 description** 声明"我需要什么输入、我产出什么输出"：
   - `inspect_facility`: "写入 FacilityInspection。当存在 ReconData 时检查精度更高"
   - `generate_clearance_plans`: "根据 FacilityInspection 记录...生成候选 ClearancePlan"
   - `dispatch_resources`: "根据已评分的 ClearancePlan(需有 total_score)..."

2. **对象 description** 声明"谁产出我、谁消费我"：
   - `FacilityInspection`: "inspect_facility 产出。generate_clearance_plans、set_traffic_control、assess_event_level 以本记录为输入"
   - `ClearancePlan`: "generate_clearance_plans 产出，score_plans 评分，dispatch_resources 和 evaluate_traffic 以本记录为输入"

LLM 从这些**双向声明**中自行推断出：recon → inspect → plans → score → dispatch → evaluate。

### 4.3 业务策略写在被约束方

遵循 hv_access 的关键经验：跨函数的业务约束，写在被约束的函数/对象自身的 description 上。

例如：
- "交通事故不需要无人机侦测"写在 `AccidentEvent.description` 和 `plan_recon_mission` 内部逻辑
- "dispatch_drone 需要 ComplianceCheck 通过且 FlightApproval 已批准"写在 `dispatch_drone.description`
- "应急抢险任务适用快速审批"写在 `FlightApproval.description`

### 4.4 无人机法规作为规则表

S3 暂行条例(63 条)和 S4 CCAR-92(56 条关键条目)完整入库为 `S3Regulation` 和 `S4Regulation` 对象，LLM 可按条号或关键词查询原文。

同时提取了 9 张结构化规则表（DroneClassRule, OperatorLicenseRule 等），支持 `check_compliance` 等函数做确定性校验。

### 4.5 预警与预案衔接

气象预警(WeatherWarning)与交通应急预案(S1)通过三个函数衔接：
- `trigger_defense_response`: 预警级别 → 防御响应级别(规则表 DefenseResponseLevelRule)
- `intensify_patrol`: 受影响路段 → 巡检频率提升
- `generate_event_report`: 首报基于 ReconData 快速生成，符合 S1 "首报要快"要求

### 4.6 渐进式披露

system prompt 只渲染每个对象/函数的 `summary`（一行），完整定义通过：
- `inspect` 元工具主动查看
- 首次调用函数时自动注入 `hint`（详细规则）
- 结果含 `*_type` 字段时自动注入对象 description

## 5. 数据依赖图

以自然灾害事件为例，LLM 可从对象间的输入/输出关系推断出的调用链路：

```
WeatherWarning ─── trigger_defense_response ──→ DefenseResponse
       │                                              │
       └── intensify_patrol ──→ PatrolSchedule         │
                                                       ↓
DisasterEvent ─── plan_recon_mission ──→ ReconMission
       │                                    │
       │              check_compliance ──→ ComplianceCheck
       │              request_flight_approval ──→ FlightApproval
       │              check_airspace_conflict ──→ AirspaceConflict
       │              dispatch_drone (需 ComplianceCheck通过 + FlightApproval已批准)
       │              collect_recon_data ──→ ReconData
       │                                        │
       │    inspect_facility (当存在 ReconData 时精度更高) ──→ FacilityInspection
       │                                                          │
       │    assess_event_level ←── FacilityInspection             │
       │    set_traffic_control ←── FacilityInspection ──→ TrafficControl
       │    generate_clearance_plans ←── FacilityInspection ──→ ClearancePlan
       │                                                          │
       │    score_plans ──→ 更新 ClearancePlan.total_score        │
       │    dispatch_resources (需 total_score) ──→ ResourceDispatch
       │    evaluate_traffic (需 ResourceDispatch) ──→ TrafficEvaluation
       │    generate_detour (III级+无可行方案) ──→ DetourPlan
       │
       └── generate_event_report ──→ EventReport
              首报: ReconData
              续报: FacilityInspection + ClearancePlan
              终报: TrafficEvaluation + TrafficControl

AccidentEvent ─── set_traffic_control ──→ TrafficControl
       │
       └── generate_event_report ──→ EventReport
```

注意：这张图**不在 ontology 中**，是从对象/函数的 description 自动推导出来的。LLM 也能做同样的推导。

## 6. 测试场景

| 场景 | 事件 | 预期行为 |
|---|---|---|
| G318 滑坡处置 | E001 DisasterEvent | recon → inspect → plans → dispatch |
| 大桥地震损伤 | E002 DisasterEvent | recon(激光雷达) → 桥涵三维检查 |
| 隧道泥石流 | E003 DisasterEvent | recon → 隧道评估矩阵 → 抢通目标 |
| 重卡翻车 | A001 AccidentEvent | 不走 inspect/recon，直接 traffic_control |
| 货物散落 | A002 AccidentEvent | traffic_control + 清障 |
| 暴雨预警 | WW001 | defense_response → intensify_patrol |
| 红色预警 | WW002 | 一级防御 → 无人机前置 |

LLM 行为验证要点：
- E001: 自主走完 recon → inspect → plans 链路
- A001: 看到 `event_type=AccidentEvent` 后不调 inspect_facility
- WW001: 触发防御响应和巡检加密
- 合规检查: 自动校验载荷兼容性，不合格时选择替代无人机

## 7. 启动与使用

```bash
# 多域模式（同时服务 fee/hv_access/road_emergency）
oag serve
# 访问 http://localhost:18000/d/road_emergency/

# 单域模式
DOMAIN=domains/road_emergency oag serve

# 命令行
DOMAIN=domains/road_emergency oag chat
DOMAIN=domains/road_emergency oag info
DOMAIN=domains/road_emergency oag call get_event event_id=E001
```

## 8. 关键洞察

1. **类型分派 > 字段分派**：DisasterEvent/AccidentEvent 的拆分让 LLM 从类型名直接识别处理路径，比看 `event_type` 字符串值更可靠
2. **数据依赖双向声明**：对象说"谁产出我/谁消费我"，函数说"我需要什么/我产出什么"——LLM 从任一方向都能推断链路
3. **业务策略绑在被约束方**：`plan_recon_mission` 自己拒绝 AccidentEvent，不靠全局流程图告诉 LLM "事故不需要侦测"
4. **法规即规则表**：S3/S4 的 119 条原文入库可查，同时提取为 9 张结构化规则表供函数做确定性校验
5. **渐进式披露**：50 个对象 + 55 个函数的完整定义不会一次性灌入 LLM，summary 缩短默认 prompt，hint 按使用自动浮出
6. **载荷兼容性是函数内部逻辑**：`plan_recon_mission` 自动按载荷过滤无人机，不依赖 LLM 在外部做判断——函数内部的业务逻辑不应该暴露给 LLM 去编排
