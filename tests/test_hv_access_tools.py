import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.ontology.data_executor import DataExecutor
from oag.ontology.loader import load_domain


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
