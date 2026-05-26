from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .context import ContextManager, truncate_tool_result
from .hooks import AuditLog, HookRegistry, HookResult, audit_log_hook, business_review_hook, write_confirmation_hook
from .worker import run_workers_parallel
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
    "mutate": ToolMeta(
        name="mutate", category="action",
        is_read_only=False, is_destructive=True,
        requires_confirmation=True, max_result_chars=2000,
    ),
    "search": ToolMeta(name="search", category="query"),
    "start_workflow": ToolMeta(name="start_workflow", category="action"),
    "summarize_progress": ToolMeta(name="summarize_progress", category="inspect"),
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
        self._cache: dict[str, ToolResult] = {}

        if self.config.enable_write_confirmation:
            self.hooks.register("pre_tool_call", write_confirmation_hook)
        if self.config.enable_audit:
            self.hooks.register("post_tool_call", audit_log_hook)
        self.hooks.register("post_tool_call", business_review_hook)

    def get_tool_meta(self, tool_name: str) -> ToolMeta:
        return _derive_tool_meta(tool_name, self.registry)

    def execute_tool(self, tool_name: str, args: dict,
                     session_id: str = "",
                     confirmed: bool = False,
                     messages: list[dict] | None = None) -> ToolResult:
        tool_meta = self.get_tool_meta(tool_name)

        if tool_name == "mutate" and not confirmed:
            pre_check = self._tool_executor.validate_mutate(args)
            if pre_check:
                return ToolResult(content=pre_check)

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

        if tool_name == "dispatch_workers":
            return self._dispatch_workers(args)

        if tool_name == "summarize_progress":
            return self._summarize_progress(messages)

        if tool_meta.is_read_only:
            cache_key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
            if cache_key in self._cache:
                return self._cache[cache_key]

        raw_result = self._tool_executor.execute(tool_name, args)

        truncated_result = truncate_tool_result(raw_result, tool_meta.max_result_chars)
        was_truncated = len(truncated_result) < len(raw_result)

        post_result = self.hooks.fire("post_tool_call", {
            "tool_name": tool_name,
            "args": args,
            "tool_meta": tool_meta,
            "result": raw_result,
            "session_id": session_id,
            "hook_event": "post_tool_call",
            "audit_log": self.audit,
        })

        review_notes = post_result.data.get("review_notes", [])
        if review_notes:
            truncated_result += "\n\n[⚠ 系统校验提示]\n" + "\n".join(f"- {n}" for n in review_notes)

        result = ToolResult(
            content=truncated_result,
            raw_content=raw_result,
            truncated=was_truncated,
        )

        if tool_meta.is_read_only:
            cache_key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
            self._cache[cache_key] = result

        if tool_name == "mutate" and not result.blocked:
            self._cache.clear()

        return result

    def _dispatch_workers(self, args: dict) -> ToolResult:
        tasks = args.get("tasks", [])
        if not tasks:
            return ToolResult(content=json.dumps({"error": "tasks 列表不能为空"}, ensure_ascii=False))

        context = args.get("context", "")

        results = run_workers_parallel(
            self, self.context_mgr.client, self.context_mgr.model,
            tasks, context=context,
            max_workers=min(len(tasks), 4),
        )

        summary = []
        for r in results:
            status_icon = "✓" if r["status"] == "success" else "✗"
            tools_used = ", ".join(tc["name"] for tc in r.get("tool_calls", []))
            summary.append({
                "worker": r["worker_id"],
                "task": r["task"],
                "status": status_icon,
                "tools_used": tools_used,
                "result": r["result"][:500],
            })

        return ToolResult(
            content=json.dumps(summary, ensure_ascii=False, default=str),
        )

    def _summarize_progress(self, messages: list[dict] | None) -> ToolResult:
        if not messages or len(messages) < 2:
            return ToolResult(content=json.dumps({"error": "对话历史过短，无需总结"}, ensure_ascii=False))

        tool_names_used: list[str] = []
        for m in messages:
            for tc in m.get("tool_calls", []):
                if isinstance(tc, dict):
                    tool_names_used.append(tc["function"]["name"])

        summary_text = self.context_mgr._summarize(messages[1:])

        result = {
            "summary": summary_text,
            "total_messages": len(messages),
            "tool_calls_count": len(tool_names_used),
            "tools_used": sorted(set(tool_names_used)),
        }
        return ToolResult(content=json.dumps(result, ensure_ascii=False))

    def build_tools(self) -> list[dict]:
        tools = self._tool_executor.build_tools()
        if self.rule_engine:
            tools.extend(self.rule_engine.build_tools())

        tools.append({
            "type": "function",
            "function": {
                "name": "dispatch_workers",
                "description": "并行派遣多个 Worker 执行独立子任务。每个 Worker 是独立的智能体，有自己的工具和上下文。Worker 只能看到 context 中提供的信息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "子任务描述列表。每条须包含完整信息（事件ID、设施ID等），Worker 看不到你的对话历史",
                        },
                        "context": {
                            "type": "string",
                            "description": "传递给所有 Worker 的背景信息，如事件详情、已查到的设施列表等",
                        },
                    },
                    "required": ["tasks"],
                },
            },
        })

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
        parts.append("- 数据变更: 使用 mutate 创建/更新/删除对象实例（需用户确认）")
        parts.append("- 全文搜索: 使用 search 跨类型关键词搜索")
        if self.ontology.workflows:
            parts.append("- 工作流: 使用 start_workflow 启动和跟踪工作流进度")
        parts.append("- 进度总结: 使用 summarize_progress 回顾对话进展")
        parts.append("- 并行执行: 当有多个相互独立的子任务可以同时进行时，使用 dispatch_workers 并行执行以提高效率")

        if domain_context:
            parts.append(f"\n{domain_context}")

        return "\n".join(parts)

    def maybe_compact(self, messages: list[dict]) -> tuple[list[dict], bool]:
        return self.context_mgr.maybe_compact(messages)

    def run_stop_check(self, user_question: str, messages: list[dict]) -> str | None:
        last_assistant = ""
        tool_errors = []
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break
            if m.get("role") == "tool":
                content = m.get("content", "")
                if '"error"' in content or "不存在" in content:
                    tool_errors.append(content[:100])

        issues = []
        if not last_assistant:
            issues.append("未生成最终回答（可能工具调用轮次用尽）")
        elif len(last_assistant) < 20:
            issues.append("回复过短，可能未完整回答")
        if tool_errors:
            issues.append(f"有工具执行出错未处理: {'; '.join(tool_errors[:2])}")

        if not issues:
            return None

        return (
            f"[系统自检] 请检查你的回复是否完整回答了用户问题: \"{user_question}\"\n"
            f"发现的问题: {'; '.join(issues)}\n"
            f"如果回复已完整，直接说'已确认回复完整'即可。否则请补充。"
        )


