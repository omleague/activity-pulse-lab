from __future__ import annotations

import os
import time
from contextlib import contextmanager
from time import monotonic
from typing import Iterator

from activity_pulse import activity_pulse


DEMO_TEXT = "Verifying vault integrity -"

DEMO_STOP_KEY = "r"
DEMO_AUTO_STOP_SECONDS = 300.0
DEMO_POLL_SECONDS = 0.03


@contextmanager
def _lab_stop_key_mode() -> Iterator[None]:
    """Prepare cross-platform single-key reading for the lab stopper."""
    if os.name == "nt":
        yield
        return

    import sys
    import termios
    import tty

    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)

    try:
        tty.setcbreak(file_descriptor)
        yield
    finally:
        termios.tcsetattr(
            file_descriptor,
            termios.TCSADRAIN,
            previous_settings,
        )


def _wait_for_lab_stop() -> str:
    """Wait for a cross-platform stop key, with an automatic escape hatch."""
    deadline = monotonic() + DEMO_AUTO_STOP_SECONDS

    with _lab_stop_key_mode():
        while monotonic() < deadline:
            key: str | None = None

            if os.name == "nt":
                import msvcrt

                if msvcrt.kbhit():
                    key = msvcrt.getwch()

                    if key in ("\x00", "\xe0"):
                        if msvcrt.kbhit():
                            msvcrt.getwch()

                        key = None
            else:
                import select
                import sys

                ready, _, _ = select.select(
                    [sys.stdin],
                    [],
                    [],
                    0,
                )

                if ready:
                    key = sys.stdin.read(1)

            if key and key.casefold() == DEMO_STOP_KEY:
                return f"{DEMO_STOP_KEY.upper()} key"

            time.sleep(DEMO_POLL_SECONDS)

    return "automatic timeout"


def _simulate_caller() -> None:
    """Simulate a larger program ending the activity scope."""
    print(
        f"Pulse running. Press {DEMO_STOP_KEY.upper()} to stop "
        f"(automatic stop after "
        f"{DEMO_AUTO_STOP_SECONDS:g} seconds)."
    )

    with activity_pulse(DEMO_TEXT):
        stop_reason = _wait_for_lab_stop()

    print(
        f"Activity line released. "
        f"Stop reason: {stop_reason}."
    )


if __name__ == "__main__":
    _simulate_caller()