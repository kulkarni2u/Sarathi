"""Tests for sarathi chat REPL."""
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import cli
from src.tui_data import ChatSession


class MockChatSession(ChatSession):
    """Test double for ChatSession that doesn't call real CLIs."""

    def __init__(self, workspace_root: str | None = None, timeout: int = 180):
        super().__init__(workspace_root, timeout)
        self.provider = None
        self.sent_messages = []

    def resolve_provider(self):
        """Always return a mock provider unless explicitly cleared."""
        if self.provider is None:
            self.provider = ("mock_provider", "/mock/path")
        return self.provider

    def available_providers(self):
        """Return mock providers."""
        return [("claude", "/path/to/claude"), ("mock_provider", "/mock/path")]

    def set_provider(self, name: str) -> bool:
        """Mock provider switching."""
        if name in ("claude", "mock_provider", "codex", "opencode"):
            self.provider = (name, f"/path/to/{name}")
            return True
        return False

    def send(self, message: str) -> str:
        """Mock blocking send."""
        self.sent_messages.append(("send", message))
        self.history.append((message, f"Reply to: {message}"))
        return f"Reply to: {message}"

    def send_streaming(self, message: str, on_text=None) -> str:
        """Mock streaming send."""
        self.sent_messages.append(("send_streaming", message))
        reply = f"Streaming reply to: {message}"
        if on_text:
            # Simulate streaming chunks
            for chunk in ["Streaming ", "reply ", "to: ", message]:
                on_text(on_text.__self__  # this is a hack for testing
                        if hasattr(on_text, "__self__")
                        else ("Streaming reply to: " + message[:len("Streaming reply to: " + message)//4]))
        self.history.append((message, reply))
        return reply

    def cancel(self) -> bool:
        """Mock cancel."""
        return True


def test_handle_chat_default_provider_first_available(monkeypatch):
    """Test that chat uses first available provider by default."""
    inputs = iter(["hello", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    # Check that banner was printed with provider
    banner_lines = [o for o in outputs if "Sarathi Chat" in o]
    assert len(banner_lines) == 1
    assert "mock_provider" in banner_lines[0]


def test_handle_chat_explicit_provider_override(monkeypatch):
    """Test that --provider flag overrides default."""
    inputs = iter(["/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider="claude", workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    banner_lines = [o for o in outputs if "Sarathi Chat" in o]
    assert len(banner_lines) == 1
    assert "claude" in banner_lines[0]


def test_handle_chat_unknown_provider_exits():
    """Test that unknown provider causes exit(1)."""
    def mock_input(prompt):
        raise EOFError()

    def mock_output(msg):
        pass

    args = Namespace(provider="nonexistent", workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        with pytest.raises(SystemExit) as exc_info:
            cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
        assert exc_info.value.code == 1


def test_handle_chat_quit_command_exits(monkeypatch):
    """Test that /quit command cleanly exits the REPL."""
    inputs = iter(["hello", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    # Verify /quit didn't cause an exception
    assert True


def test_handle_chat_model_command_shows_current(monkeypatch):
    """Test that /model with no args shows current provider."""
    inputs = iter(["/model", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    current_provider_lines = [o for o in outputs if "Current provider:" in o]
    assert len(current_provider_lines) == 1
    assert "mock_provider" in current_provider_lines[0]


def test_handle_chat_model_command_switches_provider(monkeypatch):
    """Test that /model name switches to that provider."""
    inputs = iter(["/model claude", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    switched_lines = [o for o in outputs if "Provider switched to:" in o]
    assert len(switched_lines) == 1
    assert "claude" in switched_lines[0]


def test_handle_chat_model_command_unknown_provider_error(monkeypatch):
    """Test that /model with unknown provider shows error."""
    inputs = iter(["/model badprovider", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    error_lines = [o for o in outputs if "Error: Unknown provider" in o]
    assert len(error_lines) == 1


def test_handle_chat_help_command_shows_help(monkeypatch):
    """Test that /help shows available commands."""
    inputs = iter(["/help", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    help_lines = [o for o in outputs if "Slash commands:" in o]
    assert len(help_lines) == 1
    # Verify that help contains expected commands
    all_output = "\n".join(outputs)
    assert "/quit" in all_output
    assert "/model" in all_output
    assert "/help" in all_output


def test_handle_chat_unknown_command_shows_error(monkeypatch):
    """Test that unknown slash command shows error."""
    inputs = iter(["/badcommand", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)

    error_lines = [o for o in outputs if "Unknown command:" in o]
    assert len(error_lines) == 1
    assert "/badcommand" in error_lines[0]


def test_handle_chat_empty_input_reprompts(monkeypatch):
    """Test that empty input doesn't send a message, just reprompts."""
    inputs = iter(["", "hello", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    class TrackingChatSession(MockChatSession):
        """Mock that tracks messages sent."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.messages_sent = []

        def send(self, message: str) -> str:
            self.messages_sent.append(message)
            return super().send(message)

        def send_streaming(self, message: str, on_text=None) -> str:
            self.messages_sent.append(message)
            return super().send_streaming(message, on_text)

    with patch("src.tui_data.ChatSession", TrackingChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
        # Get the instance that was created
        # Since we can't easily get it back, we verify through outputs instead
        assistant_outputs = [o for o in outputs if "assistant>" in o]
        assert len(assistant_outputs) == 1  # Only "hello" should produce output


def test_handle_chat_no_stream_flag_uses_blocking_send(monkeypatch):
    """Test that --no-stream uses blocking send."""
    inputs = iter(["hello", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=True)

    class BlockingTrackingSession(MockChatSession):
        """Mock that tracks which send method was called."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.send_called = False
            self.send_streaming_called = False

        def send(self, message: str) -> str:
            self.send_called = True
            return super().send(message)

        def send_streaming(self, message: str, on_text=None) -> str:
            self.send_streaming_called = True
            return super().send_streaming(message, on_text)

    # Monkey-patch to capture the instance
    captured_instance = None
    original_init = BlockingTrackingSession.__init__

    def patched_init(self, *args, **kwargs):
        nonlocal captured_instance
        captured_instance = self
        original_init(self, *args, **kwargs)

    BlockingTrackingSession.__init__ = patched_init

    try:
        with patch("src.tui_data.ChatSession", BlockingTrackingSession):
            cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
            # Verify that only blocking send was called
            assert captured_instance is not None
            assert captured_instance.send_called
            assert not captured_instance.send_streaming_called
    finally:
        BlockingTrackingSession.__init__ = original_init


def test_handle_chat_streaming_uses_send_streaming(monkeypatch):
    """Test that by default streaming send is used."""
    inputs = iter(["hello", "/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    class StreamingTrackingSession(MockChatSession):
        """Mock that tracks which send method was called."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.send_called = False
            self.send_streaming_called = False

        def send(self, message: str) -> str:
            self.send_called = True
            return super().send(message)

        def send_streaming(self, message: str, on_text=None) -> str:
            self.send_streaming_called = True
            return super().send_streaming(message, on_text)

    captured_instance = None
    original_init = StreamingTrackingSession.__init__

    def patched_init(self, *args, **kwargs):
        nonlocal captured_instance
        captured_instance = self
        original_init(self, *args, **kwargs)

    StreamingTrackingSession.__init__ = patched_init

    try:
        with patch("src.tui_data.ChatSession", StreamingTrackingSession):
            cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
            assert captured_instance is not None
            assert captured_instance.send_streaming_called
            assert not captured_instance.send_called
    finally:
        StreamingTrackingSession.__init__ = original_init


def test_handle_chat_keyboard_interrupt_cancels_reply_keeps_loop_alive(monkeypatch):
    """Test that Ctrl-C during a reply cancels and keeps REPL alive."""
    call_count = [0]

    def mock_input(prompt):
        call_count[0] += 1
        if call_count[0] == 1:
            return "hello"
        elif call_count[0] == 2:
            return "/quit"
        else:
            raise EOFError()

    outputs = []

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    class InterruptibleSession(MockChatSession):
        """Mock session that raises KeyboardInterrupt on send_streaming."""
        def send_streaming(self, message: str, on_text=None) -> str:
            raise KeyboardInterrupt()

    with patch("src.tui_data.ChatSession", InterruptibleSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
        # Verify that we got the "cancelled" message and didn't raise
        cancelled_lines = [o for o in outputs if "cancelled" in o]
        assert len(cancelled_lines) == 1


def test_handle_chat_eof_exits_cleanly(monkeypatch):
    """Test that Ctrl-D (EOF) exits the REPL cleanly."""
    def mock_input(prompt):
        raise EOFError()

    outputs = []

    def mock_output(msg):
        outputs.append(msg)

    args = Namespace(provider=None, workspace=None, no_stream=False)

    with patch("src.tui_data.ChatSession", MockChatSession):
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
        # Should exit without raising
        assert True


def test_handle_chat_no_providers_available_exits_with_code_1():
    """Test that when no CLIs are available on PATH, exit(1) is called."""

    def mock_input(prompt):
        raise EOFError()

    def mock_output(msg):
        pass

    args = Namespace(provider=None, workspace=None, no_stream=False)

    class NoProvidersChatSession(MockChatSession):
        def resolve_provider(self):
            return None

        def available_providers(self):
            return []

    with patch("src.tui_data.ChatSession", NoProvidersChatSession):
        with pytest.raises(SystemExit) as exc_info:
            cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
        assert exc_info.value.code == 1


def test_handle_chat_uses_provided_workspace():
    """Test that --workspace flag is respected."""
    inputs = iter(["/quit"])
    outputs = []

    def mock_input(prompt):
        val = next(inputs, None)
        if val is None:
            raise EOFError()
        return val

    def mock_output(msg):
        outputs.append(msg)

    test_workspace = "/custom/workspace"
    args = Namespace(provider=None, workspace=test_workspace, no_stream=False)

    with patch("src.tui_data.ChatSession") as mock_chat_cls:
        mock_instance = MockChatSession(workspace_root=test_workspace)
        mock_chat_cls.return_value = mock_instance
        cli.handle_chat(args, input_fn=mock_input, output_fn=mock_output)
        # Verify ChatSession was instantiated with the workspace
        mock_chat_cls.assert_called_once()
        call_kwargs = mock_chat_cls.call_args[1]
        assert call_kwargs.get("workspace_root") == test_workspace
