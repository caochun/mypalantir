"""End-to-end test: build_graph → compute_fees → find_path → validate_path"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oag.ontology.loader import load_domain
from domains.fee.functions.build_graph import build_graph
from domains.fee.functions.compute_fees import compute_fees
from domains.fee.functions.find_path import find_path
from domains.fee.functions.validate_path import validate_path

DOMAIN_DIR = ROOT / "domains" / "fee"


def setup():
    _ontology, store, _registry = load_domain(DOMAIN_DIR)
    return store


def test_data_loading():
    store = setup()
    assert store.table_count("TollStation") == 4
    assert store.table_count("TollUnit") == 16
    assert store.table_count("BaseRate") == 32
    assert store.table_count("SpecialTimeDiscount") > 0
    assert store.table_count("NoContiguityRule") >= 1
    store.close()


def test_build_graph():
    store = setup()
    result = build_graph(store)
    assert result["edges_created"] > 0
    print(f"  build_graph: {result}")
    store.close()


def test_compute_fees():
    store = setup()
    build_graph(store)
    result = compute_fees(store)
    assert result["params_created"] > 0
    print(f"  compute_fees: {result}")
    store.close()


def test_full_pipeline():
    store = setup()

    g = build_graph(store)
    print(f"  build_graph: {g}")

    c = compute_fees(store)
    print(f"  compute_fees: {c}")

    stations = store.query("TollStation")
    station_map = {}
    for s in stations:
        name = s.get("name", "")
        sid = s.get("station_id", "")
        station_map[name] = sid
        print(f"  Station: {name} -> {sid}")

    en_id = None
    ex_id = None
    for name, sid in station_map.items():
        if "乐陵南" in name:
            en_id = sid
        if "乐陵北" in name:
            ex_id = sid
    assert en_id, "找不到站: 乐陵南"
    assert ex_id, "找不到站: 乐陵北"

    p = find_path(store, en_station_id=en_id, ex_station_id=ex_id, vehicle_type=1)
    print(f"  find_path: {p}")
    assert "error" not in p, f"find_path error: {p.get('error')}"
    assert p["total_fee"] == 1300, f"MTC total_fee expected 1300, got {p['total_fee']}"

    v = validate_path(store, path_id=p["path_id"])
    print(f"  validate_path: {v}")
    assert v["passed"], f"Validation errors: {v['errors']}"

    store.close()


if __name__ == "__main__":
    print("=== test_data_loading ===")
    test_data_loading()
    print("=== test_build_graph ===")
    test_build_graph()
    print("=== test_compute_fees ===")
    test_compute_fees()
    print("=== test_full_pipeline ===")
    test_full_pipeline()
    print("\nAll tests passed!")
