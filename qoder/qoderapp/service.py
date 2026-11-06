"""The research desk: ask a question, get evidence, keep the review state.

The service joins the two stores.  seekdb holds the notes and answers the
retrieval, PowerContext holds the review state of every topic and is read
back on the next run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from qoderapp.config import Settings
from qoderapp.memory import DeskMemory, TopicState
from qoderapp.store import NoteHit, NoteStore

FRONTMATTER = re.compile(r"^---\s*$")
FIELD = re.compile(r"^(title|topic):\s*(.+)$", re.MULTILINE)


@dataclass
class Note:
    """One note read from the sample corpus."""

    note_id: str
    topic: str
    title: str
    source_path: str
    body: str


@dataclass
class Answer:
    """The answer to one question."""

    question: str
    topic: str
    hits: list[NoteHit] = field(default_factory=list)
    open_notes: list[str] = field(default_factory=list)
    reviews: int = 0
    statements: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"# {self.question}", ""]
        if self.open_notes:
            lines.append(
                f"> 复习提醒：本主题还有 {len(self.open_notes)} 条笔记没有标记为已掌握。"
            )
            lines.append("")
        lines.append("## 证据")
        for hit in self.hits:
            lines.append(
                f"- **{hit.title}**（主题 {hit.topic}，来源 `{hit.source_path}`，相关度 {hit.score:.4f}）"
            )
            if hit.snippet:
                lines.append(f"  > {hit.snippet[:200]}")
        if not self.hits:
            lines.append("- （没有命中的笔记）")
        return "\n".join(lines)


def read_notes(directory: Path) -> list[Note]:
    """Read every markdown note of a directory."""

    notes: list[Note] = []
    for path in sorted(directory.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        topic = ""
        title = path.stem
        lines = text.splitlines()
        if lines and FRONTMATTER.match(lines[0]):
            closing = 0
            for index in range(1, len(lines)):
                if FRONTMATTER.match(lines[index]):
                    closing = index
                    break
            head = "\n".join(lines[1:closing])
            for key, value in FIELD.findall(head):
                if key == "topic":
                    topic = value.strip()
                else:
                    title = value.strip()
        relative = path.relative_to(directory).as_posix()
        notes.append(
            Note(
                note_id=f"NOTE-{relative}",
                topic=topic or "未分类",
                title=title,
                source_path=f"sample/{relative}",
                body=text,
            )
        )
    return notes


class ResearchDesk:
    """The service the web interface and the command line talk to."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = NoteStore(settings)
        self.memory = DeskMemory(settings)

    def seed(self) -> int:
        """Import the sample corpus into seekdb."""

        notes = read_notes(Path(self.settings.sample_dir))
        self.store.ensure_schema()
        self.store.replace(
            [
                {
                    "note_id": note.note_id,
                    "topic": note.topic,
                    "title": note.title,
                    "source_path": note.source_path,
                    "body": note.body,
                }
                for note in notes
            ]
        )
        return len(notes)

    def topics(self) -> list[tuple[str, int]]:
        self.store.ensure_schema()
        return self.store.topics()

    async def ask(self, question: str, topic: str = "", limit: int = 8) -> Answer:
        """Answer a question with the notes that support it."""

        self.store.ensure_schema()
        hits = self.store.search(question, topic=topic, limit=limit)
        state = await self.memory.load(topic) if topic else None
        answer = Answer(question=question, topic=topic, hits=hits)
        answer.statements = list(self.store.statements)
        if state is not None:
            answer.open_notes = list(state.open_notes)
            answer.reviews = state.reviews
        return answer

    async def mark(self, topic: str, note_id: str, mastered: bool) -> TopicState:
        """Record that a note of a topic is mastered or still open."""

        state = await self.memory.load(topic)
        if state is None:
            state = TopicState(topic=topic)
        if mastered:
            if note_id not in state.mastered:
                state.mastered.append(note_id)
            if note_id in state.open_notes:
                state.open_notes.remove(note_id)
        else:
            if note_id not in state.open_notes:
                state.open_notes.append(note_id)
            if note_id in state.mastered:
                state.mastered.remove(note_id)
        state.reviews += 1
        await self.memory.save(state)
        return state

    async def progress(self) -> list[dict]:
        """Return the review progress of every topic."""

        states = await self.memory.all_states()
        summary = []
        for state in states:
            summary.append(
                {
                    "topic": state.topic,
                    "mastered": len(state.mastered),
                    "open": len(state.open_notes),
                    "reviews": state.reviews,
                    "questions": state.questions,
                }
            )
        return summary
