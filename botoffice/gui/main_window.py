"""Main window: the office view plus the side panel.

Everything the user does in the GUI is a request to the backend. The window
never decides what an agent should do; it renders what the backend reports.

The side panel mirrors the office at a glance: a staff list with a status
dot per person, and an activity feed underneath. All user-facing text comes
from i18n.py so a language selector can be added later.
"""

from __future__ import annotations

import html as html_lib
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFileDialog
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QInputDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .i18n import t
from .scene import AVATAR_COLOR_INDEX, STATE_COLORS
from .scene_widget import SceneWidget

# Colour per visible state, for the staff list.
STATE_HEX = {name: color.name() for name, color in STATE_COLORS.items()}
ACTIVE_STATES = ("working", "walking", "interacting", "meeting", "returning")

# Short role codes for the name tag above each character.
ROLE_SHORTS = (
    ("frontend", "FE"),
    ("front end", "FE"),
    ("backend", "BE"),
    ("back end", "BE"),
    ("full stack", "FS"),
    ("design", "Des"),
    ("data", "Dat"),
    ("test", "QA"),
    ("qa", "QA"),
    ("ops", "Ops"),
    ("doc", "Doc"),
    ("product", "PM"),
    ("research", "Res"),
    ("lead", "Lead"),
    ("manager", "Mgr"),
    ("dev", "Dev"),
    ("engineer", "Dev"),
)


