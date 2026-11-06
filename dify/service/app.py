# -*- coding: utf-8 -*-
"""
雾隐镇 · 夜班档案室 —— seekdb 自定义工具服务 (Dify Custom Tool 后端)

作用
----
本服务是 Dify 应用《雾隐镇 · 夜班档案室》的自定义工具后端：

  * Dify 的「自定义工具」节点通过 HTTP 调用本服务；
  * 本服务用 pymysql（MySQL 协议）连接 seekdb，默认 127.0.0.1:2881；
  * 每次调用都把 **实际执行的 SQL** 放进响应的 sql_trace 字段，
    评审可以在 Dify 的节点执行记录里直接看到"到底查了哪张表、哪条 SQL"。

对外接口（与 custom_tool.yml 一一对应）
--------------------------------------
  POST /search_archive        检索卷宗 / 物证 / 镇民 / 镇志
  POST /get_player_progress   读取该侦探在该案上的调查进度（跨会话记忆）
  POST /record_progress       写回调查进度与问答日志（必要时结案）
  GET  /health                健康检查 + seekdb 连通性 + 表存在性

依赖
----
fastapi / uvicorn / pymysql 三个，详见 requirements.txt。
配置全部来自环境变量或同目录 .env（占位值见 .env.example）。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pymysql
from pymysql.cursors import DictCursor

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

APP_NAME = "wuyin-archive-tool"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------


def _load_dotenv(path: str = ".env") -> None:
    """极简 .env 解析：只处理 KEY=VALUE，忽略空行与 # 注释，不覆盖已有环境变量。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)) or default)
    except ValueError:
        return default


DB_CONFIG: Dict[str, Any] = {
    "host": _env_str("SEEKDB_HOST", "127.0.0.1"),
    "port": _env_int("SEEKDB_PORT", 2881),
    "user": _env_str("SEEKDB_USER", "root"),
    "password": os.environ.get("SEEKDB_PASSWORD", ""),
    "database": _env_str("SEEKDB_DATABASE", "wuyin_archive"),
    "charset": _env_str("SEEKDB_CHARSET", "utf8mb4"),
    "connect_timeout": _env_int("SEEKDB_CONNECT_TIMEOUT", 10),
    "read_timeout": _env_int("SEEKDB_READ_TIMEOUT", 30),
    "write_timeout": _env_int("SEEKDB_WRITE_TIMEOUT", 30),
}

# 可选的接口鉴权。留空表示不鉴权（局域网/本地演示最省事）。
TOOL_API_KEY = os.environ.get("TOOL_API_KEY", "").strip()

# 全文索引模式：
#   auto（默认）—— 缺索引就创建；创建失败则退回 LIKE 检索
#   on           —— 只用全文索引，不创建
#   off          —— 一次都不创建全文索引，直接用 LIKE 检索
# seekdb 1.3.0 在 Windows 上执行 ADD FULLTEXT KEY 可能让服务端进程崩溃，
# 那种环境请用 off：检索走 LIKE，功能不变，但不会触发建索引。
FULLTEXT_MODE = _env_str("DIFY_FULLTEXT", "auto").lower() or "auto"

# 需要维护全文索引的表及其 MATCH 列（列顺序必须与 FULLTEXT 索引一致）
FULLTEXT_SPECS: List[Tuple[str, str, str]] = [
    ("case_files", "ft_case_files", "keywords, summary"),
    ("evidence", "ft_evidence", "name, keywords, detail"),
    ("suspects", "ft_suspects", "name, alias"),
    ("town_lore", "ft_lore", "topic, content"),
]

REQUIRED_TABLES = ["case_files", "evidence", "suspects", "town_lore",
                   "player_progress", "investigation_log"]

# --------------------------------------------------------------------------
# SQL 执行与追踪
# --------------------------------------------------------------------------


class SqlTrace:
    """记录每次真实执行的 SQL，供评审核对。"""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, sql: str, rows: int, elapsed_ms: int, note: str = "") -> None:
        self.items.append({
            "sql": " ".join(sql.split()),
            "rows": rows,
            "elapsed_ms": elapsed_ms,
            "note": note,
        })

    def as_list(self) -> List[Dict[str, Any]]:
        return self.items


