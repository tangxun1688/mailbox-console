# -*- coding: utf-8 -*-
"""验证 dist 里的 exe 真的能起来（liveness check，不用人盯屏幕）。

启动 exe → 等窗口出现（EnumWindows 找标题）→ 检查 exe 旁边有没有生成 data.db
→ 连子进程一起 taskkill。

用法：
    python verify_exe.py                                   # 目录版默认路径
    python verify_exe.py 邮箱管理工具.exe                  # 单文件版
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
EXE = os.path.join(DIST, sys.argv[1] if len(sys.argv) > 1 else os.path.join("邮箱管理工具", "邮箱管理工具.exe"))

TITLE_KEY = "邮箱管理工具"
user32 = ctypes.windll.user32


def visible_windows() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((buf.value, pid.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def main() -> int:
    if not os.path.exists(EXE):
        print("✗ 找不到", EXE)
        return 1
    print("exe:", EXE, f"{os.path.getsize(EXE) / 1024 / 1024:.1f} MB")

    proc = subprocess.Popen([EXE])
    found = None
    deadline = time.time() + 60
    while time.time() < deadline and proc.poll() is None:
        time.sleep(1)
        found = next((w for w in visible_windows() if TITLE_KEY in w[0]), None)
        if found:
            break

    folder = os.path.dirname(EXE)
    db, log = os.path.join(folder, "data.db"), os.path.join(folder, "error.log")
    ok = bool(found) and os.path.exists(db) and not os.path.exists(log)
    print(f"窗口: {found}")
    print(f"data.db 落在 exe 旁边: {os.path.exists(db)}"
          + (f"  ({os.path.getsize(db)} bytes)" if os.path.exists(db) else ""))
    print(f"error.log: {os.path.exists(log)}")
    if os.path.exists(log):
        print(open(log, encoding="utf-8", errors="replace").read()[-3000:])
    print("进程存活:", proc.poll() is None)

    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    print("结果:", "✓ 通过" if ok else "✗ 不通过")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
