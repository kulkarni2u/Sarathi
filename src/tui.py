"""Sarathi terminal UI: chat-first home with a task dashboard mode.

`sarathi tui` opens a centered chat prompt. The first message docks the
conversation to the bottom of the screen; Ctrl+T flips between the chat
view and the task panel (run monitor, task browser, proposal review) at
any time. The task panel polls `.sarathi/tasks`, so it can watch runs
started elsewhere (CLI, MCP, service) without coordination.
"""
from __future__ import annotations

import json
import time

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static

try:
    from . import tui_data
except ImportError:
    # Support direct execution via sarathi.py, which prepends src/ to sys.path.
    import tui_data


SARATHI_BANNER = r"""
 ██████  █████  ██████   █████  ████████ ██   ██ ██
██      ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
 █████  ███████ ██████  ███████    ██    ███████ ██
     ██ ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
 ██████ ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
"""

CHAT_HELP = (
    "/run <description>  run a task through the policy-backed lifecycle\n"
    "                    (recent chat context is included automatically)\n"
    "/model [name]       show or switch the agent CLI used for chat\n"
    "/context [task_id]  attach a task's status to the conversation\n"
    "/tasks              switch to the task panel (Ctrl+T also toggles)\n"
    "/help               show this help\n"
    "/quit               exit Sarathi\n"
    "Anything else is sent to the agent CLI as conversation."
)

_OUTCOME_STYLES = {
    "pass": "green",
    "success": "green",
    "completed": "green",
    "fail": "bold red",
    "failed": "bold red",
    "error": "bold red",
    "unverified": "yellow",
    "skipped": "dim",
}

_RISK_STYLES = {"low": "green", "medium": "yellow", "high": "bold red"}

_DECISION_STYLES = {"accepted": "green", "rejected": "red"}


def _styled(text: object, styles: dict[str, str]) -> Text:
    value = str(text)
    return Text(value, style=styles.get(value.lower(), ""))


def _styled_phase(current_phase: str) -> Text:
    if current_phase == "Completed":
        return Text(current_phase, style="dim")
    return Text(current_phase, style="bold cyan")


def _short(text: object, width: int) -> str:
    flattened = " ".join(str(text).split())
    if len(flattened) <= width:
        return flattened
    return flattened[: width - 1] + "…"


def _format_snapshot(text: str) -> str:
    """Highlight the field labels in a `sarathi status` snapshot."""
    lines = []
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if sep and not line.startswith(" "):
            lines.append(f"[bold cyan]{escape(key)}:[/]{escape(rest)}")
        else:
            lines.append(escape(line))
    return "\n".join(lines)


