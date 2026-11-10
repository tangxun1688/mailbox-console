# 打包成可直接运行的 exe（PyInstaller）

> 结论：**PyInstaller 目录版 + 便携 zip 已经验证可用，日常就发这个。**
> 一条命令出成品：`python build.py --zip`（或双击 `build.bat`）。
>
> 单文件版（15 MB 一个 exe）仍然支持（`--onefile`），但**默认不再产出**：它每次启动要把运行时解包到
> `%TEMP%`，启动慢、易被杀软误杀，而且在低完整性目录里会报 `Could not create temporary directory!`（§6.1b）。

---

## 0. 三十秒版

```bash
cd G:\AI_All\DSHWork\mailbox-gui
python build.py --zip
```

产物（`dist\`）：

| 产物 | 形态 | 大小 | 说明 |
|---|---|---:|---|
| `dist\邮箱管理工具\邮箱管理工具.exe` | **目录版**（exe + `_internal\`） | exe 3.1 MB，整目录约 32 MB | 解压/拷贝后直接双击，**推荐** |
| `dist\邮箱管理工具-便携版.zip` | 目录版打成的 zip | 约 15 MB | 分发包：拷给别人，解压即用 |
| `dist\邮箱管理工具.exe` | 单文件版（**仅 `--onefile` 时产出**） | 15.1 MB | 一个文件走天下，但启动要解包到 `%TEMP%`，不推荐 |

两个版本都不需要在目标机器装 Python、也不需要装 VC++ 运行库（`VCRUNTIME140.dll` 已打进 `_internal\`）。

**数据不打包**：exe 旁边没有 `data.db` 时首次启动自动建空库；要沿用现有账号，把工程里的
`data.db` 拷到 exe 同一目录即可（里面是明文密码和令牌，别乱放）。

---

## 1. 环境要求

| 项 | 要求 |
|---|---|
| 解释器 | **必须带 tkinter** 的 CPython。本机用 `C:\Users\Ryan\AppData\Local\Python\pythoncore-3.15-64\python.exe`（3.15.1 / Tk 9.0）。workbuddy 自带的 3.13.12 **没有 tkinter，打出来会启动即崩** |
| PyInstaller | 6.22.3（`build.py` 会自动装到 `.venv-build\`，见下） |
| 网络 | 首次装 PyInstaller 需要能访问 PyPI |
| MSVC | **不需要**（所以 Nuitka 这条路走不通，见 §7） |

`build.py` 的自我保护：如果当前解释器里没有 PyInstaller，它会

1. 在工程下建 `.venv-build\`（虚拟环境，已加 `.gitignore`）；
2. 只装 `pyinstaller` 一个包（保证不会把 numpy/PIL 之类误带进 exe）；
3. `os.execv` 切到 `.venv-build\Scripts\python.exe` 重新执行自己。

换机器时若 python 不在 PATH，直接写全路径调用即可：

```bat
"C:\Users\Ryan\AppData\Local\Python\pythoncore-3.15-64\python.exe" build.py --zip
```

---

## 2. 命令开关

```bash
python build.py                 # 目录版（默认）→ dist\邮箱管理工具\
python build.py --onefile       # 单文件      → dist\邮箱管理工具.exe
python build.py --zip           # 目录版 + 便携 zip（日常就这个）
python build.py --both --zip    # 额外再出一个单文件版
python build.py --console       # 保留黑色控制台窗口，启动报错直接看得见（排错用）
python build.py --name Foo      # 换 exe 名字
python build.py --no-clean      # 复用 build\ 缓存，第二次打包更快
python build.py --runtime-tmpdir D:\temp   # 单文件版解包目录（受限环境用，见 §6.1）
python build.py --zip --verify   # 打完后自动起窗口自检，通过才返回 0
python build.py --zip --verify --verify-timeout 15    # 自检等窗口的秒数（默认 30）
```

`build.bat` 只是 `chcp 65001` + `python build.py %*` + 失败 `pause` 的壳，双击即可。

产物时间：全新打包约 18 秒（两种都打）。

---

## 3. 为了能冻结，改动过哪些代码

原始版本按「从源码目录运行」写死了几处路径，直接打包会出现**窗口起不来**或**每次启动空库**。
现在的处理：

| 文件 | 改动 | 原因 |
|---|---|---|
| `paths.py`（新增） | `is_frozen()` / `app_dir()` / `resource_dir()` / `data_dir()` / `db_path()` / `log_path()` | 统一回答「exe 在哪、数据写哪、只读包里的资源在哪」 |
| `store.py` | `DB_PATH = paths.db_path()` | 原来是 `Path(__file__).with_name("data.db")`，单文件版里 `__file__` 指向 `%TEMP%\_MEIxxxx\`，**每次启动都是空库、关掉就丢** |
| `view_db.py` | `DB = paths.db_path()` | 同上，保证命令行查的是 exe 旁边的同一个库 |
| `import_dialog.py` | 导入默认目录 = `paths.app_dir()` | 打包后 cwd 不可靠 |
| `app.py` | 新增 `log_crash()` / `_install_excepthook()` / `App.report_callback_exception()` | exe 是 `--windowed`，没有控制台，异常只能靠 `error.log` + 弹窗 |
| `app.py` | 新增 `_set_icon()` | 从 exe 目录或 `_MEIPASS` 找 `app.ico` 设窗口图标，找不到静默跳过 |
| `app.py` | 「查看原文」的 HTML 改写到 `data_dir()\mail_preview\`（只留最近 20 个），失败才退回 `%TEMP%` | `%TEMP%` 在某些环境不可写；也避免预览文件散落 |
| `tools/make_icon.py`（新增） | 纯标准库生成 `app.ico`（7 个尺寸） | 仓库里要有图标源；随时可重新生成 |
| `build.py` / `build.bat`（新增） | 打包脚本 | 见 §2 |
| `verify_exe.py`（新增） | 无人值守自检 | 见 §5 |

数据目录规则（`paths.data_dir()`）：

1. **exe 所在目录** —— 便携第一优先；实测可写（`mkstemp` 试探）就用它；
2. 不可写（比如放在 `C:\Program Files`、只读介质）→ 退到 `%APPDATA%\mailbox-gui\`；
3. 还可用环境变量 `MAILBOX_DB=<路径>` 强制指定整条 `data.db` 路径（测试/多套数据用）。

---

## 4. 产物怎么交付

### 目录版（推荐）
把整个 `dist\邮箱管理工具\` 文件夹拷走（或用 `-便携版.zip`），双击里面的 `邮箱管理工具.exe`。
首次运行会在 exe 旁边生成空的 `data.db` 和（出错时）`error.log`。

### 单文件版
只拷 `dist\邮箱管理工具.exe`。注意：

- 启动时会把 15 MB 解包到 `%TEMP%\_MEIxxxx\`，**首次启动 1–3 秒**，随后退出时自动清理；
- 少数安全软件会拦「PyInstaller 自解压」行为（见 §6.2）；
- 若目标机的 `%TEMP%` 不允许建目录，会弹 `Error: Could not create temporary directory!`（见 §6.1）。

### 带上现有数据
```bash
copy data.db dist\邮箱管理工具\data.db
```
或单文件版：`copy data.db dist\data.db`。**注意 `data.db` 是明文凭证，不要提交 git、不要进 zip 外发。**

---

## 5. 验证记录（本机实测）

`verify_exe.py` 会启动 exe、30 秒内（`--timeout` 可调）用 `EnumWindows` 找标题**完全等于**「邮箱管理工具」的可见窗口（`in` 匹配会被资源管理器窗口误命中）、
检查 exe 旁边是否生成 `data.db`、是否出现 `error.log`，最后 `taskkill /T /F` 收尾。

```bash
python build.py --zip
python verify_exe.py                          # 目录版
python verify_exe.py 邮箱管理工具.exe         # 单文件版
python verify_exe.py --timeout 10             # 改等窗口的秒数
MAILBOX_VERIFY_TEMP=D:\tmp python verify_exe.py   # 指定子进程 TEMP（单文件版解包用）
```

实测结果：

| 用例 | 结果 |
|---|---|
| 源码冒烟：`App()` → 1120×760 | ✓ |
| 目录版 exe 启动 | ✓ 窗口标题「邮箱管理工具」，生成 28 KB 空库 |
| 目录版 + 真实 4.7 MB `data.db` | ✓ 正常启动，`accounts = 1010`，无 `error.log` |
| 单文件版 exe（`%TEMP%` 可用时） | ✓ 窗口正常，`data.db` 落在 exe 旁边（不是 `_MEIxxxx` 里） |
| 单文件版（产物落在低完整性目录，带 Low 标签） | ✗ `Could not create temporary directory!` —— 低完整性进程建不了解包目录，见 §6.1（b） |
| 同一份单文件 exe 复制到 `%USERPROFILE%` 下再启动 | ✓ 窗口正常、生成 `data.db`（复制会丢掉 Low 标签） |

图标 / 版本信息也验过：exe 属性里 `产品名称 = 邮箱管理工具`、版本 `0.1.0`，任务栏与窗口左上角都是信封图标。

---

### 一条命令连打包带自检

```bat
python build.py --zip --verify
```

目录版和单文件版都会真的启动一次、确认窗口起来、确认 `data.db` 落在 exe 旁边、
确认没有 `error.log`，然后收掉进程。自检产生的 `data.db` 会被删掉，不会被打进 zip。
任何一项不过就返回非 0，`build.bat` 会停下来 `pause`。

自检启动单文件版时，`TEMP` 会优先指到仓库内的 `build\tmptest`：DSH 沙箱这类环境里
`%TEMP%` 允许普通写入，但 bootloader 在里面解包仍会直接弹 `Error`，用仓库内目录更可靠。
自己机器上想换目录：`set MAILBOX_VERIFY_TEMP=D:\tmp`。

## 6. 排错清单

### 6.1 `Error: Could not create temporary directory!`（只影响单文件版）

单文件版启动时必须在可写目录里建一个 `_MEIxxxx` 目录解包；目录版根本不解包。
实测到两种成因：

**a) 目标目录不可写**（`%TEMP%` 被策略/安全软件限制）。换 `TEMP` 或把解包路径钉死：

```bash
set TEMP=D:\temp
python build.py --onefile --runtime-tmpdir "D:\mailbox-tmp"
```

**b) 产物带 Low 完整性标签**（本项目实际踩到的那个）。如果构建目录本身是低完整性
（沙箱、受限目录、Windows 沙盒容器），PyInstaller 生成的 exe 会继承
`Mandatory Label\Low Mandatory Level`。这种 exe 即使从资源管理器双击，进程也只能以低完整性
运行，bootloader 建解包目录被拒 → 弹这个框。症状是**同一份 exe 换到别处就能跑**。查一下：

```bat
icacls dist\邮箱管理工具.exe | findstr Mandatory
```

出现 `Low Mandatory Level` 就是它。两种修法：

- 把 exe **复制**到普通用户目录（如 `%USERPROFILE%\Desktop`）——复制会丢掉标签，最省事；
- 或用管理员身份执行 `icacls dist\邮箱管理工具.exe /setintegritylevel Medium`。

`build.py` 打包完成后会自动 `icacls` 检查一次，命中就打印这条警告。目录版不受该标签影响
（低完整性、中完整性启动都实测正常）。

### 6.1b `PermissionError: [WinError 5] ... _internal\libcrypto-3.dll`（重新打包时）

上一次自检/试运行留下的 `邮箱管理工具.exe` 还活着，DLL 被映射进进程，删不掉。
`build.py` 现在会先 `taskkill` 同名残留进程再动手；`verify_exe.py` 收尾时会确认进程真的退出
（`taskkill` 之后复查 `poll()`，兜底 `TerminateProcess`），没退干净就报错而不是静默放过。

真遇到了手工收尾：

```bat
taskkill /IM 邮箱管理工具.exe /T /F
```

### 6.2 杀软误报 / 首次启动慢
PyInstaller 自解压行为常被杀软启发式命中。对策：优先目录版；把 exe 加白名单；
对外分发可考虑代码签名（本机未做，见 §7）。

### 6.3 双击没反应
1. 用 `python build.py --console` 重打一个带控制台的版本，看 stderr；
2. 或看 exe 旁边的 `error.log`（`app.py` 的 excepthook 和 Tk 回调异常都会写进去）；
3. 最常见原因：打包用的解释器**没有 tkinter**（换成 3.15.1 那个）。

### 6.4 启动后是空库
说明 `data.db` 没在 exe 旁边。检查 `paths.data_dir()` 实际落在哪 —— 若 exe 放在只读目录，
会被重定向到 `%APPDATA%\mailbox-gui\`。想固定就设 `MAILBOX_DB`。

### 6.5 图标没变
Windows 会缓存图标。改完 `app.ico` 重新打包后，换个文件名或重启资源管理器再看。

### 6.6 打包机 / 目标机差异
- exe 与 Python 位数绑定（本机 64 位）；32 位机器跑不了。
- 打包机必须是**有 tkinter 的同一个大版本**；想换 Python 版本就换解释器重打。
- 目标机不需要 Python、不需要 VC 运行库。

### 6.7 中文 exe 名 / 中文路径
已验证可用。唯一注意：批处理里带中文时记得 `chcp 65001`（`build.bat` 已加）。

---

## 7. 没做 / 不建议现在做的

| 方向 | 结论 |
|---|---|
| **Nuitka** | 本机**没有 MSVC/gcc**，Nuitka 编译不出 exe。要用得先装 Visual Studio Build Tools（数 GB） |
| 代码签名 | 需要证书；不做的话 SmartScreen 首次运行会提示「未知发布者」 |
| 安装包（Inno Setup / MSIX） | 目前「绿色便携 + 拷 data.db」已够用；上了安装包反而要处理卸载时的数据保留 |
| 单文件 + 自解压到固定目录 | 可用 `--runtime-tmpdir` 折中，但会留下残留目录，收益不大 |
| 用 `start.vbs` 启动 | 那是源码运行方式（写死本机 `pythonw.exe`），打包后直接双击 exe，不再需要它 |

---

## 8. 重新生成图标

```bash
python tools/make_icon.py        # 覆盖 app.ico，纯标准库，不需要 Pillow
python build.py --zip           # 重新打包把新图标嵌进 exe
```

`app.ico` 含 16/24/32/48/64/128/256 七个尺寸，PowerShell/资源管理器/任务栏都能取到合适的一档。
