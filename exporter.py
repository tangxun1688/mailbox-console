# -*- coding: utf-8 -*-
"""导出：选列 + 分隔符拼行 + 冲突检查。纯函数，方便单独测试。"""

import re

EXPORT_COLUMNS = [
    ("email", "邮箱"),
    ("password", "密码"),
    ("client_id", "Client ID"),
    ("refresh_token", "令牌"),
    ("recovery_email", "辅助邮箱"),
    ("recovery_password", "辅助密码"),
    ("note", "备注"),
]

DELIMITERS = ["----", ":"]


def value_of(row, column: str) -> str:
    """兼容 sqlite3.Row 和 dict。"""
    try:
        v = row[column]
    except (IndexError, KeyError):
        return ""
    return "" if v is None else str(v)


def build_lines(rows, columns: list[str], delimiter: str) -> list[str]:
    return [delimiter.join(value_of(r, c) for c in columns) for r in rows]


def find_conflicts(rows, columns: list[str], delimiter: str, limit: int = 5) -> list[str]:
    """找出字段值本身含分隔符的行——这种行导出去会被下游解析错。"""
    problems = []
    for idx, row in enumerate(rows, 1):
        for c in columns:
            v = value_of(row, c)
            if delimiter in v:
                problems.append(f"第 {idx} 行「{c}」含分隔符 {delimiter!r}")
                break
        if len(problems) >= limit:
            problems.append("…")
            break
    return problems


def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", text)
