# Changelog — 开发纪事

---

## 2026-11-09（第十五轮）— 员工实时日志

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/app.py` | 新增每员工事件环形日志（`agent.say` / `agent.tool_call` / `agent.state` / `bus.event`），新增 `GET /api/agents/{id}/log` |
| `botoffice/gui/main_window.py` / `i18n.py` | Chat 页签下方新增 **Live log** 面板：点员工即加载他最近的事件 |
| `scripts/verify/employee.test.py` | 新增：员工日志有内容且带文本 |

### 为什么改

用户要求补 munder-difflin 的「点员工看终端」。真正的 PTY 终端需要自己启动 CLI 并抓 stdout（node-pty 那种），
这一轮先做**实用版**：实时事件日志。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED（含日志） |
| `scripts/verify/backend.test.py` / `bus.test.py` | ALL CHECKS PASSED |

### 未验证 / 未做

- 真正的 PTY 终端（启动 CLI、转发输入输出）尚未实现。

---

## 2026-11-09（第十四轮）— 收件箱

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/orchestrator/inbox.py` | **新增**：订阅 `agent.say` / `task.assigned` / `handoff.done`，留存消息并记未读 |
| `botoffice/app.py` | 新增 `GET /api/inbox`、`POST /api/inbox/read` |
| `botoffice/gui/main_window.py` / `i18n.py` | 新增 **Inbox 页签**，标题显示未读数，带「Mark all read」 |
| `scripts/verify/employee.test.py` | 新增：收件箱有消息、初始未读、全部已读后清零 |

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED（含收件箱） |
| `scripts/verify/backend.test.py` / `bus.test.py` | ALL CHECKS PASSED |

---

## 2026-11-09（第十三轮）— 审批队列

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/orchestrator/approvals.py` | **新增**：`ApprovalQueue`，订阅 `bus.event` 的 `permission_request` 与 `approval.request`，生成待办 |
| `botoffice/external/ingest.py` | `bus.event` 补上员工 id，审批能对应到人 |
| `botoffice/app.py` | 新增 `GET /api/approvals`、`POST /api/approvals/{id}` |
| `botoffice/gui/main_window.py` / `i18n.py` | 新增 **Approvals 页签**：列出待办，Approve / Reject 两个按钮 |
| `scripts/verify/bus.test.py` | 新增：权限请求 → 待办 → 批准 → 队列清空 |

### 为什么改

用户要求补齐 munder-difflin 的 `ask me` 能力：外部 CLI 请求权限时，办公室要停下来等人决定。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/bus.test.py` | ALL CHECKS PASSED（含审批流程） |
| `scripts/verify/backend.test.py` / `employee.test.py` | ALL CHECKS PASSED |

### 未验证

- 没有接真实 Claude Code 的权限请求端到端跑过。

---

## 2026-11-08（第十二轮）— 固定平面图 + 柔和 2.5D

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/orchestrator/office.py` | 改为**固定平面图**：会议室在上、办公区两排工位在中间、老板办公室左下、休息区右下、茶水间右上、大门在下 |
| `botoffice/gui/scene.py` | 场景按 `landmarks.zones` 绘制；会议室加玻璃墙；新增大门；阴影改为叠层柔化；家具顶面加渐变；整体加一层暖环境光 |
| `botoffice/orchestrator/tasks.py` | 派活改为走到 **Lead 的工位**（Lead 是同事不是房间） |
| 测试 | 工位坐标与派活目标同步更新 |

### 为什么改

用户给出明确的平面图：左下 boss、下方大门、右下休息区、右上茶水间、中间两排工位、上方会议室（玻璃墙隔离），画风走柔和 2.5D。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `backend` / `employee` / `bus` 三个测试 | ALL CHECKS PASSED |
| 演示截图 | `docs/office-demo.png` |

### 未验证 / 已知差距

- **手绘质感做不到**：参考图是手绘插画（笔触、材质、光影），QPainter 只能做柔和矢量，
  要那种质感必须上图片素材或 3D 渲染。
- 分区比例与位置还需要按截图微调。

---

## 2026-11-08（第十一轮）— 团队工作目录

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/orchestrator/teams.py` | **新增**：`TeamRegistry`，团队与工作目录存在 `config/teams.json` |
| `botoffice/app.py` | 新增 `GET/POST /api/teams`；新增 `registry_for(team)`：每个团队一套工具，文件工具绑定到该团队目录 |
| `botoffice/agent/runtime.py` | 运行时按员工所属团队解析工具集，调用点不用改 |
| `botoffice/gui/main_window.py` / `i18n.py` | 新增 **Teams 页签**：查看团队、选目录（Browse）、保存 |
| `scripts/verify/employee.test.py` | 新增：团队工作目录保存后，该团队能读到自己目录里的文件，且与别的团队工具集隔离 |

