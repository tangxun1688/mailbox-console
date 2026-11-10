# -*- coding: utf-8 -*-
"""令牌同步：批量把 refresh_token 兑换一次并写回，用来保活 + 找出死号。

单独窗口，和主界面分开。同步会轮换令牌，所以同步期间主界面不要取件。
"""

import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from tkinter import messagebox, ttk

import mail
import store
from ui_util import center


class SyncDialog(tk.Toplevel):
    def __init__(self, master, accounts, on_done=None):
        super().__init__(master)
        self.title("同步令牌")
        self.geometry("820x520")
        self.transient(master)
        self.grab_set()

        self.accounts = [dict(a) for a in accounts]
        self.on_done = on_done
        self.queue: queue.Queue = queue.Queue()
        self.running = False
        self.stop_flag = False
        self.ok = 0
        self.fail = 0
        self.skipped = 0

        self._build()
        center(self, master, 820, 520)
        self.after(100, self._poll)

    # ------------------------------------------------------------------ #
    def _build(self):
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text=f"待同步 {len(self.accounts)} 个账号").pack(side="left")

        ttk.Label(top, text="并发").pack(side="left", padx=(16, 4))
        self.conc_var = tk.StringVar(value="3")
        ttk.Combobox(
            top, textvariable=self.conc_var, values=["1", "2", "3", "4", "5"],
            width=3, state="readonly",
        ).pack(side="left")

        self.start_btn = ttk.Button(top, text="开始同步", command=self.start)
        self.start_btn.pack(side="right")
        self.stop_btn = ttk.Button(top, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=8)

        note = ttk.Label(
            self,
            text="同步会兑换并轮换每个账号的 refresh_token。期间请不要在主界面取件，"
                 "否则同一个号两边会互相顶掉。",
            foreground="#8a6d3b",
            wraplength=780,
            justify="left",
        )
        note.pack(fill="x", padx=14, pady=(0, 6))

        self.summary = ttk.Label(self, text=self._summary_text(), foreground="#666", wraplength=780)
        self.summary.pack(fill="x", padx=14, pady=(0, 8))

        prog = ttk.Frame(self, padding=(12, 0))
        prog.pack(fill="x")
        self.bar = ttk.Progressbar(prog, mode="determinate", maximum=max(1, len(self.accounts)))
        self.bar.pack(side="left", fill="x", expand=True)
        self.stat = ttk.Label(prog, text="0 / 0", width=26, anchor="e")
        self.stat.pack(side="right", padx=(8, 0))

        table = ttk.Frame(self, padding=(12, 8))
        table.pack(fill="both", expand=True)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table, columns=("email", "result", "cost", "detail"), show="headings")
        for key, title, width, anchor in (
            ("email", "邮箱", 260, "w"),
            ("result", "结果", 90, "center"),
            ("cost", "耗时", 70, "center"),
            ("detail", "说明", 340, "w"),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("bad", foreground="#b03030")

        for acc in self.accounts:
            self.tree.insert("", "end", iid=str(acc["id"]), values=(acc["email"], "等待", "", ""))

        bottom = ttk.Frame(self, padding=(12, 8))
        bottom.pack(fill="x")
        self.hint = ttk.Label(bottom, text="", foreground="#666")
        self.hint.pack(side="left")
        ttk.Button(bottom, text="关闭", command=self.close).pack(side="right")

    # ------------------------------------------------------------------ #
    def _summary_text(self) -> str:
        """这条横幅告诉用户：最快什么时候到期、有多少号从没同步过。"""
        best, unknown = None, 0
        for acc in self.accounts:
            ts = (acc.get("token_updated_at") or "").strip()
            if not ts:
                unknown += 1
                continue
            try:
                days = (datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).days
            except ValueError:
                unknown += 1
                continue
            remain = store.EXPIRY_DAYS - days
            if best is None or remain < best[0]:
                best = (remain, acc["email"])

        parts = []
        if best:
            word = "已过期" if best[0] < 0 else f"{best[0]} 天后到期"
            parts.append(f"最快 {word}（{best[1]}）")
        if unknown:
            parts.append(f"{unknown} 个账号还没同步过，无到期时间")
        return "　·　".join(parts) or "全部账号都还没有同步记录"

    def start(self):
        if self.running or not self.accounts:
            return
        self.running = True
        self.stop_flag = False
        self.ok = self.fail = self.skipped = 0
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.bar.config(value=0, maximum=len(self.accounts))
        self.hint.config(text="正在同步…")

        workers = max(1, int(self.conc_var.get()))
        threading.Thread(target=self._worker, args=(workers,), daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.stop_btn.config(state="disabled")
        self.hint.config(text="正在停止，已在跑的会跑完…")

    def _worker(self, workers: int):
        total = len(self.accounts)
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._sync_one, acc): acc for acc in self.accounts}
            for fut in as_completed(futures):
                acc_id, status, detail, cost = fut.result()
                done += 1
                if status is True:
                    self.ok += 1
                elif status is False:
                    self.fail += 1
                else:
                    self.skipped += 1
                self.queue.put(("row", acc_id, (status, detail, cost)))
                self.queue.put(("progress", None, (done, total)))
        self.queue.put(("done", None, (total, self.ok, self.fail, self.skipped)))

    def _sync_one(self, acc: dict):
        if self.stop_flag:
            return acc["id"], None, "已跳过", 0.0
        started = time.time()
        try:
            result = mail.exchange_token(acc["client_id"], acc["refresh_token"])
            store.update_token(
                acc["id"],
                result["refresh_token"],
                result["access_token"],
                time.time() + result["expires_in"],
                source="sync",
            )
            return acc["id"], True, "已更新", time.time() - started
        except mail.MailError as e:
            store.update_status(acc["id"], "令牌失效", str(e))
            return acc["id"], False, str(e)[:80], time.time() - started
        except Exception as e:
            store.update_status(acc["id"], "令牌失效", f"{type(e).__name__}: {e}")
            return acc["id"], False, f"{type(e).__name__}: {e}"[:80], time.time() - started

    # ------------------------------------------------------------------ #
    def _poll(self):
        try:
            while True:
                kind, acc_id, payload = self.queue.get_nowait()

                if kind == "row":
                    status, detail, cost = payload
                    label = "✓ 已更新" if status else ("— 已跳过" if status is None else "✗ 失败")
                    tag = "ok" if status else ("bad" if status is False else "")
                    if self.tree.exists(str(acc_id)):
                        self.tree.set(str(acc_id), "result", label)
                        self.tree.set(str(acc_id), "cost", f"{cost:.1f}s")
                        self.tree.set(str(acc_id), "detail", detail)
                        if tag:
                            self.tree.item(str(acc_id), tags=(tag,))
                    continue

                if kind == "progress":
                    done, total = payload
                    self.bar.config(value=done)
                    self.stat.config(text=f"{done} / {total}　成功 {self.ok}　失败 {self.fail}")
                    continue

                if kind == "done":
                    total, ok, fail, skipped = payload
                    self.running = False
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    msg = f"完成：成功 {ok}，失败 {fail}"
                    if skipped:
                        msg += f"，跳过 {skipped}"
                    self.hint.config(text=msg)
                    if self.on_done:
                        self.on_done()
                    continue
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def close(self):
        if self.running:
            if not messagebox.askyesno("同步未完成", "还在同步，确定关闭吗？", parent=self):
                return
            self.stop_flag = True
        self.destroy()
