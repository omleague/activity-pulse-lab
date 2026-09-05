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


def test_default_config_is_valid() -> None:
    assert DEFAULT_PULSE_CONFIG.color_schemes == DEFAULT_COLOR_SCHEMES


def test_default_palette_is_magenta_cyan_orange() -> None:
    assert DEFAULT_COLOR_SCHEMES == (
        ((255, 151, 239), (157, 20, 139)),
        ((151, 236, 249), (20, 126, 145)),
        ((247, 174, 112), (174, 82, 23)),
    )
    assert DEFAULT_PULSE_CONFIG.color_strength == 1.0
    assert DEFAULT_PULSE_CONFIG.blend_between_schemes is False


def test_color_schemes_advance_without_transition_cycles() -> None:
    assert pulse_module._scheme_for_cycle(
        0,
        0,
        DEFAULT_COLOR_SCHEMES,
    ) == DEFAULT_COLOR_SCHEMES[0]

    assert pulse_module._scheme_for_cycle(
        1,
        0,
        DEFAULT_COLOR_SCHEMES,
    ) == DEFAULT_COLOR_SCHEMES[1]

    assert pulse_module._scheme_for_cycle(
        2,
        0,
        DEFAULT_COLOR_SCHEMES,
    ) == DEFAULT_COLOR_SCHEMES[2]

    assert pulse_module._scheme_for_cycle(
        3,
        0,
        DEFAULT_COLOR_SCHEMES,
    ) == DEFAULT_COLOR_SCHEMES[0]


def test_color_cycle_preserves_requested_start_index() -> None:
    assert pulse_module._scheme_for_cycle(
        0,
        1,
        DEFAULT_COLOR_SCHEMES,
    ) == DEFAULT_COLOR_SCHEMES[1]


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


def test_empty_color_schemes_are_rejected() -> None:
    with pytest.raises(ValueError):
        PulseConfig(color_schemes=())


@pytest.mark.parametrize("value", [0, -1])
def test_refresh_rate_must_be_positive(value: int) -> None:
    with pytest.raises(ValueError):
        PulseConfig(refresh_per_second=value)


@pytest.mark.parametrize("value", [0, -1])
def test_reference_text_length_must_be_positive(value: int) -> None:
    with pytest.raises(ValueError):
        PulseConfig(reference_text_length=value)


@pytest.mark.parametrize(
    "field_name",
    [
        "expand_seconds",
        "contract_seconds",
        "initial_rest_seconds",
        "rest_seconds",
        "underglow_rise_seconds",
        "underglow_fall_seconds",
    ],
)
def test_negative_timing_values_are_rejected(field_name: str) -> None:
    with pytest.raises(ValueError):
        PulseConfig(**{field_name: -0.01})


@pytest.mark.parametrize(
    "field_name",
    [
        "expand_seconds",
        "contract_seconds",
        "rest_seconds",
    ],
)
def test_nonfinite_heartbeat_timings_are_rejected(field_name: str) -> None:
    with pytest.raises(ValueError):
        PulseConfig(**{field_name: math.inf})


def test_zero_total_heartbeat_cycle_is_rejected() -> None:
    with pytest.raises(ValueError):
        PulseConfig(
            expand_seconds=0,
            contract_seconds=0,
            rest_seconds=0,
        )


def test_safe_zero_active_heartbeat_is_allowed() -> None:
    config = PulseConfig(
        expand_seconds=0,
        contract_seconds=0,
        rest_seconds=1,
    )

    assert config.expand_seconds == 0
    assert config.contract_seconds == 0


def test_disabled_underglow_may_have_zero_cycle() -> None:
    config = PulseConfig(
        underglow_enabled=False,
        underglow_rise_seconds=0,
        underglow_fall_seconds=0,
    )

    assert config.underglow_enabled is False


def test_enabled_underglow_requires_nonzero_cycle() -> None:
    with pytest.raises(ValueError):
        PulseConfig(
            underglow_enabled=True,
            underglow_rise_seconds=0,
            underglow_fall_seconds=0,
        )


