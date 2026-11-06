"""Run the verification sample of the research desk end to end.

The script performs the steps of the sample in order: import the notes into
seekdb, ask a question and show the evidence, record the review state, read
that state back from another process and show that it is used in the answer.
Every expected output is checked and the script reports what it saw.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qoderapp.config import Settings
from qoderapp.service import ResearchDesk

TOPIC = "检索基础"
OPEN_NOTE = "NOTE-分词与倒排.md"
DONE_NOTE = "NOTE-检索基础.md"
QUESTION = "分词器不一致会怎样"


def _run(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "qoderapp" / "cli.py"), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    settings = Settings.from_env()
    desk = ResearchDesk(settings)
    checks: list[tuple[str, bool, str]] = []

    count = desk.seed()
    checks.append(("笔记导入 seekdb", count == 4, f"{count} 条笔记"))

    answer = __import__("asyncio").run(desk.ask(QUESTION))
    checks.append(("提问命中证据", bool(answer.hits), f"{len(answer.hits)} 条命中"))
    checks.append(
        (
            "证据带真实出处",
            all((Path(__file__).resolve().parents[1] / hit.source_path).is_file() for hit in answer.hits),
            ", ".join(hit.source_path for hit in answer.hits),
        )
    )
    checks.append(
        (
            "检索由 seekdb 执行",
            any("MATCH(body)" in statement for statement in answer.statements),
            f"{len(answer.statements)} 条 SQL",
        )
    )

    mark_open = _run(["mark", "--topic", TOPIC, "--note", OPEN_NOTE])
    mark_done = _run(["mark", "--topic", TOPIC, "--note", DONE_NOTE, "--mastered"])
    checks.append(
        ("复习状态写入", mark_open.returncode == 0 and mark_done.returncode == 0, mark_done.stdout.strip())
    )

    progress = _run(["progress"])
    checks.append(
        (
            "状态跨进程读回",
            "已掌握 1" in progress.stdout and "待复习 1" in progress.stdout,
            progress.stdout.strip().replace("\n", " | "),
        )
    )

    reminder = __import__("asyncio").run(desk.ask(QUESTION, topic=TOPIC))
    checks.append(
        (
            "状态被用于回答",
            len(reminder.open_notes) == 1,
            f"提醒 {len(reminder.open_notes)} 条待复习",
        )
    )

    print("=" * 72)
    print("研记 · Research Desk 验证样例")
    print("=" * 72)
    failed = 0
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {name:18} {detail}")
    print("=" * 72)
    print("结论：" + ("全部通过" if not failed else f"{failed} 项未通过"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
