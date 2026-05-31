"""Tests for the 4 new built-in tools: mutate, search, start_workflow, summarize_progress."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.ontology.schema import Ontology, ObjectTypeDef, PropertyDef, WorkflowDef, WorkflowStep
from oag.ontology.store import Store
from oag.ontology.registry import FunctionRegistry
from oag.harness import Harness, HarnessConfig
from oag.ontology.data_executor import DataExecutor
from oag.ontology.runtime import OntologyRuntime
from oag.tools.registry import ToolRegistry


def _make_ontology():
    return Ontology(
        name="test",
        objects={
            "Person": ObjectTypeDef(
                kind="entity",
                properties={
                    "name": PropertyDef(type="str", required=True),
                    "age": PropertyDef(type="int"),
                    "city": PropertyDef(type="str"),
                },
            ),
            "Item": ObjectTypeDef(
                kind="entity",
                properties={
                    "item_id": PropertyDef(type="str", required=True),
                    "title": PropertyDef(type="str"),
                    "price": PropertyDef(type="float"),
                },
            ),
        },
        workflows={
            "onboarding": WorkflowDef(
                description="新员工入职流程",
                trigger="new_hire",
                steps=[
                    WorkflowStep(name="create_account", function="create_user", description="创建账号", next="assign_role"),
                    WorkflowStep(name="assign_role", function="set_role", description="分配角色", next={"admin": "setup_admin", "user": "done"}),
                    WorkflowStep(name="setup_admin", function="admin_setup", description="管理员配置", next="done"),
                    WorkflowStep(name="done", description="完成"),
                ],
            ),
        },
    )


def _make_store(ontology):
    store = Store(ontology)
    store.create_tables()
    return store


class _CombinedExecutor:
    """Test helper combining OntologyRuntime + DataExecutor via ToolRegistry."""
    def __init__(self, ontology, store, registry):
        self.ont = OntologyRuntime(ontology, store, registry)
        self.data = DataExecutor(store, registry)
        self.tools = ToolRegistry()
        self.ont.register_tools(self.tools, self.data)

    def execute(self, name, args):
        tool = self.tools.get(name)
        if tool:
            if name == "mutate":
                pre_check = self.ont.validate_mutate(args)
                if pre_check:
                    return pre_check
            return tool.handler(args)
        return self.data.execute(name, args)

    def validate_mutate(self, args):
        return self.ont.validate_mutate(args)

    def build_tools(self):
        return self.tools.build_tools()


def _make_executor(ontology, store):
    registry = FunctionRegistry()
    return _CombinedExecutor(ontology, store, registry)


# ── mutate: create ──

def test_mutate_create():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": 30, "city": "Beijing"},
    }))
    assert result["inserted"] == 1
    assert "_id" in result

    rows = store.query("Person", {"name": "Alice"})
    assert len(rows) == 1
    assert rows[0]["age"] == 30
    store.close()


def test_mutate_create_missing_required():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"age": 25},
    }))
    assert "error" in result
    assert "name" in str(result["details"])
    store.close()


def test_mutate_create_unknown_field():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Bob", "nonexistent": "x"},
    }))
    assert "error" in result
    assert "nonexistent" in str(result["details"])
    store.close()


# ── mutate: update ──

def test_mutate_update():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": 30, "city": "Beijing"},
    })

    result = json.loads(executor.execute("mutate", {
        "operation": "update",
        "object_type": "Person",
        "object_id": "Alice",
        "data": {"city": "Shanghai"},
    }))
    assert result["updated"] == 1

    rows = store.query("Person", {"name": "Alice"})
    assert rows[0]["city"] == "Shanghai"
    store.close()


def test_mutate_update_no_id():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("mutate", {
        "operation": "update",
        "object_type": "Person",
        "data": {"city": "Shanghai"},
    }))
    assert "error" in result
    store.close()


# ── mutate: delete ──

def test_mutate_delete():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": 30},
    })
    assert store.count("Person") == 1

    result = json.loads(executor.execute("mutate", {
        "operation": "delete",
        "object_type": "Person",
        "object_id": "Alice",
    }))
    assert result["deleted"] == 1
    assert store.count("Person") == 0
    store.close()


def test_mutate_unknown_type():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Ghost",
        "data": {"x": 1},
    }))
    assert "error" in result
    store.close()


# ── search ──

def test_search_basic():
    ont = _make_ontology()
    store = _make_store(ont)
    store.load_data("Person", [
        {"name": "Alice", "age": 30, "city": "Beijing"},
        {"name": "Bob", "age": 25, "city": "Shanghai"},
    ])
    store.load_data("Item", [
        {"item_id": "I1", "title": "Alice in Wonderland", "price": 29.9},
    ])
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("search", {"keyword": "Alice"}))
    assert len(result) >= 2
    types_found = {r["_object_type"] for r in result}
    assert "Person" in types_found
    assert "Item" in types_found
    store.close()


def test_search_specific_types():
    ont = _make_ontology()
    store = _make_store(ont)
    store.load_data("Person", [
        {"name": "Alice", "age": 30, "city": "Beijing"},
    ])
    store.load_data("Item", [
        {"item_id": "I1", "title": "Alice in Wonderland", "price": 29.9},
    ])
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("search", {
        "keyword": "Alice",
        "object_types": ["Person"],
    }))
    assert all(r["_object_type"] == "Person" for r in result)
    store.close()


def test_search_no_results():
    ont = _make_ontology()
    store = _make_store(ont)
    store.load_data("Person", [{"name": "Alice", "age": 30}])
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("search", {"keyword": "zzzzz"}))
    assert result == []
    store.close()


# ── start_workflow ──

def test_start_workflow():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "onboarding",
    }))
    assert result["workflow"] == "onboarding"
    assert result["current_step"] == "create_account"
    assert result["current_step_index"] == 0
    assert result["total_steps"] == 4
    assert result["next_action"] == "调用 create_user"
    store.close()


def test_start_workflow_advance():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    executor.execute("start_workflow", {"workflow_name": "onboarding"})

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "onboarding",
        "advance_to_step": "assign_role",
    }))
    assert result["current_step"] == "assign_role"
    assert result["current_step_index"] == 1
    step = [s for s in result["steps"] if s["name"] == "assign_role"][0]
    assert "branches" in step
    store.close()


def test_start_workflow_unknown():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "nonexistent",
    }))
    assert "error" in result
    store.close()


def test_start_workflow_advance_unknown_step():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    executor.execute("start_workflow", {"workflow_name": "onboarding"})

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "onboarding",
        "advance_to_step": "nonexistent_step",
    }))
    assert "error" in result
    store.close()


# ── build_tools includes new tools ──

def test_build_tools_includes_new():
    ont = _make_ontology()
    store = _make_store(ont)
    registry = FunctionRegistry()
    executor = _CombinedExecutor(ont, store, registry)

    tools = executor.build_tools()
    names = {t["function"]["name"] for t in tools}
    assert "mutate" in names
    assert "search" in names
    assert "start_workflow" in names
    store.close()


# ── type validation ──

def test_mutate_type_validation():
    ont = _make_ontology()
    store = _make_store(ont)
    executor = _make_executor(ont, store)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": "not_a_number"},
    }))
    assert "error" in result
    assert any("age" in d for d in result["details"])
    store.close()
