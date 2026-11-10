# 邮箱管理工具 · mailbox-gui

> **交接文档**。本文面向接手本项目的 AI Agent / 开发者：先读 §0–§3，再按需要查后面各节。
> 最后更新：2026-11-11（新增「打包成可运行 exe」能力，细节见 [BUILD.md](BUILD.md)）

---

## 0. 三十秒现状

| 项 | 值 |
|---|---|
| 位置 | 源码 `G:\AI_All\WorkBuddyDefaultDirectory\mailbox-gui`；含 git 的开发副本 `G:\AI_All\DSHWork\mailbox-gui` |
| 形态 | Windows 桌面应用，Tkinter + SQLite，**纯标准库，零 pip 依赖**（打包时才用 PyInstaller） |
| 入口 | 打包后双击 `邮箱管理工具.exe`；源码方式双击 `start.vbs` 或 `python app.py` |
| 打包 | `python build.py --both --verify --zip` → `dist\`（打完自动起窗口自检），详见 **[BUILD.md](BUILD.md)** |
| 代码量 | 13 个 `.py`，约 2 700 行 |
| 数据 | `data.db`，当前 **1010 个账号 / 1045 条令牌历史 / 约 4.7 MB** |
| 状态 | 功能完整可用；无已知阻塞性 bug |
| 主要风险 | `data.db` 里是**明文密码和令牌**；令牌兑换即轮换，同一账号不能两处同时用 |

**项目目标**：把一批邮箱账号（从商家买来的 `邮箱----密码----clientid----令牌----辅助邮箱----辅助密码` 格式）导入本地库，按需查看某个邮箱的最新邮件，批量保活令牌，按需导出。

**明确不做的**（设计边界，不要擅自加）：

- 不做后台自动轮询所有账号
- 不做验证码自动识别 / 自动填充到第三方站点
- 取件一律**手动点按钮触发**，不在启动时自动取

---

## 1. 环境与启动

### Python 解释器（踩过坑）

```bash
# ✅ 用这个（3.15.1，带 tkinter）
C:\Users\Ryan\AppData\Local\Python\pythoncore-3.15-64\python.exe
# 或 PATH 里的 python（本机指向 3.15.1）

# ❌ 不要用 workbuddy 内置的 3.13.12，它没有 tkinter
C:\Users\Ryan\.workbuddy\binaries\python\versions\3.13.12\python.exe
```

`start.vbs` 里写死了 `C:\Users\Ryan\AppData\Local\Python\bin\pythonw.exe`。换机器必须改这一行。

检查方法：

```bash
python -c "import tkinter; print('ok')"
```

### 启动

```bash
cd G:\AI_All\WorkBuddyDefaultDirectory\mailbox-gui
python app.py
```

首次启动自动建库（`store.init_db()`，含幂等迁移 `_migrate()`）。

已经打包成 exe 的话不用装 Python：双击 `dist\邮箱管理工具\邮箱管理工具.exe`（目录版）
或 `dist\邮箱管理工具.exe`（单文件版）。重新打包见 **[BUILD.md](BUILD.md)**。

> **重要**：改完代码必须关掉旧窗口再开。Python 进程不会热加载，用户多次因为没重启而以为改动没生效。

---

## 2. 文件地图

| 文件 | 行数 | 职责 |
|---|---:|---|
| `app.py` | 833 | 主窗口：工具栏、账号表（勾选/批量）、邮件列表、正文、缓存、线程调度 |
| `mail.py` | 277 | 兑换令牌、IMAP 连接/主机回退、MIME 解析 |
| `store.py` | 280 | SQLite schema、迁移、增删改查、令牌历史、到期统计 |
| `importer.py` | 136 | 导入的纯函数：编码嗅探、分隔符、字段猜测、必填校验 |
| `import_dialog.py` | 190 | 导入对话框（粘贴 / 选文件 / 字段映射 / 预览） |
| `exporter.py` | 48 | 导出拼行、分隔符冲突检查 |
| `export_dialog.py` | 150 | 导出对话框（选列 / 分隔符 / 范围 / 预览） |
| `sync_dialog.py` | 239 | 令牌同步独立窗口（线程池 + 进度 + 结果表） |
| `view_db.py` | 110 | 命令行查看数据库、CSV 导出、历史查询 |
| `ui_util.py` | 49 | `center()` + `CenteredToplevel` 基类 |
| `start.vbs` | 27 | 无终端启动（**源码方式**；打包后直接双击 exe 即可） |
| `paths.py` | 82 | 冻结感知的路径：exe 目录 / `_MEIPASS` / 数据目录 / `data.db` / `error.log` |
| `build.py` | 195 | 打包脚本：目录版 / 单文件 / zip / 自检，自动准备 `.venv-build` |
| `build.bat` | 14 | 双击打包 |
| `verify_exe.py` | 129 | 打包后自检：起窗口 → 查 `data.db` / `error.log` → 确认进程退出 |
| `tools/make_icon.py` | 116 | 纯标准库生成 `app.ico`（7 个尺寸） |
| `app.ico` | — | 图标：嵌进 exe 资源，同时作为窗口图标 |
| `data.db` | — | 运行时数据库（**不要提交 git**） |

### 分层原则

```
界面层    app.py / *_dialog.py
            ↓ 调用
