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


def test_golden_weekly_flow_numeric_with_dot_format():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="agressivo", state=state)
    r2, state = _step(user_message="2.800", state=state)
    assert r2["consultant_stage"] == "follow_up"
    assert "alvo mensal validado: ~r$2800." in r2["content"].lower()


def test_golden_weekly_flow_numeric_with_comma_format():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="conservador", state=state)
    r2, state = _step(user_message="R$ 3.000,00", state=state)
    assert r2["consultant_stage"] == "follow_up"
    assert "alvo mensal validado: ~r$3000." in r2["content"].lower()


def test_golden_weekly_flow_affirmative_without_number_uses_saved_target():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="agressivo", state=state)
    r2, state = _step(user_message="fechado", state=state)
    assert r2["consultant_stage"] == "follow_up"
    assert "alvo mensal validado: ~r$2600." in r2["content"].lower()


def test_golden_weekly_flow_prevents_generic_drift_after_profile():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="agressivo", state=state)
    r2, state = _step(user_message="isso bate quase 3600 por mes, nao e muito?", state=state)
    assert GENERIC_DRIFT_SNIPPET.lower() not in r2["content"].lower()
    content_lower = r2["content"].lower()
    assert ("r$2.920" in content_lower) or ("r$2920" in content_lower)


def test_golden_weekly_flow_profile_confortavel():
    state = _base_weekly_intent_state()
    r1, state = _step(user_message="confortavel", state=state)
    assert "perfil *confortavel*" in r1["content"].lower() or "perfil *confortável*" in r1["content"].lower()
    assert "r$3200/mes" in r1["content"].lower()


def test_golden_followup_more_time_14_days():
    state = _base_weekly_intent_state()
    state["case_summary"] = normalize_case_summary(
        {"active_intent": "weekly_budget_cap", "followup_pending": True, "followup_days": 7}
    )
    r1, state = _step(user_message="vamos em 14 dias", state=state)
    assert "14 dias" in r1["content"].lower()
    assert state["case_summary"].get("followup_days") == 14


def test_golden_followup_more_time_30_days():
    state = _base_weekly_intent_state()
    state["case_summary"] = normalize_case_summary(
        {"active_intent": "weekly_budget_cap", "followup_pending": True, "followup_days": 7}
    )
    r1, state = _step(user_message="melhor em 30 dias", state=state)
    assert "30 dias" in r1["content"].lower()
    assert state["case_summary"].get("followup_days") == 30


def test_golden_checkin_deu_certo_requests_mode_choice():
    state = _base_weekly_intent_state()
    state["case_summary"] = normalize_case_summary(
        {"active_intent": "weekly_budget_cap", "followup_pending": True, "followup_days": 7}
    )
    r1, state = _step(user_message="deu certo", state=state)
    assert "modo conservador" in r1["content"].lower()
    assert r1["consultant_stage"] == "action_plan"


def test_golden_checkin_deu_ruim_requests_mode_choice():
    state = _base_weekly_intent_state()
    state["case_summary"] = normalize_case_summary(
        {"active_intent": "weekly_budget_cap", "followup_pending": True, "followup_days": 7}
    )
    r1, state = _step(user_message="deu ruim", state=state)
    assert "modo conservador" in r1["content"].lower()
    assert GENERIC_DRIFT_SNIPPET.lower() not in r1["content"].lower()


def test_golden_active_intent_with_question_not_lost():
    state = _base_weekly_intent_state()
    r1, state = _step(user_message="qual vc indica pra casal e filho?", state=state)
    assert "2 adultos e 1 crian" in r1["content"].lower()
    assert r1["open_question_key"] == "open_text_followup"


def test_golden_numeric_after_monthly_challenge_closes_plan():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="isso ta alto por mes", state=state)
    r2, state = _step(user_message="3200", state=state)
    assert "alvo mensal validado: ~r$3200." in r2["content"].lower()
    assert r2["consultant_stage"] == "follow_up"


def test_golden_profile_then_yes_closes_followup():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="conservador", state=state)
    r2, state = _step(user_message="sim", state=state)
    assert r2["consultant_stage"] == "follow_up"
    assert "alvo mensal validado: ~r$3000." in r2["content"].lower()


def test_golden_followup_pending_keeps_intent_after_numeric_close():
    state = _base_weekly_intent_state()
    r1, state = _step(user_message="2000", state=state)
    assert r1["consultant_stage"] == "follow_up"
    assert state["case_summary"].get("active_intent") == "weekly_budget_cap"
    assert state["case_summary"].get("followup_pending") is True


def test_golden_fallback_question_remains_on_budget_topic():
    state = _base_weekly_intent_state()
    r1, state = _step(user_message="nao sei", state=state)
    assert "teto mais conservador" in r1["question"].lower()
    assert "calibrar um teto" in r1["content"].lower()


def test_golden_sequence_three_turn_success():
    state = _base_weekly_intent_state()
    _, state = _step(user_message="qual vc indica p 2 adultos e 1 crianca?", state=state)
    _, state = _step(user_message="agressivo", state=state)
    r3, state = _step(user_message="2800", state=state)
    assert r3["consultant_stage"] == "follow_up"
    assert "alvo mensal validado: ~r$2800." in r3["content"].lower()
