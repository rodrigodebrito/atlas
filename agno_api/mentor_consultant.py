from __future__ import annotations

from typing import Any


CONSULTANT_STAGES = {
    "diagnosis",
    "diagnosis_clarification",
    "income_clarification",
    "debt_mapping",
    "reserve_check",
    "action_plan",
    "follow_up",
}

STAGE_FLOW_ORDER = {
    "diagnosis": 0,
    "diagnosis_clarification": 1,
    "income_clarification": 2,
    "debt_mapping": 3,
    "reserve_check": 4,
    "action_plan": 5,
    "follow_up": 6,
}


def normalize_consultant_stage(stage: str | None) -> str:
    value = (stage or "").strip().lower()
    if value in CONSULTANT_STAGES:
        return value
    return "diagnosis"


def normalize_case_summary(summary: Any) -> dict[str, Any]:
    data = summary if isinstance(summary, dict) else {}
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    clean_notes = [str(note).strip()[:160] for note in notes if str(note).strip()]
    return {
        "income_extra_type": str(data.get("income_extra_type") or "").strip().lower(),
        "income_extra_origin": str(data.get("income_extra_origin") or "").strip().lower(),
        "has_emergency_reserve": _normalize_binary(data.get("has_emergency_reserve")),
        "debt_outside_cards": _normalize_binary(data.get("debt_outside_cards")),
        "card_payment_behavior": str(data.get("card_payment_behavior") or "").strip().lower(),
        "main_issue_hypothesis": str(data.get("main_issue_hypothesis") or "").strip().lower(),
        "last_user_signal": str(data.get("last_user_signal") or "").strip()[:240],
        "notes": clean_notes[-5:],
    }


def merge_case_summary(
    summary: dict[str, Any] | None,
    user_message: str,
    question_key: str = "",
    expected_answer_type: str = "",
) -> dict[str, Any]:
    merged = normalize_case_summary(summary)
    text = (user_message or "").strip().lower()
    if not text:
        return merged

    merged["last_user_signal"] = (user_message or "").strip()[:240]
    normalized_key = (question_key or "").strip().lower()
    normalized_expected = (expected_answer_type or "").strip().lower()

    income_origin = _extract_income_origin(text)
    if income_origin:
        merged["income_extra_origin"] = income_origin

    income_type = _extract_income_type(text)
    if income_type:
        merged["income_extra_type"] = income_type

    if normalized_key == "has_emergency_reserve" or normalized_expected == "has_reserve":
        reserve_status = _extract_binary_status(text)
        if reserve_status:
            merged["has_emergency_reserve"] = reserve_status

    if normalized_key == "debt_outside_cards" or normalized_expected == "debt_status":
        debt_status = _extract_binary_status(text)
        if debt_status:
            merged["debt_outside_cards"] = debt_status
        if any(token in text for token in ("financiamento", "emprestimo", "empréstimo", "consignado")):
            merged["debt_outside_cards"] = "yes"

    card_behavior = _extract_card_payment_behavior(text)
    if card_behavior:
        merged["card_payment_behavior"] = card_behavior

    if normalized_key == "category_other_breakdown":
        _push_note(merged, f"Categoria Outros citada pelo usuario: {(user_message or '').strip()[:100]}")

    merged["main_issue_hypothesis"] = _infer_main_issue_hypothesis(merged)
    return merged


def infer_consultant_stage(
    question_key: str = "",
    expected_answer_type: str = "",
    last_open_question: str = "",
    case_summary: dict[str, Any] | None = None,
) -> str:
    normalized_key = (question_key or "").strip().lower()
    normalized_expected = (expected_answer_type or "").strip().lower()
    question = (last_open_question or "").strip().lower()
    summary = normalize_case_summary(case_summary)

    if normalized_key in {"income_extra_recurrence", "income_extra_origin"}:
        return "income_clarification"
    if normalized_key in {"debt_outside_cards", "card_repayment_behavior"}:
        return "debt_mapping"
    if normalized_key == "has_emergency_reserve":
        return "reserve_check"
    if normalized_key in {"category_other_breakdown", "amount_followup", "open_text_followup", "yes_no_followup"}:
        return "diagnosis_clarification"

    if normalized_expected in {"income_recurrence"}:
        return "income_clarification"
    if normalized_expected in {"debt_status"}:
        return "debt_mapping"
    if normalized_expected in {"has_reserve"}:
        return "reserve_check"
    if normalized_expected in {"number_amount", "open_text", "yes_no"} and question:
        return "diagnosis_clarification"

    if summary.get("main_issue_hypothesis") in {"high_interest_debt", "outside_debt_pressure"}:
        return "action_plan"
    if summary.get("has_emergency_reserve") == "no":
        return "action_plan"
    return "diagnosis"


