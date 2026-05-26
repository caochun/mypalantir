from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from .harness import Harness


class Worker:
    """轻量级 worker agent，执行单一任务后返回结果。"""

    def __init__(self, harness: Any, llm_client: OpenAI, model: str,
                 worker_id: str = "", max_turns: int = 5):
        self.harness = harness
        self.client = llm_client
        self.model = model
        self.worker_id = worker_id
        self.max_turns = max_turns

    def run(self, task: str) -> dict:
        system = self.harness.build_system_prompt()
        system += (
            f"\n\n你是 Worker {self.worker_id}，负责执行一个具体子任务。"
            "\n完成后直接总结关键结果，不要发散。"
        )
        tools = self.harness.build_tools()
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
                         tasks: list[str], max_workers: int = 4) -> list[dict]:
    results: list[dict] = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i, task in enumerate(tasks):
            worker = Worker(harness, llm_client, model,
                            worker_id=f"W{i+1}", max_turns=5)
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
