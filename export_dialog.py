# -*- coding: utf-8 -*-
"""导出对话框：选列 → 选分隔符 → 预览 → 保存 txt。"""

import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import exporter
from ui_util import center


class ExportDialog(tk.Toplevel):
    def __init__(self, master, rows_all, rows_selected):
        super().__init__(master)
        self.title("导出账号")
        self.geometry("620x560")
        self.transient(master)
        self.grab_set()

        self.rows_all = rows_all
        self.rows_selected = rows_selected
        self.col_vars: dict[str, tk.BooleanVar] = {}
        self.delim_var = tk.StringVar(value="----")
        self.scope_var = tk.StringVar(value="all")

        self._build()
        center(self, master, 620, 560)
        self._refresh_preview()

    # ------------------------------------------------------------------ #
    def _build(self):
        cols = ttk.LabelFrame(self, text="导出哪几列", padding=(10, 8))
        cols.pack(fill="x", padx=12, pady=(12, 0))
        defaults = {"email", "password", "client_id", "refresh_token"}
        for i, (key, label) in enumerate(exporter.EXPORT_COLUMNS):
            var = tk.BooleanVar(value=key in defaults)
            self.col_vars[key] = var
            cb = ttk.Checkbutton(cols, text=label, variable=var, command=self._refresh_preview)
            cb.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 18), pady=3)

        opts = ttk.LabelFrame(self, text="格式", padding=(10, 8))
        opts.pack(fill="x", padx=12, pady=(10, 0))

        line1 = ttk.Frame(opts)
        line1.pack(fill="x", pady=2)
        ttk.Label(line1, text="分隔符：", width=8).pack(side="left")
        for d in exporter.DELIMITERS:
            ttk.Radiobutton(
                line1, text=repr(d), value=d, variable=self.delim_var, command=self._refresh_preview
            ).pack(side="left", padx=(0, 16))

        line2 = ttk.Frame(opts)
        line2.pack(fill="x", pady=2)
        ttk.Label(line2, text="范围：", width=8).pack(side="left")
        ttk.Radiobutton(
            line2, text=f"当前列表全部（{len(self.rows_all)} 条）", value="all",
            variable=self.scope_var, command=self._refresh_preview,
        ).pack(side="left", padx=(0, 16))
        sel_btn = ttk.Radiobutton(
            line2, text=f"仅选中（{len(self.rows_selected)} 条）", value="selected",
            variable=self.scope_var, command=self._refresh_preview,
        )
        sel_btn.pack(side="left")
        if not self.rows_selected:
            sel_btn.state(["disabled"])
            if self.scope_var.get() == "selected":
                self.scope_var.set("all")

        prev = ttk.LabelFrame(self, text="预览（前 3 行）", padding=(8, 6))
        prev.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        self.preview = tk.Text(prev, height=8, wrap="none")
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")

        self.warn = ttk.Label(self, text="", foreground="#b03030")
        self.warn.pack(fill="x", padx=14, pady=(6, 0))

        bottom = ttk.Frame(self, padding=(12, 10))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="导出…", command=self._do_export).pack(side="right", padx=8)

    # ------------------------------------------------------------------ #
    def _columns(self) -> list[str]:
        return [key for key, _ in exporter.EXPORT_COLUMNS if self.col_vars[key].get()]

    def _rows(self):
        return self.rows_selected if self.scope_var.get() == "selected" else self.rows_all

    def _refresh_preview(self):
        columns = self._columns()
        rows = self._rows()
        if not columns:
            text = "（至少选一列）"
            self.warn.config(text="")
        else:
            lines = exporter.build_lines(rows[:3], columns, self.delim_var.get())
            text = "\n".join(lines) if lines else "（没有数据）"
            problems = exporter.find_conflicts(rows, columns, self.delim_var.get())
            self.warn.config(text="；".join(problems) if problems else "")

        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def _do_export(self):
        columns = self._columns()
        if not columns:
            messagebox.showwarning("没有选列", "至少勾选一列。", parent=self)
            return

        rows = self._rows()
        if not rows:
            messagebox.showwarning("没有数据", "当前范围没有账号。", parent=self)
            return

        delimiter = self.delim_var.get()
        lines = exporter.build_lines(rows, columns, delimiter)
        default_name = f"export_{datetime.now():%Y%m%d_%H%M}.txt"

        path = filedialog.asksaveasfilename(
            title="保存为",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("文本文件", "*.txt")],
        )
        if not path:
            return

        problems = exporter.find_conflicts(rows, columns, delimiter)
        if problems and not messagebox.askyesno(
            "存在分隔符冲突",
            "以下数据本身就含有分隔符，导出后可能被下游解析错：\n\n"
            + "\n".join(problems)
            + "\n\n仍然导出吗？",
            parent=self,
        ):
            return

        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
                fh.write("\n".join(lines))
                fh.write("\n")
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return

        messagebox.showinfo("导出完成", f"已导出 {len(lines)} 条到\n{path}", parent=self)
        self.destroy()
