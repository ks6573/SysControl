"""
Key bindings and SIGINT handling for the SysControl CLI prompt.

Two responsibilities:

1. ``build_key_bindings()`` returns the prompt_toolkit ``KeyBindings`` for the
   interactive REPL (Codex-style multi-line: Enter submits a single-line buffer,
   inserts a newline once the buffer is multi-line; Ctrl-D submits any non-empty
   buffer and only triggers EOF on an empty buffer; Ctrl-L clears the screen;
   Esc-Enter always inserts a newline).

2. ``install_sigint_handler(...)`` installs a ``SIGINT`` handler for the lifetime
   of the REPL.  The first Ctrl-C during a streaming turn signals cancellation
   via a ``threading.Event`` (already plumbed through ``TurnCallbacks`` and
   ``run_streaming_turn``).  A second Ctrl-C within ``DOUBLE_PRESS_WINDOW`` shuts
   the MCP pool down cleanly and exits with status 130.
"""

from __future__ import annotations

import contextlib
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator

from prompt_toolkit.key_binding import KeyBindings

DIM_OPEN = "\033[2m"
DIM_CLOSE = "\033[0m"
DOUBLE_PRESS_WINDOW = 1.0  # seconds


def build_key_bindings(on_shift_tab: Callable[[], str] | None = None) -> KeyBindings:
    """Build the REPL key bindings used by `_build_prompt_session`."""
    bindings = KeyBindings()

    @bindings.add("c-l")
    def _clear_screen(event: object) -> None:
        print("\033[2J\033[H", end="", flush=True)
        event.app.invalidate()  # type: ignore[attr-defined]

    @bindings.add("escape", "enter")
    def _insert_newline_alt(event: object) -> None:
        event.current_buffer.insert_text("\n")  # type: ignore[attr-defined]

    @bindings.add("enter")
    def _enter(event: object) -> None:
        buf = event.current_buffer  # type: ignore[attr-defined]
        if "\n" in buf.text:
            buf.insert_text("\n")
        else:
            buf.validate_and_handle()

    @bindings.add("c-d")
    def _ctrl_d(event: object) -> None:
        buf = event.current_buffer  # type: ignore[attr-defined]
        if buf.text:
            buf.validate_and_handle()
        else:
            event.app.exit(exception=EOFError())  # type: ignore[attr-defined]

    @bindings.add("s-tab")
    def _shift_tab(event: object) -> None:
        if on_shift_tab is None:
            return
        buf = event.current_buffer  # type: ignore[attr-defined]
        buf.text = on_shift_tab()
        buf.cursor_position = len(buf.text)
        buf.validate_and_handle()

    return bindings


@contextlib.contextmanager
def install_sigint_handler(
    cancel_event: threading.Event,
    on_exit: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Install a SIGINT handler that cancels streams; double-tap exits cleanly.

    Only installs on the main thread.  Restores the prior handler on exit so
    embedded callers (tests, IDE runners) are not surprised.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    state = {"last": 0.0}
    previous = signal.getsignal(signal.SIGINT)

    def _handler(_signum: int, _frame: object) -> None:
        now = time.monotonic()
        if now - state["last"] < DOUBLE_PRESS_WINDOW:
            print(f"\n{DIM_OPEN}Exiting…{DIM_CLOSE}", flush=True)
            if on_exit is not None:
                with contextlib.suppress(Exception):
                    on_exit()
            sys.exit(130)
        state["last"] = now
        cancel_event.set()
        print(
            f"\n{DIM_OPEN}^C  cancelling…  press again within "
            f"{DOUBLE_PRESS_WINDOW:.0f}s to exit.{DIM_CLOSE}",
            flush=True,
        )

    signal.signal(signal.SIGINT, _handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