### 为什么改

用户问「开始第一个 conversation 时它怎么知道我的项目路径，有设置的地方么」——
之前确实没有，文件工具固定用项目下的 `workspace/`。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED（含跨团队目录隔离） |
| `scripts/verify/backend.test.py` / `bus.test.py` | ALL CHECKS PASSED |

---

## 2026-11-08（第十轮）— waiting 状态

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/agent/state_machine.py` | 新增 `WAITING` 状态与合法转移 |
| `botoffice/external/ingest.py` | `permission_request` 映射为 `waiting`（被审批卡住，不是「在聊天」） |
| `botoffice/gui/scene.py` | 新增黄色状态点与图例项 |
| `botoffice/gui/main_window.py` / `i18n.py` | 员工计数增加 Waiting |
| `scripts/verify/bus.test.py` | 新增：审批请求 → waiting |

### 为什么改

用户希望「空闲」和「等着你」能一眼区分，对应 munder-difflin 里的 waiting。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/bus.test.py` | ALL CHECKS PASSED |
| `scripts/verify/backend.test.py` / `employee.test.py` | ALL CHECKS PASSED |

---

## 2026-11-08（第九轮）— 会话结束不等于离职

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/external/ingest.py` | `session_end` 不再把员工置为 `offline`，而是回到 `idle`：**人还在办公室，等下一次派活** |
| `scripts/verify/bus.test.py` | 改为断言「会话结束后员工仍在，状态为 idle」 |
| `docs/rules.md` | 同步事件映射说明 |

### 为什么改

用户指出：外部 Agent 的会话结束只是这一次干完了，人和工位都应该保留。
测试用的 Agent 可能只在有测试任务时工作，UI 机器人只在涉及 UI 时工作，其余时间就是空闲等待。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/bus.test.py` | ALL CHECKS PASSED（含「员工仍在」断言） |

### 未验证

- 没有真实 Claude Code 会话端到端跑过（钩子尚未写入用户配置）。

---

## 2026-11-08（第八轮）— 多团队 / 多办公室

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/orchestrator/roles.py` | 员工新增 `team` 字段，默认 `general` |
| `botoffice/orchestrator/office.py` | **新增 `OfficeManager`**：每个团队一个独立 `Office`（各自的工位、边界、地标） |
| `botoffice/orchestrator/tasks.py` | 走位改为按员工所属团队取办公室，交接/开聊的目标工位也取对应团队 |
| `botoffice/app.py` | `GET /api/status?team=` 按团队过滤员工并返回该团队布局；返回 `teams` 列表；删除员工时归还到其团队 |
| `botoffice/gui/main_window.py` | 工具栏新增**团队下拉框**；「新建对话」增加 Team 字段 |
| `scripts/verify/employee.test.py` | 新增：两个团队各自独立、新团队从第一个工位开始、团队列表正确 |

### 为什么改

用户要求 C 项：多个团队，每个团队一个办公室，点选团队切换展示。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED（含团队隔离） |
| `scripts/verify/bus.test.py` | ALL CHECKS PASSED |
| 演示脚本 | exit=0，工具栏出现团队下拉框 |

### 未验证

- 多楼层（同一团队分楼层）尚未实现；目前是「多团队 = 多办公室」。
- 没有在真实窗口里手动切换团队验证。

---

## 2026-11-08（第七轮）— 点员工对话

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/app.py` | 新增 `POST /api/agents/{id}/say`：给员工发一句话并拿回回复；外部员工、Boss、没配模型的员工都会被拒绝并说明原因 |
| `botoffice/orchestrator/tasks.py` | 新增公开方法 `context_for()`，让聊天接口复用同一套记忆上下文 |
| `botoffice/gui/main_window.py` | 「Chat」页签改为可交互：**点办公室里的任意小人**即打开与他的对话，带输入框与发送按钮 |
| `botoffice/gui/i18n.py` | 新增聊天相关文案 |
| `scripts/verify/employee.test.py` | 新增：内部员工能回复、外部员工返回 400 |

### 为什么改

用户选择方案 A（保留 PySide6，移植 munder-difflin 的行为），B 项是「点员工打开他的终端/对话」。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED（含对话） |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `scripts/verify/bus.test.py` | ALL CHECKS PASSED |
| 演示脚本 | exit=0 |

