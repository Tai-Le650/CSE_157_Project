from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateInputs:
    armed: bool
    estop_latched: bool
    generation_matches: bool
    session_alive: bool
    sensor_healthy: bool
    allowlisted: bool
    is_idle_label: bool
    cooldown_ok: bool
    repeat: bool
    activation_ok: bool
    workspace_matches: bool


def gate_decision(inputs: GateInputs) -> tuple[bool, str]:
    if inputs.estop_latched:
        return False, "emergency_stop_latched"
    if not inputs.armed:
        return False, "not_armed"
    if not inputs.generation_matches:
        return False, "stale_request"
    if not inputs.workspace_matches:
        return False, "workspace_changed"
    if not inputs.session_alive:
        return False, "control_session_lost"
    if not inputs.sensor_healthy:
        return False, "sensor_unhealthy"
    if not inputs.allowlisted:
        return False, "action_not_allowlisted"
    if inputs.is_idle_label:
        return False, "idle_never_acts"
    if inputs.repeat:
        return False, "repeat_detection"
    if not inputs.cooldown_ok:
        return False, "cooldown"
    if not inputs.activation_ok:
        return False, "sound_activation_inactive"
    return True, "ok"