业务层    mail.py（网络+解析）   importer.py / exporter.py（纯函数）
            ↓ 调用
存储层    store.py
```

`importer.py` / `exporter.py` 是**纯函数**，不依赖 tkinter，可以单独写脚本测试。
`mail.py` 不含任何界面代码，`fetch_latest()` 是取件唯一入口。

---

## 3. 数据模型

### `accounts`

| 字段 | 含义 |
|---|---|
| `id` | 主键 |
| `email` | 登录邮箱，**查重时不区分大小写** |
| `password` | 邮箱密码 |
| `client_id` | OAuth 应用 ID（必须与签发令牌时一致） |
| `refresh_token` | 当前有效的刷新令牌 |
| `recovery_email` / `recovery_password` | 辅助邮箱及密码 |
| `group_name` | 预留，未使用 |
| `note` | 备注，可双击编辑，搜索会匹配 |
| `status` | `未取件` / `成功` / `失败` / `令牌失效` |
| `last_error` | 最近一次失败原因 |
| `last_fetch_at` | 最近取件时间 |
| `token_updated_at` | **最近一次令牌兑换时间**（取件和同步都会更新） |
| `access_token` / `access_expires_at` | 短期凭证缓存，约 60 分钟 |
| `imap_host` | 上次连上的 IMAP 主机，下次优先用 |

### `token_history`

| 字段 | 含义 |
|---|---|
| `id` | 主键 |
| `account_id` | 关联 `accounts.id` |
| `refresh_token` | **被替换掉的那个旧令牌**（不是当前值） |
| `source` | `fetch`（取件）/ `sync`（同步）/ `import-overwrite`（导入覆盖） |
| `changed_at` | 替换时间 |

每个账号**只保留最近 20 条**（`record_history` 内截断），防止长期运行无限膨胀。

索引：`idx_accounts_email`、`idx_history_account`。老库缺字段时由 `_migrate()` 自动补。

---

## 4. 令牌生命周期（最容易踩坑）

### 规则

1. 微软 refresh token 是 **90 天滑动窗口**，每次兑换重新计时
2. **兑换一次就轮换**：服务端返回新的 `refresh_token`，旧的可能短时间还能用，但**不能依赖**
3. 因此**同一个账号不能在主界面取件和同步窗口同时跑**，两边会互相顶掉
4. 兑换成功后必须**立刻写库**（`store.update_token`），这是唯一会造成断链的地方

### 代码路径

```
app._ensure_access(acc)
  ├─ access_token 剩余 > 60 秒 → 直接复用，不碰 refresh token
  └─ 否则 mail.exchange_token() → store.update_token(...)
                                    ├─ 旧令牌写 token_history
                                    └─ 更新 refresh_token / access_token / token_updated_at
