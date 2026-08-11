"""Tests for the WhodunnitSensor detection cascade and lifecycle."""

import time

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    mock_restore_cache,
)

from custom_components.whodunnit.const import (
    ATTR_CACHE_DEBUG,
    ATTR_CONFIDENCE,
    ATTR_CONTEXT_ID,
    ATTR_EVENT_TIME,
    ATTR_HISTORY_LOG,
    ATTR_SOURCE_ID,
    ATTR_SOURCE_NAME,
    ATTR_SOURCE_TYPE,
    ATTR_USER_ID,
    COMMAND_ECHO_MAX_WINDOW,
    COMMAND_ECHO_WINDOW,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DOMAIN,
    EVENT_TRIGGER_DETECTED,
    ID_INDIRECT_AUTOMATION,
    NAME_DEVICE,
    NAME_INDIRECT_AUTOMATION,
    NAME_UNKNOWN_USER,
    STATE_AUTOMATION,
    STATE_DEVICE,
    STATE_MONITORING,
    STATE_SCRIPT,
    STATE_SERVICE,
    STATE_UI,
    USER_CACHE_TTL,
)
from custom_components.whodunnit.sensor import WhodunnitSensor


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _setup_sensor(
    hass,
    make_config_entry,
    register_target,
    target="switch.test",
    *,
    platform="test",
    state="off",
    attributes=None,
):
    """Register the target, set up the entry, return (entry, sensor_entity_id)."""
    register_target(target, platform=platform, state=state, attributes=attributes)
    entry = make_config_entry(target)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sensor_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{target}_whodunnit"
    )
    assert sensor_id is not None
    return entry, sensor_id


async def _fire(hass, target, new_state, *, context=None, attributes=None):
    """Drive a state change on the target entity and let the sensor react."""
    hass.states.async_set(target, new_state, attributes or {}, context=context)
    await hass.async_block_till_done()


def _attrs(hass, sensor_id):
    return hass.states.get(sensor_id).attributes


async def _make_user(hass, name="Alice", *, with_person=True):
    """Create an HA user, optionally with a matching person entity."""
    user = await hass.auth.async_create_user(name)
    if with_person:
        hass.states.async_set(
            "person.alice", "home", {"user_id": user.id, "friendly_name": name}
        )
    return user


# --------------------------------------------------------------------------- #
# Detection cascade
# --------------------------------------------------------------------------- #


async def test_device_internal_change(
    hass: HomeAssistant, make_config_entry, register_target
):
    """No user, no parent, no cache hit -> device-originated."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    await _fire(hass, "switch.test", "on", context=Context())

    state = hass.states.get(sid)
    assert state.state == STATE_DEVICE
    assert state.attributes[ATTR_SOURCE_TYPE] == "device"
    assert state.attributes[ATTR_SOURCE_NAME] == NAME_DEVICE
    assert state.attributes[ATTR_SOURCE_ID] == "switch.test"
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_HIGH


async def test_cache_hit_automation(
    hass: HomeAssistant, make_config_entry, register_target
):
    """Direct context cache hit classifies as the cached source."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context()
    cache[ctx.id] = {
        "id": "automation.morning",
        "name": "Morning Routine",
        "type": STATE_AUTOMATION,
        "timestamp": time.monotonic(),
    }
    await _fire(hass, "switch.test", "on", context=ctx)

    state = hass.states.get(sid)
    assert state.state == STATE_AUTOMATION
    assert state.attributes[ATTR_SOURCE_ID] == "automation.morning"
    assert state.attributes[ATTR_SOURCE_NAME] == "Morning Routine"
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_HIGH