### 未验证

- 没在真实窗口里手动点过小人验证 UI 交互（只验证了接口与窗口构建）。
- 外部 CLI 的对话尚未支持（它们由自己的 CLI 驱动）。

---

## 2026-11-08（第六轮）— Agent Bus：外部 CLI 接入

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/external/ingest.py` | **新增**：校验钩子 payload，把 `session_start / tool_use / task_complete / session_end / heartbeat / permission_request` 映射成办公室事件；首次见到某个 runtime 时自动创建外部员工并分配工位 |
| `botoffice/app.py` | 新增 `POST /api/bus/events`、`GET /api/bus/agents` |
| `scripts/hooks/botoffice-hook.py` | **新增**：读 stdin → POST 到 hub → 退出。200ms 超时、永远 exit 0、不写 stdout；把 CLI 的钩子名（如 `PostToolUse`）映射成我们的总线事件 |
| `botoffice/gui/app.py` / `server.py` | 启动时写 `data/hub.port`，钩子无需配置即可找到端口 |
| `scripts/verify/bus.test.py` | **新增**：覆盖事件映射、自动建员工、未知事件 400、钩子契约（不阻塞、不写 stdout、正确映射） |

### 为什么改

用户要求「继续 A：接 Claude Code 钩子」。这是让办公室真正跟着外部 CLI 动起来的第一步。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/bus.test.py` | ALL CHECKS PASSED（含钩子子进程测试） |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED |

### 未验证

- **还没有把钩子写进真实的 Claude Code 配置**（`~/.claude/settings.json`），需要用户授权。
- 没有在真实 Claude Code 会话里端到端跑过。

---

## 2026-11-08（第五轮）— 英文 UI、GrokBot 侧栏、体素小人、稳定性

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/gui/i18n.py` | **新增**：所有 UI 文案集中一处，当前英文，后续可加语言选择 |
| `botoffice/gui/main_window.py` | 整体英文化；右侧栏改为「员工列表 + 状态点 + 活动时间线」；新增「Hide/Show panel」折叠按钮；新增「+ Add Me」创建 Boss |
| `botoffice/gui/scene.py` | 小人改为方块体素风：不同肤色 / 四种发型 / 女性形象（裙子+长发+发饰）；按 runtime 着色工装（Claude Code 橙、Codex 白、OpenCode 黑、Gemini 蓝）；**子 Agent 头顶天线**；名牌改为「昵称-角色-模型缩写」置于头顶；分区地板（工作区/茶水区/休息区）；数字看板；垃圾桶/衣帽架/纸箱/茶几/单人沙发/海报 |
| `botoffice/orchestrator/roles.py` | 新增 `kind: user`（Boss 就是用户本人） |
| `botoffice/orchestrator/office.py` | Boss 站在老板办公室，不占员工工位；工位间距 3.5/3.0 |
| `botoffice/app.py` | 新增 `POST /api/boss`；「第一个员工成为 Lead」排除 Boss |
| `botoffice/llm/providers.py` | 新增 `short` 字段（名牌上的模型缩写，如 DSF） |
| `botoffice/gui/client.py` | **改为同步 HTTP**：多线程各自跑 asyncio + httpx 会偶发崩溃 |
| `botoffice/gui/app.py` | 启动时预加载 httpx 传输栈、关闭循环 GC、退出时 join 线程后 `os._exit` |
| `botoffice/gui/__main__.py` | **新增**：修复 `python -m botoffice.gui` 无法启动 |
| `BotOffice.bat` / `scripts/run.bat` | **新增**：Windows 双击启动 |
| `LICENSE` | **新增**：MIT |
| `.gitignore` | **新增** |

### 为什么改

用户要求：UI 用英文（以后再加语言选择）；侧栏照 GrokBot 做且可折叠；小人要方块体素风、有女有男；子 Agent 要有天线区分；办公室要有会议室/茶水间/数字看板；Windows 要双击启动；加 MIT 许可并推送到 `wjfriend/BotOffice`。

### 修复的真实 bug

1. **启动器一直不可用**：缺 `botoffice/gui/__main__.py`，`python -m botoffice.gui` 直接报错。
2. **进程偶发段错误**（约 5/6 概率）：GUI 在多个线程里各自 `asyncio.run` + httpx，CPython 3.14 下会崩溃。
   处理：客户端改同步 HTTP → 启动时预加载 httpx 传输栈 → 关闭循环 GC → 退出时 join 后 `os._exit`。
   **压力测试 8/8 次正常退出。**
3. **窗口绘制崩溃**：`QPainterPath` 裁剪 + 渐变画天空会偶发 access violation，改为按比例在墙面四边形内定位，不用裁剪。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED |
| 演示脚本连续 8 次 | 8/8 exit=0 |
| `BotOffice.bat` 双击 | 进程持续运行 |
| 推送到 GitHub | `wjfriend/BotOffice` main 分支成功 |

### 未验证

- 未在真实显示器上长时间观察帧率。
- 外部 CLI 仍未真正接入（只有登记）。
- 未按 munder-difflin 补齐终端/审批/收件箱等功能。

---

## 2026-11-08（第四轮）— 画风对齐 GrokBot + Windows 启动器

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/gui/scene.py` | 整体重画：木地板、落地窗（天空渐变 + 云 + 城市天际线）、每张工位下的**彩色地毯**、所有家具改为**不透明**实体（顶面 + 两个受光侧面） |
| `botoffice/gui/scene.py` | 新增 `_box()` 统一实体绘制；新增 `_shadow()` 接触阴影；`_draw_office_room()` 用实体浅蓝墙体替代半透明玻璃盒 |
| `botoffice/gui/__main__.py` | **新增**：`python -m botoffice.gui` 之前直接报 `No module named botoffice.gui.__main__` |
| `BotOffice.bat` | **新增**：项目根目录双击启动 |
| `scripts/run.bat` | **新增**：Windows 原生启动器（建 venv、装依赖、启动），支持 `--check` |
| `README.md` / `CLAUDE.md` / `docs/architecture.md` | 补充 Windows 启动方式 |

