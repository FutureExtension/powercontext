"""Command line of the research desk."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qoderapp.config import Settings
from qoderapp.service import ResearchDesk


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research desk")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="把样例笔记导入 seekdb")

    ask = sub.add_parser("ask", help="检索笔记并输出带出处的证据")
    ask.add_argument("--question", required=True)
    ask.add_argument("--topic", default="")
    ask.add_argument("--json", action="store_true")

    mark = sub.add_parser("mark", help="记录某条笔记的复习状态")
    mark.add_argument("--topic", required=True)
    mark.add_argument("--note", required=True)
    mark.add_argument("--mastered", action="store_true")

    sub.add_parser("progress", help="输出各主题的复习进度")

    serve = sub.add_parser("serve", help="启动网页服务")
    serve.add_argument("--host", default="")
    serve.add_argument("--port", type=int, default=0)

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command == "serve":
        from qoderapp.server import serve as run_server
        if args.host:
            settings = type(settings)(
                **{**settings.__dict__, "host": args.host, "port": args.port or settings.port}
            )
        run_server(settings)
        return 0

    desk = ResearchDesk(settings)
    if args.command == "seed":
        count = desk.seed()
        print(f"seekdb `{settings.seekdb_database}` 已导入 {count} 条笔记。")
        return 0
    if args.command == "ask":
        answer = asyncio.run(desk.ask(args.question, topic=args.topic))
        if args.json:
            print(
                json.dumps(
                    {
                        "question": answer.question,
                        "hits": [
                            {
                                "note_id": hit.note_id,
                                "title": hit.title,
                                "source_path": hit.source_path,
                                "score": hit.score,
                            }
                            for hit in answer.hits
                        ],
                        "open_notes": answer.open_notes,
                        "statements": answer.statements,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(answer.to_markdown())
        return 0
    if args.command == "mark":
        state = asyncio.run(desk.mark(args.topic, args.note, args.mastered))
        print(
            f"主题 {state.topic}：已掌握 {len(state.mastered)} 条，待复习 {len(state.open_notes)} 条。"
        )
        return 0
    if args.command == "progress":
        for item in asyncio.run(desk.progress()):
            print(
                f"{item['topic']}: 已掌握 {item['mastered']}，待复习 {item['open']}，复习次数 {item['reviews']}"
            )
        return 0
    parser.error("unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