def test_enabled_underglow_allows_one_zero_leg() -> None:
    PulseConfig(
        underglow_enabled=True,
        underglow_rise_seconds=0,
        underglow_fall_seconds=2,
    )

    PulseConfig(
        underglow_enabled=True,
        underglow_rise_seconds=2,
        underglow_fall_seconds=0,
    )


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        (0, 1),
        (-1, 1),
        (1, 0),
        (1, -1),
        (2, 1),
        (math.inf, math.inf),
    ],
)
def test_invalid_beat_scale_relationships_are_rejected(
    minimum: float,
    maximum: float,
) -> None:
    with pytest.raises(ValueError):
        PulseConfig(
            min_beat_scale=minimum,
            max_beat_scale=maximum,
        )


def test_nonfinite_color_strength_is_rejected() -> None:
    with pytest.raises(ValueError):
        PulseConfig(color_strength=math.nan)


def test_nonfinite_overshoot_is_rejected() -> None:
    with pytest.raises(ValueError):
        PulseConfig(pulse_overshoot=math.inf)


def test_interpolate_rgb_clamps_amount() -> None:
    assert pulse_module._interpolate_rgb((0, 0, 0), (100, 100, 100), -1) == (
        0,
        0,
        0,
    )
    assert pulse_module._interpolate_rgb((0, 0, 0), (100, 100, 100), 2) == (
        100,
        100,
        100,
    )


def test_dampening_zero_returns_neutral_color() -> None:
    assert pulse_module._dampen_rgb(
        (255, 0, 0),
        0,
        (235, 235, 235),
    ) == (235, 235, 235)


def test_dampening_one_returns_requested_color() -> None:
    assert pulse_module._dampen_rgb(
        (255, 0, 0),
        1,
        (235, 235, 235),
    ) == (255, 0, 0)


def test_beat_duration_scale_is_one_at_reference_length() -> None:
    config = PulseConfig(reference_text_length=32)

    assert pulse_module._beat_duration_scale(32, config) == pytest.approx(1.0)


def test_beat_duration_scale_respects_bounds() -> None:
    config = PulseConfig(
        reference_text_length=32,
        min_beat_scale=0.8,
        max_beat_scale=1.2,
    )

    assert pulse_module._beat_duration_scale(1, config) == pytest.approx(0.8)
    assert pulse_module._beat_duration_scale(10000, config) == pytest.approx(
        1.2
    )


def test_rendering_never_changes_caller_text() -> None:
    rendered = pulse_module._render_heartbeat_frame(
        "Working -",
        1.0,
        DEFAULT_COLOR_SCHEMES[0],
        None,
        bold_active_text=True,
        color_strength=0.3,
        neutral_dampening_color=(235, 235, 235),
    )

    assert rendered.plain == "Working -"


def test_center_out_frame_styles_center_first() -> None:
    rendered = pulse_module._render_heartbeat_frame(
        "ABCDE",
        0.0,
        DEFAULT_COLOR_SCHEMES[0],
        None,
        bold_active_text=True,
        color_strength=0.3,
        neutral_dampening_color=(235, 235, 235),
    )

    assert any(span.start == 2 and span.end == 3 for span in rendered.spans)


def test_enabled_false_prints_static_text_before_work(
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


def test_runtime_error_propagates_same_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    error = RuntimeError("boom")

    with pytest.raises(RuntimeError) as caught:
        with activity_pulse(
            "Working -",
            console=_interactive_console()[0],
        ):
            raise error

    assert caught.value is error


def test_keyboard_interrupt_propagates_same_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    error = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt) as caught:
        with activity_pulse(
            "Working -",
            console=_interactive_console()[0],
        ):
            raise error

    assert caught.value is error


def test_system_exit_propagates_same_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pulse_module, "Live", RecordingLive)

    error = SystemExit(7)

    with pytest.raises(SystemExit) as caught:
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


def test_color_schemes_can_opt_into_transition_cycles() -> None:
    expected = pulse_module._interpolate_scheme(
        DEFAULT_COLOR_SCHEMES[0],
        DEFAULT_COLOR_SCHEMES[1],
        0.5,
    )

    assert pulse_module._scheme_for_cycle(
        1,
        0,
        DEFAULT_COLOR_SCHEMES,
        blend_between_schemes=True,
    ) == expected