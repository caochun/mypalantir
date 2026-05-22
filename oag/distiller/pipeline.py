from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .concept import discover_concepts, save_concepts
from .document import DocumentIndex, prepare_documents
from .llm import DistillerLLM

log = logging.getLogger(__name__)

PHASE_NAMES = {
    0: "文档准备",
    1: "概念发现",
    2: "属性丰富",
    3: "关系发现",
    4: "函数发现",
    5: "规则提取与Prompt优化",
    6: "组装ontology",
}


class DistillerPipeline:

    def __init__(self, docs_dir: str | Path, output_dir: str | Path | None = None, llm_config: dict | None = None):
        self.docs_dir = Path(docs_dir).resolve()
        self.output_dir = Path(output_dir).resolve() if output_dir else self.docs_dir
        self.state_dir = self.output_dir / ".distill"
        self.state_file = self.state_dir / "state.yaml"
        self.llm = DistillerLLM(llm_config)
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file) as f:
                return yaml.safe_load(f) or {}
        return {
            "docs_dir": str(self.docs_dir),
            "output_dir": str(self.output_dir),
            "current_phase": -1,
            "phases": {},
        }

    def _save_state(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            yaml.dump(self.state, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def run(self, up_to_phase: int = 1):
        for phase in range(up_to_phase + 1):
            phase_state = self.state.get("phases", {}).get(str(phase), {})
            if phase_state.get("status") == "completed":
                log.info("Phase %d (%s) already completed, skipping", phase, PHASE_NAMES.get(phase, "?"))
                continue

            log.info("=== Phase %d: %s ===", phase, PHASE_NAMES.get(phase, "?"))
            self._run_phase(phase)
            self.state["current_phase"] = phase
            self.state.setdefault("phases", {})[str(phase)] = {"status": "completed", "output": self._phase_output_name(phase)}
            self._save_state()

        log.info("Pipeline complete up to phase %d. %s", up_to_phase, self.llm.usage_summary())

    def _run_phase(self, phase: int):
        if phase == 0:
            self._run_phase0()
        elif phase == 1:
            self._run_phase1()
        elif phase == 2:
            self._run_phase2()
        elif phase == 3:
            self._run_phase3()
        elif phase == 4:
            self._run_phase4()
        elif phase == 5:
            self._run_phase5()
        elif phase == 6:
            self._run_phase6()
        else:
            raise ValueError(f"Phase {phase} not implemented yet")

    def _run_phase0(self):
        index = prepare_documents(self.docs_dir, self.llm)
        index.save(self.state_dir / "doc_index.yaml")

    def _run_phase1(self):
        index_path = self.state_dir / "doc_index.yaml"
        if not index_path.exists():
            raise FileNotFoundError(f"Phase 0 output not found: {index_path}. Run phase 0 first.")

        index = DocumentIndex.load(index_path)
        index.chunks = []
        for md_file in sorted(self.docs_dir.glob("*.md")):
            from .document import chunk_markdown
            text = md_file.read_text(encoding="utf-8")
            index.chunks.extend(chunk_markdown(text, md_file.name))

        result = discover_concepts(
            index, self.llm, self.docs_dir,
            domains_dir=self.docs_dir.parent,
        )
        save_concepts(result, self.state_dir / "phase1_concepts.yaml")

    def _run_phase2(self):
        concepts_path = self.state_dir / "phase1_concepts.yaml"
        if not concepts_path.exists():
            raise FileNotFoundError(f"Phase 1 output not found: {concepts_path}. Run phase 1 first.")

        from .attribute import enrich_attributes, save_schema
        schema = enrich_attributes(concepts_path, self.docs_dir, self.llm)
        save_schema(schema, self.state_dir / "phase2_schema.yaml")

    def _run_phase3(self):
        schema_path = self.state_dir / "phase2_schema.yaml"
        if not schema_path.exists():
            raise FileNotFoundError(f"Phase 2 output not found: {schema_path}. Run phase 2 first.")

        from .relationship import discover_relationships, save_relationships
        result = discover_relationships(schema_path, self.docs_dir, self.llm)
        save_relationships(result, self.state_dir)

    def _run_phase6(self):
        from .assemble import assemble_ontology, save_ontology
        ontology = assemble_ontology(self.state_dir)
        save_ontology(ontology, self.output_dir / "ontology.yaml")

    def _run_phase5(self):
        functions_path = self.state_dir / "phase4_functions.yaml"
        schema_path = self.state_dir / "phase3_schema.yaml"
        if not functions_path.exists():
            raise FileNotFoundError(f"Phase 4 output not found: {functions_path}. Run phase 4 first.")

        from .rule import extract_rules, save_enriched_functions
        enriched = extract_rules(functions_path, schema_path, self.docs_dir, self.llm)
        save_enriched_functions(enriched, self.state_dir / "phase5_functions.yaml")

    def _run_phase4(self):
        schema_path = self.state_dir / "phase3_schema.yaml"
        links_path = self.state_dir / "phase3_links.yaml"
        if not schema_path.exists():
            raise FileNotFoundError(f"Phase 3 output not found: {schema_path}. Run phase 3 first.")

        from .function import discover_functions, save_functions
        result = discover_functions(schema_path, links_path, self.docs_dir, self.llm)
        save_functions(result, self.state_dir / "phase4_functions.yaml")

    def _phase_output_name(self, phase: int) -> str:
        return {0: "doc_index.yaml", 1: "phase1_concepts.yaml", 2: "phase2_schema.yaml", 3: "phase3_links.yaml", 4: "phase4_functions.yaml", 5: "phase5_functions.yaml", 6: "ontology.yaml"}.get(phase, f"phase{phase}.yaml")

    def status(self) -> str:
        lines = [f"Distiller state: {self.state_dir}"]
        lines.append(f"Docs: {self.state.get('docs_dir', '?')}")
        lines.append(f"Current phase: {self.state.get('current_phase', -1)}")
        phases = self.state.get("phases", {})
        for p in range(max(int(k) for k in phases) + 1 if phases else 0):
            ps = phases.get(str(p), {})
            name = PHASE_NAMES.get(p, f"Phase {p}")
            status = ps.get("status", "pending")
            output = ps.get("output", "")
            lines.append(f"  Phase {p} ({name}): {status} -> {output}")
        return "\n".join(lines)
