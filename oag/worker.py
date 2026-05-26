from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from .harness import Harness

WORKER_SYSTEM_TEMPLATE = """\
你是 Worker {worker_id}，负责执行一个具体子任务。

## 领域: {domain}

## 背景信息（主 Agent 已获取）
{context}

## 可用工具
你只需使用以下工具完成任务，不要调用无关工具。

## 要求
- 直接执行任务，不要重复查询主 Agent 已提供的信息
- 完成后用 1-3 句话总结关键结果
- 包含具体数据（等级、数值、状态）"""

TOOL_ALLOWLIST: dict[str, set[str]] = {
    "inspect": {"inspect_facility", "inspect", "query", "lookup_damage_grade", "apply_rule"},
    "recon": {"plan_recon_mission", "check_compliance", "request_flight_approval",
              "dispatch_drone", "collect_recon_data", "get_drone", "get_drones_in_range",
              "get_operators_available", "inspect", "query", "lookup_drone_class",
              "lookup_operator_license_rule", "lookup_airspace_rule"},
    "plan": {"generate_clearance_plans", "score_plans", "lookup_clearance_technique",
             "lookup_bridge_type", "inspect", "query"},
    "dispatch": {"dispatch_resources", "get_depots_in_range", "get_rescue_teams_in_range",
                 "get_equipment_by_depot", "get_material_by_depot", "inspect", "query"},
    "report": {"generate_event_report", "query", "query_links", "inspect"},
}

TASK_KEYWORDS: list[tuple[str, str]] = [
    ("检查", "inspect"), ("评估", "inspect"), ("inspect", "inspect"),
    ("侦测", "recon"), ("无人机", "recon"), ("飞行", "recon"),
    ("方案", "plan"), ("抢通", "plan"),
    ("调度", "dispatch"), ("资源", "dispatch"),
    ("报告", "report"), ("报送", "report"),
]


def _classify_task(task: str) -> str:
    for keyword, category in TASK_KEYWORDS:
        if keyword in task:
            return category
    return ""


def _filter_tools(all_tools: list[dict], task: str) -> list[dict]:
    category = _classify_task(task)
    allowed = TOOL_ALLOWLIST.get(category)
    if not allowed:
        return all_tools
    return [t for t in all_tools if t["function"]["name"] in allowed]


class Worker:
    def __init__(self, harness: Any, llm_client: OpenAI, model: str,
                 worker_id: str = "", max_turns: int = 5,
                 context: str = ""):
        self.harness = harness
        self.client = llm_client
        self.model = model
        self.worker_id = worker_id
        self.max_turns = max_turns
        self.context = context

    def run(self, task: str) -> dict:
        system = WORKER_SYSTEM_TEMPLATE.format(
            worker_id=self.worker_id,
            domain=self.harness.ontology.description or self.harness.ontology.name,
            context=self.context or "(无)",
        )

        all_tools = self.harness.build_tools()
        tools = _filter_tools(all_tools, task)

        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

        tool_calls_log: list[dict] = []

        for _ in range(self.max_turns):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=0.1,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                return {
                    "worker_id": self.worker_id,
                    "task": task,
                    "result": msg.content or "",
                    "tool_calls": tool_calls_log,
                    "status": "success",
                }

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self.harness.execute_tool(tc.function.name, args, confirmed=True)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content,
                })
                tool_calls_log.append({"name": tc.function.name, "args": args})

        return {
            "worker_id": self.worker_id,
            "task": task,
            "result": "(达到最大轮次限制)",
            "tool_calls": tool_calls_log,
            "status": "max_turns",
        }


def run_workers_parallel(harness: Any, llm_client: OpenAI, model: str,
                         tasks: list[str], context: str = "",
                         max_workers: int = 4) -> list[dict]:
    results: list[dict] = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i, task in enumerate(tasks):
            worker = Worker(harness, llm_client, model,
                            worker_id=f"W{i+1}", max_turns=5,
                            context=context)
            future = pool.submit(worker.run, task)
            futures[future] = i

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {
                    "worker_id": f"W{idx+1}",
                    "task": tasks[idx],
                    "result": f"Worker 执行出错: {e}",
                    "tool_calls": [],
                    "status": "error",
                }

    return results
