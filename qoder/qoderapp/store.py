"""Notes stored in seekdb and retrieved with a native fulltext query.

The desk keeps one table of notes.  Each note carries a topic, a title and
the body of the note, and the body carries a fulltext index so that one
``MATCH ... AGAINST`` statement ranks the notes inside the database.

The query side uses the tokenizer that the index was built with, so the two
sides always agree on where a word begins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pymysql

from qoderapp.config import Settings

TABLES = (
    """
CREATE TABLE IF NOT EXISTS desk_note (
      note_id    VARCHAR(191) NOT NULL PRIMARY KEY,
      topic      VARCHAR(128) NOT NULL,
      title      VARCHAR(256) NOT NULL,
      source_path VARCHAR(256) NOT NULL DEFAULT '',
      body       TEXT         NOT NULL
    )
    """,
)

# The fulltext indexes are built separately: a build can take the
# server down, so it only runs when the index is really missing.
INDEXES = (
    ("desk_note", "idx_desk_note_body", "CREATE FULLTEXT INDEX idx_desk_note_body ON desk_note (body) WITH PARSER ik"),
)

# The identifier column carries a path and a title, so it is wider than the
# 64 characters an early schema allowed.  An installation that already
# created the narrow table has to be migrated, otherwise the import fails
# with "Data too long for column".
MIGRATIONS = (
    ("desk_note", "note_id", 191, "VARCHAR(191) NOT NULL"),
    ("desk_note", "topic", 128, "VARCHAR(128) NOT NULL DEFAULT ''"),
    ("desk_note", "source_path", 256, "VARCHAR(256) NOT NULL DEFAULT ''"),
)


def _render(statement: str, parameters: list[object]) -> str:
    """Return the statement with its parameters inlined, for the log."""

    rendered = statement
    for value in parameters:
        rendered = rendered.replace("%s", f"'{value}'", 1)
    return rendered


def _fulltext_index_exists(cursor, database: str, table: str, index: str) -> bool:
    """Return whether the fulltext index is already installed.

    Building a fulltext index can take the server down, so the index is only
    built when it is really missing.
    """

    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s "
        "AND INDEX_TYPE='FULLTEXT'",
        (database, table, index),
    )
    row = cursor.fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _create_index(cursor, statement: str) -> None:
    """Build a fulltext index and report a lost server clearly.

    seekdb 1.3.0 on Windows can crash while it builds a fulltext index, so a
    lost connection is reported as such instead of a bare protocol error.
    """

    try:
        cursor.execute(statement)
    except pymysql.err.OperationalError as error:
        message = str(error)
        if "duplicate" in message.lower():
            # Another session installed the index first.
            return
        if "Lost connection" in message or "gone away" in message:
            raise RuntimeError(
                "the seekdb server closed the connection while it built the fulltext "
                "index; seekdb 1.3.0 on Windows crashes in the index build, so retry "
                "the command, or run the embedded engine (pylibseekdb) instead"
            ) from error
        raise


@dataclass(frozen=True)
class NoteHit:
    """One retrieved note."""

    note_id: str
    topic: str
    title: str
    source_path: str
    score: float
    snippet: str = ""


@dataclass
class NoteStore:
    """seekdb backed store of the notes."""

    settings: Settings
    statements: list[str] = field(default_factory=list)

    def connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password,
            charset="utf8mb4",
            autocommit=True,
        )

    def ensure_schema(self) -> None:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.settings.seekdb_database}`"
                )
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                for statement in TABLES:
                    try:
                        cursor.execute(statement)
                    except pymysql.MySQLError as error:
                        # A duplicate table is a ProgrammingError, so the
                        # already-installed schema is detected by message.
                        if "duplicate" not in str(error).lower():
                            raise
                for table, index, statement in INDEXES:
                    if _fulltext_index_exists(cursor, self.settings.seekdb_database, table, index):
                        continue
                    _create_index(cursor, statement)
                for table, column, width, definition in MIGRATIONS:
                    cursor.execute(
                        "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                        (self.settings.seekdb_database, table, column),
                    )
                    row = cursor.fetchone()
                    if row is None or int(row[0] or 0) >= width:
                        continue
                    cursor.execute(
                        f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` {definition}"
                    )
        finally:
            connection.close()

    def replace(self, notes: Iterable[dict]) -> None:
        """Replace the stored notes with the given rows."""

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                cursor.execute("DELETE FROM desk_note")
                for note in notes:
                    cursor.execute(
                        "INSERT INTO desk_note (note_id, topic, title, source_path, body) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            note["note_id"],
                            note["topic"],
                            note["title"],
                            note["source_path"],
                            note["body"],
                        ),
                    )
        finally:
            connection.close()

    def tokenize(self, text: str) -> list[str]:
        """Segment the text with the tokenizer that the fulltext index uses."""

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                cursor.execute("SELECT tokenize(%s, 'ik')", (text,))
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row or not row[0]:
            return []
        try:
            return [str(token) for token in json.loads(row[0]) if str(token).strip()]
        except (TypeError, ValueError):
            return []

    def search(self, query: str, topic: str = "", limit: int = 8) -> list[NoteHit]:
        """Return the notes that best match the query."""

        terms = self.tokenize(query)
        if not terms:
            return []
        expression = " ".join(terms)
        statement = (
            "SELECT note_id, topic, title, source_path, "
            "MATCH(body) AGAINST (%s IN BOOLEAN MODE) AS score, "
            "SUBSTRING(body, 1, 400) "
            "FROM desk_note "
            "WHERE MATCH(body) AGAINST (%s IN BOOLEAN MODE)"
        )
        parameters: list[object] = [expression, expression]
        if topic:
            statement += " AND topic = %s"
            parameters.append(topic)
        statement += " ORDER BY score DESC LIMIT %s"
        parameters.append(limit)
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                cursor.execute(statement, tuple(parameters))
                rows = cursor.fetchall()
        finally:
            connection.close()
        self.statements.append(_render(statement, parameters))
        return [
            NoteHit(
                note_id=str(row[0]),
                topic=str(row[1]),
                title=str(row[2]),
                source_path=str(row[3]),
                score=float(row[4]),
                snippet=" ".join(str(row[5]).split()),
            )
            for row in rows
        ]

    def topics(self) -> list[tuple[str, int]]:
        """Return every topic with the number of notes it holds."""

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                cursor.execute(
                    "SELECT topic, COUNT(*) FROM desk_note GROUP BY topic ORDER BY topic"
                )
                return [(str(row[0]), int(row[1])) for row in cursor.fetchall()]
        finally:
            connection.close()