async def test_cache_hit_ui_regular_user(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A UI cache entry for a real user resolves to the person entity."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    user = await _make_user(hass, "Alice", with_person=True)
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context(user_id=user.id)
    cache[ctx.id] = {"id": user.id, "type": STATE_UI, "timestamp": time.monotonic()}
    await _fire(hass, "switch.test", "on", context=ctx)

    state = hass.states.get(sid)
    assert state.state == STATE_UI
    assert state.attributes[ATTR_SOURCE_TYPE] == "user"
    assert state.attributes[ATTR_SOURCE_ID] == "person.alice"
    assert state.attributes[ATTR_SOURCE_NAME] == "Alice"
    assert state.attributes[ATTR_USER_ID] == user.id
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_HIGH


async def test_cache_hit_ui_service_account(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A UI cache entry for a user with no person entity is a service account."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    user = await _make_user(hass, "Node-RED", with_person=False)
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context(user_id=user.id)
    cache[ctx.id] = {"id": user.id, "type": STATE_UI, "timestamp": time.monotonic()}
    await _fire(hass, "switch.test", "on", context=ctx)

    state = hass.states.get(sid)
    assert state.state == STATE_SERVICE
    assert state.attributes[ATTR_SOURCE_TYPE] == "service"
    assert state.attributes[ATTR_SOURCE_ID] == user.id
    assert state.attributes[ATTR_SOURCE_NAME] == "Node-RED"


async def test_step2_user_id_without_cache(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A user_id with no cache entry classifies as a UI action."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    user = await _make_user(hass, "Alice", with_person=True)

    await _fire(hass, "switch.test", "on", context=Context(user_id=user.id))

    state = hass.states.get(sid)
    assert state.state == STATE_UI
    assert state.attributes[ATTR_SOURCE_TYPE] == "user"
    assert state.attributes[ATTR_SOURCE_ID] == "person.alice"


async def test_step2_user_id_service_account(
    hass: HomeAssistant, make_config_entry, register_target
):
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    user = await _make_user(hass, "AppDaemon", with_person=False)

    await _fire(hass, "switch.test", "on", context=Context(user_id=user.id))

    state = hass.states.get(sid)
    assert state.state == STATE_SERVICE
    assert state.attributes[ATTR_SOURCE_ID] == user.id


async def test_unknown_user_id_uses_placeholder_name(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A user_id that resolves to no HA user is reported as Unknown User."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    # A person tied to a different user must be skipped by the person scan.
    hass.states.async_set("person.bob", "home", {"user_id": "someone-else"})

    await _fire(hass, "switch.test", "on", context=Context(user_id="ghost-user-id"))

    state = hass.states.get(sid)
    assert state.state == STATE_UI
    assert state.attributes[ATTR_SOURCE_NAME] == NAME_UNKNOWN_USER
    assert state.attributes[ATTR_SOURCE_ID] == "ghost-user-id"


async def test_user_cache_expiry_picks_up_person_rename(
    hass: HomeAssistant, make_config_entry, register_target
):
    """An expired user-cache entry re-resolves the person's current name."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    user = await _make_user(hass, "Alice", with_person=True)

    await _fire(hass, "switch.test", "on", context=Context(user_id=user.id))
    assert _attrs(hass, sid)[ATTR_SOURCE_NAME] == "Alice"

    # Rename the person, then age the cache entry past its TTL.
    hass.states.async_set(
        "person.alice", "home", {"user_id": user.id, "friendly_name": "Alicia"}
    )
    hass.data[DOMAIN]["user_cache"][user.id]["timestamp"] -= USER_CACHE_TTL + 1

    await _fire(hass, "switch.test", "off", context=Context(user_id=user.id))
    assert _attrs(hass, sid)[ATTR_SOURCE_NAME] == "Alicia"


async def test_step3_parent_in_cache(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A parent context found in the cache resolves to that source (high)."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    cache = hass.data[DOMAIN]["context_cache"]

    parent = Context()
    cache[parent.id] = {
        "id": "script.bedtime",
        "name": "Bedtime",
        "type": STATE_SCRIPT,
        "timestamp": time.monotonic(),
    }
    child = Context(parent_id=parent.id)
    await _fire(hass, "switch.test", "on", context=child)

    state = hass.states.get(sid)
    assert state.state == STATE_SCRIPT
    assert state.attributes[ATTR_SOURCE_ID] == "script.bedtime"
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_HIGH


async def test_step3_parent_not_in_cache(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A parent context that is missing yields an indirect-automation guess."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)

    child = Context(parent_id="missing-parent-context")
    await _fire(hass, "switch.test", "on", context=child)

    state = hass.states.get(sid)
    assert state.state == STATE_AUTOMATION
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_MEDIUM
    assert state.attributes[ATTR_SOURCE_ID] == ID_INDIRECT_AUTOMATION
    assert state.attributes[ATTR_SOURCE_NAME] == NAME_INDIRECT_AUTOMATION


# --------------------------------------------------------------------------- #
# Bleed handling (ESPHome)
# --------------------------------------------------------------------------- #


async def test_bleed_platform_downgrades_repeat_ui_hit(
    hass: HomeAssistant, make_config_entry, register_target
):
    """On ESPHome, the second hit on a UI context is low confidence (bleed)."""
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="switch.esp", platform="esphome",
    )
    user = await _make_user(hass, "Alice", with_person=True)
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context(user_id=user.id)
    cache[ctx.id] = {"id": user.id, "type": STATE_UI, "timestamp": time.monotonic()}

    # First hit: genuine dashboard action -> high confidence.
    await _fire(hass, "switch.esp", "on", context=ctx)
    assert _attrs(hass, sid)[ATTR_CONFIDENCE] == CONFIDENCE_HIGH

    # Second hit reusing the same context -> bleed suspected -> low.
    await _fire(hass, "switch.esp", "off", context=ctx)
    assert _attrs(hass, sid)[ATTR_CONFIDENCE] == CONFIDENCE_LOW


# --------------------------------------------------------------------------- #
# Command-echo guard (Matter / push integrations)
# --------------------------------------------------------------------------- #


async def test_echo_guard_downgrades_change_soon_after_command():
    """A context-free change within the echo window of a command is low."""
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})
    now = time.monotonic()
    sensor._last_command_time = now - 1.0  # HA commanded this entity 1s ago

    result = await sensor._async_classify(Context(), now)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_LOW


async def test_echo_guard_allows_genuine_press_after_window():
    """A context-free change once the window has passed is a real press (high)."""
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})
    now = time.monotonic()
    sensor._last_command_time = now - (COMMAND_ECHO_WINDOW + 1)

    result = await sensor._async_classify(Context(), now)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_HIGH


async def test_echo_guard_high_when_no_prior_command():
    """With no command ever recorded, a device change is a genuine press."""
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})

    result = await sensor._async_classify(Context(), time.monotonic())

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_HIGH


async def test_echo_after_command_is_low_end_to_end(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A command records the time; a trailing context-free change reads low.

    Exercises the full pipeline: _async_handle_change records the command time
    on the automation classification, and the following context-free change is
    down-weighted by the Step 4 guard - the exact Matter echo pattern.
    """
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.matter", platform="matter", state="off",
    )
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context()
    cache[ctx.id] = {
        "id": "automation.dim",
        "name": "Dim",
        "type": STATE_AUTOMATION,
        "timestamp": time.monotonic(),
    }
    # Automation commands the light on -> classified automation, command time set.
    await _fire(hass, "light.matter", "on", context=ctx)
    assert hass.states.get(sid).state == STATE_AUTOMATION

    # The Matter node reports a context-free change moments later -> probable echo.
    await _fire(hass, "light.matter", "off", context=Context())
    state = hass.states.get(sid)
    assert state.state == STATE_DEVICE
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_LOW


async def test_device_echo_does_not_refresh_command_window(
    hass: HomeAssistant, make_config_entry, register_target
):
    """Only HA commands arm _last_command_time; echoes never touch it.

    A Matter transition streams several context-free echoes, and each one does
    extend the guard (via the separate _last_echo_time chain) so the whole
    train is covered. What must not happen is an echo moving the *command*
    timestamp: that is the anchor for COMMAND_ECHO_MAX_WINDOW, and if a chain
    could push it forward the ceiling would slide and the window could stay
    open indefinitely. Keeping the two clocks separate is what bounds it.
    """
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.matter", platform="matter", state="off",
    )
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context()
    cache[ctx.id] = {
        "id": "automation.dim",
        "name": "Dim",
        "type": STATE_AUTOMATION,
        "timestamp": time.monotonic(),
    }
    await _fire(hass, "light.matter", "on", context=ctx)

    sensor = next(
        p.entities[sid]
        for p in entity_platform.async_get_platforms(hass, DOMAIN)
        if sid in p.entities
    )
    armed_at = sensor._last_command_time
    assert armed_at > 0.0  # the automation command armed the guard

    # A trailing echo classifies device/low and must not re-arm the window.
    await _fire(hass, "light.matter", "off", context=Context())
    assert _attrs(hass, sid)[ATTR_CONFIDENCE] == CONFIDENCE_LOW
    assert sensor._last_command_time == armed_at


async def test_echo_chain_bridges_consecutive_reports():
    """A train keeps the guard open past the command's own window.

    Reports arrive ~2s apart and can run well beyond COMMAND_ECHO_WINDOW from
    the command; each echo extends the chain so the whole train reads low.
    """
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})
    now = time.monotonic()
    # Command is older than the gap window, but a report landed 2s ago.
    sensor._last_command_time = now - (COMMAND_ECHO_WINDOW + 4)
    sensor._last_echo_time = now - 2.0

    result = await sensor._async_classify(Context(), now)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_LOW
    assert result.is_echo is True


