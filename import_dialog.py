# -*- coding: utf-8 -*-
"""导入对话框：粘贴或选文件 → 嗅探分隔符 → 字段映射 → 预览 → 入库。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import importer
import paths
import store
from ui_util import center


class ImportDialog(tk.Toplevel):
    def __init__(self, master, on_done):
        super().__init__(master)
        self.title("导入邮箱账号")
        self.geometry("780x640")
        self.transient(master)
        self.grab_set()

        self.on_done = on_done
        self.rows: list[list[str]] = []
        self.sep = "----"
        self.mapping: list[str] = []
        self.combos: list[ttk.Combobox] = []

        self._build()
        center(self, master, 780, 640)

    # ------------------------------------------------------------------ #
    def _build(self):
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="把账号数据粘贴到下面（支持 ---- / Tab / 逗号 / 冒号等分隔），也可以从文件读入").pack(side="left")
        ttk.Button(top, text="从文件读取…", command=self._choose_file).pack(side="right")

        box = ttk.Frame(self, padding=(12, 0))
        box.pack(fill="x")
        self.text = tk.Text(box, height=7, wrap="none", font=("Consolas", 9))
        self.text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        sb.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=sb.set)

        # 粘贴后自动解析，省一次点击
        self.text.bind("<<Paste>>", lambda _e: self.after(150, self._parse))

        bar = ttk.Frame(self, padding=(12, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="解析内容", command=self._parse).pack(side="left")
        self.hint = ttk.Label(bar, text="", foreground="#888")
        self.hint.pack(side="left", padx=10)

        mid = ttk.LabelFrame(self, text="字段映射（每列对应什么）", padding=(10, 8))
        mid.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self.map_frame = ttk.Frame(mid)
        self.map_frame.pack(fill="both", expand=True)

        low = ttk.LabelFrame(self, text="预览（前 3 行）", padding=(10, 8))
        low.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        self.preview = tk.Text(low, height=4, wrap="none")
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")

        bottom = ttk.Frame(self, padding=(12, 10))
        bottom.pack(fill="x")
        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bottom, text="覆盖已存在的字段（含令牌）", variable=self.overwrite_var
        ).pack(side="left")
        ttk.Label(bottom, text="默认只补空，不会冲掉库里更新的令牌", foreground="#888").pack(
            side="left", padx=8
        )
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        self.ok_btn = ttk.Button(bottom, text="导入", command=self._do_import, state="disabled")
        self.ok_btn.pack(side="right", padx=8)

    # ------------------------------------------------------------------ #
    def _choose_file(self):
        path = filedialog.askopenfilename(
            title="选择账号文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=str(paths.app_dir()),
        )
        if not path:
            return
        try:
            content = importer.read_text(path)
        except Exception as e:
            messagebox.showerror("读取失败", str(e), parent=self)
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self._parse()

    def _parse(self):
        content = self.text.get("1.0", "end")
        lines = importer.parse_text(content)
        if not lines:
            self.hint.config(text="还没有内容，先粘贴或选文件")
            return

        self.sep = importer.detect_separator(lines)
        self.rows = importer.split_lines(lines, self.sep)
        self.mapping = importer.guess_mapping(self.rows)
        self._build_mapping()
        self._refresh_preview()
        self.ok_btn.config(state="normal")
        self.hint.config(text=f"识别到分隔符 {self.sep!r}，共 {len(self.rows)} 行")

    def _build_mapping(self):
        for child in self.map_frame.winfo_children():
            child.destroy()
        self.combos = []

        headers = ttk.Frame(self.map_frame)
        headers.pack(fill="x")
        for text, width in (("列", 6), ("样例", 46), ("解析为", 16)):
            ttk.Label(headers, text=text, width=width).pack(side="left")

        ncols = max(len(r) for r in self.rows)
        for i in range(ncols):
            line = ttk.Frame(self.map_frame)
            line.pack(fill="x", pady=2)
            ttk.Label(line, text=f"第 {i + 1} 列", width=6).pack(side="left")

            sample = next((r[i] for r in self.rows if i < len(r) and r[i]), "")
            if len(sample) > 46:
                sample = sample[:20] + "…" + sample[-10:]
            ttk.Label(line, text=sample, width=46, anchor="w").pack(side="left")

            var = tk.StringVar(value=self.mapping[i] if i < len(self.mapping) else "")
            values = [label for _, label in importer.FIELD_OPTIONS]
            combo = ttk.Combobox(line, values=values, state="readonly", width=14)
            combo.set(dict(importer.FIELD_OPTIONS).get(var.get(), "忽略"))
            combo.pack(side="left", padx=6)
            combo.bind("<<ComboboxSelected>>", lambda _e, i=i: self._on_combo(i))
            self.combos.append(combo)

    def _on_combo(self, index: int):
        label = self.combos[index].get()
        self.mapping[index] = next((k for k, v in importer.FIELD_OPTIONS if v == label), "")
        self._refresh_preview()

    def _refresh_preview(self):
        lines = importer.preview_lines(self.rows, self.mapping, 3)
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", "\n".join(lines) if lines else "（没有可预览的内容）")
        self.preview.configure(state="disabled")

    def _do_import(self):
        accounts, row_stats = importer.build_accounts(self.rows, self.mapping)
        if not accounts:
            messagebox.showwarning(
                "没有可导入的行",
                "邮箱 / 密码 / Client ID / 令牌 四项都必须有值。\n"
                f"当前：缺邮箱 {row_stats['no_email']} 行，缺必填字段 {row_stats['incomplete']} 行。\n"
                "检查下面的字段映射是否对错了列。",
                parent=self,
            )
            return
        try:
            stats = store.upsert_accounts(accounts, overwrite=self.overwrite_var.get())
        except Exception as e:
            messagebox.showerror("写入失败", str(e), parent=self)
            return

        msg = f"新增 {stats['added']} 条"
        if stats["filled"]:
            msg += f"，补全 {stats['filled']} 条"
        if stats["overwritten"]:
            msg += f"，覆盖 {stats['overwritten']} 条"

        skipped = []
        if row_stats["no_email"]:
            skipped.append(f"缺邮箱 {row_stats['no_email']} 行")
        if row_stats["incomplete"]:
            skipped.append(f"缺必填字段 {row_stats['incomplete']} 行")
        if skipped:
            msg += "\n\n已跳过：" + "，".join(skipped)

        if stats["kept"]:
            msg += (
                f"\n\n有 {stats['kept']} 条已存在且内容不同，已保留库里的值，没有覆盖。\n"
                "确实要用文件里的旧值，勾选「覆盖已存在的字段」再导一次。"
            )
        messagebox.showinfo("导入完成", msg, parent=self)
        self.on_done()
        self.destroy()
