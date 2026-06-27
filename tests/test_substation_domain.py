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
            "search_substation_evidence",
            {
                "query": "阀冷 主循环泵 异常 处理",
                "doc_role": "emergency_procedure",
                "evidence_role": "handling_rule",
                "limit": 5,
            },
        )
    )

    headings = [item["heading"] for item in out["chunks"]]
    assert all("目录" not in heading and "目 录" not in heading for heading in headings)
    assert any("主循环泵异常" in heading for heading in headings)


def test_substation_sample_event_chain_judgement():
    _, repository, registry = _load_substation()
    sample = """
1. 2026-06-14 23:30:01.133 至 2026-06-14 23:43:15.178，站点：泰州站，设备：直流站控系统，事件类型：自动功率升降，二级摘要：自动功率控制输入功率变化速率整定值和目标功率整定值设定命令，随后执行升降命令；历时13分14秒后双极功率升降完成。，事件性质：，告警等级：3
2. 2026-06-14 23:45:00.256 至 2026-06-14 23:58:01.373，站点：泰州站，设备：直流站控系统，事件类型：自动功率升降，二级摘要：自动功率控制输入功率变化速率整定值和目标功率整定值设定命令，随后执行升降命令；历时13分1秒后双极功率升降完成。，事件性质：，告警等级：3
3. 2026-06-14 23:45:13.095 至 2026-06-14 23:50:29.914，站点：泰州站，设备：极2高端阀冷系统，事件类型：阀冷相关操作，二级摘要：极2高端阀冷E5.VK02开关阀关到位信号消失，约7秒后E5.VK02开关阀开到位产生；E5.P01高压泵、E5.J02加药泵停运，历时约5分17秒后E2.J03加药泵、工业水泵、E2.J02加药泵、E4.P01外冷补水泵停运，E5.VK0，事件性质：，告警等级：3
4. 2026-06-14 23:48:21.159 至 2026-06-14 23:48:28.347，站点：泰州站，设备：500kV交流站控系统/1000kV交流站控系统/站用电控制系统/1000kV(合建)交流站控系统/极1高端VCE/极1高端阀组控制系统/极1低端VCE/极2低端VCE，事件类型：辅助系统信息，二级摘要：500kV交流站控系统、1000kV交流站控系统、站用电控制系统、1000kV(合建)交流站控系统、极1高端VCE、极1高端阀组控制系统、极1低端VCE、极2低端VCE下多个故障录波装置及阀测控机箱录波启动告警产生，随后告警相继消失。，事件性质：，告警等级：2
"""

    parsed = json.loads(registry.call_as_tool("parse_substation_events", {"event_text": sample}))
    assert parsed["event_chain"]["event_count"] == 4

    analysed = json.loads(
        registry.call_as_tool(
            "assess_substation_event_chain",
            {"events_json": json.dumps(parsed, ensure_ascii=False), "limit_evidence": 6},
        )
    )
    conclusion = analysed["structured_conclusion"]
    assert conclusion["event_nature"] == "正常"
    assert conclusion["risk_level"] in {"较高", "严重"}
    assert conclusion["evidence_refs"]
    assert "文档依据" in conclusion["reason"]
    assert all("目录" not in ref["heading"] and "目 录" not in ref["heading"] for ref in conclusion["evidence_refs"])
    assert repository.count("StationEvent") == 4
    assert repository.count("EventChain") == 1
    assert repository.count("EventConclusion") == 1


def test_substation_taizhou_tap_change_is_evidence_driven_normal():
    _, _, registry = _load_substation()
    sample = """
1. 2026-06-14 21:56:14.560 至 2026-06-14 21:56:38.708，站点：泰州站，设备：极2低端阀组控制系统，事件类型：变压器档位调整，二级摘要：极2低端换流变822B分接开关操作中，Y侧B/C相及D侧A/B/C相分接开关正在操作，历时约4秒后分接头由22档降至21档，分接开关操作完成。，事件性质：，告警等级：3
"""

    analysed = json.loads(
        registry.call_as_tool(
            "assess_substation_event_chain",
            {"event_text": sample, "limit_evidence": 6},
        )
    )
    conclusion = analysed["structured_conclusion"]

    assert conclusion["event_type"] == "换流变分接开关档位调整"
    assert conclusion["event_nature"] == "正常"
    assert conclusion["risk_level"] == "低"
    assert any(fact["fact_id"] == "transformer_tap_change" and "22档降至21档" in fact["value"] for fact in conclusion["observed_facts"])
    assert any(trigger["trigger_id"] == "tap_inconsistency_alarm" for trigger in conclusion["abnormal_triggers"])
    tap_matches = {
        match["trigger_id"]: match["status"]
        for match in conclusion["trigger_match"]
        if match["trigger_id"].startswith("tap_")
    }
    assert tap_matches
    assert set(tap_matches.values()) == {"not_matched"}
    assert conclusion["evidence_refs"]
    assert conclusion["evidence_refs"][0]["heading"] == "4.12.2 处理"
    assert "泰州" in conclusion["evidence_refs"][0]["md_path"]
    assert all(ref.get("scenario_match") == "transformer_tap_change" for ref in conclusion["evidence_refs"])


