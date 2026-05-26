from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .context import ContextManager, truncate_tool_result
from .hooks import AuditLog, HookRegistry, HookResult, audit_log_hook, write_confirmation_hook
from .registry import FunctionRegistry
from .rules import RuleEngine
from .schema import Ontology
from .store import Store

logger = logging.getLogger(__name__)


@dataclass
class ToolMeta:
    name: str
    category: str = "query"  # query / analysis / action / inspect / rule
    is_read_only: bool = True
    is_destructive: bool = False
    max_result_chars: int = 5000
    requires_confirmation: bool = False


@dataclass
class ToolResult:
    content: str
    raw_content: str = ""
    truncated: bool = False
    blocked: bool = False
    block_reason: str = ""
    needs_confirmation: bool = False


@dataclass
class HarnessConfig:
    max_turns: int = 10
    max_tool_result_chars: int = 5000
    enable_audit: bool = True
    enable_write_confirmation: bool = True


BUILTIN_TOOLS_META: dict[str, ToolMeta] = {
    "inspect": ToolMeta(name="inspect", category="inspect"),
    "query": ToolMeta(name="query", category="query"),
    "count": ToolMeta(name="count", category="query"),
    "query_links": ToolMeta(name="query_links", category="query"),
    "describe": ToolMeta(name="describe", category="analysis"),
    "pivot": ToolMeta(name="pivot", category="analysis"),
    "distribution": ToolMeta(name="distribution", category="analysis"),
    "apply_rule": ToolMeta(name="apply_rule", category="rule"),
    "apply_rule_batch": ToolMeta(name="apply_rule_batch", category="rule"),
}


def _derive_tool_meta(name: str, registry: FunctionRegistry) -> ToolMeta:
    if name in BUILTIN_TOOLS_META:
        return BUILTIN_TOOLS_META[name]

    fdef = registry.get_def(name)
    if fdef:
        has_writes = bool(fdef.writes_to)
        is_business = fdef.function_type == "business"
        return ToolMeta(
            name=name,
            category="action" if has_writes else "query",
            is_read_only=not has_writes,
            is_destructive=False,
            requires_confirmation=has_writes or is_business,
        )

    return ToolMeta(name=name)