def transition_consultant_stage(
    current_stage: str = "",
    question_key: str = "",
    expected_answer_type: str = "",
    last_open_question: str = "",
    case_summary: dict[str, Any] | None = None,
) -> str:
    current = normalize_consultant_stage(current_stage)
    inferred = infer_consultant_stage(
        question_key,
        expected_answer_type,
        last_open_question,
        case_summary,
    )
    summary = normalize_case_summary(case_summary)

    if _should_move_to_action_plan(summary, inferred, question_key, expected_answer_type):
        return "action_plan"

    if current == "follow_up":
        return "follow_up"

    if current in {"diagnosis", "diagnosis_clarification"}:
        return inferred

    if current == "income_clarification":
        if STAGE_FLOW_ORDER[inferred] > STAGE_FLOW_ORDER[current]:
            return inferred
        if summary.get("income_extra_type") and summary.get("income_extra_origin"):
            if summary.get("has_emergency_reserve") == "unknown":
                return "reserve_check"
            return "action_plan"
        return "income_clarification"

    if current == "debt_mapping":
        if STAGE_FLOW_ORDER[inferred] > STAGE_FLOW_ORDER[current]:
            return inferred
        if summary.get("debt_outside_cards") != "unknown" or summary.get("card_payment_behavior"):
            if summary.get("has_emergency_reserve") == "unknown":
                return "reserve_check"
            return "action_plan"
        return "debt_mapping"

    if current == "reserve_check":
        if STAGE_FLOW_ORDER[inferred] > STAGE_FLOW_ORDER[current]:
            return inferred
        if summary.get("has_emergency_reserve") != "unknown":
            return "action_plan"
        return "reserve_check"

    if current == "action_plan":
        return "action_plan"

    if STAGE_FLOW_ORDER[inferred] >= STAGE_FLOW_ORDER[current]:
        return inferred
    return current


def build_case_summary_context(case_summary: dict[str, Any] | None) -> str:
    summary = normalize_case_summary(case_summary)
    lines: list[str] = []
    if summary["income_extra_type"]:
        lines.append(f"- Receita extra: {summary['income_extra_type']}")
    if summary["income_extra_origin"]:
        lines.append(f"- Origem da receita extra: {summary['income_extra_origin']}")
    if summary["has_emergency_reserve"] != "unknown":
        lines.append(f"- Reserva de emergencia: {summary['has_emergency_reserve']}")
    if summary["debt_outside_cards"] != "unknown":
        lines.append(f"- Dividas fora dos cartoes: {summary['debt_outside_cards']}")
    if summary["card_payment_behavior"]:
        lines.append(f"- Comportamento com cartao: {summary['card_payment_behavior']}")
    if summary["main_issue_hypothesis"]:
        lines.append(f"- Hipotese principal: {summary['main_issue_hypothesis']}")
    if summary["last_user_signal"]:
        lines.append(f"- Ultimo sinal do usuario: {summary['last_user_signal']}")
    for note in summary["notes"][-2:]:
        lines.append(f"- Nota: {note}")
    return "\n".join(lines)


def build_consultant_plan(case_summary: dict[str, Any] | None, stage: str = "") -> dict[str, str]:
    summary = normalize_case_summary(case_summary)
    normalized_stage = normalize_consultant_stage(stage)
    hypothesis = summary.get("main_issue_hypothesis")

    problem = "falta clareza sobre para onde o dinheiro esta vazando"
    why = "sem diagnostico claro, a pessoa continua ajustando detalhes e ignora o vazamento principal"
    first_move = "identificar a categoria ou comportamento que mais pesa no mes antes de falar de investimento"
    next_priority = "fechar uma pergunta objetiva que destrave a proxima decisao"

    if hypothesis == "high_interest_debt":
        problem = "divida cara ou pagamento ruim do cartao"
        why = "juros altos destroem qualquer tentativa de organizar o mes"
        first_move = "parar rotativo ou minimo e reorganizar pagamento da fatura antes de qualquer outro plano"
        next_priority = "mapear se ha outras dividas fora dos cartoes"
    elif hypothesis == "outside_debt_pressure":
        problem = "dividas fora do cartao comprimindo o caixa"
        why = "parcelas e financiamentos podem estar escondendo o problema principal do mes"
        first_move = "mapear quais dividas existem, custo e peso mensal antes de cortar categorias menores"
        next_priority = "entender reserva e folego de caixa"
    elif hypothesis == "no_emergency_buffer":
        problem = "sem reserva de emergencia"
        why = "qualquer imprevisto empurra a pessoa de volta para cartao, emprestimo ou descontrole"
        first_move = "criar uma reserva minima e parar de depender do improviso"
        next_priority = "definir de onde sai o primeiro valor para essa reserva"
    elif hypothesis == "income_volatility":
        problem = "receita extra instavel confundindo a leitura do mes"
        why = "se renda pontual vira base do padrao de vida, o orcamento quebra facil"
        first_move = "separar o que e renda recorrente do que foi so alivio pontual"
        next_priority = "organizar gastos fixos como se a renda extra nao existisse"

    if normalized_stage == "income_clarification":
        next_priority = "confirmar se a renda extra e recorrente ou pontual e de onde ela veio"
    elif normalized_stage == "debt_mapping":
        next_priority = "mapear dividas e comportamento do cartao para priorizar o risco certo"
    elif normalized_stage == "reserve_check":
        next_priority = "entender se existe reserva para saber se o proximo passo e protecao ou ataque a divida"
    elif normalized_stage == "action_plan":
        next_priority = "traduzir o diagnostico em uma primeira acao simples e executavel nesta semana"

    return {
        "primary_problem": problem,
        "why_it_matters": why,
        "first_move": first_move,
        "next_priority": next_priority,
    }


