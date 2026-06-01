import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.ontology.data_executor import DataExecutor
from oag.ontology.loader import load_domain


def test_expand_request_r003_transfer_workflow_regression():
    ontology, store, registry = load_domain(ROOT / "domains" / "hv_access")
    data = DataExecutor(store, registry)

    request = json.loads(data.execute("get_request", {"request_id": "R003"}))
    filter_result = json.loads(data.execute("filter_sources", {
        "request_id": "R003",
        "point_ids": request["original_point_id"],
        "per_path_capacity_kva": request["capacity_kva"],
    }))
    feeder_result = json.loads(data.execute("transfer_feeder_load", {
        "request_id": "R003",
        "source_feeder_id": "F004",
        "required_capacity_kva": 2500,
    }))
    transformer_result = json.loads(data.execute("transfer_transformer_load", {
        "request_id": "R003",
        "source_transformer_id": "MT003",
        "required_capacity_kva": 3500,
    }))

    assert request["request_type"] == "ExpandRequest"
    assert filter_result["passed"] == 0
    assert filter_result["results"][0]["remedy"] == "馈线问题→考虑 transfer_feeder_load"
    assert feeder_result["transfer"]["source_feeder_id"] == "F004"
    assert feeder_result["transfer"]["target_feeder_id"] == "F005"
    assert transformer_result["transfer"]["source_transformer_id"] == "MT003"
    assert transformer_result["transfer"]["target_transformer_id"] == "MT004"

    store.close()


def test_r003_source_requirement_conflict_is_explicit():
    ontology, store, registry = load_domain(ROOT / "domains" / "hv_access")
    data = DataExecutor(store, registry)

    result = json.loads(data.execute("validate_source_requirement", {
        "request_id": "R003",
    }))

    assert result["conflict"] is True
    assert result["check"]["declared_source_structure"] == "单电源"
    assert result["check"]["required_source_structure"] == "双回路"
    assert result["check"]["passed"] == 0
    assert "双回路" in result["next_action"]

    store.close()


def test_r003_transfer_verification_requires_supplementary_loop():
    ontology, store, registry = load_domain(ROOT / "domains" / "hv_access")
    data = DataExecutor(store, registry)

    data.execute("validate_source_requirement", {"request_id": "R003"})
    data.execute("transfer_feeder_load", {
        "request_id": "R003",
        "source_feeder_id": "F004",
        "required_capacity_kva": 2500,
    })
    data.execute("transfer_transformer_load", {
        "request_id": "R003",
        "source_transformer_id": "MT003",
        "required_capacity_kva": 3500,
    })
    verification = json.loads(data.execute("verify_transfer_result", {
        "request_id": "R003",
    }))

    record = verification["verification"]
    assert record["feeder_resolved"] == 1
    assert record["transformer_resolved"] == 1
    assert record["source_requirement_passed"] == 0
    assert record["passed"] == 0
    assert "电源结构冲突" in record["remaining_issues"]
    assert "双回路" in record["next_action"]

    supplement = json.loads(data.execute("search_supplementary_sources", {
        "request_id": "R003",
    }))
    assert supplement["supplement_required"] is True
    assert supplement["required_source_structure"] == "双回路"
    assert supplement["candidates_found"] >= 1
    assert supplement["candidates"][0]["point_id"] == "AP006"
    assert supplement["candidates"][0]["busbar_id"] != "BUS003"

    store.close()


def test_r003_supplementary_loop_composes_only_selected_points():
    ontology, store, registry = load_domain(ROOT / "domains" / "hv_access")
    data = DataExecutor(store, registry)

    plans = json.loads(data.execute("compose_plans", {
        "request_id": "R003",
        "source_structure": "双回路",
        "point_ids": "AP005,AP006",
    }))

    assert plans["plans_generated"] == 3
    assert plans["point_ids"] == "AP005,AP006"
    assert {plan["point_ids"] for plan in plans["plans"]} == {"AP005,AP006"}
    assert all("双回路" in plan["operation_mode"] for plan in plans["plans"])
    assert all("AP001" not in plan["point_ids"] for plan in plans["plans"])

    store.close()


def test_r003_expand_composition_requires_selected_points():
    ontology, store, registry = load_domain(ROOT / "domains" / "hv_access")
    data = DataExecutor(store, registry)

    result = json.loads(data.execute("compose_plans", {
        "request_id": "R003",
        "source_structure": "双回路",
    }))

    assert result["error"] == "增容双回路/双电源方案必须指定 point_ids"
    assert "AP005" in result["hint"]
    assert "不要对增容申请使用全量电源点重新组合" in result["hint"]

    store.close()


def test_transfer_tools_accept_legacy_string_capacity_args():
    ontology, store, registry = load_domain(ROOT / "domains" / "hv_access")
    data = DataExecutor(store, registry)

    feeder_result = json.loads(data.execute("transfer_feeder_load", {
        "request_id": "R003",
        "source_feeder_id": "F004",
        "required_capacity_kva": "2500",
    }))
    transformer_result = json.loads(data.execute("transfer_transformer_load", {
        "request_id": "R003",
        "source_transformer_id": "MT003",
        "required_capacity_kva": "3500",
    }))

    assert "工具执行错误" not in str(feeder_result)
    assert "工具执行错误" not in str(transformer_result)
    assert feeder_result["transfer"]["transfer_capacity_kva"] == 2500
    assert transformer_result["transfer"]["transfer_capacity_kva"] == 3500

    store.close()