```

`store.update_token(..., source=...)` 的 `source` 参数区分取件与同步。

### 到期提醒

```
剩余天数 = store.EXPIRY_DAYS(90) − (今天 − token_updated_at)
```

`store.expiry_stats()` 用 SQL 取全部账号里**最小**的那个，返回 `(剩余天数, 邮箱, 无记录账号数)`。

工具栏「同步令牌」右边显示，配色：>30 天灰 / 15–30 黄 / <15 红 / <0 深红。
启动 800 ms 后若 ≤30 天，状态栏提一次（不弹窗）。

账号表行色另按 `token_updated_at` 距今 60–80 天标黄、≥80 天标红。

---

## 5. 核心流程

### 5.1 导入

`ImportDialog` → `importer` 纯函数 → `store.upsert_accounts()`

- 支持**直接粘贴**或选文件；粘贴后 150 ms 自动解析
- 分隔符 `----` / Tab / `|` / `;` / `,` / `:` 自动嗅探
- 字段猜测顺序：GUID→`client_id`；长度 >200 或 `M.C` 开头→`refresh_token`；含 `@`→第一个 `email`、第二个 `recovery_email`；剩余列按顺序给 `password` / `recovery_password`
- **必填四项**：`email` / `password` / `client_id` / `refresh_token`，缺任一行跳过并统计
- 去重 `LOWER(email)=LOWER(?)`，大小写不同不会新增重复行
- **默认只补空**：已有非空字段不被导入文件覆盖（防止旧文件里的失效令牌冲掉新令牌）；勾「覆盖已存在的字段」才强制覆盖，旧值进 history

返回统计：`{"added","filled","overwritten","kept"}`。

### 5.2 单账号取件

```
选中账号 → 选 1/3/5/10 封（默认 1）→ 点「获取邮件」
```

`app._fetch_worker`（子线程）：

1. `_ensure_access()` 拿 access token
2. `mail.fetch_latest(email, access, limit, preferred_host)` → `(items, host)`
3. 新主机写 `imap_host`；状态写 `成功`；结果存 `self.mail_cache[acc_id]`
4. 结果通过 `queue` 回主线程，`_poll_queue()`（100 ms 轮询）刷新 UI

`mail.fetch_latest()` 内部：

- 主机顺序 `["outlook.office365.com", "outlook.live.com"]`，`preferred_host` 优先；**连接/TLS 失败才切换，`AuthFailed` 直接抛出不换主机**
- `LIST` 兼容带引号和不带引号两种文件夹名；`pick_folder()` 把 `INBOX`→`Inbox`、`Junk Email`→`Junk`
- 同时读 `INBOX` 和 `Junk Email`，跨文件夹按时间倒序合并
- 每封返回 `subject / from / to / date / ts / text / html / folder / uid`
- `text` = 去标签正文（优先 plain，否则剥 `<style>/<script>` + `html.unescape`）；`html` = 原始 HTML 原封不动

**缓存**：`self.mail_cache` 在内存里，**无 TTL，关程序即清空**。切回取过的账号显示 `· 缓存 23:12`，要看新邮件再点一次按钮。

### 5.3 批量取件

- 账号表首列 `☐/☑`；点该列切换，**Shift+点任意列可整段勾选**（`_range_check`）
- 「全选」= 当前列表全部；配合搜索框 = 筛选结果
- 工具栏实时显示 `已选 N 个 · 约 X 分钟`（按 `N*10/并发/60` 估算，>200 变红）
- `ThreadPoolExecutor(max_workers=并发)`，可选 1–8，默认 3
- 每个账号一条独立 IMAP 连接，**取完立即 `logout()`，没有长连接**；并发数 = 同时连接数
- 进度通过 `("progress", ...)` 回传，状态栏 `批量取件 3/12　失败 0`；结束 `("batch_done", ...)`
- 超过 50 个先弹窗确认预估耗时；建议单批 ≤200（1000 个约 55 分钟且会被限流）

### 5.4 令牌同步（P3）

工具栏「同步令牌」→ `SyncDialog`（模态独立窗口）：

- 范围 = 打开时主界面当前列表
- 并发 1–5，默认 3；可中途停止（未开始的标「已跳过」）
- 每个账号 `mail.exchange_token` → `store.update_token(source="sync")`
- 失败把 `status` 置为 `令牌失效`，结果表显示原因和耗时
- 顶部横幅：`最快 N 天后到期（email） · N 个账号还没同步过`
- 主界面正在取件时会提示先等结束，避免同号互顶

### 5.5 导出

工具栏独立按钮 → `ExportDialog`：

- 列：邮箱 / 密码 / Client ID / 令牌 / 辅助邮箱 / 辅助密码 / 备注，任选
- 分隔符：`----` 或 `:`
- 范围：当前列表全部 / 仅选中一条
- 前 3 行预览；字段值含分隔符时警告
- UTF-8 + CRLF，输出 `.txt`
- **导出的是库里最新令牌，且完全不脱敏**（别外发）

### 5.6 查看数据库

```bash
python view_db.py                         # 概览，令牌打码
python view_db.py -q Amina                # 按邮箱或备注过滤
python view_db.py --full                  # 全部字段，明文
python view_db.py --csv out.csv           # CSV（UTF-8 BOM，Excel 可开），完整值
python view_db.py --history xxx@hotmail.com   # 令牌变更历史（大小写不敏感 + 模糊匹配）
```

本机**没有 sqlite3 命令行**，所以用这个脚本。也可装 DB Browser for SQLite 或 VS Code 的 SQLite Viewer 插件。

---

## 6. 界面与交互约定

### 布局

```
┌ 工具栏：[导入] [取件 1|3|5|10] [获取邮件] [导出…] [同步令牌] 最近到期 90 天 │ 搜索
├ 账号（LabelFrame，分组标题含账号数）
│   [☐ 全选] [已选 N 个 · 约 X 分钟] [批量取件] [并发 3]        [滚动条]
│   选 | # | 邮箱 | 密码 | 辅助邮箱 | 辅助密码 | 状态 | 令牌更新 | 备注
├ 邮件 最近 1 封 │ 2026-11-09 17:22:24                    [查看原文]
│   ┌ 两行一条 ┐ │ ┌────────────────────────────────────┐
│   │ 主题      │ │ │ 正文（去标签）                      │
│   │ 时间·发件 │ │ │                                    │
│   └──────────┘ │ └────────────────────────────────────┘
└ 状态栏
```

### 交互表

| 操作 | 结果 |
|---|---|
| 单击账号表行 | 选中账号；若本次会话取过件，直接显示缓存 |
| 双击 邮箱/密码/辅助邮箱/辅助密码 | 复制到剪贴板 + 鼠标旁 toast + 状态栏提示 |
| 双击备注列 | 就地编辑（回车保存 / Esc 取消） |
| 双击其他列 | 取件 |
| 单击勾选列 | 切换勾选 |
| Shift + 单击任意列 | 从锚点到该行整段勾选 |
| 单击邮件条目 | 高亮 + 右侧正文切换 |
| 未取件时 | 顶栏隐藏，正文区居中提示；不显示多余输入框 |

### 给后续 Agent 的硬约定

1. **主体 + 滚动条一律用 `grid`，不要用 `pack` + `expand`**。本项目三次出现「控件被挤成 1px」（查看原文按钮、状态栏、账号表滚动条），根因都是 pack 顺序。
2. **固定在底部的元素**（状态栏、按钮条）要 `side="bottom"` 且**先 pack**。
3. **新弹窗一律居中**：继承 `CenteredToplevel(master, w, h)`，或 `__init__` 末尾调 `center(self, master, w, h)`。不要写死坐标。
4. **Tk Text 选中高亮不能用内置 tag `sel`**（失焦时 `inactiveselectbackground` 透明，不上色），必须用自定义 tag（当前用 `hl`，色 `#cfe4fb`）。
5. **Windows 滚轮事件发给焦点控件**，不是光标下控件。已有 `bind_all("<MouseWheel>", _on_wheel_global)` 按 `winfo_containing` 分发，新增可滚动控件要加进白名单。
6. **列索引用常量**：`app.py` 顶部 `COL_CHK … COL_NOTE`，改列顺序只改那里。
7. **邮件列表用 Text 自绘两行条目**（Treeview 不支持单元格换行），`_mail_spans` 存每条起止 index，点击靠 `compare()` 命中。
8. **线程安全**：网络任务在 `ThreadPoolExecutor` / `threading.Thread`，结果一律走 `self.queue` + `root.after(100, _poll_queue)`，子线程不得碰 widget。`store` 每次调用开独立 sqlite 连接。

