# -*- coding: utf-8 -*-
"""取件逻辑：兑换令牌 + IMAP 读信 + MIME 解析。

不含任何界面代码，GUI 直接调用 fetch_latest()。
"""

import email
import html as html_lib
import imaplib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

HOST = "outlook.office365.com"
PORT = 993
TIMEOUT = 30
# 主用失败才走备选；顺序即优先级
HOSTS = ["outlook.office365.com", "outlook.live.com"]
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


class MailError(Exception):
    """带人话原因的失败。"""


class AuthFailed(MailError):
    """服务器拒绝了 access token。调用方可以强刷令牌后重试一次。"""


# --------------------------------------------------------------------------- #
# 令牌
# --------------------------------------------------------------------------- #
def exchange_token(client_id: str, refresh_token: str) -> dict:
    """用 refresh_token 换 access_token。返回的 refresh_token 可能已轮换，调用方必须落库。"""
    if not client_id:
        raise MailError("缺少 client_id，无法兑换令牌")

    data = urllib.parse.urlencode(
        {"client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            raise MailError(f"兑换失败：HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise MailError(f"网络不可达：{e.reason}") from None

    if body.get("error"):
        raise MailError(_explain_token_error(body["error"], body.get("error_description", "")))

    if not body.get("access_token"):
        raise MailError("兑换失败：响应里没有 access_token")
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token") or refresh_token,
        "expires_in": int(body.get("expires_in") or 3600),
    }


def _explain_token_error(code: str, desc: str) -> str:
    table = {
        "invalid_grant": "令牌已失效或 client_id 不匹配",
        "invalid_client": "client_id 不对",
        "consent_required": "该令牌没有邮件权限，需重新网页授权",
        "interaction_required": "需要重新登录授权",
    }
    reason = table.get(code, code)
    return f"{reason}｜{desc[:160]}" if desc else reason


# --------------------------------------------------------------------------- #
# 连接
# --------------------------------------------------------------------------- #
def _connect(email_addr: str, access_token: str, hosts=None) -> tuple[imaplib.IMAP4_SSL, str]:
    """依次尝试主机，返回 (连接, 实际用上的主机)。默认先 office365，失败再走 live。"""
    ctx = ssl.create_default_context()
    auth = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
    last_err = ""

    for host in hosts or HOSTS:
        try:
            imap = imaplib.IMAP4_SSL(host, PORT, ssl_context=ctx, timeout=TIMEOUT)
        except ssl.SSLError as e:
            last_err = f"{host} TLS 握手失败：{e}"
            continue
        except OSError as e:
            last_err = f"连不上 {host}:{PORT}：{e}"
            continue

        try:
            imap.authenticate("XOAUTH2", lambda _c: auth.encode())
            return imap, host
        except imaplib.IMAP4.error as e:
            try:
                imap.shutdown()
            except Exception:
                pass
            # 认证被拒是账号问题，换主机也没用，直接抛
            raise AuthFailed(_explain_imap_error(str(e))) from None
        except OSError as e:
            last_err = f"{host} 认证超时：{e}"
            continue

    raise MailError(last_err or "所有 IMAP 主机都连不上")


def _explain_imap_error(raw: str) -> str:
    low = raw.lower()
    if "authenticated but not connected" in low:
        return "认证通过但邮箱未开通 IMAP"
    if "authenticationfailed" in low or "authenticate failed" in low:
        return "令牌被服务器拒绝（可能已过期）"
    if "too many" in low:
        return "请求过于频繁，被限流"
    return f"IMAP 认证失败：{raw[:120]}"


def list_folders(imap: imaplib.IMAP4_SSL) -> list[str]:
    """兼容两种 LIST 返回：(...) "/" INBOX 和 (...) "/" "Sent Items"。"""
    names: list[str] = []
    for item in imap.list()[1] or []:
        if not isinstance(item, bytes):
            continue
        line = item.decode("utf-8", "replace").strip()
        m = re.match(r"^\([^)]*\)\s+(?:\"[^\"]*\"|NIL)\s+(?P<n>.+)$", line)
        name = m.group("n").strip() if m else (line.split()[-1] if line.split() else "")
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        if name and name not in names:
            names.append(name)
    return names


def pick_folder(available: list[str], want: str) -> str | None:
    """INBOX 匹配 Inbox，Junk Email 匹配 Junk。"""
    norm = lambda s: re.sub(r"[\s_\-]+", "", s).lower()
    if want in available:
        return want
    for a in available:
        if norm(a) == norm(want):
            return a
    for a in available:
        if norm(want) in norm(a) or norm(a) in norm(want):
            return a
    return None


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style|head)\b[^>]*>.*?</\1\s*>", " ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def parse_message(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    plain, html_parts = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, "replace")
        except LookupError:
            content = payload.decode("utf-8", "replace")
        (plain if ctype == "text/plain" else html_parts).append(content)

    raw_html = "\n".join(html_parts)
    body = "\n".join(plain) if plain else html_to_text(raw_html)

    ts = 0.0
    when = msg.get("Date")
    try:
        dt = parsedate_to_datetime(when) if when else None
        ts = dt.timestamp() if dt else 0.0
        date_text = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
    except Exception:
        date_text = when or ""

    return {
        "subject": str(make_header(decode_header(msg.get("Subject") or ""))),
        "from": str(make_header(decode_header(msg.get("From") or ""))),
        "to": str(make_header(decode_header(msg.get("To") or ""))),
        "date": date_text,
        "ts": ts,
        "text": body.strip(),
        "html": raw_html,
    }


# --------------------------------------------------------------------------- #
# 取件
# --------------------------------------------------------------------------- #
def fetch_latest(
    email_addr: str,
    access_token: str,
    limit: int = 5,
    folders=("INBOX", "Junk Email"),
    preferred_host: str = "",
) -> tuple[list[dict], str]:
    """取最近 limit 封，跨文件夹按时间倒序合并。

    返回 (邮件列表, 实际连上的主机)。preferred_host 传上次成功的主机，优先尝试。
    """
    order = list(HOSTS)
    if preferred_host and preferred_host in order:
        order.remove(preferred_host)
        order.insert(0, preferred_host)

    imap, host = _connect(email_addr, access_token, order)
    results: list[dict] = []
    try:
        available = list_folders(imap)
        for want in folders:
            name = pick_folder(available, want)
            if not name:
                continue
            try:
                typ, _ = imap.select(f'"{name}"', readonly=True)
            except imaplib.IMAP4.error:
                continue
            if typ != "OK":
                continue
            typ, data = imap.uid("search", None, "ALL")
            if typ != "OK" or not data or not data[0]:
                continue
            uids = sorted(data[0].split(), key=int, reverse=True)[:limit]
            for uid in uids:
                try:
                    typ, msg_data = imap.uid("fetch", uid, "(RFC822)")
                except imaplib.IMAP4.error:
                    continue
                if typ != "OK" or not msg_data or msg_data[0] is None:
                    continue
                item = parse_message(msg_data[0][1])
                item["folder"] = name
                item["uid"] = uid.decode()
                results.append(item)
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    results.sort(key=lambda r: r["ts"], reverse=True)
    return results[:limit], host


def mask(value: str) -> str:
    if not value:
        return "(空)"
    return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else value
