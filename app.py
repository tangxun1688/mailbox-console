# -*- coding: utf-8 -*-
"""邮箱管理工具 —— 主窗口。

运行： python app.py
"""

import os
import queue
import re
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from tkinter import messagebox, ttk

import mail
import paths
import store
from export_dialog import ExportDialog
from import_dialog import ImportDialog
from sync_dialog import SyncDialog

APP_TITLE = "邮箱管理工具"
FONT = ("Microsoft YaHei UI", 9)
HINT_COPY = "双击邮箱 / 密码 / 辅助邮箱 / 辅助密码 可复制"

# 账号表列序号（1 开始），改列顺序只改这里
COL_CHK, COL_IDX, COL_EMAIL, COL_PWD = "#1", "#2", "#3", "#4"
COL_REC, COL_RECPWD, COL_STATUS, COL_TOKEN, COL_NOTE = "#5", "#6", "#7", "#8", "#9"


def log_crash(title: str, exc_type, exc, tb) -> str:
    """把崩溃写进 exe 旁边的 error.log。

    打包时用 --noconsole，stderr 无处可去；没有这个文件，
    exe 闪退时用户只能看到"什么都没发生"。
    """
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        path = paths.log_path()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} {title} =====\n{text}")
        return str(path)
    except OSError:
        return ""


