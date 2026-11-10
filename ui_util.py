# -*- coding: utf-8 -*-
"""界面小工具。"""

import tkinter as tk


def center(win, parent=None, width: int | None = None, height: int | None = None) -> None:
    """把窗口摆到父窗口中间；没有父窗口就摆到屏幕中间。

    Tk 的 Toplevel 不给坐标时由系统决定，Windows 上经常跑到左上角。
    """
    win.update_idletasks()
    w = width or win.winfo_width()
    h = height or win.winfo_height()

    if parent is not None and parent.winfo_viewable():
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 3)
    else:
        x = (win.winfo_screenwidth() - w) // 2
        y = (win.winfo_screenheight() - h) // 2

    win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")


class CenteredToplevel(tk.Toplevel):
    """新建弹窗的约定写法：继承它并传宽高，打开后自动居中到父窗口。

        class FooDialog(CenteredToplevel):
            def __init__(self, master):
                super().__init__(master, 800, 600)
                ...建控件...
                # 不要再自己设 geometry 坐标

    已有对话框（导入/导出/同步）是在 __init__ 末尾显式调用 center() 的，
    效果一样；新写的窗口建议直接用这个基类。
    """

    def __init__(self, master, width: int, height: int, **kwargs):
        super().__init__(master, **kwargs)
        self._win_size = (width, height)
        self.after_idle(self._apply_center)

    def _apply_center(self):
        try:
            self.update_idletasks()
            center(self, self.master, *self._win_size)
        except tk.TclError:
            pass