def test_substation_parser_accepts_unnumbered_event_text():
    _, _, registry = _load_substation()
    sample = "2026-06-14 21:56:14.560 至 2026-06-14 21:56:38.708，站点：泰州站，设备：极2低端阀组控制系统，事件类型：变压器档位调整，二级摘要：极2低端换流变822B分接开关操作中，历时约4秒后分接头由22档降至21档，分接开关操作完成。，事件性质：，告警等级：3"

    parsed = json.loads(registry.call_as_tool("parse_substation_events", {"event_text": sample}))

    assert parsed["event_chain"]["event_count"] == 1
    event = parsed["events"][0]
    assert event["sequence"] == 1
    assert event["station_name"] == "泰州站"
    assert event["alarm_level"] == 3
    assert event["parse_quality"] in {"high", "medium"}


def test_substation_parser_degrades_to_raw_event_for_loose_input():
    _, _, registry = _load_substation()
    sample = "2026-06-14 21:56:14 至 2026-06-14 21:56:38 泰州站 极2低端换流变分接头由22档降至21档，操作完成，告警等级3"

    analysed = json.loads(
        registry.call_as_tool(
            "assess_substation_event_chain",
            {"event_text": sample, "limit_evidence": 4},
        )
    )

    assert "error" not in analysed
    assert analysed["event_summary"]["event_count"] == 1
    conclusion = analysed["structured_conclusion"]
    assert conclusion["event_type"] == "换流变分接开关档位调整"
    assert conclusion["event_nature"] == "正常"
    assert conclusion["observed_facts"]


def test_substation_parser_preserves_raw_text_without_known_format():
    _, _, registry = _load_substation()
    sample = "2026-06-14 21:56:14.560 泰州站极2低端换流变分接头由22档降至21档，操作完成，未见跳闸闭锁，告警等级3"

    parsed = json.loads(registry.call_as_tool("parse_substation_events", {"event_text": sample}))

    assert parsed["event_chain"]["event_count"] == 1
    event = parsed["events"][0]
    assert event["parse_quality"] == "low"
    assert event["raw_text"] == sample.replace("，", ",")
    assert "分接头由22档降至21档" in event["summary"]

    analysed = json.loads(
        registry.call_as_tool(
            "assess_substation_event_chain",
            {"event_text": sample, "limit_evidence": 4},
        )
    )
    assert "error" not in analysed
    assert analysed["structured_conclusion"]["event_type"] == "换流变分接开关档位调整"


def test_substation_parser_splits_events_by_time_starts_without_numbers():
    _, _, registry = _load_substation()
    sample = """
2026-06-14 21:56:14.560 泰州站极2低端换流变分接头由22档降至21档，操作完成，告警等级3
2026-06-14 21:57:01.000 泰州站多个故障录波启动信号出现后消失，告警等级3
"""

    parsed = json.loads(registry.call_as_tool("parse_substation_events", {"event_text": sample}))

    assert parsed["event_chain"]["event_count"] == 2
    assert [event["sequence"] for event in parsed["events"]] == [1, 2]
    assert "分接头由22档降至21档" in parsed["events"][0]["raw_text"]
    assert "故障录波启动" in parsed["events"][1]["raw_text"]


def test_substation_assessment_returns_compact_result_for_long_chain():
    _, _, registry = _load_substation()
    sample = "\n".join(
        f"2026-06-14 21:{i:02d}:00.000 泰州站第{i + 1}条事件，某设备信号出现后消失，告警等级3"
        for i in range(21)
    )

    analysed_raw = registry.call_as_tool(
        "assess_substation_event_chain",
        {"event_text": sample, "limit_evidence": 4},
    )
    analysed = json.loads(analysed_raw)

    assert "parsed" not in analysed
    assert "case_context" not in analysed
    assert analysed["event_summary"]["event_count"] == 21
    assert analysed["event_summary"]["omitted_event_count"] == 13
    assert "answer_md" in analysed
    assert len(analysed_raw) < 20000


