"""Mechanical protection for the reusable activity pulse."""

from __future__ import annotations

import inspect
import io
import math
import signal

import pytest
from rich.console import Console
from rich.text import Text

import activity_pulse as pulse_module
from activity_pulse import (
    DEFAULT_COLOR_SCHEMES,
    DEFAULT_PULSE_CONFIG,
    PulseConfig,
    activity_pulse,
)


class RecordingLive:
    """Small Live stand-in for testing context-manager behavior."""

    instances: list["RecordingLive"] = []

    def __init__(self, renderable, **kwargs) -> None:
        self.renderable = renderable
        self.kwargs = kwargs
        self.updates: list[tuple[object, bool]] = []
        self.entered = False
        self.exited = False
        RecordingLive.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True
        return False

    def update(self, renderable, *, refresh=False) -> None:
        self.updates.append((renderable, refresh))


@pytest.fixture(autouse=True)
def _clear_recording_live() -> None:
    RecordingLive.instances.clear()


def _interactive_console(
    *,
    no_color: bool = False,
) -> tuple[Console, io.StringIO]:
    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system="truecolor",
        no_color=no_color,
    )
    return console, stream


def _active_indexes(rendered: Text) -> set[int]:
    return {
        span.start
        for span in rendered.spans
        if span.end == span.start + 1 and span.style.bold
    }


def test_default_config_is_valid() -> None:
    assert DEFAULT_PULSE_CONFIG.color_schemes == DEFAULT_COLOR_SCHEMES


def test_default_palette_is_ten_color_rainbow() -> None:
    assert len(DEFAULT_COLOR_SCHEMES) == 10
    assert DEFAULT_PULSE_CONFIG.color_strength == pytest.approx(0.30)
    assert DEFAULT_PULSE_CONFIG.mode == "left_to_right"


def test_color_schemes_progress_from_random_start() -> None:
    assert pulse_module._scheme_for_cycle(
        0, 8, DEFAULT_COLOR_SCHEMES
    ) == DEFAULT_COLOR_SCHEMES[8]
    assert pulse_module._scheme_for_cycle(
        1, 8, DEFAULT_COLOR_SCHEMES
    ) == DEFAULT_COLOR_SCHEMES[9]
    assert pulse_module._scheme_for_cycle(
        2, 8, DEFAULT_COLOR_SCHEMES
    ) == DEFAULT_COLOR_SCHEMES[0]


def test_public_api_is_explicit() -> None:
    assert pulse_module.__all__ == [
        "DEFAULT_COLOR_SCHEMES",
        "DEFAULT_PULSE_CONFIG",
        "PulseConfig",
        "activity_pulse",
    ]


def test_activity_pulse_keeps_small_public_signature() -> None:
    assert list(inspect.signature(activity_pulse).parameters) == [
        "text",
        "console",
        "config",
        "enabled",
    ]


@pytest.mark.parametrize(
    "mode",
    ["left_to_right", "right_to_left", "bounce"],
)
def test_supported_modes(mode: str) -> None:
    assert PulseConfig(mode=mode).mode == mode


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        PulseConfig(mode="sideways")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0.0, -0.1, math.inf])
def test_invalid_travel_seconds_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        PulseConfig(travel_seconds=value)


@pytest.mark.parametrize("value", [-0.1, 1.1, math.nan])
def test_invalid_color_strength_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        PulseConfig(color_strength=value)


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf])
def test_invalid_width_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        PulseConfig(pulse_width_ratio=value)


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf])
def test_invalid_envelope_power_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        PulseConfig(envelope_power=value)


def test_pulse_width_defaults_to_phrase_length() -> None:
    assert pulse_module._pulse_radius(20, 1.0) == pytest.approx(10.0)


def test_left_edge_enters_before_center() -> None:
    text = "ABCDEFGHIJK"
    scheme = DEFAULT_COLOR_SCHEMES[0]

    entering = pulse_module._render_travel_frame(
        text,
        0.10,
        scheme,
        None,
        bold_active_text=True,
        color_strength=0.3,
        neutral_dampening_color=(235, 235, 235),
        pulse_width_ratio=1.0,
        envelope_power=1.0,
    )
    active = _active_indexes(entering)

    assert active
    assert min(active) == 0
    assert max(active) < len(text) // 2


def test_midpoint_touches_entire_phrase() -> None:
    text = "ABCDEFGHIJK"
    scheme = DEFAULT_COLOR_SCHEMES[0]

    midpoint = pulse_module._render_travel_frame(
        text,
        0.50,
        scheme,
        None,
        bold_active_text=True,
        color_strength=0.3,
        neutral_dampening_color=(235, 235, 235),
        pulse_width_ratio=1.0,
        envelope_power=1.0,
    )

    assert _active_indexes(midpoint) == set(range(len(text)))


