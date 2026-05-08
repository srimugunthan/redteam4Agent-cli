"""Full CLI commands for AgentRedTeam — Phase 7."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="agentrt", help="Adversarial red-team testing for AI agent systems.")
console = Console()

# Sub-app groups
config_app = typer.Typer(help="Configuration management.")
plugin_app = typer.Typer(help="Plugin management.")
trace_app = typer.Typer(help="Trace inspection and export.")
report_app = typer.Typer(help="Report generation.")

app.add_typer(config_app, name="config")
app.add_typer(plugin_app, name="plugin")
app.add_typer(trace_app, name="trace")
app.add_typer(report_app, name="report")


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------

@app.command()
def version() -> None:
    """Print the installed agentrt version."""
    from agentrt import __version__
    typer.echo(f"agentrt {__version__}")


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

@app.command()
def run(
    campaign: Path = typer.Option(..., "--campaign", help="Campaign YAML file"),
    profile: Optional[str] = typer.Option(None, "--profile"),
    target: Optional[str] = typer.Option(None, "--target", help="Override target endpoint (REST only)"),
    category: Optional[List[str]] = typer.Option(None, "--category"),
    judge: Optional[str] = typer.Option(None, "--judge", help="Override judge model"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: JSON summary to stdout, exit 0|1|2"),
    severity_threshold: str = typer.Option("medium", "--severity-threshold"),
    run_id: Optional[str] = typer.Option(None, "--run-id"),
    resume: bool = typer.Option(False, "--resume"),
    output_dir: Path = typer.Option(Path("./reports"), "--output-dir"),
) -> None:
    """Run a full red-team campaign."""
    asyncio.run(
        _run_campaign(
            campaign, profile, target, category, judge, ci,
            severity_threshold, run_id, resume, output_dir,
        )
    )


async def _run_campaign(
    campaign_path: Path,
    profile: Optional[str],
    target: Optional[str],
    category: Optional[List[str]],
    judge_override: Optional[str],
    ci: bool,
    severity_threshold: str,
    run_id: Optional[str],
    resume: bool,
    output_dir: Path,
) -> None:
    """Async implementation of the run command."""
    from langgraph.checkpoint.memory import MemorySaver

    from agentrt.config.loader import (
        load_campaign,
        resolve_adapter,
        resolve_judge,
        resolve_plugins,
        resolve_probe_generator,
        resolve_search_strategy,
    )
    from agentrt.config.settings import AgentrtSettings
    from agentrt.attacks.base import AttackContext
    from agentrt.engine.orchestrator import (
        AttackGraphConfig,
        build_attack_graph,
        make_initial_state,
    )
    from agentrt.report.builder import ReportBuilder
    from agentrt.trace.store import TraceStore

    try:
        # Build overrides dict from CLI flags (non-None values only)
        overrides: dict = {}
        if target is not None:
            overrides["target"] = {"endpoint": target}
        if judge_override is not None:
            overrides["judge"] = {"model": judge_override}

        config = load_campaign(campaign_path, overrides)

        # If --profile CLI flag is set, override config.profile
        if profile is not None:
            config = load_campaign(campaign_path, {**overrides, "profile": profile})

        api_keys = AgentrtSettings()
        actual_run_id = run_id or str(uuid.uuid4())

        adapter = resolve_adapter(config)
        judge_engine = resolve_judge(config, api_keys)
        generator = resolve_probe_generator(config, api_keys)
        plugins = resolve_plugins(config)

        # Filter by category if provided
        if category:
            plugins = [
                p for p in plugins
                if p.category in category or p.id in category
            ]

        strategy = resolve_search_strategy(config, api_keys)

        # Check if injection attacks present
        needs_mock = any(p.id in ("A-02", "B-04") for p in plugins)

        # Build TraceStore
        output_dir.mkdir(parents=True, exist_ok=True)
        store = TraceStore(db_path=output_dir / "traces.db", jsonl_dir=output_dir)
        await store.init()
        await store.create_run(actual_run_id, config.name)

        # Start mock server if needed
        mock_server = None
        if needs_mock and config.mock_server.routes:
            from agentrt.mock_server.server import MockToolServer
            mock_server = MockToolServer(routes=config.mock_server.routes)
            await mock_server.start()
            if not ci:
                console.print(f"[green]Mock server started at {mock_server.base_url}[/green]")

        attack_context = AttackContext(
            run_id=actual_run_id,
            config=config,
            mock_server=mock_server,
        )

        cfg = AttackGraphConfig(
            agent=adapter,
            judge=judge_engine,
            probe_generator=generator,
            trace_store=store,
            context=attack_context,
            plugins={p.id: p for p in plugins},
            search_strategy=strategy,
            max_turns=config.execution.max_turns,
        )

        graph = build_attack_graph(cfg, checkpointer=MemorySaver())
        initial = make_initial_state(
            actual_run_id, plugins, mutation_count=config.execution.mutation_count
        )

        if not ci:
            console.print(
                f"[cyan]Starting campaign '{config.name}' "
                f"(run_id={actual_run_id}, plugins={len(plugins)})[/cyan]"
            )

        await graph.ainvoke(initial, {"configurable": {"thread_id": actual_run_id}})
        await store.complete_run(actual_run_id)

        # Stop mock server if started
        if mock_server is not None:
            await mock_server.stop()

        # Load campaign result and generate reports
        campaign_result = await store.load(actual_run_id)
        await store.close()

        builder = ReportBuilder(
            campaign_result,
            include_traces=config.reporting.include_traces,
            severity_threshold=severity_threshold,
        )

        for fmt in config.reporting.formats:
            report_path = builder.write(fmt, output_dir)
            if not ci:
                console.print(f"[green]Report written: {report_path}[/green]")

        # CI mode summary
        successes = [r for r in campaign_result.results if r.verdict.success]
        summary = {
            "run_id": actual_run_id,
            "campaign": config.name,
            "total": len(campaign_result.results),
            "findings": len(successes),
            "exit_code": 1 if successes else 0,
        }

        if ci:
            typer.echo(json.dumps(summary))
            raise typer.Exit(code=1 if successes else 0)
        else:
            console.print(
                f"[bold]Campaign complete:[/bold] "
                f"{len(campaign_result.results)} attacks, "
                f"{len(successes)} findings."
            )

    except (FileNotFoundError, Exception) as exc:
        if ci:
            typer.echo(json.dumps({"error": str(exc), "exit_code": 2}))
            raise typer.Exit(code=2)
        else:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

@app.command()
def validate(
    campaign: Path = typer.Option(..., "--campaign"),
) -> None:
    """Validate a campaign YAML without running it."""
    from pydantic import ValidationError

    from agentrt.config.loader import load_campaign

    try:
        config = load_campaign(campaign)
        console.print(
            f"[green]OK:[/green] Campaign '{config.name}' is valid "
            f"(version={config.version})."
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    except ValidationError as exc:
        console.print(f"[red]Validation error:[/red]\n{exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# probe command
# ---------------------------------------------------------------------------

@app.command()
def probe(
    target: str = typer.Option(..., "--target"),
    attack: str = typer.Option(..., "--attack", help="Plugin ID e.g. A-01"),
    payload: Optional[str] = typer.Option(None, "--payload"),
) -> None:
    """Run a single attack plugin against a target."""
    asyncio.run(_probe(target, attack, payload))


async def _probe(target: str, attack_id: str, payload: Optional[str]) -> None:
    from agentrt.adapters.rest import RestAdapter
    from agentrt.attacks.base import AttackContext
    from agentrt.attacks.registry import PluginRegistry

    PluginRegistry.discover()

    try:
        plugin_cls = PluginRegistry.get(attack_id)
    except KeyError:
        console.print(f"[red]Error:[/red] Plugin '{attack_id}' not found.")
        raise typer.Exit(code=1)

    plugin = plugin_cls()
    adapter = RestAdapter(target)
    context = AttackContext(run_id=str(uuid.uuid4()), config=None)

    try:
        result = await plugin.execute(adapter, context)
        console.print(f"[bold]Result:[/bold] {result}")
    except NotImplementedError:
        # Plugin execute() not fully implemented — show seed queries
        console.print(f"[yellow]Plugin {attack_id} execute() not implemented.[/yellow]")
        console.print(f"Seed queries: {plugin.seed_queries}")
    except Exception as exc:
        console.print(f"[red]Error running plugin:[/red] {exc}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------

@app.command()
def doctor() -> None:
    """Check connectivity, API keys, and optional dependencies."""
    import importlib
    import os

    table = Table(title="AgentRedTeam Doctor")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    checks_passed = True

    # (1) ANTHROPIC_API_KEY
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        table.add_row("ANTHROPIC_API_KEY", "[green]OK[/green]", f"Set ({key[:8]}...)")
    else:
        table.add_row("ANTHROPIC_API_KEY", "[yellow]MISSING[/yellow]", "Not set (required for LLM judge/generator)")
        # Not fatal — keyword judge doesn't need it

    # (2) OPENAI_API_KEY
    oai_key = os.environ.get("OPENAI_API_KEY")
    if oai_key:
        table.add_row("OPENAI_API_KEY", "[green]OK[/green]", f"Set ({oai_key[:8]}...)")
    else:
        table.add_row("OPENAI_API_KEY", "[dim]MISSING[/dim]", "Not set (optional)")

    # (3) langgraph importable
    try:
        importlib.import_module("langgraph")
        table.add_row("langgraph", "[green]OK[/green]", "Importable")
    except ImportError as exc:
        table.add_row("langgraph", "[red]FAIL[/red]", str(exc))
        checks_passed = False

    # (4) aiosqlite importable
    try:
        importlib.import_module("aiosqlite")
        table.add_row("aiosqlite", "[green]OK[/green]", "Importable")
    except ImportError as exc:
        table.add_row("aiosqlite", "[red]FAIL[/red]", str(exc))
        checks_passed = False

    console.print(table)

    if checks_passed:
        console.print("[green]All required checks passed.[/green]")
    else:
        console.print("[red]Some required checks failed.[/red]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# trace sub-commands
# ---------------------------------------------------------------------------

@trace_app.command("export")
def trace_export(
    run_id: str = typer.Option(..., "--run-id"),
    format: str = typer.Option("json", "--format"),
    output: Path = typer.Option(Path("./traces"), "--output"),
    db: Path = typer.Option(Path("./agentrt_traces.db"), "--db"),
) -> None:
    """Export traces for a completed run."""
    asyncio.run(_trace_export(run_id, format, output, db))


async def _trace_export(run_id: str, fmt: str, output: Path, db: Path) -> None:
    from agentrt.trace.store import TraceStore

    store = TraceStore(db_path=db, jsonl_dir=None)
    try:
        await store.init()
        out_path = await store.export(run_id, fmt, output)
        console.print(f"[green]Exported to:[/green] {out_path}")
    except KeyError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# report sub-commands
# ---------------------------------------------------------------------------

@report_app.command("generate")
def report_generate(
    run_id: str = typer.Option(..., "--run-id"),
    format: str = typer.Option("json", "--format"),
    output: Path = typer.Option(Path("./reports"), "--output"),
    db: Path = typer.Option(Path("./agentrt_traces.db"), "--db"),
    include_traces: str = typer.Option("failures", "--include-traces"),
) -> None:
    """Generate a report for a completed run."""
    asyncio.run(_report_generate(run_id, format, output, db, include_traces))


async def _report_generate(
    run_id: str, fmt: str, output: Path, db: Path, include_traces: str
) -> None:
    from agentrt.report.builder import ReportBuilder
    from agentrt.trace.store import TraceStore

    store = TraceStore(db_path=db, jsonl_dir=None)
    try:
        await store.init()
        campaign_result = await store.load(run_id)
    except KeyError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    finally:
        await store.close()

    builder = ReportBuilder(campaign_result, include_traces=include_traces)
    path = builder.write(fmt, output)
    console.print(f"[green]Report written:[/green] {path}")


# ---------------------------------------------------------------------------
# plugin sub-commands
# ---------------------------------------------------------------------------

@plugin_app.command("list")
def plugin_list(
    category: Optional[str] = typer.Option(None, "--category"),
) -> None:
    """List all registered attack plugins."""
    from agentrt.attacks.registry import PluginRegistry

    PluginRegistry.discover()
    plugins = PluginRegistry.list_all()

    if category:
        plugins = [p for p in plugins if p.category == category]

    table = Table(title="Registered Attack Plugins")
    table.add_column("ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Category")
    table.add_column("Severity")

    for p in plugins:
        severity_color = {
            "critical": "red",
            "high": "yellow",
            "medium": "blue",
            "low": "green",
        }.get(p.severity, "white")
        table.add_row(
            p.id,
            p.name,
            p.category,
            f"[{severity_color}]{p.severity}[/{severity_color}]",
        )

    console.print(table)
    console.print(f"Total: {len(plugins)} plugin(s)")


@plugin_app.command("info")
def plugin_info(
    plugin_id: str = typer.Argument(...),
) -> None:
    """Show details for a specific plugin."""
    from agentrt.attacks.registry import PluginRegistry

    PluginRegistry.discover()

    try:
        plugin_cls = PluginRegistry.get(plugin_id)
    except KeyError:
        console.print(f"[red]Error:[/red] Plugin '{plugin_id}' not found.")
        raise typer.Exit(code=1)

    p = plugin_cls()
    console.print(f"[bold]ID:[/bold]       {p.id}")
    console.print(f"[bold]Name:[/bold]     {p.name}")
    console.print(f"[bold]Category:[/bold] {p.category}")
    console.print(f"[bold]Severity:[/bold] {p.severity}")
    if p.seed_queries:
        console.print(f"[bold]Seed queries ({len(p.seed_queries)}):[/bold]")
        for q in p.seed_queries:
            console.print(f"  - {q}")
    if p.probe_template:
        console.print(f"[bold]Probe template:[/bold] {p.probe_template}")
    if p.dataset_path:
        console.print(f"[bold]Dataset path:[/bold] {p.dataset_path}")


# ---------------------------------------------------------------------------
# config sub-commands
# ---------------------------------------------------------------------------

@config_app.command("show")
def config_show(
    campaign: Optional[Path] = typer.Option(None, "--campaign"),
) -> None:
    """Show the fully resolved config."""
    from agentrt.config.loader import load_campaign
    from agentrt.config.settings import CampaignConfig

    if campaign is not None:
        try:
            config = load_campaign(campaign)
        except (FileNotFoundError, Exception) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1)
    else:
        config = CampaignConfig()

    console.print_json(config.model_dump_json(indent=2))


@config_app.command("profiles")
def config_profiles() -> None:
    """List available profiles."""
    table = Table(title="Built-in Profiles")
    table.add_column("Profile", style="bold cyan")
    table.add_column("Description")

    profiles = [
        ("quick", "Fast smoke test — reduced mutation, basic coverage"),
        ("full", "Comprehensive — all categories, maximum mutation"),
        ("stealth", "Low-noise — delayed requests, minimal footprint"),
        ("ci", "CI-optimized — keyword judge, exit codes, JSON output"),
    ]

    for name, desc in profiles:
        table.add_row(name, desc)

    console.print(table)


if __name__ == "__main__":
    app()
