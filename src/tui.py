from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Static, Label, Input
from textual.layout import Layout
from rich.panel import Panel
from rich.text import Text
from typing import List, Dict, Any
import asyncio
import sys
import re
import json
from pathlib import Path
from src.dispatch import DispatchRequest

# --- Stellar Constants ---
SARATHI_ASCII_BANNER = r"""
  ██████  █████  ██████   █████  ████████ ██   ██ ██
 ██      ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
  █████  ███████ ██████  ███████    ██    ███████ ██
      ██ ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
  ██████ ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
"""

SARATHI_TAGLINE = "─── GUIDING SYSTEMS ───────────────────"

# --- Utility Functions ---

def get_aesthetic_style(name: str, type: str = "info", is_bold: bool = False) -> str:
    """Gets a style based on OpenCode's vibrant, dark aesthetic."""
    styles = {
        "banner": "cyan on black",
        "prompt": "bold green",
        "error": "bold red",
        "success": "bold green",
        "phase_name": "bold cyan",
        "progress": "cyan",
        "warning": "bold yellow",
        "info": "cyan",
        "default": "white",
    }
    base_style = styles.get(type, "white")
    style_parts = list(base_style.split(" "))
    if is_bold:
        style_parts.insert(0, "bold")
    return " ".join(style_parts)


# --- Textual App ---

