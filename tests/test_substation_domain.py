from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from domains.substation.functions import register
from oag.ontology.registry import FunctionRegistry
from oag.ontology.repository import ObjectRepository
from oag.ontology.schema import Ontology


ROOT = Path(__file__).resolve().parents[1]
SUBSTATION_MD_ROOT = ROOT / "domains" / "substation" / "docs_md" / "md"


def _load_substation():
    if not SUBSTATION_MD_ROOT.exists() or not any(SUBSTATION_MD_ROOT.rglob("*.md")):
        pytest.skip("substation extracted markdown is not available locally")
    ontology = Ontology.model_validate(
        yaml.safe_load((ROOT / "domains" / "substation" / "ontology.yaml").read_text(encoding="utf-8"))
    )
    registry = FunctionRegistry()
    repository = ObjectRepository(ontology, registry)
    register(registry, repository, ontology)
    return ontology, repository, registry


def test_substation_valve_cooling_procedure_prefers_body_over_toc():
    _, _, registry = _load_substation()

    out = json.loads(
        registry.call_as_tool(
            "find_relevant_procedures",
            {
                "phenomenon": "阀冷主循环泵异常",
                "device_name": "极2高端阀冷系统",
                "limit": 3,
            },
        )
    )

    headings = [item["heading"] for item in out["procedures"]]
    assert all("目录" not in heading and "目 录" not in heading for heading in headings)
    assert "主循环泵异常" in headings[0]


def test_substation_sample_event_chain_judgement():
    _, _, registry = _load_substation()
    sample = """
1. 2026-06-14 23:30:01.133 至 2026-06-14 23:43:15.178，站点：泰州站，设备：直流站控系统，事件类型：自动功率升降，二级摘要：自动功率控制输入功率变化速率整定值和目标功率整定值设定命令，随后执行升降命令；历时13分14秒后双极功率升降完成。，事件性质：，告警等级：3
2. 2026-06-14 23:45:00.256 至 2026-06-14 23:58:01.373，站点：泰州站，设备：直流站控系统，事件类型：自动功率升降，二级摘要：自动功率控制输入功率变化速率整定值和目标功率整定值设定命令，随后执行升降命令；历时13分1秒后双极功率升降完成。，事件性质：，告警等级：3
3. 2026-06-14 23:45:13.095 至 2026-06-14 23:50:29.914，站点：泰州站，设备：极2高端阀冷系统，事件类型：阀冷相关操作，二级摘要：极2高端阀冷E5.VK02开关阀关到位信号消失，约7秒后E5.VK02开关阀开到位产生；E5.P01高压泵、E5.J02加药泵停运，历时约5分17秒后E2.J03加药泵、工业水泵、E2.J02加药泵、E4.P01外冷补水泵停运，E5.VK0，事件性质：，告警等级：3
4. 2026-06-14 23:48:21.159 至 2026-06-14 23:48:28.347，站点：泰州站，设备：500kV交流站控系统/1000kV交流站控系统/站用电控制系统/1000kV(合建)交流站控系统/极1高端VCE/极1高端阀组控制系统/极1低端VCE/极2低端VCE，事件类型：辅助系统信息，二级摘要：500kV交流站控系统、1000kV交流站控系统、站用电控制系统、1000kV(合建)交流站控系统、极1高端VCE、极1高端阀组控制系统、极1低端VCE、极2低端VCE下多个故障录波装置及阀测控机箱录波启动告警产生，随后告警相继消失。，事件性质：，告警等级：2
"""

    parsed = json.loads(registry.call_as_tool("parse_event_chain", {"event_text": sample}))
    assert parsed["event_chain"]["event_count"] == 4

    analysed = json.loads(
        registry.call_as_tool(
            "analyze_event_chain",
            {"events": json.dumps(parsed, ensure_ascii=False), "require_citations": True},
        )
    )
    assert analysed["interpretation"]["anomaly_judgement"] == "可能正常"
    assert analysed["evidence"]["chunks"]
