from __future__ import annotations

from pathlib import Path

from oag.ontology.loader import load_domain


ROOT = Path(__file__).resolve().parents[1]


def test_drone_domain_loads_with_explicit_sources():
    ontology, repo, registry = load_domain(ROOT / "domains" / "drone")

    assert ontology.name == "drone"
    assert registry.has("get_event")
    assert ontology.objects["RoadSegment"].source.type == "json_file"
    assert ontology.objects["DisasterEvent"].source.type == "runtime_memory"
    assert repo.query("RoadSegment", limit=1)
    assert repo.query_by_id("DisasterEvent", "E001")

    repo.insert_record("ClearancePlan", {"plan_id": "P_TEST", "status": "candidate"})
    assert repo.query_by_id("ClearancePlan", "P_TEST")["status"] == "candidate"


def test_icf_domain_loads_with_explicit_sources():
    ontology, repo, registry = load_domain(ROOT / "domains" / "icf")

    assert ontology.name == "icf"
    assert registry.has("execute_node")
    assert ontology.objects["BeamLine"].source.type == "json_file"
    assert ontology.objects["LaunchMission"].source.type == "runtime_memory"
    assert repo.query("BeamLine", limit=1)
    assert repo.query_by_id("LaunchMission", "M001")

    repo.insert_record("FlowNode", {"node_id": "N_TEST", "mission_id": "M001"})
    assert repo.query_by_id("FlowNode", "N_TEST")["mission_id"] == "M001"


def test_fee_domain_loads_with_explicit_sources():
    ontology, repo, registry = load_domain(ROOT / "domains" / "fee")

    assert ontology.name == "fee"
    assert registry.has("build_graph")
    assert ontology.objects["TollStation"].source.type == "fee_json_file"
    assert ontology.objects["Contiguity"].source.type == "runtime_memory"
    assert repo.query("TollStation", limit=1)[0]["station_id"] == "300105"
    assert repo.query("BaseRate", filters={"rate_code": "01", "vehicle_type": 1}, limit=1)

    result = registry.call("build_graph")
    assert result["edges_created"] > 0
    assert repo.query("Contiguity", limit=1)
