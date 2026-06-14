from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from openai import OpenAI

from oag.agent import Agent
from oag.runtime.events import event_to_dict
from oag.harness import Harness, HarnessConfig
from oag.ontology.loader import load_domain
from oag.ontology.registry import FunctionRegistry
from oag.ontology.repository import ObjectRepository
from oag.ontology.schema import Ontology

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
logger = logging.getLogger(__name__)


def _stream_error_message(exc: Exception) -> str:
    text = str(exc)
    if "Loading model" in text or "503" in text:
        return "LLM 服务暂时不可用：模型仍在加载，请稍后重试。"
    if "APIConnectionError" in type(exc).__name__ or "Connection" in text:
        return "LLM 服务连接失败，请确认 llama-server 正在运行。"
    return f"生成失败：{text or type(exc).__name__}"


class AgentRun:
    def __init__(self, run_id: str, session_id: str, message: str):
        self.run_id = run_id
        self.session_id = session_id
        self.message = message
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.cancelled = False
        self.seq = 0
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.condition = threading.Condition()


class AgentRunManager:
    def __init__(self, agent: Agent):
        self.agent = agent
        self._runs: dict[str, AgentRun] = {}
        self._active_by_session: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(self, session_id: str, message: str) -> AgentRun:
        run = AgentRun(uuid.uuid4().hex, session_id, message)
        with self._lock:
            self._runs[run.run_id] = run
            self._active_by_session[session_id] = run.run_id
        thread = threading.Thread(target=self._execute, args=(run,), daemon=True)
        thread.start()
        return run

    def get(self, run_id: str) -> AgentRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def get_active(self, session_id: str) -> AgentRun | None:
        with self._lock:
            run_id = self._active_by_session.get(session_id)
            if not run_id:
                return None
            run = self._runs.get(run_id)
        if not run:
            return None
        with run.condition:
            if run.done or run.cancelled:
                return None
        return run

    def cancel(self, run_id: str) -> bool:
        run = self.get(run_id)
        if not run:
            return False
        with run.condition:
            run.cancelled = True
            run.condition.notify_all()
        return True

    def stream(self, run: AgentRun, since: int = 0):
        with run.condition:
            run_info = {
                "type": "run",
                "run_id": run.run_id,
                "session_id": run.session_id,
                "done": run.done,
                "seq": run.seq,
            }
        yield {"event": "run", "data": json.dumps(run_info, ensure_ascii=False)}

        next_seq = max(1, int(since or 0) + 1)
        while True:
            pending: list[dict[str, Any]] = []
            done = False
            should_ping = False
            with run.condition:
                while not run.done and not run.cancelled and run.seq < next_seq:
                    run.condition.wait(timeout=15)
                    if run.seq < next_seq:
                        should_ping = True
                        break
                if should_ping:
                    pass
                else:
                    pending = [
                        event for event in run.events
                        if int(event.get("seq", 0)) >= next_seq
                    ]
                    done = run.done or run.cancelled
            if should_ping:
                yield {"event": "ping", "data": "{}"}
                continue
            for event in pending:
                next_seq = int(event["seq"]) + 1
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
            if done and not pending:
                break

    def _execute(self, run: AgentRun):
        try:
            for event in self.agent.chat_stream(run.message, run.session_id):
                if run.cancelled:
                    break
                d = event_to_dict(event)
                self._append(run, d["type"], d)
        except Exception as exc:
            logger.exception("Agent run failed: %s", run.run_id)
            self._append(run, "text", {"type": "text", "content": _stream_error_message(exc)})
        finally:
            self._append(run, "done", {"type": "done"})
            with run.condition:
                run.done = True
                run.updated_at = time.time()
                run.condition.notify_all()
            with self._lock:
                if self._active_by_session.get(run.session_id) == run.run_id:
                    self._active_by_session.pop(run.session_id, None)

    def _append(self, run: AgentRun, event_type: str, data: dict[str, Any]):
        with run.condition:
            run.seq += 1
            item = {
                "seq": run.seq,
                "type": event_type,
                "data": {**data, "seq": run.seq, "run_id": run.run_id},
            }
            run.events.append(item)
            run.updated_at = time.time()
            run.condition.notify_all()


def _make_agent(ontology: Ontology, repository: ObjectRepository,
                registry: FunctionRegistry, llm_config: dict) -> Agent:
    client = OpenAI(
        api_key=llm_config.get("api_key", "sk-placeholder"),
        base_url=llm_config.get("api_url", "http://localhost:8090/v1"),
    )
    model = llm_config.get("model", "qwen3.5-plus")
    harness = Harness(
        ontology, repository, registry, client, model,
        HarnessConfig(
            max_turns=llm_config.get("max_turns", 30),
            max_tool_result_chars=llm_config.get("max_tool_result_chars", 5000),
        ),
    )
    return Agent(harness, client, model)


