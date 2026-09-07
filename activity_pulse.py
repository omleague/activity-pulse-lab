"""Reusable indeterminate activity pulse for Rich terminal output."""

from __future__ import annotations

import random
from contextlib import contextmanager
from dataclasses import dataclass
from math import cos, isfinite, pi
from time import monotonic
from typing import Iterator, Literal

from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.text import Text


__all__ = [
    "DEFAULT_COLOR_SCHEMES",
    "DEFAULT_PULSE_CONFIG",
    "PulseConfig",
    "activity_pulse",
]

RGB = tuple[int, int, int]
ColorScheme = tuple[RGB, RGB]
PulseMode = Literal["left_to_right", "right_to_left", "bounce"]


DEFAULT_COLOR_SCHEMES: tuple[ColorScheme, ...] = (
    ((255, 174, 174), (205, 45, 45)),    # Red
    ((255, 198, 145), (220, 96, 25)),    # Orange
    ((255, 220, 145), (208, 142, 20)),   # Amber
    ((255, 239, 155), (190, 164, 20)),   # Yellow
    ((210, 244, 155), (100, 168, 35)),   # Lime
    ((155, 238, 185), (30, 150, 82)),    # Green
    ((150, 234, 239), (25, 145, 165)),   # Cyan
    ((155, 198, 250), (45, 98, 205)),    # Blue
    ((192, 170, 250), (105, 65, 198)),   # Violet
    ((247, 170, 228), (185, 55, 150)),   # Magenta
)


@dataclass(frozen=True)
class PulseConfig:
    """Visual and timing controls for the activity pulse."""

    color_schemes: tuple[ColorScheme, ...] = DEFAULT_COLOR_SCHEMES
    mode: PulseMode = "left_to_right"

    refresh_per_second: int = 60
    travel_seconds: float = 0.65
    initial_rest_seconds: float = 0.75
    rest_seconds: float = 0.45

    bold_active_text: bool = True
    color_strength: float = 0.30
    neutral_dampening_color: RGB = (235, 235, 235)

    pulse_width_ratio: float = 1.0
    envelope_power: float = 1.0

    underglow_enabled: bool = False
    activity_rest_color: RGB = (135, 135, 135)
    underglow_peak_color: RGB = (220, 220, 220)
    underglow_rise_seconds: float = 20.0
    underglow_fall_seconds: float = 20.0

    def __post_init__(self) -> None:
        """Reject configuration values that make rendering undefined."""
        if not self.color_schemes:
            raise ValueError("PulseConfig.color_schemes must not be empty.")

        if self.mode not in ("left_to_right", "right_to_left", "bounce"):
            raise ValueError(
                "PulseConfig.mode must be 'left_to_right', "
                "'right_to_left', or 'bounce'."
            )

        if self.refresh_per_second <= 0:
            raise ValueError(
                "PulseConfig.refresh_per_second must be greater than zero."
            )

        timing_values = (
            ("travel_seconds", self.travel_seconds),
            ("initial_rest_seconds", self.initial_rest_seconds),
            ("rest_seconds", self.rest_seconds),
            ("underglow_rise_seconds", self.underglow_rise_seconds),
            ("underglow_fall_seconds", self.underglow_fall_seconds),
        )

        for name, value in timing_values:
            if not isfinite(value) or value < 0:
                raise ValueError(
                    f"PulseConfig.{name} must be finite and non-negative."
                )

        if self.travel_seconds <= 0:
            raise ValueError(
                "PulseConfig.travel_seconds must be greater than zero."
            )

        if (
            self.underglow_enabled
            and self.underglow_rise_seconds
            + self.underglow_fall_seconds
            == 0
        ):
            raise ValueError(
                "Enabled underglow must have a non-zero cycle duration."
            )

        if (
            not isfinite(self.color_strength)
            or not 0.0 <= self.color_strength <= 1.0
        ):
            raise ValueError(
                "PulseConfig.color_strength must be finite and between 0 and 1."
            )

        if (
            not isfinite(self.pulse_width_ratio)
            or self.pulse_width_ratio <= 0
        ):
            raise ValueError(
                "PulseConfig.pulse_width_ratio must be finite and positive."
            )

        if (
            not isfinite(self.envelope_power)
            or self.envelope_power <= 0
        ):
            raise ValueError(
                "PulseConfig.envelope_power must be finite and positive."
            )


