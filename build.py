# -*- coding: utf-8 -*-
"""把 mailbox-gui 打包成可直接双击运行的 exe（PyInstaller）。

用法（都在工程根目录跑）：
    python build.py                  # 目录版 → dist/邮箱管理工具/邮箱管理工具.exe（推荐）
    python build.py --onefile        # 单文件 → dist/邮箱管理工具.exe
    python build.py --both --zip     # 目录版 + 单文件，并把目录版打成 zip
    python build.py --console        # 保留控制台，启动报错直接看得见
    python build.py --both --verify  # 打完自动起窗口自检（失败返回非 0）
    python build.py --both --verify --verify-timeout 15   # 自检等窗口的秒数
    python build.py --name Foo       # 换名字

排错用开关：
    --runtime-tmpdir PATH   单文件版解包到哪个目录。默认用 %TEMP%；
                            在沙箱 / 受限权限环境里 %TEMP% 不允许建目录时，
                            指向一个可写目录（如 D:\\tmp）即可。
    --no-icon               不嵌入 app.ico
    --no-clean              复用 build 缓存（第二次打包快一点）

依赖：只用标准库 + 打包时用到的 PyInstaller。当前解释器没装 PyInstaller 时，
脚本会自动建 `.venv-build` 虚拟环境并只装 PyInstaller——保证不把无关包拖进 exe。
解释器必须**带 tkinter**（本机 3.15.1 有；workbuddy 自带 3.13.12 没有）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv-build"
VENV_PY = VENV / "Scripts" / "python.exe"
DEFAULT_NAME = "邮箱管理工具"

VERSION_FILE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 1, 0, 0), prodvers=(0, 1, 0, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', ''),
        StringStruct('FileDescription', '邮箱管理工具'),
        StringStruct('FileVersion', '0.1.0'),
        StringStruct('InternalName', 'mailbox-gui'),
        StringStruct('OriginalFilename', '{exe}'),
        StringStruct('ProductName', '邮箱管理工具'),
        StringStruct('ProductVersion', '0.1.0')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def _ensure_pyinstaller() -> None:
    """PyInstaller 装在独立 venv 里，避免把无关包打进 exe。"""
    try:
        import PyInstaller  # noqa: F401

        return
    except ImportError:
        pass

    if not VENV_PY.exists():
        print(f"[build] 创建打包用虚拟环境 {VENV.name}（只需一次）…")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False)
        print("[build] 安装 PyInstaller …")
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "pyinstaller"], check=True)

    # 换 venv 的解释器重新执行本脚本（venv 里已装好 PyInstaller）
    print(f"[build] 切换到 {VENV_PY}")
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])


def _kill_stale(name: str = "邮箱管理工具") -> None:
    """上一轮自检/试运行没退干净的实例会锁住 _internal 里的 dll，先收掉。"""
    exe = f"{name}.exe"
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="mbcs", errors="replace").stdout
    pids = [line.split('","')[1] for line in out.splitlines() if line.startswith('"')]
    for pid in pids:
        print(f"[kill] 收掉残留进程 {exe} pid={pid}")
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)


def _build(onefile: bool, args) -> Path:
    import PyInstaller.__main__ as pyi

    icon = ROOT / "app.ico"
    use_icon = not args.no_icon and icon.exists()
    build_tmp = ROOT / "build"
    build_tmp.mkdir(exist_ok=True)

    version_file = build_tmp / f"version_info_{'onefile' if onefile else 'onedir'}.txt"
    version_file.write_text(
        VERSION_FILE.format(exe=args.name + ".exe"), encoding="utf-8"
    )

    argv = [
        str(ROOT / "app.py"),
        "--name", args.name,
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(build_tmp / ("onefile" if onefile else "onedir")),
        "--specpath", str(build_tmp),
        "--noconfirm",
        "--log-level", "INFO" if args.no_clean else "WARN",
        "--console" if args.console else "--windowed",
        "--onefile" if onefile else "--onedir",
        "--version-file", str(version_file),
        # 只用标准库；显式排除重型包，防止哪天误装后被拖进 exe
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        "--exclude-module", "pip",
    ]
    if not args.no_clean:
        argv.append("--clean")
    if use_icon:
        argv += ["--icon", str(icon), "--add-data", f"{icon}{os.pathsep}."]
    if onefile and args.runtime_tmpdir:
        argv += ["--runtime-tmpdir", args.runtime_tmpdir]

    print(f"\n[build] {'单文件' if onefile else '目录版'}打包开始 …")
    pyi.run(argv)

    target = (
        ROOT / "dist" / (args.name + ".exe")
        if onefile
        else ROOT / "dist" / args.name / (args.name + ".exe")
    )
    if not target.exists():
        print(f"[build] ✗ 没找到产物 {target}")
        raise SystemExit(1)
    print(f"[build] ✓ {target}  ({target.stat().st_size / 1024 / 1024:.1f} MB)")
    _warn_low_integrity(target)
    return target


def _warn_low_integrity(target: Path) -> None:
    """产物若落在低完整性目录（沙箱/受限），会带上 Low 标签 → 单文件版解包被拒。

    症状：双击后弹 “Could not create temporary directory!”。修复：把 exe 复制到普通
    用户目录（复制会丢掉标签），或管理员执行 `icacls <exe> /setintegritylevel Medium`。
    """
    try:
        r = subprocess.run(
            ["icacls", str(target)], capture_output=True, text=True,
            encoding="gbk", errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return
    out = (r.stdout or "") + (r.stderr or "")
    if "Low Mandatory" not in out and "低强制" not in out:
        return
    print(
        "[build] ⚠ 产物带 Low 完整性标签（构建目录是低完整性/受限目录）\n"
        "        目录版不受影响；单文件版双击会报 Could not create temporary directory。\n"
        "        解决办法：把 exe 复制到普通用户目录（复制会丢掉该标签），\n"
        "        或用管理员执行 icacls <exe> /setintegritylevel Medium"
    )


def _verify(target: Path, timeout: int) -> bool:
    """跑 verify_exe.py：起窗口 → 查 data.db/error.log → 收尾。

    自检会真的建一次 data.db，跑完把它删掉，免得留在 dist 里被打进 zip。
    """
    rel = target.relative_to(ROOT / "dist")
    folder = target.parent
    before = {p.name for p in folder.glob("*.db*")} | {p.name for p in folder.glob("error.log")}
    print(f"\n[verify] {rel} …")
    rc = subprocess.run(
        [sys.executable, str(ROOT / "verify_exe.py"), str(rel), "--timeout", str(timeout)],
        cwd=str(ROOT),
    ).returncode
    for path in list(folder.glob("*.db*")) + list(folder.glob("error.log")):
        if path.name not in before:
            path.unlink(missing_ok=True)
    return rc == 0


def _zip_dir(folder: Path) -> Path:
    out = folder.parent / f"{folder.name}-便携版.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, Path(folder.name) / p.relative_to(folder))
    print(f"[build] ✓ {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="打包 mailbox-gui 成 exe")
    ap.add_argument("--onedir", action="store_true", help="目录版（默认就是它）")
    ap.add_argument("--onefile", action="store_true", help="单文件 exe")
    ap.add_argument("--both", action="store_true", help="目录版 + 单文件都打")
    ap.add_argument("--zip", action="store_true", help="目录版额外打 zip")
    ap.add_argument("--console", action="store_true", help="保留控制台窗口（排错用）")
    ap.add_argument("--name", default=DEFAULT_NAME, help=f"exe 名，默认 {DEFAULT_NAME}")
    ap.add_argument("--runtime-tmpdir", default=None, help="单文件版解包目录（受限环境用）")
    ap.add_argument("--no-icon", action="store_true", help="不嵌入图标")
    ap.add_argument("--no-clean", action="store_true", help="复用 build 缓存")
    ap.add_argument("--verify", action="store_true", help="打完后立刻跑 verify_exe.py 自检")
    ap.add_argument("--verify-timeout", type=int, default=30, help="自检等窗口的秒数，默认 30")
    args = ap.parse_args()

    _ensure_pyinstaller()

    want_onefile = args.onefile or args.both
    want_onedir = args.onedir or args.both or not want_onefile

    built: list[Path] = []
    _kill_stale(args.name)
    if want_onedir:
        # 打包前把上一轮的 data.db / error.log 挪走，避免把用户数据打进 zip
        for leftover in (ROOT / "dist" / args.name).glob("*.db*"):
            leftover.unlink()
        built.append(_build(False, args))
        if args.zip:
            _zip_dir(ROOT / "dist" / args.name)
    if want_onefile:
        built.append(_build(True, args))

    if args.verify:
        results = [(t, _verify(t, args.verify_timeout)) for t in built]
        failed = [t for t, ok in results if not ok]
        if failed:
            print("\n[verify] ✗ 自检未通过：" + "、".join(t.name for t in failed))
            return 1
        print("\n[verify] ✓ 全部自检通过")

    print("\n[build] 分发说明：")
    print("  · 把出厂的 exe（或整个目录）拷给另一台机器，首次运行会在它旁边生成空的 data.db。")
    print("  · 要沿用现有账号：把工程里的 data.db 一起拷到 exe 旁边（注意里面是明文密码）。")
    print("  · 目录版启动更快、更不容易被杀软误杀；单文件版方便但每次启动要解包到 %TEMP%。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
