from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Generator

from openai import OpenAI

from .events import (
    CompactEvent, Event, TextEvent, ToolCallEvent, event_to_dict,
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


class Agent:
    def __init__(self, harness: Harness, llm_client: OpenAI, model: str,
                 db_dir: str = ".oag_data"):
        self.harness = harness
        self.client = llm_client
        self.model = model

        Path(db_dir).mkdir(parents=True, exist_ok=True)
        db_path = str(Path(db_dir) / f"chat_{harness.ontology.name}.db")
        self.sessions = SessionStore(db_path)

    def chat(self, message: str, session_id: str = "default") -> str:
        result_parts = []
        for event in self.chat_stream(message, session_id):
            if isinstance(event, TextEvent):
                result_parts.append(event.content)
        return "".join(result_parts)

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[Event, None, None]:
        messages = self.sessions.get(session_id)

        if not messages:
            system_prompt = self.harness.build_system_prompt()
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": message})

        messages, compacted = self.harness.maybe_compact(messages)
        if compacted:
            yield CompactEvent()

        tools = self.harness.build_tools()

        for _ in range(self.harness.config.max_turns):
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
                break

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
                result = self.harness.execute_tool(tc.function.name, args, session_id)

                yield ToolCallEvent(
                    name=tc.function.name,
                    args=args,
                    result=result.content[:200],
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

        self.sessions.save(session_id, messages)

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


