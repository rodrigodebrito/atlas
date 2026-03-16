import importlib
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest


class _DummyResponse:
    def __init__(self, content: str):
        self.content = content


class _StubAtlasAgent:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def arun(self, input: str, session_id: str):
        self.calls.append({"input": input, "session_id": session_id})
        if not self._responses:
            raise AssertionError("Stub agent recebeu mais chamadas do que o esperado")
        return _DummyResponse(self._responses.pop(0))


class _CompatConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        text = (sql or "").strip()
        if ";" in text.strip().rstrip(";"):
            return self._conn.executescript(sql)
        return self._conn.execute(sql, params)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def cursor(self):
        return self._conn.cursor()

    def __getattr__(self, item):
        return getattr(self._conn, item)


@pytest.fixture
def atlas(monkeypatch):
    data_dir = Path.cwd() / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / f"pri_test_{uuid.uuid4().hex}.db"
    real_connect = sqlite3.connect

    def _temp_conn():
        return real_connect(str(db_path))

    def _patched_connect(_path, *args, **kwargs):
        conn = real_connect(str(db_path), *args, **kwargs)
        return _CompatConnection(conn)

    monkeypatch.setattr(sqlite3, "connect", _patched_connect)
    sys.modules.pop("agno_api.agent", None)
    agent = importlib.import_module("agno_api.agent")

    monkeypatch.setattr(agent, "_get_conn", _temp_conn)
    monkeypatch.setattr(agent, "DB_TYPE", "sqlite")

    with agent._db() as (conn, cur):
        agent._ensure_mentor_dialog_state_table(cur)
        conn.commit()

    try:
        yield agent
    finally:
        db_path.unlink(missing_ok=True)


def test_save_and_load_mentor_state_persists_structured_fields(atlas):
    phone = "+5511999999999"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Essa receita extra veio pra ficar ou foi pontual?",
        open_question_key="income_extra_recurrence",
        expected_answer_type="income_recurrence",
        consultant_stage="income_clarification",
        case_summary={
            "income_extra_origin": "plantao",
            "has_emergency_reserve": "unknown",
        },
        memory_turns=[
            {"role": "Usuario", "content": "pri faz uma analise"},
            {"role": "Pri", "content": "Essa receita extra veio pra ficar ou foi pontual?"},
        ],
        expires_at=atlas._mentor_expiry_iso(),
    )

    state = atlas._load_mentor_state(phone)

    assert state is not None
    assert state["mode"] == "mentor"
    assert state["last_open_question"] == "Essa receita extra veio pra ficar ou foi pontual?"
    assert state["open_question_key"] == "income_extra_recurrence"
    assert state["expected_answer_type"] == "income_recurrence"
    assert state["consultant_stage"] == "income_clarification"
    assert state["case_summary"]["income_extra_origin"] == "plantao"
    assert len(state["memory_turns"]) == 2


def test_structured_question_key_recognizes_short_continuation_reply(atlas):
    state = {
        "open_question_key": "income_extra_origin",
        "expected_answer_type": "open_text",
    }

    assert atlas._looks_like_answer_to_open_mentor_question("foi por plantao", state)
    assert not atlas._looks_like_answer_to_open_mentor_question("gastei 50 no ifood", state)


def test_merge_case_summary_extracts_consultant_signals(atlas):
    summary = atlas.merge_case_summary(
        {"has_emergency_reserve": "unknown"},
        "Foi por plantao e eu nao tenho reserva ainda",
        "has_emergency_reserve",
        "has_reserve",
    )

    assert summary["income_extra_origin"] == "plantao"
    assert summary["has_emergency_reserve"] == "no"
    assert summary["main_issue_hypothesis"] == "no_emergency_buffer"


def test_transition_consultant_stage_promotes_to_action_plan_when_case_is_ready(atlas):
    next_stage = atlas.transition_consultant_stage(
        "reserve_check",
        "",
        "",
        "",
        {
            "has_emergency_reserve": "no",
            "main_issue_hypothesis": "no_emergency_buffer",
        },
    )

    assert next_stage == "action_plan"