async def test_echo_chain_cannot_outlive_max_window():
    """The ceiling wins even while a chain is still being extended."""
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})
    now = time.monotonic()
    sensor._last_command_time = now - (COMMAND_ECHO_MAX_WINDOW + 1)
    sensor._last_echo_time = now - 2.0  # chain still live

    result = await sensor._async_classify(Context(), now)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_HIGH
    assert result.is_echo is False


async def test_echo_chain_closes_once_reports_stop():
    """Once the train goes quiet the guard re-arms, well inside the ceiling."""
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})
    now = time.monotonic()
    sensor._last_command_time = now - 20.0  # still under the 30s ceiling
    sensor._last_echo_time = now - (COMMAND_ECHO_WINDOW + 1)

    result = await sensor._async_classify(Context(), now)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_HIGH


# --------------------------------------------------------------------------- #
# Command-value matching
# --------------------------------------------------------------------------- #


def _sensor_with_command(**command):
    """A sensor whose target was just commanded to the given values."""
    cache = {}
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, cache)
    cache["light.matter"] = {
        "state": "on",
        "brightness": None,
        "color_temp_kelvin": None,
        "timestamp": time.monotonic(),
        **command,
    }
    return sensor


def _light_state(brightness=None, state="on", color_temp_kelvin=None):
    attrs = {}
    if brightness is not None:
        attrs["brightness"] = brightness
    if color_temp_kelvin is not None:
        attrs["color_temp_kelvin"] = color_temp_kelvin
    return State("light.matter", state, attrs)


