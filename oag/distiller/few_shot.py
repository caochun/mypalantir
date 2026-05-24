from __future__ import annotations

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_REFERENCE_DOMAINS = ("fee", "road_emergency")


def _load_ontology(domains_dir: Path, domain_name: str) -> dict | None:
    path = domains_dir / domain_name / "ontology.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def load_workflow_few_shot(domains_dir: Path) -> str:
    """Phase 1: show an example workflow derived from road_emergency functions."""
    ont = _load_ontology(domains_dir, "road_emergency")
    if not ont:
        return "(无参考工作流)"

    funcs = ont.get("functions", {})
    business_funcs = []
    for name, fdef in funcs.items():
        hint = fdef.get("hint", "")
        if hint and len(hint) > 50:
            deps = fdef.get("depends_on", [])
            business_funcs.append((name, fdef.get("summary", ""), deps))

    if not business_funcs:
        return "(无参考工作流)"

    lines = ["### road_emergency domain 的业务流程示例", ""]
    lines.append("该领域的 Agent 按以下流程处理公路应急事件：")
    lines.append("")
    for name, summary, deps in business_funcs[:10]:
        dep_str = f" (前置: {', '.join(deps)})" if deps else ""
        lines.append(f"- `{name}`: {summary}{dep_str}")
    lines.append("")
    lines.append("每个业务函数对应一个工作流步骤，writes_to 标注产出的过程记录。")
    return "\n".join(lines)


def load_objects_few_shot(domains_dir: Path) -> str:
    """Phase 2: show object lists from reference domains."""
    lines = []
    for domain_name in _REFERENCE_DOMAINS:
        ont = _load_ontology(domains_dir, domain_name)
        if not ont:
            continue
        objects = ont.get("objects", {})
        lines.append(f"### {domain_name} domain ({len(objects)} 个对象)")
        for name, obj in objects.items():
            summary = obj.get("summary", obj.get("description", ""))
            lines.append(f"- **{name}**: {summary}")
        lines.append("")
    return "\n".join(lines) if lines else "(无参考对象)"


def load_attributes_few_shot(domains_dir: Path) -> str:
    """Phase 3: show object properties from road_emergency."""
    ont = _load_ontology(domains_dir, "road_emergency")
    if not ont:
        return ""

    lines = ["### road_emergency domain 属性示例", ""]
    objects = ont.get("objects", {})
    shown = 0
    for name, obj in objects.items():
        props = obj.get("properties", {})
        if not props or shown >= 3:
            continue
        lines.append(f"**{name}** ({obj.get('summary', '')})")
        for pname, pdef in list(props.items())[:5]:
            req = " [required]" if pdef.get("required") else ""
            lines.append(f"  - {pname}: {pdef.get('type', 'str')}{req} — {pdef.get('description', '')}")
        lines.append("")
        shown += 1
    return "\n".join(lines)


def load_links_few_shot(domains_dir: Path) -> str:
    """Phase 4: show relationship examples."""
    lines = ["### 关系示例（来自 fee domain）", ""]
    ont = _load_ontology(domains_dir, "fee")
    if ont:
        links = ont.get("links", {})
        for name, link in list(links.items())[:5]:
            src = link.get("source", "")
            tgt = link.get("target", "")
            join = link.get("join", {})
            desc = link.get("description", "")
            lines.append(f"```yaml")
            lines.append(f"{name}:")
            lines.append(f"  source: {src}")
            lines.append(f"  target: {tgt}")
            lines.append(f"  join: {{source_key: {join.get('source_key', '')}, target_key: {join.get('target_key', '')}}}")
            lines.append(f"  description: {desc}")
            lines.append(f"```")
            lines.append("")

    ont_re = _load_ontology(domains_dir, "road_emergency")
    if ont_re:
        links = ont_re.get("links", {})
        if links:
            lines.append("### 关系示例（来自 road_emergency domain）")
            lines.append("")
            for name, link in list(links.items())[:5]:
                src = link.get("source", "")
                tgt = link.get("target", "")
                join = link.get("join", {})
                desc = link.get("description", "")
                lines.append(f"- `{name}`: {src}.{join.get('source_key', '')} → {tgt}.{join.get('target_key', '')} ({desc})")
            lines.append("")

    return "\n".join(lines) if len(lines) > 2 else ""


def load_functions_few_shot(domains_dir: Path) -> str:
    """Phase 5: show function design examples including hints."""
    ont = _load_ontology(domains_dir, "road_emergency")
    if not ont:
        return ""

    funcs = ont.get("functions", {})
    lines = ["### road_emergency domain 函数设计参考", ""]

    categories = {"业务编排": [], "规则查询": [], "接口查询": []}
    for name, fdef in funcs.items():
        hint = fdef.get("hint", "")
        if name.startswith("lookup_"):
            categories["规则查询"].append((name, fdef))
        elif hint and len(hint) > 50:
            categories["业务编排"].append((name, fdef))
        else:
            categories["接口查询"].append((name, fdef))

    for cat_name, items in categories.items():
        if not items:
            continue
        lines.append(f"**{cat_name}函数** ({len(items)} 个)")
        for name, fdef in items[:3]:
            summary = fdef.get("summary", "")
            group = fdef.get("group", "")
            deps = fdef.get("depends_on", [])
            hint = fdef.get("hint", "")
            lines.append(f"- `{name}`: {summary} [group: {group}]")
            if deps:
                lines.append(f"  depends_on: {deps}")
            if hint and len(hint) > 10:
                hint_preview = hint[:200] + "..." if len(hint) > 200 else hint
                lines.append(f"  hint: {hint_preview}")
        lines.append("")

    return "\n".join(lines)


def load_hint_few_shot(domains_dir: Path) -> str:
    """Phase 6: show hint writing examples."""
    ont = _load_ontology(domains_dir, "road_emergency")
    if not ont:
        return ""

    funcs = ont.get("functions", {})
    lines = ["### Hint 写作参考", ""]

    for name, fdef in funcs.items():
        hint = fdef.get("hint", "")
        if not hint or len(hint) < 80:
            continue
        func_type = "lookup" if name.startswith("lookup_") else "业务编排"
        lines.append(f"**{name}** ({func_type}函数)")
        lines.append(f"```")
        lines.append(hint.strip())
        lines.append(f"```")
        lines.append("")
        if len(lines) > 40:
            break

    return "\n".join(lines)


def load_summary_few_shot(domains_dir: Path) -> str:
    """Phase 7: show good summary style."""
    ont = _load_ontology(domains_dir, "road_emergency")
    if not ont:
        return ""

    lines = ["### Summary 风格参考（road_emergency domain）", ""]
    lines.append("对象 summary 示例：")
    objects = ont.get("objects", {})
    for name, obj in list(objects.items())[:8]:
        lines.append(f'- {name}: "{obj.get("summary", "")}"')
    lines.append("")

    lines.append("函数 summary 示例：")
    funcs = ont.get("functions", {})
    for name, fdef in list(funcs.items())[:8]:
        lines.append(f'- {name}: "{fdef.get("summary", "")}"')

    return "\n".join(lines)
