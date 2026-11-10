# -*- coding: utf-8 -*-
"""运行时路径。源码运行和 PyInstaller 打包后（frozen）行为一致。

打包成 exe 后有两个"当前目录"会打架，必须分清楚：

- `app_dir()`      —— **exe 所在目录**。用户数据（data.db、error.log）放这里，
                     拷走文件夹即带走全部账号，绿色便携。
- `resource_dir()` —— **只读资源目录**。onefile 模式下是 `sys._MEIPASS`
                     临时解包目录，每次启动都不一样、退出即删，
                     绝不能往里写数据库。

坑：源码里 `Path(__file__).with_name("data.db")` 在 exe 里会指向
`%TEMP%\\_MEIxxxx\\data.db`，表现为"每次启动都空库、导入的账号全丢"。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "mailbox-gui"


def is_frozen() -> bool:
    """是否运行在 PyInstaller（或同类）打包后的可执行文件里。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """用户数据目录：exe 所在目录；源码运行时是工程目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """只读资源目录（图标等）。onefile 下是临时解包目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent


def _writable(path: Path) -> bool:
    """真的写一个文件试试。os.access 在 Windows ACL 下不可靠。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".wtest_", dir=path)
        os.close(fd)
        os.unlink(probe)
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """可写数据目录。

    绝大多数情况就是 exe 旁边（绿色版）。只有在只读位置运行时
    （解压到 `C:\\Program Files` 之类）才退到 `%APPDATA%\\mailbox-gui`。
    """
    here = app_dir()
    if _writable(here):
        return here
    fallback = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def db_path() -> Path:
    """数据库路径。环境变量 `MAILBOX_DB` 可覆盖（测试 / 多套数据用）。"""
    override = os.environ.get("MAILBOX_DB")
    if override:
        return Path(override).expanduser().resolve()
    return data_dir() / "data.db"


def log_path() -> Path:
    """崩溃日志路径（--noconsole 打包后看不到 stderr，只能落盘）。"""
    return data_dir() / "error.log"
