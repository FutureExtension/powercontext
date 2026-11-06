"""Load the sample project into seekdb.

The seed reads the specification files, the code symbols and the test cases of
the sample project and stores them so that the context module can retrieve
them with one fulltext query.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdd.config import Settings
from sdd.store import MaterialStore

_FUNCTION = re.compile(r"^def ([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_TEST = re.compile(r"^def (test_[A-Za-z0-9_]*)", re.MULTILINE)
_SPEC_ID = re.compile(r"spec_id:\s*(\S+)")
_SPEC_TITLE = re.compile(r"title:\s*(.+)")
_SPEC_TAGS = re.compile(r"tags:\s*\[(.*)\]")


def _spec_rows(project: Path) -> list[dict]:
    rows = []
    for path in sorted((project / "specs").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        spec_id = (_SPEC_ID.search(text) or [None, path.stem])[1]
        title_match = _SPEC_TITLE.search(text)
        title = title_match.group(1).strip() if title_match else path.stem
        body = f"{title}\n{text}"
        rows.append(
            {
                "spec_id": spec_id,
                "title": title,
                "file_path": f"sample_project/specs/{path.name}",
                "body": body,
            }
        )
    return rows


def _symbol_rows(project: Path) -> list[dict]:
    rows = []
    for path in sorted((project / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(project).as_posix()
        for match in _FUNCTION.finditer(text):
            name = match.group(1)
            start = text.rfind("\n\n", 0, match.start()) + 2
            snippet = text[start : match.start() + 400]
            rows.append(
                {
                    "symbol_id": f"SYM-{relative}-{name}",
                    "file_path": relative,
                    "symbol": name,
                    "kind": "function",
                    "spec_id": "",
                    "related_test": f"test_{name}",
                    "body": f"{name} {snippet}",
                }
            )
    return rows


def _test_rows(project: Path) -> list[dict]:
    rows = []
    for path in sorted((project / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(project).as_posix()
        for match in _TEST.finditer(text):
            name = match.group(1)
            start = text.rfind("\n\n", 0, match.start()) + 2
            purpose = text[start : match.start() + 300]
            rows.append(
                {
                    "test_id": f"TST-{relative}-{name}",
                    "file_path": relative,
                    "name": name,
                    "body": f"{name} {purpose}",
                }
            )
    return rows


def seed(settings: Settings) -> None:
    project = Path(settings.sample_project)
    store = MaterialStore(settings)
    store.ensure_schema()
    specs = _spec_rows(project)
    symbols = _symbol_rows(project)
    tests = _test_rows(project)
    store.replace(specs, symbols, tests)
    print(
        f"seekdb `{settings.seekdb_database}` 已导入 "
        f"{len(specs)} 条规格、{len(symbols)} 个代码符号、{len(tests)} 个测试用例。"
    )


if __name__ == "__main__":
    seed(Settings.from_env())