class ArchiveDB:
    """seekdb 访问层（MySQL 协议 / pymysql）。"""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._fulltext_ready: Optional[bool] = None

    # -- 连接 ------------------------------------------------------------
    def connect(self, with_database: bool = True):
        kwargs: Dict[str, Any] = {
            "host": self.config["host"],
            "port": self.config["port"],
            "user": self.config["user"],
            "password": self.config["password"],
            "charset": self.config["charset"],
            "cursorclass": DictCursor,
            "autocommit": False,
            "connect_timeout": self.config["connect_timeout"],
            "read_timeout": self.config["read_timeout"],
            "write_timeout": self.config["write_timeout"],
        }
        if with_database:
            kwargs["database"] = self.config["database"]
        return pymysql.connect(**kwargs)

    def query(self, sql: str, params: Optional[Sequence[Any]] = None,
              trace: Optional[SqlTrace] = None, note: str = "") -> List[Dict[str, Any]]:
        started = time.time()
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params or ()))
                rows = cur.fetchall()
            conn.rollback()
        finally:
            conn.close()
        elapsed = int((time.time() - started) * 1000)
        if trace is not None:
            trace.add(sql, len(rows), elapsed, note)
        return list(rows)

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None,
                trace: Optional[SqlTrace] = None, note: str = "") -> int:
        started = time.time()
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params or ()))
                affected = cur.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        elapsed = int((time.time() - started) * 1000)
        if trace is not None:
            trace.add(sql, int(affected), elapsed, note)
        return int(affected)

    # -- 全文索引探测 -----------------------------------------------------
    def _has_fulltext_index(self, table: str) -> bool:
        try:
            rows = self.query("SHOW INDEX FROM " + table)
        except Exception:
            return False
        for row in rows:
            index_type = str(row.get("Index_type", "") or "").upper()
            key_name = str(row.get("Key_name", "") or "").lower()
            if index_type == "FULLTEXT" or key_name.startswith("ft_"):
                return True
        return False

    def ensure_fulltext(self, trace: Optional[SqlTrace] = None) -> bool:
        """幂等地创建全文索引。失败不致命：检索会自动退回 LIKE 方案。"""
        if self._fulltext_ready is not None:
            return self._fulltext_ready
        if FULLTEXT_MODE == "off":
            # 明确关闭：不执行任何 ADD FULLTEXT KEY，避免触发 seekdb 的建索引崩溃。
            self._fulltext_ready = False
            if trace is not None:
                trace.add("DIFY_FULLTEXT=off", 0, 0, "按配置跳过全文索引创建，使用 LIKE 检索")
            return False
        ready = True
        for table, index_name, columns in FULLTEXT_SPECS:
            try:
                if self._has_fulltext_index(table):
                    continue
                self.execute(
                    "ALTER TABLE " + table + " ADD FULLTEXT KEY " + index_name
                    + " (" + columns + ")",
                    trace=trace,
                    note="创建全文索引",
                )
            except Exception as exc:  # pragma: no cover - 取决于 seekdb 版本
                ready = False
                if trace is not None:
                    trace.add(
                        "ALTER TABLE " + table + " ADD FULLTEXT KEY " + index_name,
                        0, 0, "全文索引创建失败（将退回 LIKE 检索）: " + str(exc)[:180],
                    )
        self._fulltext_ready = ready
        return ready

    def fulltext_ready(self) -> bool:
        if self._fulltext_ready is None:
            self.ensure_fulltext()
        return bool(self._fulltext_ready)

    # -- 表检查 -----------------------------------------------------------
    def missing_tables(self) -> List[str]:
        try:
            rows = self.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s",
                [self.config["database"]],
            )
        except Exception:
            return list(REQUIRED_TABLES)
        existing = {str(r.get("table_name", "")).lower() for r in rows}
        return [t for t in REQUIRED_TABLES if t not in existing]

    def ping(self) -> Dict[str, Any]:
        started = time.time()
        try:
            rows = self.query("SELECT VERSION() AS version, DATABASE() AS db")
            version = rows[0].get("version") if rows else "?"
            db = rows[0].get("db") if rows else "?"
            missing = self.missing_tables()
            return {
                "ok": True,
                "version": version,
                "database": db,
                "missing_tables": missing,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc)[:300],
                "target": "%s:%s/%s" % (self.config["host"], self.config["port"],
                                        self.config["database"]),
                "elapsed_ms": int((time.time() - started) * 1000),
            }


