# Status — 项目状态

> 最后更新：2026-11-08

---

## 当前里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| **M1 后端跑通** | 多平台 LLM、角色体系、四层记忆与压缩、四种交互 | ✅ 已完成 |
| **M2 2.5D 可视化** | PySide6 原生窗口、等距场景、小人走位、拖拽开聊 | ✅ 已完成 |
| **M3 办公室化** | 新建对话→Lead、看板、动画、材料库、职级权限 | 🚧 进行中 |
| **M4 外部 Agent 接入** | Agent Bus 钩子、Claude Code / Codex / OpenCode / Gemini CLI | 🚧 事件入口与钩子脚本已完成，未接入真实 CLI 配置 |
| **M5 美化 + 打包** | 场景细节、日夜光照、PyInstaller 打包 | ⏳ 待开始 |
| **M6 3D 升级** | three.js、大连本地外景、桌面背景轮换 | ⏳ 待开始 |

---

## M1 已完成明细

- ✅ 三协议 LLM 适配层：`openai` / `anthropic` / `ollama` + `mock`
- ✅ 平台注册表：用户自定义 base_url / key / 模型 / 单价
- ✅ 每员工绑定模型 + fallback + 价格优先
- ✅ 四层记忆：global / dept / private / work，物理隔离
- ✅ 压缩流水线：L0 去重折叠 → L1 小模型摘要 → L2 预算拼装
- ✅ Agent 循环：JSON 决策 → 范围校验 → 执行工具 → 回灌
- ✅ 可见状态机：IDLE / WALKING / INTERACTING / MEETING / WORKING / RETURNING / OFFLINE
- ✅ 四种交互：派活 / 交接 / 开会 / 拖拽开聊
- ✅ 全局工具注册表：文件、命令、浏览器、桌面（可选依赖）
- ✅ 事件总线 + 全量事件日志 + SSE
- ✅ 成本统计：按平台 / 按模型

---

## M2 已完成明细

- ✅ PySide6 原生窗口（`QApplication.platformName() == "windows"`，`winId() > 0`）
- ✅ QPainter 等距 2.5D：地板、墙、工位、小人、气泡、会议室、Leader 玻璃办公室
- ✅ 无限工位：`desk_position(index)` 自动分配，8 人实测通过
- ✅ 场景自动缩放 `fit_room()`，房间再大也装得下
- ✅ 拖拽小人到另一人身上 → 触发开聊（模拟鼠标事件实测通过）
- ✅ 拖拽到空地 → 小人走过去
- ✅ 事件流驱动动画：`agent.move` / `agent.say` / `agent.state`
- ✅ 侧边栏五个页签：角色 / 平台 / 对话 / 记忆 / 成本

---

## M3 进行中

| 事项 | 状态 |
|---|---|
| 新建对话 → 选择 Agent 类型 → 第一个成为 Lead | ✅ 已实现 |
| 看板（任务/状态总览） | ✅ 已实现 |
| 点员工打开对话（`POST /api/agents/{id}/say`） | ✅ 已实现 |
| 多团队 / 多办公室（每团队独立布局，工具栏切换） | ✅ 已实现 |
| 审批队列（`ask me`：外部 CLI 请求权限时排队，由你批准/拒绝） | ✅ 已实现 |
| 收件箱（Agent 发言/派活/交接留存，未读计数） | ✅ 已实现 |
| 点员工看实时事件日志（工具调用/说话/状态） | ✅ 已实现 |
| 模型选择器（每个员工随时换模型） | ✅ 已实现 |
| 密钥管理（只回 `api_key_set`，永不回显 Key） | ✅ 已实现 |
| 员工复制 / 隐藏 | ✅ 已实现 |
| 团队导入导出（Markdown + YAML frontmatter） | ✅ 已实现 |
| Routines 定时任务 | ✅ 已实现 |
| 群聊（多 Agent 同屏轮流发言） | ✅ 已实现 |
| 流式回复（OpenAI 协议 SSE + 气泡逐字） | ✅ 已实现 |
| 应用集成 / MCP | ⏳ 待做 |
| 每个 Bot 一台电脑（默认不分配，可共享） | ⏳ 最后做 |
| 真正的 PTY 终端（自己启动 CLI 并抓 stdout） | ⏳ 未做 |
| 员工动画：敲键盘、眨眼、状态色点 | ✅ 已实现 |
| 办公室场景：木地板、落地窗（天空/云/城市天际线）、白板、公告板、挂钟、茶水间、沙发区、书架、打印机、圆桌会议室 | ✅ 已实现 |
| 每张工位下的彩色地毯（对应员工颜色） | ✅ 已实现 |
| 所有家具不透明实体（顶面 + 受光侧面 + 接触阴影） | ✅ 已实现 |
| Windows 双击启动 `BotOffice.bat` | ✅ 已实现 |
| 角色差异化：三种发型、眼镜、粉彩衣服、随房间缩放 | ✅ 已实现 |
| 职级权限（assign / hire / review / meeting） | 🚧 数据层已完成，工具层待接 |
| Lead 招人工具 `hire_employee` | ⏳ |
| 材料库（按需检索） | ⏳ |

### 本轮验证

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | ✅ LINT OK |
| `scripts/verify/backend.test.py` | ✅ ALL CHECKS PASSED |
| `scripts/verify/employee.test.py` | ✅ ALL CHECKS PASSED（16 项） |
| 场景居中稳定性 | ✅ 连续 4 帧偏移完全一致（修复前会来回跳，表现为闪烁） |
| 演示截图 | `docs/office-demo.png` |

---

## 功能差距（对照 munder-difflin）

> 参考对象：`HarnessMD/munder-difflin`（可视化 agent harness，Electron + Pixi.js）。
> 我们保留 2.5D 等距画风，功能与信息架构向它看齐。

| 功能 | 对方 | 我们 |
|---|---|---|
| 每个 Agent 的可交互终端 | ✅ xterm.js | ❌ |
| 员工卡片（状态 / 模型 / 上下文占用 / 当前任务） | ✅ | 🚧 有状态与模型，缺上下文占用与当前任务 |
| 审批队列（花钱 / 危险操作） | ✅ | ❌ |
| 自主等级 / token 预算 | ✅ | 🚧 有 `budget_tokens`，无自主等级 |
| 看板 | ✅ | ✅ 基础任务列表 |
| 收件箱 / 消息 | ✅ | ❌ |
| 记忆检索 | ✅ 语义检索 | 🚧 关键词检索 |
| 多楼层 / 多办公室 | ✅ | 🚧 多团队已支持，多楼层未做 |
| 外部 CLI 接入 | ✅ node-pty 真进程 | ❌ 仅登记为 `kind: external` |
| 办公室画风 | 像素 | ✅ 2.5D 等距（本项目选择） |

## 已知问题

| 问题 | 影响 | 计划 |
|---|---|---|
| 外部 Agent 尚未接入 | 只能用手动添加的内部员工 | M4 |
| 系统 Python 的 `browser_use` 版本旧 | 浏览器工具不可用 | 用项目 `.venv` 安装 |
| 3D 尚未开始 | 只有 2.5D | M6 |

---

## 验证现状

| 项 | 结果 |
|---|---|
| `bash scripts/lint.sh` | ✅ LINT OK |
| `scripts/verify/backend.test.py` | ✅ ALL CHECKS PASSED（19 项） |
| 8 人办公室 | ✅ avatars: 8 |
| 拖拽开聊 | ✅ DRAG RESULT: OK conversation happened |
| 原生窗口 | ✅ windows / winId > 0 |
