"""
Key bindings, SIGINT, and SIGWINCH handling for the SysControl CLI prompt.

Responsibilities:

1. ``build_key_bindings()`` returns the prompt_toolkit ``KeyBindings`` for the
   interactive REPL (Claude-Code-style: Enter always submits the buffer; Ctrl-J
   and Esc-Enter explicitly insert a newline for multi-line input; Ctrl-D
   submits any non-empty buffer and only triggers EOF on an empty buffer;
   Ctrl-L clears the screen).

2. ``install_sigint_handler(...)`` installs a ``SIGINT`` handler for the lifetime
   of the REPL.  The first Ctrl-C during a streaming turn signals cancellation
   via a ``threading.Event`` (already plumbed through ``TurnCallbacks`` and
   ``run_streaming_turn``).  A second Ctrl-C within ``DOUBLE_PRESS_WINDOW`` shuts
   the MCP pool down cleanly and exits with status 130.

3. ``install_resize_handler(...)`` installs a ``SIGWINCH`` handler that invokes
   a callback whenever the terminal is resized so the REPL can invalidate cached
   widths and re-render its status footer / cards.
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

    @bindings.add("c-j")
    def _insert_newline_ctrl_j(event: object) -> None:
        # Claude-Code-style: Ctrl-J inserts an explicit newline for multi-line
        # input.  Esc-Enter is preserved as an alias for terminals that emit a
        # different sequence.
        event.current_buffer.insert_text("\n")  # type: ignore[attr-defined]

    @bindings.add("enter")
    def _enter(event: object) -> None:
        # Always submit on Enter.  Multi-line input is composed with Ctrl-J or
        # Esc-Enter to avoid the "once-multiline-always-newline" trap from the
        # previous binding (which inserted a newline if the buffer already
        # contained one).
        buf = event.current_buffer  # type: ignore[attr-defined]
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


@contextlib.contextmanager
def install_resize_handler(on_resize: Callable[[], None]) -> Iterator[None]:
    """Install a SIGWINCH handler that calls *on_resize* when the terminal is
    resized.  Restores the prior handler on exit.

    Only installs on the main thread.  Silently no-ops on platforms that do not
    expose SIGWINCH (e.g. Windows).
    """
    sigwinch = getattr(signal, "SIGWINCH", None)
    if sigwinch is None or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous = signal.getsignal(sigwinch)

    def _handler(_signum: int, _frame: object) -> None:
        with contextlib.suppress(Exception):
            on_resize()

    signal.signal(sigwinch, _handler)
    try:
        yield
    finally:
        signal.signal(sigwinch, previous)