DB = ArchiveDB(DB_CONFIG)

# --------------------------------------------------------------------------
# 文本工具：从"问句"里抽出检索词（词典来自 seekdb 的真实语料）
# --------------------------------------------------------------------------

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,31}")
QUOTED = re.compile(r"[「『\"'《]([^」』\"'》]{1,24})[」』\"'》]")


def _text_of(row: Dict[str, Any], fields: Sequence[str]) -> str:
    parts = []
    for field in fields:
        value = row.get(field)
        if value is None:
            continue
        parts.append(str(value))
    return " ".join(parts)


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def extract_terms(question: str,
                  corpus: str,
                  locations: Sequence[str],
                  persons: Sequence[str],
                  hints: Sequence[str]) -> List[str]:
    """把自然语言问句变成检索词。

    词典 **完全来自 seekdb**：地点来自 case_files/evidence 的 location，
    人名来自 suspects 的 name/alias；中文按 2/3-gram 切分，
    只保留在数据库语料里真实出现过的字串，避免"雾钟是谁弄坏的"这种
    整句被当成关键词而查不到东西。
    """
    text = (question or "").strip()
    if not text:
        return _dedupe(hints)[:8]

    terms: List[str] = []
    terms.extend(hints)
    for loc in locations:
        if loc and loc in text:
            terms.append(loc)
    for person in persons:
        if person and person in text:
            terms.append(person)

    for run in CJK_RUN.findall(text):
        for size in (4, 3, 2):
            for index in range(len(run) - size + 1):
                gram = run[index:index + size]
                if gram in corpus:
                    terms.append(gram)

    for word in LATIN_WORD.findall(text):
        terms.append(word)

    # 长词优先，避免 "钟楼" 被 "楼" 淹没
    unique = _dedupe(terms)
    unique.sort(key=lambda item: (-len(item), item))
    return unique[:8]


def _score(row: Dict[str, Any], fields: Sequence[str], terms: Sequence[str]) -> int:
    haystack = _text_of(row, fields)
    score = 0
    for term in terms:
        if term and term in haystack:
            score += len(term)
    return score


# --------------------------------------------------------------------------
# 请求 / 响应模型
# --------------------------------------------------------------------------


class SearchArchiveRequest(BaseModel):
    player_id: str = Field(default="detective_001", description="侦探代号，对应 seekdb 的 player_progress.player_id")
    case_id: str = Field(default="", description="当前案件编号，例如 CASE-2403；留空表示不限案件")
    question: str = Field(default="", description="侦探的提问原文")
    keywords_hint: str = Field(default="", description="逗号分隔的显式关键词，例如 雾钟,钟楼")
    limit: int = Field(default=6, description="每类结果最多返回条数")


class GetProgressRequest(BaseModel):
    player_id: str = Field(default="detective_001", description="侦探代号")
    case_id: str = Field(default="", description="案件编号")


class RecordProgressRequest(BaseModel):
    player_id: str = Field(default="detective_001", description="侦探代号")
    case_id: str = Field(default="", description="案件编号")
    action: str = Field(default="note", description="note=记录一问一答；close=结案")
    question: str = Field(default="", description="侦探的提问原文")
    reply: str = Field(default="", description="阿灯这一轮的回答")
    evidence_ids: str = Field(default="", description="逗号分隔的已掌握物证编号")
    suspect_ids: str = Field(default="", description="逗号分隔的已排除嫌疑人编号")
    notes: str = Field(default="", description="补充笔记")
    culprit: str = Field(default="", description="结案时给出的真凶编号")


