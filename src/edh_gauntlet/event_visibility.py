"""Canonical visibility policy for game-event evidence projections.

The rules ledger keeps an omniscient event internally. Post-game strategy evidence
must never copy that record wholesale. Every known event type is classified here;
unknown events are ``unclassified`` and their card/detail payload is redacted by
the learning exporter until a deliberate policy is added.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


ACTOR_ONLY_EVENT_TYPES = frozenset({
    'scheduler_control', 'scheduler_wake', 'scheduler_suppressed',
    "autopass_priority",
    "autopass_stack_end",
    "autopass_stack_start",
    "forced_choice",
    "llm_decision",
    "look_top",
    "miracle_available",
    "miracle_expired",
    "mana_pool_empty",
    "priority_object_pass_auto",
    "priority_object_pass_deadline_change",
    "priority_object_pass_end",
    "priority_object_pass_reschedule",
    "priority_object_pass_start",
    "priority_object_pass_tick",
    "priority_seat_snooze_auto",
    "priority_seat_snooze_end",
    "priority_seat_snooze_start",
    "priority_specialized_pass",
    "timing_affordance",
    "unsupported_audit",
})


ACTOR_WITH_PUBLIC_STUB_EVENT_TYPES = frozenset({
    "draw",
    "mulligan_keep",
    "put_on_top",
    "scry",
    "surveil",
    "surveil_keep",
    "top_reorder",
    "tutor",
    "tutor_top",
})


PUBLIC_EVENT_TYPES = frozenset({
    'planner_phase_boundary', 'planner_turn_boundary', 'planner_life_change',
    "ability_countered", "ability_fizzle", "ability_resolve", "activated_ability",
    "attach", "aura_disable", "aura_illegal_attach", "aura_restore", "aura_return_failed",
    "bounce", "cascade_bottom", "cascade_decline", "cascade_hit", "cast", "cleanup",
    "battle_protector", "cast_transformed", "combat_buff", "combat_damage",
    "combat_damage_battle", "combat_damage_creature",
    "combat_damage_planeswalker", "combo_adjudication_approved",
    "combo_adjudication_operation", "combo_adjudication_rejected", "combo_attempt",
    "combo_consent_declined", "combo_interaction", "combo_loop_proposed", "combo_router",
    "commander_damage", "commander_zone", "control_change", "control_exchange",
    "convoke_payment", "copy_ceases", "copy_countered", "copy_effect", "copy_targets",
    "counter_abilities", "counter_counter", "counter_removed", "countered",
    "countered_destination", "counters", "counters_replaced", "counterspell", "damage",
    "damage_prevented", "dark_depths", "deck_loss", "delayed_trigger",
    "delayed_trigger_resolved", "desert_warfare", "destroy_prevented", "direct_damage",
    "discard", "eliminated", "energy", "equip", "etb", "everything_counter", "exile",
    "explore_grave", "explore_keep", "explore_land", "explore_reveal", "extra_land",
    "fading", "fight_damage", "food", "game_start", "gifts_split", "global_bounce",
    "global_effect", "goad_attack_requirement", "graveyard_land_play", "helm_copy",
    "horizon_adjudication", "horizon_stop", "land_animation",
    "land_copy", "land_copy_effect", "land_play", "leaves_game", "life_gain",
    "life_loss", "loyalty_damage", "ltb", "mana_ability", "mana_payment", "mass_damage",
    "maze_end_activate", "messageboard_message", "mill", "miracle_reveal", "monstrous", "ozolith_decline",
    "ozolith_move", "persist", "phase_in", "phase_out", "pilot_game_stop",
    "planeswalker_activation", "pregame_leyline", "priority_closed", "proliferate",
    "propaganda_tax", "protection", "reactive_protection", "regenerate",
    "replacement_effect", "resolve", "return_to_hand", "reveal", "reveal_hand",
    "reveal_to_hand", "riot", "room_unlock", "room_unlock_resolve", "saga_chapter",
    "shuffle", "spell_fizzle", "spell_to_graveyard", "stack_add", "surveil_bin",
    "token_ceases", "token_etb", "transform", "transmute", "treasure",
    "trigger_countered", "trigger_resolve", "trigger_stack_add", "triggers_deferred",
    "uncounterable", "untap", "untap_effect", "winner", "zone_move",
})


EVENT_VISIBILITY_POLICY = {
    **{name: "public" for name in PUBLIC_EVENT_TYPES},
    **{name: "actor" for name in ACTOR_ONLY_EVENT_TYPES},
    **{name: "actor_public" for name in ACTOR_WITH_PUBLIC_STUB_EVENT_TYPES},
}


def event_visibility(event_type: str, override: Optional[str] = None) -> str:
    if override is not None:
        if override not in {"public", "actor", "actor_public"}:
            raise ValueError(f"unsupported event visibility {override!r}")
        return override
    return EVENT_VISIBILITY_POLICY.get(str(event_type), "unclassified")


def public_event_stub(
    event_type: str,
    actor: Optional[str],
    extra: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """Return fields safe for non-actor packets for a partly private event."""

    who = actor or "A player"
    if event_type == "mulligan_keep":
        mulligans = int(extra.get("mulligans", 0))
        hand_size = int(extra.get("hand_size", 7))
        return {
            "detail": f"{who} kept {hand_size} cards after {mulligans} mulligan(s)",
            "mulligans": mulligans,
            "hand_size": hand_size,
        }
    if event_type == "draw":
        view: dict[str, Any] = {"detail": f"{who} drew a card"}
        if "draw_number" in extra:
            view["draw_number"] = extra["draw_number"]
        return view
    details = {
        "scry": f"{who} scried without revealing the private disposition",
        "surveil": f"{who} surveilled; cards moved to public zones are logged separately",
        "surveil_keep": f"{who} kept one or more surveilled cards in the library",
        "put_on_top": f"{who} put a card on top of a library without revealing its identity",
        "tutor": f"{who} searched a library without revealing the selected identity",
        "tutor_top": f"{who} searched and put an unrevealed card on top of a library",
        "top_reorder": f"{who} privately reordered cards on top of a library",
    }
    detail = details.get(event_type)
    if detail is None:
        return None
    view = {"detail": detail}
    destination = extra.get("destination")
    if destination:
        view["destination"] = destination
    return view


__all__ = [
    "ACTOR_ONLY_EVENT_TYPES",
    "ACTOR_WITH_PUBLIC_STUB_EVENT_TYPES",
    "EVENT_VISIBILITY_POLICY",
    "PUBLIC_EVENT_TYPES",
    "event_visibility",
    "public_event_stub",
]