---

## 7. 性能基线（真实测量）

单账号取 1 封，合计约 **16 秒**：

| 环节 | 耗时 |
|---|---|
| 兑换 access token | 6.07 s |
| IMAP 连接 + 认证 | 7.16 s |
| LIST / SELECT / UID SEARCH | 各 ≈0.5 s |
| FETCH 1 封（13 KB） | 1.33 s |
| 本地解析 | 0.003 s |

底层：TCP 0.03 s、**TLS 握手 1.8 s**、**token 接口 RTT 3.16 s**。

**结论：82% 时间是跨境网络等待，不是代码瓶颈。** 已做的优化：access token 复用（省 6 s）、主机回退、缓存。想质变只能走代理或换线路。

`P2 连接复用` 评估过但**未实现**：风险为连接空闲被踢（捕获重连）、会话状态串号（每次强制 SELECT）、句柄泄漏（切号即关）。收益是每次省 2–7 s。

---

## 8. 已知限制 / 风险

- `data.db` 明文凭证，**不要提交 git、不要放共享盘**（仓库已加 `.gitignore` 忽略它和 `dist/`、`build/`）
- 单文件 exe 启动要解包到 `%TEMP%`：受限权限或杀软环境下会失败，优先用目录版
- 未做代码签名，别人首次运行单文件 exe 可能有 SmartScreen 提示
- 分组功能未做（`group_name` 字段预留）；只有「全部」+ 搜索
- 正文是纯文本，窗口内不渲染 HTML（「查看原文」交给系统浏览器）
- 导入按固定分隔符切分，不支持带引号 CSV（密码里含逗号会切错）
- 缓存无 TTL、不落盘，关程序即失
- 同一账号不可两处同时用（取件 vs 同步 vs 外部脚本），否则令牌互顶
- 从商家导入的号原本没有 `token_updated_at`，到期时间未知；**第一次同步建立基线**
- `start.vbs` 硬编码了本机 pythonw 路径
- 批量取件一次上千个会被限流，建议 ≤200

