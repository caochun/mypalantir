from __future__ import annotations

import json
import re
from typing import Any, Generator

from openai import OpenAI

from .events import Event, StepDoneEvent, StepStartEvent, ToolCallEvent
from .harness import Harness
from .pipeline_types import PlanStep, StepResult

STEP_SYSTEM_PROMPT = """\
你正在执行一个多步计划的第 {step_id} 步。

## 目标
{purpose}

## 需要调用的工具
{target}

## 参数
{args_desc}

## 前置步骤结果
{context_summary}

## 可用工具
你可以调用以下工具完成本步骤。必要时先 inspect() 获取函数/对象详情，再调用目标工具。
重要：调用工具时，参数值（如 event_id、facility_id）必须使用前置步骤结果中的实际值，禁止编造 ID。
完成后直接总结本步骤的关键结果，不要回答用户的原始问题。"""

SYNTHESIZE_PROMPT = """\
你是一个领域专家助手。根据以下执行结果，用中文回答用户的问题。
回答要简洁明了，给出关键数据。注意数据单位转换（如分→元、米→公里）。

## 用户问题
{question}

## 执行结果
{results_summary}

请回答："""


class Executor:
    def __init__(self, harness: Harness, llm_client: OpenAI, model: str,
                 max_turns_per_step: int = 5):
        self.harness = harness
        self.client = llm_client
        self.model = model
        self.max_turns_per_step = max_turns_per_step

    def execute_step(self, step: PlanStep,
                     context: dict[int, StepResult]) -> StepResult:
        result = StepResult(step_id=step.step_id, target=step.target)
        for event in self.execute_step_stream(step, context):
            if isinstance(event, _StepResultEvent):
                result = event.result
        return result

    def execute_step_stream(self, step: PlanStep,
                            context: dict[int, StepResult]) -> Generator[Event, None, StepResult]:
        resolved_args = self._resolve_refs(step.args, context)
        context_summary = self._build_context_summary(step.depends_on, context)

        system = STEP_SYSTEM_PROMPT.format(
            step_id=step.step_id,
            purpose=step.purpose,
            target=step.target,
            args_desc=json.dumps(resolved_args, ensure_ascii=False, default=str),
            context_summary=context_summary or "(无前置步骤)",
        )

        tools = self.harness.build_tools()
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"请执行: {step.target}({json.dumps(resolved_args, ensure_ascii=False, default=str)})"},
        ]

        last_tool_result: Any = None
        for _ in range(self.max_turns_per_step):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=0.1,
            )

            msg = response.choices[0].message

            if msg.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    tool_result = self.harness.execute_tool(
                        tc.function.name, args, confirmed=True,
                    )

                    yield ToolCallEvent(
                        name=tc.function.name,
                        args=args,
                        result=tool_result.content[:200],
                        step_id=step.step_id,
                    )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result.content,
                    })
                    try:
                        last_tool_result = json.loads(tool_result.content)
                    except (json.JSONDecodeError, TypeError):
                        last_tool_result = tool_result.content
                continue

            note = msg.content or ""
            yield _StepResultEvent(result=StepResult(
                step_id=step.step_id,
                target=step.target,
                output=last_tool_result,
                status="success",
                note=note,
            ))
            return

        yield _StepResultEvent(result=StepResult(
            step_id=step.step_id,
            target=step.target,
            output=last_tool_result,
            status="error",
            note="达到步骤最大轮次限制",
        ))

    def synthesize(self, question: str, results: list[StepResult]) -> str:
        prompt = self._build_synthesize_prompt(question, results)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    def synthesize_stream(self, question: str,
                          results: list[StepResult]) -> Generator[str, None, None]:
        prompt = self._build_synthesize_prompt(question, results)
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def rerun_step(self, step: PlanStep, context: dict[int, StepResult],
                   suggestion: str = "") -> StepResult:
        amended_purpose = step.purpose
        if suggestion:
            amended_purpose += f"\n注意: {suggestion}"
        amended_step = PlanStep(
            step_id=step.step_id,
            action=step.action,
            target=step.target,
            args=step.args,
            purpose=amended_purpose,
            depends_on=step.depends_on,
        )
        return self.execute_step(amended_step, context)

    def _build_synthesize_prompt(self, question: str,
                                  results: list[StepResult]) -> str:
        summary_parts = []
        for r in results:
            output_str = _truncate(
                json.dumps(r.output, ensure_ascii=False, default=str), 1000
            ) if r.output else "(无输出)"
            summary_parts.append(
                f"步骤{r.step_id} [{r.target}]: {r.note}\n  结果: {output_str}"
            )
        return SYNTHESIZE_PROMPT.format(
            question=question,
            results_summary="\n\n".join(summary_parts),
        )

    def _resolve_refs(self, args: dict[str, Any],
                      context: dict[int, StepResult]) -> dict[str, Any]:
        resolved = {}
        for key, val in args.items():
            if isinstance(val, str) and val.startswith("$step_"):
                resolved[key] = self._dereference(val, context)
            else:
                resolved[key] = val
        return resolved

    def _dereference(self, ref: str, context: dict[int, StepResult]) -> Any:
        match = re.match(r"\$step_(\d+)(?:\.(.+))?", ref)
        if not match:
            return ref
        step_id = int(match.group(1))
        field = match.group(2)
        result = context.get(step_id)
        if not result or result.output is None:
            return ref
        if field and isinstance(result.output, dict):
            return result.output.get(field, ref)
        if field and isinstance(result.output, list) and result.output:
            return result.output[0].get(field, ref)
        return result.output

    def _build_context_summary(self, depends_on: list[int],
                                context: dict[int, StepResult]) -> str:
        if not depends_on:
            return ""
        parts = []
        for sid in depends_on:
            r = context.get(sid)
            if r:
                output_str = _truncate(
                    json.dumps(r.output, ensure_ascii=False, default=str), 2000
                ) if r.output else "(无)"
                parts.append(f"步骤{sid} [{r.target}]: {r.note}\n  {output_str}")
        return "\n\n".join(parts)


class _StepResultEvent:
    def __init__(self, result: StepResult):
        self.result = result


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


