# Rules — 接口与算法约定

> 本文是**实现契约**。改判定逻辑前必须先读对应章节。
> 结构在 `docs/architecture.md`，项目级约束在 `CLAUDE.md`。

---

## 1. 事件总线契约

### 1.1 发布

```python
bus.publish(event_type: str, **data)
```

- `event_type` 用 `dot.separated`：`agent.move`、`memory.write`。
- 保留键：`seq`（自增序号）、`ts`（时间戳）、`type`（事件类型）。
- **业务字段不得使用 `seq` / `ts` / `type` 三个键**。会议主题用 `topic`，与 `type` 不冲突。

### 1.2 订阅

```python
bus.subscribe("agent.*", handler)   # 前缀通配
bus.subscribe("*", handler)         # 全量
```

### 1.3 事件类型表

| 事件 | 触发时机 | 关键字段 |
|---|---|---|
| `employee.hired` | 新员工入库 | `id`, `name`, `rank`, `desk` |
| `employee.left` | 员工离职 | `id` |
| `agent.state` | 状态机切换 | `agent`, `state`, `prev` |
| `agent.move` | 开始走位 | `agent`, `target`[x,z], `seconds` |
| `agent.say` | 说话 | `agent`, `text` |
| `agent.think` | 一次 LLM 决策 | `agent`, `turn` |
| `agent.tool_call` | 调用工具 | `agent`, `tool`, `args` |
| `agent.tool_denied` | 越权调用 | `agent`, `tool` |
| `agent.error` | 出错 | `agent`, `error` |
| `agent.max_turns` | 循环超限 | `agent` |
| `interact.start` | 拖拽开聊开始 | `from`, `to` |
| `interact.done` | 开聊结束 | `from`, `to`, `messages` |
| `task.assigned` | 派活 | `leader`, `worker`, `task` |
| `task.done` | 任务完成 | `worker`, `task`, `summary` |
| `handoff.start` | 交接开始 | `from`, `to` |
| `meeting.start` | 开会 | `participants`, `topic` |
| `meeting.decision` | 会议结论 | `topic`, `decision`, `by` |
| `memory.write` | 写记忆 | `scope`, `author`, `text` |
| `memory.denied` | 越权写记忆 | `agent`, `scope` |
| `library.add` | 材料入库 | `id`, `title`, `tags` |
| `library.search` | 检索材料 | `agent`, `query`, `hits` |
| `cost.usage` | 一次 LLM 计费 | `provider`, `model`, `cost` |
| `bus.event` | 外部 Agent 原始事件 | `runtime`, `agent`, `event` |

---

## 2. Agent 状态机

```
IDLE ──→ WALKING ──→ INTERACTING ──→ RETURNING ──→ IDLE
  │         │            │
  │         └──→ MEETING ┘
  └──→ WORKING ──→ IDLE
  └──→ OFFLINE
```

| 状态 | 含义 | 场景表现 |
|---|---|---|
| `IDLE` | 在工位待命 | 坐着/轻微呼吸 |
| `WORKING` | 正在执行任务 | 敲键盘动画 |
| `WALKING` | 走位中 | 位置插值 + 走路摆动 |
| `INTERACTING` | 与另一人对话 | 面对面 + 气泡 |
| `MEETING` | 会议中 | 围坐 |
| `RETURNING` | 回座 | 走位 |
| `OFFLINE` | 离线/未连接 | 灰显 |

非法转移直接抛异常，不静默忽略。

---

## 3. 记忆分层

| 层 | scope | 谁能读 | 谁能写 | 用途 |
|---|---|---|---|---|
| 公告栏 | `global` | 全员 | Lead / Manager | 全公司公告 |
| 部门白板 | `dept:<name>` | 本部门 | 本部门 | 部门共识 |
| 个人抽屉 | `private:<id>` | **只有本人** | 只有本人 | 私人笔记 |
| 工作轨迹 | `work:<task_id>` | 参与者 | 参与者 | 执行细节，**不进聊天上下文** |

**硬规则**

1. `private:*` 绝不能被其他 Agent 读到（`CLAUDE.md` 约束 6）。
2. 写入前必须校验 `scope.can_write`，越权发 `memory.denied` 且不落盘。
3. `work:*` 默认不自动注入上下文，只有显式检索时才出现。
4. 任何写入都要走压缩流水线（`CLAUDE.md` 约束 7）。

### 3.1 压缩流水线

