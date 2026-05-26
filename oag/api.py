from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .events import event_to_dict
from .loader import load_domain
from .orchestrator import Orchestrator
from .registry import FunctionRegistry
from .schema import Ontology
from .store import Store

STATIC_DIR = Path(__file__).parent / "static"


def create_app(ontology: Ontology, store: Store,
               registry: FunctionRegistry, llm_config: dict,
               domain_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title=f"OAG - {ontology.name}", description=ontology.description)
    orch = Orchestrator(ontology, store, registry, llm_config)
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
        rows = store.query(object_type, body.get("filters"), body.get("limit"))
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
        reply = orch.chat(message, session_id)
        return {"reply": reply, "session_id": session_id}

    @app.post("/agent/confirm")
    async def agent_confirm(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "default")
        approved = body.get("approved", False)
        if not orch.agent.has_pending(session_id):
            return JSONResponse({"error": "no pending confirmation"}, 400)

        def event_generator():
            for event in orch.agent.confirm_tool(session_id, approved):
                d = event_to_dict(event)
                yield {"event": d["type"], "data": json.dumps(d, ensure_ascii=False)}

        return EventSourceResponse(event_generator())

    @app.get("/agent/chat/stream")
    async def agent_chat_stream(request: Request):
        message = request.query_params.get("message", "")
        session_id = request.query_params.get("session_id", "default")
        if not message:
            return JSONResponse({"error": "message is required"}, 400)

        def event_generator():
            for event in orch.chat_stream(message, session_id):
                d = event_to_dict(event)
                yield {"event": d["type"], "data": json.dumps(d, ensure_ascii=False)}
            yield {"event": "done", "data": "{}"}

        return EventSourceResponse(event_generator())

    @app.get("/agent/history")
    async def agent_history(request: Request):
        session_id = request.query_params.get("session_id", "")
        if not session_id:
            return orch.list_sessions()
        return orch.get_history(session_id)

    @app.get("/audit")
    def get_audit():
        limit = 50
        return orch.harness.audit.get_entries(limit)

    return app


def create_multi_app(domain_base: str, llm_config: dict) -> FastAPI:
    app = FastAPI(title="OAG Multi-Domain")
    base = Path(domain_base).resolve()

    domains: dict[str, dict] = {}
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not (d / "ontology.yaml").exists():
            continue
        try:
            ont, store, reg = load_domain(d)
            sub = create_app(ont, store, reg, llm_config, domain_dir=d)
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
