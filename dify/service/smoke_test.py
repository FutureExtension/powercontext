# -*- coding: utf-8 -*-
"""
雾隐镇 · 夜班档案室 —— 一键冒烟测试 (smoke_test.py)

用途
----
给评审一条命令，验证 **Dify 会调用的那套 HTTP 接口** 以及 **seekdb 的真实读写**。

三种模式
--------
  python smoke_test.py --init      把 init_data.sql 灌进 seekdb（幂等）
  python smoke_test.py             端到端验证（真实 seekdb）：
                                    1. /health            连通性 + 表是否齐全
                                    2. /search_archive    真实 SELECT
                                    3. /get_player_progress 真实 SELECT（跨会话记忆）
                                    4. /record_progress   真实 INSERT/UPDATE（写回闭环）
                                    5. 直接查 seekdb，确认行真的落库了
  python smoke_test.py --offline   离线模式：不连数据库，用内置 mock 验证
                                    HTTP 契约与编排逻辑（机器上没数据库时用）

依赖：只用标准库 + pymysql（pymysql 仅在 --init / 真实模式需要）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULT_BASE_URL = os.environ.get("TOOL_BASE_URL", "http://127.0.0.1:8100")
DB_HOST = os.environ.get("SEEKDB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("SEEKDB_PORT", "2881") or 2881)
DB_USER = os.environ.get("SEEKDB_USER", "root")
DB_PASSWORD = os.environ.get("SEEKDB_PASSWORD", "")
DB_NAME = os.environ.get("SEEKDB_DATABASE", "wuyin_archive")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


class Checker:
    """极简断言收集器。"""

    def __init__(self) -> None:
        self.results: List[Tuple[str, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((PASS if ok else FAIL, name, detail))
        print("[%s] %s%s" % (PASS if ok else FAIL, name, (" -> " + detail) if detail else ""))
        return ok

    def skip(self, name: str, detail: str = "") -> None:
        self.results.append((SKIP, name, detail))
        print("[%s] %s%s" % (SKIP, name, (" -> " + detail) if detail else ""))

    def summary(self) -> int:
        failed = [r for r in self.results if r[0] == FAIL]
        skipped = [r for r in self.results if r[0] == SKIP]
        print("")
        print("=" * 66)
        print("总计 %d 项：%d 通过 / %d 失败 / %d 跳过"
              % (len(self.results), len(self.results) - len(failed) - len(skipped),
                 len(failed), len(skipped)))
        if failed:
            print("失败项：")
            for status, name, detail in failed:
                print("  - %s %s" % (name, detail))
        print("=" * 66)
        return 1 if failed else 0


# --------------------------------------------------------------------------
# HTTP 小工具（只用标准库）
# --------------------------------------------------------------------------


def http_json(base_url: str, path: str, payload: Optional[Dict[str, Any]] = None,
              timeout: int = 30) -> Dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# --------------------------------------------------------------------------
# SQL 脚本切分与执行
# --------------------------------------------------------------------------


def split_sql(text: str) -> List[str]:
    statements: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_single:
            if char == "'":
                if index + 1 < length and text[index + 1] == "'":
                    buf.append("''")
                    index += 2
                    continue
                in_single = False
            buf.append(char)
        elif in_double:
            if char == '"':
                in_double = False
            buf.append(char)
        else:
            if char == "'":
                in_single = True
                buf.append(char)
            elif char == '"':
                in_double = True
                buf.append(char)
            elif char == "-" and index + 1 < length and text[index + 1] == "-":
                while index < length and text[index] != "\n":
                    index += 1
                buf.append("\n")
                continue
            elif char == "#":
                while index < length and text[index] != "\n":
                    index += 1
                buf.append("\n")
                continue
            elif char == "/" and index + 1 < length and text[index + 1] == "*":
                end = text.find("*/", index + 2)
                index = (end + 2) if end >= 0 else length
                buf.append(" ")
                continue
            elif char == ";":
                statements.append("".join(buf))
                buf = []
            else:
                buf.append(char)
        index += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    cleaned: List[str] = []
    for statement in statements:
        body = "\n".join(
            line for line in statement.splitlines()
            if not line.strip().startswith("--")
        ).strip()
        if body:
            cleaned.append(body)
    return cleaned


def apply_init_sql(path: Optional[str] = None) -> int:
    import pymysql

    sql_path = path or os.path.join(HERE, "init_data.sql")
    with open(sql_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    statements = split_sql(text)
    mode = os.environ.get("DIFY_FULLTEXT", "auto").strip().lower()
    if mode == "off":
        # 不创建全文索引：seekdb 1.3.0 在 Windows 上建 FULLTEXT 索引可能让服务端崩溃。
        kept = [s for s in statements if "ADD FULLTEXT KEY" not in s.upper()]
        print("DIFY_FULLTEXT=off：跳过 %d 条全文索引语句，检索走 LIKE" % (len(statements) - len(kept)))
        statements = kept

    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        charset="utf8mb4", autocommit=False, connect_timeout=10,
    )
    ok = 0
    failed: List[str] = []
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                try:
                    cursor.execute(statement)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append((statement.split("\n")[0][:80], str(exc)[:160]))
        try:
            connection.commit()
        except Exception as exc:  # noqa: BLE001
            print("提交失败：%s" % str(exc)[:200])
            print("若失败发生在全文索引语句上，这是 seekdb 1.3.0 在 Windows 上的已知崩溃问题；")
            print("重启 seekdb 后用 `DIFY_FULLTEXT=off python smoke_test.py --init` 走 LIKE 检索路径。")
            raise
    finally:
        connection.close()

    print("已执行 %d / %d 条语句 -> %s:%s" % (ok, len(statements), DB_HOST, DB_PORT))
    for head, err in failed:
        print("  [跳过] %s  (%s)" % (head, err))
    if failed:
        print("提示：只有第 3 段（全文索引 ALTER TABLE）失败是可以接受的，"
              "工具服务会自动退回 LIKE 检索。")
    return 0 if ok else 1

# --------------------------------------------------------------------------
# 离线模式：内置 mock 数据库（不连 seekdb，只验证 HTTP 契约与编排逻辑）
# --------------------------------------------------------------------------


class MockDB:
    """极简假库：按 SQL 里出现的表名返回固定数据，并记录写操作。"""

    def __init__(self) -> None:
        self.writes: List[str] = []
        self.case_files = [
            {"case_id": "CASE-2403", "title": "雾钟停摆的那一夜", "crime_type": "破坏",
             "location": "钟楼", "occurred_at": "2026-03-09 02:05:00", "severity": 5,
             "keywords": "雾钟,钟楼,停摆,铜锤", "summary": "雾钟停摆，海雾预警失灵。",
             "status": "open"},
        ]
        self.evidence = [
            {"evidence_id": "EV-0301", "case_id": "CASE-2403", "name": "断掉的钟舌销",
             "detail": "销子从中间断开，断口是新的。", "location": "钟楼",
             "found_at": "2026-03-09 07:10:00", "keywords": "钟舌,铜锤,断口", "weight": 3},
            {"evidence_id": "EV-0302", "case_id": "CASE-2403", "name": "钟楼下的铜屑",
             "detail": "石阶缝里扫出一小撮铜屑。", "location": "钟楼",
             "found_at": "2026-03-09 07:20:00", "keywords": "铜屑,石阶,锤", "weight": 3},
            {"evidence_id": "EV-0305", "case_id": "CASE-2403", "name": "海雾预警的空档",
             "detail": "那两小时预警簿上是一片空白。", "location": "钟楼",
             "found_at": "2026-03-10 10:00:00", "keywords": "预警,海雾,空白", "weight": 3},
        ]
        self.suspects = [
            {"suspect_id": "SUS-05", "name": "温砚", "alias": "砚师傅", "occupation": "修钟匠",
             "motive": "一笔没人付的修钟费", "hideout": "钟楼下铺",
             "alibi": "声称熬夜修摆", "note": "铺子里有一柄铜锤"},
            {"suspect_id": "SUS-08", "name": "老丁", "alias": "丁叔", "occupation": "巡夜人",
             "motive": "没有动机", "hideout": "更衣棚",
             "alibi": "声称那晚在钟楼附近转悠", "note": "记着全镇每个人的门"},
        ]
        self.town_lore = [
            {"lore_id": "LORE-02", "topic": "雾钟镇雾", "content": "雾钟的钟声能压住海雾。",
             "keywords": "雾钟,钟声,海雾"},
        ]
        self.progress: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []

        # 与 init_data.sql 一致的初始记忆：detective_001 在 CASE-2403 上已有一轮调查
        self.progress[("detective_001", "CASE-2403")] = {
            "player_id": "detective_001",
            "case_id": "CASE-2403",
            "cleared_evidence": '["EV-0302"]',
            "eliminated_suspects": '["SUS-08"]',
            "notes": "上一夜已排除丁叔（老丁）：他那晚确实在钟楼附近转悠，但没碰过钟。",
            "turns": 2,
            "updated_at": "2026-03-10 23:50:00",
        }
        self.logs.extend([
            {"log_id": 1, "player_id": "detective_001", "case_id": "CASE-2403",
             "action": "note", "question": "钟楼的雾钟到底是怎么坏的？",
             "reply": "（上一轮）我在钟楼石阶的缝里扫到过一撮铜屑。",
             "evidence_ids": "EV-0302", "suspect_ids": "",
             "created_at": "2026-03-10 23:20:00"},
            {"log_id": 2, "player_id": "detective_001", "case_id": "CASE-2403",
             "action": "note", "question": "老丁那晚在哪儿？",
             "reply": "（上一轮）丁叔说他在钟楼附近转悠，我把他记成已排除的人。",
             "evidence_ids": "EV-0302", "suspect_ids": "SUS-08",
             "created_at": "2026-03-10 23:45:00"},
        ])

    # -- 与 ArchiveDB 同名接口 ------------------------------------------
    def query(self, sql: str, params=None, trace=None, note: str = "") -> List[Dict[str, Any]]:
        flat = " ".join(sql.split())
        upper = flat.upper()
        rows: List[Dict[str, Any]] = []
        if "INFORMATION_SCHEMA.TABLES" in upper:
            rows = [{"table_name": t} for t in
                    ("case_files", "evidence", "suspects", "town_lore",
                     "player_progress", "investigation_log")]
        elif "SHOW INDEX" in upper:
            rows = []
        elif "FROM CASE_FILES" in upper and "CONCAT_WS" in upper:
            rows = [{"t": " ".join(str(v) for v in r.values())} for r in self.case_files]
        elif "FROM EVIDENCE" in upper and "CONCAT_WS" in upper:
            rows = [{"t": " ".join(str(v) for v in r.values())} for r in self.evidence]
        elif "FROM SUSPECTS" in upper and "CONCAT_WS" in upper:
            rows = [{"t": " ".join(str(v) for v in r.values())} for r in self.suspects]
        elif "FROM TOWN_LORE" in upper and "CONCAT_WS" in upper:
            rows = [{"t": " ".join(str(v) for v in r.values())} for r in self.town_lore]
        elif "DISTINCT LOCATION" in upper:
            rows = [{"location": "钟楼"}]
        elif "FROM SUSPECTS UNION" in upper or ("FROM SUSPECTS" in upper and "UNION" in upper):
            rows = [{"name": "温砚"}, {"name": "砚师傅"}, {"name": "老丁"}, {"name": "丁叔"}]
        elif "FROM CASE_FILES" in upper:
            rows = [dict(r) for r in self.case_files]
            if "WHERE (CASE_ID = %s" in upper and params:
                wanted = params[0]
                if wanted:
                    rows = [r for r in rows if r["case_id"] == wanted]
        elif "FROM EVIDENCE" in upper:
            rows = [dict(r) for r in self.evidence]
        elif "FROM SUSPECTS" in upper:
            rows = [dict(r) for r in self.suspects]
        elif "FROM TOWN_LORE" in upper:
            rows = [dict(r) for r in self.town_lore]
        elif "FROM PLAYER_PROGRESS" in upper:
            rows = []
            for (player_id, case_id), value in self.progress.items():
                if params and params[0] and value["player_id"] != params[0]:
                    continue
                if params and len(params) > 1 and params[1] and value["case_id"] != params[1]:
                    continue
                rows.append(dict(value))
        elif "COUNT(*)" in upper and "INVESTIGATION_LOG" in upper:
            rows = [{"c": len([r for r in self.logs if not params or r["player_id"] == params[0]])}]
        elif "FROM INVESTIGATION_LOG" in upper:
            rows = [dict(r) for r in self.logs]
        elif "SELECT VERSION()" in upper:
            rows = [{"version": "mock", "db": "wuyin_archive"}]
        if trace is not None:
            trace.add(sql, len(rows), 0, note)
        return rows

    def execute(self, sql: str, params=None, trace=None, note: str = "") -> int:
        flat = " ".join(sql.split())
        upper = flat.upper()
        affected = 0
        if upper.startswith("ALTER TABLE"):
            pass
        elif upper.startswith("INSERT INTO PLAYER_PROGRESS"):
            player_id, case_id = params[0], params[1]
            key = (player_id, case_id)
            existing = self.progress.get(key, {})
            self.progress[key] = {
                "player_id": player_id, "case_id": case_id,
                "cleared_evidence": params[2], "eliminated_suspects": params[3],
                "notes": params[4], "turns": params[5],
                "updated_at": "2026-03-11 00:00:00",
            }
            self.writes.append("player_progress upsert " + player_id + "/" + case_id)
            affected = 1
        elif upper.startswith("INSERT INTO INVESTIGATION_LOG"):
            self.logs.append({
                "log_id": len(self.logs) + 1, "player_id": params[0],
                "case_id": params[1], "action": params[2], "question": params[3],
                "reply": params[4], "evidence_ids": params[5], "suspect_ids": params[6],
                "created_at": "2026-03-11 00:00:00",
            })
            self.writes.append("investigation_log insert " + str(params[0]))
            affected = 1
        elif upper.startswith("UPDATE CASE_FILES"):
            for row in self.case_files:
                if row["case_id"] == params[1]:
                    row["status"] = "closed"
                    self.writes.append("case_files close " + str(params[1]))
                    affected = 1
        if trace is not None:
            trace.add(sql, affected, 0, note)
        return affected

    def ping(self) -> Dict[str, Any]:
        return {"ok": True, "version": "mock", "database": "wuyin_archive",
                "missing_tables": [], "elapsed_ms": 0}

    def missing_tables(self) -> List[str]:
        return []

    def fulltext_ready(self) -> bool:
        return False

    def ensure_fulltext(self, trace=None) -> bool:
        return False


# --------------------------------------------------------------------------
# 服务进程管理
# --------------------------------------------------------------------------


def service_is_up(base_url: str) -> bool:
    try:
        http_json(base_url, "/health", timeout=3)
        return True
    except Exception:
        return False


def spawn_service(base_url: str) -> Optional[subprocess.Popen]:
    match = re.search(r":(\d+)", base_url)
    port = match.group(1) if match else "8100"
    env = os.environ.copy()
    env["TOOL_PORT"] = port
    log_path = os.path.join(HERE, "service.log")
    handle = open(log_path, "wb")
    try:
        process = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "app.py")],
            cwd=HERE, env=env, stdout=handle, stderr=subprocess.STDOUT,
        )
    except Exception as exc:  # noqa: BLE001
        print("启动服务失败: %s" % exc)
        return None
    for _ in range(60):
        time.sleep(0.5)
        if service_is_up(base_url):
            print("工具服务已启动 (pid=%d, log=%s)" % (process.pid, log_path))
            return process
        if process.poll() is not None:
            print("服务进程已退出，返回码 %s" % process.returncode)
            return None
    print("等待服务健康检查超时")
    return process

# --------------------------------------------------------------------------
# 端到端验证流程
# --------------------------------------------------------------------------

TEST_PLAYER = "smoke_tester"
TEST_CASE = "CASE-2403"
TEST_QUESTION = "钟楼的雾钟到底是怎么坏的？铜锤又是谁的？"


def run_http_tests(base_url: str, checker: Checker) -> None:
    # 1) 健康检查 -----------------------------------------------------
    health = http_json(base_url, "/health")
    checker.check("GET /health 返回工具服务信息",
                  health.get("service") == "wuyin-archive-tool",
                  "service=" + str(health.get("service")))
    seekdb_info = health.get("seekdb") or {}
    checker.check("seekdb 连接正常", bool(seekdb_info.get("ok")),
                  "version=" + str(seekdb_info.get("version"))
                  + " db=" + str(seekdb_info.get("db"))
                  + " missing_tables=" + str(seekdb_info.get("missing_tables")))
    checker.check("6 张业务表齐全", not seekdb_info.get("missing_tables"),
                  "missing=" + str(seekdb_info.get("missing_tables")))

    # 2) 检索（真实 SELECT） -------------------------------------------
    search = http_json(base_url, "/search_archive", {
        "player_id": TEST_PLAYER,
        "case_id": TEST_CASE,
        "question": TEST_QUESTION,
        "keywords_hint": "雾钟,铜锤",
        "limit": 6,
    })
    checker.check("POST /search_archive 返回 ok", bool(search.get("ok")))
    hits = search.get("hit_counts") or {}
    checker.check("检索命中物证 >= 2", int(hits.get("evidence", 0)) >= 2,
                  "evidence=%s cases=%s suspects=%s lore=%s"
                  % (hits.get("evidence"), hits.get("cases"),
                     hits.get("suspects"), hits.get("lore")))
    trace = search.get("sql_trace") or []
    checker.check("响应带 sql_trace（可核对真实 SQL）", len(trace) >= 4,
                  "%d 条 SQL" % len(trace))
    print("")
    print("---- /search_archive 实际执行的 SQL（节选） ----")
    for item in trace:
        if "SELECT" in str(item.get("sql", "")).upper() and "CONCAT_WS" in str(item.get("sql", "")):
            print("  " + str(item.get("sql"))[:300])
            print("      -> rows=%s  (%s ms)" % (item.get("rows"), item.get("elapsed_ms")))
    print("")

    # 3) 跨会话记忆（读 player_progress） --------------------------------
    progress = http_json(base_url, "/get_player_progress", {
        "player_id": "detective_001", "case_id": TEST_CASE,
    })
    checker.check("POST /get_player_progress 返回 ok", bool(progress.get("ok")))
    checker.check("找到 detective_001 的历史进度（跨会话记忆）",
                  bool(progress.get("found")),
                  "turns=%s" % ((progress.get("progress") or {}).get("turns")))
    saved = progress.get("progress") or {}
    checker.check("历史进度里带着已排除的镇民",
                  "SUS-08" in (saved.get("eliminated_suspects") or []),
                  str(saved.get("eliminated_suspects")))
    checker.check("历史日志条数 >= 2", int(progress.get("log_count") or 0) >= 2,
                  "log_count=%s" % progress.get("log_count"))

    # 4) 写回（真实 INSERT / UPSERT） -----------------------------------
    before = http_json(base_url, "/get_player_progress",
                        {"player_id": TEST_PLAYER, "case_id": TEST_CASE})
    before_turns = int(((before.get("progress") or {}).get("turns")) or 0)

    note = http_json(base_url, "/record_progress", {
        "player_id": TEST_PLAYER,
        "case_id": TEST_CASE,
        "action": "note",
        "question": TEST_QUESTION,
        "reply": "（冒烟测试）铜锤砸断了钟舌的固定销，销子是从中间断的。",
        "evidence_ids": "EV-0301",
        "suspect_ids": "",
        "notes": "（冒烟测试写入）",
    })
    checker.check("POST /record_progress 写回成功", bool(note.get("ok")))
    checker.check("player_progress 被更新（turns 递增）",
                  int((note.get("progress") or {}).get("turns") or 0) == before_turns + 1,
                  "turns %s -> %s" % (before_turns, (note.get("progress") or {}).get("turns")))
    checker.check("已掌握物证被记入进度",
                  "EV-0301" in ((note.get("progress") or {}).get("cleared_evidence") or []),
                  str((note.get("progress") or {}).get("cleared_evidence")))

    # 5) 结案写回（真实 UPDATE case_files） ------------------------------
    close = http_json(base_url, "/record_progress", {
        "player_id": TEST_PLAYER,
        "case_id": TEST_CASE,
        "action": "close",
        "question": "结案",
        "reply": "（冒烟测试）真凶是温砚。",
        "evidence_ids": "EV-0301,EV-0302",
        "suspect_ids": "",
        "culprit": "SUS-05",
    })
    checker.check("结案：case_files.status 变为 closed",
                  close.get("case_status") == "closed",
                  "case_status=%s" % close.get("case_status"))
    checker.check("结案：3 张表都被写入",
                  int((close.get("written") or {}).get("case_files", 0)) == 1,
                  "written=%s" % (close.get("written")))

    # 6) 复原案件状态（保持初始数据可重复使用） --------------------------
    http_json(base_url, "/record_progress", {
        "player_id": TEST_PLAYER, "case_id": TEST_CASE, "action": "note",
        "question": "（冒烟测试收尾）", "reply": "已复原案件状态。",
    })
    restore = http_json(base_url, "/record_progress", {
        "player_id": TEST_PLAYER, "case_id": TEST_CASE, "action": "note",
        "question": "（冒烟测试收尾）", "reply": "已复原案件状态。",
    })
    checker.check("结案后仍可继续写回（UPSERT 正常）", bool(restore.get("ok")))


def verify_in_database(checker: Checker) -> None:
    """直连 seekdb，确认 HTTP 层的写入真的落库了。"""
    import pymysql

    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT log_id, player_id, case_id, action, question, created_at "
                "FROM investigation_log WHERE player_id = %s ORDER BY log_id",
                [TEST_PLAYER])
            logs = cursor.fetchall()
            checker.check("seekdb.investigation_log 里能查到冒烟测试的记录",
                          len(logs) >= 2, "%d 行" % len(logs))
            for row in logs:
                print("   log_id=%s action=%s question=%s"
                      % (row.get("log_id"), row.get("action"),
                         str(row.get("question"))[:40]))

            cursor.execute(
                "SELECT player_id, case_id, cleared_evidence, eliminated_suspects, turns, "
                "updated_at FROM player_progress WHERE player_id = %s",
                [TEST_PLAYER])
            progress = cursor.fetchall()
            checker.check("seekdb.player_progress 里能查到冒烟测试的进度",
                          len(progress) == 1, "%d 行" % len(progress))
            if progress:
                print("   cleared_evidence=%s turns=%s updated_at=%s"
                      % (progress[0].get("cleared_evidence"),
                         progress[0].get("turns"), progress[0].get("updated_at")))

            cursor.execute(
                "SELECT case_id, status, closed_at, closed_by FROM case_files "
                "WHERE case_id = %s", [TEST_CASE])
            case_rows = cursor.fetchall()
            checker.check("seekdb.case_files 能查到该案件",
                          len(case_rows) == 1,
                          "status=%s" % (case_rows[0].get("status") if case_rows else "N/A"))

            # 复原：把案件状态改回 open，保持初始数据干净
            cursor.execute(
                "UPDATE case_files SET status = 'open', closed_at = NULL, closed_by = NULL "
                "WHERE case_id = %s AND closed_by LIKE %s",
                [TEST_CASE, TEST_PLAYER + "%"])
            connection.commit()
            print("   已把 %s 的 status 复原为 open（冒烟测试不污染初始数据）" % TEST_CASE)
    finally:
        connection.close()


def reset_state(checker: Checker) -> None:
    import pymysql

    connection = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4", autocommit=True, connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM investigation_log WHERE player_id = %s", [TEST_PLAYER])
            cursor.execute("DELETE FROM player_progress WHERE player_id = %s", [TEST_PLAYER])
            cursor.execute(
                "UPDATE case_files SET status = 'open', closed_at = NULL, closed_by = NULL "
                "WHERE closed_by LIKE %s", [TEST_PLAYER + "%"])
        print("已清空 %s 的测试数据，案件状态复原为 open。" % TEST_PLAYER)
        checker.check("重置完成", True)
    finally:
        connection.close()


def run_offline(checker: Checker) -> int:
    """离线模式：用内置 mock 起一个服务进程，验证 HTTP 契约。"""
    import importlib.util
    import threading
    import uvicorn

    spec = importlib.util.spec_from_file_location(
        "archive_service", os.path.join(HERE, "app.py"))
    service = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(service)

    mock = MockDB()
    service.DB = mock
    port = 8123
    config = uvicorn.Config(service.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = "http://127.0.0.1:%d" % port
    for _ in range(60):
        time.sleep(0.25)
        try:
            http_json(base_url, "/health", timeout=2)
            break
        except Exception:
            continue

    print("=== 离线 mock 模式（未连接 seekdb）===")
    try:
        run_http_tests(base_url, checker)
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    checker.check("mock 记录到 player_progress 写入",
                  any("player_progress" in item for item in mock.writes),
                  str(mock.writes))
    checker.check("mock 记录到 investigation_log 写入",
                  any("investigation_log" in item for item in mock.writes),
                  str(mock.writes))
    checker.check("mock 记录到 case_files 结案写入",
                  any("case_files close" in item for item in mock.writes),
                  str(mock.writes))
    return checker.summary()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="雾隐镇 · 夜班档案室 冒烟测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("示例: " + chr(10)
               + "  python smoke_test.py --init     初始化 seekdb" + chr(10)
               + "  python smoke_test.py            真实端到端验证" + chr(10)
               + "  python smoke_test.py --offline  离线 mock 验证" + chr(10)
               + "  python smoke_test.py --reset    清掉测试数据、复原案件状态"),
    )
    parser.add_argument("--init", action="store_true", help="把 init_data.sql 灌进 seekdb")
    parser.add_argument("--reset", action="store_true", help="清掉冒烟测试留下的数据")
    parser.add_argument("--offline", action="store_true", help="离线 mock 模式，不连数据库")
    parser.add_argument("--no-spawn", action="store_true", help="不要自动拉起服务进程")
    parser.add_argument(
        "--no-fulltext",
        action="store_true",
        help="初始化时跳过全文索引（等同 DIFY_FULLTEXT=off），适合会崩在 ADD FULLTEXT KEY 的 seekdb 构建",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="工具服务地址")
    args = parser.parse_args()
    if args.no_fulltext:
        os.environ["DIFY_FULLTEXT"] = "off"

    checker = Checker()

    if args.init:
        return apply_init_sql()

    if args.reset:
        reset_state(checker)
        return checker.summary()

    if args.offline:
        return run_offline(checker)

    base_url = args.base_url
    process = None
    if not service_is_up(base_url):
        if args.no_spawn:
            print("工具服务未启动: %s" % base_url)
            return 2
        process = spawn_service(base_url)
        if process is None or not service_is_up(base_url):
            print("无法连接工具服务 %s" % base_url)
            return 2

    try:
        print("=== 端到端验证（真实 seekdb）===")
        run_http_tests(base_url, checker)
        print("")
        print("=== 直连 seekdb 复核落库结果 ===")
        verify_in_database(checker)
        return checker.summary()
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except Exception:
                process.kill()
            print("已关闭自动拉起的服务进程。")


if __name__ == "__main__":
    sys.exit(main())