| 层 | 做什么 | 是否用模型 |
|---|---|---|
| L0 | 规范化、去确认语（好的/收到/ok）、去重、单条限长 400 字 | 否 |
| L1 | 小模型摘要成 ≤5 条事实，失败则退回 L0 | 是（便宜模型） |
| L2 | 按 `budget_tokens` 拼装上下文，超出则丢最旧/最低优先级 | 否 |

`estimate_tokens`：中文约 1 字 1 token，英文约 4 字符 1 token。

---

## 4. 材料库（Material Library）

**核心原则**：资料只存一份，**不写进每个人的上下文**。谁需要谁去查。

### 4.1 存储

```
data/library/
├── index.json          # 元数据索引
└── docs/<id>.md        # 正文
```

索引条目：

```json
{
  "id": "dalian-market-notes",
  "title": "大连本地市场观察",
  "tags": ["dalian", "market", "stock"],
  "scope": "global",
  "author": "alice",
  "updated_at": 1730000000,
  "summary": "一句话摘要"
}
```

### 4.2 检索

```python
library.search(query: str, k: int = 3, scopes: list[str] | None = None)
```

- v1 用**关键词 + 标签打分**，不引入向量库（`CLAUDE.md` 约束 16）。
- 返回 `[{id, title, snippet, score}]`，`snippet` 只截取命中段落。
- **只有被检索到的片段进入上下文**，索引本身不进。

### 4.3 写入

- 只有 `library_write` 权限的职级能写（见 §5）。
- 写入发 `library.add` 事件。

### 4.4 与记忆的区别

| | 记忆 | 材料库 |
|---|---|---|
| 内容 | 办公室发生的事（情节） | 参考资料（文档） |
| 写入 | Agent 交互时自动 | 显式调用工具 |
| 读取 | 按 scope 自动注入 | **只有显式检索** |
| 规模 | 小、会压缩 | 大、原文保存 |

---

## 5. 职级与权限

```python
RANKS = ("owner", "lead", "manager", "member")
```

| 权限 | owner(用户) | lead | manager | member |
|---|---|---|---|---|
| `assign` 派活给别人 | ✓ | ✓ | ✓ | ✗ |
| `hire` 招新员工 | ✓ | ✓ | ✗ | ✗ |
| `fire` 辞退 | ✓ | ✓ | ✗ | ✗ |
| `review` 审阅 | ✓ | ✓ | ✓ | ✗ |
| `call_meeting` 召集会议 | ✓ | ✓ | ✓ | ✗ |
| `library_write` | ✓ | ✓ | ✓ | ✗ |
| `spawn_subagent` | ✓ | ✓ | ✗ | ✗ |

**硬规则**

1. 权限由代码校验，**LLM 不能给自己授权**。
2. Lead 只能有一个；离职后由用户指定新 Lead。
3. 职级变化必须发 `employee.promoted` / `employee.demoted` 事件。

---

## 6. Lead 选型（Selector）

### 6.1 谁是 Lead

- 办公室为空时，用户「新建对话」选中的第一个 Agent 自动成为 Lead。
- 该 Agent 可以是**内部 LLM Agent**，也可以是**外部 CLI Agent**（如 Claude Code）。
- Lead 由 `config/roles.json` 的 `rank: "lead"` 标记。

### 6.2 招人流程

```
Lead 收到任务
  → LLM 决策 {"tool":"hire_employee","args":{
        "name":"Bob","role":"Backend Engineer",
        "runtime":"builtin","model":"deepseek",
        "responsibilities":"..."
    }}
  → hierarchy 校验：Lead 有 hire 权限
  → selector 校验：
      · runtime 存在（builtin / 已接入的 CLI）
      · provider 存在且成本已知
      · 人数未超上限
  → 校验通过才真正创建；失败则把错误回灌给 Lead，让它改参数
```

### 6.3 选型原则（给 Lead 的 system prompt 用）

1. **能复用就复用**：已有空闲员工能干的活，不新招人。
2. **便宜优先**：简单活给便宜模型，复杂规划才用强模型。
3. **外部 Agent 优先用于它擅长的**：写代码用 Claude Code / Codex，网页操作用 Browser。
4. **一次只招必要的**：不要为了显得热闹而招人。
5. **模型与职责匹配**：文档类用便宜模型，架构类用强模型。

### 6.4 模型选择由代码执行

- LLM 只输出**意图**（要什么能力的员工）。
- 具体 provider / model 的最终解析由 `llm/router.py` 决定（`prefer_cheap`、fallback）。
- 这样符合「模型只做判断，确定性转换交给代码」。

