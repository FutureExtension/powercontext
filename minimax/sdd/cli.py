"""Command line entry point of the SDD context module."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sdd.config import Settings
from sdd.context import build_context
from sdd.minimax_client import MiniMaxClient, MiniMaxError
from sdd.state import TaskRecord, TaskStateStore
from sdd.store import MaterialStore

SYSTEM_PROMPT = (
    "你是资深软件工程师。根据给定的任务上下文（规格、代码、测试）完成代码修改，"
    "先说明修改思路，再给出完整的差异。修改必须保持既有行为兼容。"
)


def _seed(settings: Settings) -> int:
    from scripts.seed import seed

    seed(settings)
    return 0


async def _plan(settings: Settings, task: str, scope: str, as_json: bool) -> int:
    bundle = await build_context(settings, task, scope)
    if as_json:
        print(bundle.to_json())
    else:
        print(bundle.to_markdown())
    state = bundle.state
    if state is None:
        state = TaskRecord(task=task, scope=scope)
    state.task = task
    state.specs = [hit.identifier for hit in bundle.specs]
    state.symbols = [f"{hit.file_path}:{hit.title}" for hit in bundle.symbols]
    state.tests = [f"{hit.file_path}:{hit.title}" for hit in bundle.tests]
    if not state.todo:
        state.todo = ["按规格实现修改", "运行目标功能测试", "运行回归测试"]
    await TaskStateStore(settings).save(state)
    return 0


async def _status(settings: Settings, scope: str) -> int:
    state = await TaskStateStore(settings).load(scope)
    if state is None:
        print(f"作用域 {scope} 还没有保存的任务状态。")
        return 1
    print(json.dumps(state.__dict__, ensure_ascii=False, indent=2))
    return 0


async def _ask(settings: Settings, task: str, scope: str) -> int:
    bundle = await build_context(settings, task, scope)
    print(bundle.to_markdown())
    if not settings.has_minimax_key:
        print(
            "\n[未调用 MiniMax] 环境变量 MINIMAX_API_KEY 未设置。\n"
            "设置后重新执行本命令即可得到 MiniMax 的代码修改建议，"
            "建议文本会连同任务状态一起写入 PowerContext。",
            file=sys.stderr,
        )
        return 2
    client = MiniMaxClient(
        api_key=settings.minimax_api_key or "",
        base_url=settings.minimax_base_url,
        model=settings.minimax_model,
    )
    try:
        answer = client.complete(bundle.to_markdown(), system=SYSTEM_PROMPT)
    except MiniMaxError as error:
        print(f"[MiniMax 调用失败] {error}", file=sys.stderr)
        return 3
    state = bundle.state or TaskRecord(task=task, scope=scope)
    state.task = task
    state.proposal = answer
    state.done.append("已由 MiniMax 生成代码修改建议")
    await TaskStateStore(settings).save(state)
    print("\n===== MiniMax 建议 =====\n")
    print(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDD 上下文模块")
    parser.add_argument("--scope", default="sdd-task", help="PowerContext 作用域")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="把样例工程的规格、代码与测试导入 seekdb")
    seed_parser.add_argument("--scope", default=argparse.SUPPRESS, help="PowerContext 作用域")

    plan = sub.add_parser("plan", help="检索并输出任务上下文")
    plan.add_argument("--task", required=True)
    plan.add_argument("--json", action="store_true")
    plan.add_argument("--scope", default=argparse.SUPPRESS, help="PowerContext 作用域")

    status = sub.add_parser("status", help="读取已保存的任务状态")
    status.add_argument("--scope", default=argparse.SUPPRESS, help="PowerContext 作用域")
    status.set_defaults(func=None)

    ask = sub.add_parser("ask", help="检索上下文并调用 MiniMax 生成修改建议")
    ask.add_argument("--task", required=True)
    ask.add_argument("--scope", default=argparse.SUPPRESS, help="PowerContext 作用域")

    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "seed":
        return _seed(settings)
    if args.command == "plan":
        return asyncio.run(_plan(settings, args.task, args.scope, args.json))
    if args.command == "status":
        return asyncio.run(_status(settings, args.scope))
    if args.command == "ask":
        return asyncio.run(_ask(settings, args.task, args.scope))
    parser.error("unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
