from __future__ import annotations

import json
from typing import Any, Generator

from openai import OpenAI

from .agent import Agent, ToolExecutor
from .executor import Executor
from .pipeline_types import Plan, StepResult
from .planner import Planner
from .registry import FunctionRegistry
from .reviewer import Reviewer
from .schema import Ontology
from .store import Store


class Orchestrator:

    def __init__(self, ontology: Ontology, store: Store,
                 registry: FunctionRegistry, llm_config: dict):
        self.ontology = ontology
        self.store = store
        self.registry = registry

        self.client = OpenAI(
            api_key=llm_config.get("api_key", "sk-placeholder"),
            base_url=llm_config.get("api_url", "http://localhost:8090/v1"),
        )
        self.model = llm_config.get("model", "qwen3.5-plus")

        self.agent = Agent(ontology, store, registry, llm_config)
        self.planner = Planner(ontology, registry, self.client, self.model)
        self.executor = Executor(ontology, store, registry, self.client, self.model)
        self.reviewer = Reviewer(ontology, registry, self.client, self.model)
        self.max_retries = 1

    def chat(self, message: str, session_id: str = "default") -> str:
        complexity = self.planner.classify(message)
        if complexity == "simple":
            return self.agent.chat(message, session_id)

        plan = self.planner.plan(message)
        if not plan.steps:
            return self.agent.chat(message, session_id)

        results = self._execute_with_review(plan)
        return self.executor.synthesize(plan.question, results)

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[dict, None, None]:
        complexity = self.planner.classify(message)
        if complexity == "simple":
            yield from self.agent.chat_stream(message, session_id)
            return

        yield {"type": "planning", "content": "正在规划执行步骤..."}
        plan = self.planner.plan(message)

        if not plan.steps:
            yield from self.agent.chat_stream(message, session_id)
            return

        yield {"type": "plan", "content": json.dumps({
            "reasoning": plan.reasoning,
            "steps": [{"step_id": s.step_id, "target": s.target, "purpose": s.purpose} for s in plan.steps],
        }, ensure_ascii=False)}

        results: list[StepResult] = []
        for event in self._stream_with_review(plan):
            if event.get("type") == "_step_result":
                results.append(event["result"])
            else:
                yield event

        yield {"type": "synthesizing", "content": "正在组织回答..."}
        for text_chunk in self.executor.synthesize_stream(plan.question, results):
            yield {"type": "text", "content": text_chunk}

    def _execute_with_review(self, plan: Plan) -> list[StepResult]:
        context: dict[int, StepResult] = {}

        for step in plan.steps:
            result = self.executor._execute_step(step, context)
            context[step.step_id] = result

            if self.reviewer.should_review(step.target):
                prior_str = self.executor._build_context_summary(step.depends_on, context)
                review = self.reviewer.review(result, prior_str)
                if not review.passed and self.max_retries > 0:
                    result = self.executor.rerun_step(step, context, review.suggestion)
                    context[step.step_id] = result

        return list(context.values())

    def _stream_with_review(self, plan: Plan) -> Generator[dict, None, None]:
        context: dict[int, StepResult] = {}

        for step in plan.steps:
            yield {"type": "step_start", "step_id": step.step_id, "target": step.target, "purpose": step.purpose}

            result = StepResult(step_id=step.step_id, target=step.target)
            for event in self.executor._execute_step_stream(step, context):
                if event.get("_result"):
                    result = event["_result"]
                else:
                    yield event

            context[step.step_id] = result

            if self.reviewer.should_review(step.target):
                yield {"type": "review_start", "step_id": step.step_id, "target": step.target}
                prior_str = self.executor._build_context_summary(step.depends_on, context)
                review = self.reviewer.review(result, prior_str)
                yield {
                    "type": "review_done", "step_id": step.step_id,
                    "passed": review.passed,
                    "issues": review.issues,
                    "suggestion": review.suggestion,
                }
                if not review.passed and self.max_retries > 0:
                    yield {"type": "step_retry", "step_id": step.step_id, "suggestion": review.suggestion}
                    from .pipeline_types import PlanStep as PS
                    retry_step = PS(
                        step_id=step.step_id, action=step.action, target=step.target,
                        args=step.args, depends_on=step.depends_on,
                        purpose=step.purpose + f"\n注意: {review.suggestion}",
                    )
                    for event in self.executor._execute_step_stream(retry_step, context):
                        if event.get("_result"):
                            result = event["_result"]
                        else:
                            yield event
                    context[step.step_id] = result

            yield {
                "type": "step_done", "step_id": step.step_id, "target": step.target,
                "status": result.status,
                "note": result.note[:200] if result.note else "",
            }
            yield {"type": "_step_result", "result": result}

    def get_history(self, session_id: str) -> list[dict]:
        return self.agent.get_history(session_id)

    def list_sessions(self) -> list[dict]:
        return self.agent.list_sessions()