def test_pri_month_snapshot_only_uses_complete_month_history(atlas):
    phone = "+5511933334444"
    user_id = f"user_{uuid.uuid4().hex}"
    now = atlas._now_br()
    current_month_start = datetime(now.year, now.month, 1)
    prev_year, prev_month = atlas._shift_year_month(now.year, now.month, -1)
    prev_month_mid = datetime(prev_year, prev_month, 20)

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            "INSERT INTO transactions (id, user_id, type, amount_cents, category, occurred_at) VALUES (?, ?, 'EXPENSE', ?, ?, ?)",
            (f"tx_{uuid.uuid4().hex}", user_id, 8000, "Alimentacao", prev_month_mid.strftime("%Y-%m-%d")),
        )
        cur.execute(
            "INSERT INTO transactions (id, user_id, type, amount_cents, category, occurred_at) VALUES (?, ?, 'EXPENSE', ?, ?, ?)",
            (f"tx_{uuid.uuid4().hex}", user_id, 12000, "Alimentacao", current_month_start.strftime("%Y-%m-%d")),
        )
        conn.commit()
    finally:
        conn.close()

    snapshot = atlas._get_pri_month_opening_snapshot(phone)

    assert snapshot["has_complete_month_history"] is False
    assert snapshot["complete_month_history_count"] == 0
    assert snapshot["average_complete_month_expense_cents"] == 0


@pytest.mark.asyncio
async def test_chat_endpoint_keeps_short_reply_inside_pri_flow(atlas, monkeypatch):
    phone = "+5511988887777"
    stub_agent = _StubAtlasAgent(
        [
            "Pri aqui. Essa receita extra veio pra ficar ou foi pontual?",
            "Boa. Entao foi pontual. Isso muda o plano. Voce tem alguma reserva hoje?",
        ]
    )

    routes = iter(
        [
            {"intent": "mentor", "action": "", "params": {}},
            {"intent": "save_transaction", "action": "save_transaction", "params": {}},
        ]
    )
    executed_routes: list[dict] = []

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return next(routes)

    async def _fake_execute_intent(result: dict, user_phone: str, body: str, full_message: str):
        executed_routes.append(result)
        return {"response": "NAO_DEVERIA_EXECUTAR"}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "_execute_intent", _fake_execute_intent)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    first = await atlas.chat_endpoint(user_phone=phone, message="pri me ajuda")
    assert "pontual" in first["content"].lower()
    assert "ABERTURA OBRIGATÓRIA DA PRI" in stub_agent.calls[0]["input"]
    assert "você NÃO faz um resumo completo do mês" in stub_agent.calls[0]["input"]

    state_after_first = atlas._load_mentor_state(phone)
    assert state_after_first is not None
    assert state_after_first["open_question_key"] == "income_extra_recurrence"

    second = await atlas.chat_endpoint(user_phone=phone, message="foi por plantao")
    second_content = second["content"].lower()
    assert "plantao" in second_content
    assert "pontual" in second_content or "frequencia" in second_content

    assert executed_routes == []
    assert len(stub_agent.calls) == 1

    state_after_second = atlas._load_mentor_state(phone)
    assert state_after_second is not None
    assert "pontual" in state_after_second["last_open_question"].lower() or "frequencia" in state_after_second["last_open_question"].lower()
    assert state_after_second["consultant_stage"] == "income_clarification"
    assert state_after_second["case_summary"]["income_extra_origin"] == "plantao"


@pytest.mark.asyncio
async def test_chat_endpoint_keeps_affirmative_reply_for_plan_offer_inside_pri_flow(atlas, monkeypatch):
    phone = "+5511971112222"
    stub_agent = _StubAtlasAgent(
        [
            (
                "Pri aqui. Hoje teu dinheiro nao explodiu num gasto so. "
                "Ele foi pingando em alimentacao. "
                "Me conta se quer ajuda pra montar um plano pra isso."
            ),
            "Fechou. Entao vamos montar isso juntas. Primeiro: voce quer cortar delivery, mercado ou refeicao fora?",
        ]
    )

    routes = iter(
        [
            {"intent": "mentor", "action": "", "params": {}},
            {"intent": "save_transaction", "action": "save_transaction", "params": {}},
        ]
    )
    executed_routes: list[dict] = []

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return next(routes)

    async def _fake_execute_intent(result: dict, user_phone: str, body: str, full_message: str):
        executed_routes.append(result)
        return {"response": "NAO_DEVERIA_EXECUTAR"}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "_execute_intent", _fake_execute_intent)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    first = await atlas.chat_endpoint(user_phone=phone, message="pri faz uma analise do meu dia")
    assert "montar um plano" in first["content"].lower()

    state_after_first = atlas._load_mentor_state(phone)
    assert state_after_first is not None
    assert "quer ajuda" in (state_after_first["last_open_question"] or "").lower()
    assert state_after_first["open_question_key"] == "plan_help_offer"
    assert state_after_first["expected_answer_type"] == "yes_no"

    second = await atlas.chat_endpoint(user_phone=phone, message="quero sim")
    assert "vamos montar" in second["content"].lower()
    assert executed_routes == []
    assert len(stub_agent.calls) == 1