class Harness:
    def __init__(self, ontology: Ontology, store: Store,
                 registry: FunctionRegistry, llm_client: OpenAI,
                 model: str, config: HarnessConfig | None = None):
        self.ontology = ontology
        self.store = store
        self.registry = registry
        self.config = config or HarnessConfig()
        self.hooks = HookRegistry()
        self.audit = AuditLog()
        self.rule_engine = RuleEngine(ontology, store) if ontology.rules else None
        self.context_mgr = ContextManager(llm_client, model)

        self._tool_executor = _ToolExecutor(ontology, store, registry, self.rule_engine)

        if self.config.enable_write_confirmation:
            self.hooks.register("pre_tool_call", write_confirmation_hook)
        if self.config.enable_audit:
            self.hooks.register("post_tool_call", audit_log_hook)

    def get_tool_meta(self, tool_name: str) -> ToolMeta:
        return _derive_tool_meta(tool_name, self.registry)

    def execute_tool(self, tool_name: str, args: dict,
                     session_id: str = "",
                     confirmed: bool = False) -> ToolResult:
        tool_meta = self.get_tool_meta(tool_name)

        if not confirmed:
            pre_result = self.hooks.fire("pre_tool_call", {
                "tool_name": tool_name,
                "args": args,
                "tool_meta": tool_meta,
                "session_id": session_id,
            })
            if pre_result.action == "block":
                return ToolResult(
                    content=json.dumps({"blocked": True, "reason": pre_result.reason}, ensure_ascii=False),
                    blocked=True,
                    block_reason=pre_result.reason,
                )
            if pre_result.action == "pause":
                return ToolResult(
                    content=json.dumps({"paused": True, "reason": pre_result.reason}, ensure_ascii=False),
                    blocked=True,
                    block_reason=pre_result.reason,
                    needs_confirmation=True,
                )

        raw_result = self._tool_executor.execute(tool_name, args)

        truncated_result = truncate_tool_result(raw_result, tool_meta.max_result_chars)
        was_truncated = len(truncated_result) < len(raw_result)

        self.hooks.fire("post_tool_call", {
            "tool_name": tool_name,
            "args": args,
            "tool_meta": tool_meta,
            "result": raw_result,
            "session_id": session_id,
            "hook_event": "post_tool_call",
            "audit_log": self.audit,
        })

        return ToolResult(
            content=truncated_result,
            raw_content=raw_result,
            truncated=was_truncated,
        )

    def build_tools(self) -> list[dict]:
        tools = self._tool_executor.build_tools()
        if self.rule_engine:
            tools.extend(self.rule_engine.build_tools())
        return tools

    def build_system_prompt(self, domain_context: str = "") -> str:
        parts = []
        parts.append(f"你是 {self.ontology.name} 领域的智能助手。")
        if self.ontology.description:
            parts.append(f"\n## 领域说明\n{self.ontology.description}")

        parts.append("\n## 可用对象")
        for name, obj in self.ontology.objects.items():
            kind_label = f" [{obj.kind}]" if obj.kind != "entity" else ""
            line = (obj.summary or obj.description or "").strip().split("\n")[0]
            parts.append(f"- {name}{kind_label}: {line}")

        if self.ontology.links:
            parts.append("\n## 关系")
            for lname, ldef in self.ontology.links.items():
                parts.append(f"- {lname}: {ldef.source} → {ldef.target}")

        if self.ontology.rules:
            parts.append("\n## 可用规则（确定性，无需推理）")
            for rname, rdef in self.ontology.rules.items():
                applies = ", ".join(rdef.applies_to)
                parts.append(f"- {rname} [{rdef.rule_type}]: {rdef.description} (适用于: {applies})")
            parts.append("\n使用 apply_rule/apply_rule_batch 工具应用规则，不要自己推理规则逻辑。")

        if self.ontology.workflows:
            parts.append("\n## 工作流（复杂任务请按以下流程逐步执行）")
            for wname, wdef in self.ontology.workflows.items():
                parts.append(f"\n### {wname}: {wdef.description}")
                parts.append(f"触发条件: {wdef.trigger}")
                for i, ws in enumerate(wdef.steps):
                    fn_label = f"调用 {ws.function}" if ws.function else "人工步骤"
                    branch = ""
                    if isinstance(ws.next, dict):
                        branch = " → 分支: " + ", ".join(f"{k}→{v}" for k, v in ws.next.items())
                    elif ws.next:
                        branch = f" → {ws.next}"
                    desc = f" ({ws.description})" if ws.description else ""
                    parts.append(f"  {i+1}. {ws.name}: {fn_label}{desc}{branch}")
            parts.append("\n重要: 执行工作流时逐步调用工具，根据每步的实际结果决定下一步行动。"
                         "不要一次规划所有步骤——看到结果后再决定。"
                         "如果某步结果显示应走分支路径，就走分支。")

        fn_lines = []
        for name, fdef in self.registry.list_functions():
            if not fdef:
                continue
            fn_parts = [f"- {name}"]
            if fdef.function_type:
                fn_parts.append(f"[{fdef.function_type}]")
            fn_parts.append(f": {(fdef.summary or '').strip().split(chr(10))[0]}")
            if fdef.writes_to:
                fn_parts.append(f" ⚠️writes_to: {', '.join(fdef.writes_to)}")
            fn_lines.append("".join(fn_parts))
        if fn_lines:
            parts.append("\n## 可用函数")
            parts.extend(fn_lines)

        parts.append("\n## 工具使用规则")
        parts.append("- 查询数据: 使用 query/count/query_links")
        parts.append("- 统计分析: 使用 describe/pivot/distribution")
        parts.append("- 应用规则: 使用 apply_rule（确定性，不要自己推理）")
        parts.append("- 查看详情: 使用 inspect 获取函数/对象的完整定义")
        parts.append("- 业务操作: 调用注册的业务函数")

        if domain_context:
            parts.append(f"\n{domain_context}")

        return "\n".join(parts)

    def maybe_compact(self, messages: list[dict]) -> tuple[list[dict], bool]:
        return self.context_mgr.maybe_compact(messages)


