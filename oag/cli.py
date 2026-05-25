from __future__ import annotations

import os
from pathlib import Path

import click
from dotenv import load_dotenv

from .loader import load_domain


def _init(env_file: str = ".env"):
    load_dotenv(env_file)
    domain_dir = os.getenv("DOMAIN", "domains/fee")

    ontology, store, registry = load_domain(domain_dir)

    llm_config = {
        "api_key": os.getenv("LLM_API_KEY", "sk-placeholder"),
        "api_url": os.getenv("LLM_API_URL", "http://localhost:8090/v1"),
        "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),
    }

    return ontology, store, registry, llm_config, domain_dir


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

    domain_env = os.getenv("DOMAIN", "")
    if domain_env:
        from .api import create_app
        ontology, store, registry, llm_config, domain_dir = _init()
        app = create_app(ontology, store, registry, llm_config, domain_dir=domain_dir)
    else:
        from .api import create_multi_app
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
    """Interactive agent chat (with multi-agent pipeline)."""
    from .orchestrator import Orchestrator

    ontology, store, registry, llm_config, _ = _init()
    orch = Orchestrator(ontology, store, registry, llm_config)

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
        for event in orch.chat_stream(message):
            etype = event["type"]
            if etype == "text":
                click.echo(event["content"], nl=False)
            elif etype == "planning":
                click.echo(f"  [{event['content']}]")
            elif etype == "plan":
                import json as _json
                plan_data = _json.loads(event["content"])
                for s in plan_data.get("steps", []):
                    click.echo(f"  计划步骤{s['step_id']}: {s['target']} — {s['purpose']}")
            elif etype == "step_start":
                click.echo(f"\n  [步骤{event['step_id']}: {event['target']} — {event['purpose']}]", nl=False)
            elif etype == "step_done":
                click.echo(f" → {event['status']}")
            elif etype == "synthesizing":
                click.echo(f"\n  [{event['content']}]\n")
            elif etype == "tool_call":
                click.echo(f"\n  [调用 {event['name']}({event['arguments']})]", nl=False)
            elif etype == "tool_result":
                result = event["result"]
                if len(result) > 200:
                    result = result[:200] + "..."
                click.echo(f"\n  [结果: {result}]", nl=False)
        click.echo("\n")


@cli.command()
@click.argument("function_name")
@click.argument("args", nargs=-1)
def call(function_name: str, args: tuple):
    """Call a function directly. Args as key=value pairs."""
    ontology, store, registry, llm_config, _ = _init()

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
    ontology, store, registry, llm_config, _ = _init()

    click.echo(f"Ontology: {ontology.name} — {ontology.description}\n")

    click.echo("Objects:")
    for name, obj in ontology.objects.items():
        count = store.table_count(name)
        click.echo(f"  {name}: {obj.description} ({count} records)")

    click.echo("\nFunctions:")
    for name, fdef in registry.list_functions():
        desc = fdef.description if fdef else ""
        click.echo(f"  {name}: {desc}")

    click.echo("\nLinks:")
    for name, ldef in ontology.links.items():
        click.echo(f"  {name}: {ldef.source} → {ldef.target}")


@cli.group()
def distill():
    """Domain Distiller — 从业务文档生成 OAG domain"""
    pass


@distill.command()
@click.argument("docs_dir")
@click.option("--output", default=None, help="输出目录，默认与 docs_dir 相同")
@click.option("--phase", default=1, type=int, help="运行到指定阶段（0=文档准备, 1=概念发现）")
def run(docs_dir: str, output: str | None, phase: int):
    """从文档开始运行 distiller pipeline."""
    import logging

    from .distiller.pipeline import DistillerPipeline

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()

    llm_config = {
        "api_key": os.getenv("LLM_API_KEY", "sk-placeholder"),
        "api_url": os.getenv("LLM_API_URL", "http://localhost:8090/v1"),
        "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),
    }

    pipeline = DistillerPipeline(docs_dir, output, llm_config)
    pipeline.run(up_to_phase=phase)

    click.echo(f"\nDone. Results in {pipeline.state_dir}/")
    click.echo(pipeline.llm.usage_summary())


@distill.command()
@click.argument("docs_dir")
@click.option("--dry-run", is_flag=True, help="只显示会处理哪些文件，不实际修改")
def extract_images(docs_dir: str, dry_run: bool):
    """用 LLM 将文档中的图片表格转为 Markdown 文本（需要视觉模型）."""
    import logging

    from .distiller.image_extract import process_domain_images
    from .distiller.llm import DistillerLLM

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()

    llm_config = {
        "api_key": os.getenv("LLM_API_KEY", "sk-placeholder"),
        "api_url": os.getenv("LLM_API_URL", "http://localhost:8090/v1"),
        "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),
    }

    llm = DistillerLLM(llm_config)
    results = process_domain_images(Path(docs_dir), llm, dry_run=dry_run)

    if results:
        click.echo(f"\nProcessed {sum(results.values())} images in {len(results)} files.")
        click.echo(llm.usage_summary())
    else:
        click.echo("No images found to process.")


@distill.command()
@click.argument("state_dir")
def status(state_dir: str):
    """查看 distiller pipeline 状态."""
    from .distiller.pipeline import DistillerPipeline

    docs_dir = str(Path(state_dir).parent)
    pipeline = DistillerPipeline(docs_dir)
    click.echo(pipeline.status())


if __name__ == "__main__":
    cli()
