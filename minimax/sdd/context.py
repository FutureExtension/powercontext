"""Assemble the development context of one task.

The bundle answers, for a single task:

* which specification entries apply,
* which code files and symbols have to change,
* which tests verify the feature and the compatibility,
* what has already been done, what is still open and which verification
  results already exist.

The retrieval terms are taken from the vocabulary that the database itself
holds, so the module never invents search terms of its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sdd.config import Settings
from sdd.state import TaskRecord, TaskStateStore
from sdd.store import MaterialHit, MaterialStore

_SPLIT = re.compile(r"[\s,;:()\[\]{}<>|/\\\-]+")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENTIFIER_STOP = frozenset(
    {
        "Iterable",
        "Mapping",
        "None",
        "Order",
        "bool",
        "dict",
        "false",
        "list",
        "none",
        "spec_id",
        "str",
        "tags",
        "title",
        "true",
    }
)


@dataclass
class ContextBundle:
    """The context handed to the development assistant."""

    task: str
    scope: str
    query: str
    specs: list[MaterialHit] = field(default_factory=list)
    symbols: list[MaterialHit] = field(default_factory=list)
    tests: list[MaterialHit] = field(default_factory=list)
    state: TaskRecord | None = None
    code_query: str = ""
    statements: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# 任务上下文",
            "",
            f"- 任务：{self.task}",
            f"- 作用域：{self.scope}",
            f"- 检索词（由数据库 IK 分词器切分）：{self.query}",
            f"- 代码检索词（来自规格正文中的标识符）：{self.code_query}",
            "",
            "## 实际执行的数据库查询",
        ]
        for statement in self.statements:
            lines.append(f"- `{statement}`")
        if not self.statements:
            lines.append("- （无）")
        lines += [
            "",
            "## 适用的规格条目",
        ]
        for hit in self.specs:
            lines.append(f"- [{hit.identifier}] {hit.title}  （来源 {hit.file_path}，相关度 {hit.score:.4f}）")
        if not self.specs:
            lines.append("- （无）")
        lines += ["", "## 需要修改的代码文件或符号"]
        for hit in self.symbols:
            lines.append(f"- {hit.title}  （{hit.file_path}，相关度 {hit.score:.4f}）")
        if not self.symbols:
            lines.append("- （无）")
        lines += ["", "## 用于验证功能及兼容性的测试"]
        for hit in self.tests:
            lines.append(f"- {hit.title}  （{hit.file_path}，相关度 {hit.score:.4f}）")
        if not self.tests:
            lines.append("- （无）")
        lines += ["", "## 已完成事项 / 待办事项 / 已有验证结果"]
        state = self.state
        if state is None:
            lines.append("- 已完成事项：（无记录，这是该任务的第一次运行）")
            lines.append("- 待办事项：按上面的规格与测试完成修改")
            lines.append("- 已有验证结果：（无）")
        else:
            lines.append("- 已完成事项：" + ("；".join(state.done) or "（无）"))
            lines.append("- 待办事项：" + ("；".join(state.todo) or "（无）"))
            lines.append("- 已有验证结果：" + ("；".join(state.verification) or "（无）"))
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        import json

        payload = {
            "task": self.task,
            "scope": self.scope,
            "query": self.query,
            "specs": [hit.identifier for hit in self.specs],
            "symbols": [f"{hit.file_path}:{hit.title}" for hit in self.symbols],
            "tests": [f"{hit.file_path}:{hit.title}" for hit in self.tests],
            "state": None
            if self.state is None
            else {
                "done": self.state.done,
                "todo": self.state.todo,
                "verification": self.state.verification,
                "proposal": self.state.proposal,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


def tokenize(store: MaterialStore, task: str) -> list[str]:
    """Segment the task text with the tokenizer the fulltext index uses.

    The index was built with the IK parser, so the query has to be segmented
    the same way.  Asking the database itself keeps the two sides in sync and
    avoids the module guessing where the word boundaries are.
    """

    connection = store.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"USE `{store.settings.seekdb_database}`")
            cursor.execute("SELECT tokenize(%s, 'ik')", (task,))
            row = cursor.fetchone()
    finally:
        connection.close()
    if not row or not row[0]:
        return []
    try:
        tokens = json.loads(row[0])
    except (TypeError, ValueError):
        return []
    return [str(token) for token in tokens if str(token).strip()]


def identifiers(text: str) -> list[str]:
    """Return the code identifiers that a specification mentions.

    The specifications are written in Chinese while the code and the tests
    carry English identifiers, so a task that is phrased in Chinese cannot be
    matched against the code index directly.  The specifications bridge the
    two: they name the functions and the parameters they govern.
    """

    found = []
    for name in _IDENTIFIER.findall(text):
        if len(name) < 4 or name in _IDENTIFIER_STOP:
            continue
        if name not in found:
            found.append(name)
    return found


def build_query(task: str, terms: list[str], limit: int = 8) -> str:
    """Keep the vocabulary terms that the task text mentions."""

    matched = [term for term in terms if term in task]
    if not matched:
        return " ".join(task.split()[:limit])
    return " ".join(matched[:limit])


async def build_context(
    settings: Settings,
    task: str,
    scope: str,
    *,
    limit_per_kind: int = 5,
) -> ContextBundle:
    """Retrieve the context of one task from seekdb and PowerContext."""

    store = MaterialStore(settings)
    tokens = tokenize(store, task)
    query = " ".join(tokens)

    # The specifications are the bridge between the task and the code: they
    # are found with the task words, and they name the identifiers that the
    # code and the test index are searched with.
    specs = store.search_specs(query, limit_per_kind)
    spec_bodies = store.spec_bodies([hit.identifier for hit in specs])
    code_terms = identifiers(task)
    for body in spec_bodies:
        code_terms.extend(identifiers(body))
    code_query = " ".join(dict.fromkeys(code_terms))

    symbols = store.search_symbols(code_query, limit_per_kind * 2)
    tests = store.search_tests(code_query, limit_per_kind * 2)

    state = await TaskStateStore(settings).load(scope)

    bundle = ContextBundle(
        task=task,
        scope=scope,
        query=query,
        specs=specs,
        symbols=symbols,
        tests=tests,
        state=state,
    )
    bundle.code_query = code_query
    bundle.statements = list(store.statements)
    if state is not None:
        bundle.specs = specs
    return bundle
