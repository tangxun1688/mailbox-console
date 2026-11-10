# -*- coding: utf-8 -*-
"""快速查看 data.db 里的账号。

用法：
    python view_db.py                 # 概览
    python view_db.py -q Amina        # 只看包含 Amina 的
    python view_db.py --full          # 显示全部字段
    python view_db.py --csv out.csv   # 导出成 CSV（Excel 能直接打开）
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).with_name("data.db")

BRIEF = [
    ("id", "ID", 5),
    ("email", "邮箱", 34),
    ("status", "状态", 8),
    ("token_updated_at", "令牌更新", 19),
    ("refresh_token", "令牌", 16),
    ("note", "备注", 12),
]

FULL = [
    ("id", "ID", 5),
    ("email", "邮箱", 34),
    ("password", "密码", 16),
    ("client_id", "Client ID", 38),
    ("refresh_token", "令牌", 16),
    ("recovery_email", "辅助邮箱", 28),
    ("recovery_password", "辅助密码", 14),
    ("status", "状态", 8),
    ("last_error", "最近错误", 24),
    ("last_fetch_at", "取件时间", 19),
    ("token_updated_at", "令牌更新", 19),
    ("note", "备注", 12),
]


def main():
    parser = argparse.ArgumentParser(description="查看 data.db")
    parser.add_argument("-q", "--keyword", default="", help="按邮箱或备注过滤")
    parser.add_argument("--full", action="store_true", help="显示全部字段")
    parser.add_argument("--csv", default="", help="导出到 CSV 文件")
    parser.add_argument("--history", default="", metavar="邮箱", help="查看某个邮箱的令牌变更历史")
    args = parser.parse_args()

    if not DB.exists():
        sys.exit(f"找不到 {DB}，先运行一次 app.py")

    if args.history:
        import store

        store.init_db()   # 老库可能还没有历史表，建一下再查
        rows = store.history(args.history)
        title = rows[0]["email"] if rows else args.history
        print(f"\n{title}　共 {len(rows)} 条令牌变更（新的在上）\n")
        for r in rows:
            token = r["refresh_token"] or ""
            if not args.full:
                token = (token[:10] + "…" + token[-4:]) if len(token) > 14 else token
            print(f"{r['changed_at']} | {r['source']:<16} | {token}")
        if not rows:
            print("（没有记录。只有兑换过或覆盖过令牌的账号才有历史）")
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if args.keyword:
        like = f"%{args.keyword}%"
        rows = conn.execute(
            "SELECT * FROM accounts WHERE email LIKE ? OR note LIKE ? ORDER BY id", (like, like)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()

    if args.csv:
        if not rows:
            sys.exit("没有数据可导出")
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(rows[0].keys())
            for r in rows:
                writer.writerow([r[k] for k in r.keys()])
        print(f"已导出 {len(rows)} 条到 {args.csv}")
        return

    cols = FULL if args.full else BRIEF
    print(f"\n{DB}　共 {len(rows)} 条\n")

    for r in rows:
        parts = []
        for key, title, _size in cols:
            value = r[key]
            if key == "refresh_token" and value:
                value = value[:10] + "…" + value[-4:]
            elif value in (None, ""):
                value = "—"
            parts.append(f"{title}={value}")
        print(" | ".join(parts))

    print("\n完整令牌用 --full 查看；导出成表格用 --csv out.csv")


if __name__ == "__main__":
    main()