def create_app(ontology: Ontology, repository: ObjectRepository,
               registry: FunctionRegistry, llm_config: dict,
               domain_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title=f"OAG - {ontology.name}", description=ontology.description)
    agent = _make_agent(ontology, repository, registry, llm_config)
    run_manager = AgentRunManager(agent)
    _domain_dir = Path(domain_dir).resolve() if domain_dir else None

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/prompts")
    def get_prompts():
        if _domain_dir:
            p = _domain_dir / "prompts.json"
            if p.exists():
                return json.loads(p.read_text("utf-8"))
        return []

    @app.get("/schema")
    def get_schema():
        return ontology.model_dump()

    @app.get("/schema/objects")
    def list_objects():
        return {
            name: {
                "kind": obj.kind,
                "description": obj.description,
                "properties": list(obj.properties.keys()),
            }
            for name, obj in ontology.objects.items()
        }

    @app.get("/schema/functions")
    def list_functions():
        return {
            name: fdef.model_dump() if fdef else {}
            for name, fdef in registry.list_functions()
        }

    @app.get("/schema/rules")
    def list_rules():
        return {
            name: rdef.model_dump()
            for name, rdef in ontology.rules.items()
        }

    @app.get("/schema/workflows")
    def list_workflows():
        return {
            name: wdef.model_dump()
            for name, wdef in ontology.workflows.items()
        }

    @app.post("/query")
    async def query(request: Request):
        body = await request.json()
        object_type = body.get("object_type")
        if not object_type:
            return JSONResponse({"error": "object_type is required"}, 400)
        rows = repository.query(object_type, body.get("filters"), body.get("limit"))
        return rows

    @app.post("/function/{name}")
    async def call_function(name: str, request: Request):
        if not registry.has(name):
            return JSONResponse({"error": f"Unknown function: {name}"}, 404)
        body = await request.json() if await request.body() else {}
        result_str = registry.call_as_tool(name, body)
        try:
            return json.loads(result_str)
        except json.JSONDecodeError:
            return {"result": result_str}

    @app.post("/agent/chat")
    async def agent_chat(request: Request):
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("session_id", "default")
        if not message:
            return JSONResponse({"error": "message is required"}, 400)
        reply = agent.chat(message, session_id)
        return {"reply": reply, "session_id": session_id}

    @app.post("/agent/confirm")
    async def agent_confirm(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "default")
        approved = body.get("approved", False)
        answer = body.get("answer")
        if not agent.has_pending(session_id):
            return JSONResponse({"error": "no pending confirmation"}, 400)

        def event_generator():
            try:
                for event in agent.confirm_tool(session_id, approved, answer=answer):
                    d = event_to_dict(event)
                    yield {"event": d["type"], "data": json.dumps(d, ensure_ascii=False)}
            except Exception as exc:
                logger.exception("Agent confirmation stream failed")
                data = {"type": "text", "content": _stream_error_message(exc)}
                yield {"event": "text", "data": json.dumps(data, ensure_ascii=False)}
            yield {"event": "done", "data": "{}"}

        return EventSourceResponse(event_generator())

    @app.get("/agent/chat/stream")
    async def agent_chat_stream(request: Request):
        run_id = request.query_params.get("run_id", "")
        since_raw = request.query_params.get("since", "0")
        try:
            since = max(0, int(since_raw or 0))
        except ValueError:
            since = 0

        if run_id:
            run = run_manager.get(run_id)
            if not run:
                def missing_run_generator():
                    data = {
                        "type": "text",
                        "content": "上一次生成任务已经不存在，请重新提问。",
                        "seq": 1,
                        "run_id": run_id,
                    }
                    yield {"event": "text", "data": json.dumps(data, ensure_ascii=False)}
                    yield {"event": "done", "data": json.dumps({"type": "done", "seq": 2, "run_id": run_id})}

                return EventSourceResponse(missing_run_generator())
            return EventSourceResponse(run_manager.stream(run, since))

        message = request.query_params.get("message", "")
        session_id = request.query_params.get("session_id", "default")
        if not message:
            return JSONResponse({"error": "message is required"}, 400)

        run = run_manager.start(session_id, message)
        return EventSourceResponse(run_manager.stream(run, since=0))

    @app.post("/agent/runs/{run_id}/cancel")
    async def agent_run_cancel(run_id: str):
        if not run_manager.cancel(run_id):
            return JSONResponse({"error": "run not found"}, 404)
        return {"ok": True, "run_id": run_id}

    @app.get("/agent/runs/active")
    async def agent_run_active(request: Request):
        session_id = request.query_params.get("session_id", "default")
        run = run_manager.get_active(session_id)
        if not run:
            return {"run_id": None}
        with run.condition:
            return {
                "run_id": run.run_id,
                "session_id": run.session_id,
                "seq": run.seq,
                "done": run.done,
                "cancelled": run.cancelled,
            }

    @app.get("/agent/history")
    async def agent_history(request: Request):
        session_id = request.query_params.get("session_id", "")
        if not session_id:
            return agent.list_sessions()
        return agent.get_history(session_id)

    @app.get("/agent/context")
    async def agent_context(request: Request):
        session_id = request.query_params.get("session_id", "default")
        return agent.get_context_usage(session_id)

    @app.get("/audit")
    def get_audit():
        limit = 50
        return agent.harness.audit.get_entries(limit)

    return app


def create_multi_app(domain_base: str, llm_config: dict) -> FastAPI:
    app = FastAPI(title="OAG Multi-Domain")
    base = Path(domain_base).resolve()

    domains: dict[str, dict] = {}
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not (d / "ontology.yaml").exists():
            continue
        try:
            ont, repository, reg = load_domain(d)
            sub = create_app(ont, repository, reg, llm_config, domain_dir=d)
            domains[d.name] = {"ontology": ont}
            app.mount(f"/d/{d.name}", sub)
            print(f"  Mounted domain: /d/{d.name} — {ont.description}")
        except Exception as e:
            print(f"  Skip domain {d.name}: {e}")

    @app.get("/")
    def home():
        return FileResponse(STATIC_DIR / "home.html")

    @app.get("/domains")
    def list_domains():
        return [
            {"name": n, "description": info["ontology"].description}
            for n, info in domains.items()
        ]

    return app