class _ToolExecutor:
    def __init__(self, ontology: Ontology, store: Store,
                 registry: FunctionRegistry,
                 rule_engine: RuleEngine | None = None):
        self.ontology = ontology
        self.store = store
        self.registry = registry
        self.rule_engine = rule_engine
        self._hint_shown: set[str] = set()
        self._active_workflows: dict[str, dict] = {}

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

            if name == "mutate":
                return self._mutate(args)

            if name == "search":
                return self._search(args)

            if name == "start_workflow":
                return self._start_workflow(args)

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

    def _find_object_type(self, object_id: Any) -> str | None:
        for type_name in self.ontology.objects:
            row = self.store.query_by_id(type_name, object_id)
            if row:
                return type_name
        return None

    def validate_mutate(self, args: dict) -> str | None:
        """Pre-validate mutate args. Returns error JSON if invalid, None if ok."""
        operation = args.get("operation", "")
        object_type = args.get("object_type", "")
        data = args.get("data", {})
        object_id = args.get("object_id")

        obj_def = self.ontology.objects.get(object_type)
        if not obj_def:
            return json.dumps({"error": f"未知对象类型: {object_type}"}, ensure_ascii=False)
        if operation not in ("create", "update", "delete"):
            return json.dumps({"error": f"未知操作: {operation}"}, ensure_ascii=False)
        if operation in ("update", "delete") and not object_id:
            return json.dumps({"error": f"{operation} 操作需要 object_id"}, ensure_ascii=False)
        if operation in ("update", "delete") and object_id:
            existing = self.store.query_by_id(object_type, object_id)
            if not existing:
                found_in = self._find_object_type(object_id)
                if found_in:
                    return json.dumps({
                        "error": f"在 {object_type} 中未找到 {object_id}",
                        "hint": f"该ID存在于 {found_in}，请改用 object_type=\"{found_in}\"",
                    }, ensure_ascii=False)
                return json.dumps({"error": f"在 {object_type} 中未找到 {object_id}"}, ensure_ascii=False)
        if operation in ("create", "update"):
            errors = self._validate_data(obj_def, data, operation)
            if errors:
                available = {p: {"type": d.type, "description": d.description}
                             for p, d in obj_def.properties.items()}
                return json.dumps({"error": "数据校验失败", "details": errors,
                                   "available_fields": available}, ensure_ascii=False)
        return None

    def _mutate(self, args: dict) -> str:
        pre_check = self.validate_mutate(args)
        if pre_check:
            return pre_check

        operation = args["operation"]
        object_type = args["object_type"]

        if operation == "create":
            result = self.store.insert_record(object_type, args.get("data", {}))
        elif operation == "update":
            result = self.store.update_record(object_type, args["object_id"], args.get("data", {}))
        else:
            result = self.store.delete_record(object_type, args["object_id"])

        return json.dumps(result, ensure_ascii=False, default=str)

    def _validate_data(self, obj_def: Any, data: dict, operation: str) -> list[str]:
        errors: list[str] = []
        valid_props = obj_def.properties

        for key in data:
            if key not in valid_props and key != "_id":
                errors.append(f"未知字段: {key}")

        if operation == "create":
            for prop_name, prop_def in valid_props.items():
                if prop_def.required and prop_name not in data:
                    errors.append(f"缺少必填字段: {prop_name}")

        type_map = {"int": int, "float": float, "str": str}
        for key, value in data.items():
            if key in valid_props and value is not None:
                expected = valid_props[key].type
                validator = type_map.get(expected)
                if validator:
                    try:
                        validator(value)
                    except (ValueError, TypeError):
                        errors.append(f"字段 {key} 类型错误: 期望 {expected}")

        return errors

    def _search(self, args: dict) -> str:
        keyword = args.get("keyword", "")
        object_types = args.get("object_types")
        limit = args.get("limit", 20)
        results = self.store.search_text(keyword, object_types, limit)
        return json.dumps(results, ensure_ascii=False, default=str)

    def _start_workflow(self, args: dict) -> str:
        workflow_name = args.get("workflow_name", "")
        advance_to = args.get("advance_to_step", "")

        wf = self.ontology.workflows.get(workflow_name)
        if not wf:
            return json.dumps({"error": f"未知工作流: {workflow_name}"}, ensure_ascii=False)

        state = self._active_workflows.get(workflow_name)
        if not state:
            state = {"workflow_name": workflow_name, "current_step_index": 0}
            self._active_workflows[workflow_name] = state

        if advance_to:
            found = False
            for i, step in enumerate(wf.steps):
                if step.name == advance_to:
                    state["current_step_index"] = i
                    found = True
                    break
            if not found:
                return json.dumps({"error": f"未知步骤: {advance_to}"}, ensure_ascii=False)

        idx = state["current_step_index"]
        steps_info = []
        for i, step in enumerate(wf.steps):
            info: dict[str, Any] = {
                "index": i,
                "name": step.name,
                "description": step.description or "",
                "function": step.function or "",
                "is_current": i == idx,
            }
            if isinstance(step.next, dict):
                info["branches"] = step.next
            elif step.next:
                info["next"] = step.next
            steps_info.append(info)

        current = wf.steps[idx] if idx < len(wf.steps) else None
        result: dict[str, Any] = {
            "workflow": workflow_name,
            "description": wf.description,
            "trigger": wf.trigger,
            "total_steps": len(wf.steps),
            "current_step_index": idx,
            "current_step": current.name if current else "completed",
            "steps": steps_info,
        }
        if current and current.function:
            result["next_action"] = f"调用 {current.function}"

        return json.dumps(result, ensure_ascii=False, default=str)

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

        tools.append({
            "type": "function",
            "function": {
                "name": "mutate",
                "description": "创建/更新/删除对象实例。写操作需要用户确认。object_id 使用业务主键（如 event_id、drone_id），不是内部 _id。如果不确定字段名，先用 inspect 查看对象定义",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create", "update", "delete"],
                            "description": "操作类型",
                        },
                        "object_type": {
                            "type": "string",
                            "enum": obj_types,
                            "description": "对象类型",
                        },
                        "object_id": {
                            "type": "string",
                            "description": "对象ID（update/delete必填）",
                        },
                        "data": {
                            "type": "object",
                            "description": "要写入的字段（create/update时提供）",
                        },
                    },
                    "required": ["operation", "object_type"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "search",
                "description": "跨对象类型全文搜索。在所有（或指定）对象类型的文本字段中搜索关键词",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                        "object_types": {
                            "type": "array",
                            "items": {"type": "string", "enum": obj_types},
                            "description": "限定搜索的对象类型（可选，不填搜索全部）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最大返回条数（默认20）",
                        },
                    },
                    "required": ["keyword"],
                },
            },
        })

        workflow_names = list(self.ontology.workflows.keys()) if self.ontology.workflows else []
        if workflow_names:
            tools.append({
                "type": "function",
                "function": {
                    "name": "start_workflow",
                    "description": "启动或推进工作流。返回工作流定义、当前步骤和下一步指引",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_name": {
                                "type": "string",
                                "enum": workflow_names,
                                "description": "工作流名称",
                            },
                            "advance_to_step": {
                                "type": "string",
                                "description": "推进到指定步骤名（可选）",
                            },
                        },
                        "required": ["workflow_name"],
                    },
                },
            })

        tools.append({
            "type": "function",
            "function": {
                "name": "summarize_progress",
                "description": "总结当前对话进展。返回已完成的操作摘要、使用的工具统计。适合长对话中回顾进度",
                "parameters": {
                    "type": "object",
                    "properties": {},
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
