# -*- coding: utf-8 -*-
"""SQLite 存取层。所有界面都通过这里读写账号。"""

import sqlite3
from datetime import datetime

import paths

# 注意：不要写成 Path(__file__).with_name("data.db")——打包成 exe 后 __file__
# 指向临时解包目录，数据库会每次启动重建、退出即删。见 paths.py。
DB_PATH = paths.db_path()

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    email              TEXT UNIQUE NOT NULL,
    password           TEXT DEFAULT '',
    client_id          TEXT DEFAULT '',
    refresh_token      TEXT DEFAULT '',
    recovery_email     TEXT DEFAULT '',
    recovery_password  TEXT DEFAULT '',
    group_name         TEXT DEFAULT '',
    note               TEXT DEFAULT '',
    status             TEXT DEFAULT '未取件',
    last_error         TEXT DEFAULT '',
    last_fetch_at      TEXT DEFAULT '',
    token_updated_at   TEXT DEFAULT '',
    access_token       TEXT DEFAULT '',
    access_expires_at  REAL DEFAULT 0,
    imap_host          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);

CREATE TABLE IF NOT EXISTS token_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    refresh_token TEXT,
    source        TEXT,
    changed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_account ON token_history(account_id);
"""

COLUMNS = ["email", "password", "client_id", "refresh_token", "recovery_email", "recovery_password", "note"]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补字段，不破坏已有数据。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    if "imap_host" not in cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN imap_host TEXT DEFAULT ''")


def _run(sql: str, args: tuple = (), fetch: bool = False):
    conn = connect()
    try:
        cur = conn.execute(sql, args)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows
    finally:
        conn.close()


MERGE_FIELDS = ["password", "client_id", "refresh_token", "recovery_email", "recovery_password"]


def upsert_accounts(items: list[dict], overwrite: bool = False) -> dict:
    """按 email 合并。

    默认**只补空**：已存在的非空字段不会被导入文件覆盖——尤其是 refresh_token，
    导入一份旧文件会把已轮换的新令牌冲掉，账号直接报废。

    overwrite=True 才按导入内容强制覆盖（旧的令牌值仍会存进 token_history）。
    """
    stats = {"added": 0, "filled": 0, "overwritten": 0, "kept": 0}
    conn = connect()
    try:
        for it in items:
            email = (it.get("email") or "").strip()
            if not email:
                continue
            row = conn.execute(
                "SELECT * FROM accounts WHERE LOWER(email) = LOWER(?)", (email,)
            ).fetchone()

            if not row:
                conn.execute(
                    """INSERT INTO accounts (email, password, client_id, refresh_token,
                       recovery_email, recovery_password) VALUES (?,?,?,?,?,?)""",
                    (
                        email,
                        it.get("password", ""),
                        it.get("client_id", ""),
                        it.get("refresh_token", ""),
                        it.get("recovery_email", ""),
                        it.get("recovery_password", ""),
                    ),
                )
                stats["added"] += 1
                continue

            changes, kept = {}, 0
            for field in MERGE_FIELDS:
                incoming = (it.get(field) or "").strip()
                current = (row[field] or "").strip()
                if not incoming:
                    continue
                if not current:
                    changes[field] = incoming          # 补空，永远安全
                elif incoming != current:
                    if overwrite:
                        changes[field] = incoming
                        if field == "refresh_token":
                            record_history(conn, row["id"], current, "import-overwrite")
                    else:
                        kept += 1

            if changes:
                if changes.get("refresh_token"):
                    changes["token_updated_at"] = now_text()
                sets = ", ".join(f"{k}=?" for k in changes)
                conn.execute(f"UPDATE accounts SET {sets} WHERE id=?", (*changes.values(), row["id"]))
                stats["filled" if not overwrite else "overwritten"] += 1
            if kept:
                stats["kept"] += 1

        conn.commit()
    finally:
        conn.close()
    return stats


def list_accounts(keyword: str = "") -> list[sqlite3.Row]:
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        sql = """SELECT * FROM accounts WHERE email LIKE ? OR note LIKE ?
                 ORDER BY id"""
        return _run(sql, (like, like), fetch=True) or []
    return _run("SELECT * FROM accounts ORDER BY id", fetch=True) or []


def get_account(acc_id: int):
    rows = _run("SELECT * FROM accounts WHERE id = ?", (acc_id,), fetch=True)
    return rows[0] if rows else None


def record_history(conn: sqlite3.Connection, account_id: int, token: str, source: str) -> None:
    """记下被替换掉的旧令牌，万一覆盖错了还能找回来。

    每个账号只保留最近 20 条——每次取件兑换都会记一笔，不设上限会无限增长。
    """
    if not token:
        return
    conn.execute(
        "INSERT INTO token_history (account_id, refresh_token, source, changed_at) VALUES (?,?,?,?)",
        (account_id, token, source, now_text()),
    )
    conn.execute(
        """DELETE FROM token_history
           WHERE account_id = ?
             AND id NOT IN (SELECT id FROM token_history
                            WHERE account_id = ? ORDER BY id DESC LIMIT 20)""",
        (account_id, account_id),
    )


def history(email: str) -> list[sqlite3.Row]:
    """查某个邮箱的令牌历史。不区分大小写，也允许只输入一部分。"""
    needle = (email or "").strip().replace("%", "").replace("_", "")
    if not needle:
        return []
    rows = _run(
        """SELECT h.changed_at, h.source, h.refresh_token, a.email
           FROM token_history h JOIN accounts a ON a.id = h.account_id
           WHERE LOWER(a.email) = LOWER(?)
           ORDER BY h.id DESC""",
        (needle,),
        fetch=True,
    )
    if not rows:  # 全等没命中，退化成模糊匹配
        rows = _run(
            """SELECT h.changed_at, h.source, h.refresh_token, a.email
               FROM token_history h JOIN accounts a ON a.id = h.account_id
               WHERE LOWER(a.email) LIKE LOWER(?)
               ORDER BY h.id DESC""",
            (f"%{needle}%",),
            fetch=True,
        )
    return rows or []


def update_token(acc_id: int, refresh_token: str, access_token: str, expires_at: float, source: str = "fetch") -> None:
    """兑换成功后立刻落库——这是断链风险最高的一步，失败必须让调用方知道。

    source: fetch（主界面取件）/ sync（同步窗口）/ import-overwrite（导入覆盖）
    """
    conn = connect()
    try:
        old = conn.execute("SELECT refresh_token FROM accounts WHERE id=?", (acc_id,)).fetchone()
        if old and (old["refresh_token"] or "") != refresh_token:
            record_history(conn, acc_id, old["refresh_token"], source)
        conn.execute(
            """UPDATE accounts SET refresh_token=?, access_token=?, access_expires_at=?,
               token_updated_at=? WHERE id=?""",
            (refresh_token, access_token, expires_at, now_text(), acc_id),
        )
        conn.commit()
    finally:
        conn.close()


EXPIRY_DAYS = 90


def expiry_stats() -> tuple[int | None, str, int]:
    """返回 (最快剩余天数, 那个账号的邮箱, 无记录账号数)。

    微软的 refresh token 是 90 天滑动窗口，每兑换一次重新计时，
    所以剩余天数 = 90 - 距上次更新的天数。
    """
    conn = connect()
    try:
        row = conn.execute(
            """SELECT email,
                      CAST(julianday('now','localtime') - julianday(token_updated_at) AS INTEGER) AS days
               FROM accounts
               WHERE token_updated_at IS NOT NULL AND token_updated_at != ''
               ORDER BY days DESC LIMIT 1"""
        ).fetchone()
        unknown = conn.execute(
            "SELECT COUNT(*) AS c FROM accounts WHERE token_updated_at IS NULL OR token_updated_at = ''"
        ).fetchone()["c"]
    finally:
        conn.close()

    if not row:
        return None, "", int(unknown)
    return EXPIRY_DAYS - int(row["days"]), row["email"], int(unknown)


def update_status(acc_id: int, status: str, error: str = "", fetched: bool = False) -> None:
    if fetched:
        _run(
            "UPDATE accounts SET status=?, last_error=?, last_fetch_at=? WHERE id=?",
            (status, error, now_text(), acc_id),
        )
    else:
        _run("UPDATE accounts SET status=?, last_error=? WHERE id=?", (status, error, acc_id))


def update_note(acc_id: int, note: str) -> None:
    _run("UPDATE accounts SET note=? WHERE id=?", (note, acc_id))


def update_imap_host(acc_id: int, host: str) -> None:
    """记住这个号上次连上的主机，下次优先用它。"""
    _run("UPDATE accounts SET imap_host=? WHERE id=?", (host, acc_id))


def count() -> int:
    rows = _run("SELECT COUNT(*) AS c FROM accounts", fetch=True)
    return int(rows[0]["c"]) if rows else 0
