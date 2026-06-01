from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from oag.ontology.loader import load_domain


def _ensure_project_root_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _init(env_file: str = ".env"):
    load_dotenv(env_file)
    domain_dir = os.getenv("DOMAIN", "domains/hv_access")

    ontology, repository, registry = load_domain(domain_dir)

    llm_config = {
        "api_key": os.getenv("LLM_API_KEY", "sk-placeholder"),
        "api_url": os.getenv("LLM_API_URL", "http://localhost:8090/v1"),
        "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),
    }

    return ontology, repository, registry, llm_config, domain_dir


@click.group()
def cli():
    """OAG — Ontology Augmented Generation"""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
def serve(host: str, port: int):
    """Start the API server. Set DOMAIN for single-domain mode, or omit for multi-domain."""
    import uvicorn

    from .api import create_app, create_multi_app

    domain_env = os.getenv("DOMAIN", "")
    if domain_env:
        ontology, repository, registry, llm_config, domain_dir = _init()
        app = create_app(ontology, repository, registry, llm_config, domain_dir=domain_dir)
    else:
        load_dotenv()
        llm_config = {
            "api_key": os.getenv("LLM_API_KEY", "sk-placeholder"),
            "api_url": os.getenv("LLM_API_URL", "http://localhost:8090/v1"),
            "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),
        }
        app = create_multi_app("domains", llm_config)

    uvicorn.run(app, host=host, port=port)


@cli.command()
def chat():
    """Interactive agent chat."""
    from oag.runtime.events import (
        CompactEvent, ConfirmationEvent, TextEvent, ToolCallEvent,
    )

    from .api import _make_agent

    ontology, repository, registry, llm_config, _ = _init()
    agent = _make_agent(ontology, repository, registry, llm_config)

    click.echo(f"OAG Agent ({ontology.name}: {ontology.description})")
    click.echo("输入问题开始对话，输入 quit 退出\n")

    while True:
        try:
            message = click.prompt("你", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            break
        if message.strip().lower() in ("quit", "exit", "q"):
            break

        click.echo()
        for event in agent.chat_stream(message):
            if isinstance(event, TextEvent):
                click.echo(event.content, nl=False)
            elif isinstance(event, ToolCallEvent):
                click.echo(f"  ▸ {event.name}", nl=False)
            elif isinstance(event, CompactEvent):
                click.echo("  [对话历史已压缩]")
            elif isinstance(event, ConfirmationEvent):
                click.echo(f"\n  ⚠ 需要确认: {event.reason}")
                if click.confirm("  确认执行?", default=True):
                    for e in agent.confirm_tool(message, True):
                        if isinstance(e, TextEvent):
                            click.echo(e.content, nl=False)
                else:
                    for e in agent.confirm_tool(message, False):
                        if isinstance(e, TextEvent):
                            click.echo(e.content, nl=False)
        click.echo("\n")


@cli.command()
@click.argument("function_name")
@click.argument("args", nargs=-1)
def call(function_name: str, args: tuple):
    """Call a function directly. Args as key=value pairs."""
    ontology, repository, registry, llm_config, _ = _init()

    if not registry.has(function_name):
        click.echo(f"Unknown function: {function_name}")
        available = [name for name, _ in registry.list_functions()]
        click.echo(f"Available: {', '.join(available)}")
        return

    kwargs = {}
    for arg in args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kwargs[k] = v

    result = registry.call_as_tool(function_name, kwargs)
    click.echo(result)


@cli.command()
def info():
    """Show ontology information."""
    ontology, repository, registry, llm_config, _ = _init()

    click.echo(f"Ontology: {ontology.name} — {ontology.description}\n")

    click.echo("Objects:")
    for name, obj in ontology.objects.items():
        kind_label = f" [{obj.kind}]" if obj.kind != "entity" else ""
        count = repository.table_count(name)
        click.echo(f"  {name}{kind_label}: {obj.description} ({count} records)")

    click.echo("\nFunctions:")
    for name, fdef in registry.list_functions():
        desc = fdef.description if fdef else ""
        click.echo(f"  {name}: {desc}")

    click.echo("\nLinks:")
    for name, ldef in ontology.links.items():
        click.echo(f"  {name}: {ldef.source} → {ldef.target}")

    if ontology.rules:
        click.echo("\nRules:")
        for name, rdef in ontology.rules.items():
            applies = ", ".join(rdef.applies_to)
            click.echo(f"  {name} [{rdef.rule_type}]: {rdef.description} (适用: {applies})")

    if ontology.workflows:
        click.echo("\nWorkflows:")
        for name, wdef in ontology.workflows.items():
            steps = " → ".join(s.name for s in wdef.steps)
            click.echo(f"  {name}: {wdef.description} ({steps})")


@cli.group()
def distill():
    """Ontology Builder — 从业务文档生成 OAG domain"""
    pass


@distill.command()
@click.argument("docs_dir")
@click.option("--output", default=None, help="输出目录，默认与 docs_dir 相同")
@click.option("--phase", default=4, type=int, help="运行到指定阶段（0=读文档, 1=建模蓝图, 2=生成本体, 3=审查, 4=修复输出）")
def run(docs_dir: str, output: str | None, phase: int):
    """从文档开始运行 ontology builder pipeline."""
    import logging

    _ensure_project_root_on_path()
    from domains.tools.ontology_builder.llm import load_builder_config
    from domains.tools.ontology_builder.pipeline import DistillerPipeline

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    llm_config = load_builder_config()
    pipeline = DistillerPipeline(docs_dir, output, llm_config)
    pipeline.run(up_to_phase=phase)

    click.echo(f"\nDone. Results in {pipeline.state_dir}/")
    click.echo(pipeline.llm.usage_summary())


@distill.command()
@click.argument("docs_dir")
@click.option("--dry-run", is_flag=True, help="只显示会处理哪些文件，不实际修改")
def extract_images(docs_dir: str, dry_run: bool):
    """用 LLM 将文档中的图片表格转为 Markdown 文本（需要视觉模型）."""
    raise click.ClickException("当前 ontology_builder 版本暂不支持图片表格抽取。")


@distill.command()
@click.argument("state_dir")
def status(state_dir: str):
    """查看 ontology builder pipeline 状态."""

    _ensure_project_root_on_path()
    from domains.tools.ontology_builder.pipeline import DistillerPipeline

    state_path = Path(state_dir).resolve()
    output_dir = state_path.parent if state_path.name == "state" else state_path
    pipeline = DistillerPipeline(str(output_dir), str(output_dir))
    click.echo(pipeline.status())


if __name__ == "__main__":
    cli()
