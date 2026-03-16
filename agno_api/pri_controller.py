from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_EXPLICIT_PRI_PREFIXES = ("pri", "priscila")

_EXPLICIT_WRITE_PREFIXES = (
    "lanca",
    "lança",
    "registre",
    "registra",
    "anota",
    "salva",
    "cadastre",
    "cadastra",
    "corrige",
    "corrija",
    "muda",
    "altera",
    "reclassifica",
    "categoriza",
    "apaga",
    "deleta",
    "remove",
    "exclui",
    "fecha a fatura",
    "fechar fatura",
    "fecha fatura",
    "paga a conta",
    "pagar conta",
    "marca como pago",
    "marcar como pago",
)

_WRITE_QUERY_ACTIONS = {"delete_last"}
_WRITE_AGENDA_ACTIONS = {"create", "complete", "delete", "pause", "resume", "edit", "snooze"}
_LEGACY_WRITE_ACTIONS = {
    "save_transaction",
    "update_transaction",
    "update_merchant_category",
    "delete_last",
    "delete_transactions",
    "register_bill",
    "pay_bill",
    "close_bill",
    "set_card_bill",
    "set_future_bill",
    "register_recurring",
    "register_card",
    "create_goal",
    "add_to_goal",
    "set_salary_day",
    "set_reminder_days",
    "set_category_budget",
    "remove_category_budget",
}


@dataclass(frozen=True)
class PriMessageContext:
    raw_body: str
    effective_body: str
    explicit_pri_message: bool
    explicit_write_command: bool
    in_mentor_session: bool
    in_pri_context: bool
    skip_onboarding: bool
    skip_pending_action_check: bool


def message_addresses_pri(text: str) -> bool:
    body = (text or "").strip().lower()
    return bool(body.startswith(_EXPLICIT_PRI_PREFIXES))


def strip_pri_prefix(text: str) -> str:
    body = (text or "").strip()
    lowered = body.lower()
    for prefix in _EXPLICIT_PRI_PREFIXES:
        if lowered.startswith(prefix):
            trimmed = body[len(prefix):].lstrip(" ,:-")
            return trimmed or body
    return body


def is_explicit_write_command(text: str) -> bool:
    body = strip_pri_prefix(text).strip().lower()
    if not body:
        return False
    return any(body.startswith(prefix) for prefix in _EXPLICIT_WRITE_PREFIXES)


def is_write_intent_route(route: dict[str, Any] | None) -> bool:
    data = route if isinstance(route, dict) else {}
    intent = str(data.get("intent") or "").strip().lower()
    action = str(data.get("action") or "").strip().lower()

    if intent in _LEGACY_WRITE_ACTIONS or action in _LEGACY_WRITE_ACTIONS:
        return True

    if intent == "transaction":
        return True
    if intent == "agenda" and action in _WRITE_AGENDA_ACTIONS:
        return True
    if intent == "query" and action in _WRITE_QUERY_ACTIONS:
        return True
    return False


def should_skip_pending_action_check(*, explicit_pri_message: bool, in_mentor_session: bool) -> bool:
    return explicit_pri_message or in_mentor_session


def build_pri_message_context(text: str, *, in_mentor_session: bool = False) -> PriMessageContext:
    raw_body = (text or "").strip()
    explicit_pri_message = message_addresses_pri(raw_body)
    effective_body = strip_pri_prefix(raw_body) if explicit_pri_message else raw_body
    explicit_write_command = is_explicit_write_command(raw_body)
    in_pri_context = explicit_pri_message or in_mentor_session
    skip_onboarding = explicit_pri_message
    skip_pending = should_skip_pending_action_check(
        explicit_pri_message=explicit_pri_message,
        in_mentor_session=in_mentor_session,
    )
    return PriMessageContext(
        raw_body=raw_body,
        effective_body=effective_body,
        explicit_pri_message=explicit_pri_message,
        explicit_write_command=explicit_write_command,
        in_mentor_session=in_mentor_session,
        in_pri_context=in_pri_context,
        skip_onboarding=skip_onboarding,
        skip_pending_action_check=skip_pending,
    )


def should_force_pri_readonly(
    *,
    explicit_pri_message: bool,
    in_mentor_session: bool,
    route: dict[str, Any] | None,
    explicit_write_command: bool,
    looks_like_followup_answer: bool,
) -> bool:
    if explicit_pri_message and not explicit_write_command:
        return True
    if not in_mentor_session:
        return False
    if not explicit_write_command:
        return True
    if looks_like_followup_answer:
        return True
    if is_write_intent_route(route) and not explicit_write_command:
        return True
    return False


def resolve_pri_route(
    *,
    route: dict[str, Any] | None,
    context: PriMessageContext,
    looks_like_followup_answer: bool,
) -> dict[str, Any]:
    route_data = route if isinstance(route, dict) else {}
    if should_force_pri_readonly(
        explicit_pri_message=context.explicit_pri_message,
        in_mentor_session=context.in_mentor_session,
        route=route_data,
        explicit_write_command=context.explicit_write_command,
        looks_like_followup_answer=looks_like_followup_answer,
    ):
        return {"intent": "mentor", "action": "", "params": {}}
    return route_data