### 为什么改

用户反馈：

1. 家具是半透明的、画风差很多，截图 1（GrokBot）那种更好看，3D/2.5D 无所谓。
2. Windows 上 `bash scripts/run.sh` 报「没有已安装的 WSL 分发」，要能双击一键启动。

### 修复的真实 bug

1. **家具半透明**：旧 `_draw_box()` 对所有侧面调用 `setAlpha(90)`，导致冰箱、书架、吧台全部半透。新 `_box()` 用 `darker()` 做明暗，**完全不使用 alpha**（只有阴影用）。
2. **启动器根本跑不起来**：`botoffice/gui` 缺少 `__main__.py`，`python -m botoffice.gui` 直接失败。之前只验证了截图脚本 `demo_snapshot.py`，没验证真正的启动路径——这是上一轮汇报里「能跑」的说法不严谨。
3. **Windows 无启动器**：项目声明支持 Windows，却只提供 `.sh`。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED |
| `scripts\run.bat --check` | Setup OK |
| 双击 `BotOffice.bat`（实测） | 进程持续运行，窗口正常 |
| `python -m botoffice.gui`（实测） | 进程持续运行 |

### 未验证

- 没有在真实显示器上长时间观察 30fps 流畅度。
- 乐高风格没有采用：用户最终选择截图 1（GrokBot）那种观感。

---

