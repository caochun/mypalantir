from __future__ import annotations

import json
import re

from openai import OpenAI

from .pipeline_types import ReviewResult, StepResult
from .registry import FunctionRegistry
from .schema import Ontology

REVIEW_PROMPT = """\
你是一个业务规则审查专家。请审查以下函数执行结果是否符合业务规则。

## 函数信息
函数名: {function_name}
函数说明: {function_description}

## 执行规则 (hint)
{hint}

## 执行结果
{result}

## 前置步骤结果（供参考）
{context}

## 审查要点
1. 结果是否符合 hint 中描述的规则逻辑？
2. 必填字段是否齐全？
3. 数值是否在合理范围内？
4. 决策依据是否充分？

输出 JSON:
```json
{{
  "passed": true 或 false,
  "issues": ["问题描述（如有）"],
  "suggestion": "建议重做方式（如果 passed=false）"
}}
```

请输出 JSON："""


class Reviewer:

    def __init__(self, ontology: Ontology, registry: FunctionRegistry,
                 llm_client: OpenAI, model: str):
        self.ontology = ontology
        self.registry = registry
        self.client = llm_client
        self.model = model

    def should_review(self, target: str) -> bool:
        fdef = self.registry.get_def(target)
        if not fdef:
            return False
        if fdef.function_type == "business":
            return True
        if fdef.hint and len(fdef.hint) > 50:
            return True
        return False

    def review(self, step_result: StepResult,
               prior_context: str = "") -> ReviewResult:
        fdef = self.registry.get_def(step_result.target)
        if not fdef:
            return ReviewResult(step_id=step_result.step_id, passed=True)

        result_str = json.dumps(step_result.output, ensure_ascii=False, default=str) if step_result.output else "(无输出)"

        prompt = REVIEW_PROMPT.format(
            function_name=step_result.target,
            function_description=fdef.description or fdef.summary,
            hint=fdef.hint or "(无 hint)",
            result=result_str[:3000],
            context=prior_context[:2000] or "(无前置步骤)",
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=512,
            )
            text = response.choices[0].message.content or ""
            data = _parse_json(text)

            return ReviewResult(
                step_id=step_result.step_id,
                passed=data.get("passed", True),
                issues=data.get("issues", []),
                suggestion=data.get("suggestion", ""),
            )
        except Exception:
            return ReviewResult(step_id=step_result.step_id, passed=True)


def _parse_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
