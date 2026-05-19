from __future__ import annotations

from oag.registry import FunctionRegistry
from oag.schema import Ontology
from oag.store import Store

from .build_graph import build_graph
from .compute_fees import compute_fees
from .find_path import find_path
from .validate_path import validate_path

FIELD_MAPPINGS = {
    "TollStation": {
        "STATIONID": "station_id", "NAME": "name", "TYPE": "type",
        "TOLLPLAZACOUNT": "toll_plaza_count", "USESTATUS": "use_status",
        "REALTYPE": "real_type", "REGIONNAME": "region_name",
        "COUNTRYNAME": "country_name", "REGIONALISMCODE": "regionalism_code",
        "PROVINCEID": "province_id",
    },
    "TollUnit": {
        "TOLLINTERVALID": "toll_interval_id", "TOLLINTERVALNAME": "toll_interval_name",
        "PROVINCEID": "province_id", "TOLLROADID": "toll_road_id",
        "RATECODE": "rate_code", "SECTIONID": "section_id",
        "STARTORGID": "start_org_id", "STARTORGTYPE": "start_org_type",
        "ENDORGID": "end_org_id", "ENDORGTYPE": "end_org_type",
        "STARTORGNAME": "start_org_name", "ENDORGNAME": "end_org_name",
        "ACTUALLENGTH": "actual_length", "CHARGELENGTH": "charge_length",
        "DIRECTION": "direction", "PROVINCETYPE": "province_type",
        "OPPOSITEID": "opposite_id", "GANTRYID": "gantry_id",
        "GANTRYNAME": "gantry_name", "TOLLFLAG": "toll_flag",
        "ROADTYPE": "road_type", "VERSION": "version", "LASTVER": "lastver",
    },
    "BaseRate": {
        "RATECODE": "rate_code", "VC": "vc", "VCRATE": "vc_rate",
        "PROVINCEID": "province_id", "RATETYPE": "rate_type",
        "RATEDESC": "rate_desc", "VERSION": "version", "LASTVER": "lastver",
    },
    "SpecialTimeDiscount": {
        "TOLLINTERVALID": "toll_interval_id", "STARTDATE": "start_date",
        "ENDDATE": "end_date", "STARTHOUR": "start_hour", "ENDHOUR": "end_hour",
        "VEHILCETYPE": "vehicle_type", "CPCDISCOUNT": "cpc_discount",
        "ETCDISCOUNT": "etc_discount", "FLAG": "flag", "LASTVER": "lastver",
        "VERUSETIME": "verusetime",
    },
    "NoContiguityRule": {
        "ENROADNODEID": "en_road_node_id", "ENROADNODETYPE": "en_road_node_type",
        "EXROADNODEID": "ex_road_node_id", "EXROADNODETYPE": "ex_road_node_type",
        "CONTIGUITYTYPE": "contiguity_type", "VERSION": "version", "LASTVER": "lastver",
    },
}

DATA_FILES = {
    "TollStation": "toll_station.json",
    "TollUnit": "toll_unit.json",
    "BaseRate": "base_rate.json",
    "SpecialTimeDiscount": "special_time_discount.json",
    "NoContiguityRule": "no_contiguity_rule.json",
}


def register(registry: FunctionRegistry, store: Store, ontology: Ontology):
    for name, fn in [
        ("build_graph", build_graph),
        ("compute_fees", compute_fees),
        ("find_path", find_path),
        ("validate_path", validate_path),
    ]:
        func_def = ontology.functions.get(name)
        registry.register(name, lambda s=store, f=fn, **kw: f(s, **kw), func_def)
