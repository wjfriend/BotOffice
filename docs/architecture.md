# Architecture

> 架构细节文档。项目级必须遵守的约束在 `CLAUDE.md`，本文只讲**结构**。
> 接口、算法、事件协议在 `docs/rules.md`。

---

## 1. 一句话结构

**一个进程 = 一个原生桌面窗口 + 一个本机 HTTP 服务 + 一个事件总线。**

- 前端：PySide6/Qt 原生窗口，QPainter 画 2.5D 等距场景。
- 后端：FastAPI/uvicorn 跑在同一进程的后台线程，只监听 `127.0.0.1`，端口由 OS 分配。
- 两层之间只通过 HTTP + SSE 事件流通信，互不直接调用。
- 3D/2.5D 层**只表演，不决策**（`CLAUDE.md` 约束 10）。

```
┌──────────────────────────────────────────────────────────────┐
│ L6 原生 GUI（PySide6/Qt）                                       │
│   场景：QPainter 等距 2.5D，工位/小人/气泡/会议室/看板              │
│   面板：看板 · 员工 · 平台 · 对话 · 记忆 · 材料库 · 成本            │
│   只订阅事件流并渲染；唯一写操作是「交互意图」（拖拽）走后端 API      │
├──────────────────────────────────────────────────────────────┤
│ L5 编排层（orchestrator）                                       │
│   office.py     办公室布局、无限工位分配                          │
│   roles.py      员工定义（角色 = 职责 + 范围，数据不是代码）         │
│   hierarchy.py  职级与权限（谁能派活/招人/审阅/开会）               │
│   selector.py   Lead 选型：用哪个 Agent、哪个模型招新员工            │
│   tasks.py      四种交互：派活 / 交接 / 开会 / 拖拽开聊             │
├──────────────────────────────────────────────────────────────┤
│ L4 Agent 层                                                    │
│   agent/runtime.py       内部 Agent 循环（决策→校验→执行→回灌）    │
│   agent/state_machine.py 可见状态机                              │
│   agent/tools.py         全局工具注册表（能力全公司公用）           │
│   external/              外部 CLI Agent 适配（Claude Code 等）     │
│   external/ingest.py     Agent Bus 事件入口（hook → HTTP POST）    │
├──────────────────────────────────────────────────────────────┤
│ L3 LLM 适配层（llm）                                            │
│   client.py    按协议分派：openai / anthropic / ollama / mock     │
│   providers.py 平台注册表（用户自定义 base_url / key / 单价）       │
│   router.py    每员工绑定模型 + fallback + 价格优先                │
├──────────────────────────────────────────────────────────────┤
│ L2 记忆与材料库（memory / library）                              │
│   memory/   四层：global / dept / private / work                 │
│   compact.py L0 无模型折叠 → L1 小模型摘要 → L2 预算感知拼装        │
│   library/  材料库：资料只存一份，按需检索，不塞进每个人上下文        │
├──────────────────────────────────────────────────────────────┤
│ L1 事件总线（bus.py）                                            │
│   进程内 publish/subscribe + 全量事件日志 + SSE 推送                │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 目录结构

```
botoffice/
├── CLAUDE.md                 # 项目级约束（精简）
├── README.md                 # 英文说明
├── pyproject.toml
├── .env.example
├── server.py                 # 无 GUI 模式入口（打印 ready + 端口）
├── botoffice/
│   ├── __init__.py
│   ├── app.py                # FastAPI 装配、路由、OfficeContext
│   ├── bus.py                # 事件总线
│   ├── logging_setup.py      # log/ 下 JSON Lines 日志
│   ├── cli.py                # 命令行客户端
│   ├── memory/
│   │   ├── __init__.py       # 分层记忆门面
│   │   ├── store.py          # JSON 原子写 + 检索
│   │   └── compact.py        # L0/L1/L2 压缩流水线
│   ├── library/              # 材料库（按需检索）
│   │   ├── __init__.py
│   │   └── store.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py         # 三协议 + mock
│   │   ├── providers.py      # 平台注册表
│   │   └── router.py         # 模型绑定与路由
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── runtime.py        # 通用 Agent 循环
│   │   ├── state_machine.py  # 可见状态机
│   │   ├── tools.py          # 全局工具注册表
│   │   └── builtin_tools.py  # 文件 / 命令 / 浏览器 / 桌面工具
│   ├── external/             # 外部 CLI Agent
│   │   ├── __init__.py
│   │   ├── adapters.py       # Claude Code / Codex / OpenCode / Gemini CLI
│   │   └── ingest.py         # Agent Bus 事件入口
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── office.py         # 布局与工位
│   │   ├── roles.py          # 员工定义
│   │   ├── hierarchy.py      # 职级与权限
│   │   ├── selector.py       # Lead 选型
│   │   └── tasks.py          # 四种交互
│   └── gui/
│       ├── __init__.py
│       ├── __main__.py       # python -m botoffice.gui 入口
│       ├── app.py            # 启动：找空闲端口、起服务、开窗口
│       ├── client.py         # HTTP + SSE 客户端
│       ├── main_window.py    # 主窗口与对话框
│       ├── scene.py          # 等距场景绘制
│       ├── scene_widget.py   # 鼠标拖拽交互
│       └── panels.py         # 看板 / 员工 / 记忆 / 成本面板
├── config/
│   ├── providers.json        # LLM 平台
│   └── roles.json            # 员工
├── scripts/
│   ├── lint.sh
│   ├── run.sh
│   ├── hooks/                # 外部 Agent 钩子脚本
│   │   └── claude-code-hook.sh
│   └── verify/
│       └── backend.test.py
├── docs/
├── log/                      # 运行时日志（可删）
└── data/                     # 记忆与材料库持久化
```

---

## 3. 关键数据流

### 3.1 启动

```
Windows: 双击 BotOffice.bat  →  scripts\run.bat
Linux:   bash scripts/run.sh
  → botoffice.gui.__main__  →  botoffice.gui.app:main()
  → find_free_port()                # bind(0) 再读端口
  → BackgroundServer(port)          # uvicorn 后台线程
  → MainWindow(office)              # 原生窗口
  → office.listen()                 # SSE 订阅 /api/stream