DEFAULT_PULSE_CONFIG = PulseConfig()


def _interpolate_rgb(
    start: RGB,
    end: RGB,
    amount: float,
) -> RGB:
    amount = max(0.0, min(1.0, amount))

    return (
        round(start[0] + ((end[0] - start[0]) * amount)),
        round(start[1] + ((end[1] - start[1]) * amount)),
        round(start[2] + ((end[2] - start[2]) * amount)),
    )


def _dampen_rgb(
    rgb: RGB,
    strength: float,
    neutral: RGB,
) -> RGB:
    strength = max(0.0, min(1.0, strength))

    return _interpolate_rgb(
        neutral,
        rgb,
        strength,
    )


def _scheme_for_cycle(
    cycle_number: int,
    start_index: int,
    color_schemes: tuple[ColorScheme, ...],
) -> ColorScheme:
    return color_schemes[
        (start_index + cycle_number) % len(color_schemes)
    ]


def _activity_style(
    rgb: RGB | None,
    *,
    bold: bool = False,
) -> Style:
    if rgb is None:
        return Style(bold=bold)

    red, green, blue = rgb

    return Style(
        color=f"rgb({red},{green},{blue})",
        bold=bold,
    )


def _underglow_amount(
    elapsed: float,
    config: PulseConfig,
) -> float:
    cycle_seconds = (
        config.underglow_rise_seconds + config.underglow_fall_seconds
    )
    cycle_position = elapsed % cycle_seconds

    if cycle_position < config.underglow_rise_seconds:
        if config.underglow_rise_seconds == 0:
            return 1.0
        return cycle_position / config.underglow_rise_seconds

    fall_position = cycle_position - config.underglow_rise_seconds

    if config.underglow_fall_seconds == 0:
        return 0.0

    return 1.0 - (fall_position / config.underglow_fall_seconds)


def _activity_rest_color(
    elapsed: float,
    config: PulseConfig,
) -> RGB | None:
    if not config.underglow_enabled:
        return None

    return _interpolate_rgb(
        config.activity_rest_color,
        config.underglow_peak_color,
        _underglow_amount(elapsed, config),
    )


def _render_baseline(
    text: str,
    color: RGB | None = None,
) -> Text:
    if color is None:
        return Text(text)

    return Text(
        text,
        style=_activity_style(color),
    )


def _pulse_radius(
    text_length: int,
    pulse_width_ratio: float,
) -> float:
    if text_length <= 0:
        return 0.0

    return max(0.5, (text_length * pulse_width_ratio) / 2.0)


def _pulse_center(
    text_length: int,
    progress: float,
    pulse_width_ratio: float,
) -> float:
    radius = _pulse_radius(text_length, pulse_width_ratio)
    start = -radius
    end = (text_length - 1) + radius

    return start + ((end - start) * max(0.0, min(1.0, progress)))


def _envelope_amount(
    distance: float,
    radius: float,
    envelope_power: float,
) -> float:
    if radius <= 0 or distance >= radius:
        return 0.0

    normalized = distance / radius
    smooth_amount = (1.0 + cos(pi * normalized)) / 2.0

    return smooth_amount ** envelope_power