def _install_excepthook() -> None:
    """启动阶段的异常（建库失败、Tcl 初始化失败…）也要看得见。"""

    def hook(exc_type, exc, tb):
        path = log_crash("启动/未捕获异常", exc_type, exc, tb)
        try:
            messagebox.showerror(
                APP_TITLE,
                f"程序出错：{exc}\n\n" + (f"详情已写入：\n{path}" if path else "日志写入失败"),
            )
        except Exception:
            pass

    sys.excepthook = hook


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1120x760")
        self.minsize(960, 620)
        self._set_icon()

        store.init_db()
        self.queue: queue.Queue = queue.Queue()
        self.accounts: list = []
        self.mail_items: list[dict] = []
        self.current_acc = None
        self.busy = False
        self._flash_job = None
        self._mail_spans: list[tuple[str, str]] = []
        self._current_mail = -1
        self._toast_win = None
        self._toast_job = None
        self.checked: set[int] = set()
        self.mail_cache: dict[int, list[dict]] = {}
        self.mail_cache_time: dict[int, str] = {}
        self._anchor_id: int | None = None
        self._shown_acc_id: int | None = None

        self._setup_style()
        self._build()
        self.reload_accounts()
        self.after(100, self._poll_queue)
        self.after(800, self._warn_expiring)

    # ------------------------------------------------------------------ #
    def _set_icon(self):
        """窗口/任务栏图标。源码目录和打包后的临时解包目录都找一遍。"""
        for folder in (paths.app_dir(), paths.resource_dir()):
            ico = folder / "app.ico"
            if ico.exists():
                try:
                    self.iconbitmap(default=str(ico))
                    return
                except tk.TclError:
                    pass

    def report_callback_exception(self, exc, val, tb):
        """Tk 回调里的异常默认只打到 stderr，noconsole 打包后等于静默吞掉。"""
        path = log_crash("界面回调异常", exc, val, tb)
        detail = f"\n\n日志：{path}" if path else ""
        try:
            messagebox.showerror(APP_TITLE, f"操作出错：{val}{detail}", parent=self)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure(".", font=FONT)
        style.configure("Treeview", font=FONT, rowheight=24)
        style.configure("Treeview.Heading", font=FONT)
        self.option_add("*Font", FONT)

    def _build(self):
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")

        # 状态栏先占住底部，否则会被下面的 expand 控件挤掉
        self.status_var = tk.StringVar(value=HINT_COPY)
        ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 4)).pack(
            side="bottom", fill="x"
        )

        ttk.Button(toolbar, text="导入", command=self.open_import).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, text="取件").pack(side="left")
        self.limit_var = tk.StringVar(value="1")
        ttk.Combobox(
            toolbar, textvariable=self.limit_var, values=["1", "3", "5", "10"],
            width=4, state="readonly",
        ).pack(side="left", padx=(4, 6))
        ttk.Label(toolbar, text="封").pack(side="left")

        self.fetch_btn = ttk.Button(toolbar, text="获取邮件", command=self.fetch_mail, state="disabled")
        self.fetch_btn.pack(side="left", padx=(10, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.export_btn = ttk.Button(toolbar, text="导出…", command=self.open_export)
        self.export_btn.pack(side="left")
        ttk.Button(toolbar, text="同步令牌", command=self.open_sync).pack(side="left", padx=(8, 0))
        self.expiry_label = ttk.Label(toolbar, text="", foreground="#666")
        self.expiry_label.pack(side="left", padx=(10, 0))

        ttk.Label(toolbar, text="搜索").pack(side="right", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._debounce_search())
        ttk.Entry(toolbar, textvariable=self.search_var, width=24).pack(side="right")
        self._search_job = None

        # 账号表
        self.acc_frame = ttk.LabelFrame(self, text="账号", padding=(6, 4))
        self.acc_frame.pack(fill="both", expand=False, padx=10, pady=(4, 0))

        cols = ("chk", "idx", "email", "password", "recovery_email", "recovery_password", "status", "token_at", "note")
        self.tree = ttk.Treeview(self.acc_frame, columns=cols, show="headings", height=10)
        for key, title, width, anchor in (
            ("chk", "选", 34, "center"),
            ("idx", "#", 44, "center"),
            ("email", "邮箱", 230, "w"),
            ("password", "密码", 110, "w"),
            ("recovery_email", "辅助邮箱", 185, "w"),
            ("recovery_password", "辅助密码", 110, "w"),
            ("status", "状态", 76, "center"),
            ("token_at", "令牌更新", 130, "center"),
            ("note", "备注", 100, "w"),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor)

        # 用 grid 而不是 pack：pack 下 expand 的控件会把滚动条挤成 1px
        self.acc_frame.columnconfigure(0, weight=1)
        self.acc_frame.rowconfigure(1, weight=1)

        bar = ttk.Frame(self.acc_frame)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.check_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="全选", variable=self.check_all_var, command=self.toggle_all).pack(side="left")

        self.checked_label = ttk.Label(bar, text="已选 0 个", foreground="#666")
        self.checked_label.pack(side="left", padx=(10, 12))

        self.batch_btn = ttk.Button(bar, text="批量取件", command=self.batch_fetch)
        self.batch_btn.pack(side="left")
        ttk.Label(bar, text="并发").pack(side="left", padx=(12, 4))
        self.conc_var = tk.StringVar(value="3")
        ttk.Combobox(
            bar, textvariable=self.conc_var, values=["1", "2", "3", "4", "5", "6", "8"],
            width=3, state="readonly",
        ).pack(side="left")
        ttk.Label(bar, text="个账号同时跑", foreground="#888").pack(side="left", padx=(4, 0))

        self.tree.grid(row=1, column=0, sticky="nsew")

        sb = ttk.Scrollbar(self.acc_frame, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_account)
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("bad", foreground="#b03030")
        self.tree.tag_configure("warn", foreground="#b8860b")      # 令牌 60~80 天没动
        self.tree.tag_configure("expired", foreground="#c62828")   # 超过 80 天，快到期了

        # 邮件区：左列表 + 右正文，两行 grid，保证左右上下都对齐
        mail_frame = ttk.Frame(self)
        mail_frame.pack(fill="both", expand=True, padx=10, pady=(8, 6))
        mail_frame.columnconfigure(0, weight=0)
        mail_frame.columnconfigure(1, weight=1)
        mail_frame.rowconfigure(1, weight=1)

        self.mail_title = ttk.Label(mail_frame, text="邮件", foreground="#666")
        self.mail_title.grid(row=0, column=0, sticky="w", pady=(0, 4))

        # 正文上方那条：完整时间 + 查看原文。
        # 当前邮箱不在这里重复——上面账号表选中哪个就是从哪个号取的
        self.topbar = ttk.Frame(mail_frame)
        self.topbar.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=(0, 4))

        self.detail_time = ttk.Label(self.topbar, text="", foreground="#999")
        self.detail_time.pack(side="left")
        ttk.Button(self.topbar, text="查看原文", command=self.open_raw).pack(side="right")

        list_wrap = ttk.Frame(mail_frame)
        list_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)

        self.mail_list = tk.Text(
            list_wrap, width=46, wrap="none", cursor="hand2", padx=10, pady=4,
            font=("Microsoft YaHei UI", 9), background="#ffffff",
            borderwidth=0, highlightthickness=1, highlightbackground="#c9c9c9",
            highlightcolor="#c9c9c9",
        )
        self.mail_list.grid(row=0, column=0, sticky="nsew")
        msb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.mail_list.yview)
        msb.grid(row=0, column=1, sticky="ns")
        self.mail_list.configure(yscrollcommand=msb.set)
        self.mail_list.tag_configure("subject", font=("Microsoft YaHei UI", 10, "bold"), spacing1=7)
        self.mail_list.tag_configure("meta", foreground="#7a7a7a", spacing3=7)
        # 自定义 tag（不能叫 sel：那是 Text 内置选中标签，失焦时不上色）
        self.mail_list.tag_configure("hl", background="#cfe4fb")
        self.mail_list.bind("<Button-1>", self._on_mail_click)
        self.mail_list.configure(state="disabled")

        body_wrap = ttk.Frame(mail_frame)
        body_wrap.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        body_wrap.columnconfigure(0, weight=1)
        body_wrap.rowconfigure(0, weight=1)
        self.body = tk.Text(
            body_wrap, height=8, wrap="word", font=("Microsoft YaHei UI", 10), padx=16, pady=12,
            spacing1=2, spacing3=5, background="#ffffff",
            borderwidth=0, highlightthickness=1, highlightbackground="#c9c9c9",
            highlightcolor="#c9c9c9",
        )
        self.body.grid(row=0, column=0, sticky="nsew")
        bsb = ttk.Scrollbar(body_wrap, orient="vertical", command=self.body.yview)
        bsb.grid(row=0, column=1, sticky="ns")
        self.body.configure(yscrollcommand=bsb.set, state="disabled")

        # 列表和正文都支持滚轮
        for widget in (self.tree, self.mail_list, self.body):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", self._on_wheel_linux)
            widget.bind("<Button-5>", self._on_wheel_linux)

        # Windows 下滚轮事件发给“有焦点的控件”，不是光标下的控件。
        # 兜一层全局处理：按光标位置找目标，保证停在哪个区域就滚哪个。
        self.bind_all("<MouseWheel>", self._on_wheel_global)

        self._show_placeholder()

    # ------------------------------------------------------------------ #
    # 账号表
    # ------------------------------------------------------------------ #
    def _debounce_search(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, self.reload_accounts)

    @staticmethod
    def _token_days(text: str) -> int | None:
        """令牌距离上次更新多少天；没记录或格式不对返回 None。"""
        if not text or text == "—":
            return None
        try:
            return (datetime.now() - datetime.strptime(text, "%Y-%m-%d %H:%M:%S")).days
        except ValueError:
            return None

    def _update_expiry_label(self):
        best, email, unknown = store.expiry_stats()
        if best is None:
            text = f"{unknown} 个号无同步记录" if unknown else ""
            color = "#666"
        elif best < 0:
            text = "令牌已过期"
            color = "#8e0000"
        else:
            text = f"最近到期 {best} 天"
            color = "#c62828" if best < 15 else ("#b8860b" if best <= 30 else "#666")
        if best is not None and unknown:
            text += f"　·　{unknown} 个无记录"
        self.expiry_label.config(text=text, foreground=color)

    def _warn_expiring(self):
        best, email, unknown = store.expiry_stats()
        if best is None or best > 30:
            return
        word = "令牌已过期" if best < 0 else f"令牌最快 {best} 天后到期"
        self._flash(f"{word}（{email}），建议点「同步令牌」处理", 8000)

    def reload_accounts(self):
        keyword = self.search_var.get().strip()
        self.accounts = store.list_accounts(keyword)
        total = store.count()
        self.acc_frame.config(
            text=f"账号　共 {len(self.accounts)} 个（已筛选，总计 {total}）"
            if keyword
            else f"账号　共 {total} 个"
        )
        selected = self.current_acc["id"] if self.current_acc else None

        self.tree.delete(*self.tree.get_children())
        for i, acc in enumerate(self.accounts, 1):
            status = acc["status"] or "未取件"
            tag = ""
            if status == "成功":
                tag = "ok"
            elif status and status != "未取件":
                tag = "bad"

            days = self._token_days(acc["token_updated_at"])
            if tag != "bad":
                if days is not None and days >= 80:
                    tag = "expired"
                elif days is not None and days >= 60:
                    tag = "warn"
            self.tree.insert(
                "", "end", iid=str(acc["id"]),
                values=(
                    "☑" if acc["id"] in self.checked else "☐",
                    i,
                    acc["email"],
                    acc["password"],
                    acc["recovery_email"],
                    acc["recovery_password"],
                    status,
                    acc["token_updated_at"] or "—",
                    acc["note"],
                ),
                tags=(tag,) if tag else (),
            )
        self._update_checked_label()
        self._update_expiry_label()
        self.status_var.set(HINT_COPY)

        if selected and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
        elif self.accounts:
            first = str(self.accounts[0]["id"])
            self.tree.selection_set(first)

    def _on_select_account(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            self.current_acc = None
            self.fetch_btn.config(state="disabled")
            return
        self.current_acc = store.get_account(int(sel[0]))
        if self.current_acc:
            self._show_cached(self.current_acc["id"])
        self.fetch_btn.config(state="normal" if not self.busy else "disabled")

    def _show_cached(self, acc_id: int):
        """切到某个账号时，如果这次会话里取过件就直接显示，不用重连。"""
        items = self.mail_cache.get(acc_id)
        if items:
            if acc_id == self._shown_acc_id and self.mail_items:
                return          # 已经是这个号的内容，不用重画
            self._fill_mail_list(
                items, cached=True, acc_id=acc_id,
                cached_note=self.mail_cache_time.get(acc_id, ""),
            )
        else:
            self.mail_items = []
            self._show_placeholder()

    COPY_COLUMNS = {
        COL_EMAIL: ("email", "邮箱"),
        COL_PWD: ("password", "密码"),
        COL_REC: ("recovery_email", "辅助邮箱"),
        COL_RECPWD: ("recovery_password", "辅助密码"),
    }

    def _on_tree_click(self, event):
        """点勾选列切换勾选；按住 Shift 点任意位置，从上次点到这次整段勾上。"""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        acc_id = int(iid)
        column = self.tree.identify_column(event.x)

        if event.state & 0x0001 and self._anchor_id is not None:      # Shift
            self._range_check(self._anchor_id, acc_id)
            return "break" if column == COL_CHK else None

        if column == COL_CHK:
            self._toggle_one(acc_id)
            self._anchor_id = acc_id
            return "break"

        self._anchor_id = acc_id

    def _range_check(self, start_id: int, end_id: int):
        ids = [int(x) for x in self.tree.get_children()]
        try:
            a, b = ids.index(start_id), ids.index(end_id)
        except ValueError:
            self._toggle_one(end_id)
            return
        for i in range(min(a, b), max(a, b) + 1):
            self.checked.add(ids[i])
        self._render_checks()

    def _toggle_one(self, acc_id: int):
        if acc_id in self.checked:
            self.checked.discard(acc_id)
        else:
            self.checked.add(acc_id)
        iid = str(acc_id)
        if self.tree.exists(iid):
            self.tree.set(iid, "chk", "☑" if acc_id in self.checked else "☐")
        self._update_checked_label()

    def _render_checks(self):
        for acc in self.accounts:
            iid = str(acc["id"])
            if self.tree.exists(iid):
                self.tree.set(iid, "chk", "☑" if acc["id"] in self.checked else "☐")
        self._update_checked_label()

    def toggle_all(self):
        if self.check_all_var.get():
            self.checked = {acc["id"] for acc in self.accounts}
        else:
            self.checked.clear()
        self._render_checks()

    def _update_checked_label(self):
        n = len(self.checked)
        if not n:
            self.checked_label.config(text="已选 0 个", foreground="#666")
            return
        minutes = n * 10 / max(1, int(self.conc_var.get())) / 60
        estimate = f"约 {minutes:.0f} 分钟" if minutes >= 1 else "不到 1 分钟"
        warn = "#b03030" if n > 200 else "#666"
        self.checked_label.config(text=f"已选 {n} 个 · {estimate}", foreground=warn)

    def _copy_cell(self, iid: str, column: str, x_root: int, y_root: int):
        field, label = self.COPY_COLUMNS[column]
        value = self.tree.set(iid, field)
        if not value:
            return
        self.clipboard_clear()
        self.clipboard_append(value)
        self._flash(f"已复制{label}：{value}")
        self._toast(f"✓ 已复制{label}", x_root, y_root)

    def _toast(self, text: str, x_root: int, y_root: int, ms: int = 900):
        """鼠标旁弹个小提示。同一时刻只留一个，连续复制不会叠一堆。"""
        self._close_toast()

        tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(
            tip, text=text, bg="#2f2f2f", fg="#ffffff", padx=10, pady=5,
            font=("Microsoft YaHei UI", 9),
        ).pack()
        tip.update_idletasks()
        tip.geometry(f"+{x_root + 16}+{y_root + 16}")

        self._toast_win = tip
        self._toast_job = self.after(ms, self._close_toast)

    def _close_toast(self):
        if self._toast_job:
            self.after_cancel(self._toast_job)
            self._toast_job = None
        if self._toast_win:
            try:
                self._toast_win.destroy()
            except Exception:
                pass
            self._toast_win = None

    def _flash(self, text: str, ms: int = 2500):
        self.status_var.set(text)
        if self._flash_job:
            self.after_cancel(self._flash_job)
        self._flash_job = self.after(ms, lambda: self.status_var.set(HINT_COPY))

    def _on_tree_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not iid or column == COL_CHK:
            return
        self.tree.selection_set(iid)

        if column == COL_NOTE:                    # 备注列，就地编辑
            self._edit_note(iid, column)
        elif column in self.COPY_COLUMNS:         # 邮箱/密码/辅助邮箱/辅助密码，双击复制
            self._copy_cell(iid, column, event.x_root, event.y_root)
        else:                                      # 其余列双击取件
            self.fetch_mail()

    def _edit_note(self, iid: str, column: str):
        bbox = self.tree.bbox(iid, column)
        if not bbox:
            return
        x, y, w, h = bbox
        current = self.tree.set(iid, "note")
        var = tk.StringVar(value="" if current in ("—", "None") else current)

        entry = ttk.Entry(self.tree, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, "end")

        state = {"done": False}

        def commit(_event=None):
            if state["done"]:
                return
            state["done"] = True
            store.update_note(int(iid), var.get().strip())
            entry.destroy()
            self.reload_accounts()

        def cancel(_event=None):
            state["done"] = True
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    # ------------------------------------------------------------------ #
    # 取件
    # ------------------------------------------------------------------ #
    def fetch_mail(self):
        if self.busy or not self.current_acc:
            return
        acc = self.current_acc
        limit = int(self.limit_var.get())

        self.busy = True
        self.fetch_btn.config(state="disabled")
        self.status_var.set(f"正在取件：{acc['email']} …")
        self.mail_items = []
        self._show_placeholder(f"正在取件：{acc['email']} …")

        threading.Thread(target=self._fetch_worker, args=(dict(acc), limit), daemon=True).start()

    def _match_mail(self, acc: dict, access: str, limit: int):
        """取一个账号的邮件，返回 (邮件列表, 主机)。令牌被拒时强刷一次。"""
        prefer = acc.get("imap_host") or ""
        try:
            return mail.fetch_latest(acc["email"], access, limit=limit, preferred_host=prefer)
        except mail.AuthFailed:
            access = self._ensure_access(acc, force=True)
            return mail.fetch_latest(acc["email"], access, limit=limit, preferred_host=prefer)

    def _fetch_worker(self, acc: dict, limit: int):
        try:
            access = self._ensure_access(acc)
            items, host = self._match_mail(acc, access, limit)
            if host != acc.get("imap_host"):
                store.update_imap_host(acc["id"], host)
            store.update_status(acc["id"], "成功", "", fetched=True)
            self.queue.put(("ok", acc, items))
        except mail.MailError as e:
            store.update_status(acc["id"], "失败", str(e), fetched=True)
            self.queue.put(("err", acc, str(e)))
        except Exception as e:  # 兜底，避免线程静默死掉
            store.update_status(acc["id"], "失败", f"{type(e).__name__}: {e}", fetched=True)
            self.queue.put(("err", acc, f"{type(e).__name__}: {e}"))

    # ------------------------------------------------------------------ #
    # 批量取件
    # ------------------------------------------------------------------ #
    def batch_fetch(self):
        if self.busy:
            return
        ids = [i for i in sorted(self.checked) if store.get_account(i)]
        if not ids:
            messagebox.showinfo("没有选中账号", "先在左侧勾选要取件的账号。", parent=self)
            return
        if len(ids) > 50 and not messagebox.askyesno(
            "确认批量取件",
            f"一次跑 {len(ids)} 个账号，按每个约 10 秒、并发 {self.conc_var.get()} 估算，"
            f"大概需要 {len(ids) * 10 / int(self.conc_var.get()) / 60:.0f} 分钟。\n\n继续吗？",
            parent=self,
        ):
            return

        limit = int(self.limit_var.get())
        workers = max(1, int(self.conc_var.get()))

        self.busy = True
        self.fetch_btn.config(state="disabled")
        self.batch_btn.config(state="disabled")
        self.status_var.set(f"批量取件 0/{len(ids)} …")
        threading.Thread(target=self._batch_worker, args=(ids, limit, workers), daemon=True).start()

    def _batch_worker(self, ids: list[int], limit: int, workers: int):
        total, done, failed = len(ids), 0, 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._batch_one, aid, limit): aid for aid in ids}
            for fut in as_completed(futures):
                if not fut.result():
                    failed += 1
                done += 1
                self.queue.put(("progress", None, (done, total, failed)))
        self.queue.put(("batch_done", None, (total, failed)))

    def _batch_one(self, acc_id: int, limit: int) -> bool:
        acc = store.get_account(acc_id)
        if not acc:
            return False
        acc = dict(acc)
        try:
            access = self._ensure_access(acc)
            items, host = self._match_mail(acc, access, limit)
            if host != acc.get("imap_host"):
                store.update_imap_host(acc_id, host)
            store.update_status(acc_id, "成功", "", fetched=True)
            self.mail_cache[acc_id] = items     # 供切回该账号时直接展示
            self.mail_cache_time[acc_id] = datetime.now().strftime("%H:%M")
            return True
        except mail.MailError as e:
            store.update_status(acc_id, "失败", str(e), fetched=True)
            return False
        except Exception as e:
            store.update_status(acc_id, "失败", f"{type(e).__name__}: {e}", fetched=True)
            return False

    def _ensure_access(self, acc: dict, force: bool = False) -> str:
        """access token 没过期就复用，过期（或被拒）才兑换一次。

        每次都从库里重读，避免用界面上的旧快照导致重复兑换。
        """
        row = store.get_account(acc["id"]) or acc
        now = time.time()

        if not force:
            cached = row["access_token"] or ""
            if cached and float(row["access_expires_at"] or 0) > now + 60:
                return cached

        result = mail.exchange_token(row["client_id"], row["refresh_token"])
        store.update_token(
            row["id"], result["refresh_token"], result["access_token"], now + result["expires_in"]
        )
        return result["access_token"]

    def _poll_queue(self):
        try:
            while True:
                kind, acc, payload = self.queue.get_nowait()

                if kind == "progress":
                    done, total, failed = payload
                    self.status_var.set(f"批量取件 {done}/{total}　失败 {failed}")
                    continue

                if kind == "batch_done":
                    total, failed = payload
                    self.busy = False
                    self.fetch_btn.config(state="normal" if self.current_acc else "disabled")
                    self.batch_btn.config(state="normal")
                    self.status_var.set(f"批量取件完成：成功 {total - failed} 个，失败 {failed} 个")
                    self.reload_accounts()
                    if self.current_acc:
                        self._show_cached(self.current_acc["id"])
                    continue

                self.busy = False
                self.fetch_btn.config(state="normal" if self.current_acc else "disabled")
                if kind == "ok":
                    self.mail_cache[acc["id"]] = payload
                    self.mail_cache_time[acc["id"]] = datetime.now().strftime("%H:%M")
                    self._fill_mail_list(payload, acc_id=acc["id"])
                    self.status_var.set(f"{acc['email']}：取到 {len(payload)} 封")
                else:
                    self.status_var.set(f"{acc['email']}：{payload}")
                    messagebox.showerror("取件失败", payload, parent=self)
                self.reload_accounts()
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------ #
    # 邮件列表：两行一条（主题 / 时间 · 发件人）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _short_time(date_text: str) -> str:
        """2026-11-09 17:22:24 -> 11-09 17:22"""
        try:
            return date_text[5:16]
        except Exception:
            return date_text

    @staticmethod
    def _sender_email(sender: str) -> str:
        """Fantopia <no-reply@x.io> -> no-reply@x.io"""
        m = re.search(r"<([^>]+)>", sender or "")
        return m.group(1).strip() if m else (sender or "").strip().strip('"')

    def _show_placeholder(self, text: str = "在左侧选择账号，点「获取邮件」取回最近邮件"):
        """没有邮件时的空状态：隐藏顶栏，正文区居中显示提示。"""
        self.topbar.grid_remove()
        self.mail_title.config(text="邮件")
        self.mail_list.configure(state="normal")
        self.mail_list.delete("1.0", "end")
        self.mail_list.configure(state="disabled")
        self._mail_spans = []
        self._current_mail = -1
        self._shown_acc_id = None
        self.detail_time.config(text="")

        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.tag_configure("hint", foreground="#9a9a9a", justify="center", spacing1=60)
        self.body.insert("1.0", text, "hint")
        self.body.configure(state="disabled")

    def _fill_mail_list(
        self, items: list[dict], cached: bool = False, acc_id: int | None = None, cached_note: str = ""
    ):
        self.mail_items = items
        if acc_id is not None:
            self._shown_acc_id = acc_id
        self.topbar.grid()
        self.mail_list.configure(state="normal")
        self.mail_list.delete("1.0", "end")
        self._mail_spans: list[tuple[str, str]] = []

        for m in items:
            start = self.mail_list.index("end-1c")
            self.mail_list.insert("end", m["subject"] or "（无主题）", "subject")
            self.mail_list.insert("end", "\n")
            meta = f"{self._short_time(m['date'])} · {self._sender_email(m['from'])}"
            self.mail_list.insert("end", meta, "meta")
            self.mail_list.insert("end", "\n")
            self._mail_spans.append((start, self.mail_list.index("end-1c")))

        self.mail_list.configure(state="disabled")

        if not items:
            self._show_placeholder("这个账号没有取到邮件")
            self.mail_title.config(text="邮件　最近 0 封")
            return

        suffix = f"　·　缓存 {cached_note}" if cached else ""
        self.mail_title.config(text=f"邮件　最近 {len(items)} 封{suffix}")
        self._select_mail(0)

    def _on_mail_click(self, event):
        idx = self.mail_list.index(f"@{event.x},{event.y}")
        for i, (start, end) in enumerate(self._mail_spans):
            if self.mail_list.compare(start, "<=", idx) and self.mail_list.compare(idx, "<", end):
                self._select_mail(i)
                return

    def _on_wheel(self, event):
        event.widget.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_wheel_linux(self, event):
        event.widget.yview_scroll(-1 if event.num == 4 else 1, "units")
        return "break"

    def _on_wheel_global(self, event):
        """事件落在非滚动控件上时，按光标位置找到真正的目标再滚。"""
        target = self.winfo_containing(event.x_root, event.y_root)
        while target is not None:
            if target in (self.tree, self.mail_list, self.body):
                target.yview_scroll(int(-event.delta / 120), "units")
                return "break"
            target = getattr(target, "master", None)
        return None

    def _select_mail(self, index: int):
        self.mail_list.configure(state="normal")
        self.mail_list.tag_remove("hl", "1.0", "end")
        if 0 <= index < len(self._mail_spans):
            start, end = self._mail_spans[index]
            self.mail_list.tag_add("hl", start, end)
        self.mail_list.configure(state="disabled")
        self._current_mail = index
        self._show_mail(index)

    # ------------------------------------------------------------------ #
    # 邮件内容
    # ------------------------------------------------------------------ #
    def _show_mail(self, index: int):
        if not (0 <= index < len(self.mail_items)):
            self.detail_time.config(text="")
            self._set_body("")
            return

        m = self.mail_items[index]
        self.detail_time.config(text=m["date"])
        self._set_body(m["text"] or "（没有正文）")

    def _set_body(self, text: str):
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", text)
        self.body.configure(state="disabled")

    def open_raw(self):
        if not (0 <= self._current_mail < len(self.mail_items)):
            return
        m = self.mail_items[self._current_mail]
        if not m.get("html"):
            messagebox.showinfo("没有原文", "这封邮件没有 HTML 部分。", parent=self)
            return
        folder = os.path.join(paths.data_dir(), "mail_preview")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            # exe 旁边和 %APPDATA% 都写不了（比如只读介质）时退回系统临时目录
            folder = os.path.join(tempfile.gettempdir(), "mailbox_gui")
            os.makedirs(folder, exist_ok=True)
        self._prune_preview(folder)
        path = os.path.join(folder, f"mail_{int(time.time())}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(m["html"])
        webbrowser.open(f"file:///{path.replace(os.sep, '/')}")

    @staticmethod
    def _prune_preview(folder, keep=20):
        """预览目录只留最近 20 封，避免越攒越多。"""
        try:
            files = sorted(
                (
                    os.path.join(folder, n)
                    for n in os.listdir(folder)
                    if n.startswith("mail_") and n.endswith(".html")
                ),
                key=os.path.getmtime,
            )
            for old in files[:-keep]:
                os.remove(old)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # 导入 / 导出
    # ------------------------------------------------------------------ #
    def open_import(self):
        ImportDialog(self, self.reload_accounts)

    def open_sync(self):
        if self.busy:
            messagebox.showinfo("正在取件", "等当前任务跑完再同步，避免同一个号两边互相顶掉。", parent=self)
            return
        accounts = self.accounts
        if not accounts:
            messagebox.showinfo("没有账号", "当前列表是空的。", parent=self)
            return
        SyncDialog(self, accounts, on_done=self.reload_accounts)

    def open_export(self):
        rows_all = store.list_accounts(self.search_var.get())
        rows_selected = []
        sel = self.tree.selection()
        if sel:
            acc = store.get_account(int(sel[0]))
            if acc:
                rows_selected = [acc]
        ExportDialog(self, rows_all, rows_selected)


if __name__ == "__main__":
    _install_excepthook()
    App().mainloop()