def test_right_edge_is_last_visible_region() -> None:
    text = "ABCDEFGHIJK"
    scheme = DEFAULT_COLOR_SCHEMES[0]

    leaving = pulse_module._render_travel_frame(
        text,
        0.90,
        scheme,
        None,
        bold_active_text=True,
        color_strength=0.3,
        neutral_dampening_color=(235, 235, 235),
        pulse_width_ratio=1.0,
        envelope_power=1.0,
    )
    active = _active_indexes(leaving)

    assert active
    assert max(active) == len(text) - 1
    assert min(active) > len(text) // 2


def test_center_is_stronger_than_edges() -> None:
    radius = 10.0
    center = pulse_module._envelope_amount(0.0, radius, 1.0)
    halfway = pulse_module._envelope_amount(5.0, radius, 1.0)
    edge = pulse_module._envelope_amount(9.9, radius, 1.0)

    assert center > halfway > edge > 0.0


def test_bounce_goes_forward_then_back_without_rest_between_legs() -> None:
    config = PulseConfig(
        mode="bounce",
        travel_seconds=1.0,
        rest_seconds=0.5,
    )

    assert pulse_module._cycle_timing(0.25, config) == pytest.approx((0, 0.25))
    assert pulse_module._cycle_timing(1.25, config) == pytest.approx((0, 0.75))
    assert pulse_module._cycle_timing(1.75, config) == pytest.approx((0, 0.25))
    assert pulse_module._cycle_timing(2.25, config) is None


def test_right_to_left_reverses_progress() -> None:
    config = PulseConfig(
        mode="right_to_left",
        travel_seconds=1.0,
        rest_seconds=0.5,
    )
    cycle, progress = pulse_module._cycle_timing(0.25, config)
    assert cycle == 0
    assert progress == pytest.approx(0.75)


def test_rendering_never_changes_caller_text() -> None:
    rendered = pulse_module._render_travel_frame(
        "Working -",
        0.5,
        DEFAULT_COLOR_SCHEMES[0],
        None,
        bold_active_text=True,
        color_strength=0.3,
        neutral_dampening_color=(235, 235, 235),
        pulse_width_ratio=1.0,
        envelope_power=1.0,
    )

    assert rendered.plain == "Working -"


def test_disabled_false_prints_static_text_before_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console, stream = _interactive_console()

    def bomb_live(*_args, **_kwargs):
        raise AssertionError("Live must not start.")

    monkeypatch.setattr(pulse_module, "Live", bomb_live)

    with activity_pulse(
        "Working -",
        console=console,
        enabled=False,
    ):
        assert "Working -" in stream.getvalue()


def test_non_tty_uses_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=False,
    )

    def bomb_live(*_args, **_kwargs):
        raise AssertionError("Live must not start.")

    monkeypatch.setattr(pulse_module, "Live", bomb_live)

    with activity_pulse("Working -", console=console):
        pass

    assert "Working -" in stream.getvalue()


def test_color_system_none_uses_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        color_system=None,
    )

    def bomb_live(*_args, **_kwargs):
        raise AssertionError("Live must not start.")

    monkeypatch.setattr(pulse_module, "Live", bomb_live)

    with activity_pulse("Working -", console=console):
        pass

    assert "Working -" in stream.getvalue()


def test_no_color_does_not_disable_animation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    console, _ = _interactive_console(no_color=True)

    with activity_pulse("Working -", console=console):
        pass

    assert len(RecordingLive.instances) == 1


def test_callers_console_is_given_to_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    console, _ = _interactive_console()

    with activity_pulse("Working -", console=console):
        pass

    live = RecordingLive.instances[0]
    assert live.kwargs["console"] is console


def test_live_does_not_redirect_stdout_or_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    with activity_pulse(
        "Working -",
        console=_interactive_console()[0],
    ):
        pass

    live = RecordingLive.instances[0]

    assert live.kwargs["redirect_stdout"] is False
    assert live.kwargs["redirect_stderr"] is False


def test_live_is_non_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    with activity_pulse(
        "Working -",
        console=_interactive_console()[0],
    ):
        pass

    assert RecordingLive.instances[0].kwargs["transient"] is False


def test_clean_exit_restores_static_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    with activity_pulse(
        "Working -",
        console=_interactive_console()[0],
    ):
        pass

    live = RecordingLive.instances[0]

    assert len(live.updates) == 1

    final_renderable, refresh = live.updates[0]

    assert isinstance(final_renderable, Text)
    assert final_renderable.plain == "Working -"
    assert refresh is True
    assert live.exited is True


@pytest.mark.parametrize(
    "error",
    [RuntimeError("boom"), KeyboardInterrupt(), SystemExit(7)],
)
def test_caller_exception_propagates_same_exception(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    with pytest.raises(type(error)) as caught:
        with activity_pulse(
            "Working -",
            console=_interactive_console()[0],
        ):
            raise error

    assert caught.value is error


def test_activity_pulse_does_not_take_signal_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    def forbidden_signal_call(*_args, **_kwargs):
        raise AssertionError("Activity Pulse must not install signal handlers.")

    monkeypatch.setattr(signal, "signal", forbidden_signal_call)

    with activity_pulse(
        "Working -",
        console=_interactive_console()[0],
    ):
        pass