def _render_travel_frame(
    text: str,
    progress: float,
    scheme: ColorScheme,
    rest_color: RGB | None,
    *,
    bold_active_text: bool,
    color_strength: float,
    neutral_dampening_color: RGB,
    pulse_width_ratio: float,
    envelope_power: float,
) -> Text:
    if not text:
        return Text()

    rendered = _render_baseline(text, rest_color)
    radius = _pulse_radius(len(text), pulse_width_ratio)
    center = _pulse_center(
        len(text),
        progress,
        pulse_width_ratio,
    )
    light_color, dark_color = scheme

    for index in range(len(text)):
        amount = _envelope_amount(
            abs(index - center),
            radius,
            envelope_power,
        )

        if amount <= 0.0:
            continue

        full_pulse_rgb = _interpolate_rgb(
            light_color,
            dark_color,
            amount,
        )
        pulse_rgb = _dampen_rgb(
            full_pulse_rgb,
            color_strength,
            neutral_dampening_color,
        )

        rendered.stylize(
            _activity_style(
                pulse_rgb,
                bold=bold_active_text,
            ),
            index,
            index + 1,
        )

    return rendered


def _cycle_timing(
    elapsed: float,
    config: PulseConfig,
) -> tuple[int, float] | None:
    active_seconds = (
        config.travel_seconds * 2
        if config.mode == "bounce"
        else config.travel_seconds
    )
    cycle_seconds = active_seconds + config.rest_seconds

    cycle_number = int(elapsed // cycle_seconds)
    cycle_position = elapsed % cycle_seconds

    if cycle_position >= active_seconds:
        return None

    if config.mode == "bounce":
        if cycle_position < config.travel_seconds:
            progress = cycle_position / config.travel_seconds
        else:
            reverse_position = cycle_position - config.travel_seconds
            progress = 1.0 - (
                reverse_position / config.travel_seconds
            )
    else:
        progress = cycle_position / config.travel_seconds
        if config.mode == "right_to_left":
            progress = 1.0 - progress

    return cycle_number, progress


class _TravelingPulseRenderable:
    def __init__(
        self,
        text: str,
        config: PulseConfig,
    ) -> None:
        self.text = text
        self.config = config
        self.started_at = monotonic()
        self.start_scheme_index = random.randrange(
            len(config.color_schemes)
        )

    def __rich__(self) -> Text:
        if not self.text:
            return Text()

        elapsed = monotonic() - self.started_at
        rest_color = _activity_rest_color(
            elapsed,
            self.config,
        )

        if elapsed < self.config.initial_rest_seconds:
            return _render_baseline(
                self.text,
                rest_color,
            )

        active_elapsed = (
            elapsed - self.config.initial_rest_seconds
        )
        timing = _cycle_timing(
            active_elapsed,
            self.config,
        )

        if timing is None:
            return _render_baseline(
                self.text,
                rest_color,
            )

        cycle_number, progress = timing
        scheme = _scheme_for_cycle(
            cycle_number,
            self.start_scheme_index,
            self.config.color_schemes,
        )

        return _render_travel_frame(
            self.text,
            progress,
            scheme,
            rest_color,
            bold_active_text=self.config.bold_active_text,
            color_strength=self.config.color_strength,
            neutral_dampening_color=self.config.neutral_dampening_color,
            pulse_width_ratio=self.config.pulse_width_ratio,
            envelope_power=self.config.envelope_power,
        )


@contextmanager
def activity_pulse(
    text: str,
    *,
    console: Console | None = None,
    config: PulseConfig = DEFAULT_PULSE_CONFIG,
    enabled: bool = True,
) -> Iterator[None]:
    """
    Show indeterminate activity while the caller performs work.

    Leaving the context stops the visual and restores ordinary terminal text.
    Exceptions and interruptions from the caller are not consumed.
    """
    active_console = console or Console()
    baseline = _render_baseline(text)

    if (
        not enabled
        or not active_console.is_terminal
        or active_console.color_system is None
    ):
        active_console.print(baseline)
        yield
        return

    pulse = _TravelingPulseRenderable(
        text,
        config,
    )

    with Live(
        pulse,
        console=active_console,
        refresh_per_second=config.refresh_per_second,
        transient=False,
        redirect_stdout=False,
        redirect_stderr=False,
    ) as live:
        try:
            yield
        finally:
            live.update(
                baseline,
                refresh=True,
            )
