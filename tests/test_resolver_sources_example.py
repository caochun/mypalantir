import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.harness import Harness, HarnessConfig
from oag.ontology.loader import load_domain
from oag.ontology.data_executor import DataExecutor
from oag.ontology.adapters.json_file import JsonFileAdapter


class DummyClient:
    pass


DOMAIN_DIR = ROOT / "domains" / "examples" / "resolver_sources"


def test_resolver_sources_example_loads_and_queries():
    ontology, store, registry = load_domain(DOMAIN_DIR)
    data = DataExecutor(store, registry)

    profiles = json.loads(data.execute("query", {
        "object_type": "CustomerProfile",
        "filters": {"tier": "gold"},
    }))
    balances = json.loads(data.execute("query", {
        "object_type": "AccountBalance",
        "filters": {"customer_id": "C001"},
        "order_by": "account_id",
    }))
    risk = json.loads(data.execute("query", {
        "object_type": "CustomerRiskView",
        "filters": {"customer_id": "C001"},
    }))

    assert [row["customer_id"] for row in profiles] == ["C001"]
    assert [row["account_id"] for row in balances] == ["A100", "A101"]
    assert risk[0]["total_balance"] == 1300
    assert risk[0]["risk_level"] == "normal"
    assert ontology.objects["CustomerProfile"].source.type == "json_file"
    assert ontology.objects["AccountBalance"].source.type == "sql_view"
    assert ontology.objects["CustomerRiskView"].source.type == "resolver"

    store.close()


def test_resolver_sources_example_query_links_and_search():
    ontology, store, registry = load_domain(DOMAIN_DIR)
    harness = Harness(
        ontology,
        store,
        registry,
        DummyClient(),
        "dummy-model",
        HarnessConfig(enable_write_confirmation=False),
    )

    linked = json.loads(harness.execute_tool("query_links", {
        "source_type": "CustomerProfile",
        "source_id": "C001",
        "link_name": "customer_has_accounts",
    }).content)
    search = json.loads(harness.execute_tool("search", {
        "keyword": "Acme",
        "object_types": ["CustomerProfile"],
    }).content)
    note = json.loads(harness.execute_tool("mutate", {
        "operation": "create",
        "object_type": "InvestigationNote",
        "data": {
            "note_id": "N001",
            "customer_id": "C001",
            "content": "Follow up with account owner.",
        },
    }).content)

    assert [row["account_id"] for row in linked] == ["A100", "A101"]
    assert search[0]["customer_id"] == "C001"
    assert note["inserted"] == 1

    store.close()


def test_json_file_adapter_reads_domain_json_without_sqlite_import(tmp_path):
    source_domain = ROOT / "domains" / "hv_access"
    domain_dir = tmp_path / "hv_access_json_source"
    shutil.copytree(source_domain, domain_dir)

    ontology, store, registry = load_domain(domain_dir)
    data = DataExecutor(store, registry)

    rows = json.loads(data.execute("query", {
        "object_type": "Substation",
        "limit": 1,
    }))
    count = json.loads(data.execute("count", {
        "object_type": "Substation",
    }))

    assert ontology.objects["Substation"].source.type == "json_file"
    assert isinstance(store.adapter_for("Substation"), JsonFileAdapter)
    assert rows[0]["substation_id"]
    assert count["count"] == len(json.loads((domain_dir / "data" / "substation.json").read_text()))

    store.close()
