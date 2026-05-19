from __future__ import annotations

import json
from typing import Any, Callable

from .schema import FunctionDef


class FunctionRegistry:
    def __init__(self):
        self._functions: dict[str, Callable] = {}
        self._defs: dict[str, FunctionDef] = {}
        self._executed: set[str] = set()

    def register(self, name: str, fn: Callable, definition: FunctionDef | None = None):
        self._functions[name] = fn
        if definition:
            self._defs[name] = definition

    def call(self, name: str, **kwargs) -> Any:
        fn = self._functions.get(name)
        if not fn:
            raise ValueError(f"Function not found: {name}")
        self._ensure_deps(name)
        result = fn(**kwargs)
        self._executed.add(name)
        return result

    def _ensure_deps(self, name: str):
        fdef = self._defs.get(name)
        if not fdef:
            return
        for dep in fdef.depends_on:
            if dep not in self._executed and dep in self._functions:
                self._ensure_deps(dep)
                self._functions[dep]()
                self._executed.add(dep)

    def has(self, name: str) -> bool:
        return name in self._functions

    def get_def(self, name: str) -> FunctionDef | None:
        return self._defs.get(name)

    def list_functions(self) -> list[tuple[str, FunctionDef | None]]:
        return [(name, self._defs.get(name)) for name in self._functions]

    def call_as_tool(self, name: str, args: dict) -> str:
        try:
            result = self.call(name, **args)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)
            return str(result)
        except Exception as e:
            return f"函数执行错误: {e}"