def test_command_match_landed_on_commanded_value():
    """A report sitting on the commanded value is that command's echo."""
    sensor = _sensor_with_command(brightness=200)
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(brightness=195), _light_state(brightness=10)
    )
    assert verdict is True


def test_command_match_accepts_a_converging_fade_step():
    """A mid-fade step is far from the target but heading for it -> echo.

    The step below is 120 away from the commanded 200, well outside tolerance;
    it only counts as an echo because it is closer than the previous report.
    """
    sensor = _sensor_with_command(brightness=200)
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(brightness=80), _light_state(brightness=10)
    )
    assert verdict is True


def test_command_match_rejects_a_change_moving_away():
    """A report heading away from the commanded value is somebody else."""
    sensor = _sensor_with_command(brightness=200)
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(brightness=40), _light_state(brightness=90)
    )
    assert verdict is False


def test_command_match_rejects_wrong_on_off_state():
    """Commanded on, reported off - not this command arriving."""
    sensor = _sensor_with_command(brightness=200)
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(state="off"), _light_state(brightness=200)
    )
    assert verdict is False


def test_command_match_ignores_a_stale_command():
    """Past the echo ceiling the recorded command is no longer relevant."""
    sensor = _sensor_with_command(brightness=200)
    sensor._command_cache["light.matter"]["timestamp"] -= COMMAND_ECHO_MAX_WINDOW + 1
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(brightness=200), _light_state(brightness=10)
    )
    assert verdict is None


def test_command_match_none_without_a_recorded_command():
    """With nothing recorded the caller falls back to the time guard."""
    sensor = WhodunnitSensor("light.matter", {"name": "Dev"}, {}, {}, {})
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(brightness=200), None
    )
    assert verdict is None


async def test_plain_turn_on_does_not_swallow_a_later_press():
    """A record of nothing but "we asked for on" is too thin to rule on.

    `light.turn_on` with neither brightness nor colour is the most common light
    call there is, and every later report of a lit light satisfies it - a manual
    dim included. Judging that a match would swallow presses for the whole
    ceiling, so the value comparison must abstain and let the guard answer.
    """
    sensor = _sensor_with_command()  # state on, nothing numeric recorded
    now = time.monotonic()
    sensor._last_command_time = now - 20.0  # any train is long over

    verdict = sensor._command_echo_verdict(
        now, _light_state(brightness=30), _light_state(brightness=200)
    )
    assert verdict is None

    result = await sensor._async_classify(Context(), now, verdict)
    assert result.confidence == CONFIDENCE_HIGH


