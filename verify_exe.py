# -*- coding: utf-8 -*-
"""验证 dist 里的 exe 真的能起来（liveness check，不用人盯屏幕）。

启动 exe → 等窗口出现（EnumWindows 找标题）→ 检查 exe 旁边有没有生成 data.db
→ 连子进程一起 taskkill。

用法：
    python verify_exe.py                                   # 目录版默认路径
    python verify_exe.py 邮箱管理工具.exe                  # 单文件版
    python verify_exe.py --timeout 10                      # 改等窗口的秒数
    MAILBOX_VERIFY_TEMP=D:\\tmp python verify_exe.py       # 指定子进程 TEMP
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
_argv = [a for a in sys.argv[1:] if not a.startswith("--")]
TIMEOUT = 30
if "--timeout" in sys.argv:
    TIMEOUT = int(sys.argv[sys.argv.index("--timeout") + 1])
EXE = os.path.join(DIST, _argv[0] if _argv else os.path.join("邮箱管理工具", "邮箱管理工具.exe"))

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


def _child_env() -> dict[str, str]:
    """给被测进程一个真的能建目录的 TEMP（单文件版要在这儿解包）。"""
    env = dict(os.environ)
    here = os.path.dirname(os.path.abspath(__file__))
    forced = env.get("MAILBOX_VERIFY_TEMP", "").strip()
    if forced:
        os.makedirs(forced, exist_ok=True)
        env["TEMP"] = env["TMP"] = os.path.abspath(forced)
        return env
    # 先试仓库内的 build/tmptest：DSH 沙箱/部分杀软会放过 %TEMP% 的普通写入，
    # 但单文件版 bootloader 在里面解包仍会直接弹 Error，所以仓库内目录更可靠。
    for cand in (os.path.join(here, "build", "tmptest"), env.get("TEMP", "")):
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, f"_probe_{os.getpid()}")
            os.mkdir(probe)
            os.rmdir(probe)
        except OSError:
            continue
        env["TEMP"] = env["TMP"] = os.path.abspath(cand)
        return env
    return env


def _ensure_dead(proc: subprocess.Popen, seconds: float = 10.0) -> bool:
    """taskkill 之后必须确认进程真的没了，否则 dist 里的 dll 会被锁住。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.5)
    # 兜底：直接 TerminateProcess
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0001, False, proc.pid)  # PROCESS_TERMINATE
    if h:
        k32.TerminateProcess(h, 1)
        k32.CloseHandle(h)
    try:
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        return False


def main() -> int:
    if not os.path.exists(EXE):
        print("✗ 找不到", EXE)
        return 1
    print("exe:", EXE, f"{os.path.getsize(EXE) / 1024 / 1024:.1f} MB")

    env = _child_env()
    print("子进程 TEMP:", env.get("TEMP"))
    proc = subprocess.Popen([EXE], env=env)
    found = None
    deadline = time.time() + TIMEOUT
    while time.time() < deadline and proc.poll() is None:
        time.sleep(1)
        # 标题必须完全相等：Explorer 窗口标题里也可能含"邮箱管理工具"
        found = next((w for w in visible_windows() if w[0].strip() == TITLE_KEY), None)
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
    if not _ensure_dead(proc):
        print("✗ 进程没能收掉（残留进程会锁住 dist 里的 dll，下次打包会 PermissionError）")
        ok = False
    else:
        print("进程已收尾")
    print("结果:", "✓ 通过" if ok else "✗ 不通过")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