```

### 3.2 新建对话 → 第一个员工成为 Lead

```
用户点「新建对话」
  → 对话框：选择 Agent 类型（Claude Code / Codex / 内部模型…）+ 名字
  → POST /api/employees
  → office.hire(...)                # 分配 desk_position(0)
  → 若办公室原本为空 → 该员工 leader=True（Lead）
  → 用户把第一句需求发给 Lead
  → Lead 决定：自己干 / 招人 / 开会
```

### 3.3 Lead 招人

```
Lead 的 LLM 返回 {"tool":"hire_employee","args":{...}}
  → runtime 校验：该员工有 hire 权限（hierarchy）
  → selector 校验：runtime / provider 存在，成本在预算内
  → 新员工入库，desk_position(n) 分配工位
  → publish("employee.hired")
  → GUI：小人走进来，坐到新工位
```

### 3.4 外部 Agent 接入（Agent Bus）

```
Claude Code 触发 PostToolUse hook
  → scripts/hooks/claude-code-hook.sh 读 stdin JSON
  → POST http://127.0.0.1:<port>/api/bus/events
  → external/ingest.py 映射成办公室事件
  → publish("agent.tool_call") / ("agent.say") / ("agent.state")
  → GUI 让对应小人打字 / 气泡 / 变色
  → 钩子脚本立即 exit 0（永不阻塞宿主）
```

### 3.5 拖拽开聊

```
用户拖 Bot A 到 Bot B 身上
  → SceneWidget 发 drop_requested(A, B)
  → POST /api/interactions/interact {from_id, to_id}
  → A 起身走到 B 工位，双方 INTERACT
  → 各自读共享记忆 + 材料库检索 → 决定 check/new/keep_waiting
  → 摘要写记忆，细节写 work:<task_id>
  → publish("interact.done")，GUI 播放回座
