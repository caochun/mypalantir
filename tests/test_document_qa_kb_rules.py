from __future__ import annotations

from domains.document_qa.functions.index import (
    DOCUMENT_KB_EXTRACTOR_VERSION,
    classify_enhanced_relation_type,
    document_kb_signature,
    extract_doc_numbers,
)


def test_extract_doc_numbers_normalizes_common_chinese_references():
    assert extract_doc_numbers("依据郑政〔2024〕12号和郑水函[2023]8号执行") == [
        "郑政〔2024〕12",
        "郑水函〔2023〕8",
    ]


def test_classify_enhanced_relation_type_uses_local_evidence_context():
    doc = {
        "title": "关于水务事项的通知",
        "relation_text": "第一段只是落实总体要求。\n第二段根据郑政〔2024〕12号办理。",
    }

    assert classify_enhanced_relation_type(doc, "郑政〔2024〕12", default="cites_by_doc_no") == "based_on"


def test_document_kb_signature_changes_with_extractor_version():
    doc = {"title": "测试文档"}
    signature = document_kb_signature(doc)

    assert str(DOCUMENT_KB_EXTRACTOR_VERSION)
    assert signature == document_kb_signature(doc)
