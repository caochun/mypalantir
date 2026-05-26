from __future__ import annotations

import json
import re

from openai import OpenAI

from .pipeline_types import Plan, PlanStep
from .registry import FunctionRegistry
from .schema import Ontology

SIMPLE_KEYWORDS = {"查一下", "查询", "多少", "有哪些", "列出", "什么是", "解释"}
COMPLEX_KEYWORDS = {
    "制定方案", "生成方案", "全流程", "调度",
    "检查并", "评估并",
}
COMPLEX_CONNECTORS = re.compile(r"然后|接着|再加|同时|并且|之后")
ACTION_VERBS = re.compile(
    r"检查|评估|制定|生成|调度|启动|规划|侦测|审批|管制|巡检"
    r"|绕行|清障|评分|响应|前置|加密|通行评估|终报|首报|续报"
)

CLASSIFY_PROMPT = """\
判断以下用户问题是"简单查询"还是"多步业务流程"。

简单查询：只需要查一个对象或调一个函数就能回答。
多步业务流程：需要多个步骤、涉及多个函数或对象联动。

可用函数: {function_names}

用户问题: {question}

只输出 JSON: {{"complexity": "simple" 或 "complex"}}"""

PLAN_PROMPT = """\
你是 OAG 执行规划器。根据用户问题，规划工具调用步骤。

## 领域: {domain_description}

## 可用对象
{objects_summary}

## 可用函数（含依赖和类型）
{functions_summary}

## 关系
{links_summary}

## 可用规则
{rules_summary}

## 已定义工作流
{workflows_summary}

## 规划规则
1. 如果问题匹配已定义的工作流，直接按工作流步骤规划
2. 业务函数（business 类型）调用前，确保其 depends_on 中的函数已执行
3. 有对应规则的判断任务，使用 apply_rule 而非自行推理
4. 可并行的步骤标注 depends_on=[]，有依赖的标注所依赖的 step_id
5. args 中可以用 "$step_N.字段名" 引用前面步骤的结果
6. 重要：args 中的 event_id、facility_id 等必须使用用户问题中提到的原始 ID，禁止编造 ID
7. 涉及事件相关设施的操作（inspect_facility、set_traffic_control 等），第一步必须是 get_affected_facilities(event_id) 获取设施 ID 列表，不要直接调 get_bridge_status/get_tunnel_status（因为你不知道设施 ID）
8. 用户提到设施名称（如"龙门山隧道"）但没给 ID 时，也必须先调 get_affected_facilities 从结果中找到对应的设施 ID

## 用户问题
{question}

输出 JSON:
```json
{{
  "reasoning": "规划推理过程",
  "workflow_ref": "引用的工作流名称（如有）",
  "steps": [
    {{
      "step_id": 1,
      "action": "call_function",
      "target": "函数名或apply_rule",
      "args": {{"参数名": "值或$step_N.字段"}},
      "purpose": "这步要达成什么",
      "depends_on": []
    }}
  ]
}}
```

请输出 JSON："""