def test_substation_control_response_difference_is_related_not_tap_inconsistency():
    _, _, registry = _load_substation()
    sample = """
1. 2026-01-20 15:48:42.594 至 2026-01-20 15:48:49.429，站点：山阳换流站，设备：站用电开入，事件类型：运方调整-变压器档位调整，二级摘要：35kV 1号站用变有载分接开关机构箱进入切换状态，A/B套主机指令下发存在约127ms差异，约4.4s后显示档位BCD码1，约6.8s后切换中信号消失，档位调整完成。，事件性质：，告警等级：3
2. 2026-01-20 15:48:58.522 至 2026-01-20 15:48:58.588，站点：山阳换流站，设备：交流场，事件类型：变压器档位调整，二级摘要：1号降压变分接开关调节至7档，A、B套主机下发相同指令时间差达66ms，提示指令下发存在异常。，事件性质：，告警等级：3
"""

    analysed_raw = registry.call_as_tool(
        "assess_substation_event_chain",
        {"event_text": sample, "limit_evidence": 5},
    )
    analysed = json.loads(analysed_raw)
    conclusion = analysed["structured_conclusion"]
    matches = {match["trigger_id"]: match for match in conclusion["trigger_match"]}

    assert conclusion["event_nature"] == "需核查"
    assert any(fact.get("fact_category") == "control_response" for fact in conclusion["observed_facts"])
    assert matches["tap_inconsistency_alarm"]["status"] == "related_but_not_matched"
    assert "控制响应差异" in matches["tap_inconsistency_alarm"]["basis"]
    assert "相关但未命中" in analysed["answer_md"]
    assert len(analysed_raw) < 20000


def test_substation_answer_context_explains_ab_system_from_control_docs():
    _, _, registry = _load_substation()

    raw = registry.call_as_tool(
        "prepare_substation_answer_context",
        {"query": "根据文档回答一下：A/B套指令是什么意思", "limit_evidence": 5},
    )
    out = json.loads(raw)

    assert out["intent"] == "concept"
    assert out["evidence"]
    assert any(item["source"]["doc_role"] == "control_protection_spec" for item in out["evidence"])
    joined = "\n".join(item["excerpt"] for item in out["evidence"])
    assert any(term in joined for term in ["冗余", "两套系统", "值班", "备用", "Active", "Standby"])
    assert len(raw) < 12000


def test_substation_answer_context_does_not_overweight_fifth_volume_for_general_concepts():
    _, _, registry = _load_substation()

    out = json.loads(
        registry.call_as_tool(
            "prepare_substation_answer_context",
            {"query": "控制保护系统冗余是什么意思", "limit_evidence": 5},
        )
    )

    assert out["intent"] == "concept"
    assert out["evidence"]
    assert out["evidence"][0]["source"]["doc_role"] == "control_protection_spec"
    assert sum(1 for item in out["evidence"] if item["source"]["doc_role"] == "emergency_procedure") <= 1


def test_substation_answer_context_uses_fifth_volume_for_ab_command_difference():
    _, _, registry = _load_substation()

    raw = registry.call_as_tool(
        "prepare_substation_answer_context",
        {
            "query": "A/B套主机指令下发差异：站用变分接开关切换指令差127ms、降压变分接开关指令差66ms，提示控保双套响应存在不一致。这意味着什么",
            "limit_evidence": 5,
        },
    )
    out = json.loads(raw)

    assert out["intent"] == "diagnosis"
    assert out["evidence"]
    assert any(item["source"]["doc_role"] == "emergency_procedure" for item in out["evidence"])
    joined = "\n".join(
        f"{item['source']['title']} {item['source']['heading']} {item['excerpt']}"
        for item in out["evidence"]
    )
    assert any(term in joined for term in ["分接", "档位"])
    assert len(raw) < 12000


def test_substation_search_evidence_is_compact_locator():
    _, _, registry = _load_substation()

    raw = registry.call_as_tool(
        "search_substation_evidence",
        {"query": "A套 B套 值班 备用 切换 冗余配置", "limit": 8},
    )
    out = json.loads(raw)

    assert out["chunks"]
    assert all("content" not in chunk for chunk in out["chunks"])
    assert all("snippet" in chunk for chunk in out["chunks"])
    assert "prepare_substation_answer_context" in out["usage_note"]
    assert len(raw) < 12000