@pytest.mark.asyncio
async def test_explicit_panel_request_bypasses_active_mentor_session(atlas, monkeypatch):
    phone = "+5511912340000"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Quer que eu monte um plano pra isso?",
        open_question_key="plan_help_offer",
        expected_answer_type="yes_no",
        consultant_stage="action_plan",
        case_summary={"main_issue_hypothesis": "cashflow_pressure"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )

    async def _unexpected_mini_route(*_args, **_kwargs):
        raise AssertionError("mini-router nao deveria rodar para o comando explicito 'painel'")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _unexpected_mini_route)
    monkeypatch.setattr(atlas, "get_panel_url", lambda _phone: "https://atlas.test/painel")

    result = await atlas.chat_endpoint(user_phone=phone, message="painel")

    assert "atlas.test/painel" in result["content"]
    assert "painel" in result["content"].lower()


@pytest.mark.asyncio
async def test_debt_followup_stays_structured_even_with_generic_open_text_key(atlas, monkeypatch):
    phone = "+5511944443333"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Agora, me diz: alem dos cartoes, tem alguma divida ou emprestimo que nao aparece aqui?",
        open_question_key="open_text_followup",
        expected_answer_type="debt_status",
        consultant_stage="debt_mapping",
        case_summary={"main_issue_hypothesis": "cashflow_pressure"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "save_transaction", "action": "save_transaction", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(user_phone=phone, message="entao estou usando 1.500 do cheque especial")

    content = result["content"].lower()
    assert "alerta vermelho" in content
    assert "cheque especial" in content
    assert "morde teu mes" in content
    assert "media mensal" not in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["consultant_stage"] == "action_plan"
    assert state["open_question_key"] == "amount_followup"
    assert state["case_summary"]["main_issue_hypothesis"] == "high_interest_debt"
    assert state["case_summary"]["debt_outside_cards"] == "yes"


@pytest.mark.asyncio
async def test_reserve_amount_followup_handles_no_capacity_reply(atlas, monkeypatch):
    phone = "+5511932100000"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Hoje, sem se enrolar, voce consegue separar quanto por mes: R$100, R$300 ou mais?",
        open_question_key="amount_followup",
        expected_answer_type="number_amount",
        consultant_stage="action_plan",
        case_summary={"main_issue_hypothesis": "no_emergency_buffer", "has_emergency_reserve": "no"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "save_transaction", "action": "save_transaction", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(user_phone=phone, message="nao separo valor")

    content = result["content"].lower()
    assert "falta de folga" in content
    assert "abrindo espaco" in content
    assert "delivery" in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "open_text_followup"
    assert state["consultant_stage"] == "action_plan"
    assert state["case_summary"]["main_issue_hypothesis"] == "no_emergency_buffer"


@pytest.mark.asyncio
async def test_first_pri_month_analysis_uses_structured_opening_without_llm(atlas, monkeypatch):
    phone = "+5511977776666"
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    monkeypatch.setattr(
        atlas,
        "_get_pri_opening_snapshot",
        lambda _phone, _scope="month": {
            "first_name": "Rodrigo",
            "scope": "month",
            "period_label": "este mes",
            "declared_income_cents": 1200000,
            "actual_income_cents": 1767754,
            "expense_total_cents": 1912147,
            "card_total_cents": 473420,
            "top_categories": [
                {"name": "Moradia", "total_cents": 821143, "count": 5},
                {"name": "Outros", "total_cents": 531700, "count": 3},
                {"name": "Alimentacao", "total_cents": 195400, "count": 33},
            ],
        },
    )

    result = await atlas.chat_endpoint(user_phone=phone, message="pri faz uma analise do meu mes")

    assert "falta de renda" in result["content"].lower()
    assert "vazamento" in result["content"].lower()
    assert "outros" in result["content"].lower()
    assert "tudo misturado" in result["content"].lower()
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "category_other_breakdown"
    assert state["consultant_stage"] == "diagnosis_clarification"
    assert state["case_summary"]["main_issue_hypothesis"] == "cashflow_pressure"


@pytest.mark.asyncio
async def test_explicit_pri_month_analysis_restarts_with_structured_opening_during_active_session(atlas, monkeypatch):
    phone = "+5511977444400"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Quer que eu monte um plano pra isso?",
        open_question_key="plan_help_offer",
        expected_answer_type="yes_no",
        consultant_stage="action_plan",
        case_summary={"main_issue_hypothesis": "cashflow_pressure"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    monkeypatch.setattr(
        atlas,
        "_get_pri_opening_snapshot",
        lambda _phone, _scope="month": {
            "first_name": "Rodrigo",
            "scope": "month",
            "period_label": "este mes",
            "declared_income_cents": 1200000,
            "actual_income_cents": 1777344,
            "expense_total_cents": 1918795,
            "card_total_cents": 473420,
            "top_categories": [
                {"name": "Moradia", "total_cents": 821143, "count": 5},
                {"name": "Outros", "total_cents": 535700, "count": 3},
                {"name": "Alimentacao", "total_cents": 198052, "count": 34},
            ],
        },
    )

    result = await atlas.chat_endpoint(user_phone=phone, message="pri faz uma analise do meu mes")

    content = result["content"].lower()
    assert "vazamento" in content
    assert "outros" in content
    assert "ta tudo misturado" in content
    assert "?" in result["content"]
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "category_other_breakdown"
    assert state["consultant_stage"] == "diagnosis_clarification"


@pytest.mark.asyncio
async def test_structured_followup_handles_cheque_especial_answer_without_llm(atlas, monkeypatch):
    phone = "+5511944441111"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Alem dos cartoes, tem alguma divida ou emprestimo que nao aparece aqui?",
        open_question_key="debt_outside_cards",
        expected_answer_type="debt_status",
        consultant_stage="debt_mapping",
        case_summary={"main_issue_hypothesis": "cashflow_pressure"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(user_phone=phone, message="entao estou usando 1.500 do cheque especial")

    content = result["content"].lower()
    assert "alerta vermelho" in content
    assert "cheque especial" in content
    assert "1.500" in result["content"] or "R$1.500" in result["content"]
    assert "?" in result["content"]
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "amount_followup"
    assert state["consultant_stage"] == "action_plan"
    assert state["case_summary"]["main_issue_hypothesis"] == "high_interest_debt"


@pytest.mark.asyncio
async def test_first_pri_month_analysis_explains_when_no_full_month_history(atlas, monkeypatch):
    phone = "+5511977000001"
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    monkeypatch.setattr(
        atlas,
        "_get_pri_opening_snapshot",
        lambda _phone, _scope="month": {
            "first_name": "Rodrigo",
            "scope": "month",
            "period_label": "este mes",
            "declared_income_cents": 1200000,
            "actual_income_cents": 1767754,
            "expense_total_cents": 1912147,
            "card_total_cents": 473420,
            "top_categories": [
                {"name": "Outros", "total_cents": 531700, "count": 3},
            ],
            "average_complete_month_expense_cents": 0,
            "complete_month_history_count": 0,
            "has_complete_month_history": False,
        },
    )

    result = await atlas.chat_endpoint(user_phone=phone, message="pri faz uma analise do meu mes")

    content = result["content"].lower()
    assert "mes fechado" in content
    assert "media mensal" in content
    assert "seguranca" in content
    assert stub_agent.calls == []


@pytest.mark.asyncio
async def test_first_pri_debt_question_uses_debt_frame_without_llm(atlas, monkeypatch):
    phone = "+5511966665555"
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    monkeypatch.setattr(
        atlas,
        "_get_pri_opening_snapshot",
        lambda _phone, _scope="month": {
            "first_name": "Rodrigo",
            "scope": "month",
            "period_label": "este mes",
            "declared_income_cents": 1200000,
            "actual_income_cents": 1200000,
            "expense_total_cents": 900000,
            "card_total_cents": 0,
            "top_categories": [],
        },
    )

    result = await atlas.chat_endpoint(user_phone=phone, message="pri estou devendo 2.000 no cheque especial o que fazer?")

    content = result["content"].lower()
    assert "custo desse dinheiro" in content
    assert "cheque especial" in content or "rotativo" in content
    assert "levantar parte disso" in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["case_summary"]["main_issue_hypothesis"] == "high_interest_debt"
    assert state["consultant_stage"] == "diagnosis_clarification"


@pytest.mark.asyncio
async def test_first_pri_last_week_analysis_uses_temporal_frame_without_llm(atlas, monkeypatch):
    phone = "+5511955554444"
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    monkeypatch.setattr(
        atlas,
        "_get_pri_opening_snapshot",
        lambda _phone, _scope="month": {
            "first_name": "Rodrigo",
            "scope": "last_week",
            "period_label": "semana passada",
            "declared_income_cents": 1200000,
            "actual_income_cents": 0,
            "expense_total_cents": 356700,
            "card_total_cents": 473420,
            "top_categories": [
                {"name": "Outros", "total_cents": 160000, "count": 2},
                {"name": "Alimentacao", "total_cents": 82000, "count": 6},
            ],
        },
    )

    result = await atlas.chat_endpoint(user_phone=phone, message="pri faz minha analise da semana passada")

    content = result["content"].lower()
    assert "semana passada" in content
    assert "outros" in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "category_other_breakdown"
