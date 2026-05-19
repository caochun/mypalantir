from __future__ import annotations

import os

import click
from dotenv import load_dotenv

from .loader import load_domain


def _init(env_file: str = ".env"):
    load_dotenv(env_file)
    domain_dir = os.getenv("DOMAIN", "domains/fee")

    ontology, store, registry = load_domain(domain_dir)

    llm_config = {
        "api_key": os.getenv("LLM_API_KEY", ""),
        "api_url": os.getenv("LLM_API_URL", "http://localhost:8090/v1"),
        "model": os.getenv("LLM_MODEL", "qwen3.5-plus"),
    }

    return ontology, store, registry, llm_config


@click.group()
def cli():
    """OAG — Ontology Augmented Generation"""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
def serve(host: str, port: int):
    """Start the API server."""
    import uvicorn
    from .api import create_app

    ontology, store, registry, llm_config = _init()
    app = create_app(ontology, store, registry, llm_config)
    uvicorn.run(app, host=host, port=port)


@cli.command()
def chat():
    """Interactive agent chat."""
    from .agent import Agent

    ontology, store, registry, llm_config = _init()
    agent = Agent(ontology, store, registry, llm_config)

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
            if event["type"] == "text":
                click.echo(event["content"], nl=False)
            elif event["type"] == "tool_call":
                click.echo(f"\n  [调用 {event['name']}({event['arguments']})]", nl=False)
            elif event["type"] == "tool_result":
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
    ontology, store, registry, llm_config = _init()

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
    ontology, store, registry, llm_config = _init()

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


if __name__ == "__main__":
    cli()
