from __future__ import annotations

import pytest

from agno_api.mentor_consultant import (
    enforce_dialogue_contract,
    has_template_drift,
    normalize_case_summary,
)


GENERIC_TEMPLATE = (
    "Fechado. Bora pro jogo real.\n\n"
    "O que eu faria agora: identificar a categoria ou comportamento que mais pesa no mes antes de falar de investimento.\n\n"
    "Hoje:\n"
    "1. Escolher um ajuste.\n\n"
    "Proximos 7 dias:\n"
    "2. Transformar esse ajuste em regra simples.\n\n"
    "Proximos 30 dias:\n"
    "3. Revisar resultado."
)


@pytest.mark.parametrize(
    ("user_message", "last_question", "expected_snippet"),
    [
        ("Qual vc indica pr 2 pessoas e uma criança?", "Me diz um teto simples pra 7 dias: quanto limitar em delivery/comer fora?", "R$550"),
        ("qual voce indica para 2 pessoas e 1 crianca?", "Me diz um teto simples pra 7 dias: quanto limitar em delivery/comer fora?", "R$180"),
        ("quanto vc indica pra 2 pessoas e uma crianca?", "Me diz um teto simples pra 7 dias: quanto limitar em delivery/comer fora?", "R$2.920"),
        ("qual valor vc sugere pra 2 pessoas e 1 crianca?", "Me diz um teto simples pra 7 dias: quanto limitar em delivery/comer fora?", "Topa testar esse teto"),
        ("isso bate quase 3600 por mes, nao e muito?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("isso ta alto por mes", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$3.000"),
        ("ficou alto por mes", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$3.200"),
        ("qual valor fica bom?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.800"),
        ("quanto vc indica?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("qual vc indica p 2 pessoas?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$550"),
        ("qual vc indica pra familia com 1 crianca?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$180"),
        ("quanto sugere pra casal e filho?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("isso da quase 3.600 por mes", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("isso bate por mes", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$550"),
        ("qual vc indica para duas pessoas e uma crianca", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$180"),
        ("qual valor pra 2 adultos e 1 crianca?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("quanto fica bom pra familia?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$3.000"),
        ("qual vc indica p 2 adultos e 1 criança?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.800"),
        ("isso está alto por mês", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$550"),
        ("quanto voce indica para duas pessoas e um filho?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$180"),
        ("qual valor ideal para casal com criança?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("isso ficou alto demais no mês", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$3.000"),
        ("qual vc indica pra 2 pessoas e 1 crianca", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$550"),
        ("quanto vc indica pra família de 3?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$180"),
        ("qual valor fica melhor por mes?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("isso bate quase 3600 por mês", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("qual voce indica pra casal e uma crianca?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$550"),
        ("quanto sugere para 2 pessoas e uma criança?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$180"),
        ("qual valor vc recomenda p 2 pessoas e 1 crianca?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
        ("isso por mes ta alto?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$3.000"),
        ("qual vc indica para 2 adultos e 1 filho?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$550"),
        ("quanto vc sugere por mes para esse caso?", "Topa testar esse teto por 7 dias e me mandar o resultado?", "R$2.920"),
    ],
)
def test_contract_repair_avoids_template_drift_in_explicit_questions(
    user_message: str,
    last_question: str,
    expected_snippet: str,
):
    payload = {
        "content": GENERIC_TEMPLATE,
        "question": "",
        "open_question_key": "open_text_followup",
        "expected_answer_type": "open_text",
        "consultant_stage": "action_plan",
        "case_summary": normalize_case_summary({"main_issue_hypothesis": "cashflow_pressure"}),
    }

    repaired = enforce_dialogue_contract(
        payload=payload,
        user_message=user_message,
        last_open_question=last_question,
        open_question_key="open_text_followup",
        expected_answer_type="open_text",
        stage="action_plan",
        case_summary=payload["case_summary"],
    )

    assert "Bora pro jogo real" not in repaired["content"]
    assert "identificar a categoria ou comportamento" not in repaired["content"]
    assert expected_snippet in repaired["content"]
    assert repaired["question"]
    assert repaired["open_question_key"] == "open_text_followup"


def test_has_template_drift_detects_off_context_template():
    assert has_template_drift(
        response_content=GENERIC_TEMPLATE,
        user_message="Qual vc indica pr 2 pessoas e uma criança?",
        last_open_question="Me diz um teto simples pra 7 dias: quanto limitar em delivery/comer fora?",
        open_question_key="open_text_followup",
    )


def test_has_template_drift_does_not_flag_on_topic_response():
    response = (
        "Fechou. Para 2 adultos e 1 criança, eu iria de R$550/semana em mercado/casa e R$180/semana em delivery.\n\n"
        "Topa testar por 7 dias e me contar?"
    )
    assert not has_template_drift(
        response_content=response,
        user_message="Qual vc indica pr 2 pessoas e uma criança?",
        last_open_question="Me diz um teto simples pra 7 dias: quanto limitar em delivery/comer fora?",
        open_question_key="open_text_followup",
    )


def test_contract_follow_up_state_clears_open_question_fields():
    payload = {
        "content": "Combinado.",
        "question": "Me manda em 7 dias?",
        "open_question_key": "open_text_followup",
        "expected_answer_type": "open_text",
        "consultant_stage": "follow_up",
        "case_summary": {},
    }
    repaired = enforce_dialogue_contract(
        payload=payload,
        user_message="fechado",
        last_open_question="",
        open_question_key="open_text_followup",
        expected_answer_type="open_text",
        stage="follow_up",
        case_summary={},
    )
    assert repaired["consultant_stage"] == "follow_up"
    assert repaired["question"] == ""
    assert repaired["open_question_key"] == ""
    assert repaired["expected_answer_type"] == ""
