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
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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
            "runtime": runtime,
            "provider": self.provider_box.currentData() if runtime == "builtin" else "",
            "responsibilities": self.resp_edit.toPlainText().strip(),
            "avatar": self.avatar_box.currentData(),
        }


class MainWindow(QMainWindow):
    """The BotOffice window."""

    TAB_STAFF = 0
    TAB_TASKS = 1
    TAB_PLATFORMS = 2
    TAB_CHAT = 3
    TAB_MEMORY = 4
    TAB_COST = 5

    def __init__(self, office) -> None:
        super().__init__()
        self.office = office
        self.setWindowTitle(t("app.title"))
        self.resize(1440, 880)

        self.roles: list[dict] = []
        self.providers: list[dict] = []
        self.chat_lines: list[tuple[str, str]] = []
        self.activity_lines: list[tuple[str, str]] = []

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
        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.memory_list = QListWidget()
        self.costs_list = QListWidget()
        for widget in (self.board_view, self.providers_list, self.chat_view,
                       self.memory_list, self.costs_list):
            widget.setStyleSheet(
                "background:#151a26;border:none;color:#e6ebf5;font-size:13px;"
            )

        self.tabs.addTab(staff_page, t("tab.staff"))
        self.tabs.addTab(self.board_view, t("tab.tasks"))
        self.tabs.addTab(self.providers_list, t("tab.platforms"))
        self.tabs.addTab(self.chat_view, t("tab.chat"))
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

    # -------------------------------------------------------------- refresh

    def refresh_all(self) -> None:
        self.office.get("/api/status", self.on_status)

    def on_status(self, status: Any) -> None:
        if not isinstance(status, dict):
            return
        self.roles = status.get("roles", [])
        self.providers = status.get("providers", [])
        self._fill_providers()
        self._sync_scene(status)
        self.refresh_staff()
        self.stat_agents.setText(t("stat.agents", count=len(self.roles)))
        self.stat_cost.setText(t("stat.cost", value=f"{status.get('total_cost', 0):.4f}"))
        self.refresh_memory()
        self.refresh_costs()
        self.refresh_board()

    def _fill_providers(self) -> None:
        self.providers_list.clear()
        for provider in self.providers:
            item = QListWidgetItem(
                f"{provider.get('label') or provider['id']}  ({provider.get('protocol')})\n"
                f"{t('field.model')}: {provider.get('model')}"
            )
            self.providers_list.addItem(item)

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
            if avatar.state == "idle" and not avatar.walking:
                avatar.x = float(desk[0])
                avatar.z = float(desk[1])
                avatar.target_x = float(desk[0])
                avatar.target_z = float(desk[1])
        for role_id in list(self.scene_widget.scene.avatars):
            if not any(r["id"] == role_id for r in self.roles):
                self.scene_widget.scene.remove_avatar(role_id)
        states = [avatar.state for avatar in self.scene_widget.scene.avatars.values()]
        self.scene_widget.scene.set_stats({
            "working": sum(1 for state in states if state in ACTIVE_STATES),
            "idle": sum(1 for state in states if state == "idle"),
            "cost": float(status.get("total_cost", 0)),
        })
        self.scene_widget.update()

    # ---------------------------------------------------------------- staff

    def refresh_staff(self) -> None:
        scene = self.scene_widget.scene
        states = [avatar.state for avatar in scene.avatars.values()]
        working = sum(1 for state in states if state in ACTIVE_STATES)
        idle = sum(1 for state in states if state == "idle")
        offline = sum(1 for state in states if state == "offline")
        self.counts_label.setText(
            t("staff.counts", working=working, idle=idle, offline=offline)
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
            f"{t('staff.counts', working=summary.get('total', 0), idle='', offline='')}"
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
