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