async def test_toggle_evicts_the_stale_command_record(
    hass: HomeAssistant, make_config_entry, register_target
):
    """An unhandled light service must not leave a record asserting the opposite.

    `light.toggle` turns the light off while the cache still says "we asked for
    on", so the toggle's own echo would be ruled a manual press - the false
    signal the guard exists to avoid. Evicting leaves the guard to decide.
    """
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.matter", platform="matter",
        state="on", attributes={"brightness": 200},
    )
    command_cache = hass.data[DOMAIN]["command_cache"]

    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "light",
            "service": "turn_on",
            "service_data": {"entity_id": "light.matter", "brightness": 250},
        },
    )
    await hass.async_block_till_done()
    assert "light.matter" in command_cache

    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "light",
            "service": "toggle",
            "service_data": {"entity_id": "light.matter"},
        },
    )
    await hass.async_block_till_done()
    assert "light.matter" not in command_cache

    # With the record gone, the toggle's echo cannot be ruled a person.
    sensor = next(
        p.entities[sid]
        for p in entity_platform.async_get_platforms(hass, DOMAIN)
        if sid in p.entities
    )
    verdict = sensor._command_echo_verdict(
        time.monotonic(), _light_state(state="off"), _light_state(brightness=200)
    )
    assert verdict is None


async def test_command_match_overrides_the_time_guard_mid_train():
    """A press during a live echo train still reads high.

    This is the case timing alone cannot reach: the chain is active, so the
    windows would say echo, but the value says somebody moved the light
    somewhere the command never asked for.
    """
    sensor = _sensor_with_command(brightness=200)
    now = time.monotonic()
    sensor._last_command_time = now - 1.0
    sensor._last_echo_time = now - 2.0  # a train is running

    result = await sensor._async_classify(Context(), now, echo_verdict=False)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_HIGH
    assert result.is_echo is False


async def test_command_match_marks_echo_outside_the_time_windows():
    """Conversely, a confirmed echo reads low even past the windows."""
    sensor = _sensor_with_command(brightness=200)
    now = time.monotonic()
    # No command recorded on the timing clocks at all.
    result = await sensor._async_classify(Context(), now, echo_verdict=True)

    assert result.state == STATE_DEVICE
    assert result.confidence == CONFIDENCE_LOW
    assert result.is_echo is True


async def test_light_command_is_recorded_and_matched_end_to_end(
    hass: HomeAssistant, make_config_entry, register_target
):
    """The real listener records the command; the sensor matches a report to it.

    Covers the whole path: EVENT_CALL_SERVICE -> command_cache (with
    brightness_pct converted to the 0-255 scale) -> a context-free report that
    lands on the commanded value being classified as that command's echo.
    """
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.matter", platform="matter",
        state="on", attributes={"brightness": 10},
    )

    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "light",
            "service": "turn_on",
            "service_data": {"entity_id": "light.matter", "brightness_pct": 100},
        },
    )
    await hass.async_block_till_done()

    recorded = hass.data[DOMAIN]["command_cache"]["light.matter"]
    assert recorded["brightness"] == 255  # 100% converted to the reported scale
    assert recorded["state"] == "on"

    # The Matter node reports the achieved level with no context of its own.
    await _fire(
        hass, "light.matter", "on", context=Context(), attributes={"brightness": 254}
    )

    state = hass.states.get(sid)
    assert state.state == STATE_DEVICE
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_LOW


async def _command_then_report(
    hass, make_config_entry, register_target, *, was, commanded, reported
):
    """Register a light at `was`, command it to `commanded`, report `reported`.

    One report per test: two attribute-only changes in a row would hit the 2s
    ATTRIBUTE_CHANGE_THROTTLE and the second would never be classified.
    """
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.matter", platform="matter",
        state="on", attributes={"brightness": was},
    )
    hass.bus.async_fire(
        EVENT_CALL_SERVICE,
        {
            "domain": "light",
            "service": "turn_on",
            "service_data": {"entity_id": "light.matter", "brightness": commanded},
        },
    )
    await hass.async_block_till_done()
    await _fire(
        hass, "light.matter", "on",
        context=Context(), attributes={"brightness": reported},
    )
    return sid


async def test_fade_step_towards_the_commanded_value_is_an_echo(
    hass: HomeAssistant, make_config_entry, register_target
):
    """120 is nowhere near the commanded 250, but it is closer than 10 was."""
    sid = await _command_then_report(
        hass, make_config_entry, register_target,
        was=10, commanded=250, reported=120,
    )
    assert _attrs(hass, sid)[ATTR_CONFIDENCE] == CONFIDENCE_LOW


async def test_press_during_a_fade_is_not_swallowed(
    hass: HomeAssistant, make_config_entry, register_target
):
    """Somebody dimming a light mid-fade reads high, not low.

    The regression this whole mechanism exists for: the time guard alone would
    call anything arriving while the train is running an echo.
    """
    sid = await _command_then_report(
        hass, make_config_entry, register_target,
        was=90, commanded=250, reported=30,
    )
    state = hass.states.get(sid)
    assert state.state == STATE_DEVICE
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_HIGH


