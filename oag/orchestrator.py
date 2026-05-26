from __future__ import annotations

import asyncio
import json
from typing import Generator

from openai import OpenAI

from .agent import Agent
from .events import (
    Event, PlanEvent, PlanningEvent, ReviewEvent, StepDoneEvent,
    StepStartEvent, SynthesizingEvent, TextEvent, event_to_dict,
)
from .executor import Executor
from .harness import Harness, HarnessConfig
from .pipeline_types import Plan, PlanStep, StepResult
from .planner import Planner
from .registry import FunctionRegistry
from .reviewer import Reviewer
from .schema import Ontology
from .store import Store


def find_parallel_groups(steps: list[PlanStep]) -> list[list[PlanStep]]:
    executed: set[int] = set()
    groups: list[list[PlanStep]] = []
    remaining = list(steps)

    while remaining:
        ready = [s for s in remaining
                 if all(d in executed for d in s.depends_on)]
        if not ready:
            groups.append(remaining)
            break
        groups.append(ready)
        for s in ready:
            executed.add(s.step_id)
            remaining.remove(s)

    return groups


def can_run_parallel(steps: list[PlanStep],
                     registry: FunctionRegistry) -> bool:
    write_sets: list[set[str]] = []
    for step in steps:
        fdef = registry.get_def(step.target)
        writes = set(fdef.writes_to) if fdef else set()
        write_sets.append(writes)

    for i in range(len(write_sets)):
        for j in range(i + 1, len(write_sets)):
            if write_sets[i] & write_sets[j]:
                return False
    return True


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

        harness_config = HarnessConfig(
            max_turns=llm_config.get("max_turns", 10),
            max_tool_result_chars=llm_config.get("max_tool_result_chars", 5000),
        )
        self.harness = Harness(
            ontology, store, registry,
            self.client, self.model, harness_config,
        )

        self.agent = Agent(self.harness, self.client, self.model)
        self.planner = Planner(ontology, registry, self.client, self.model)
        self.executor = Executor(self.harness, self.client, self.model)
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

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[Event, None, None]:
        complexity = self.planner.classify(message)
        if complexity == "simple":
            yield from self.agent.chat_stream(message, session_id)
            return

        yield PlanningEvent(content="正在规划执行步骤...")
        plan = self.planner.plan(message)

        if not plan.steps:
            yield from self.agent.chat_stream(message, session_id)
            return

        yield PlanEvent(
            reasoning=plan.reasoning,
            steps=[
                {"step_id": s.step_id, "target": s.target, "purpose": s.purpose}
                for s in plan.steps
            ],
        )

        results: list[StepResult] = []
        for event in self._stream_with_review(plan):
            if isinstance(event, _StepResultCarrier):
                results.append(event.result)
            else:
                yield event

        yield SynthesizingEvent(content="正在组织回答...")
        for text_chunk in self.executor.synthesize_stream(plan.question, results):
            yield TextEvent(content=text_chunk)

    def chat_stream_sse(self, message: str, session_id: str = "default") -> Generator[dict, None, None]:
        for event in self.chat_stream(message, session_id):
            yield event_to_dict(event)

    def _execute_with_review(self, plan: Plan) -> list[StepResult]:
        context: dict[int, StepResult] = {}
        groups = find_parallel_groups(plan.steps)

        for group in groups:
            for step in group:
                result = self.executor.execute_step(step, context)
                context[step.step_id] = result

                if self.reviewer.should_review(step.target):
                    prior_str = self.executor._build_context_summary(step.depends_on, context)
                    review = self.reviewer.review(result, prior_str)
                    if not review.passed and self.max_retries > 0:
                        result = self.executor.rerun_step(step, context, review.suggestion)
                        context[step.step_id] = result
                        re_review = self.reviewer.review(result, prior_str)
                        if not re_review.passed:
                            result.status = "review_failed"
                            result.note = f"[审查未通过] {'; '.join(re_review.issues)}\n{result.note}"

        return list(context.values())

    def _stream_with_review(self, plan: Plan) -> Generator[Event | _StepResultCarrier, None, None]:
        context: dict[int, StepResult] = {}

        for step in plan.steps:
            yield StepStartEvent(
                step_id=step.step_id,
                target=step.target,
                purpose=step.purpose,
            )

            result = self.executor.execute_step(step, context)
            context[step.step_id] = result

            if self.reviewer.should_review(step.target):
                prior_str = self.executor._build_context_summary(step.depends_on, context)
                review = self.reviewer.review(result, prior_str)
                yield ReviewEvent(
                    step_id=step.step_id,
                    passed=review.passed,
                    issues=review.issues,
                    suggestion=review.suggestion,
                )
                if not review.passed and self.max_retries > 0:
                    result = self.executor.rerun_step(step, context, review.suggestion)
                    context[step.step_id] = result
                    re_review = self.reviewer.review(result, prior_str)
                    yield ReviewEvent(
                        step_id=step.step_id,
                        passed=re_review.passed,
                        issues=re_review.issues,
                        suggestion=re_review.suggestion,
                    )
                    if not re_review.passed:
                        result.status = "review_failed"
                        result.note = f"[审查未通过] {'; '.join(re_review.issues)}\n{result.note}"

            yield StepDoneEvent(
                step_id=step.step_id,
                target=step.target,
                status=result.status,
                note=result.note[:200] if result.note else "",
            )
            yield _StepResultCarrier(result=result)

    def get_history(self, session_id: str) -> list[dict]:
        return self.agent.get_history(session_id)

    def list_sessions(self) -> list[dict]:
        return self.agent.list_sessions()


class _StepResultCarrier(Event):
    def __init__(self, result: StepResult):
        super().__init__(type="_internal")
        self.result = result
