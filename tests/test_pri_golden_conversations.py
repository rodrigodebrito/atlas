from __future__ import annotations

from agno_api.mentor_consultant import build_structured_pri_followup, normalize_case_summary


GENERIC_DRIFT_SNIPPET = "Bora pro jogo real"


def _step(
    *,
    user_message: str,
    state: dict,
) -> tuple[dict, dict]:
    result = build_structured_pri_followup(
        user_message=user_message,
        question_key=state.get("open_question_key", ""),
        expected_answer_type=state.get("expected_answer_type", ""),
        case_summary=state.get("case_summary", {}),
        stage=state.get("consultant_stage", "action_plan"),
        last_open_question=state.get("last_open_question", ""),
        mentor_turn_count=state.get("mentor_turn_count", 1),
        max_turns=3,
    )
    next_state = {
        "open_question_key": result.get("open_question_key", ""),
        "expected_answer_type": result.get("expected_answer_type", ""),
        "consultant_stage": result.get("consultant_stage", "action_plan"),
        "last_open_question": result.get("question", ""),
        "mentor_turn_count": int(state.get("mentor_turn_count", 1)) + 1,
        "case_summary": normalize_case_summary(result.get("case_summary", {})),
    }
    return result, next_state


def _base_weekly_intent_state() -> dict:
    return {
        "open_question_key": "open_text_followup",
        "expected_answer_type": "open_text",
        "consultant_stage": "action_plan",
        "last_open_question": "Me diz um teto simples pra testar por 7 dias: quanto voce quer limitar em delivery/comer fora?",
        "mentor_turn_count": 1,
        "case_summary": normalize_case_summary({"active_intent": "weekly_budget_cap"}),
    }


def test_golden_weekly_flow_profile_then_numeric_target():
    state = _base_weekly_intent_state()

    r1, state = _step(user_message="Qual vc indica pr 2 pessoas e uma crianca?", state=state)
    assert "2 adultos e 1 crian" in r1["content"].lower()
    assert GENERIC_DRIFT_SNIPPET.lower() not in r1["content"].lower()

    r2, state = _step(user_message="agressivo", state=state)
    assert "perfil *agressivo*" in r2["content"].lower()
    assert "r$2600/mes" in r2["content"].lower()
    assert GENERIC_DRIFT_SNIPPET.lower() not in r2["content"].lower()

    previous_question = r2.get("question", "")
    r3, state = _step(user_message="2000", state=state)
    assert "alvo mensal validado: ~r$2000." in r3["content"].lower()
    assert r3["consultant_stage"] == "follow_up"
    assert r3.get("question", "") != previous_question
    assert GENERIC_DRIFT_SNIPPET.lower() not in r3["content"].lower()


def test_golden_weekly_flow_monthly_challenge_then_choice():
    state = _base_weekly_intent_state()

    r1, state = _step(user_message="isso bate quase 3600 por mes, nao e muito?", state=state)
    assert "R$2.920" in r1["content"]
    assert "qual teto mensal final" in r1["content"].lower()

    r2, state = _step(user_message="2800", state=state)
    assert "alvo mensal validado: ~r$2800." in r2["content"].lower()
    assert r2["consultant_stage"] == "follow_up"


def test_golden_followup_reschedule_to_15_days():
    state = _base_weekly_intent_state()
    state["case_summary"] = normalize_case_summary(
        {
            "active_intent": "weekly_budget_cap",
            "followup_pending": True,
            "followup_days": 7,
        }
    )

    r1, state = _step(user_message="pode ser em 15 dias", state=state)
    assert "15 dias" in r1["content"].lower()
    assert r1["consultant_stage"] == "follow_up"
    assert state["case_summary"].get("followup_days") == 15


def test_golden_followup_checkin_keeps_context():
    state = _base_weekly_intent_state()
    state["case_summary"] = normalize_case_summary(
        {
            "active_intent": "weekly_budget_cap",
            "followup_pending": True,
            "followup_days": 7,
            "monthly_target_cents": 280000,
        }
    )

    r1, state = _step(user_message="gastei bem menos essa semana, sobrou do teto", state=state)
    assert "ajuste agora em modo conservador" in r1["content"].lower()
    assert r1["consultant_stage"] == "action_plan"
    assert GENERIC_DRIFT_SNIPPET.lower() not in r1["content"].lower()