class _ToolExecutor:
    def __init__(self, ontology: Ontology, store: Store,
                 registry: FunctionRegistry,
                 rule_engine: RuleEngine | None = None):
        self.ontology = ontology
        self.store = store
        self.registry = registry
        self.rule_engine = rule_engine
        self._hint_shown: set[str] = set()

    def execute(self, name: str, args: dict) -> str:
        try:
            if name == "inspect":
                return self._inspect(args.get("name", ""))

            if name == "query":
                rows = self.store.query(
                    args["object_type"], args.get("filters"),
                    args.get("limit"), args.get("order_by"), args.get("offset"),
                )
                if not rows:
                    total = self.store.count(args["object_type"])
                    if total == 0:
                        return json.dumps({"results": [], "note": f"{args['object_type']} 当前没有数据。"}, ensure_ascii=False)
                    return json.dumps({"results": [], "note": f"未找到匹配记录（共 {total} 条）。"}, ensure_ascii=False)
                return json.dumps(rows, ensure_ascii=False, default=str)

            if name == "count":
                n = self.store.count(args["object_type"], args.get("filters"))
                return json.dumps({"count": n}, ensure_ascii=False)

            if name == "query_links":
                rows = self.store.query_links(
                    args["source_type"], args["source_id"], args["link_name"],
                )
                return json.dumps(rows, ensure_ascii=False, default=str)

            if name == "describe":
                from .analytics import describe
                result = describe(self.store, args["object_type"], args.get("column"))
                return json.dumps(result, ensure_ascii=False, default=str)

            if name == "pivot":
                from .analytics import pivot
                result = pivot(
                    self.store, args["object_type"],
                    args["index"], args["columns"], args["values"],
                    args.get("aggfunc", "mean"),
                )
                return json.dumps(result, ensure_ascii=False, default=str)

            if name == "distribution":
                from .analytics import distribution
                result = distribution(
                    self.store, args["object_type"],
                    args["column"], args.get("bins", 10),
                )
                return json.dumps(result, ensure_ascii=False, default=str)

            if self.rule_engine and name in ("apply_rule", "apply_rule_batch"):
                return self.rule_engine.execute_tool(name, args)

            if self.registry.has(name):
                result = self.registry.call_as_tool(name, args)
                return self._maybe_inject_hint(name, result)

            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"工具执行错误: {e}"}, ensure_ascii=False)

    def _inspect(self, target: str) -> str:
        if not target:
            return json.dumps({"error": "需要参数 name"}, ensure_ascii=False)

        fdef = self.registry.get_def(target)
        if fdef:
            return json.dumps({
                "kind": "function",
                "name": target,
                "summary": fdef.summary,
                "description": fdef.description,
                "group": fdef.group,
                "depends_on": fdef.depends_on,
                "hint": fdef.hint,
                "function_type": fdef.function_type,
                "writes_to": fdef.writes_to,
                "params": {
                    p: {"type": d.type, "description": d.description, "default": d.default}
                    for p, d in fdef.params.items()
                },
            }, ensure_ascii=False, default=str)

        obj = self.ontology.objects.get(target)
        if obj:
            info: dict[str, Any] = {
                "kind": "object",
                "name": target,
                "object_kind": obj.kind,
                "summary": obj.summary,
                "description": obj.description,
                "properties": {
                    p: {"type": d.type, "required": d.required, "description": d.description}
                    for p, d in obj.properties.items()
                },
            }
            rules = self.ontology.get_rules_for_object(target)
            if rules:
                info["applicable_rules"] = {
                    rname: {"description": rdef.description, "rule_type": rdef.rule_type}
                    for rname, rdef in rules.items()
                }
            return json.dumps(info, ensure_ascii=False, default=str)

        rdef = self.ontology.rules.get(target)
        if rdef:
            return json.dumps({
                "kind": "rule",
                "name": target,
                "description": rdef.description,
                "rule_type": rdef.rule_type,
                "applies_to": rdef.applies_to,
                "conditions": [
                    {"field": c.field, "operator": c.operator, "value": c.value, "result": c.result}
                    for c in rdef.conditions
                ],
            }, ensure_ascii=False, default=str)

        return json.dumps({"error": f"未找到: {target}"}, ensure_ascii=False)

    def _maybe_inject_hint(self, fn_name: str, result: str) -> str:
        notes: list[str] = []
        fdef = self.registry.get_def(fn_name)
        if fdef and fdef.hint and fn_name not in self._hint_shown:
            notes.append(f"[函数 {fn_name} 的详细规则]\n{fdef.hint.strip()}")
            self._hint_shown.add(fn_name)

        if notes:
            return result + "\n\n" + "\n\n".join(notes)
        return result

    def build_tools(self) -> list[dict]:
        tools = []
        obj_types = list(self.ontology.objects.keys())

        tools.append({
            "type": "function",
            "function": {
                "name": "inspect",
                "description": "查看函数/对象/规则的完整定义",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "函数名、对象类型名或规则名"},
                    },
                    "required": ["name"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "query",
                "description": "查询对象实例。filters支持后缀: __like模糊, __gt大于, __gte大于等于, __lt小于, __lte小于等于, __ne不等于",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string", "enum": obj_types},
                        "filters": {"type": "object", "description": "过滤条件"},
                        "order_by": {"type": "string", "description": "排序字段，-前缀降序"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": ["object_type"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "count",
                "description": "统计对象数量",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string", "enum": obj_types},
                        "filters": {"type": "object"},
                    },
                    "required": ["object_type"],
                },
            },
        })

        if self.ontology.links:
            tools.append({
                "type": "function",
                "function": {
                    "name": "query_links",
                    "description": "沿关系查询关联实例",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source_type": {"type": "string"},
                            "source_id": {"type": "string"},
                            "link_name": {"type": "string", "enum": list(self.ontology.links.keys())},
                        },
                        "required": ["source_type", "source_id", "link_name"],
                    },
                },
            })

        tools.append({
            "type": "function",
            "function": {
                "name": "describe",
                "description": "统计摘要",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string", "enum": obj_types},
                        "column": {"type": "string"},
                    },
                    "required": ["object_type"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "pivot",
                "description": "透视表分析",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string", "enum": obj_types},
                        "index": {"type": "string"},
                        "columns": {"type": "string"},
                        "values": {"type": "string"},
                        "aggfunc": {"type": "string", "enum": ["mean", "sum", "count", "min", "max"]},
                    },
                    "required": ["object_type", "index", "columns", "values"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "distribution",
                "description": "分布直方图",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string", "enum": obj_types},
                        "column": {"type": "string"},
                        "bins": {"type": "integer"},
                    },
                    "required": ["object_type", "column"],
                },
            },
        })

        for name, fdef in self.registry.list_functions():
            if not fdef:
                continue
            props = {}
            required = []
            for pname, pdef in fdef.params.items():
                props[pname] = {
                    "type": pdef.type if pdef.type in ("string", "integer", "number") else "string",
                    "description": pdef.description,
                }
                if pdef.default is None:
                    required.append(pname)

            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": (fdef.summary or fdef.description or "").strip(),
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            })

        return tools