class SarathiTUI(App):
    """The main interactive TUI application for Sarathi."""
    
    def __init__(self, initial_message: str | None = None, exit_after: bool = False):
        super().__init__()
        self.output_content = ""
        self.initial_message = initial_message
        self.exit_after = exit_after

    def compose(self) -> ComposeResult:
        yield Static(SARATHI_ASCII_BANNER)
        yield Static(SARATHI_TAGLINE)
        yield Static("""
Welcome to Sarathi AI Orchestrator!

• Ask general questions (what's today's date, explain X, etc.)
• For project work, ensure you have a policy pack (run 'sarathi init')
""", id="output-log")
        yield Static("> ", id="prompt")
        yield Input(placeholder="Ask a question or describe a task...")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        
        # Process initial message after a brief delay to ensure UI is ready
        if self.initial_message:
            msg = self.initial_message
            self.initial_message = None
            self.call_later(self._process_initial_message, msg)

    def _process_initial_message(self, message: str):
        """Process initial message after UI is ready."""
        self.run_workflow(message)
        if self.exit_after:
            self.exit(0)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        
        # Check for exit command
        if message.lower() in ("exit", "quit", "q", "bye"):
            self.output_content += "\n👋 Goodbye!"
            self.query_one("#output-log").update(self.output_content)
            self.exit(0)
            return
        
        # Clear input
        event.input.value = ""
        
        # Execute workflow
        self.run_workflow(message)

    def is_generic_question(self, message: str) -> bool:
        """Classify if message is generic chat vs project task using LLM."""
        text = message.lower().strip()
        
        # Quick heuristic for obvious cases
        obvious_generic = {"hello", "hi", "hey", "help", "quit", "exit", "q", "bye"}
        if text in obvious_generic:
            return True
        
        # Try LLM classification
        try:
            return self._llm_classify(message)
        except Exception:
            # Fallback to pattern-based classification
            return self._pattern_classify(message)

    def _llm_classify(self, message: str) -> bool:
        """Classify using lightweight LLM call."""
        from src.dispatch import LocalDispatcher
        
        dispatcher = LocalDispatcher()
        prompt = f"""Message: "{message}"

Is this a casual conversation/question (generic) or a code/project task (project)?
Respond with ONE word: generic or project"""
        
        request = DispatchRequest(
            mode="execute",
            task_id="classify",
            phase="classify",
            prompt=prompt,
            inputs={},
        )
        
        response = dispatcher.dispatch(request)
        return "generic" in response.outputs.get("content", "").lower()[:20]

    def _pattern_classify(self, message: str) -> bool:
        """Fallback pattern-based classification."""
        text = message.lower()
        generic_patterns = [
            r"what\s+(is|are|does|do|did|was|were|can)",
            r"how\s+(do|does|did|can|could|would|should)",
            r"why\s+",
            r"explain\s+",
            r"describe\s+",
            r"define\s+",
            r"tell\s+me\s+about",
            r"who\s+is\s+",
            r"when\s+did\s+",
            r"where\s+(is|are|does)",
            r"\bdate\b",
            r"\btime\b",
            r"^hello",
            r"^hi\s",
            r"^hey",
            r"^help",
        ]
        project_patterns = [
            r"\brefactor\b",
            r"\barchitect\b",
            r"\bmigrate\b",
            r"\bredesign\b",
            r"\b(build|create|implement)\s+",
            r"\b(fix|debug)\s+",
            r"\bwrite\s+",
            r"\bgenerate\s+",
            r"\badd\s+",
            r"\bremove\s+",
            r"\bupdate\s+",
            r"\btest\s+",
        ]
        is_generic = any(re.search(p, text) for p in generic_patterns)
        is_project = any(re.search(p, text) for p in project_patterns)
        return is_generic or not is_project

    def run_workflow(self, message: str):
        """Execute the Sarathi workflow - either chat mode or project mode."""
        log = self.query_one("#output-log")
        
        # Check for exit command first
        if message.lower() in ("exit", "quit", "q", "bye"):
            self.output_content += "\n👋 Goodbye!"
            log.update(self.output_content)
            self.exit(0)
            return
        
        # Check if it's a generic question FIRST - even if policy pack exists
        is_generic = self.is_generic_question(message)
        
        # Always use chat mode for generic questions (fast, no engine needed)
        if is_generic:
            self.run_chat_mode(message, log)
            return
        
        # For project tasks, check for policy pack
        from src.cli import discover_policy_pack
        policy_pack = discover_policy_pack()
        
        if not policy_pack:
            self.output_content += """
⚠️  No policy pack found.

For project work, run: sarathi init <project-path>
"""
            log.update(self.output_content)
            return
        
        # Policy pack exists - use full engine for project tasks
        try:
            self.run_project_mode(message, policy_pack)
        except Exception as e:
            self.output_content += f"\n❌ Error: {str(e)}"
        
        log.update(self.output_content)

    def run_chat_mode(self, message: str, log):
        """Handle generic questions - answer using LLM."""
        # Try quick responses for obvious cases
        text = message.lower()
        
        if "date" in text and "today" in text:
            from datetime import datetime
            today = datetime.now().strftime("%B %d, %Y")
            self.output_content += f"\n📅 Today's date is: {today}"
            log.update(self.output_content)
            return
        elif "time" in text:
            from datetime import datetime
            now = datetime.now().strftime("%I:%M %p")
            self.output_content += f"\n🕐 Current time: {now}"
            log.update(self.output_content)
            return
        elif any(g in text for g in ["hello", "hi", "hey"]) and len(message.split()) < 3:
            self.output_content += """
👋 Hello! I'm Sarathi - your AI orchestration partner.

I can help with:
• General questions and conversations
• Project work (with a policy pack)

To work on a project: sarathi init <path>
"""
            log.update(self.output_content)
            return
        elif text == "help":
            self.output_content += """
ℹ️ Sarathi Commands:

  sarathi           - Start interactive chat
  sarathi init <path> - Initialize a project
  sarathi run <task> - Run a task through phases
  sarathi status    - Check task status

Try asking me something!
"""
            log.update(self.output_content)
            return
        
        # Use LLM to answer the question
        self.output_content += f"\n🤖 {message}"
        log.update(self.output_content)
        
        try:
            answer = self._llm_answer(message)
            self.output_content += f"\n{answer}"
        except Exception as e:
            self.output_content += f"""
I can answer general questions. For project work,
set up a policy pack: sarathi init <project-path>
"""
        
        log.update(self.output_content)

    def _llm_answer(self, question: str) -> str:
        """Get answer from LLM for generic questions."""
        import os
        import shutil
        from src.dispatch import DispatchRequest
        from src.dispatch import LocalDispatcher
        from src.storage import connect
        
        # Strategy 1: Check OPENAI_API_KEY env var
        if os.getenv("OPENAI_API_KEY"):
            provider_config = {"provider": "openai", "model": "gpt-4o"}
            dispatcher = LocalDispatcher(provider_config=provider_config)
            
            prompt = f"""You are a helpful assistant. Answer this question concisely:

Question: {question}

Answer:"""
            
            request = DispatchRequest(
                mode="execute",
                task_id="answer",
                phase="answer",
                prompt=prompt,
                inputs={},
            )
            
            try:
                response = dispatcher.dispatch(request)
                return response.outputs.get("content", "I don't have an answer right now.")
            except Exception as e:
                pass
        
        # Strategy 2: Try desktop database provider config
        db_path = Path(".sarathi/sarathi.db")
        if db_path.exists():
            try:
                conn = connect(db_path)
                row = conn.execute("SELECT config FROM providers WHERE health = 'online' LIMIT 1").fetchone()
                if row and row["config"]:
                    provider_config = json.loads(row["config"])
                    if provider_config.get("path"):
                        dispatcher = LocalDispatcher(provider_config=provider_config)
                        
                        prompt = f"""You are a helpful assistant. Answer this question concisely:

Question: {question}

Answer:"""
                        
                        request = DispatchRequest(
                            mode="execute",
                            task_id="answer",
                            phase="answer",
                            prompt=prompt,
                            inputs={},
                        )
                        
                        try:
                            response = dispatcher.dispatch(request)
                            return response.outputs.get("content", "I don't have an answer right now.")
                        except Exception:
                            pass
                conn.close()
            except Exception:
                pass
        
        # Strategy 3: Try available CLI tools (claude, opencode, codex)
        cli_tools = [("claude", ["-p", "--print"]), ("opencode", []), ("codex", ["--print"])]
        for tool, args in cli_tools:
            if shutil.which(tool):
                try:
                    import subprocess as sp
                    result = sp.run(
                        [tool] + args + [question],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0 and result.stdout:
                        return result.stdout.strip()[:500]
                except Exception:
                    continue
        
        # No provider available
        return """No LLM provider available. To enable AI answers:

  • Set OPENAI_API_KEY env var: export OPENAI_API_KEY=your-key
  • Or install a CLI tool: Claude, OpenCode, or Codex
  • Or run 'sarathi init <project>' for project mode"""

    def run_project_mode(self, message: str, policy_pack: str):
        """Execute full Sarathi workflow with policy pack."""
        from src.engine import Engine, TaskContext, Complexity
        
        # Auto-calculate complexity
        complexity = Complexity.MEDIUM
        text = message.lower()
        high_patterns = [r'\b(architect|architecture|refactor|migrate|redesign)\b', r'\b(new\s+feature)\b']
        low_patterns = [r'\b(fix|bug|typo|simple)\b']
        if any(p in text for p in high_patterns):
            complexity = Complexity.HIGH
        elif any(p in text for p in low_patterns):
            complexity = Complexity.LOW
        
        self.output_content += f"\n⚙️ Running: {message}"
        self.output_content += f"\n   Complexity: {complexity.value}"
        
        # Create engine and run task
        engine = Engine(policy_pack_path=policy_pack, enforce_preflight=False)
        task = TaskContext(
            task_id=engine.generate_task_id(message),
            description=message,
            complexity=complexity,
        )
        
        result = engine.run_task(task)
        
        self.output_content += f"\n✅ Completed ({len(result.phase_results)} phases)"
        
        # Show final outcome from last phase
        if result.phase_results:
            last = result.phase_results[-1]
            self.output_content += f"\n   → {last.outcome[:100]}"


def launch_sarathi_tui(initial_message: str | None = None, exit_after: bool = False) -> None:
    """Launches the Sarathi TUI application."""
    app = SarathiTUI(initial_message, exit_after)
    app.run()