from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Generator

from openai import OpenAI

from .events import (
    CompactEvent, ConfirmationEvent, Event, TextEvent, ToolCallEvent,
    event_to_dict,
)
from .harness import Harness


class SessionStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history "
            "(session_id TEXT PRIMARY KEY, messages TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.commit()
        self._cache: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict]:
        if session_id in self._cache:
            return self._cache[session_id]
        row = self.conn.execute(
            "SELECT messages FROM chat_history WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row:
            messages = json.loads(row[0])
        else:
            messages = []
        self._cache[session_id] = messages
        return messages

    def save(self, session_id: str, messages: list[dict]):
        self._cache[session_id] = messages
        self.conn.execute(
            "INSERT OR REPLACE INTO chat_history (session_id, messages, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (session_id, json.dumps(messages, ensure_ascii=False, default=str)),
        )
        self.conn.commit()

    def list_sessions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT session_id, updated_at FROM chat_history ORDER BY updated_at DESC"
        ).fetchall()
        return [{"session_id": r[0], "updated_at": r[1]} for r in rows]


class PendingConfirmation:
    def __init__(self, session_id: str, tool_name: str, args: dict,
                 tool_call_id: str, messages: list[dict]):
        self.session_id = session_id
        self.tool_name = tool_name
        self.args = args
        self.tool_call_id = tool_call_id
        self.messages = messages


class Agent:
    def __init__(self, harness: Harness, llm_client: OpenAI, model: str,
                 db_dir: str = ".oag_data"):
        self.harness = harness
        self.client = llm_client
        self.model = model
        self._pending: dict[str, PendingConfirmation] = {}

        Path(db_dir).mkdir(parents=True, exist_ok=True)
        db_path = str(Path(db_dir) / f"chat_{harness.ontology.name}.db")
        self.sessions = SessionStore(db_path)

    def chat(self, message: str, session_id: str = "default") -> str:
        result_parts = []
        for event in self.chat_stream(message, session_id):
            if isinstance(event, TextEvent):
                result_parts.append(event.content)
        return "".join(result_parts)

    def has_pending(self, session_id: str) -> bool:
        return session_id in self._pending

    def confirm_tool(self, session_id: str, approved: bool) -> Generator[Event, None, None]:
        pending = self._pending.pop(session_id, None)
        if not pending:
            yield TextEvent(content="没有待确认的操作。")
            return

        messages = pending.messages

        if not approved:
            messages.append({
                "role": "tool",
                "tool_call_id": pending.tool_call_id,
                "content": json.dumps({"denied": True, "reason": "用户拒绝执行"}, ensure_ascii=False),
            })
            messages.append({
                "role": "user",
                "content": f"[系统提示] 用户拒绝了 {pending.tool_name} 的执行",
            })
            self.sessions.save(session_id, messages)
            yield TextEvent(content=f"已取消 {pending.tool_name} 的执行。")
            return

        result = self.harness.execute_tool(
            pending.tool_name, pending.args, session_id,
            confirmed=True, messages=messages,
        )

        yield ToolCallEvent(
            name=pending.tool_name,
            args=pending.args,
            result=result.content[:200],
        )

        messages.append({
            "role": "tool",
            "tool_call_id": pending.tool_call_id,
            "content": result.content,
        })

        yield from self._continue_loop(messages, session_id)
        self.sessions.save(session_id, messages)

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[Event, None, None]:
        messages = self.sessions.get(session_id)

        if not messages:
            system_prompt = self.harness.build_system_prompt()
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": message})

        messages, compacted = self.harness.maybe_compact(messages)
        if compacted:
            yield CompactEvent()

        yield from self._run_loop(messages, session_id)

        stop_result = self.harness.run_stop_check(message, messages)
        if stop_result:
            messages.append({"role": "user", "content": stop_result})
            yield from self._run_loop(messages, session_id)

        self.sessions.save(session_id, messages)

    def _run_loop(self, messages: list[dict], session_id: str) -> Generator[Event, None, None]:
        tools = self.harness.build_tools()

        for turn in range(self.harness.config.max_turns):
            if turn > 0 and turn % 5 == 0:
                messages, compacted = self.harness.maybe_compact(messages)
                if compacted:
                    yield CompactEvent()

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=0.1,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                content = msg.content or ""
                messages.append({"role": "assistant", "content": content})
                yield TextEvent(content=content)
                return

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

            tool_calls_parsed = [
                (tc, json.loads(tc.function.arguments)) for tc in msg.tool_calls
            ]

            if len(tool_calls_parsed) > 1:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=min(len(tool_calls_parsed), 4)) as pool:
                    futures = {
                        pool.submit(self.harness.execute_tool, tc.function.name, args, session_id, False, messages): (tc, args)
                        for tc, args in tool_calls_parsed
                    }
                    call_results = {}
                    for future in futures:
                        tc, args = futures[future]
                        call_results[tc.id] = (tc, args, future.result())
                results_ordered = [call_results[tc.id] for tc, _ in tool_calls_parsed]
            else:
                tc, args = tool_calls_parsed[0]
                result = self.harness.execute_tool(tc.function.name, args, session_id, messages=messages)
                results_ordered = [(tc, args, result)]

            for tc, args, result in results_ordered:
                if result.needs_confirmation:
                    self._pending[session_id] = PendingConfirmation(
                        session_id=session_id,
                        tool_name=tc.function.name,
                        args=args,
                        tool_call_id=tc.id,
                        messages=messages,
                    )
                    yield ConfirmationEvent(
                        tool_name=tc.function.name,
                        args=args,
                        reason=result.block_reason,
                    )
                    return

                preview_len = 5000 if tc.function.name == "dispatch_workers" else 200
                yield ToolCallEvent(
                    name=tc.function.name,
                    args=args,
                    result=result.content[:preview_len],
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content,
                })

                if result.blocked:
                    messages.append({
                        "role": "user",
                        "content": f"[系统提示] 工具 {tc.function.name} 被阻止: {result.block_reason}",
                    })

    def _continue_loop(self, messages: list[dict], session_id: str) -> Generator[Event, None, None]:
        yield from self._run_loop(messages, session_id)

    def chat_stream_sse(self, message: str, session_id: str = "default") -> Generator[dict, None, None]:
        for event in self.chat_stream(message, session_id):
            yield event_to_dict(event)

    def get_history(self, session_id: str) -> list[dict]:
        messages = self.sessions.get(session_id)
        return [
            {"role": m["role"], "content": m.get("content", "")}
            for m in messages
            if m["role"] in ("user", "assistant") and m.get("content")
        ]

    def list_sessions(self) -> list[dict]:
        return self.sessions.list_sessions()


