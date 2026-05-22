from oag.registry import FunctionRegistry
from oag.schema import Ontology
from oag.store import Store

DATA_FILES = {
    "DroneClassRule": "drone_class_rule.json",
    "OperatorLicenseRule": "operator_license_rule.json",
    "DamageGradeStandard": "damage_grade_standard.json",
    "EventLevelStandard": "event_level_standard.json",
    "AirspaceRule": "airspace_rule.json",
    "EmergencyFlightRule": "emergency_flight_rule.json",
    "OperationClassRule": "operation_class_rule.json",
}

FIELD_MAPPINGS = {}


def register(registry: FunctionRegistry, store: Store, ontology: Ontology):
    pass
