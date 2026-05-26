from __future__ import annotations

import json
from typing import Generator

from openai import OpenAI

from .agent import Agent
from .events import Event, TextEvent, event_to_dict
from .harness import Harness, HarnessConfig
from .planner import Planner
from .registry import FunctionRegistry
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

        harness_config = HarnessConfig(
            max_turns=llm_config.get("max_turns", 30),
            max_tool_result_chars=llm_config.get("max_tool_result_chars", 5000),
        )
        self.harness = Harness(
            ontology, store, registry,
            self.client, self.model, harness_config,
        )

        self.agent = Agent(self.harness, self.client, self.model)
        self.planner = Planner(ontology, registry, self.client, self.model)

    def chat(self, message: str, session_id: str = "default") -> str:
        return self.agent.chat(message, session_id)

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[Event, None, None]:
        yield from self.agent.chat_stream(message, session_id)

    def chat_stream_sse(self, message: str, session_id: str = "default") -> Generator[dict, None, None]:
        for event in self.chat_stream(message, session_id):
            yield event_to_dict(event)

    def get_history(self, session_id: str) -> list[dict]:
        return self.agent.get_history(session_id)

    def list_sessions(self) -> list[dict]:
        return self.agent.list_sessions()
