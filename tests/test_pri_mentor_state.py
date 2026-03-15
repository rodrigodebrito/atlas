import importlib
import sqlite3
import sys
import uuid
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

    state_after_first = atlas._load_mentor_state(phone)
    assert state_after_first is not None
    assert state_after_first["open_question_key"] == "income_extra_recurrence"

    second = await atlas.chat_endpoint(user_phone=phone, message="foi por plantao")
    assert "reserva" in second["content"].lower()

    assert executed_routes == []
    assert len(stub_agent.calls) == 2
    assert "[CHAVE FORMAL DA PERGUNTA ABERTA]" in stub_agent.calls[1]["input"]
    assert "income_extra_recurrence" in stub_agent.calls[1]["input"]
    assert "[ESTAGIO ATUAL DA CONSULTORIA]" in stub_agent.calls[1]["input"]
    assert "income_clarification" in stub_agent.calls[1]["input"]
    assert "[RESUMO ESTRUTURADO DO CASO]" in stub_agent.calls[1]["input"]
    assert "Origem da receita extra: plantao" in stub_agent.calls[1]["input"]
    assert "[PLANO DE CONSULTORIA DA PRI]" in stub_agent.calls[1]["input"]
    assert "Primeira acao recomendada" in stub_agent.calls[1]["input"]

    state_after_second = atlas._load_mentor_state(phone)
    assert state_after_second is not None
    assert "reserva" in state_after_second["last_open_question"].lower()
    assert state_after_second["consultant_stage"] == "reserve_check"
    assert state_after_second["case_summary"]["income_extra_origin"] == "plantao"
