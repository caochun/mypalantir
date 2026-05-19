from __future__ import annotations

import json
import re
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

    def chat(self, message: str, session_id: str = "default") -> str:
        history = self.sessions.setdefault(session_id, [])
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
            return content

        return "达到最大轮次限制，请简化问题后重试。"

    def chat_stream(self, message: str, session_id: str = "default") -> Generator[dict, None, None]:
        history = self.sessions.setdefault(session_id, [])
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
            return

        yield {"type": "text", "content": "达到最大轮次限制，请简化问题后重试。"}

    def _build_system_prompt(self) -> str:
        parts = []

        parts.append(f"你是{self.ontology.description}领域的专家助手。")
        parts.append("你通过调用工具来获取数据和执行计算，然后基于工具返回的结果回答用户问题。")
        parts.append("不要猜测或编造数据，所有数据必须来自工具调用的结果。\n")

        parts.append("## 世界模型\n")
        for name, obj in self.ontology.objects.items():
            props_desc = []
            for pname, pdef in obj.properties.items():
                desc = f"{pname}({pdef.type})"
                if pdef.description:
                    desc += f": {pdef.description}"
                props_desc.append(desc)
            parts.append(f"**{name}**: {obj.description}")
            parts.append(f"  属性: {', '.join(props_desc)}\n")

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

        parts.append("## 可用工具\n")
        parts.append("### 数据查询")
        parts.append("- **query**: 查询实例。参数: object_type, filters(可选, 支持后缀: __like模糊, __gt/gte/lt/lte/ne比较), order_by(可选, 前缀-降序), limit(可选), offset(可选)")
        parts.append("- **count**: 计数。参数: object_type, filters(可选, 同query)")
        parts.append("- **query_links**: 沿关系查询。参数: source_type, source_id, link_name\n")
        parts.append("### 数据分析")
        parts.append("- **describe**: 统计摘要。参数: object_type, column(可选, 不传返回总览)")
        parts.append("- **pivot**: 透视表。参数: object_type, index, columns, values, aggfunc(mean/sum/count/min/max)")
        parts.append("- **distribution**: 分布直方图。参数: object_type, column, bins(默认10)\n")

        parts.append("### 领域函数")
        for name, fdef in self.registry.list_functions():
            if not fdef:
                continue
            params_str = ""
            if fdef.params:
                param_parts = []
                for pname, pdef in fdef.params.items():
                    p = f"{pname}({pdef.type})"
                    if pdef.default is not None:
                        p += f"={pdef.default}"
                    if pdef.description:
                        p += f": {pdef.description}"
                    param_parts.append(p)
                params_str = ", ".join(param_parts)
            parts.append(f"- **{name}**({params_str}): {fdef.description}")
            if fdef.depends_on:
                parts.append(f"  依赖: {', '.join(fdef.depends_on)}")
            if fdef.hint:
                parts.append(f"  提示: {fdef.hint}")
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
                    "description": fdef.description,
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

    def _execute_tool(self, name: str, args: dict) -> str:
        try:
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
                return self.registry.call_as_tool(name, args)

            return f"未知工具: {name}"
        except Exception as e:
            return f"工具执行错误: {e}"