## 2026-11-08（第三轮）— 场景与角色重画

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/gui/scene.py` | 木地板、窗户（带云）、白板、公告板、挂钟、茶水间（吧台/咖啡机/饮水机/冰箱）、沙发区（地毯/落地灯/边几）、书架（彩色书脊）、打印机、办公区地毯、圆桌会议室（带椅子）、桌上键盘/杯子/纸张 |
| `botoffice/gui/scene.py` | 角色改为更可爱的比例：大头、腮红、高光眼、眨眼、三种发型、眼镜、粉彩衣服、小短腿 |
| `botoffice/gui/scene.py` | 角色随房间缩放（`avatar_scale`），房间放大后小人不会显得像蚂蚁 |
| `botoffice/orchestrator/office.py` | 修复 `room_bounds()` 没算 Leader 办公室，导致玻璃办公室画在地板外面 |

### 为什么改

用户反馈：「小人太丑了，办公室太简陋了，pixtuoid 就很生动」。

参考 pixtuoid 的做法（**不复制其素材与代码**）：它的生动感来自完整的
生活化场景（茶水间、冰箱、饮水机、沙发、书架、白板、挂钟、宠物、植物）
加上像素级角色动作。本轮按同样思路用 QPainter 重新实现。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `scripts/verify/employee.test.py` | ALL CHECKS PASSED |
| `python scripts/demo_snapshot.py docs/office-demo.png` | 截图正常 |

### 未验证

- 没有在真实显示器上长时间观察动画流畅度（只做了截图与帧偏移稳定性检查）。
- 宠物（猫/狗）、日夜光照、外部景观尚未实现。

---

## 2026-11-08（第二轮）— 新建对话 / 看板 / 可爱化

### 改了什么

| 文件 | 变更 |
|---|---|
| `botoffice/orchestrator/board.py` | 新增：订阅事件总线，把任务投影成看板卡片 |
| `botoffice/orchestrator/roles.py` | 新增 `rank` 字段与 `can()` 权限判断；leader 与 rank 自动同步 |
| `botoffice/app.py` | 新增 `POST /api/employees`（新建对话，首个自动成为 Lead）、`GET /api/tasks`；`ctx.hire()` 统一入口 |
| `botoffice/gui/main_window.py` | 新增「新建对话」按钮与对话框（Agent 类型 / 平台 / 外观颜色）、「看板」页签 |
| `botoffice/gui/scene.py` | 小人改可爱比例（大头、腮红、高光眼、眨眼、粉彩衣）；状态色点；敲键盘动画；背景渐变；场景随房间缩放 |
| `botoffice/gui/app.py` | 事件流改走 Qt 信号回主线程，避免跨线程操作控件 |
| `scripts/verify/employee.test.py` | 新增：验证首个员工成为 Lead、外部 runtime、未知平台拒绝、看板接口 |
| `scripts/demo_snapshot.py` | 新增：开发用截图脚本 |

### 为什么改

1. 用户要求「在我这个 app 里新建对话然后选择 Claude Code，它就是第一个 agent / Lead」。
2. 用户想要「类似小游戏场景的虚拟 AI 办公室」，要有看板。
3. 用户反馈「动画一直闪烁」「没有那么可爱」。

### 如何验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `python scripts/verify/backend.test.py` | ALL CHECKS PASSED |
| `python scripts/verify/employee.test.py` | ALL CHECKS PASSED |
| `python scripts/demo_snapshot.py docs/office-demo.png` | 截图正常，小人/气泡/看板都在 |

### 修复的真实 bug

`OfficeScene.center_on()` 原来用「带旧偏移的屏幕坐标」反推新偏移，公式为
`new = W/2 - (S + old)`，展开后是 `new = K - old`，会**每帧来回跳**，
表现为画面闪烁；放大房间后一帧就把房间甩出屏幕（整屏只剩背景）。
改为用无偏移的原始等距投影计算，连续 4 帧偏移一致。

### 未验证

- 外部 CLI（Claude Code / Codex）尚未真正接钩子，目前只是登记为 `kind: external`。
- 材料库、`hire_employee` 工具尚未实现。

---

## 2026-11-08 — 产品模型重定义 + 文档拆分

### 改了什么

| 文件 | 变更 |
|---|---|
| `CLAUDE.md` | 精简为项目级约束，架构细节移出 |
| `docs/architecture.md` | 新建：六层结构、目录、数据流、配置规范、线程模型 |
| `docs/rules.md` | 新建：事件协议、状态机、记忆、材料库、职级、选型、Agent Bus、API |
| `docs/status.md` | 新建：里程碑与验证现状 |
| `docs/dev-rule.md` | 新建：交付检查清单 |
| `docs/changelog.md` | 本文件 |

### 为什么改

用户明确要求：

1. 产品重新定义——BotOffice 本身是 Agent，也能把其他 Agent 拉进办公室组队。
2. Lead 可以是外部 Agent：在应用里「新建对话」选 Claude Code，它就成为第一个员工 / Lead。
3. 材料库共享：资料只存一份，按需检索，不塞进每个人上下文。
4. CLAUDE.md 太长，架构移到 `architecture.md`，只留项目级必须遵守的东西。

### 如何验证

- 文档结构：`ls docs/`
- 语法门禁：`bash scripts/lint.sh`

### 未验证

- 代码尚未实现 M3/M4 的新能力，文档是设计先行。

---

## 2026-11-07 — M1 + M2 跑通

### 改了什么

- 后端：事件总线、四层记忆、压缩流水线、三协议 LLM、Agent 循环、状态机、四种交互、成本统计。
- GUI：PySide6 原生窗口、QPainter 等距 2.5D、无限工位、拖拽开聊、五个侧边页签。

### 验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | LINT OK |
| `scripts/verify/backend.test.py` | ALL CHECKS PASSED（19 项） |
| 8 人办公室 | avatars: 8 |
| 拖拽开聊 | OK conversation happened |
| 原生窗口 | windows / winId > 0 |

### 未验证

- 真实 LLM 平台（只跑了 mock）。
- 浏览器 / 桌面工具（可选依赖未装）。