def build_consultant_plan_context(case_summary: dict[str, Any] | None, stage: str = "") -> str:
    plan = build_consultant_plan(case_summary, stage)
    return "\n".join(
        [
            f"- Problema principal: {plan['primary_problem']}",
            f"- Por que importa: {plan['why_it_matters']}",
            f"- Primeira acao recomendada: {plan['first_move']}",
            f"- Proxima prioridade: {plan['next_priority']}",
        ]
    )


def _normalize_binary(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "no", "unknown"}:
        return text
    return "unknown"


def _extract_binary_status(text: str) -> str:
    lowered = (text or "").strip().lower()
    if not lowered:
        return ""
    if any(token in lowered for token in ("nao", "não", "sem ", "nunca", "zero")):
        return "no"
    if any(token in lowered for token in ("sim", "tenho", "guardo", "possuo", "tem ", "tô com", "to com")):
        return "yes"
    return ""


def _extract_income_origin(text: str) -> str:
    mapping = {
        "plantao": "plantao",
        "plantão": "plantao",
        "freela": "freela",
        "freelance": "freelance",
        "bonus": "bonus",
        "bônus": "bonus",
        "comissao": "comissao",
        "comissão": "comissao",
        "hora extra": "hora extra",
        "venda": "venda",
        "pix": "pix",
    }
    for token, label in mapping.items():
        if token in text:
            return label
    return ""


def _extract_income_type(text: str) -> str:
    recurring_tokens = ("recorrente", "todo mes", "todo mês", "fixa", "fixo", "sempre")
    one_off_tokens = ("pontual", "so esse mes", "só esse mês", "esse mes", "esse mês", "foi so", "foi só")
    if any(token in text for token in recurring_tokens):
        return "recorrente"
    if any(token in text for token in one_off_tokens):
        return "pontual"
    return ""


def _extract_card_payment_behavior(text: str) -> str:
    if any(token in text for token in ("rotativo",)):
        return "rotativo"
    if any(token in text for token in ("minimo", "mínimo")):
        return "minimo"
    if any(token in text for token in ("parcial", "parcelo")):
        return "parcial"
    if any(token in text for token in ("total", "pago tudo", "pago a fatura inteira")):
        return "total"
    return ""


def _infer_main_issue_hypothesis(summary: dict[str, Any]) -> str:
    if summary.get("card_payment_behavior") in {"rotativo", "minimo"}:
        return "high_interest_debt"
    if summary.get("debt_outside_cards") == "yes":
        return "outside_debt_pressure"
    if summary.get("has_emergency_reserve") == "no":
        return "no_emergency_buffer"
    if summary.get("income_extra_type") == "pontual":
        return "income_volatility"
    return summary.get("main_issue_hypothesis", "")


def _push_note(summary: dict[str, Any], note: str) -> None:
    clean_note = (note or "").strip()[:160]
    if not clean_note:
        return
    notes = list(summary.get("notes") or [])
    if clean_note not in notes:
        notes.append(clean_note)
    summary["notes"] = notes[-5:]


def _should_move_to_action_plan(
    summary: dict[str, Any],
    inferred_stage: str,
    question_key: str,
    expected_answer_type: str,
) -> bool:
    if inferred_stage == "action_plan":
        return True
    if (question_key or "").strip() or (expected_answer_type or "").strip():
        return False
    if summary.get("main_issue_hypothesis") in {
        "high_interest_debt",
        "outside_debt_pressure",
        "no_emergency_buffer",
    }:
        if summary.get("has_emergency_reserve") != "unknown" or summary.get("card_payment_behavior"):
            return True
    return False
