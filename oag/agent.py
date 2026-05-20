from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Generator

from openai import OpenAI

from .registry import FunctionRegistry
from .schema import Ontology
from .store import Store


class Agent:
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
        self.max_turns = llm_config.get("max_turns", 10)
        self.sessions: dict[str, list[dict]] = {}
        self._hint_shown: set[str] = set()
        self._init_chat_history()

    def _init_chat_history(self):
        db_dir = Path(".oag_data")
        db_dir.mkdir(exist_ok=True)
        db_path = db_dir / f"chat_{self.ontology.name}.db"
        self._chat_db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._chat_db.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "session_id TEXT NOT NULL, messages TEXT NOT NULL, "
            "updated_at TEXT DEFAULT (datetime('now')))"
        )
        self._chat_db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id)"
        )
        self._chat_db.commit()

    def _load_session(self, session_id: str) -> list[dict]:
        row = self._chat_db.execute(
            "SELECT messages FROM chat_history WHERE session_id = ?", [session_id]
        ).fetchone()
        if row:
            return json.loads(row[0])
        return []

    def _save_session(self, session_id: str, messages: list[dict]):
        self._chat_db.execute(
            "INSERT INTO chat_history (session_id, messages, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(session_id) DO UPDATE SET messages=excluded.messages, updated_at=excluded.updated_at",
            [session_id, json.dumps(messages, ensure_ascii=False)]
        )
        self._chat_db.commit()

    def get_history(self, session_id: str) -> list[dict]:
        history = self.sessions.get(session_id) or self._load_session(session_id)
        out = []
        for msg in history:
            role = msg.get("role", "")
            if role == "user":
                out.append({"role": "user", "content": msg.get("content", "")})
            elif role == "assistant" and not msg.get("tool_calls"):
                content = msg.get("content", "")
                if content:
                    out.append({"role": "assistant", "content": content})
        return out

    def list_sessions(self) -> list[dict]:
        rows = self._chat_db.execute(
            "SELECT session_id, updated_at FROM chat_history ORDER BY updated_at DESC"
        ).fetchall()
        return [{"session_id": r[0], "updated_at": r[1]} for r in rows]

    def chat(self, message: str, session_id: str = "default") -> str:
        if session_id not in self.sessions:
            self.sessions[session_id] = self._load_session(session_id)
        history = self.sessions[session_id]
        history.append({"role": "user", "content": message})

        system = self._build_system_prompt()
        tools = self._build_tools()

        for _ in range(self.max_turns):
            messages = [{"role": "system", "content": system}] + history

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=0.1,
            )

            choice = response.choices[0]
            msg = choice.message

            if msg.tool_calls:
                history.append({
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
                    result = self._execute_tool(
                        tc.function.name,
                        json.loads(tc.function.arguments),
                    )
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                continue

            content = msg.content or ""
            history.append({"role": "assistant", "content": content})
            self._save_session(session_id, history)
            return content

        return "达到最大轮次限制，请简化问题后重试。"

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[dict, None, None]:
        if session_id not in self.sessions:
            self.sessions[session_id] = self._load_session(session_id)
        history = self.sessions[session_id]
        history.append({"role": "user", "content": message})

        system = self._build_system_prompt()
        tools = self._build_tools()

        for _ in range(self.max_turns):
            messages = [{"role": "system", "content": system}] + history

            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                temperature=0.1,
                stream=True,
            )

            content_parts = []
            tool_calls_acc: dict[int, dict] = {}

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "text", "content": delta.content}

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        acc = tool_calls_acc[idx]
                        if tc_delta.id:
                            acc["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                acc["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                acc["arguments"] += tc_delta.function.arguments

            if tool_calls_acc:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in tool_calls_acc.values()
                    ],
                }
                history.append(assistant_msg)

                for tc in tool_calls_acc.values():
                    yield {"type": "tool_call", "name": tc["name"], "arguments": tc["arguments"]}
                    result = self._execute_tool(tc["name"], json.loads(tc["arguments"]))
                    yield {"type": "tool_result", "name": tc["name"], "result": result}
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                continue

            content = "".join(content_parts)
            history.append({"role": "assistant", "content": content})
            self._save_session(session_id, history)
            return

        yield {"type": "text", "content": "达到最大轮次限制，请简化问题后重试。"}

    def _build_system_prompt(self) -> str:
        parts = []

        parts.append(f"你是{self.ontology.description}领域的专家助手。")
        parts.append("你通过调用工具来获取数据和执行计算，然后基于工具返回的结果回答用户问题。")
        parts.append("不要猜测或编造数据，所有数据必须来自工具调用的结果。\n")

        parts.append("## 世界模型 (默认只看 summary；查完整属性调 inspect(name))\n")
        for name, obj in self.ontology.objects.items():
            line = (obj.summary or obj.description or "").strip().split("\n")[0]
            parts.append(f"- **{name}**: {line}")
        parts.append("")

        if self.ontology.links:
            parts.append("## 关系\n")
            for lname, ldef in self.ontology.links.items():
                parts.append(
                    f"- {lname}: {ldef.source} → {ldef.target} "
                    f"(通过 {ldef.join['source_key']} = {ldef.join['target_key']})"
                )
                if ldef.description:
                    parts.append(f"  {ldef.description}")
            parts.append("")

        parts.append("## 可用工具(参数细节见各工具的 schema 或调用时的提示)\n")
        parts.append("### 数据查询")
        parts.append("- **query**: 查询某类型实例(支持 filters/order_by/limit/offset)")
        parts.append("- **count**: 计数(同 query 的 filters)")
        parts.append("- **query_links**: 沿声明的 link 关系跨对象查询\n")
        parts.append("### 数据分析")
        parts.append("- **describe**: 列统计摘要(numeric/text 自适应)")
        parts.append("- **pivot**: 透视表(支持 mean/sum/count/min/max)")
        parts.append("- **distribution**: 数值列分布直方图\n")

        parts.append("### 领域函数 (默认只看 summary；查参数/规则/提示调 inspect(name))")
        # 按 group 字段分组渲染。group 为空的函数归入"其他"。
        groups: dict[str, list[tuple[str, "FunctionDef"]]] = {}
        for name, fdef in self.registry.list_functions():
            if not fdef:
                continue
            g = fdef.group or "其他"
            groups.setdefault(g, []).append((name, fdef))

        for group_name, items in groups.items():
            parts.append(f"\n**[{group_name}]**")
            for name, fdef in items:
                line = (fdef.summary or fdef.description or "").strip().split("\n")[0]
                parts.append(f"- **{name}**: {line}")
        parts.append("")

        parts.append("### 元工具")
        parts.append("- **inspect**: 查看函数/对象的完整定义(参数细节/规则提示/字段属性)")
        parts.append("")

        parts.append("## 注意事项")
        parts.append("- 调用有依赖关系的函数前，确保依赖函数已执行")
        parts.append("- 用中文回答用户问题")
        parts.append("- 回答要简洁明了，给出关键数据")
        parts.append("- 注意数据单位：属性描述中标注了单位的，向用户展示时应转换为用户友好的单位（如分→元、米→公里）")

        return "\n".join(parts)

    def _build_tools(self) -> list[dict]:
        tools = []

        obj_types = list(self.ontology.objects.keys())

        # 元工具: 渐进式披露的入口
        tools.append({
            "type": "function",
            "function": {
                "name": "inspect",
                "description": "查看某个函数或对象的完整定义(参数说明/规则提示/字段属性)。"
                               "默认系统提示词只展示一行 summary；调用具体工具前若需详细参数、"
                               "或处理工具返回结果时需要规则细节，调本工具",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "函数名或对象类型名",
                        }
                    },
                    "required": ["name"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "query",
                "description": "查询某个类型的实例数据。filters支持后缀: name__like模糊匹配, price__gt大于, price__gte大于等于, price__lt小于, price__lte小于等于, price__ne不等于",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "description": "对象类型名称",
                            "enum": obj_types,
                        },
                        "filters": {
                            "type": "object",
                            "description": "过滤条件。等值: {name: val}, 模糊: {name__like: val}, 比较: {price__gt: 500}",
                        },
                        "order_by": {
                            "type": "string",
                            "description": "排序字段，前缀-表示降序，如 -price",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回数量限制",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "跳过前N条",
                        },
                    },
                    "required": ["object_type"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "count",
                "description": "统计某个类型的实例数量",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "enum": obj_types,
                        },
                        "filters": {
                            "type": "object",
                            "description": "过滤条件(同query)",
                        },
                    },
                    "required": ["object_type"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "query_links",
                "description": "沿关系查询关联实例",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_type": {
                            "type": "string",
                            "description": "源对象类型",
                        },
                        "source_id": {
                            "type": "string",
                            "description": "源对象ID",
                        },
                        "link_name": {
                            "type": "string",
                            "description": "关系名称",
                            "enum": list(self.ontology.links.keys()),
                        },
                    },
                    "required": ["source_type", "source_id", "link_name"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "describe",
                "description": "统计摘要。不传column返回总览，传column返回该列的统计信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "enum": obj_types,
                        },
                        "column": {
                            "type": "string",
                            "description": "列名(可选)",
                        },
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
                        "index": {"type": "string", "description": "行维度列名"},
                        "columns": {"type": "string", "description": "列维度列名"},
                        "values": {"type": "string", "description": "值列名"},
                        "aggfunc": {
                            "type": "string",
                            "description": "聚合函数",
                            "enum": ["mean", "sum", "count", "min", "max"],
                            "default": "mean",
                        },
                    },
                    "required": ["object_type", "index", "columns", "values"],
                },
            },
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "distribution",
                "description": "数值列的分布直方图",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string", "enum": obj_types},
                        "column": {"type": "string", "description": "数值列名"},
                        "bins": {"type": "integer", "description": "分箱数", "default": 10},
                    },
                    "required": ["object_type", "column"],
                },
            },
        })

        for name, fdef in self.registry.list_functions():
            if not fdef:
                continue
            properties = {}
            required = []
            for pname, pdef in fdef.params.items():
                prop: dict[str, Any] = {"description": pdef.description or pname}
                if pdef.type == "int":
                    prop["type"] = "integer"
                elif pdef.type == "float":
                    prop["type"] = "number"
                else:
                    prop["type"] = "string"
                if pdef.default is not None:
                    prop["default"] = pdef.default
                else:
                    required.append(pname)
                properties[pname] = prop

            tool_def: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": fdef.summary or fdef.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                    },
                },
            }
            if required:
                tool_def["function"]["parameters"]["required"] = required
            tools.append(tool_def)

        return tools

    def _maybe_inject_hint(self, fn_name: str, result: str) -> str:
        """渐进式披露: 在首次调某函数时附加该函数的完整 hint；
        若结果含 `*_type` 字段且对应已知对象，附加该对象的 description。"""
        notes: list[str] = []

        fdef = self.registry.get_def(fn_name)
        if fdef and fdef.hint and fn_name not in self._hint_shown:
            notes.append(f"[函数 {fn_name} 的详细规则]\n{fdef.hint.strip()}")
            self._hint_shown.add(fn_name)

        # 扫结果中的 *_type 字段(如 request_type=ExpandRequest)，附加对象详情
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                for key, val in data.items():
                    if (isinstance(key, str) and key.endswith("_type")
                            and isinstance(val, str)):
                        obj = self.ontology.objects.get(val)
                        if obj and val not in self._hint_shown:
                            desc = (obj.description or "").strip()
                            if desc and desc != (obj.summary or "").strip():
                                notes.append(f"[对象 {val} 的完整定义]\n{desc}")
                                self._hint_shown.add(val)
        except (json.JSONDecodeError, TypeError):
            pass

        if notes:
            return result + "\n\n" + "\n\n".join(notes)
        return result

    def _inspect(self, target: str) -> str:
        """渐进式披露入口: 返回函数或对象的完整定义。"""
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
                "params": {
                    p: {
                        "type": d.type,
                        "description": d.description,
                        "default": d.default,
                    }
                    for p, d in fdef.params.items()
                },
            }, ensure_ascii=False, default=str)

        obj = self.ontology.objects.get(target)
        if obj:
            return json.dumps({
                "kind": "object",
                "name": target,
                "summary": obj.summary,
                "description": obj.description,
                "properties": {
                    p: {
                        "type": d.type,
                        "required": d.required,
                        "description": d.description,
                        "default": d.default,
                    }
                    for p, d in obj.properties.items()
                },
            }, ensure_ascii=False, default=str)

        return json.dumps({"error": f"未找到函数或对象: {target}"}, ensure_ascii=False)

    def _execute_tool(self, name: str, args: dict) -> str:
        try:
            if name == "inspect":
                return self._inspect(args.get("name", ""))

            if name == "query":
                rows = self.store.query(
                    args["object_type"],
                    args.get("filters"),
                    args.get("limit"),
                    args.get("order_by"),
                    args.get("offset"),
                )
                return json.dumps(rows, ensure_ascii=False, default=str)

            if name == "count":
                n = self.store.count(args["object_type"], args.get("filters"))
                return json.dumps({"count": n}, ensure_ascii=False)

            if name == "query_links":
                rows = self.store.query_links(
                    args["source_type"],
                    args["source_id"],
                    args["link_name"],
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

            if self.registry.has(name):
                result = self.registry.call_as_tool(name, args)
                # 渐进式披露: 首次调用时附加 hint，结果含已知对象类型时附加对象 description
                return self._maybe_inject_hint(name, result)

            return f"未知工具: {name}"
        except Exception as e:
            return f"工具执行错误: {e}"
