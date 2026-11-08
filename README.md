# BotOffice

A free, open-source virtual office where AI agents work together.

BotOffice is an agent in its own right, and a container for other agents.
Start a conversation with one agent — Claude Code, Codex, or any LLM you
configure — and it becomes the **Lead**. Hand the Lead a job; it decides
which agents and which models to hire, and the new employees walk into the
office and take a desk.

## What it is

- A **native desktop app** (PySide6 / Qt). Not a web page.
- An **isometric 2.5D office** where every agent is a character with a desk.
- **New conversation → Lead**: the first agent you pick runs the office.
- **Multi-platform LLM support**: OpenAI-compatible, Anthropic Messages and
  Ollama endpoints, all configured by you. No vendor is hardcoded.
- **Shared, layered memory** with a compaction pipeline that keeps context
  small, so cheap models stay cheap.
- **A task board** so you can see what everyone is working on.
- **One shared toolbox**: browser control, file access and command execution
  are available to every role. A role only declares what it is responsible
  for.

## Requirements

- Python 3.11 or newer
- Windows or Linux

## Quick start

**Windows — one double-click.** Open the project folder and double-click
`BotOffice.bat`. A console window opens, dependencies install on the first
run, and the office window appears.

From PowerShell, if you prefer:

```powershell
.\BotOffice.bat
```

**Linux** — from a terminal:

```bash
bash scripts/run.sh
```

The first run creates a virtual environment and installs dependencies. After
that, the same launcher starts the app directly.

> Do not run `bash scripts/run.sh` from PowerShell: `bash` there means the
> WSL launcher, which fails unless a WSL distribution is installed. Use
> `BotOffice.bat` on Windows.

## First five minutes

1. Click **+ 添加平台** and add an LLM provider. For a look around without an
   API key, choose protocol **Mock（离线试玩）**.
2. Click **新建对话** and pick an agent type: an internal model on one of your
   platforms, or an external CLI such as Claude Code. The first one becomes
   the **Lead**.
3. Add more employees the same way. Each one gets a desk automatically.
4. Drag one character onto another to make them talk. The conversation shows
   up in the 对话 tab.
5. Open the 看板 tab to see the task list and everyone's role and model.
6. Switch to the 成本 tab to see what each platform has cost so far.

## Configure a real provider

```json
{
  "id": "deepseek",
  "label": "DeepSeek",
  "protocol": "openai",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-...",
  "model": "deepseek-chat",
  "cost_per_1k_input": 0.001,
  "cost_per_1k_output": 0.002,
  "currency": "CNY"
}
```

Supported protocols:

| Protocol | Endpoint | Auth |
|---|---|---|
| `openai` | `{base_url}/chat/completions` | `Authorization: Bearer {api_key}` |
| `anthropic` | `{base_url}/v1/messages` | `x-api-key` header |
| `ollama` | `{base_url}/api/chat` | none |
| `mock` | none | none (offline demo) |

## Architecture

```
PySide6 GUI  ──renders──>  event bus  <──publishes──  orchestration layer
                                                            |
                                          +-----------------+-----------------+
                                          |                                   |
                                   memory layer                      LLM adapter layer
                              (global / dept / private / work)    (openai / anthropic / ollama)
```

The GUI only renders events and reports user intent. It never decides what
an agent does.

## Memory model

| Scope | Shared with |
|---|---|
| `global` | everyone |
| `dept:<name>` | one department |
| `private:<id>` | one agent only |
| `work:<task_id>` | the agents on that task, never auto-injected |

Context is compacted in three stages: free cleaning (dedupe, drop filler),
optional cheap-model summarisation, then budget-aware assembly that fits a
token limit per call.

## Command line

```bash
python -m botoffice.cli status
python -m botoffice.cli add-role alice "Alice" "Frontend Engineer"
python -m botoffice.cli assign alice bob "Build the login page"
python -m botoffice.cli meeting alice,bob "Plan the sprint"
```

## Optional tools

```bash
pip install -e ".[browser]"   # browser control
pip install -e ".[desktop]"   # desktop control (needs an isolated session)
```

The office runs fine without them; unavailable tools are simply not
registered.

## License

MIT