---

## 9. 修改后怎么验证

```bash
PY="C:/Users/Ryan/AppData/Local/Python/pythoncore-3.15-64/python.exe"

# 1) 全量语法检查
$PY -m py_compile app.py mail.py store.py importer.py exporter.py \
     import_dialog.py export_dialog.py sync_dialog.py view_db.py ui_util.py

# 2) 纯函数测试（不联网）
$PY -c "
import importer, exporter
print(importer.detect_separator(['a----b','c----d']))
print(exporter.build_lines([{'email':'a@b.com'}], ['email'], '----'))
"

# 3) 窗口冒烟测试（会短暂创建窗口后销毁）
$PY -c "
import app
w = app.App(); w.update()
print(w.title(), w.winfo_width(), w.winfo_height())
w.destroy()
"

# 4) 打包 + 打包后自检（会短暂起窗口再关掉）
$PY build.py --both --verify --zip      # 打包 + 自检（推荐）
$PY verify_exe.py                       # 单独自检目录版
$PY verify_exe.py 邮箱管理工具.exe      # 单独自检单文件版
```

**不要**在验证时直接调用真实 `exchange_token`——每次都会轮换令牌，必须把新令牌写回 `data.db`，否则账号断链。确需联网测试时，参考 `store.update_token(...)` 立即落库。

清理临时文件：`__pycache__` 可随时删除，不影响运行。

---

## 10. 版本沿革（便于理解设计取舍）

| 阶段 | 内容 |
|---|---|
| 基础 | 导入 + 字段映射 + 账号表 + SQLite |
| 单账号取件 | IMAP XOAUTH2、正文/原文双视图、令牌写库 |
| 导出 | 选列 / 分隔符 / 范围 / 预览 |
| 数据安全 | 导入默认只补空、令牌历史、大小写去重、必填校验 |
| UI 打磨 | 两行邮件列表、右侧只放正文、滚动条、双击复制、滚轮跟随光标 |
| P0 | IMAP 主机回退 + 记住成功主机、当前邮箱显示（后因冗余移除） |
| P1 | 账号勾选 + Shift 范围 + 批量并发取件 + 耗时预估 |
| P2 | 评估连接复用，**未实现** |
| P3 | 独立令牌同步窗口、过期标色与提醒、90 天到期模型、`source` 区分 |
| 收尾 | 三个对话框统一居中 + `CenteredToplevel` 基类 |
| 打包 | PyInstaller 目录版/单文件版、`paths.py` 冻结路径、图标、`error.log`、`--verify` 自检（[BUILD.md](BUILD.md)） |

被明确否决/移除的功能：按条件选菜单、邮件区重复展示邮箱、自动轮询、验证码自动识别。

---

## 11. 修改前请先确认的事

下面几条是**产品决策**，不是实现细节，改之前要和用户确认：

1. 保持「手动触发取件」，不要加后台自动轮询
2. 保持「导入默认不覆盖已有令牌」
3. 保持「导出不脱敏」（这是刻意选择，方便用户拿去用）
4. 保持「同步令牌」为独立模态窗口，不要塞进主界面
5. 保持「取件与同步互斥」，避免同一账号两处轮换

技术层面可自由改进：连接复用（P2）、缓存 TTL、并发上限调优、界面美化。