```

---

## 4. 员工配置规范（JSON，全英文）

员工是**数据不是代码**。新增员工只改 `config/roles.json` 或走 API。

```json
{
  "id": "alice",
  "name": "Alice",
  "role": "Frontend Engineer",
  "kind": "builtin",
  "department": "frontend",
  "rank": "member",
  "responsibilities": "Owns UI implementation and component library.",
  "scope": {
    "memory_read": ["global", "dept:frontend", "private:alice"],
    "memory_write": ["dept:frontend", "private:alice"],
    "tools": []
  },
  "llm": {
    "primary": "deepseek",
    "fallback": "qwen",
    "prefer_cheap": false,
    "budget_tokens": 12000
  },
  "desk": [12.0, 8.0],
  "avatar": ""
}
```

`kind` 两种：

| kind | 含义 | 模型由谁决定 |
|---|---|---|
| `builtin` | 内部 LLM Agent，走自建适配层 | BotOffice（`llm.primary`） |
| `external` | 外部 CLI Agent，走 Agent Bus | 该 CLI 自己的配置 |

`external` 额外字段：

```json
{
  "kind": "external",
  "external": {
    "runtime": "claude-code",
    "session_id": "",
    "pid": 0
  }
}
```

`rank` 取值与权限见 `docs/rules.md` §5。

---

## 5. 平台配置规范

```json
{
  "id": "deepseek",
  "protocol": "openai",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "${DEEPSEEK_API_KEY}",
  "model": "deepseek-chat",
  "label": "DeepSeek",
  "currency": "CNY",
  "cost_per_1k_input": 0.001,
  "cost_per_1k_output": 0.002,
  "max_tokens": 4096,
  "temperature": 0.7
}
```

- `protocol` ∈ `openai | anthropic | ollama | mock`
- 密钥**永不写入仓库**，落盘时写成 `${ID_API_KEY}` 占位符（`CLAUDE.md` 约束 14）。
- `mock` 不需要网络，用于离线试玩与自动化测试。

---

## 6. 场景坐标

等距投影：

```
screen_x = (x - z) * tile_w / 2
screen_y = (x + z) * tile_h / 2 - height
```

- 深度排序按 `(x + z)` 从小到大绘制。
- `BASE_TILE_W = 46`、`BASE_TILE_H = 23`；场景按 `fit_room()` 自动缩放，房间再大也能装进窗口。
- 办公室是**固定平面图**（`ROOM` 28×24），不随人数变大；人多时工位往下加行。
- 分区（`ZONES`）：
  | 区域 | 位置 | 内容 |
  |---|---|---|
  | 会议室 | 上方 | 圆桌 + 玻璃墙 |
  | 办公区 | 中间 | 两排工位 |
  | 老板办公室 | 左下 | Boss（用户本人） |
  | 休息区 | 右下 | 沙发、茶几、落地灯 |
  | 茶水间 | 右上 | 吧台、冰箱、饮水机 |
  | 大门 | 下方 | 入口 |
- 工位按 `desk_position(index)` 分配（每排 5 个，两排，满了继续往后加）。
- `landmarks()` 返回 `zones`、`entrance`、`desks`、`bounds`，GUI 只按这些数据画。

---

## 7. 线程模型

| 线程 | 干什么 | 规则 |
|---|---|---|
| GUI 主线程 | Qt 事件循环、绘制 | 绝不做网络/LLM 调用 |
| uvicorn 线程 | 处理 HTTP 请求 | 通过 `BackgroundCaller` 回调回主线程 |
| Agent 工作线程 | 跑 Agent 循环（可能几十秒） | 结果走事件总线，不直接碰 Qt 对象 |
| 事件总线 | 进程内发布订阅 | 线程安全，订阅者自行派发 |

**规则**：任何可能慢的操作（LLM、工具、文件）都不能在 GUI 线程执行。
