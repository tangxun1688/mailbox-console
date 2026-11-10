# -*- coding: utf-8 -*-
"""导入文件的解析：嗅探分隔符、猜字段、按映射生成账号。纯函数，方便单独测试。"""

import re
from pathlib import Path

SEPARATORS = ["----", "\t", "|", ";", ",", ":"]

FIELD_OPTIONS = [
    ("", "忽略"),
    ("email", "邮箱"),
    ("password", "密码"),
    ("client_id", "Client ID"),
    ("refresh_token", "令牌"),
    ("recovery_email", "辅助邮箱"),
    ("recovery_password", "辅助密码"),
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


def read_text(path: str) -> str:
    """按常见编码依次尝试读取文件内容。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_text(text: str) -> list[str]:
    """切成数据行：去空白、跳过空行和 # 注释。"""
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def read_lines(path: str) -> list[str]:
    return parse_text(read_text(path))


def detect_separator(lines: list[str]) -> str:
    """选一个能把前若干行切出一致列数的分隔符，优先 ---- 这种更具体的。"""
    sample = lines[:20]
    for sep in SEPARATORS:
        counts = [len(l.split(sep)) for l in sample]
        if counts and min(counts) >= 2 and len(set(counts)) == 1:
            return sep
    return "----"


def split_lines(lines: list[str], sep: str) -> list[list[str]]:
    return [[c.strip() for c in l.split(sep)] for l in lines]


def guess_mapping(rows: list[list[str]]) -> list[str]:
    """按内容猜每一列是什么字段。

    判据顺序：GUID -> client_id；超长串（>200）或 M.C 开头 -> 令牌；
    含 @ -> 邮箱（第一个登录邮箱、第二个辅助邮箱）；剩下的按顺序给密码 / 辅助密码。
    """
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    mapping = [""] * ncols
    email_seen = 0

    for i in range(ncols):
        vals = [r[i].strip() for r in rows if i < len(r) and r[i].strip()]
        if not vals:
            continue
        sample = vals[0]
        if GUID_RE.match(sample):
            mapping[i] = "client_id"
        elif len(sample) > 200 or (sample.startswith("M.C") and len(sample) > 50):
            mapping[i] = "refresh_token"
        elif EMAIL_RE.match(sample):
            mapping[i] = "email" if email_seen == 0 else "recovery_email"
            email_seen += 1

    # 密码类不靠内容判断，按剩余列的先后顺序分配
    for slot in ("password", "recovery_password"):
        for i in range(ncols):
            if not mapping[i] and any(i < len(r) and r[i].strip() for r in rows):
                mapping[i] = slot
                break
    return mapping


REQUIRED_FIELDS = ("email", "password", "client_id", "refresh_token")


def build_accounts(rows: list[list[str]], mapping: list[str]) -> tuple[list[dict], dict]:
    """按映射组装账号。

    邮箱 / 密码 / Client ID / 令牌 四项必填，缺一个就跳过该行；
    辅助邮箱、辅助密码可以空着。
    返回 (账号列表, 统计)。
    """
    accounts: list[dict] = []
    stats = {"no_email": 0, "incomplete": 0, "ok": 0}

    for row in rows:
        item: dict[str, str] = {}
        for i, field in enumerate(mapping):
            if field and i < len(row):
                item[field] = row[i].strip()

        if not item.get("email"):
            stats["no_email"] += 1
            continue

        missing = [f for f in REQUIRED_FIELDS if not item.get(f)]
        if missing:
            stats["incomplete"] += 1
            continue

        accounts.append(item)
        stats["ok"] += 1

    return accounts, stats


def preview_lines(rows: list[list[str]], mapping: list[str], n: int = 3) -> list[str]:
    out = []
    for row in rows[:n]:
        parts = []
        for i, field in enumerate(mapping):
            if field and i < len(row):
                value = row[i]
                if field == "refresh_token" and len(value) > 24:
                    value = value[:10] + "…" + value[-4:]
                parts.append(value)
        out.append(" | ".join(parts))
    return out
