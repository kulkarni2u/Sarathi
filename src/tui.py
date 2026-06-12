"""Sarathi terminal dashboard: live run monitor, task browser, proposal review.

Launch with `sarathi tui`. The dashboard polls `.sarathi/tasks` on an
interval, so it can watch runs started elsewhere (CLI, MCP, service)
without any coordination.
"""
from __future__ import annotations

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Log, Static

try:
    from . import tui_data
except ImportError:
    # Support direct execution via sarathi.py, which prepends src/ to sys.path.
    import tui_data


def _short(text: object, width: int) -> str:
    flattened = " ".join(str(text).split())
    if len(flattened) <= width:
        return flattened
    return flattened[: width - 1] + "…"


def _discover_policy_pack() -> str | None:
    try:
        from .cli import discover_policy_pack
    except ImportError:
        from cli import discover_policy_pack
    return discover_policy_pack()


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
                artifact["id"],
                artifact["risk_level"],
                f"{artifact['confidence']:.2f}",
                artifact["policy_file"],
                _short(artifact["title"], 60),
                self.decided.get(artifact["id"], ""),
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


class SarathiDashboard(App):
    """Task browser, live run monitor, and proposal review for Sarathi."""

    TITLE = "Sarathi"
    SUB_TITLE = "harness dashboard"

    CSS = """
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "proposals", "Proposals"),
        Binding("u", "resume", "Resume task"),
    ]

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
        self.selected_task_id = task_id
        self.refresh_interval = refresh_interval

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="tasks")
            with Vertical(id="detail"):
                yield Static("No task selected.", id="snapshot")
                yield DataTable(id="phases")
                yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        tasks = self.query_one("#tasks", DataTable)
        tasks.cursor_type = "row"
        tasks.add_columns("Task", "Phase", "Outcome", "Updated")
        phases = self.query_one("#phases", DataTable)
        phases.cursor_type = "none"
        phases.add_columns("Phase", "Agent", "Outcome", "Iter", "Error")
        self.refresh_data()
        self.set_interval(self.refresh_interval, self.refresh_data)

    def refresh_data(self) -> None:
        summaries = tui_data.task_summaries(self.persistence)
        table = self.query_one("#tasks", DataTable)
        table.clear()
        known: set[str] = set()
        for summary in summaries:
            known.add(summary["task_id"])
            table.add_row(
                _short(summary["task_id"], 20),
                summary["current_phase"],
                _short(summary["last_outcome"], 14),
                str(summary["last_updated"])[5:16].replace("T", " "),
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
        log = self.query_one("#log", Log)
        phases.clear()
        log.clear()
        if self.selected_task_id is None:
            snapshot.update("No saved tasks. Run `sarathi run \"…\"` first.")
            return
        text = tui_data.status_snapshot(self.persistence, self.selected_task_id)
        snapshot.update(escape(text) if text else f"Task {self.selected_task_id} not found.")
        for row in tui_data.phase_rows(self.persistence, self.selected_task_id):
            phases.add_row(
                row["phase"],
                row["agent"],
                row["outcome"],
                str(row["iterations"]),
                _short(row["error"], 40),
            )
        for line in tui_data.phase_log_tail(self.persistence, self.selected_task_id):
            log.write_line(tui_data.format_log_line(line))

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
        self.push_screen(ProposalsScreen(self.persistence))

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
            result = tui_data.resume_task(self.persistence, task_id, policy_pack)
        except Exception as exc:
            self.call_from_thread(
                self.notify, f"Resume failed: {exc}", severity="error"
            )
            return
        phase = result.current_phase.value if result.current_phase else "Completed"
        self.call_from_thread(self.notify, f"Resumed {task_id}: now at {phase}")
        self.call_from_thread(self.refresh_data)


def launch_sarathi_tui(task_id: str | None = None) -> None:
    """Launch the Sarathi dashboard."""
    SarathiDashboard(task_id=task_id).run()
