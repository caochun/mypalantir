from __future__ import annotations

import json
import logging
import os
import re

from openai import OpenAI

log = logging.getLogger(__name__)


class DistillerLLM:

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.client = OpenAI(
            api_key=config.get("api_key", os.getenv("LLM_API_KEY", "sk-placeholder")),
            base_url=config.get("api_url", os.getenv("LLM_API_URL", "http://localhost:8090/v1")),
        )
        self.model = config.get("model", os.getenv("LLM_MODEL", "qwen3.5-plus"))
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        log.info("LLM request: %d messages, json_mode=%s", len(messages), json_mode)
        kwargs["max_tokens"] = kwargs.get("max_tokens", 16384)
        response = self.client.chat.completions.create(**kwargs)

        usage = response.usage
        if usage:
            self.total_prompt_tokens += usage.prompt_tokens
            self.total_completion_tokens += usage.completion_tokens
            log.info("tokens: prompt=%d completion=%d", usage.prompt_tokens, usage.completion_tokens)

        return response.choices[0].message.content or ""

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.1,
    ) -> dict:
        text = self.chat(messages, temperature=temperature, json_mode=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            repaired = _repair_truncated_json(text)
            if repaired is not None:
                log.warning("Repaired truncated JSON (%d chars)", len(text))
                return repaired
            raise ValueError(f"LLM did not return valid JSON:\n{text[:500]}")

    def usage_summary(self) -> str:
        return f"Total tokens: prompt={self.total_prompt_tokens}, completion={self.total_completion_tokens}"


def _repair_truncated_json(text: str) -> dict | None:
    for i in range(len(text) - 1, 0, -1):
        if text[i] in ('}', ']'):
            candidate = text[:i + 1]
            depth_obj = candidate.count('{') - candidate.count('}')
            depth_arr = candidate.count('[') - candidate.count(']')
            candidate += ']' * depth_arr + '}' * depth_obj
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None
