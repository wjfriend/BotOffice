"""User-facing strings in one place.

The UI is English for now. A language selector will read these same keys
later, so no widget may hardcode a string. Keys are dotted: area.name.
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # Window and toolbar.
    "app.title": "BotOffice — AI Agent Office",
    "toolbar.new_chat": "New Conversation",
    "toolbar.add_role": "+ Add Employee",
    "toolbar.add_provider": "+ Add Platform",
    "toolbar.add_me": "+ Add Me",
    "toolbar.hide_panel": "Hide panel",
    "toolbar.show_panel": "Show panel",
    "stat.agents": "{count} people",
    "stat.cost": "Cost {value}",
    # Tabs.
    "tab.staff": "Staff",
    "tab.tasks": "Tasks",
    "tab.approvals": "Approvals",
    "tab.inbox": "Inbox",
    "tab.routines": "Routines",
    "tab.platforms": "Platforms",
    "tab.teams": "Teams",
    "tab.chat": "Chat",
    "tab.memory": "Memory",
    "tab.cost": "Cost",
    # Chat panel.
    "chat.no_target": "Click a character in the office to start a conversation.",
    "chat.with": "Chat with {name}",
    "chat.placeholder": "Type a message...",
    "chat.send": "Send",
    "chat.you": "You",
    "chat.log": "Live log",
    "chat.tools": "Tools",
    "chat.tools_empty": "nothing yet",
    "chat.model": "Model",
    "chat.duplicate": "Duplicate",
    "chat.hide": "Hide",
    "chat.show": "Show",
    "chat.group_none": "Direct message",
    "chat.group_new": "New group",
    "chat.group_name": "Group name",
    "chat.group_members": "Members (comma separated, e.g. alice, bob)",
    "platforms.set_key": "Set key",
    "platforms.key_done": "Key saved. It is never shown again.",
    "platforms.key_prompt": "Paste the API key for {name}",
    "platforms.mcp": "MCP servers",
    "platforms.mcp_add": "Add MCP",
    "platforms.mcp_connect": "Connect",
    "platforms.mcp_remove": "Remove",
    "mcp.prompt_id": "Server id",
    "mcp.prompt_command": "Command (absolute path)",
    "mcp.prompt_args": "Arguments (space separated)",
    "mcp.empty": "No MCP servers yet.",
    "mcp.pick": "Select a server first.",
    "teams.export": "Export",
    "teams.import": "Import",
    "msg.no_agent": "Click a character first.",
    # Teams.
    "teams.hint": (
        "Each team works in its own folder. File tools can only touch that folder, "
        "so two teams never see each other's project files."
    ),
    "teams.id_placeholder": "team id, e.g. general",
    "teams.workspace_placeholder": "E:/path/to/project",
    "teams.save": "Save",
    "teams.browse": "Browse...",
    "teams.need_both": "Team id and workspace are both required.",
    # Staff panel.
    "staff.counts": "Working {working} · Waiting {waiting} · Idle {idle} · Offline {offline}",
    "staff.empty": "The office is empty. Click New Conversation to hire the first employee.",
    "staff.activity": "Activity",
    "staff.no_activity": "No activity yet.",
    # Visible states.
    "state.idle": "Idle",
    "state.working": "Working",
    "state.walking": "Walking",
    "state.interacting": "Talking",
    "state.meeting": "Meeting",
    "state.waiting": "Waiting",
    "state.returning": "Returning",
    "state.offline": "Offline",
    # Dialog titles.
    "dialog.add_role.title": "Add Employee",
    "dialog.add_provider.title": "Add LLM Platform",
    "dialog.new_chat.title": "New Conversation",
    # Fields.
    "field.name": "Name",
    "field.role": "Role",
    "field.department": "Department",
    "field.team": "Team",
    "field.rank": "Rank",
    "field.platform": "Platform",
    "field.responsibilities": "Responsibilities",
    "field.agent_type": "Agent type",
    "field.appearance": "Appearance",
    "field.id": "ID",
    "field.label": "Label",
    "field.short": "Short name",
    "field.protocol": "Protocol",
    "field.base_url": "Base URL",
    "field.api_key": "API Key",
    "field.model": "Model",
    "field.cost_in": "Input price / 1k tokens",
    "field.cost_out": "Output price / 1k tokens",
    "field.currency": "Currency",
    # Placeholders.
    "placeholder.name": "Alice",
    "placeholder.role": "Frontend Engineer",
    "placeholder.department": "frontend",
    "placeholder.team": "general",
    "placeholder.responsibilities": "Owns the UI and component library.",
    "placeholder.id": "deepseek",
    "placeholder.label": "DeepSeek",
    "placeholder.short": "DSF",
    "placeholder.base_url": "https://api.deepseek.com/v1",
    "placeholder.api_key": "sk-...",
    "placeholder.model": "deepseek-chat",
    # Options.
    "rank.member": "Member",
    "rank.lead": "Lead",
    "option.set_later": "(set later)",
    "option.no_platform": "(no platform yet — add one first)",
    "protocol.openai": "OpenAI compatible",
    "protocol.anthropic": "Anthropic Messages",
    "protocol.ollama": "Ollama (local)",
    "protocol.mock": "Mock (offline demo)",
    # Agent runtimes.
    "runtime.builtin": "Internal model (pick a platform)",
    "runtime.claude-code": "Claude Code",
    "runtime.codex": "Codex",
    "runtime.opencode": "OpenCode",
    "runtime.gemini-cli": "Gemini CLI",
    # Appearance colours.
    "color.red": "Red",
    "color.blue": "Blue",
    "color.green": "Green",
    "color.amber": "Amber",
    "color.purple": "Purple",
    "color.teal": "Teal",
    # Hints.
    "hint.shared_capabilities": (
        "Capabilities are shared by everyone. A role only declares what it is "
        "responsible for and which memory it may read or write."
    ),
    "hint.pricing": (
        "Prices feed the cost report and the cheapest-first routing. "
        "The Mock protocol needs no network."
    ),
    "hint.first_employee": (
        "The office is empty: this agent becomes the first employee, the Lead."
    ),
    "hint.new_employee": "This agent joins as a new employee and gets a desk.",
    # Buttons.
    "button.create": "Create",
    "button.add": "Add",
    "button.start": "Start",
    "button.cancel": "Cancel",
    # Messages.
    "msg.need_name": "Please enter a name.",
    "msg.need_provider": "Add an LLM platform first.",
    "msg.need_id_model": "ID and model must not be empty.",
    "msg.system": "System",
    "msg.became_lead": "{name} is now the Lead. The office is running.",
    "msg.no_model": "no model",
    "msg.no_role": "no role",
    # Tasks and costs.
    "tasks.empty": "No tasks yet. Assign one to the Lead and it shows up here.",
    "approvals.empty": "Nothing is waiting for you.",
    "approvals.approve": "Approve",
    "approvals.reject": "Reject",
    "inbox.empty": "No messages yet.",
    "inbox.mark_read": "Mark all read",
    "routines.empty": "No routines yet. Add one to run work on a schedule.",
    "routines.name": "Name",
    "routines.prompt": "What to run",
    "routines.every": "Every (minutes)",
    "routines.cron": "Cron, optional (e.g. 0 9 * * 1)",
    "routines.add": "Add",
    "routines.delete": "Delete",
    "routines.run": "Run now",
    "routines.disabled": "disabled",
    "cost.calls": "calls {calls} | in {tokens_in} | out {tokens_out} | {cost} {currency}",
}


def t(key: str, **kwargs: object) -> str:
    """Look up a string, formatting any placeholders."""
    text = STRINGS.get(key, key)
    if not kwargs:
        return text
    return text.format(**kwargs)