async def test_new_command_resets_the_echo_chain(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A fresh command starts a fresh train rather than inheriting the old one."""
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.matter", platform="matter", state="off",
    )
    cache = hass.data[DOMAIN]["context_cache"]

    def _command(ctx):
        cache[ctx.id] = {
            "id": "automation.dim",
            "name": "Dim",
            "type": STATE_AUTOMATION,
            "timestamp": time.monotonic(),
        }

    ctx = Context()
    _command(ctx)
    await _fire(hass, "light.matter", "on", context=ctx)
    await _fire(hass, "light.matter", "off", context=Context())  # echo

    sensor = next(
        p.entities[sid]
        for p in entity_platform.async_get_platforms(hass, DOMAIN)
        if sid in p.entities
    )
    assert sensor._last_echo_time > 0.0  # the chain is live

    ctx2 = Context()
    _command(ctx2)
    await _fire(hass, "light.matter", "on", context=ctx2)

    assert hass.states.get(sid).state == STATE_AUTOMATION
    assert sensor._last_echo_time == 0.0  # chain cleared by the new command


# --------------------------------------------------------------------------- #
# Change filtering
# --------------------------------------------------------------------------- #


async def test_no_classification_when_nothing_meaningful_changed(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A non-watched attribute change with an unchanged state is ignored."""
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target, state="on"
    )
    events = async_capture_events(hass, EVENT_TRIGGER_DETECTED)

    # State stays "on"; only an unwatched attribute changes.
    await _fire(hass, "switch.test", "on", attributes={"foo": "bar"})

    assert hass.states.get(sid).state == STATE_MONITORING
    assert len(events) == 0


async def test_watched_attribute_change_triggers_classification(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A watched attribute change (light brightness) is classified."""
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.test", state="on", attributes={"brightness": 100},
    )
    await _fire(
        hass, "light.test", "on", context=Context(), attributes={"brightness": 200}
    )
    assert hass.states.get(sid).state == STATE_DEVICE


async def test_repeat_attribute_change_is_throttled(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A second watched-attr change within 2s (same state) is throttled."""
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="light.test", state="on", attributes={"brightness": 100},
    )
    events = async_capture_events(hass, EVENT_TRIGGER_DETECTED)

    await _fire(
        hass, "light.test", "on", context=Context(), attributes={"brightness": 200}
    )
    await _fire(
        hass, "light.test", "on", context=Context(), attributes={"brightness": 250}
    )
    assert len(events) == 1  # second change suppressed by the 2s attr throttle


