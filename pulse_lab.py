from __future__ import annotations

import os
import time
from contextlib import contextmanager
from time import monotonic
from typing import Iterator

from activity_pulse import PulseConfig, activity_pulse


DEMO_TEXT = "THIS PROCESS IS STILL ACTIVE."

DEMO_STOP_KEY = "r"
DEMO_AUTO_STOP_SECONDS = 300.0
DEMO_POLL_SECONDS = 0.03

# Mike knobs: change these first.
LAB_MODE = "left_to_right"  # "left_to_right", "right_to_left", "bounce"
LAB_COLOR_STRENGTH = 0.30
LAB_TRAVEL_SECONDS = 0.65
LAB_REST_SECONDS = 0.45
LAB_PULSE_WIDTH_RATIO = 1.0
LAB_ENVELOPE_POWER = 1.0

LAB_CONFIG = PulseConfig(
    mode=LAB_MODE,
    color_strength=LAB_COLOR_STRENGTH,
    travel_seconds=LAB_TRAVEL_SECONDS,
    rest_seconds=LAB_REST_SECONDS,
    pulse_width_ratio=LAB_PULSE_WIDTH_RATIO,
    envelope_power=LAB_ENVELOPE_POWER,
)


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
    print(
        f"mode={LAB_MODE} strength={LAB_COLOR_STRENGTH:.0%} "
        f"travel={LAB_TRAVEL_SECONDS:.2f}s "
        f"width={LAB_PULSE_WIDTH_RATIO:.2f} "
        f"envelope={LAB_ENVELOPE_POWER:.2f}"
    )

    with activity_pulse(DEMO_TEXT, config=LAB_CONFIG):
        stop_reason = _wait_for_lab_stop()

    print(
        f"Activity line released. "
        f"Stop reason: {stop_reason}."
    )


if __name__ == "__main__":
    _simulate_caller()
