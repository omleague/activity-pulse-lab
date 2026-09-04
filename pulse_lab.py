from __future__ import annotations

import time
import os
import random
from math import sqrt
from contextlib import contextmanager
from time import monotonic
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.text import Text


RGB = tuple[int, int, int]
ColorScheme = tuple[RGB, RGB]


# ---------------------------------------------------------------------------
# VISUAL LAB CONTROLS
#
# Change these freely while we experiment.
# ---------------------------------------------------------------------------

# Ordered activity spectrum.
#
# These are intentionally separated enough to make progression obvious.
# Order matters: the animation advances through this tuple and only wraps
# to the beginning after reaching the final scheme.
COLOR_SCHEMES: tuple[ColorScheme, ...] = (
    # Magenta
    ((255, 151, 239), (157, 20, 139)),

    # Violet
    ((215, 164, 255), (101, 35, 177)),

    # Cyan
    ((151, 236, 249), (20, 126, 145)),

    # Teal
    ((143, 224, 209), (20, 112, 105)),

    # Burnt orange
    ((247, 174, 112), (174, 82, 23)),

    # Copper
    ((225, 162, 126), (133, 72, 43)),

    # Umber
    ((196, 157, 126), (92, 59, 40)),
)

REFRESH_PER_SECOND = 60

EXPAND_SECONDS = 0.2
CONTRACT_SECONDS = .3

INITIAL_REST_SECONDS = 1.50
REST_SECONDS = 1.5

BOLD_ACTIVE_TEXT = True
PULSE_OVERSHOOT = 0.35

REFERENCE_TEXT_LENGTH = 32

MIN_BEAT_SCALE = 0.85
MAX_BEAT_SCALE = 1.35

UNDERGLOW_ENABLED = False

ACTIVITY_REST_COLOR: RGB = (135, 135, 135)
UNDERGLOW_PEAK_COLOR: RGB = (220, 220, 220)

UNDERGLOW_RISE_SECONDS = 20.0
UNDERGLOW_FALL_SECONDS = 20.0


# ---------------------------------------------------------------------------
# TEMPORARY CALLER SIMULATION
#
# This is not a human interface.
# It merely stands in for another Python program calling the visual helper.
# ---------------------------------------------------------------------------

DEMO_TEXT = "Verifying vault integrity - but using a longer string."

DEMO_STOP_KEY = "r"
DEMO_AUTO_STOP_SECONDS = 300.0
DEMO_POLL_SECONDS = 0.03


