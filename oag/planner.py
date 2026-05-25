from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .pipeline_types import Plan, PlanStep
from .registry import FunctionRegistry
from .schema import FunctionDef, Ontology

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

## 规划规则
1. 业务函数（business 类型）调用前，确保其 depends_on 中的函数已执行
2. 需要查规则时，先调 lookup 函数
3. 需要查实体数据时，先调 get 函数
4. 每步标注 purpose（执行器需要知道为什么做这步）
5. args 中可以用 "$step_N.字段名" 引用前面步骤的结果
6. 如果某个参数需要从前面步骤的结果中获取但你不确定具体字段名，用 "$step_N" 让执行器自行判断

## 用户问题
{question}

输出 JSON:
```json
{{
  "reasoning": "规划推理过程",
  "steps": [
    {{
      "step_id": 1,
      "action": "call_function",
      "target": "函数名",
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
            text = text.strip()
            if "complex" in text:
                return "complex"
            return "simple"
        except Exception:
            return "simple"

    def plan(self, question: str) -> Plan:
        prompt = PLAN_PROMPT.format(
            domain_description=self.ontology.description,
            objects_summary=self._objects_summary(),
            functions_summary=self._functions_summary(),
            links_summary=self._links_summary(),
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

    def _objects_summary(self) -> str:
        lines = []
        for name, obj in self.ontology.objects.items():
            line = (obj.summary or obj.description or "").strip().split("\n")[0]
            lines.append(f"- {name}: {line}")
        return "\n".join(lines)

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
            param_names = list(fdef.params.keys())
            if param_names:
                parts.append(f" params: {', '.join(param_names)}")
            lines.append("".join(parts))
        return "\n".join(lines)

    def _links_summary(self) -> str:
        if not self.ontology.links:
            return "(无关系)"
        lines = []
        for lname, ldef in self.ontology.links.items():
            lines.append(
                f"- {lname}: {ldef.source} → {ldef.target} "
                f"({ldef.join['source_key']} = {ldef.join['target_key']})"
            )
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