async def test_missing_old_state_is_ignored(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A state change with no old_state (entity (re)appearing) is ignored."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    events = async_capture_events(hass, EVENT_TRIGGER_DETECTED)

    hass.states.async_remove("switch.test")
    await hass.async_block_till_done()
    await _fire(hass, "switch.test", "on", context=Context())  # old_state is None

    assert len(events) == 0
    assert hass.states.get(sid).state == STATE_MONITORING


async def test_initial_name_uses_clean_target_name(
    hass: HomeAssistant, make_config_entry, register_target
):
    """At setup the sensor name reflects the target's friendly name, not the slug.

    Same cached-name root cause as the rename case: HA caches Entity.name during
    entity-id generation (using the __init__ slug placeholder) before
    async_added_to_hass sets the clean name, so the cache must be invalidated.
    """
    _, sid = await _setup_sensor(
        hass, make_config_entry, register_target,
        target="switch.garage_main",
        attributes={"friendly_name": "Garage Door"},
    )
    friendly = hass.states.get(sid).attributes["friendly_name"]
    assert "Garage Door" in friendly
    assert "Garage Main" not in friendly  # the raw slug must not leak through


async def test_registry_non_name_change_is_ignored(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A registry update that does not change the name leaves the title alone."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    before = hass.states.get(sid).attributes["friendly_name"]

    er.async_get(hass).async_update_entity("switch.test", icon="mdi:flash")
    await hass.async_block_till_done()

    assert hass.states.get(sid).attributes["friendly_name"] == before


async def test_classification_error_is_caught(
    hass: HomeAssistant, make_config_entry, register_target, monkeypatch, caplog
):
    """An unexpected error during classification is logged, not raised."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)

    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    # Force _get_person_cached -> hass.auth.async_get_user to blow up.
    monkeypatch.setattr(hass.auth, "async_get_user", _boom)

    await _fire(hass, "switch.test", "on", context=Context(user_id="user-x"))

    # The handler swallows the error: no crash, state unchanged, error logged.
    assert hass.states.get(sid).state == STATE_MONITORING
    assert "error classifying switch.test" in caplog.text


async def test_registry_rename_updates_sensor_name(
    hass: HomeAssistant, make_config_entry, register_target
):
    """Renaming the target in the registry refreshes the sensor's name.

    Regression guard for the cached-name bug: Entity.name is a @cached_property,
    so _refresh_name() must invalidate it for the new placeholder to take effect.
    """
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)

    er.async_get(hass).async_update_entity("switch.test", name="Renamed Target")
    await hass.async_block_till_done()

    assert "Renamed Target" in hass.states.get(sid).attributes["friendly_name"]


async def test_duplicate_context_is_skipped(
    hass: HomeAssistant, make_config_entry, register_target
):
    """The same context on a non-bleed platform is classified only once."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    events = async_capture_events(hass, EVENT_TRIGGER_DETECTED)

    ctx = Context()
    await _fire(hass, "switch.test", "on", context=ctx)
    await _fire(hass, "switch.test", "off", context=ctx)

    assert len(events) == 1


# --------------------------------------------------------------------------- #
# Event firing, history, attributes
# --------------------------------------------------------------------------- #


async def test_trigger_event_payload(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A classification fires whodunnit_trigger_detected with a full payload."""
    await _setup_sensor(hass, make_config_entry, register_target)
    events = async_capture_events(hass, EVENT_TRIGGER_DETECTED)

    await _fire(hass, "switch.test", "on", context=Context())

    assert len(events) == 1
    data = events[0].data
    assert data["entity_id"] == "switch.test"
    assert data["state"] == STATE_DEVICE
    assert data["source_type"] == "device"
    assert data["confidence"] == CONFIDENCE_HIGH
    assert "event_time" in data


async def test_history_log_accumulates(
    hass: HomeAssistant, make_config_entry, register_target
):
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)

    await _fire(hass, "switch.test", "on", context=Context())
    await _fire(hass, "switch.test", "off", context=Context())

    log = _attrs(hass, sid)[ATTR_HISTORY_LOG]
    assert len(log) == 2
    # Newest entry is prepended.
    assert all(ATTR_SOURCE_TYPE in entry for entry in log)
    assert all(ATTR_CONTEXT_ID in entry for entry in log)


async def test_sensor_unavailable_when_target_not_registered(
    hass: HomeAssistant, make_config_entry
):
    """Without a registry entry for the target, the sensor is unavailable."""
    hass.states.async_set("switch.bare", "off")  # state only, not registered
    entry = make_config_entry("switch.bare")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    sensor_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "switch.bare_whodunnit"
    )
    assert hass.states.get(sensor_id).state == "unavailable"


# --------------------------------------------------------------------------- #
# State restoration
# --------------------------------------------------------------------------- #


async def _setup_with_restore(hass, make_config_entry, register_target, restored):
    """Pre-register the sensor (for a deterministic id) and seed restore cache."""
    register_target("switch.test")
    entry = make_config_entry("switch.test")
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "switch.test_whodunnit",
        suggested_object_id="restored", config_entry=entry,
    )
    mock_restore_cache(hass, [restored])
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return "sensor.restored"


async def test_restores_previous_state(
    hass: HomeAssistant, make_config_entry, register_target
):
    sid = await _setup_with_restore(
        hass, make_config_entry, register_target,
        State(
            "sensor.restored", STATE_AUTOMATION,
            {
                ATTR_SOURCE_TYPE: "automation",
                ATTR_SOURCE_ID: "automation.x",
                ATTR_SOURCE_NAME: "Auto X",
                ATTR_CONFIDENCE: CONFIDENCE_MEDIUM,
                ATTR_HISTORY_LOG: [{ATTR_EVENT_TIME: "t", ATTR_SOURCE_TYPE: "x"}],
            },
        ),
    )
    state = hass.states.get(sid)
    assert state.state == STATE_AUTOMATION
    assert state.attributes[ATTR_SOURCE_ID] == "automation.x"
    assert state.attributes[ATTR_CONFIDENCE] == CONFIDENCE_MEDIUM
    assert len(state.attributes[ATTR_HISTORY_LOG]) == 1


async def test_ignores_invalid_restored_state(
    hass: HomeAssistant, make_config_entry, register_target
):
    sid = await _setup_with_restore(
        hass, make_config_entry, register_target,
        State("sensor.restored", "bogus_state", {}),
    )
    assert hass.states.get(sid).state == STATE_MONITORING


async def test_ignores_unavailable_restored_state(
    hass: HomeAssistant, make_config_entry, register_target
):
    sid = await _setup_with_restore(
        hass, make_config_entry, register_target,
        State("sensor.restored", "unavailable", {}),
    )
    assert hass.states.get(sid).state == STATE_MONITORING


async def test_ignores_corrupt_restored_history_log(
    hass: HomeAssistant, make_config_entry, register_target
):
    """A restored history_log that is not a list is discarded."""
    sid = await _setup_with_restore(
        hass, make_config_entry, register_target,
        State("sensor.restored", STATE_AUTOMATION, {ATTR_HISTORY_LOG: "corrupt"}),
    )
    state = hass.states.get(sid)
    assert state.state == STATE_AUTOMATION
    assert state.attributes[ATTR_HISTORY_LOG] == []


async def test_cache_debug_handles_evicted_matched_entry(
    hass: HomeAssistant, make_config_entry, register_target
):
    """cache_debug degrades gracefully when the matched entry was evicted."""
    _, sid = await _setup_sensor(hass, make_config_entry, register_target)
    cache = hass.data[DOMAIN]["context_cache"]

    ctx = Context()
    cache[ctx.id] = {
        "id": "automation.morning",
        "name": "Morning",
        "type": STATE_AUTOMATION,
        "timestamp": time.monotonic(),
    }
    await _fire(hass, "switch.test", "on", context=ctx)
    assert _attrs(hass, sid)[ATTR_CACHE_DEBUG]["matched_entry"]["type"] == (
        STATE_AUTOMATION
    )

    # Evict the matched entry, then force a state write via a target rename.
    del cache[ctx.id]
    er.async_get(hass).async_update_entity("switch.test", name="Force Write")
    await hass.async_block_till_done()

    debug = _attrs(hass, sid)[ATTR_CACHE_DEBUG]
    assert debug["matched_entry"] is None
    assert debug["last_classification_ago"] is not None


# --------------------------------------------------------------------------- #
# Pure helper methods
# --------------------------------------------------------------------------- #


def test_build_cache_debug_before_any_classification():
    sensor = WhodunnitSensor("switch.test", {"name": "Dev"}, {}, {}, {})
    debug = sensor._build_cache_debug()
    assert debug == {
        "last_classification_ago": None,
        "total_cache_entries": 0,
        "matched_entry": None,
    }


def test_clean_target_name_strips_device_prefix(hass: HomeAssistant):
    sensor = WhodunnitSensor("switch.lamp", {"name": "Living Room"}, {}, {}, {})
    sensor.hass = hass
    hass.states.async_set(
        "switch.lamp", "on", {"friendly_name": "Living Room Lamp"}
    )
    assert sensor._get_clean_target_name() == "Lamp"


def test_clean_target_name_prefers_registry_name(hass: HomeAssistant):
    sensor = WhodunnitSensor("switch.lamp", {"name": "Living Room"}, {}, {}, {})
    sensor.hass = hass
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "switch", "test", "lamp_unique", suggested_object_id="lamp"
    )
    ent_reg.async_update_entity("switch.lamp", name="Living Room Lamp")
    # The user-set registry name wins over state friendly_name.
    assert sensor._get_clean_target_name() == "Lamp"


def test_clean_target_name_without_prefix(hass: HomeAssistant):
    sensor = WhodunnitSensor("switch.lamp", {"name": "Garage"}, {}, {}, {})
    sensor.hass = hass
    hass.states.async_set(
        "switch.lamp", "on", {"friendly_name": "Living Room Lamp"}
    )
    assert sensor._get_clean_target_name() == "Living Room Lamp"


def test_clean_target_name_equal_to_device_falls_back(hass: HomeAssistant):
    sensor = WhodunnitSensor("switch.lamp", {"name": "Lamp"}, {}, {}, {})
    sensor.hass = hass
    hass.states.async_set("switch.lamp", "on", {"friendly_name": "Lamp"})
    assert sensor._get_clean_target_name() == "Lamp"


def test_icon_reflects_state():
    sensor = WhodunnitSensor("switch.test", {"name": "Dev"}, {}, {}, {})
    sensor._state = STATE_DEVICE
    assert sensor.icon == "mdi:gesture-tap"
    sensor._state = "something_unmapped"
    assert sensor.icon == "mdi:help-circle-outline"
