from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .registry import FunctionRegistry
from .schema import Ontology
from .store import Store


def load_domain(domain_dir: str | Path) -> tuple[Ontology, Store, FunctionRegistry]:
    domain_dir = Path(domain_dir).resolve()

    ontology = Ontology.load(domain_dir / "ontology.yaml")
    store = Store(ontology)
    store.create_tables()

    func_pkg = _import_functions(domain_dir / "functions")

    data_dir = domain_dir / "data"
    data_files = getattr(func_pkg, "DATA_FILES", {})
    field_mappings = getattr(func_pkg, "FIELD_MAPPINGS", {})

    for type_name, filename in data_files.items():
        mapping = field_mappings.get(type_name)
        n = store.load_json_file(type_name, data_dir / filename, mapping)
        if n > 0:
            print(f"  Loaded {n} records into {type_name}")

    registry = FunctionRegistry()
    func_pkg.register(registry, store, ontology)

    return ontology, store, registry


def _import_functions(functions_dir: Path):
    pkg_name = f"_domain_{functions_dir.parent.name}_functions"
    init_file = functions_dir / "__init__.py"

    spec = importlib.util.spec_from_file_location(
        pkg_name, init_file,
        submodule_search_locations=[str(functions_dir)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = module
    spec.loader.exec_module(module)
    return module