class AddRoleDialog(QDialog):
    """Create one character through the low-level role form."""

    def __init__(self, providers: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dialog.add_role.title"))
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("placeholder.name"))
        self.role_edit = QLineEdit()
        self.role_edit.setPlaceholderText(t("placeholder.role"))
        self.dept_edit = QLineEdit("general")
        self.dept_edit.setPlaceholderText(t("placeholder.department"))
        self.resp_edit = QTextEdit()
        self.resp_edit.setPlaceholderText(t("placeholder.responsibilities"))
        self.resp_edit.setMaximumHeight(80)
        self.leader_box = QComboBox()
        self.leader_box.addItems([t("rank.member"), t("rank.lead")])
        self.model_box = QComboBox()
        for provider in providers:
            self.model_box.addItem(provider.get("label") or provider["id"], provider["id"])
        self.model_box.addItem(t("option.set_later"), "")

        form.addRow(t("field.name"), self.name_edit)
        form.addRow(t("field.role"), self.role_edit)
        form.addRow(t("field.department"), self.dept_edit)
        form.addRow(t("field.rank"), self.leader_box)
        form.addRow(t("field.platform"), self.model_box)
        form.addRow(t("field.responsibilities"), self.resp_edit)
        layout.addLayout(form)

        hint = QLabel(t("hint.shared_capabilities"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8b93a5;font-size:12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(t("button.create"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def payload(self) -> dict:
        agent_id = self.name_edit.text().strip().lower().replace(" ", "_")
        department = self.dept_edit.text().strip() or "general"
        is_leader = self.leader_box.currentIndex() == 1
        return {
            "id": agent_id,
            "name": self.name_edit.text().strip() or agent_id,
            "role": self.role_edit.text().strip(),
            "department": department,
            "leader": is_leader,
            "responsibilities": self.resp_edit.toPlainText().strip(),
            "model_primary": self.model_box.currentData() or "",
            "memory_read": ["global", f"dept:{department}", f"private:{agent_id}"],
            "memory_write": (
                ["global", f"dept:{department}", f"private:{agent_id}"]
                if is_leader
                else [f"dept:{department}", f"private:{agent_id}"]
            ),
        }


class AddProviderDialog(QDialog):
    """Connect one LLM platform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dialog.add_provider.title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText(t("placeholder.id"))
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText(t("placeholder.label"))
        self.short_edit = QLineEdit()
        self.short_edit.setPlaceholderText(t("placeholder.short"))
        self.protocol_box = QComboBox()
        self.protocol_box.addItem(t("protocol.openai"), "openai")
        self.protocol_box.addItem(t("protocol.anthropic"), "anthropic")
        self.protocol_box.addItem(t("protocol.ollama"), "ollama")
        self.protocol_box.addItem(t("protocol.mock"), "mock")
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText(t("placeholder.base_url"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText(t("placeholder.api_key"))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText(t("placeholder.model"))
        self.cost_in = QLineEdit("0")
        self.cost_out = QLineEdit("0")
        self.currency_edit = QLineEdit("CNY")

        form.addRow(t("field.id"), self.id_edit)
        form.addRow(t("field.label"), self.label_edit)
        form.addRow(t("field.short"), self.short_edit)
        form.addRow(t("field.protocol"), self.protocol_box)
        form.addRow(t("field.base_url"), self.base_edit)
        form.addRow(t("field.api_key"), self.key_edit)
        form.addRow(t("field.model"), self.model_edit)
        form.addRow(t("field.cost_in"), self.cost_in)
        form.addRow(t("field.cost_out"), self.cost_out)
        form.addRow(t("field.currency"), self.currency_edit)
        layout.addLayout(form)

        hint = QLabel(t("hint.pricing"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8b93a5;font-size:12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(t("button.add"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def payload(self) -> dict:
        return {
            "id": self.id_edit.text().strip(),
            "label": self.label_edit.text().strip(),
            "short": self.short_edit.text().strip(),
            "protocol": self.protocol_box.currentData(),
            "base_url": self.base_edit.text().strip(),
            "api_key": self.key_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "cost_per_1k_input": float(self.cost_in.text() or 0),
            "cost_per_1k_output": float(self.cost_out.text() or 0),
            "currency": self.currency_edit.text().strip() or "CNY",
        }


class NewConversationDialog(QDialog):
    """Start a new conversation by picking which agent runs it.

    The first employee in an empty office becomes the Lead. Every later
    employee is hired by the Lead or by the user.
    """

    RUNTIMES = ("builtin", "claude-code", "codex", "opencode", "gemini-cli")
    AVATARS = ("red", "blue", "green", "amber", "purple", "teal")

    def __init__(
        self,
        providers: list[dict],
        first_employee: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dialog.new_chat.title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("placeholder.name"))
        self.role_edit = QLineEdit()
        self.role_edit.setPlaceholderText(t("placeholder.role"))
        self.dept_edit = QLineEdit("general")
        self.dept_edit.setPlaceholderText(t("placeholder.department"))
        self.team_edit = QLineEdit("general")
        self.team_edit.setPlaceholderText(t("placeholder.team"))
        self.resp_edit = QTextEdit()
        self.resp_edit.setPlaceholderText(t("placeholder.responsibilities"))
        self.resp_edit.setMaximumHeight(72)

        self.runtime_box = QComboBox()
        for runtime in self.RUNTIMES:
            self.runtime_box.addItem(t(f"runtime.{runtime}"), runtime)
        self.runtime_box.currentIndexChanged.connect(self._sync_provider_enabled)

        self.provider_box = QComboBox()
        for provider in providers:
            self.provider_box.addItem(provider.get("label") or provider["id"], provider["id"])
        if not providers:
            self.provider_box.addItem(t("option.no_platform"), "")

        self.avatar_box = QComboBox()
        for color in self.AVATARS:
            self.avatar_box.addItem(t(f"color.{color}"), color)

        form.addRow(t("field.name"), self.name_edit)
        form.addRow(t("field.role"), self.role_edit)
        form.addRow(t("field.department"), self.dept_edit)
        form.addRow(t("field.team"), self.team_edit)
        form.addRow(t("field.agent_type"), self.runtime_box)
        form.addRow(t("field.platform"), self.provider_box)
        form.addRow(t("field.appearance"), self.avatar_box)
        form.addRow(t("field.responsibilities"), self.resp_edit)
        layout.addLayout(form)

        hint_text = t("hint.first_employee") if first_employee else t("hint.new_employee")
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8b93a5;font-size:12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(t("button.start"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_provider_enabled()

    def _sync_provider_enabled(self) -> None:
        builtin = self.runtime_box.currentData() == "builtin"
        self.provider_box.setEnabled(builtin)

    def payload(self) -> dict:
        agent_id = self.name_edit.text().strip().lower().replace(" ", "_")
        department = self.dept_edit.text().strip() or "general"
        runtime = self.runtime_box.currentData()
        return {
            "id": agent_id,
            "name": self.name_edit.text().strip() or agent_id,
            "role": self.role_edit.text().strip(),
            "department": department,
            "team": self.team_edit.text().strip() or "general",
            "runtime": runtime,
            "provider": self.provider_box.currentData() if runtime == "builtin" else "",
            "responsibilities": self.resp_edit.toPlainText().strip(),
            "avatar": self.avatar_box.currentData(),
        }


class MainWindow(QMainWindow):
    """The BotOffice window."""

    TAB_STAFF = 0
    TAB_TASKS = 1
    TAB_APPROVALS = 2
    TAB_INBOX = 3
    TAB_ROUTINES = 4
    TAB_PLATFORMS = 5
    TAB_TEAMS = 6
    TAB_CHAT = 7
    TAB_MEMORY = 8
    TAB_COST = 9

    def __init__(self, office) -> None:
        super().__init__()
        self.office = office
        self.setWindowTitle(t("app.title"))
        self.resize(1440, 880)

        self.roles: list[dict] = []
        self.providers: list[dict] = []
        self.chat_lines: list[tuple[str, str]] = []
        self.activity_lines: list[tuple[str, str]] = []
        self.selected_agent: str | None = None
        self.current_team: str | None = None
        self.last_total_cost: float = 0.0
        self.selected_group: str = ""

        self._build_ui()
        self.refresh_all()

    # ------------------------------------------------------------------ ui

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar.
        toolbar = QWidget()
        toolbar.setStyleSheet(
            "background:#1a2030;border-bottom:1px solid #2e3950;"
        )
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(14, 8, 14, 8)
        bar.setSpacing(8)

        title = QLabel("BotOffice")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("color:#ffb45e;")
        bar.addWidget(title)
        bar.addSpacing(12)

        self.btn_new_chat = QPushButton(t("toolbar.new_chat"))
        self.btn_new_chat.setStyleSheet(
            "background:#ffb45e;color:#241a08;border:none;border-radius:8px;"
            "padding:7px 16px;font-weight:700;"
        )
        self.btn_new_chat.clicked.connect(self.on_new_conversation)
        bar.addWidget(self.btn_new_chat)

        self.btn_add_role = QPushButton(t("toolbar.add_role"))
        self.btn_add_role.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:7px 14px;font-weight:600;"
        )
        self.btn_add_role.clicked.connect(self.on_add_role)
        bar.addWidget(self.btn_add_role)

        self.btn_add_provider = QPushButton(t("toolbar.add_provider"))
        self.btn_add_provider.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:7px 13px;"
        )
        self.btn_add_provider.clicked.connect(self.on_add_provider)
        bar.addWidget(self.btn_add_provider)

        self.btn_add_me = QPushButton(t("toolbar.add_me"))
        self.btn_add_me.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:7px 13px;"
        )
        self.btn_add_me.clicked.connect(self.on_add_me)
        bar.addWidget(self.btn_add_me)

        self.btn_sidebar = QPushButton(t("toolbar.hide_panel"))
        self.btn_sidebar.setStyleSheet(
            "background:#222a3d;color:#93a0b8;border:1px solid #2e3950;"
            "border-radius:8px;padding:7px 12px;font-size:12px;"
        )
        self.btn_sidebar.clicked.connect(self.toggle_sidebar)
        bar.addWidget(self.btn_sidebar)

        self.team_box = QComboBox()
        self.team_box.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:5px 10px;font-size:12px;"
        )
        self.team_box.currentIndexChanged.connect(self.on_team_changed)
        bar.addWidget(self.team_box)

        bar.addStretch(1)
        self.stat_cost = QLabel(t("stat.cost", value="0.00"))
        self.stat_agents = QLabel(t("stat.agents", count=0))
        for label in (self.stat_cost, self.stat_agents):
            label.setStyleSheet(
                "color:#93a0b8;background:#222a3d;border:1px solid #2e3950;"
                "border-radius:999px;padding:5px 12px;font-size:12px;"
            )
            label.setMinimumWidth(78)
            label.setAlignment(Qt.AlignCenter)
            bar.addWidget(label)

        outer.addWidget(toolbar)

        # Scene plus the side panel.
        self.splitter = QSplitter(Qt.Horizontal)
        self.scene_widget = SceneWidget()
        self.scene_widget.drop_requested.connect(self.on_drop)
        self.scene_widget.avatar_clicked.connect(self.on_avatar_clicked)
        self.splitter.addWidget(self.scene_widget)

        self.panel = QWidget()
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #2e3950;background:#1a2030;}"
            "QTabBar::tab{background:#151a26;color:#93a0b8;padding:9px 9px;"
            "border-right:1px solid #2e3950;font-size:12px;}"
            "QTabBar::tab:selected{background:#1a2030;color:#ffb45e;}"
        )

        # Staff tab: counts, people, activity. Mirrors the office at a glance.
        staff_page = QWidget()
        staff_layout = QVBoxLayout(staff_page)
        staff_layout.setContentsMargins(10, 10, 10, 10)
        staff_layout.setSpacing(6)

        self.counts_label = QLabel("")
        self.counts_label.setStyleSheet("color:#93a0b8;font-size:12px;")
        staff_layout.addWidget(self.counts_label)

        self.staff_view = QTextEdit()
        self.staff_view.setReadOnly(True)
        self.staff_view.setStyleSheet(
            "background:transparent;border:none;color:#e6ebf5;font-size:13px;"
        )
        staff_layout.addWidget(self.staff_view, 3)

        activity_title = QLabel(t("staff.activity"))
        activity_title.setStyleSheet("color:#e6ebf5;font-size:12px;font-weight:600;")
        staff_layout.addWidget(activity_title)

        self.activity_view = QTextEdit()
        self.activity_view.setReadOnly(True)
        self.activity_view.setStyleSheet(
            "background:transparent;border:none;color:#93a0b8;font-size:12px;"
        )
        staff_layout.addWidget(self.activity_view, 2)

        self.board_view = QTextEdit()
        self.board_view.setReadOnly(True)
        self.providers_list = QListWidget()
        self.memory_list = QListWidget()
        self.costs_list = QListWidget()
        for widget in (self.board_view, self.providers_list,
                       self.memory_list, self.costs_list):
            widget.setStyleSheet(
                "background:#151a26;border:none;color:#e6ebf5;font-size:13px;"
            )

        # Chat page: click a character in the office to talk to it.
        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(8, 8, 8, 8)
        chat_layout.setSpacing(6)

        chat_header_row = QHBoxLayout()
        chat_header_row.setSpacing(6)
        self.chat_header = QLabel(t("chat.no_target"))
        self.chat_header.setWordWrap(True)
        self.chat_header.setStyleSheet("color:#93a0b8;font-size:12px;")
        chat_header_row.addWidget(self.chat_header, 1)

        self.model_box = QComboBox()
        self.model_box.setStyleSheet(
            "background:#151a26;border:1px solid #2e3950;border-radius:8px;"
            "color:#e6ebf5;padding:4px 8px;font-size:12px;"
        )
        self.model_box.currentIndexChanged.connect(self.on_model_changed)
        chat_header_row.addWidget(self.model_box)
        chat_layout.addLayout(chat_header_row)

        chat_actions = QHBoxLayout()
        chat_actions.setSpacing(6)
        self.btn_duplicate = QPushButton(t("chat.duplicate"))
        self.btn_duplicate.clicked.connect(self.on_duplicate_agent)
        self.btn_hide = QPushButton(t("chat.hide"))
        self.btn_hide.clicked.connect(self.on_hide_agent)
        for button in (self.btn_duplicate, self.btn_hide):
            button.setStyleSheet(
                "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
                "border-radius:8px;padding:5px 10px;font-size:12px;"
            )
            chat_actions.addWidget(button)
        chat_actions.addStretch(1)
        chat_layout.addLayout(chat_actions)

        # Group chat: several agents answer the same message in turn.
        chat_group_row = QHBoxLayout()
        chat_group_row.setSpacing(6)
        self.group_box = QComboBox()
        self.group_box.setStyleSheet(
            "background:#151a26;border:1px solid #2e3950;border-radius:8px;"
            "color:#e6ebf5;padding:4px 8px;font-size:12px;"
        )
        self.group_box.addItem(t("chat.group_none"), "")
        self.group_box.currentIndexChanged.connect(self.on_group_selected)
        chat_group_row.addWidget(self.group_box, 1)
        self.btn_new_group = QPushButton(t("chat.group_new"))
        self.btn_new_group.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:5px 10px;font-size:12px;"
        )
        self.btn_new_group.clicked.connect(self.on_new_group)
        chat_group_row.addWidget(self.btn_new_group)
        chat_layout.addLayout(chat_group_row)

        # Tool chips: what the office is executing right now.
        tools_title = QLabel(t("chat.tools"))
        tools_title.setStyleSheet("color:#e6ebf5;font-size:12px;font-weight:600;")
        chat_layout.addWidget(tools_title)
        self.tool_chips = QLabel(t("chat.tools_empty"))
        self.tool_chips.setWordWrap(True)
        self.tool_chips.setStyleSheet("color:#8fa0b8;font-size:12px;")
        self.tool_chips.setMinimumHeight(22)
        chat_layout.addWidget(self.tool_chips)

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setStyleSheet(
            "background:#151a26;border:none;color:#e6ebf5;font-size:13px;"
        )
        chat_layout.addWidget(self.chat_view, 1)

        log_title = QLabel(t("chat.log"))
        log_title.setStyleSheet("color:#e6ebf5;font-size:12px;font-weight:600;")
        chat_layout.addWidget(log_title)
        self.agent_log_view = QTextEdit()
        self.agent_log_view.setReadOnly(True)
        self.agent_log_view.setMaximumHeight(150)
        self.agent_log_view.setStyleSheet(
            "background:#0f141d;border:1px solid #2e3950;color:#8fa0b8;font-size:11px;"
        )
        chat_layout.addWidget(self.agent_log_view)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText(t("chat.placeholder"))
        self.chat_input.returnPressed.connect(self.on_send)
        self.chat_input.setStyleSheet(
            "background:#151a26;border:1px solid #2e3950;border-radius:8px;"
            "color:#e6ebf5;padding:6px 8px;"
        )
        self.btn_send = QPushButton(t("chat.send"))
        self.btn_send.setStyleSheet(
            "background:#ffb45e;color:#241a08;border:none;border-radius:8px;"
            "padding:6px 14px;font-weight:600;"
        )
        self.btn_send.clicked.connect(self.on_send)
        row.addWidget(self.chat_input, 1)
        row.addWidget(self.btn_send)
        chat_layout.addLayout(row)

        # Teams page: each team's working folder.
        teams_page = QWidget()
        teams_layout = QVBoxLayout(teams_page)
        teams_layout.setContentsMargins(8, 8, 8, 8)
        teams_layout.setSpacing(6)

        teams_hint = QLabel(t("teams.hint"))
        teams_hint.setWordWrap(True)
        teams_hint.setStyleSheet("color:#93a0b8;font-size:12px;")
        teams_layout.addWidget(teams_hint)

        self.teams_list = QListWidget()
        self.teams_list.setStyleSheet(
            "background:#151a26;border:none;color:#e6ebf5;font-size:12px;"
        )
        self.teams_list.itemSelectionChanged.connect(self.on_team_selected)
        teams_layout.addWidget(self.teams_list, 1)

        self.team_id_edit = QLineEdit()
        self.team_id_edit.setPlaceholderText(t("teams.id_placeholder"))
        self.team_id_edit.setStyleSheet(
            "background:#151a26;border:1px solid #2e3950;border-radius:8px;"
            "color:#e6ebf5;padding:6px 8px;"
        )
        teams_layout.addWidget(self.team_id_edit)

        self.workspace_edit = QLineEdit()
        self.workspace_edit.setPlaceholderText(t("teams.workspace_placeholder"))
        self.workspace_edit.setStyleSheet(
            "background:#151a26;border:1px solid #2e3950;border-radius:8px;"
            "color:#e6ebf5;padding:6px 8px;"
        )
        teams_layout.addWidget(self.workspace_edit)

        teams_row = QHBoxLayout()
        teams_row.setSpacing(6)
        self.btn_browse = QPushButton(t("teams.browse"))
        self.btn_browse.clicked.connect(self.on_browse_workspace)
        self.btn_save_team = QPushButton(t("teams.save"))
        self.btn_save_team.setStyleSheet(
            "background:#ffb45e;color:#241a08;border:none;border-radius:8px;"
            "padding:6px 14px;font-weight:600;"
        )
        self.btn_save_team.clicked.connect(self.on_save_team)
        self.btn_export = QPushButton(t("teams.export"))
        self.btn_export.clicked.connect(self.on_export_team)
        self.btn_import = QPushButton(t("teams.import"))
        self.btn_import.clicked.connect(self.on_import_team)
        for button in (self.btn_export, self.btn_import):
            button.setStyleSheet(
                "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
                "border-radius:8px;padding:6px 12px;"
            )
            teams_row.addWidget(button)
        teams_row.addWidget(self.btn_browse)
        teams_row.addWidget(self.btn_save_team)
        teams_layout.addLayout(teams_row)

        # Approvals page: decisions that block an agent.
        approvals_page = QWidget()
        approvals_layout = QVBoxLayout(approvals_page)
        approvals_layout.setContentsMargins(8, 8, 8, 8)
        approvals_layout.setSpacing(6)

        self.approvals_list = QListWidget()
        self.approvals_list.setStyleSheet(
            "background:#151a26;border:none;color:#e6ebf5;font-size:12px;"
        )
        approvals_layout.addWidget(self.approvals_list, 1)

        approvals_row = QHBoxLayout()
        approvals_row.setSpacing(6)
        self.btn_approve = QPushButton(t("approvals.approve"))
        self.btn_approve.setStyleSheet(
            "background:#6fcf97;color:#10241a;border:none;border-radius:8px;"
            "padding:6px 14px;font-weight:600;"
        )
        self.btn_approve.clicked.connect(lambda: self.resolve_approval(True))
        self.btn_reject = QPushButton(t("approvals.reject"))
        self.btn_reject.setStyleSheet(
            "background:#e8756a;color:#2a0d0a;border:none;border-radius:8px;"
            "padding:6px 14px;font-weight:600;"
        )
        self.btn_reject.clicked.connect(lambda: self.resolve_approval(False))
        approvals_row.addWidget(self.btn_approve)
        approvals_row.addWidget(self.btn_reject)
        approvals_layout.addLayout(approvals_row)

        self.tabs.addTab(staff_page, t("tab.staff"))
        self.tabs.addTab(self.board_view, t("tab.tasks"))
        self.tabs.addTab(approvals_page, t("tab.approvals"))

        # Inbox page: messages from the office, with an unread count.
        inbox_page = QWidget()
        inbox_layout = QVBoxLayout(inbox_page)
        inbox_layout.setContentsMargins(8, 8, 8, 8)
        inbox_layout.setSpacing(6)
        self.inbox_view = QTextEdit()
        self.inbox_view.setReadOnly(True)
        self.inbox_view.setStyleSheet(
            "background:#151a26;border:none;color:#e6ebf5;font-size:12px;"
        )
        inbox_layout.addWidget(self.inbox_view, 1)
        self.btn_mark_read = QPushButton(t("inbox.mark_read"))
        self.btn_mark_read.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:6px 12px;"
        )
        self.btn_mark_read.clicked.connect(self.mark_inbox_read)
        inbox_layout.addWidget(self.btn_mark_read)
        self.tabs.addTab(inbox_page, t("tab.inbox"))

        # Routines page: work that runs on a schedule.
        routines_page = QWidget()
        routines_layout = QVBoxLayout(routines_page)
        routines_layout.setContentsMargins(8, 8, 8, 8)
        routines_layout.setSpacing(6)

        self.routines_list = QListWidget()
        self.routines_list.setStyleSheet(
            "background:#151a26;border:none;color:#e6ebf5;font-size:12px;"
        )
        routines_layout.addWidget(self.routines_list, 1)

        self.routine_name = QLineEdit()
        self.routine_name.setPlaceholderText(t("routines.name"))
        self.routine_prompt = QLineEdit()
        self.routine_prompt.setPlaceholderText(t("routines.prompt"))
        self.routine_every = QLineEdit("60")
        self.routine_every.setPlaceholderText(t("routines.every"))
        self.routine_cron = QLineEdit()
        self.routine_cron.setPlaceholderText(t("routines.cron"))
        for field_edit in (self.routine_name, self.routine_prompt, self.routine_every,
                           self.routine_cron):
            field_edit.setStyleSheet(
                "background:#151a26;border:1px solid #2e3950;border-radius:8px;"
                "color:#e6ebf5;padding:6px 8px;font-size:12px;"
            )
            routines_layout.addWidget(field_edit)

        routine_actions = QHBoxLayout()
        routine_actions.setSpacing(6)
        self.btn_routine_add = QPushButton(t("routines.add"))
        self.btn_routine_add.clicked.connect(self.on_add_routine)
        self.btn_routine_run = QPushButton(t("routines.run"))
        self.btn_routine_run.clicked.connect(self.on_run_routine)
        self.btn_routine_delete = QPushButton(t("routines.delete"))
        self.btn_routine_delete.clicked.connect(self.on_delete_routine)
        for button in (self.btn_routine_add, self.btn_routine_run, self.btn_routine_delete):
            button.setStyleSheet(
                "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
                "border-radius:8px;padding:6px 12px;font-size:12px;"
            )
            routine_actions.addWidget(button)
        routines_layout.addLayout(routine_actions)
        self.tabs.addTab(routines_page, t("tab.routines"))
        platforms_page = QWidget()
        platforms_layout = QVBoxLayout(platforms_page)
        platforms_layout.setContentsMargins(8, 8, 8, 8)
        platforms_layout.setSpacing(6)
        self.providers_list.setStyleSheet(
            "background:#151a26;border:none;color:#e6ebf5;font-size:12px;"
        )
        platforms_layout.addWidget(self.providers_list, 1)
        self.btn_set_key = QPushButton(t("platforms.set_key"))
        self.btn_set_key.setStyleSheet(
            "background:#222a3d;color:#e6ebf5;border:1px solid #2e3950;"
            "border-radius:8px;padding:6px 12px;"
        )
        self.btn_set_key.clicked.connect(self.on_set_key)
        platforms_layout.addWidget(self.btn_set_key)
        self.tabs.addTab(platforms_page, t("tab.platforms"))
        self.tabs.addTab(teams_page, t("tab.teams"))
        self.tabs.addTab(chat_page, t("tab.chat"))
        self.tabs.addTab(self.memory_list, t("tab.memory"))
        self.tabs.addTab(self.costs_list, t("tab.cost"))

        panel_layout.addWidget(self.tabs)
        self.splitter.addWidget(self.panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([1040, 400])

        outer.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

    def toggle_sidebar(self) -> None:
        visible = not self.panel.isVisible()
        self.panel.setVisible(visible)
        self.btn_sidebar.setText(
            t("toolbar.hide_panel") if visible else t("toolbar.show_panel")
        )

    # ------------------------------------------------------------- actions

    def on_new_conversation(self) -> None:
        dialog = NewConversationDialog(self.providers, first_employee=not self.roles, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        if not payload["id"]:
            QMessageBox.warning(self, "BotOffice", t("msg.need_name"))
            return
        if payload["runtime"] == "builtin" and not payload["provider"]:
            QMessageBox.warning(self, "BotOffice", t("msg.need_provider"))
            return
        self.office.post("/api/employees", payload, self.on_employee_created)

    def on_employee_created(self, result: Any) -> None:
        if isinstance(result, dict) and result.get("error"):
            QMessageBox.warning(self, "BotOffice", result["error"])
            return
        self.refresh_all()
        if isinstance(result, dict) and result.get("rank") == "lead":
            self.append_chat(
                t("msg.system"),
                t("msg.became_lead", name=result.get("name", "")),
            )

    def on_add_role(self) -> None:
        dialog = AddRoleDialog(self.providers, self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        if not payload["id"]:
            QMessageBox.warning(self, "BotOffice", t("msg.need_name"))
            return
        self.office.post("/api/roles", payload, self.on_role_created)

    def on_role_created(self, result: Any) -> None:
        if isinstance(result, dict) and result.get("error"):
            QMessageBox.warning(self, "BotOffice", result["error"])
            return
        self.refresh_all()

    def on_provider_created(self, result: Any) -> None:
        if isinstance(result, dict) and result.get("error"):
            QMessageBox.warning(self, "BotOffice", result["error"])
            return
        self.refresh_all()

    def on_add_provider(self) -> None:
        dialog = AddProviderDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        if not payload["id"] or not payload["model"]:
            QMessageBox.warning(self, "BotOffice", t("msg.need_id_model"))
            return
        self.office.post("/api/providers", payload, self.on_provider_created)

    def on_add_me(self) -> None:
        """Put the user's own character into the office."""
        self.office.post("/api/boss", {}, self.on_employee_created)

    def on_drop(self, from_id: str, to_id: str) -> None:
        """The user dragged one avatar onto another: ask them to talk."""
        self.office.post(
            "/api/interactions/interact",
            {"from_id": from_id, "to_id": to_id, "note": ""},
            self.on_interaction_done,
        )

    def on_interaction_done(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        for message in result.get("messages", []):
            name = self._display_name(message.get("from", ""))
            self.append_chat(name, message.get("text", ""))
        self.tabs.setCurrentIndex(self.TAB_CHAT)
        self.refresh_costs()

    def _display_name(self, role_id: str) -> str:
        for role in self.roles:
            if role.get("id") == role_id:
                return role.get("name", role_id)
        return role_id

    def _display_tag(self, role: dict) -> str:
        """The name tag above a character: nickname-role-model, e.g. Bob-Dev-DSF."""
        if role.get("kind") == "user":
            return "You"
        name = role.get("name") or role.get("id", "")
        return f"{name}-{self._role_short(role.get('role', ''))}-{self._model_short(role)}"

    @staticmethod
    def _role_short(role_text: str) -> str:
        lowered = (role_text or "").lower()
        for needle, code in ROLE_SHORTS:
            if needle in lowered:
                return code
        first = (role_text or "").strip().split(" ")[0]
        return first[:3].capitalize() if first else "Emp"

    def _model_short(self, role: dict) -> str:
        provider_id = role.get("llm", {}).get("primary", "")
        if not provider_id:
            runtime = (role.get("external") or {}).get("runtime", "")
            return "EXT" if runtime else "---"
        for provider in self.providers:
            if provider.get("id") == provider_id:
                return provider.get("short") or provider_id[:3].upper()
        return provider_id[:3].upper()

    def append_chat(self, who: str, text: str) -> None:
        self.chat_lines.append((who, text))
        self.chat_view.append(
            f"<b style='color:#ffb45e'>{html_lib.escape(who)}</b>: {html_lib.escape(text)}"
        )

    # ---------------------------------------------------- model and actions

    def _fill_model_box(self) -> None:
        self.model_box.blockSignals(True)
        current = self.model_box.currentData()
        self.model_box.clear()
        for provider in self.providers:
            self.model_box.addItem(
                provider.get("label") or provider["id"], provider["id"]
            )
        index = self.model_box.findData(current)
        if index >= 0:
            self.model_box.setCurrentIndex(index)
        self.model_box.blockSignals(False)

    def on_model_changed(self, index: int) -> None:
        provider_id = self.model_box.currentData()
        if not self.selected_agent or not provider_id:
            return
        self.office.post(
            f"/api/roles/{self.selected_agent}/model",
            {"primary": provider_id},
            lambda _result: self.refresh_all(),
        )

    def on_duplicate_agent(self) -> None:
        if not self.selected_agent:
            return
        self.office.post(
            f"/api/roles/{self.selected_agent}/duplicate",
            {},
            lambda _result: self.refresh_all(),
        )

    def on_hide_agent(self) -> None:
        if not self.selected_agent:
            return
        hidden = not self._agent_hidden()
        self.office.post(
            f"/api/roles/{self.selected_agent}/hide",
            {"hidden": hidden},
            lambda _result: self.refresh_all(),
        )

    def _agent_hidden(self) -> bool:
        for role in self.roles:
            if role.get("id") == self.selected_agent:
                return bool(role.get("hidden"))
        return False

    # --------------------------------------------------------- group chat

    def refresh_groups(self) -> None:
        self.office.get("/api/groups", self.on_groups)

    def on_groups(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        current = self.group_box.currentData()
        self.group_box.blockSignals(True)
        self.group_box.clear()
        self.group_box.addItem(t("chat.group_none"), "")
        for group in data.get("groups", []):
            self.group_box.addItem(group.get("name") or group.get("id"), group.get("id"))
        index = self.group_box.findData(current)
        if index >= 0:
            self.group_box.setCurrentIndex(index)
        self.group_box.blockSignals(False)

    def on_group_selected(self, index: int) -> None:
        self.selected_group = self.group_box.currentData() or ""

    def on_new_group(self) -> None:
        name, ok = QInputDialog.getText(self, t("chat.group_new"), t("chat.group_name"))
        if not ok or not name.strip():
            return
        members, ok = QInputDialog.getText(
            self, t("chat.group_new"), t("chat.group_members")
        )
        if not ok or not members.strip():
            return
        participant_ids = [
            item.strip()
            for item in members.replace(";", ",").split(",")
            if item.strip()
        ]
        self.office.post(
            "/api/groups",
            {"name": name.strip(), "participant_ids": participant_ids},
            lambda _result: self.refresh_groups(),
        )

    def on_set_key(self) -> None:
        provider = self.providers_list.currentItem()
        if provider is None:
            return
        index = self.providers_list.row(provider)
        if index >= len(self.providers):
            return
        target = self.providers[index]
        key, ok = QInputDialog.getText(
            self,
            t("platforms.set_key"),
            t("platforms.key_prompt", name=target.get("label") or target.get("id")),
            QLineEdit.Password,
        )
        if not ok or not key:
            return
        self.office.post(
            f"/api/providers/{target.get('id')}/key",
            {"api_key": key},
            lambda _result: self.refresh_all(),
        )

    def on_export_team(self) -> None:
        item = self.teams_list.currentItem()
        if item is None:
            return
        team = item.data(Qt.UserRole) or {}
        team_id = team.get("id") or "general"
        self.office.get(f"/api/teams/{team_id}/export", lambda data: self._save_team_file(data))

    def _save_team_file(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("teams.export"), data.get("filename", "team.md"), "Markdown (*.md)"
        )
        if not path:
            return
        Path(path).write_text(data.get("markdown", ""), encoding="utf-8")

    def on_import_team(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("teams.import"), "", "Markdown (*.md)"
        )
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        self.office.post(
            "/api/teams/import",
            {"markdown": text},
            lambda _result: self.refresh_all(),
        )

    # ---------------------------------------------------------------- chat

    def on_avatar_clicked(self, role_id: str) -> None:
        """The user clicked a character: open a conversation with them."""
        self.selected_agent = role_id
        self.chat_header.setText(t("chat.with", name=self._tag_for(role_id)))
        self.tabs.setCurrentIndex(self.TAB_CHAT)
        self.chat_input.setFocus()
        self.refresh_agent_log(role_id)

    def refresh_agent_log(self, role_id: str) -> None:
        self.office.get(f"/api/agents/{role_id}/log?limit=80", self.on_agent_log)

    def on_agent_log(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        rows = []
        for entry in data.get("log", []):
            stamp = time.strftime("%H:%M:%S", time.localtime(entry.get("ts") or 0))
            rows.append(
                f"<span style='color:#5c6a82'>{stamp}</span> "
                f"<span style='color:#c7d0de'>{html_lib.escape(str(entry.get('text', '')))}</span>"
            )
        self.agent_log_view.setHtml("<br>".join(rows) or "<span style='color:#5c6a82'>—</span>")

    def _tag_for(self, role_id: str) -> str:
        for role in self.roles:
            if role.get("id") == role_id:
                return self._display_tag(role)
        return role_id

    def on_send(self) -> None:
        text = self.chat_input.text().strip()
        if not text:
            return
        if not self.selected_agent and not self.selected_group:
            self.append_chat(t("msg.system"), t("chat.no_target"))
            return
        self.chat_input.clear()
        self.append_chat(t("chat.you"), text)
        if self.selected_group:
            self.office.post(
                f"/api/groups/{self.selected_group}/message",
                {"text": text, "speaker": t("chat.you")},
                self.on_group_replies,
            )
            return
        self.office.post(
            f"/api/agents/{self.selected_agent}/say",
            {"text": text},
            self.on_agent_reply,
        )

    def on_group_replies(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        if result.get("error"):
            self.append_chat(t("msg.system"), result["error"])
            return
        for reply in result.get("replies", []):
            self.append_chat(
                self._display_name(reply.get("from", "")), reply.get("text", "")
            )
        self.refresh_costs()

    def on_agent_reply(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        if result.get("error"):
            self.append_chat(t("msg.system"), result["error"])
            return
        self.append_chat(
            self._display_name(result.get("from", "")),
            result.get("text", ""),
        )
        self.refresh_costs()

    # -------------------------------------------------------------- refresh

    def refresh_all(self) -> None:
        path = "/api/status"
        if self.current_team:
            path += f"?team={self.current_team}"
        self.office.get(path, self.on_status)

    def on_team_changed(self, index: int) -> None:
        team = self.team_box.itemData(index)
        if not team:
            return
        self.current_team = team
        self.selected_agent = None
        self.chat_header.setText(t("chat.no_target"))
        self.refresh_all()

    def _sync_team_box(self, teams: list[str], current: str) -> None:
        existing = [self.team_box.itemData(i) for i in range(self.team_box.count())]
        if existing != teams:
            self.team_box.blockSignals(True)
            self.team_box.clear()
            for team in teams:
                self.team_box.addItem(team, team)
            self.team_box.blockSignals(False)
        index = self.team_box.findData(current)
        if index >= 0 and index != self.team_box.currentIndex():
            self.team_box.blockSignals(True)
            self.team_box.setCurrentIndex(index)
            self.team_box.blockSignals(False)
        self.current_team = current

    def on_status(self, status: Any) -> None:
        if not isinstance(status, dict):
            return
        self.roles = status.get("roles", [])
        self.providers = status.get("providers", [])
        self._sync_team_box(
            status.get("teams") or ["general"],
            status.get("team") or "general",
        )
        self._fill_providers()
        self._sync_scene(status)
        self.refresh_staff()
        self.stat_agents.setText(t("stat.agents", count=len(self.roles)))
        self.stat_cost.setText(t("stat.cost", value=f"{status.get('total_cost', 0):.4f}"))
        self.refresh_memory()
        self.refresh_costs()
        self.refresh_board()
        self.refresh_teams()
        self.refresh_approvals()
        self.refresh_inbox()
        self.refresh_routines()
        self.refresh_groups()
        self.refresh_tool_chips()

    def _fill_providers(self) -> None:
        self.providers_list.clear()
        for provider in self.providers:
            item = QListWidgetItem(
                f"{provider.get('label') or provider['id']}  ({provider.get('protocol')})\n"
                f"{t('field.model')}: {provider.get('model')}"
            )
            self.providers_list.addItem(item)
        self._fill_model_box()

    def _sync_scene(self, status: dict) -> None:
        """Place every role at the desk the backend assigned.

        The authoritative desks come from layout.desks; the per-role "desk"
        field is only a convenience copy and may lag behind.
        """
        layout = status.get("layout", {})
        self.scene_widget.scene.set_landmarks(layout)
        desks = layout.get("desks", {})
        self.scene_widget.scene.set_desks(desks)
        for index, role in enumerate(self.roles):
            desk = desks.get(role["id"]) or role.get("desk") or [0.0, 0.0]
            color_index = AVATAR_COLOR_INDEX.get(role.get("avatar", ""), index)
            kind = role.get("kind", "builtin")
            runtime = (role.get("external") or {}).get("runtime", "")
            is_new = role["id"] not in self.scene_widget.scene.avatars
            avatar = self.scene_widget.scene.ensure_avatar(
                role["id"],
                role.get("name", role["id"]),
                desk,
                color_index,
                kind=kind,
                runtime=runtime,
                tag=self._display_tag(role),
                rank=role.get("rank") or ("lead" if role.get("leader") else "member"),
            )
            if is_new:
                # New employees come in through the front door and walk to
                # their desk, so hiring is visible in the room.
                entrance = self.scene_widget.scene.entrance
                avatar.x = float(entrance[0])
                avatar.z = float(entrance[1])
                avatar.move_to(float(desk[0]), float(desk[1]))
            elif avatar.state == "idle" and not avatar.walking:
                avatar.x = float(desk[0])
                avatar.z = float(desk[1])
                avatar.target_x = float(desk[0])
                avatar.target_z = float(desk[1])
        for role_id in list(self.scene_widget.scene.avatars):
            if not any(r["id"] == role_id for r in self.roles):
                self.scene_widget.scene.remove_avatar(role_id)
        self.last_total_cost = float(status.get("total_cost", 0))
        self.refresh_stats()
        self.scene_widget.update()

    def refresh_stats(self) -> None:
        """Keep the wall board in step with the scene.

        The staff panel refreshes on every state change, so the board has to
        as well, otherwise the two disagree while an agent works.
        """
        states = [
            avatar.state for avatar in self.scene_widget.scene.avatars.values()
        ]
        self.scene_widget.scene.set_stats({
            "working": sum(1 for state in states if state in ACTIVE_STATES),
            "waiting": sum(1 for state in states if state == "waiting"),
            "idle": sum(1 for state in states if state == "idle"),
            "offline": sum(1 for state in states if state == "offline"),
            "cost": self.last_total_cost,
        })
        self.scene_widget.update()

    # ---------------------------------------------------------------- staff

    def refresh_staff(self) -> None:
        scene = self.scene_widget.scene
        states = [avatar.state for avatar in scene.avatars.values()]
        working = sum(1 for state in states if state in ACTIVE_STATES)
        waiting = sum(1 for state in states if state == "waiting")
        idle = sum(1 for state in states if state == "idle")
        offline = sum(1 for state in states if state == "offline")
        self.counts_label.setText(
            t("staff.counts", working=working, waiting=waiting, idle=idle, offline=offline)
        )

        rows = []
        for role in self.roles:
            avatar = scene.avatars.get(role["id"])
            state = (avatar.state if avatar else "idle").lower()
            color = STATE_HEX.get(state, STATE_HEX["idle"])
            label = t(f"state.{state}") if f"state.{state}" in STATE_HEX else state
            rank = role.get("rank") or ("lead" if role.get("leader") else "member")
            kind = role.get("kind", "builtin")
            runtime = (role.get("external") or {}).get("runtime", "")
            model = role.get("llm", {}).get("primary") or runtime or t("msg.no_model")
            name = html_lib.escape(str(role.get("name", "")))
            role_name = html_lib.escape(str(role.get("role") or t("msg.no_role")))
            action = html_lib.escape(str(role.get("action") or ""))
            usage = role.get("usage") or {}
            gauge = self._gauge_html(int(usage.get("tokens") or 0), int(usage.get("limit") or 0))
            action_html = (
                f"<br><span style='color:#8fa0b8;font-size:11px;'>{action}</span>"
                if action else ""
            )
            rows.append(
                "<tr>"
                f"<td width='14' valign='top' style='padding:7px 6px 7px 0;'>"
                f"<span style='color:{color};font-size:14px;'>●</span></td>"
                f"<td style='padding:7px 0;'>"
                f"<b style='color:#e6ebf5;'>{name}</b>"
                f"<span style='color:#93a0b8;'> · {role_name}</span><br>"
                f"<span style='color:#6f7d93;font-size:11px;'>"
                f"{html_lib.escape(rank)} · {html_lib.escape(kind)} · "
                f"{html_lib.escape(str(model))}</span>"
                f"{action_html}{gauge}"
                f"</td>"
                f"<td valign='top' align='right' style='padding:7px 0;'>"
                f"<span style='color:{color};font-size:11px;'>{label}</span></td>"
                "</tr>"
            )
        if rows:
            html = "<table width='100%' cellspacing='0'>" + "".join(rows) + "</table>"
        else:
            html = f"<p style='color:#93a0b8'>{t('staff.empty')}</p>"
        self.staff_view.setHtml(html)

    @staticmethod
    def _gauge_html(tokens: int, limit: int) -> str:
        """A small context gauge: eight cells, colour escalating as it fills."""
        if limit <= 0:
            return ""
        filled = max(0, min(8, round(tokens / limit * 8)))
        color = "#e8756a" if filled >= 7 else "#f2cd37" if filled >= 6 else "#5b8fd6"
        cells = "".join(
            f"<td style='width:9px;height:5px;background:"
            f"{color if index < filled else '#2e3950'};'></td>"
            for index in range(8)
        )
        return (
            f"<table cellspacing='1' cellpadding='0'><tr>{cells}</tr></table>"
            f"<span style='color:#6f7d93;font-size:10px;'>{tokens} / {limit}</span>"
        )

    def record_activity(self, event: dict) -> None:
        line = self._format_event(event)
        if not line:
            return
        self.activity_lines.insert(0, (time.strftime("%H:%M"), line))
        del self.activity_lines[60:]
        self.refresh_activity()

    def _format_event(self, event: dict) -> str:
        event_type = event.get("type")
        name = self._display_name
        if event_type == "agent.say":
            text = str(event.get("text", ""))[:70]
            return f"{name(event.get('id', ''))}: {text}"
        if event_type == "task.created":
            return f"{name(event.get('leader', ''))} → {name(event.get('worker', ''))}"
        if event_type == "handoff.done":
            return f"{name(event.get('sender', ''))} handed off to {name(event.get('receiver', ''))}"
        if event_type == "meeting.started":
            return f"Meeting: {event.get('topic', '')}"
        if event_type == "interact.started":
            return f"{name(event.get('id', ''))} talks to {name(event.get('peer', ''))}"
        if event_type == "employee.hired":
            return f"{event.get('name', '')} joined the office"
        if event_type == "agent.tool_call":
            return f"{name(event.get('id', ''))} used {event.get('tool', '')}"
        if event_type == "memory.write":
            return f"{name(event.get('author', ''))} wrote [{event.get('scope', '')}]"
        return ""

    def refresh_activity(self) -> None:
        if not self.activity_lines:
            self.activity_view.setHtml(
                f"<p style='color:#5c6a82'>{t('staff.no_activity')}</p>"
            )
            return
        rows = "".join(
            f"<p style='margin:3px 0;'>"
            f"<span style='color:#5c6a82;'>{stamp}</span> "
            f"<span style='color:#c7d0de;'>{html_lib.escape(line)}</span></p>"
            for stamp, line in self.activity_lines[:40]
        )
        self.activity_view.setHtml(rows)

    # ------------------------------------------------------- other panels

    # -------------------------------------------------------------- chips

    def refresh_tool_chips(self) -> None:
        self.office.get("/api/tools/recent?limit=12", self.on_tool_chips)

    def on_tool_chips(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        items = data.get("tools", [])
        if not items:
            self.tool_chips.setText(t("chat.tools_empty"))
            return
        chips = []
        for item in items:
            tool = html_lib.escape(str(item.get("tool", "")))
            who = html_lib.escape(self._display_name(str(item.get("id", ""))))
            chips.append(
                f"<span style='background:#1f2b4a;border:1px solid #2e3950;"
                f"border-radius:999px;padding:2px 9px;margin-right:5px;"
                f"color:#c7d0de;'>{tool}"
                f"<span style='color:#5c6a82;'> · {who}</span></span>"
            )
        self.tool_chips.setText("".join(chips))

    # --------------------------------------------------------------- inbox

    def refresh_inbox(self) -> None:
        self.office.get("/api/inbox", self.on_inbox)

    def on_inbox(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        messages = data.get("messages", [])
        unread = int(data.get("unread") or 0)
        self.tabs.setTabText(
            self.TAB_INBOX,
            t("tab.inbox") + (f" ({unread})" if unread else ""),
        )
        if not messages:
            self.inbox_view.setHtml(f"<p style='color:#93a0b8'>{t('inbox.empty')}</p>")
            return
        rows = "".join(
            f"<p style='margin:4px 0;'>"
            f"<b style='color:#ffb45e'>{html_lib.escape(str(m.get('sender', '')))}</b>: "
            f"{html_lib.escape(str(m.get('text', '')))}</p>"
            for m in messages[:80]
        )
        self.inbox_view.setHtml(rows)

    def mark_inbox_read(self) -> None:
        self.office.post("/api/inbox/read", {}, lambda _result: self.refresh_inbox())

    # ------------------------------------------------------------ routines

    def refresh_routines(self) -> None:
        self.office.get("/api/routines", self.on_routines)

    def on_routines(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        self.routines_list.clear()
        for routine in data.get("routines", []):
            schedule = (
                f"every {routine.get('every_minutes')} min"
                if routine.get("every_minutes")
                else (f"at {routine.get('at_hour'):02d}:{routine.get('at_minute'):02d}"
                      if routine.get("at_hour", -1) >= 0 else t("routines.disabled"))
            )
            item = QListWidgetItem(
                f"{routine.get('name')}  ·  {schedule}  ·  ran {routine.get('run_count', 0)}x"
            )
            item.setData(Qt.UserRole, routine.get("id"))
            self.routines_list.addItem(item)

    def on_add_routine(self) -> None:
        name = self.routine_name.text().strip()
        prompt = self.routine_prompt.text().strip()
        every = self.routine_every.text().strip() or "60"
        cron_text = self.routine_cron.text().strip()
        if not name or not prompt:
            QMessageBox.warning(self, "BotOffice", t("routines.empty"))
            return
        crons = [item.strip() for item in cron_text.split(";") if item.strip()]
        self.office.post(
            "/api/routines",
            {"name": name, "prompt": prompt, "every_minutes": int(every),
             "crons": crons},
            lambda _result: self.refresh_routines(),
        )

    def on_run_routine(self) -> None:
        item = self.routines_list.currentItem()
        if item is None:
            return
        routine_id = item.data(Qt.UserRole)
        if not routine_id:
            return
        self.office.post(
            f"/api/routines/{routine_id}/run", {}, lambda _result: self.refresh_routines()
        )

    def on_delete_routine(self) -> None:
        item = self.routines_list.currentItem()
        if item is None:
            return
        routine_id = item.data(Qt.UserRole)
        if not routine_id:
            return
        self.office.delete(
            f"/api/routines/{routine_id}", lambda _result: self.refresh_routines()
        )

    # ----------------------------------------------------------- approvals

    def refresh_approvals(self) -> None:
        self.office.get("/api/approvals", self.on_approvals)

    def on_approvals(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        self.approvals_list.clear()
        for item in data.get("approvals", []):
            entry = QListWidgetItem(
                f"{item.get('agent')} · {item.get('title')} — {item.get('detail', '')}"
            )
            entry.setData(Qt.UserRole, item.get("id"))
            self.approvals_list.addItem(entry)
        if not data.get("approvals"):
            self.approvals_list.addItem(QListWidgetItem(t("approvals.empty")))

    def resolve_approval(self, approved: bool) -> None:
        item = self.approvals_list.currentItem()
        if item is None:
            return
        approval_id = item.data(Qt.UserRole)
        if not approval_id:
            return
        self.office.post(
            f"/api/approvals/{approval_id}",
            {"approved": approved},
            lambda _result: self.refresh_approvals(),
        )

    # ---------------------------------------------------------------- teams

    def refresh_teams(self) -> None:
        self.office.get("/api/teams", self.on_teams)

    def on_teams(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        self.teams_list.clear()
        for team in data.get("teams", []):
            item = QListWidgetItem(f"{team.get('id')}  ·  {team.get('workspace', '')}")
            item.setData(Qt.UserRole, team)
            self.teams_list.addItem(item)

    def on_team_selected(self) -> None:
        item = self.teams_list.currentItem()
        if item is None:
            return
        team = item.data(Qt.UserRole) or {}
        self.team_id_edit.setText(team.get("id", ""))
        self.workspace_edit.setText(team.get("workspace", ""))

    def on_browse_workspace(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(self, t("teams.browse"))
        if path:
            self.workspace_edit.setText(path)

    def on_save_team(self) -> None:
        team_id = self.team_id_edit.text().strip()
        workspace = self.workspace_edit.text().strip()
        if not team_id or not workspace:
            QMessageBox.warning(self, "BotOffice", t("teams.need_both"))
            return
        self.office.post(
            "/api/teams",
            {"id": team_id, "workspace": workspace},
            self.on_team_saved,
        )

    def on_team_saved(self, result: Any) -> None:
        if isinstance(result, dict) and result.get("error"):
            QMessageBox.warning(self, "BotOffice", result["error"])
            return
        self.refresh_teams()
        self.refresh_all()

    def refresh_memory(self) -> None:
        self.office.get("/api/memory?limit=50", self.on_memory)

    def on_memory(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        self.memory_list.clear()
        for entry in data.get("entries", []):
            item = QListWidgetItem(f"[{entry.get('scope')}] {entry.get('text')}")
            item.setToolTip(f"by {entry.get('author')}")
            self.memory_list.addItem(item)

    def refresh_board(self) -> None:
        self.office.get("/api/tasks", self.on_tasks)

    def on_tasks(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        tasks = data.get("tasks", [])
        summary = data.get("summary", {})
        status_colors = {
            "queued": "#93a0b8",
            "assigned": "#ffb45e",
            "handed_off": "#5b8fd6",
            "meeting": "#4fb3bf",
            "chat": "#9b6bd1",
            "done": "#6fcf97",
        }
        rows = []
        for task in tasks:
            color = status_colors.get(task.get("status"), "#93a0b8")
            title = html_lib.escape(str(task.get("title") or task.get("id", "")))
            owner = html_lib.escape(str(task.get("worker") or task.get("leader") or ""))
            rows.append(
                f"<tr><td style='color:{color};padding:4px 6px;'>{task.get('status')}</td>"
                f"<td style='padding:4px 6px;'>{title}</td>"
                f"<td style='color:#93a0b8;padding:4px 6px;'>{owner}</td></tr>"
            )
        task_html = (
            "<table width='100%' cellspacing='0'>" + "".join(rows) + "</table>"
            if rows
            else f"<p style='color:#93a0b8'>{t('tasks.empty')}</p>"
        )

        html = (
            f"<h2 style='color:#ffb45e'>{t('tab.tasks')}</h2>"
            f"<p style='color:#93a0b8'>"
            f"{t('staff.counts', working=summary.get('total', 0), waiting='', idle='', offline='')}"
            f"</p>"
            + task_html
        )
        self.board_view.setHtml(html)

    def refresh_costs(self) -> None:
        self.office.get("/api/costs", self.on_costs)

    def on_costs(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        self.costs_list.clear()
        for row in data.get("rows", []):
            item = QListWidgetItem(
                f"{row.get('provider_id')} · {row.get('model')}\n"
                + t(
                    "cost.calls",
                    calls=row.get("calls"),
                    tokens_in=row.get("input_tokens"),
                    tokens_out=row.get("output_tokens"),
                    cost=row.get("cost"),
                    currency=row.get("currency"),
                )
            )
            self.costs_list.addItem(item)
        self.stat_cost.setText(t("stat.cost", value=f"{data.get('total', 0):.4f}"))