---

## 7. 外部 Agent 接入（Agent Bus）

### 7.1 为什么用钩子而不是轮询

- 零推理成本：钩子只转发数据，不调用 LLM。
- 实时：工具一调用，办公室立刻动。
- 不侵入：宿主 Agent 不知道 BotOffice 存在。

### 7.2 钩子脚本硬规则

参考 pixtuoid 的教训：

1. **永不阻塞宿主**：读 stdin → POST → 退出，总耗时上限 200ms。
2. **永远 exit 0**：出错也静默退出，绝不能因为 BotOffice 没开而卡住 Claude Code。
3. **不写 stdout**：避免污染宿主的输出。
4. **失败重试一次即可**，仍失败就丢弃。

### 7.3 事件格式

```json
{
  "ts": 1730000000.123,
  "runtime": "claude-code",
  "agent": "claude-code-1",
  "session_id": "abc123",
  "event": "tool_use",
  "tool": "Edit",
  "file": "src/app.ts",
  "message": "Editing src/app.ts"
}
```

`event` 取值：

| event | 映射到办公室 |
|---|---|
| `session_start` | 员工上线，`IDLE` |
| `session_end` | 会话结束，但**员工留在办公室**，回到 `IDLE`（不是离职） |
| `tool_use` | `WORKING` + 敲键盘 |
| `task_complete` | 汇报，`IDLE` |
| `heartbeat` | 保活 |
| `permission_request` | 举手求助（气泡） |

### 7.4 接入点

```
POST /api/bus/events     # 钩子调用
GET  /api/bus/agents     # 当前在线的外部 Agent
```

### 7.5 支持的运行时

| runtime | 接入方式 | 状态 |
|---|---|---|
| `claude-code` | `PostToolUse` / `Stop` hook | 规划中 |
| `codex` | 事件钩子 | 规划中 |
| `opencode` | 事件钩子 | 规划中 |
| `gemini-cli` | 事件钩子 | 规划中 |
| `builtin` | 进程内直接调用 | 已实现 |

> 外部 Agent 的模型由该 CLI 自己配置，BotOffice 不干预，只统计「它在干什么」。

---

## 8. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 员工、平台、布局、总花费 |
| GET/POST/DELETE | `/api/roles` | 员工增删查 |
| GET/POST/DELETE | `/api/providers` | 平台增删查 |
| POST | `/api/employees` | 新建对话（可选 runtime） |
| POST | `/api/interactions/assign` | 派活 |
| POST | `/api/interactions/handoff` | 交接 |
| POST | `/api/interactions/meeting` | 开会 |
| POST | `/api/interactions/interact` | 拖拽开聊 |
| GET | `/api/memory` | 记忆列表 |
| GET | `/api/memory/stats` | 记忆统计 |
| GET/POST | `/api/library` | 材料库检索 / 入库 |
| GET | `/api/costs` | 成本报表 |
| GET | `/api/tasks` | 看板任务 |
| POST | `/api/bus/events` | 外部 Agent 事件 |
| GET | `/api/events` | 事件历史 |
| GET | `/api/stream` | SSE 实时事件流 |

---

## 9. 工具契约

```python
registry.call(name, args) -> {"ok": bool, ...}
```

- 工具失败**不抛异常**，返回 `{"ok": false, "error": "..."}`，让 Agent 自己纠错。
- 越权工具返回 `agent.tool_denied`，并把「你没有这个权限」回灌给模型。
- `scope.tools` 为空表示「全部工具可用」。
- 可选依赖缺失时，工具在注册表里标记不可用，**不能让服务起不来**（`CLAUDE.md` 约束 19）。

### 9.1 浏览器串行

同一 `profile` 的浏览器任务必须排队执行，用 `registry.lock_for(name)` 保证（`CLAUDE.md` 约束 12）。

### 9.2 命令执行

`run_command` 默认关闭，需显式开启；路径逃逸一律拒绝。

---

## 10. 验证脚本清单

| 改动 | 必须跑 |
|---|---|
| Agent 状态机 | `scripts/verify/state-machine.test.py` |
| 记忆分层 | `scripts/verify/memory-isolation.test.py` |
| 记忆压缩 | `scripts/verify/memory-compaction.test.py` |
| LLM 路由 | `scripts/verify/llm-routing.test.py` |
| 后端整体 | `scripts/verify/backend.test.py` |
| 2.5D 场景 | 手动验收清单（截图存档） |

> 仅目视确认不算通过。所有脚本退出码必须为 0。
