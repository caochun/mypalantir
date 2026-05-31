"""Tests for the 4 new built-in tools: mutate, search, start_workflow, summarize_progress."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.ontology.schema import (
    ObjectSourceDef,
    Ontology,
    ObjectTypeDef,
    PropertyDef,
    WorkflowDef,
    WorkflowStep,
)
from oag.ontology.registry import FunctionRegistry
from oag.ontology.repository import ObjectRepository
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
                source=ObjectSourceDef(type="memory", id_field="name"),
                properties={
                    "name": PropertyDef(type="str", required=True),
                    "age": PropertyDef(type="int"),
                    "city": PropertyDef(type="str"),
                },
            ),
            "Item": ObjectTypeDef(
                kind="entity",
                source=ObjectSourceDef(type="memory", id_field="item_id"),
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


class MemoryAdapter:
    def __init__(self, ontology, object_type, source):
        self.ontology = ontology
        self.object_type = object_type
        self.id_field = source.id_field or ontology.get_id_column(object_type)
        self.rows = []

    def query(self, object_type, filters=None, limit=None, order_by=None, offset=None):
        rows = list(self.rows)
        for key, value in (filters or {}).items():
            field, op = key.split("__", 1) if "__" in key else (key, "eq")
            if op == "like":
                rows = [row for row in rows if value in str(row.get(field, ""))]
            elif op == "ne":
                rows = [row for row in rows if row.get(field) != value]
            else:
                rows = [row for row in rows if row.get(field) == value]
        if order_by:
            reverse = order_by.startswith("-")
            field = order_by.lstrip("-")
            rows = sorted(rows, key=lambda row: row.get(field), reverse=reverse)
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]
        return [dict(row) for row in rows]

    def count(self, object_type, filters=None):
        return len(self.query(object_type, filters))

    def query_by_id(self, object_type, id_value):
        if not self.id_field:
            return None
        rows = self.query(object_type, {self.id_field: id_value}, limit=1)
        return rows[0] if rows else None

    def search_text(self, keyword, object_types=None, limit=20):
        obj_def = self.ontology.objects[self.object_type]
        text_cols = [name for name, prop in obj_def.properties.items() if prop.type == "str"]
        results = []
        for row in self.rows:
            matched = [col for col in text_cols if row.get(col) and keyword in str(row[col])]
            if matched:
                result = dict(row)
                result["_object_type"] = self.object_type
                result["_matched_field"] = ", ".join(matched)
                results.append(result)
            if len(results) >= limit:
                break
        return results

    def insert_record(self, object_type, data):
        row = {
            key: value
            for key, value in data.items()
            if key in self.ontology.objects[self.object_type].properties
        }
        self.rows.append(row)
        return {"inserted": 1, "_id": len(self.rows)}

    def update_record(self, object_type, id_value, data):
        updated = 0
        for row in self.rows:
            if row.get(self.id_field) == id_value:
                row.update({
                    key: value
                    for key, value in data.items()
                    if key in self.ontology.objects[self.object_type].properties
                })
                updated += 1
                break
        return {"updated": updated}

    def delete_record(self, object_type, id_value):
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.get(self.id_field) != id_value]
        return {"deleted": before - len(self.rows)}

    def table_count(self, object_type):
        return len(self.rows)

    def load_data(self, rows):
        self.rows.extend(dict(row) for row in rows)


def _make_repository(ontology):
    registry = FunctionRegistry()
    registry.register_adapter(
        "memory",
        lambda ontology, object_type, source, **kw: MemoryAdapter(
            ontology,
            object_type,
            source,
        ),
    )
    return ObjectRepository(ontology, registry), registry


class _CombinedExecutor:
    """Test helper combining OntologyRuntime + DataExecutor via ToolRegistry."""
    def __init__(self, ontology, repository, registry):
        self.repository = repository
        self.ont = OntologyRuntime(ontology, registry, self.repository)
        self.data = DataExecutor(self.repository, registry)
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


def _make_executor(ontology):
    repository, registry = _make_repository(ontology)
    return _CombinedExecutor(ontology, repository, registry)


# ── mutate: create ──

def test_mutate_create():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": 30, "city": "Beijing"},
    }))
    assert result["inserted"] == 1
    assert "_id" in result

    rows = executor.repository.query("Person", {"name": "Alice"})
    assert len(rows) == 1
    assert rows[0]["age"] == 30
    

def test_mutate_create_missing_required():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"age": 25},
    }))
    assert "error" in result
    assert "name" in str(result["details"])
    

def test_mutate_create_unknown_field():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Bob", "nonexistent": "x"},
    }))
    assert "error" in result
    assert "nonexistent" in str(result["details"])
    

# ── mutate: update ──

def test_mutate_update():
    ont = _make_ontology()
    executor = _make_executor(ont)

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

    rows = executor.repository.query("Person", {"name": "Alice"})
    assert rows[0]["city"] == "Shanghai"
    

def test_mutate_update_no_id():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("mutate", {
        "operation": "update",
        "object_type": "Person",
        "data": {"city": "Shanghai"},
    }))
    assert "error" in result
    

# ── mutate: delete ──

def test_mutate_delete():
    ont = _make_ontology()
    executor = _make_executor(ont)

    executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": 30},
    })
    assert executor.repository.count("Person") == 1

    result = json.loads(executor.execute("mutate", {
        "operation": "delete",
        "object_type": "Person",
        "object_id": "Alice",
    }))
    assert result["deleted"] == 1
    assert executor.repository.count("Person") == 0
    

def test_mutate_unknown_type():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Ghost",
        "data": {"x": 1},
    }))
    assert "error" in result
    

# ── search ──

def test_search_basic():
    ont = _make_ontology()
    executor = _make_executor(ont)
    executor.repository.adapter_for("Person").load_data([
        {"name": "Alice", "age": 30, "city": "Beijing"},
        {"name": "Bob", "age": 25, "city": "Shanghai"},
    ])
    executor.repository.adapter_for("Item").load_data([
        {"item_id": "I1", "title": "Alice in Wonderland", "price": 29.9},
    ])

    result = json.loads(executor.execute("search", {"keyword": "Alice"}))
    assert len(result) >= 2
    types_found = {r["_object_type"] for r in result}
    assert "Person" in types_found
    assert "Item" in types_found
    

def test_search_specific_types():
    ont = _make_ontology()
    executor = _make_executor(ont)
    executor.repository.adapter_for("Person").load_data([
        {"name": "Alice", "age": 30, "city": "Beijing"},
    ])
    executor.repository.adapter_for("Item").load_data([
        {"item_id": "I1", "title": "Alice in Wonderland", "price": 29.9},
    ])

    result = json.loads(executor.execute("search", {
        "keyword": "Alice",
        "object_types": ["Person"],
    }))
    assert all(r["_object_type"] == "Person" for r in result)
    

def test_search_no_results():
    ont = _make_ontology()
    executor = _make_executor(ont)
    executor.repository.adapter_for("Person").load_data([{"name": "Alice", "age": 30}])

    result = json.loads(executor.execute("search", {"keyword": "zzzzz"}))
    assert result == []
    

# ── start_workflow ──

def test_start_workflow():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "onboarding",
    }))
    assert result["workflow"] == "onboarding"
    assert result["current_step"] == "create_account"
    assert result["current_step_index"] == 0
    assert result["total_steps"] == 4
    assert result["next_action"] == "调用 create_user"
    

def test_start_workflow_advance():
    ont = _make_ontology()
    executor = _make_executor(ont)

    executor.execute("start_workflow", {"workflow_name": "onboarding"})

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "onboarding",
        "advance_to_step": "assign_role",
    }))
    assert result["current_step"] == "assign_role"
    assert result["current_step_index"] == 1
    step = [s for s in result["steps"] if s["name"] == "assign_role"][0]
    assert "branches" in step
    

def test_start_workflow_unknown():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "nonexistent",
    }))
    assert "error" in result
    

def test_start_workflow_advance_unknown_step():
    ont = _make_ontology()
    executor = _make_executor(ont)

    executor.execute("start_workflow", {"workflow_name": "onboarding"})

    result = json.loads(executor.execute("start_workflow", {
        "workflow_name": "onboarding",
        "advance_to_step": "nonexistent_step",
    }))
    assert "error" in result
    

# ── build_tools includes new tools ──

def test_build_tools_includes_new():
    ont = _make_ontology()
    repository, registry = _make_repository(ont)
    executor = _CombinedExecutor(ont, repository, registry)

    tools = executor.build_tools()
    names = {t["function"]["name"] for t in tools}
    assert "mutate" in names
    assert "search" in names
    assert "start_workflow" in names
    

# ── type validation ──

def test_mutate_type_validation():
    ont = _make_ontology()
    executor = _make_executor(ont)

    result = json.loads(executor.execute("mutate", {
        "operation": "create",
        "object_type": "Person",
        "data": {"name": "Alice", "age": "not_a_number"},
    }))
    assert "error" in result
    assert any("age" in d for d in result["details"])
    