# --------------------------------------------------------------------------
# 业务：检索
# --------------------------------------------------------------------------


def _like_clause(column: str, terms: Sequence[str]) -> Tuple[str, List[Any]]:
    """构造 ( CONCAT_WS(' ', ...) LIKE %s OR ... ) 形式的关键词条件。"""
    if not terms:
        return "1 = 1", []
    parts = []
    params: List[Any] = []
    for term in terms:
        parts.append("CONCAT_WS(' ', " + column + ") LIKE %s")
        params.append("%" + term + "%")
    return "(" + " OR ".join(parts) + ")", params


def search_archive(req: SearchArchiveRequest) -> Dict[str, Any]:
    trace = SqlTrace()
    started = time.time()
    limit = max(1, min(int(req.limit or 6), 20))
    question = (req.question or "").strip()
    case_id = (req.case_id or "").strip()
    hints = [h.strip() for h in (req.keywords_hint or "").split(",") if h.strip()]

    # 1) 语料与词典全部来自 seekdb -------------------------------------
    corpus_rows = DB.query(
        "SELECT CONCAT_WS(' ', title, keywords, summary) AS t FROM case_files",
        trace=trace, note="读取卷宗语料")
    evidence_rows = DB.query(
        "SELECT CONCAT_WS(' ', name, keywords, detail) AS t FROM evidence",
        trace=trace, note="读取物证语料")
    suspect_rows = DB.query(
        "SELECT CONCAT_WS(' ', name, alias, occupation, motive) AS t FROM suspects",
        trace=trace, note="读取镇民语料")
    lore_rows = DB.query(
        "SELECT CONCAT_WS(' ', topic, content, keywords) AS t FROM town_lore",
        trace=trace, note="读取镇志语料")
    location_rows = DB.query(
        "SELECT DISTINCT location FROM case_files "
        "UNION SELECT DISTINCT location FROM evidence",
        trace=trace, note="读取地点词典")
    person_rows = DB.query(
        "SELECT name FROM suspects UNION SELECT alias FROM suspects",
        trace=trace, note="读取人名词典")

    corpus = " ".join(
        str(r.get("t", "") or "") for r in (corpus_rows + evidence_rows + suspect_rows + lore_rows)
    )
    locations = [str(r.get("location", "") or "") for r in location_rows]
    persons = [str(r.get("name", "") or "") for r in person_rows]
    terms = extract_terms(question, corpus, locations, persons, hints)

    use_fulltext = DB.fulltext_ready()

    # 2) 卷宗检索：结构化过滤 + 关键词条件 ------------------------------
    cases_sql = (
        "SELECT case_id, title, crime_type, location, occurred_at, severity, "
        "keywords, summary, status FROM case_files "
        "WHERE (case_id = %s OR %s = '') "
        "AND (location = %s OR %s = '') "
        "AND status <> 'closed' AND "
    )
    cases_params: List[Any] = [case_id, case_id, "", ""]
    if use_fulltext and terms:
        cases_sql += "(MATCH(keywords, summary) AGAINST (%s IN NATURAL LANGUAGE MODE) OR "
        cases_params.append(" ".join(terms))
    clause, clause_params = _like_clause("title, keywords, summary", terms)
    cases_sql += clause
    cases_params += clause_params
    cases_sql += " ORDER BY severity DESC, occurred_at DESC LIMIT %s"
    cases_params.append(limit * 3)

    cases = DB.query(cases_sql, cases_params, trace=trace, note="检索卷宗 case_files")

    # 3) 物证检索 -------------------------------------------------------
    evidence_sql = (
        "SELECT evidence_id, case_id, name, detail, location, found_at, keywords, weight "
        "FROM evidence WHERE (case_id = %s OR %s = '') AND "
    )
    evidence_params: List[Any] = [case_id, case_id]
    if use_fulltext and terms:
        evidence_sql += "(MATCH(name, keywords, detail) AGAINST (%s IN NATURAL LANGUAGE MODE) OR "
        evidence_params.append(" ".join(terms))
    clause, clause_params = _like_clause("name, keywords, detail", terms)
    evidence_sql += clause
    evidence_params += clause_params
    evidence_sql += " ORDER BY weight DESC, found_at ASC LIMIT %s"
    evidence_params.append(limit * 3)

    evidence = DB.query(evidence_sql, evidence_params, trace=trace, note="检索物证 evidence")

    # 4) 镇民检索 -------------------------------------------------------
    suspect_sql = (
        "SELECT suspect_id, name, alias, occupation, motive, hideout, alibi, note "
        "FROM suspects WHERE "
    )
    suspect_params: List[Any] = []
    if use_fulltext and terms:
        suspect_sql += "(MATCH(name, alias) AGAINST (%s IN NATURAL LANGUAGE MODE) OR "
        suspect_params.append(" ".join(terms))
    clause, clause_params = _like_clause("name, alias, occupation, motive, hideout", terms)
    suspect_sql += clause
    suspect_params += clause_params
    suspect_sql += " LIMIT %s"
    suspect_params.append(limit * 3)

    suspects = DB.query(suspect_sql, suspect_params, trace=trace, note="检索镇民 suspects")

    # 5) 镇志检索 -------------------------------------------------------
    lore_sql = "SELECT lore_id, topic, content, keywords FROM town_lore WHERE "
    lore_params: List[Any] = []
    if use_fulltext and terms:
        lore_sql += "(MATCH(topic, content) AGAINST (%s IN NATURAL LANGUAGE MODE) OR "
        lore_params.append(" ".join(terms))
    clause, clause_params = _like_clause("topic, content, keywords", terms)
    lore_sql += clause
    lore_params += clause_params
    lore_sql += " LIMIT %s"
    lore_params.append(limit * 3)

    lore = DB.query(lore_sql, lore_params, trace=trace, note="检索镇志 town_lore")

    # 6) 排序：命中的检索词越多、越长，分数越高 -------------------------
    def rank(rows: List[Dict[str, Any]], fields: Sequence[str]) -> List[Dict[str, Any]]:
        scored = []
        for row in rows:
            item = dict(row)
            item["score"] = _score(row, fields, terms)
            scored.append(item)
        scored.sort(key=lambda item: (-int(item["score"]), str(item.get("evidence_id") or item.get("case_id") or item.get("suspect_id") or item.get("lore_id") or "")))
        return scored[:limit]

    cases = rank(cases, ("title", "keywords", "summary"))
    evidence = rank(evidence, ("name", "keywords", "detail"))
    suspects = rank(suspects, ("name", "alias", "occupation", "motive", "hideout"))
    lore = rank(lore, ("topic", "content", "keywords"))

    return {
        "ok": True,
        "player_id": req.player_id,
        "case_id": case_id,
        "question": question,
        "keywords_hint": hints,
        "parsed": {
            "terms": terms,
            "locations": [loc for loc in locations if loc and loc in question],
            "persons": [p for p in persons if p and p in question],
        },
        "strategy": "fulltext+like" if use_fulltext else "like",
        "cases": cases,
        "evidence": evidence,
        "suspects": suspects,
        "lore": lore,
        "hit_counts": {
            "cases": len(cases),
            "evidence": len(evidence),
            "suspects": len(suspects),
            "lore": len(lore),
        },
        "sql_trace": trace.as_list(),
        "elapsed_ms": int((time.time() - started) * 1000),
    }