def _styled_log_line(line: str) -> Text:
    """Phase-log entry as `timestamp phase status` with a status color."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        entry = None
    if not isinstance(entry, dict):
        return Text(line)
    timestamp = str(entry.get("timestamp", ""))[:19].replace("T", " ")
    status = str(entry.get("status", ""))
    style = ""
    lowered = status.lower()
    if lowered in _OUTCOME_STYLES:
        style = _OUTCOME_STYLES[lowered]
    elif lowered == "started":
        style = "cyan"
    text = Text()
    text.append(timestamp, style="dim")
    text.append("  ")
    text.append(str(entry.get("phase", "")), style="bold")
    text.append("  ")
    text.append(status, style=style)
    return text


def _discover_policy_pack() -> str | None:
    try:
        from .cli import discover_policy_pack
    except ImportError:
        from cli import discover_policy_pack
    return discover_policy_pack()


class NewTaskScreen(ModalScreen):
    """Prompt for a task description to run through the lifecycle."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="new-task-dialog"):
            yield Static("[b]New task[/b] — describe it and press Enter")
            yield Input(
                placeholder="e.g. Fix null pointer in user service",
                id="new-task-input",
            )
            yield Static("[dim]Complexity is auto-detected; Esc cancels.[/dim]")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProposalsScreen(Screen):
    """Review policy proposals: accept into the policy pack or reject."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("a", "accept", "Accept"),
        Binding("x", "reject", "Reject"),
        Binding("r", "reload", "Reload"),
    ]

    def __init__(self, persistence) -> None:
        super().__init__()
        self.persistence = persistence
        self.proposals: list = []
        self.selected_id: str | None = None
        self.decided: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="proposals")
        yield Static("Loading proposals…", id="proposal-detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#proposals", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Risk", "Conf", "Target", "Title", "Decision")
        self.action_reload()

    def action_reload(self) -> None:
        self.proposals = tui_data.load_proposals(self.persistence)
        table = self.query_one("#proposals", DataTable)
        table.clear()
        for proposal in self.proposals:
            artifact = proposal.to_artifact()
            table.add_row(
                Text(artifact["id"], style="dim"),
                _styled(artifact["risk_level"], _RISK_STYLES),
                f"{artifact['confidence']:.2f}",
                Text(artifact["policy_file"], style="cyan"),
                _short(artifact["title"], 60),
                _styled(self.decided.get(artifact["id"], ""), _DECISION_STYLES),
                key=artifact["id"],
            )
        if not self.proposals:
            self.query_one("#proposal-detail", Static).update(
                "No policy proposals from persisted learnings."
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        self.selected_id = event.row_key.value
        self._show_detail()

    def _selected_proposal(self):
        for proposal in self.proposals:
            if proposal.proposal_id == self.selected_id:
                return proposal
        return None

    def _show_detail(self) -> None:
        proposal = self._selected_proposal()
        detail = self.query_one("#proposal-detail", Static)
        if proposal is None:
            detail.update("")
            return
        artifact = proposal.to_artifact()
        lines = [
            f"[b]{escape(artifact['title'])}[/b]",
            "Target: {}   Kind: {}   Risk: {}   Confidence: {:.2f}".format(
                escape(artifact["policy_file"]),
                escape(artifact["proposal_kind"]),
                escape(artifact["risk_level"]),
                artifact["confidence"],
            ),
            "",
            f"Rationale: {escape(artifact['rationale'])}",
            "",
            "Suggested change:",
            escape(artifact["suggested_change"]),
            "",
            "Evidence: " + escape(", ".join(artifact["evidence_refs"]) or "none"),
        ]
        decision = self.decided.get(artifact["id"])
        if decision:
            lines.insert(0, f"[reverse] {escape(decision)} [/reverse]")
        detail.update("\n".join(lines))

    def action_accept(self) -> None:
        self._decide(accept=True)

    def action_reject(self) -> None:
        self._decide(accept=False)

    def _decide(self, *, accept: bool) -> None:
        proposal = self._selected_proposal()
        if proposal is None:
            self.notify("No proposal selected.", severity="warning")
            return
        policy_pack = _discover_policy_pack()
        if not policy_pack:
            self.notify(
                "No policy pack found — run `sarathi init` first.", severity="error"
            )
            return
        decision = tui_data.decide_proposal(
            proposal, accept=accept, policy_pack=policy_pack
        )
        self.decided[decision["id"]] = decision["status"]
        if accept:
            self.notify(f"Accepted {decision['id']} -> {decision['policy_file']}")
        else:
            self.notify(f"Rejected {decision['id']}")
        self.action_reload()
        self._show_detail()


class ChatScreen(Screen):
    """Chat-first home: centered prompt that docks once conversation starts."""

    def __init__(self) -> None:
        super().__init__()
        self.session = tui_data.ChatSession()

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-home"):
            yield Static(SARATHI_BANNER, id="chat-banner")
            yield Static("─── guiding systems ───", id="chat-tagline")
            yield Input(
                placeholder="Ask anything — or /run <task>, /tasks, /help",
                id="chat-input-home",
            )
            yield Static("", id="chat-provider")
        with Vertical(id="chat-active"):
            yield VerticalScroll(id="chat-thread")
            yield Input(
                placeholder="Message — /run <task>, /tasks, /help",
                id="chat-input",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.app.chat_screen = self
        provider = self.session.resolve_provider()
        if provider:
            status = f"model: {provider[0]} ({provider[1]})"
        else:
            status = "no agent CLI on PATH (claude/opencode/codex) — tasks still run via Ctrl+T"
        self.query_one("#chat-provider", Static).update(f"[dim]{escape(status)}[/dim]")
        self.query_one("#chat-input-home", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        event.input.value = ""
        if not message:
            return
        if message.startswith("/"):
            self._handle_command(message)
            return
        self._activate_thread()
        self._append("you", message)
        pending = self._append("sarathi", "thinking…", pending=True)
        self.run_worker(
            lambda: self._deliver(message, pending),
            thread=True,
            exclusive=True,
            group="chat",
        )

    def _activate_thread(self) -> None:
        """Dock the conversation: hide the centered home, focus the bottom input."""
        if not self.has_class("-started"):
            self.add_class("-started")
        self.query_one("#chat-input", Input).focus()

    def _append(self, role: str, text: str, *, pending: bool = False) -> Static:
        thread = self.query_one("#chat-thread", VerticalScroll)
        label = "[bold cyan]you[/]" if role == "you" else "[bold magenta]sarathi[/]"
        body = f"[dim]{escape(text)}[/dim]" if pending else escape(text)
        widget = Static(f"{label}  {body}", classes=f"chat-msg {role}")
        thread.mount(widget)
        thread.scroll_end(animate=False)
        return widget

    def _system(self, text: str) -> None:
        self._activate_thread()
        thread = self.query_one("#chat-thread", VerticalScroll)
        thread.mount(Static(f"[dim]{escape(text)}[/dim]", classes="chat-msg system"))
        thread.scroll_end(animate=False)

    def _deliver(self, message: str, widget: Static) -> None:
        thread = self.query_one("#chat-thread", VerticalScroll)
        last_update = 0.0
        throttle_seconds = 0.05

        def on_text(partial: str) -> None:
            nonlocal last_update
            now = time.monotonic()
            if now - last_update < throttle_seconds:
                return
            last_update = now
            self.app.call_from_thread(
                widget.update, f"[bold magenta]sarathi[/]  {escape(partial)}"
            )
            self.app.call_from_thread(thread.scroll_end)

        reply = self.session.send_streaming(message, on_text=on_text)
        self.app.call_from_thread(
            widget.update, f"[bold magenta]sarathi[/]  {escape(reply)}"
        )
        self.app.call_from_thread(thread.scroll_end)

    def _transcript(self, max_turns: int = 6, max_chars: int = 500) -> str:
        """Recent chat history formatted as alternating user/assistant lines."""
        lines = []
        for user, assistant in self.session.history[-max_turns:]:
            lines.append(f"user: {user[:max_chars]}")
            lines.append(f"assistant: {assistant[:max_chars]}")
        return "\n".join(lines)

    def _handle_command(self, message: str) -> None:
        command, _, argument = message.partition(" ")
        command = command.lower()
        argument = argument.strip()
        if command in ("/tasks", "/panel"):
            self.app.action_toggle_mode()
        elif command == "/run":
            if not argument:
                self._system("Usage: /run <task description>")
            else:
                context = self._transcript() if self.session.history else None
                if self.app.launch_task(argument, context=context):
                    self._system(
                        f"Launched task: {argument} — watch it in the task panel (Ctrl+T)."
                    )
        elif command == "/model":
            self._handle_model_command(argument)
        elif command == "/context":
            self._handle_context_command(argument)
        elif command == "/help":
            self._system(CHAT_HELP)
        elif command in ("/quit", "/exit"):
            self.app.exit()
        else:
            self._system(f"Unknown command {command}. {CHAT_HELP}")

    def _handle_context_command(self, argument: str) -> None:
        if not argument:
            summaries = tui_data.task_summaries(self.app.persistence)
            if not summaries:
                self._system("No saved tasks.")
                return
            ids = ", ".join(summary["task_id"] for summary in summaries[:10])
            self._system(f"Usage: /context <task_id>. Available tasks: {ids}")
            return
        task_id = argument
        snapshot = tui_data.status_snapshot(self.app.persistence, task_id)
        if snapshot is None:
            summaries = tui_data.task_summaries(self.app.persistence)
            message = f"Task {task_id} not found."
            if summaries:
                ids = ", ".join(summary["task_id"] for summary in summaries[:10])
                message += f" Available tasks: {ids}"
            self._system(message)
            return
        self.session.add_context(f"Status of task {task_id}", snapshot)
        self._system(snapshot)
        self._system(
            "Added to conversation context — it will be sent with your next message."
        )

    def _handle_model_command(self, argument: str) -> None:
        providers = self.session.available_providers()
        if not argument:
            if not providers:
                self._system(
                    "No agent CLI found on PATH (looked for: claude, opencode, codex)."
                )
                return
            current = self.session.resolve_provider()
            current_name = current[0] if current else None
            parts = []
            for name, _path in providers:
                if name == current_name:
                    parts.append(f"{name} (current)")
                else:
                    parts.append(name)
            self._system(
                "Providers: " + ", ".join(parts) + ". Use /model <name> to switch."
            )
            return
        name = argument.strip().lower()
        if self.session.set_provider(name):
            self._system(f"Switched model to {name}.")
        else:
            choices = ", ".join(n for n, _ in providers) or "none detected"
            self._system(f"Unknown or unavailable provider {name!r}. Available: {choices}.")


class TasksScreen(Screen):
    """Task panel: live run monitor, task browser, proposal review."""

    BINDINGS = [
        Binding("q", "app.quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_task", "New task"),
        Binding("p", "proposals", "Proposals"),
        Binding("u", "resume", "Resume task"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_task_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="tasks")
            with Vertical(id="detail"):
                yield Static("No task selected.", id="snapshot")
                yield DataTable(id="phases")
                yield RichLog(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.selected_task_id = self.app.initial_task_id
        tasks = self.query_one("#tasks", DataTable)
        tasks.cursor_type = "row"
        tasks.add_columns("Task", "Phase", "Outcome", "Updated")
        phases = self.query_one("#phases", DataTable)
        phases.cursor_type = "none"
        phases.add_columns("Phase", "Agent", "Outcome", "Iter", "Error")
        self.refresh_data()
        self.set_interval(self.app.refresh_interval, self.refresh_data)

    def refresh_data(self) -> None:
        summaries = tui_data.task_summaries(self.app.persistence)
        table = self.query_one("#tasks", DataTable)
        table.clear()
        known: set[str] = set()
        for summary in summaries:
            known.add(summary["task_id"])
            table.add_row(
                _short(summary["task_id"], 20),
                _styled_phase(summary["current_phase"]),
                _styled(_short(summary["last_outcome"], 14), _OUTCOME_STYLES),
                Text(str(summary["last_updated"])[5:16].replace("T", " "), style="dim"),
                key=summary["task_id"],
            )
        if self.selected_task_id not in known:
            self.selected_task_id = summaries[0]["task_id"] if summaries else None
        if self.selected_task_id is not None:
            table.move_cursor(row=table.get_row_index(self.selected_task_id))
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        snapshot = self.query_one("#snapshot", Static)
        phases = self.query_one("#phases", DataTable)
        log = self.query_one("#log", RichLog)
        phases.clear()
        log.clear()
        if self.selected_task_id is None:
            snapshot.update("No saved tasks. Run `sarathi run \"…\"` first.")
            return
        text = tui_data.status_snapshot(self.app.persistence, self.selected_task_id)
        snapshot.update(
            _format_snapshot(text) if text else f"Task {self.selected_task_id} not found."
        )
        for row in tui_data.phase_rows(self.app.persistence, self.selected_task_id):
            phases.add_row(
                Text(row["phase"], style="bold"),
                row["agent"],
                _styled(row["outcome"], _OUTCOME_STYLES),
                str(row["iterations"]),
                Text(_short(row["error"], 40), style="red"),
            )
        for line in tui_data.phase_log_tail(self.app.persistence, self.selected_task_id):
            log.write(_styled_log_line(line))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "tasks" or event.row_key is None:
            return
        value = event.row_key.value
        if value and value != self.selected_task_id:
            self.selected_task_id = value
            self._refresh_detail()

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_proposals(self) -> None:
        self.app.push_screen(ProposalsScreen(self.app.persistence))

    def action_new_task(self) -> None:
        def on_result(description: str | None) -> None:
            if description:
                self.app.launch_task(description)

        self.app.push_screen(NewTaskScreen(), on_result)

    def action_resume(self) -> None:
        task_id = self.selected_task_id
        if task_id is None:
            self.notify("No task selected.", severity="warning")
            return
        policy_pack = _discover_policy_pack()
        if not policy_pack:
            self.notify(
                "No policy pack found — run `sarathi init` first.", severity="error"
            )
            return
        self.notify(f"Resuming {task_id}…")
        self.run_worker(
            lambda: self._resume(task_id, policy_pack),
            thread=True,
            exclusive=True,
            group="resume",
        )

    def _resume(self, task_id: str, policy_pack: str) -> None:
        try:
            result = tui_data.resume_task(self.app.persistence, task_id, policy_pack)
        except Exception as exc:
            message = f"Resume failed: {exc}"
            self.app.call_from_thread(self.notify, message, severity="error")
            self.app.call_from_thread(self.app.post_chat_event, message)
            return
        phase = result.current_phase.value if result.current_phase else "Completed"
        message = f"Resumed {task_id}: now at {phase}"
        self.app.call_from_thread(self.notify, message)
        self.app.call_from_thread(self.app.post_chat_event, message)
        self.app.call_from_thread(self.refresh_data)


class SarathiApp(App):
    """Chat-first Sarathi terminal UI with a toggleable task panel."""

    TITLE = "Sarathi"
    SUB_TITLE = "guiding systems"

    MODES = {"chat": ChatScreen, "tasks": TasksScreen}

    BINDINGS = [
        Binding("ctrl+t", "toggle_mode", "Chat/Tasks", priority=True),
    ]

    CSS = """
    #chat-home {
        align: center middle;
    }
    #chat-banner {
        width: auto;
        color: $primary;
    }
    #chat-tagline {
        width: auto;
        color: $text-muted;
        margin-bottom: 1;
    }
    #chat-input-home {
        width: 80;
        max-width: 90%;
    }
    #chat-provider {
        width: auto;
        margin-top: 1;
    }
    #chat-active {
        display: none;
        height: 1fr;
    }
    ChatScreen.-started #chat-home {
        display: none;
    }
    ChatScreen.-started #chat-active {
        display: block;
    }
    #chat-thread {
        height: 1fr;
        padding: 1 2;
    }
    #chat-input {
        dock: bottom;
        margin: 0 1 1 1;
    }
    .chat-msg {
        margin-bottom: 1;
    }
    #tasks {
        width: 42%;
        border-right: solid $primary;
    }
    #detail {
        width: 1fr;
    }
    #snapshot {
        padding: 0 1;
        height: auto;
        max-height: 50%;
        overflow-y: auto;
    }
    #phases {
        height: auto;
        max-height: 12;
    }
    #log {
        height: 1fr;
        border-top: solid $primary;
    }
    #proposals {
        height: 40%;
    }
    #proposal-detail {
        padding: 1;
        height: 1fr;
        overflow-y: auto;
    }
    NewTaskScreen {
        align: center middle;
    }
    #new-task-dialog {
        width: 80;
        height: auto;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    """

    def __init__(
        self,
        persistence=None,
        task_id: str | None = None,
        refresh_interval: float = 2.0,
    ) -> None:
        super().__init__()
        self.persistence = (
            persistence if persistence is not None else tui_data.default_persistence()
        )
        self.initial_task_id = task_id
        self.refresh_interval = refresh_interval
        self.chat_screen: ChatScreen | None = None

    def on_mount(self) -> None:
        # Opening with --task means the user wants the panel, not the chat.
        self.switch_mode("tasks" if self.initial_task_id else "chat")

    def action_toggle_mode(self) -> None:
        self.switch_mode("tasks" if self.current_mode == "chat" else "chat")

    def post_chat_event(self, text: str) -> None:
        """Post a system message into the chat thread, if it has one started.

        Safe to call from the UI thread only (callers from worker threads
        should use `call_from_thread`). Does nothing if the chat screen has
        never been activated, so users who haven't chatted aren't surprised
        by a thread appearing.
        """
        if self.chat_screen is not None and self.chat_screen.has_class("-started"):
            self.chat_screen._system(text)

    def launch_task(self, description: str, context: str | None = None) -> bool:
        """Run a new task through the lifecycle in a background worker."""
        policy_pack = _discover_policy_pack()
        if not policy_pack:
            self.notify(
                "No policy pack found — run `sarathi init` first.", severity="error"
            )
            return False
        self.notify(f"Starting: {_short(description, 60)}")
        self.run_worker(
            lambda: self._start(description, policy_pack, context),
            thread=True,
            group="run",
        )
        return True

    def _start(self, description: str, policy_pack: str, context: str | None = None) -> None:
        try:
            result = tui_data.start_task(
                self.persistence, description, policy_pack, context=context
            )
        except Exception as exc:
            self.call_from_thread(self.notify, f"Task failed: {exc}", severity="error")
            self.call_from_thread(self.post_chat_event, f"Task failed: {exc}")
            return
        if result.current_phase is None:
            message = f"Task completed: {result.task_id}"
        else:
            message = f"Task paused at {result.current_phase.value}: {result.task_id}"
        self.call_from_thread(self.notify, message)
        self.call_from_thread(self.post_chat_event, message)
        screen = self.screen
        if isinstance(screen, TasksScreen):
            screen.selected_task_id = result.task_id
            self.call_from_thread(screen.refresh_data)


# Backward-compatible alias: the app started life as a dashboard-only UI.
SarathiDashboard = SarathiApp


def launch_sarathi_tui(task_id: str | None = None) -> None:
    """Launch the Sarathi terminal UI."""
    SarathiApp(task_id=task_id).run()
