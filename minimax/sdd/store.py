"""Engineering material stored in seekdb and retrieved with a native fulltext query.

The module owns one schema with three tables: specifications, code symbols and
test cases.  Each table carries a single column fulltext index so that one
``MATCH ... AGAINST`` statement ranks the rows inside the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pymysql

from sdd.config import Settings

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS sdd_spec (
      spec_id   VARCHAR(191) NOT NULL PRIMARY KEY,
      title     VARCHAR(256) NOT NULL,
      file_path VARCHAR(256) NOT NULL DEFAULT '',
      body      TEXT         NOT NULL
    )
    """,
    "CREATE FULLTEXT INDEX idx_sdd_spec_body ON sdd_spec (body) WITH PARSER ik",
    """
    CREATE TABLE IF NOT EXISTS sdd_symbol (
      symbol_id    VARCHAR(191) NOT NULL PRIMARY KEY,
      file_path    VARCHAR(256) NOT NULL,
      symbol       VARCHAR(128) NOT NULL,
      kind         VARCHAR(32)  NOT NULL DEFAULT '',
      spec_id      VARCHAR(191) NOT NULL DEFAULT '',
      related_test VARCHAR(191) NOT NULL DEFAULT '',
      body         TEXT         NOT NULL
    )
    """,
    "CREATE FULLTEXT INDEX idx_sdd_symbol_body ON sdd_symbol (body) WITH PARSER ik",
    """
    CREATE TABLE IF NOT EXISTS sdd_test (
      test_id   VARCHAR(191) NOT NULL PRIMARY KEY,
      file_path VARCHAR(256) NOT NULL,
      name      VARCHAR(256) NOT NULL,
      body      TEXT         NOT NULL
    )
    """,
    "CREATE FULLTEXT INDEX idx_sdd_test_body ON sdd_test (body) WITH PARSER ik",
)

# The identifier columns carry a path and a symbol name, so they are wider
# than the 64 characters an early schema allowed.  An installation that
# already created the narrow tables has to be migrated, otherwise the import
# fails with "Data too long for column".  The primary key is not repeated in
# the definition: seekdb rejects a second PRIMARY KEY clause on an existing
# key column, while the key itself survives the column change.
MIGRATIONS = (
    ("sdd_spec", "spec_id", "VARCHAR(191) NOT NULL"),
    ("sdd_symbol", "symbol_id", "VARCHAR(191) NOT NULL"),
    ("sdd_symbol", "spec_id", "VARCHAR(191) NOT NULL DEFAULT ''"),
    ("sdd_symbol", "related_test", "VARCHAR(191) NOT NULL DEFAULT ''"),
    ("sdd_test", "test_id", "VARCHAR(191) NOT NULL"),
)


@dataclass(frozen=True)
class MaterialHit:
    """One retrieved row."""

    kind: str
    identifier: str
    title: str
    file_path: str
    score: float
    detail: str
    related: str = ""


@dataclass
class MaterialStore:
    """seekdb-backed store of specifications, code symbols and tests."""

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
                for statement in SCHEMA:
                    try:
                        cursor.execute(statement)
                    except pymysql.MySQLError as error:
                        # "Duplicate key name" is raised as an OperationalError
                        # while a duplicate table is a ProgrammingError, so the
                        # already-installed schema is detected by message.
                        if "duplicate" not in str(error).lower():
                            raise
                for table, column, definition in MIGRATIONS:
                    cursor.execute(
                        "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                        (self.settings.seekdb_database, table, column),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        continue
                    width = int(row[0] or 0)
                    if width >= 191:
                        continue
                    cursor.execute(
                        f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` {definition}"
                    )
        finally:
            connection.close()

    def replace(self, specs: Iterable[dict], symbols: Iterable[dict], tests: Iterable[dict]) -> None:
        """Replace the stored material with the given rows."""

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                for table in ("sdd_spec", "sdd_symbol", "sdd_test"):
                    cursor.execute(f"DELETE FROM {table}")
                for row in specs:
                    cursor.execute(
                        "INSERT INTO sdd_spec (spec_id, title, file_path, body) "
                        "VALUES (%s, %s, %s, %s)",
                        (row["spec_id"], row["title"], row["file_path"], row["body"]),
                    )
                for row in symbols:
                    cursor.execute(
                        "INSERT INTO sdd_symbol (symbol_id, file_path, symbol, kind, spec_id, "
                        "related_test, body) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (
                            row["symbol_id"],
                            row["file_path"],
                            row["symbol"],
                            row.get("kind", ""),
                            row.get("spec_id", ""),
                            row.get("related_test", ""),
                            row["body"],
                        ),
                    )
                for row in tests:
                    cursor.execute(
                        "INSERT INTO sdd_test (test_id, file_path, name, body) "
                        "VALUES (%s, %s, %s, %s)",
                        (row["test_id"], row["file_path"], row["name"], row["body"]),
                    )
        finally:
            connection.close()

    def _search(self, table: str, columns: str, query: str, limit: int) -> list[MaterialHit]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                statement = (
                    f"SELECT {columns}, MATCH(body) AGAINST (%s IN BOOLEAN MODE) AS score "
                    f"FROM {table} "
                    "WHERE MATCH(body) AGAINST (%s IN BOOLEAN MODE) "
                    "ORDER BY score DESC LIMIT %s"
                )
                cursor.execute(statement, (query, query, limit))
                rows = cursor.fetchall()
        finally:
            connection.close()
        self.statements.append(statement % (query, query, limit))
        return rows

    def spec_bodies(self, spec_ids: list[str]) -> list[str]:
        """Read the body of the given specifications.

        The module needs the specification text to learn which identifiers the
        code and the test index have to be searched with.
        """

        if not spec_ids:
            return []
        placeholders = ", ".join(["%s"] * len(spec_ids))
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{self.settings.seekdb_database}`")
                cursor.execute(
                    f"SELECT body FROM sdd_spec WHERE spec_id IN ({placeholders})",
                    tuple(spec_ids),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [str(row[0]) for row in rows]

    def search_specs(self, query: str, limit: int = 5) -> list[MaterialHit]:
        rows = self._search(
            "sdd_spec", "spec_id, title, file_path", query, limit
        )
        return [
            MaterialHit("spec", str(row[0]), str(row[1]), str(row[2]), float(row[3]), "")
            for row in rows
        ]

    def search_symbols(self, query: str, limit: int = 8) -> list[MaterialHit]:
        rows = self._search(
            "sdd_symbol", "symbol_id, symbol, file_path, kind, spec_id, related_test", query, limit
        )
        return [
            MaterialHit(
                "symbol",
                str(row[0]),
                str(row[1]),
                str(row[2]),
                float(row[6]),
                str(row[4]),
                str(row[5]),
            )
            for row in rows
        ]

    def search_tests(self, query: str, limit: int = 8) -> list[MaterialHit]:
        rows = self._search("sdd_test", "test_id, name, file_path", query, limit)
        return [
            MaterialHit("test", str(row[0]), str(row[1]), str(row[2]), float(row[3]), "")
            for row in rows
        ]