# --------------------------------------------------------------------------
# 业务：跨会话记忆（player_progress）与问答日志（investigation_log）
# --------------------------------------------------------------------------


def _load_id_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            value = json.loads(text)
            if isinstance(value, list):
                return _dedupe([str(item) for item in value])
        except (ValueError, TypeError):
            pass
    return _dedupe([item.strip() for item in text.split(",") if item.strip()])


def get_player_progress(req: GetProgressRequest) -> Dict[str, Any]:
    trace = SqlTrace()
    started = time.time()
    player_id = (req.player_id or "detective_001").strip()
    case_id = (req.case_id or "").strip()

    if case_id:
        rows = DB.query(
            "SELECT player_id, case_id, cleared_evidence, eliminated_suspects, notes, "
            "turns, updated_at FROM player_progress "
            "WHERE player_id = %s AND case_id = %s",
            [player_id, case_id], trace=trace, note="读取 player_progress")
    else:
        rows = DB.query(
            "SELECT player_id, case_id, cleared_evidence, eliminated_suspects, notes, "
            "turns, updated_at FROM player_progress "
            "WHERE player_id = %s ORDER BY updated_at DESC",
            [player_id], trace=trace, note="读取 player_progress（全部案件）")

    logs = DB.query(
        "SELECT log_id, case_id, action, question, reply, evidence_ids, suspect_ids, created_at "
        "FROM investigation_log WHERE player_id = %s"
        + (" AND case_id = %s" if case_id else "")
        + " ORDER BY log_id DESC LIMIT 5",
        [player_id, case_id] if case_id else [player_id],
        trace=trace, note="读取 investigation_log 最近 5 条")

    total = DB.query(
        "SELECT COUNT(*) AS c FROM investigation_log WHERE player_id = %s",
        [player_id], trace=trace, note="统计 investigation_log")

    progress = None
    if rows:
        row = rows[0]
        progress = {
            "player_id": row.get("player_id"),
            "case_id": row.get("case_id"),
            "cleared_evidence": _load_id_list(row.get("cleared_evidence")),
            "eliminated_suspects": _load_id_list(row.get("eliminated_suspects")),
            "notes": row.get("notes") or "",
            "turns": int(row.get("turns") or 0),
            "updated_at": str(row.get("updated_at")),
        }

    return {
        "ok": True,
        "player_id": player_id,
        "case_id": case_id,
        "found": progress is not None,
        "progress": progress,
        "all_progress": [
            {
                "case_id": r.get("case_id"),
                "cleared_evidence": _load_id_list(r.get("cleared_evidence")),
                "eliminated_suspects": _load_id_list(r.get("eliminated_suspects")),
                "turns": int(r.get("turns") or 0),
                "updated_at": str(r.get("updated_at")),
            }
            for r in rows
        ],
        "last_logs": [
            {
                "log_id": r.get("log_id"),
                "case_id": r.get("case_id"),
                "action": r.get("action"),
                "question": r.get("question"),
                "reply": (r.get("reply") or "")[:400],
                "created_at": str(r.get("created_at")),
            }
            for r in logs
        ],
        "log_count": int((total[0] or {}).get("c") or 0) if total else 0,
        "sql_trace": trace.as_list(),
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def record_progress(req: RecordProgressRequest) -> Dict[str, Any]:
    trace = SqlTrace()
    started = time.time()
    player_id = (req.player_id or "detective_001").strip()
    case_id = (req.case_id or "").strip()
    action = (req.action or "note").strip().lower()
    if action not in ("note", "close"):
        action = "note"

    new_evidence = _load_id_list(req.evidence_ids)
    new_suspects = _load_id_list(req.suspect_ids)

    existing = DB.query(
        "SELECT cleared_evidence, eliminated_suspects, notes, turns FROM player_progress "
        "WHERE player_id = %s AND case_id = %s",
        [player_id, case_id], trace=trace, note="读取旧进度（用于合并）")
    old_evidence: List[str] = []
    old_suspects: List[str] = []
    old_notes = ""
    turns = 0
    if existing:
        old_evidence = _load_id_list(existing[0].get("cleared_evidence"))
        old_suspects = _load_id_list(existing[0].get("eliminated_suspects"))
        old_notes = existing[0].get("notes") or ""
        turns = int(existing[0].get("turns") or 0)

    merged_evidence = _dedupe(old_evidence + new_evidence)
    merged_suspects = _dedupe(old_suspects + new_suspects)
    notes = old_notes
    if req.notes:
        notes = (notes + "\n" if notes else "") + req.notes
    notes = notes[:2000]
    turns = turns + 1

    DB.execute(
        "INSERT INTO player_progress "
        "(player_id, case_id, cleared_evidence, eliminated_suspects, notes, turns, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, NOW()) "
        "ON DUPLICATE KEY UPDATE cleared_evidence = VALUES(cleared_evidence), "
        "eliminated_suspects = VALUES(eliminated_suspects), notes = VALUES(notes), "
        "turns = VALUES(turns), updated_at = NOW()",
        [player_id, case_id, json.dumps(merged_evidence, ensure_ascii=False),
         json.dumps(merged_suspects, ensure_ascii=False), notes, turns],
        trace=trace, note="写回 player_progress")

    DB.execute(
        "INSERT INTO investigation_log "
        "(player_id, case_id, action, question, reply, evidence_ids, suspect_ids, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
        [player_id, case_id, action, (req.question or "")[:500], (req.reply or "")[:4000],
         ",".join(merged_evidence), ",".join(merged_suspects)],
        trace=trace, note="写入 investigation_log")

    case_status = "open"
    closed = 0
    if action == "close" and case_id:
        culprit = (req.culprit or "").strip()
        detail = "结案" + (("，真凶 " + culprit) if culprit else "")
        closed = DB.execute(
            "UPDATE case_files SET status = 'closed', closed_at = NOW(), closed_by = %s "
            "WHERE case_id = %s",
            [player_id + " / " + detail[:40], case_id],
            trace=trace, note="结案：更新 case_files.status")
        status_rows = DB.query(
            "SELECT status, closed_at, closed_by FROM case_files WHERE case_id = %s",
            [case_id], trace=trace, note="回读 case_files 状态")
        if status_rows:
            case_status = str(status_rows[0].get("status"))

    return {
        "ok": True,
        "action": action,
        "player_id": player_id,
        "case_id": case_id,
        "progress": {
            "cleared_evidence": merged_evidence,
            "eliminated_suspects": merged_suspects,
            "notes": notes,
            "turns": turns,
        },
        "case_status": case_status,
        "written": {
            "player_progress": 1,
            "investigation_log": 1,
            "case_files": closed,
        },
        "sql_trace": trace.as_list(),
        "elapsed_ms": int((time.time() - started) * 1000),
    }


# --------------------------------------------------------------------------
# HTTP 接口
# --------------------------------------------------------------------------

app = FastAPI(
    title="雾隐镇 · 夜班档案室 工具服务",
    version=APP_VERSION,
    description=(
        "《雾隐镇 · 夜班档案室》的 seekdb 工具后端。"
        "所有查询与写回都通过 MySQL 协议落在 seekdb 上，"
        "响应中的 sql_trace 字段记录了真实执行的 SQL。"
    ),
)


def _check_auth(x_api_key: Optional[str]) -> None:
    if not TOOL_API_KEY:
        return
    if x_api_key != TOOL_API_KEY:
        raise HTTPException(status_code=401, detail="X-Api-Key 不匹配")


@app.get("/health")
def health() -> JSONResponse:
    info = DB.ping()
    return JSONResponse(
        status_code=200 if info.get("ok") else 503,
        content={
            "service": APP_NAME,
            "version": APP_VERSION,
            "seekdb": info,
            "fulltext_enabled": DB.fulltext_ready(),
            "fulltext_mode": FULLTEXT_MODE,
            "auth_required": bool(TOOL_API_KEY),
        },
    )


@app.post("/search_archive")
def api_search_archive(payload: SearchArchiveRequest, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_auth(x_api_key)
    try:
        return search_archive(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="seekdb 查询失败: " + str(exc)[:400])


@app.post("/get_player_progress")
def api_get_player_progress(payload: GetProgressRequest, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_auth(x_api_key)
    try:
        return get_player_progress(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="seekdb 查询失败: " + str(exc)[:400])


@app.post("/record_progress")
def api_record_progress(payload: RecordProgressRequest, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_auth(x_api_key)
    try:
        return record_progress(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="seekdb 写回失败: " + str(exc)[:400])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=_env_str("TOOL_HOST", "0.0.0.0"),
        port=_env_int("TOOL_PORT", 8100),
        log_level=_env_str("TOOL_LOG_LEVEL", "info"),
    )