class Planner:
    def __init__(self, ontology: Ontology, registry: FunctionRegistry,
                 llm_client: OpenAI, model: str):
        self.ontology = ontology
        self.registry = registry
        self.client = llm_client
        self.model = model

    def classify(self, question: str) -> str:
        for kw in COMPLEX_KEYWORDS:
            if kw in question:
                return "complex"

        for wdef in self.ontology.workflows.values():
            if wdef.trigger and wdef.trigger in question:
                return "complex"

        action_count = len(set(ACTION_VERBS.findall(question)))
        has_connector = bool(COMPLEX_CONNECTORS.search(question))
        if action_count >= 2 and has_connector:
            return "complex"
        if action_count >= 3:
            return "complex"

        simple_count = sum(1 for kw in SIMPLE_KEYWORDS if kw in question)
        if simple_count >= 1 and len(question) < 30:
            return "simple"

        function_names = [name for name, _ in self.registry.list_functions()]
        prompt = CLASSIFY_PROMPT.format(
            function_names=", ".join(function_names),
            question=question,
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=50,
            )
            text = response.choices[0].message.content or ""
            if "complex" in text:
                return "complex"
            return "simple"
        except Exception:
            return "simple"

    def plan(self, question: str) -> Plan:
        matched = self._match_workflow(question)
        if matched:
            return matched

        prompt = PLAN_PROMPT.format(
            domain_description=self.ontology.description,
            objects_summary=self._objects_summary(),
            functions_summary=self._functions_summary(),
            links_summary=self._links_summary(),
            rules_summary=self._rules_summary(),
            workflows_summary=self._workflows_summary(),
            question=question,
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096,
        )

        text = response.choices[0].message.content or ""
        data = _parse_json(text)

        steps = []
        for s in data.get("steps", []):
            steps.append(PlanStep(
                step_id=s.get("step_id", len(steps) + 1),
                action=s.get("action", "call_function"),
                target=s.get("target", ""),
                args=s.get("args", {}),
                purpose=s.get("purpose", ""),
                depends_on=s.get("depends_on", []),
            ))

        return Plan(
            question=question,
            steps=steps,
            reasoning=data.get("reasoning", ""),
        )

    def _match_workflow(self, question: str) -> Plan | None:
        if not self.ontology.workflows:
            return None

        best_name = None
        best_wf = None
        best_score = 0

        for wname, wdef in self.ontology.workflows.items():
            if not wdef.trigger or not wdef.steps:
                continue
            triggers = []
            for sep in ["、", "或", "/"]:
                if sep in wdef.trigger:
                    triggers.extend(t.strip() for t in wdef.trigger.split(sep))
            triggers.append(wdef.trigger)
            score = 0
            for t in triggers:
                if t in question:
                    score = max(score, len(t))
            if score > best_score:
                best_score = score
                best_name = wname
                best_wf = wdef

        if not best_wf or best_score < 2:
            return None

        extracted = self._extract_ids(question)

        steps = []
        prev_id = 0
        for i, ws in enumerate(best_wf.steps):
            if not ws.function:
                continue
            step_id = i + 1
            deps = [prev_id] if prev_id > 0 else []

            args = {}
            fdef = self.registry.get_def(ws.function)
            if fdef:
                for pname in fdef.params:
                    if pname == "event_id" and extracted.get("event_id"):
                        args["event_id"] = extracted["event_id"]
                    elif pname == "facility_id" and extracted.get("facility_id"):
                        args["facility_id"] = extracted["facility_id"]
                    elif pname == "facility_type" and extracted.get("facility_type"):
                        args["facility_type"] = extracted["facility_type"]
                    elif pname == "drone_id" and extracted.get("drone_id"):
                        args["drone_id"] = extracted["drone_id"]
                    elif pname == "warning_id" and extracted.get("warning_id"):
                        args["warning_id"] = extracted["warning_id"]
                    elif pname == "mission_id" and prev_id > 0:
                        args["mission_id"] = f"$step_{prev_id}.mission_id"
                    elif pname == "plan_id" and prev_id > 0:
                        args["plan_id"] = f"$step_{prev_id}.plan_id"

            steps.append(PlanStep(
                step_id=step_id,
                action="call_function",
                target=ws.function,
                args=args,
                purpose=ws.name + (f" — {ws.description}" if ws.description else ""),
                depends_on=deps,
            ))
            prev_id = step_id

        if not steps:
            return None

        return Plan(
            question=question,
            steps=steps,
            reasoning=f"匹配工作流 [{best_name}]: {best_wf.description}",
        )

    def _extract_ids(self, question: str) -> dict:
        ids: dict[str, str] = {}
        m = re.search(r"[EeDd]\d{2,}", question)
        if m:
            ids["event_id"] = m.group(0).upper()
        m = re.search(r"[Bb]\d{2,}", question)
        if m:
            ids["facility_id"] = m.group(0).upper()
            ids["facility_type"] = "桥梁"
        m = re.search(r"[Tt]\d{2,}", question)
        if m:
            ids["facility_id"] = m.group(0).upper()
            ids["facility_type"] = "隧道"
        m = re.search(r"[Ss]\d{2,}", question)
        if m and "facility_id" not in ids:
            ids["facility_id"] = m.group(0).upper()
            ids["facility_type"] = "路段"
        m = re.search(r"DRN\d+", question, re.IGNORECASE)
        if m:
            ids["drone_id"] = m.group(0).upper()
        m = re.search(r"W\d{2,}", question)
        if m:
            ids["warning_id"] = m.group(0).upper()
        for kw, ft in [("桥梁", "桥梁"), ("桥", "桥梁"), ("隧道", "隧道"), ("路段", "路段"), ("路基", "路段")]:
            if kw in question and "facility_type" not in ids:
                ids["facility_type"] = ft
        return ids

    def _objects_summary(self) -> str:
        lines = []
        for name, obj in self.ontology.objects.items():
            kind_label = f" [{obj.kind}]" if obj.kind != "entity" else ""
            line = (obj.summary or obj.description or "").strip().split("\n")[0]
            lines.append(f"- {name}{kind_label}: {line}")
        return "\n".join(lines) or "(无)"

    def _functions_summary(self) -> str:
        lines = []
        for name, fdef in self.registry.list_functions():
            if not fdef:
                continue
            parts = [f"- {name}"]
            if fdef.function_type:
                parts.append(f"[{fdef.function_type}]")
            parts.append(f": {(fdef.summary or '').strip().split(chr(10))[0]}")
            if fdef.depends_on:
                parts.append(f" (depends_on: {', '.join(fdef.depends_on)})")
            if fdef.writes_to:
                parts.append(f" (writes_to: {', '.join(fdef.writes_to)})")
            lines.append("".join(parts))
        return "\n".join(lines) or "(无)"

    def _links_summary(self) -> str:
        if not self.ontology.links:
            return "(无)"
        lines = []
        for lname, ldef in self.ontology.links.items():
            lines.append(f"- {lname}: {ldef.source} → {ldef.target}")
        return "\n".join(lines)

    def _rules_summary(self) -> str:
        if not self.ontology.rules:
            return "(无规则，所有判断需通过函数或查询)"
        lines = []
        for rname, rdef in self.ontology.rules.items():
            applies = ", ".join(rdef.applies_to)
            lines.append(f"- {rname} [{rdef.rule_type}]: {rdef.description} (适用: {applies})")
        return "\n".join(lines)

    def _workflows_summary(self) -> str:
        if not self.ontology.workflows:
            return "(无预定义工作流)"
        lines = []
        for wname, wdef in self.ontology.workflows.items():
            steps_desc = " → ".join(s.name for s in wdef.steps)
            lines.append(f"- {wname}: {wdef.description}\n  步骤: {steps_desc}")
        return "\n".join(lines)


def _parse_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"steps": [], "reasoning": "JSON parse failed"}
