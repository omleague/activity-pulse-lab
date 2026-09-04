from __future__ import annotations

import random
from contextlib import contextmanager
from dataclasses import dataclass
from math import sqrt
from time import monotonic
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.style import Style
from rich.text import Text


RGB = tuple[int, int, int]
ColorScheme = tuple[RGB, RGB]


DEFAULT_COLOR_SCHEMES: tuple[ColorScheme, ...] = (
    ((255, 151, 239), (157, 20, 139)),  # Magenta
    ((215, 164, 255), (101, 35, 177)),  # Violet
    ((151, 236, 249), (20, 126, 145)),  # Cyan
    ((143, 224, 209), (20, 112, 105)),  # Teal
    ((247, 174, 112), (174, 82, 23)),  # Burnt orange
    ((225, 162, 126), (133, 72, 43)),  # Copper
    ((196, 157, 126), (92, 59, 40)),  # Umber
)


@dataclass(frozen=True)
class PulseConfig:
    """Visual and timing controls for the activity pulse."""

    color_schemes: tuple[ColorScheme, ...] = DEFAULT_COLOR_SCHEMES

    refresh_per_second: int = 60

    expand_seconds: float = 0.2
    contract_seconds: float = 0.3
    initial_rest_seconds: float = 1.5
    rest_seconds: float = 1.5

    bold_active_text: bool = True
    pulse_overshoot: float = 0.35

    reference_text_length: int = 32
    min_beat_scale: float = 0.85
    max_beat_scale: float = 1.35

    underglow_enabled: bool = False
    activity_rest_color: RGB = (135, 135, 135)
    underglow_peak_color: RGB = (220, 220, 220)
    underglow_rise_seconds: float = 20.0
    underglow_fall_seconds: float = 20.0


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


def _interpolate_scheme(
    start: ColorScheme,
    end: ColorScheme,
    amount: float,
) -> ColorScheme:
    return (
        _interpolate_rgb(start[0], end[0], amount),
        _interpolate_rgb(start[1], end[1], amount),
    )


def _scheme_for_cycle(
    cycle_number: int,
    start_index: int,
    color_schemes: tuple[ColorScheme, ...],
) -> ColorScheme:
    stable_count = len(color_schemes)
    stable_index = (start_index + (cycle_number // 2)) % stable_count
    current_scheme = color_schemes[stable_index]

    if cycle_number % 2 == 0:
        return current_scheme

    next_scheme = color_schemes[(stable_index + 1) % stable_count]
    return _interpolate_scheme(current_scheme, next_scheme, 0.5)


def _rgb_style(
    rgb: RGB,
    *,
    bold: bool = False,
) -> Style:
    red, green, blue = rgb
    return Style(color=f"rgb({red},{green},{blue})", bold=bold)


def _maximum_center_distance(text_length: int) -> float:
    if text_length <= 1:
        return 0.0

    return (text_length - 1) / 2


def _beat_duration_scale(
    text_length: int,
    config: PulseConfig,
) -> float:
    if text_length <= 0:
        return 1.0

    scale = sqrt(text_length / config.reference_text_length)

    return max(
        config.min_beat_scale,
        min(config.max_beat_scale, scale),
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
        return cycle_position / config.underglow_rise_seconds

    fall_position = cycle_position - config.underglow_rise_seconds

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
        style=_rgb_style(color),
    )


def _render_heartbeat_frame(
    text: str,
    progress: float,
    scheme: ColorScheme,
    rest_color: RGB | None,
    *,
    bold_active_text: bool,
) -> Text:
    if not text:
        return Text()

    rendered = _render_baseline(text, rest_color)
    maximum_distance = _maximum_center_distance(len(text))
    center = (len(text) - 1) / 2
    light_color, dark_color = scheme

    for index in range(len(text)):
        distance = abs(index - center)

        normalized_distance = (
            0.0
            if maximum_distance == 0
            else distance / maximum_distance
        )

        if normalized_distance > progress:
            continue

        pulse_rgb = _interpolate_rgb(
            light_color,
            dark_color,
            progress - normalized_distance,
        )

        rendered.stylize(
            _rgb_style(
                pulse_rgb,
                bold=bold_active_text,
            ),
            index,
            index + 1,
        )

    return rendered


class _HeartbeatRenderable:
    def __init__(
        self,
        text: str,
        config: PulseConfig,
    ) -> None:
        if not config.color_schemes:
            raise ValueError("PulseConfig.color_schemes must not be empty.")

        self.text = text
        self.config = config
        self.started_at = monotonic()

        self.start_scheme_index = random.randrange(
            len(config.color_schemes)
        )

        duration_scale = _beat_duration_scale(
            len(text),
            config,
        )

        self.expand_seconds = config.expand_seconds * duration_scale
        self.contract_seconds = config.contract_seconds * duration_scale

        self.active_seconds = (
            self.expand_seconds + self.contract_seconds
        )
        self.cycle_seconds = (
            self.active_seconds + config.rest_seconds
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

        cycle_number = int(
            active_elapsed // self.cycle_seconds
        )
        cycle_position = (
            active_elapsed % self.cycle_seconds
        )

        if cycle_position >= self.active_seconds:
            return _render_baseline(
                self.text,
                rest_color,
            )

        scheme = _scheme_for_cycle(
            cycle_number,
            self.start_scheme_index,
            self.config.color_schemes,
        )

        peak_progress = (
            1.0 + self.config.pulse_overshoot
        )

        if cycle_position < self.expand_seconds:
            progress = (
                cycle_position / self.expand_seconds
            ) * peak_progress
        else:
            contraction_position = (
                cycle_position - self.expand_seconds
            )
            contraction_progress = (
                contraction_position / self.contract_seconds
            )
            progress = (
                peak_progress
                * (1.0 - contraction_progress)
            )

        return _render_heartbeat_frame(
            self.text,
            progress,
            scheme,
            rest_color,
            bold_active_text=self.config.bold_active_text,
        )


@contextmanager
def activity_pulse(
    text: str,
    *,
    console: Console | None = None,
    config: PulseConfig = DEFAULT_PULSE_CONFIG,
) -> Iterator[None]:
    """
    Show indeterminate activity while the caller performs work.

    Leaving the context stops the visual and restores ordinary terminal text.
    Exceptions and interruptions from the caller are not consumed.
    """
    active_console = console or Console()
    heartbeat = _HeartbeatRenderable(
        text,
        config,
    )
    baseline = _render_baseline(text)

    with Live(
        heartbeat,
        console=active_console,
        refresh_per_second=config.refresh_per_second,
        transient=False,
    ) as live:
        try:
            yield
        finally:
            live.update(
                baseline,
                refresh=True,
            )