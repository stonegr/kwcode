"""
Kaiwu CLI entry point. Experience targets Claude Code parity.
Usage: kaiwu "修复登录bug" / kaiwu --plan "重构认证模块" / kaiwu init / kaiwu memory
"""

import logging
import os
import sys
import time

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(
    name="kaiwu",
    help="Kaiwu - 本地模型 coding agent",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

# ── Status icons ──────────────────────────────────────────────
ICONS = {
    "gate":           "🔍",
    "locator":        "📍",
    "locator_done":   "📍",
    "locator_fail":   "📍",
    "generator":      "⚙️ ",
    "generator_done":  "⚙️ ",
    "generator_fail":  "⚙️ ",
    "verifier":       "✅",
    "verifier_done":  "✅",
    "verifier_fail":  "❌",
    "retry":          "⚠️ ",
    "search":         "🔎",
    "search_done":    "🔎",
    "office_fail":    "📄",
}


def _status_callback(stage: str, detail: str):
    """Rich console status callback for orchestrator."""
    icon = ICONS.get(stage, "  ")
    if "fail" in stage or "retry" in stage:
        console.print(f"  {icon} [yellow]{detail}[/yellow]")
    elif "done" in stage:
        console.print(f"  {icon} [green]{detail}[/green]")
    else:
        console.print(f"  {icon} {detail}")


def _build_pipeline(
    model_path: str | None,
    ollama_url: str,
    ollama_model: str,
    project_root: str,
    verbose: bool,
):
    """Construct the full pipeline: LLM → Gate → Experts → Orchestrator."""
    from kaiwu.llm.llama_backend import LLMBackend
    from kaiwu.core.gate import Gate
    from kaiwu.core.orchestrator import PipelineOrchestrator
    from kaiwu.experts.locator import LocatorExpert
    from kaiwu.experts.generator import GeneratorExpert
    from kaiwu.experts.verifier import VerifierExpert
    from kaiwu.experts.search_augmentor import SearchAugmentorExpert
    from kaiwu.experts.office_handler import OfficeHandlerExpert
    from kaiwu.tools.executor import ToolExecutor
    from kaiwu.memory.kaiwu_md import KaiwuMemory

    llm = LLMBackend(
        model_path=model_path,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        verbose=verbose,
    )
    tools = ToolExecutor(project_root=project_root)
    memory = KaiwuMemory()
    gate = Gate(llm=llm)

    locator = LocatorExpert(llm=llm, tool_executor=tools)
    generator = GeneratorExpert(llm=llm, tool_executor=tools)
    verifier = VerifierExpert(llm=llm, tool_executor=tools)
    search = SearchAugmentorExpert(llm=llm)
    office = OfficeHandlerExpert()

    orchestrator = PipelineOrchestrator(
        locator=locator,
        generator=generator,
        verifier=verifier,
        search_augmentor=search,
        office_handler=office,
        tool_executor=tools,
        memory=memory,
    )
    return gate, orchestrator, memory


@app.command()
def main(
    task: str = typer.Argument(None, help="任务描述，如 '修复登录bug'"),
    plan: bool = typer.Option(False, "--plan", "-p", help="先输出计划，确认后执行"),
    model: str = typer.Option(None, "--model", "-m", help="Ollama模型名称 (默认 qwen3-8b)"),
    model_path: str = typer.Option(None, "--model-path", help="本地GGUF模型路径 (优先于Ollama)"),
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url", help="Ollama服务地址"),
    project_dir: str = typer.Option(".", "--project", "-d", help="项目根目录"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示专家执行详情"),
    init: bool = typer.Option(False, "--init", help="初始化KAIWU.md"),
    show_memory: bool = typer.Option(False, "--memory", help="查看项目记忆"),
):
    """Kaiwu - 本地模型 coding agent with MoE expert pipeline."""

    # Setup logging
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(name)s: %(message)s")

    project_root = os.path.abspath(project_dir)

    # ── Subcommands ──
    if init:
        from kaiwu.memory.kaiwu_md import KaiwuMemory
        mem = KaiwuMemory()
        result = mem.init(project_root)
        console.print(result)
        return

    if show_memory:
        from kaiwu.memory.kaiwu_md import KaiwuMemory
        mem = KaiwuMemory()
        content = mem.show(project_root)
        console.print(Panel(content, title="KAIWU.md", border_style="blue"))
        return

    if not task:
        console.print("[red]请提供任务描述。用法: kaiwu \"修复登录bug\"[/red]")
        raise typer.Exit(1)

    # ── Main pipeline ──
    ollama_model = model or "qwen3-8b"

    console.print(Panel(
        f"[bold]Kaiwu v0.3[/bold] | 模型: {ollama_model} | 项目: {project_root}",
        border_style="cyan",
    ))
    console.print()

    gate, orchestrator, memory = _build_pipeline(
        model_path=model_path,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        project_root=project_root,
        verbose=verbose,
    )

    # Step 1: Gate classification
    console.print("  🔍 Gate分析中...")
    gate_result = gate.classify(task, memory_context=memory.load(project_root))

    if "_parse_error" in gate_result:
        console.print(f"  [yellow]⚠ Gate解析降级: {gate_result['_parse_error']}[/yellow]")

    expert_type = gate_result["expert_type"]
    difficulty = gate_result["difficulty"]
    summary = gate_result.get("task_summary", "")
    console.print(f"     任务类型: [bold]{expert_type}[/bold] | 难度: {difficulty} | 摘要: {summary}")
    console.print()

    # Step 1.5: Plan mode (optional)
    if plan:
        console.print(Panel(
            f"[bold]执行计划[/bold]\n"
            f"专家序列: {_get_sequence_display(expert_type)}\n"
            f"搜索增强: {'难任务首次失败触发' if difficulty == 'hard' else '失败2次后触发'}\n"
            f"最大重试: 3次",
            title="Plan",
            border_style="yellow",
        ))
        confirm = typer.confirm("确认执行?")
        if not confirm:
            console.print("[yellow]已取消[/yellow]")
            raise typer.Exit(0)
        console.print()

    # Step 2: Execute pipeline
    status_fn = _status_callback if verbose else None
    result = orchestrator.run(
        user_input=task,
        gate_result=gate_result,
        project_root=project_root,
        on_status=status_fn,
    )

    # Step 3: Output result
    console.print()
    elapsed = result.get("elapsed", 0)

    if result["success"]:
        ctx = result["context"]
        files = []
        if ctx.locator_output:
            files = ctx.locator_output.get("relevant_files", [])
        elif ctx.generator_output:
            files = [p.get("file", "") for p in ctx.generator_output.get("patches", [])]
        files_str = ", ".join(files[:5]) if files else "N/A"

        console.print(f"  [bold green]✓ 完成[/bold green] | 修改文件: {files_str} | 耗时: {elapsed:.1f}s")
        console.print("    已记录到 KAIWU.md")

        # Show explanation if available
        if ctx.generator_output and ctx.generator_output.get("explanation"):
            console.print(f"\n  [dim]{ctx.generator_output['explanation']}[/dim]")
    else:
        error = result.get("error", "Unknown error")
        console.print(f"  [bold red]✗ 失败[/bold red] | {error} | 耗时: {elapsed:.1f}s")

        ctx = result.get("context")
        if ctx and ctx.verifier_output:
            detail = ctx.verifier_output.get("error_detail", "")
            if detail:
                console.print(f"    最后错误: {detail[:200]}")

        raise typer.Exit(1)


def _get_sequence_display(expert_type: str) -> str:
    """Human-readable expert sequence."""
    from kaiwu.core.orchestrator import EXPERT_SEQUENCES
    seq = EXPERT_SEQUENCES.get(expert_type, ["generator", "verifier"])
    return " → ".join([s.capitalize() for s in seq])


# ── Init subcommand (alternative syntax) ──
@app.command("init")
def cmd_init(
    project_dir: str = typer.Option(".", "--project", "-d", help="项目根目录"),
):
    """初始化 KAIWU.md 项目记忆文件。"""
    from kaiwu.memory.kaiwu_md import KaiwuMemory
    mem = KaiwuMemory()
    result = mem.init(os.path.abspath(project_dir))
    console.print(result)


@app.command("memory")
def cmd_memory(
    project_dir: str = typer.Option(".", "--project", "-d", help="项目根目录"),
):
    """查看当前项目的 KAIWU.md 记忆。"""
    from kaiwu.memory.kaiwu_md import KaiwuMemory
    mem = KaiwuMemory()
    content = mem.show(os.path.abspath(project_dir))
    Console().print(Panel(content, title="KAIWU.md", border_style="blue"))


if __name__ == "__main__":
    app()
