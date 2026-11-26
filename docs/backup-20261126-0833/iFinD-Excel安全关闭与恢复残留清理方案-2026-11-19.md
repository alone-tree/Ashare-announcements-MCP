# iFinD Excel 安全关闭与恢复残留清理方案（2026-11-19）

## 问题

1. AI 主动关闭：`engine.close_excel()` 已实现不保存关闭（`book.Close(SaveChanges=False)`），但 CLI 只有 lookup/run/text，未暴露 close。
2. 强制关闭（强杀 DSH 或 EXCEL.EXE）：下次打开弹「文档恢复」面板，需手动点关闭+不保存。
3. 目标：不引入常驻进程；优雅关闭永不保存；强杀残留在下一次打开时自动清除。

## 实测结论（2026-11-19，本机专用工作簿）

- 场景A 无改动优雅关闭：磁盘 SHA 不变，锁文件随 Close 消失，进程数秒内自行退出；偶发假超时（iFinD 弹窗阻塞 worker 进程），关闭动作本身已完成。（一次带弹窗的异常退出曾把 Excel 内存态泄漏落盘——用户手工删除的非 data 页随之外泄；正常关闭路径无此现象，工作簿已按纯通道定位收敛为单 data 页。）
- 场景B 写入脏数据后优雅关闭：磁盘 SHA 前后一致（1b68fbe3…），数据从未落盘，SaveChanges=False 确认有效。
- 场景C 脏开超过 1 分钟（触发自动保存）后强杀：磁盘 SHA 仍不变；产生两类残留：
  - 注册表 `HKCU\Software\Microsoft\Office\16.0\Excel\Resiliency\DocumentRecovery` 下引用 ifind_workspace 的记录（面板数据源，实测现存 2989D8B6、298B21B1 两条）；
  - `%APPDATA%\Microsoft\Excel\ifind_workspace*` 目录（Autorecovered/Unsaved 副本，实测现存 4 个；副本文件带 Windows 只读属性，删除前须先解除，实测踩坑）。
- 「文档恢复」面板是主窗口内部任务面板，非独立窗口，无 COM API 可关；Excel 启动时按注册表记录决定是否弹出，记录不存在则面板不出现。

## 方案（兜底，无常驻进程）

1. engine.py 新增 `_cleanup_recovery()`，仅在 `_execute` 启动 Excel 分支（Popen 前）调用一次：
   - 枚举 DocumentRecovery 子键，任一值按 utf-16le 解码后含 "ifind_workspace" 即删除整个子键；
   - 删除被删子键值内引用的 `~ar*.xar` 文件（仅限位于 %APPDATA%\Microsoft\Excel 且被 ifind 记录引用的，防止孤儿积累）；
   - 删除 `%APPDATA%\Microsoft\Excel\ifind_workspace*` 目录。
   - 明确不动：其他工作簿的恢复记录（PERSONAL.XLSB、用户自己的文件）、DisabledItems、磁盘上的正式工作簿、未引用 ifind 的其他 xar。
2. cli.py 增加 close 命令：`{"cmd":"close"}` 调 `engine.close_excel()`，AI 可主动优雅关闭。
3. 文档同步（一句话级别）：包 README（close 用法与兜底行为）、AGENTS.md（三命令改四命令）、docs/决策记录.md（变动历史一条）。

## 验证

- 端到端：打开 → 写脏 → 等 70 秒触发自动保存 → taskkill 强杀 → 确认注册表与目录残留 → open_excel → 确认残留被自动清除、工作簿正常打开、磁盘 SHA 不变。
- CLI close：stdin JSON 实测返回 quit_excel=true，进程随后退出。

## 影响面

- engine.py 约 +30 行（一个函数 + 启动分支一行调用）；cli.py 约 +6 行；文档三处各一句。
- 不改 fetch/open/close 现有行为，不动公式库与数据。