def _interpolate_rgb(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    """Return the RGB color between two endpoint colors."""
    amount = max(0.0, min(1.0, amount))

    return (
        round(start[0] + ((end[0] - start[0]) * amount)),
        round(start[1] + ((end[1] - start[1]) * amount)),
        round(start[2] + ((end[2] - start[2]) * amount)),
    )


def _interpolate_scheme(
    start: ColorScheme,
    end: ColorScheme,
    amount: float,
) -> ColorScheme:
    """Return a color scheme between two endpoint schemes."""
    return (
        _interpolate_rgb(start[0], end[0], amount),
        _interpolate_rgb(start[1], end[1], amount),
    )


def _scheme_for_cycle(
    cycle_number: int,
    start_index: int,
) -> ColorScheme:
    """Advance forward from one chosen starting point in the color spectrum."""
    stable_count = len(COLOR_SCHEMES)

    stable_offset = cycle_number // 2
    stable_index = (start_index + stable_offset) % stable_count
    current_scheme = COLOR_SCHEMES[stable_index]

    if cycle_number % 2 == 0:
        return current_scheme

    next_index = (stable_index + 1) % stable_count
    next_scheme = COLOR_SCHEMES[next_index]

    return _interpolate_scheme(
        current_scheme,
        next_scheme,
        0.5,
    )


def _rgb_style(
    rgb: tuple[int, int, int],
    *,
    bold: bool = False,
) -> Style:
    """Build one Rich foreground style from an RGB tuple."""
    red, green, blue = rgb
    return Style(color=f"rgb({red},{green},{blue})", bold=bold)


def _center_distance(index: int, text_length: int) -> float:
    """Return a character's distance from the visual center of the text."""
    center = (text_length - 1) / 2
    return abs(index - center)


def _maximum_center_distance(text_length: int) -> float:
    """Return the farthest character distance from the visual center."""
    if text_length <= 1:
        return 0.0

    return (text_length - 1) / 2


def _beat_duration_scale(text_length: int) -> float:
    """Return a gentle heartbeat-duration adjustment for text length."""
    if text_length <= 0:
        return 1.0

    scale = sqrt(text_length / REFERENCE_TEXT_LENGTH)

    return max(
        MIN_BEAT_SCALE,
        min(MAX_BEAT_SCALE, scale),
    )


def _underglow_amount(elapsed: float) -> float:
    """Return the slow neutral-to-white activity drift."""
    cycle_seconds = UNDERGLOW_RISE_SECONDS + UNDERGLOW_FALL_SECONDS
    cycle_position = elapsed % cycle_seconds

    if cycle_position < UNDERGLOW_RISE_SECONDS:
        return cycle_position / UNDERGLOW_RISE_SECONDS

    fall_position = cycle_position - UNDERGLOW_RISE_SECONDS

    return 1.0 - (fall_position / UNDERGLOW_FALL_SECONDS)


def _activity_rest_color(elapsed: float) -> RGB | None:
    """Return the activity rest color, or terminal default when disabled."""
    if not UNDERGLOW_ENABLED:
        return None

    return _interpolate_rgb(
        ACTIVITY_REST_COLOR,
        UNDERGLOW_PEAK_COLOR,
        _underglow_amount(elapsed),
    )


def _render_baseline(
    text: str,
    color: RGB | None = None,
) -> Text:
    """Return stationary baseline text."""
    if color is None:
        return Text(text)

    return Text(
        text,
        style=_rgb_style(color),
    )


def _render_heartbeat_frame(
    text: str,
    progress: float,
    scheme: ColorScheme,
    rest_color: RGB | None,
) -> Text:
    """Render one center-out heartbeat frame without moving the characters."""
    if not text:
        return Text()

    rendered = _render_baseline(
        text,
        rest_color,
    )

    maximum_distance = _maximum_center_distance(len(text))

    light_color, dark_color = scheme

    for index in range(len(text)):
        distance = _center_distance(index, len(text))

        if maximum_distance == 0:
            normalized_distance = 0.0
        else:
            normalized_distance = distance / maximum_distance

        if normalized_distance > progress:
            continue

        intensity = progress - normalized_distance

        pulse_rgb = _interpolate_rgb(
            light_color,
            dark_color,
            intensity,
        )

        rendered.stylize(
            _rgb_style(
                pulse_rgb,
                bold=BOLD_ACTIVE_TEXT,
            ),
            index,
            index + 1,
        )

    return rendered


class _HeartbeatRenderable:
    """Time-driven Rich renderable for one indeterminate activity heartbeat."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.started_at = monotonic()

        self.start_scheme_index = random.randrange(len(COLOR_SCHEMES))

        duration_scale = _beat_duration_scale(len(text))

        self.expand_seconds = EXPAND_SECONDS * duration_scale
        self.contract_seconds = CONTRACT_SECONDS * duration_scale

        self.active_seconds = self.expand_seconds + self.contract_seconds
        self.cycle_seconds = self.active_seconds + REST_SECONDS

    def __rich__(self) -> Text:
        """Return the frame appropriate for the current point in the cycle."""
        if not self.text:
            return Text()

        elapsed = monotonic() - self.started_at
        rest_color = _activity_rest_color(elapsed)

        if elapsed < INITIAL_REST_SECONDS:
            return _render_baseline(
                self.text,
                rest_color,
            )

        active_elapsed = elapsed - INITIAL_REST_SECONDS

        cycle_number = int(active_elapsed // self.cycle_seconds)
        cycle_position = active_elapsed % self.cycle_seconds

        scheme = _scheme_for_cycle(
            cycle_number,
            self.start_scheme_index,
        )

        if cycle_position >= self.active_seconds:
            return _render_baseline(
                self.text,
                rest_color,
            )

        peak_progress = 1.0 + PULSE_OVERSHOOT

        if cycle_position < self.expand_seconds:
            progress = (
                cycle_position / self.expand_seconds
            ) * peak_progress
        else:
            contraction_position = cycle_position - self.expand_seconds
            contraction_progress = (
                contraction_position / self.contract_seconds
            )
            progress = peak_progress * (1.0 - contraction_progress)

        return _render_heartbeat_frame(
            self.text,
            progress,
            scheme,
            rest_color,
        )


@contextmanager
def activity_pulse(
    text: str,
    *,
    console: Console | None = None,
) -> Iterator[None]:
    """
    Show indeterminate heartbeat activity while the caller performs work.

    The helper owns presentation cleanup only. Exceptions and interruptions
    from the caller are deliberately allowed to continue outward unchanged.
    """
    active_console = console or Console()
    heartbeat = _HeartbeatRenderable(text)
    baseline = _render_baseline(text)

    with Live(
        heartbeat,
        console=active_console,
        refresh_per_second=REFRESH_PER_SECOND,
        transient=False,
    ) as live:
        try:
            yield
        finally:
            live.update(baseline, refresh=True)


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

                ready, _, _ = select.select([sys.stdin], [], [], 0)

                if ready:
                    key = sys.stdin.read(1)

            if key and key.casefold() == DEMO_STOP_KEY:
                return f"{DEMO_STOP_KEY.upper()} key"

            time.sleep(DEMO_POLL_SECONDS)

    return "automatic timeout"


def _simulate_caller() -> None:
    """Simulate a larger program explicitly ending the activity scope."""
    print(
        f"Pulse running. Press {DEMO_STOP_KEY.upper()} to stop "
        f"(automatic stop after {DEMO_AUTO_STOP_SECONDS:g} seconds)."
    )

    with activity_pulse(DEMO_TEXT):
        stop_reason = _wait_for_lab_stop()

    print(f"Activity line released. Stop reason: {stop_reason}.")


if __name__ == "__main__":
    _simulate_caller()