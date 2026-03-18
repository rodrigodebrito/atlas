import importlib
import gc
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
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
        gc.collect()
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            gc.collect()
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


def test_pri_month_snapshot_uses_card_due_month_for_cashflow_commitment(atlas):
    phone = "+5511944445555"
    user_id = f"user_{uuid.uuid4().hex}"
    card_id = f"card_{uuid.uuid4().hex}"
    now = atlas._now_br()
    current_month = now.strftime("%Y-%m")
    prev_year, prev_month = atlas._shift_year_month(now.year, now.month, -1)

    current_day = max(6, min(now.day, 20))
    prev_month_day = 20

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO credit_cards
               (id, user_id, name, closing_day, due_day, current_bill_opening_cents)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (card_id, user_id, "Caixa", 5, 15, 0),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, occurred_at)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 10000, "Alimentacao", f"{current_month}-{current_day:02d}"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, occurred_at, card_id)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?)""",
            (
                f"tx_{uuid.uuid4().hex}",
                user_id,
                20000,
                "Outros",
                f"{prev_year}-{prev_month:02d}-{prev_month_day:02d}",
                card_id,
            ),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, occurred_at, card_id)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?)""",
            (
                f"tx_{uuid.uuid4().hex}",
                user_id,
                30000,
                "Outros",
                f"{current_month}-{current_day:02d}",
                card_id,
            ),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, occurred_at)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 5000, "Pagamento Fatura", f"{current_month}-{current_day:02d}"),
        )
        conn.commit()
    finally:
        conn.close()

    snapshot = atlas._get_pri_month_opening_snapshot(phone)

    assert snapshot["expense_total_cents"] == 30000
    top_by_name = {item["name"]: item["total_cents"] for item in snapshot["top_categories"]}
    assert top_by_name["Outros"] == 20000
    assert top_by_name["Alimentacao"] == 10000


def test_month_summary_shows_card_purchase_but_separates_next_bill_cashflow(atlas):
    phone = "+5511944446666"
    user_id = f"user_{uuid.uuid4().hex}"
    card_id = f"card_{uuid.uuid4().hex}"
    now = atlas._now_br()
    current_month = now.strftime("%Y-%m")
    prev_year, prev_month = atlas._shift_year_month(now.year, now.month, -1)

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 100000),
        )
        cur.execute(
            """INSERT INTO credit_cards
               (id, user_id, name, closing_day, due_day, current_bill_opening_cents)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (card_id, user_id, "Caixa", 5, 15, 0),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 100000, "Salario", "Salario", f"{current_month}-01"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 10000, "Alimentacao", "Mercado", f"{current_month}-10"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at, card_id)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?, ?)""",
            (
                f"tx_{uuid.uuid4().hex}",
                user_id,
                20000,
                "Outros",
                "Fatura antiga",
                f"{prev_year}-{prev_month:02d}-20",
                card_id,
            ),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at, card_id)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?, ?)""",
            (
                f"tx_{uuid.uuid4().hex}",
                user_id,
                30000,
                "Outros",
                "Compra nova",
                f"{current_month}-10",
                card_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    summary = atlas.get_month_summary.entrypoint(phone, current_month, "ALL")

    assert "Compra nova" in summary
    assert "Comprado no mês" in summary
    assert "Peso no caixa" in summary
    summary_norm = atlas._normalize_pt_text(summary)
    assert "vai cair nas proximas faturas" in summary_norm
    assert "reconciliacao" in summary_norm
    assert "R$400,00" in summary
    assert "R$300,00" in summary
    assert "__insight:" not in summary


def test_save_transaction_expense_response_is_human_and_compact(atlas):
    phone = "+5511944400001"
    user_id = f"user_{uuid.uuid4().hex}"
    now = atlas._now_br()
    current_month = now.strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 300000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 300000, "Salario", "Empresa", f"{current_month}-01"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 1500, "Alimentacao", "Cafe", f"{current_month}-05"),
        )
        conn.commit()
    finally:
        conn.close()

    response = atlas.save_transaction.entrypoint(
        user_phone=phone,
        transaction_type="EXPENSE",
        amount=5,
        category="Alimentacao",
        merchant="almoco",
    )

    assert "✅" in response
    assert "Resumo da despesa" in response
    assert "Descricao: almoco" in response
    assert "Valor: R$5,00" in response or "Valor: R$5.00" in response
    assert "Status: pago" in response
    assert "Fechamento" not in response
    assert "Entradas:" not in response
    assert "Comprado" not in response
    assert "Peso no caixa:" not in response
    assert "Saldo" not in response
    assert "painel" in response.lower()


def test_save_transaction_card_purchase_mentions_next_bill_queue(atlas):
    phone = "+5511944400002"
    user_id = f"user_{uuid.uuid4().hex}"
    card_id = f"card_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 300000),
        )
        cur.execute(
            "INSERT INTO credit_cards (id, user_id, name, closing_day, due_day) VALUES (?, ?, ?, ?, ?)",
            (card_id, user_id, "Caixa", 5, 16),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 300000, "Salario", "Empresa", f"{atlas._now_br().strftime('%Y-%m')}-01"),
        )
        conn.commit()
    finally:
        conn.close()

    response = atlas.save_transaction.entrypoint(
        user_phone=phone,
        transaction_type="EXPENSE",
        amount=120,
        category="VestuÃ¡rio",
        merchant="Tenis",
        card_name="Caixa",
    )

    normalized = atlas._normalize_pt_text(response)
    assert "resumo da despesa" in normalized
    assert "compra: caixa" in normalized
    assert "1x" in normalized
    assert "status: a pagar" in normalized
    assert "proxima fatura" in normalized


def test_save_transaction_installments_returns_spaced_blocks_with_statuses(atlas):
    phone = "+5511944400019"
    user_id = f"user_{uuid.uuid4().hex}"
    card_id = f"card_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 300000),
        )
        cur.execute(
            "INSERT INTO credit_cards (id, user_id, name, closing_day, due_day) VALUES (?, ?, ?, ?, ?)",
            (card_id, user_id, "Caixa", 5, 16),
        )
        conn.commit()
    finally:
        conn.close()

    response = atlas.save_transaction.entrypoint(
        user_phone=phone,
        transaction_type="EXPENSE",
        amount=100,
        total_amount=300,
        installments=3,
        category="Vestuario",
        merchant="tenis",
        card_name="Caixa",
    )

    normalized = atlas._normalize_pt_text(response)
    assert "resumo das transacoes" in normalized
    assert normalized.count("descricao: tenis parcelado") == 3
    assert "compra: caixa" in normalized and "3x" in normalized
    assert "status: pago" in normalized
    assert "status: a pagar" in normalized


def test_save_transaction_repeated_merchant_does_not_add_pattern_microcopy(atlas):
    phone = "+5511944400003"
    user_id = f"user_{uuid.uuid4().hex}"
    current_month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 300000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 300000, "Salario", "Empresa", f"{current_month}-01"),
        )
        for day in ("02", "06"):
            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, category, merchant, occurred_at)
                   VALUES (?, ?, 'EXPENSE', ?, ?, ?, ?)""",
                (f"tx_{uuid.uuid4().hex}", user_id, 2500, "Alimentacao", "Deville", f"{current_month}-{day}"),
            )
        conn.commit()
    finally:
        conn.close()

    response = atlas.save_transaction.entrypoint(
        user_phone=phone,
        transaction_type="EXPENSE",
        amount=30,
        category="Alimentacao",
        merchant="Deville",
    )

    assert "Gasto guardado" in response
    assert "já apareceu 3x" not in response


def test_inline_multi_expense_returns_single_pri_batch_confirmation(atlas):
    phone = "+5511944400004"
    user_id = f"user_{uuid.uuid4().hex}"
    current_month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 300000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', ?, ?, ?, ?)""",
            (f"tx_{uuid.uuid4().hex}", user_id, 300000, "Salario", "Empresa", f"{current_month}-01"),
        )
        conn.commit()
    finally:
        conn.close()

    response = atlas._multi_expense_extract(phone, "gastei 30 na padaria e 25 no almoÃ§o")

    assert response is not None
    text = atlas._normalize_pt_text(response["response"])
    assert "confirmei suas despesas" in text
    assert "resumo da despesa" in text
    assert "status: pago" in text
    assert "padaria" in text
    assert "almo" in text
    assert "fechamento" not in text
    assert "total la" in text and "r$55,00" in text

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND type = 'EXPENSE'", (user_id,))
        assert cur.fetchone()[0] == 2
    finally:
        conn.close()


def test_compact_repeated_save_response_groups_concatenated_saves(atlas):
    raw = (
        "✨ Gasto guardado antes dele sumir no meio do dia.\n\n"
        "✅ *R$35.00 — padaria*\n"
        "🍽️ Alimentação • 16/03/2026 (hoje)\n"
        "_Errou? Digite *painel* pra editar ou apagar_\n\n"
        "✨ Gasto guardado antes dele sumir no meio do dia.\n\n"
        "✅ *R$22.00 — almoço*\n"
        "🍽️ Alimentação • 16/03/2026 (hoje)\n"
        "_Errou? Digite *painel* pra editar ou apagar_"
    )

    compacted = atlas._compact_repeated_save_response(raw)

    assert compacted.count("✨") == 1
    assert "padaria" in compacted.lower()
    assert "almoço" in compacted.lower()
    assert "Total lançado agora" in compacted
    assert compacted.count("Errou?") == 1


def test_strip_whatsapp_bold_removes_null_bytes_and_controls(atlas):
    cleaned = atlas._strip_whatsapp_bold("Oi\x00 mundo\x07 *forte*")

    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "**forte**" in cleaned


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
    assert "PRI" in stub_agent.calls[0]["input"].upper()
    assert "resumo completo" in stub_agent.calls[0]["input"].lower()

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
async def test_debt_and_no_reserve_reply_stays_structured_without_monthly_average(atlas, monkeypatch):
    phone = "+5511944443334"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Agora, me diz: alem dos cartoes, tem alguma divida ou emprestimo que nao aparece aqui? Tem reserva guardada?",
        open_question_key="debt_outside_cards",
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

    result = await atlas.chat_endpoint(user_phone=phone, message="tenho 1000 de divida no especial, e nao tenho reserva")

    content = result["content"].lower()
    assert "alerta vermelho" in content
    assert "zero reserva" in content
    assert "media mensal" not in content
    assert "gasto medio mensal" not in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["consultant_stage"] == "action_plan"
    assert state["open_question_key"] == "amount_followup"
    assert state["case_summary"]["main_issue_hypothesis"] == "high_interest_debt"
    assert state["case_summary"]["has_emergency_reserve"] == "no"


@pytest.mark.asyncio
async def test_combined_debt_and_reserve_reply_stays_structured_even_with_reserve_key(atlas, monkeypatch):
    phone = "+5511944443335"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Agora, me conta: tem alguma divida alem desses cartoes? Tem reserva guardada?",
        open_question_key="has_emergency_reserve",
        expected_answer_type="has_reserve",
        consultant_stage="reserve_check",
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

    result = await atlas.chat_endpoint(user_phone=phone, message="tenho 1000 de divida no especial, e nao tenho reserva")

    content = result["content"].lower()
    assert "alerta vermelho" in content
    assert "zero reserva" in content
    assert "media mensal" not in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "amount_followup"
    assert state["consultant_stage"] == "action_plan"
    assert state["case_summary"]["main_issue_hypothesis"] == "high_interest_debt"
    assert state["case_summary"]["debt_outside_cards"] == "yes"
    assert state["case_summary"]["has_emergency_reserve"] == "no"


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
async def test_explicit_pri_followup_stays_in_mentor_even_if_router_prefers_transaction(atlas, monkeypatch):
    phone = "+5511911112222"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Me diz: esse Outros ta tudo misturado ou voce sabe o que entrou ali?",
        open_question_key="category_other_breakdown",
        expected_answer_type="free_text",
        consultant_stage="diagnosis_clarification",
        case_summary={"main_issue_hypothesis": "cashflow_pressure"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent(
        [
            "Pri aqui. Entendi. Se esse Outros era fatura da Caixa que voce ja pagou, o problema nao e vazamento novo, e classificacao errada. Me confirma uma coisa: isso era pagamento de fatura ou compra no cartao?",
        ]
    )

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "update_transaction", "action": "update_transaction", "params": {"category": "Outros"}}

    async def _forbidden_execute(*_args, **_kwargs):
        raise AssertionError("Nao deveria executar rota transacional quando a mensagem comeca com 'pri'")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "_execute_intent", _forbidden_execute)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(
        user_phone=phone,
        message="pri essa categoria outros e uma fatura da caixa de cartao que eu paguei",
    )

    content = result["content"].lower()
    assert "classificacao errada" in content
    assert "?" in result["content"]
    assert len(stub_agent.calls) == 1


@pytest.mark.asyncio
async def test_pri_consulting_mode_blocks_write_route_for_context_reply_with_amount(atlas, monkeypatch):
    phone = "+5511911122233"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Esses R$2.000 em Outros de receita extra sao recorrentes ou foi algo pontual esse mes?",
        open_question_key="income_extra_recurrence",
        expected_answer_type="income_recurrence",
        consultant_stage="income_clarification",
        case_summary={"main_issue_hypothesis": "income_volatility"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent(
        [
            "Pri aqui. Entendi. Isso nao e renda recorrente, e alivio pontual. Entao eu nao montaria teu mes contando com esse valor de novo. Me diz: sem essa ajuda, quanto teu mes fica apertado?",
        ]
    )

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "transaction", "action": "save_transaction", "params": {"amount": 2000}}

    async def _forbidden_execute(*_args, **_kwargs):
        raise AssertionError("Nao deveria executar escrita durante consultoria da Pri")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "_execute_intent", _forbidden_execute)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(
        user_phone=phone,
        message="esses 2.000 e uma ajuda pra pagar o aluguel que minha irma me passou vai ate abril",
    )

    content = result["content"].lower()
    assert "alivio pontual" in content
    assert "nao montaria teu mes contando com esse valor" in content
    assert len(stub_agent.calls) == 1


@pytest.mark.asyncio
async def test_pending_action_is_ignored_during_pri_consulting_mode(atlas, monkeypatch):
    phone = "+5511911122244"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Voce consegue separar algum valor mensal pra essa reserva?",
        open_question_key="amount_followup",
        expected_answer_type="number_amount",
        consultant_stage="reserve_check",
        case_summary={"main_issue_hypothesis": "no_emergency_buffer"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent(
        [
            "Pri aqui. Fechou. Se nao sobra valor agora, antes de falar de reserva bonita a gente precisa abrir espaco no teu mes. Me diz: onde hoje voce sente mais desperdicio, em delivery ou em gastos misturados?",
        ]
    )

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        atlas,
        "_check_pending_action",
        lambda *_args, **_kwargs: {"response": "CONFIRMACAO ANTIGA"},
    )
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(user_phone=phone, message="nao separo valor")

    assert "CONFIRMACAO ANTIGA" not in result["content"]
    assert "delivery" in result["content"].lower()
    assert len(stub_agent.calls) == 0


@pytest.mark.asyncio
async def test_explicit_pri_message_skips_atlas_onboarding(atlas, monkeypatch):
    phone = "+5511911122255"
    stub_agent = _StubAtlasAgent(
        [
            "Pri aqui. Bora olhar isso juntas. Me conta qual parte do teu dinheiro mais esta te incomodando hoje?",
        ]
    )

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(
        atlas,
        "_onboard_if_new",
        lambda *_args, **_kwargs: {"response": "Oi! Sou o ATLAS, seu assistente financeiro."},
    )
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    monkeypatch.setattr(atlas, "_get_pri_opening_snapshot", lambda *_args, **_kwargs: {})

    result = await atlas.chat_endpoint(user_phone=phone, message="pri me ajuda")

    assert "atla" not in result["content"].lower()
    assert "pri aqui" in result["content"].lower()
    assert len(stub_agent.calls) == 1


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
async def test_open_text_followup_affirmative_keeps_invoice_breakdown_flow_without_llm(atlas, monkeypatch):
    phone = "+5511944442222"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Enquanto isso, me diz: voce tem como listar os maiores gastos que lembra dessa fatura?",
        open_question_key="open_text_followup",
        expected_answer_type="open_text",
        consultant_stage="diagnosis_clarification",
        case_summary={
            "main_issue_hypothesis": "cashflow_pressure",
            "notes": ["Categoria Outros citada pelo usuario: esta tudo misturado porque e uma fatura de cartao"],
        },
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

    result = await atlas.chat_endpoint(user_phone=phone, message="tenho sim")

    content = result["content"].lower()
    assert "3 maiores gastos" in content
    assert "fatura" in content
    assert "receita real" not in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "open_text_followup"
    assert state["consultant_stage"] == "diagnosis_clarification"


@pytest.mark.asyncio
async def test_open_text_followup_card_type_answer_stays_in_pri_without_llm(atlas, monkeypatch):
    phone = "+5511944443333"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Me diz, essa fatura Caixa e cartao de credito, emprestimo, ou algum tipo de financiamento?",
        open_question_key="open_text_followup",
        expected_answer_type="open_text",
        consultant_stage="diagnosis_clarification",
        case_summary={
            "main_issue_hypothesis": "cashflow_pressure",
            "notes": ["Categoria Outros citada pelo usuario: esta tudo misturado porque e uma fatura de cartao"],
        },
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent([])

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "transaction", "action": "save_transaction", "params": {"card_name": "Caixa"}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)

    result = await atlas.chat_endpoint(user_phone=phone, message="e cartao de credito")

    content = result["content"].lower()
    assert "cartao de credito" in content
    assert "o que mais pesa nessa fatura" in content
    assert "me diz o valor" not in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "open_text_followup"
    assert state["consultant_stage"] == "diagnosis_clarification"


@pytest.mark.asyncio
async def test_card_repayment_behavior_accepts_paguei_a_fatura_toda_without_llm(atlas, monkeypatch):
    phone = "+5511944445555"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Fechado. E no cartao: voce paga a fatura toda ou ta ficando no minimo/parcelando?",
        open_question_key="card_repayment_behavior",
        expected_answer_type="debt_status",
        consultant_stage="debt_mapping",
        case_summary={"main_issue_hypothesis": "cashflow_pressure", "has_emergency_reserve": "unknown"},
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

    result = await atlas.chat_endpoint(user_phone=phone, message="paguei a fatura toda")

    content = result["content"].lower()
    assert "pagar a fatura inteira" in content or "pagar a fatura inteira ja tira um risco grande" in content or "boa. pagar a fatura inteira" in content
    assert "alguma reserva" in content or "sem colchao de seguranca" in content
    assert "minimo/parcelando" not in content
    assert stub_agent.calls == []

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "has_emergency_reserve"
    assert state["consultant_stage"] == "reserve_check"
    assert state["case_summary"]["card_payment_behavior"] == "total"
    turns = state.get("memory_turns") or []
    assert any("paguei a fatura toda" in (turn.get("content") or "").lower() for turn in turns)
    assert any("alguma reserva" in (turn.get("content") or "").lower() or "colchao de seguranca" in (turn.get("content") or "").lower() for turn in turns)


@pytest.mark.asyncio
async def test_llm_repeated_question_is_recovered_by_pri_loop_guard(atlas, monkeypatch):
    phone = "+5511944446666"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Fechado. E no cartao: voce paga a fatura toda ou ta ficando no minimo/parcelando?",
        open_question_key="card_repayment_behavior",
        expected_answer_type="debt_status",
        consultant_stage="debt_mapping",
        case_summary={"main_issue_hypothesis": "cashflow_pressure", "has_emergency_reserve": "unknown"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )
    stub_agent = _StubAtlasAgent(
        [
            "Boa. Entao a pressao nao ta vindo de emprestimo por fora.\n\nAgora eu quero olhar o ponto mais perigoso seguinte: comportamento da fatura.\n\nFechado. E no cartao: voce paga a fatura toda ou ta ficando no minimo/parcelando?",
        ]
    )

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "mentor", "action": "", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", stub_agent)
    real_followup = atlas.build_structured_pri_followup

    def _fake_followup(user_message, question_key="", expected_answer_type="", case_summary=None, stage="", last_open_question=""):
        if user_message:
            return {}
        return real_followup(user_message, question_key, expected_answer_type, case_summary, stage, last_open_question)

    monkeypatch.setattr(atlas, "build_structured_pri_followup", _fake_followup)

    result = await atlas.chat_endpoint(user_phone=phone, message="paguei a fatura toda")

    content = result["content"].lower()
    assert "alguma reserva" in content or "colchao de seguranca" in content
    assert "ficando no minimo/parcelando" not in content
    assert len(stub_agent.calls) == 1

    state = atlas._load_mentor_state(phone)
    assert state is not None
    assert state["open_question_key"] == "has_emergency_reserve"
    assert state["consultant_stage"] == "reserve_check"


@pytest.mark.asyncio
async def test_explicit_pri_write_command_can_execute_even_during_mentor_session(atlas, monkeypatch):
    phone = "+5511944444444"
    atlas._save_mentor_state(
        phone,
        mode="mentor",
        last_open_question="Me diz uma coisa: esses R$5.357 em Outros voce ja sabe o que sao ou ta tudo misturado?",
        open_question_key="category_other_breakdown",
        expected_answer_type="free_text",
        consultant_stage="diagnosis_clarification",
        case_summary={"main_issue_hypothesis": "cashflow_pressure"},
        memory_turns=[],
        expires_at=atlas._mentor_expiry_iso(),
    )

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        assert body == "lanca 45 no ifood"
        return {"intent": "transaction", "action": "save_transaction", "params": {"amount": 45}}

    async def _fake_execute(route, user_phone: str, body: str, full_message: str):
        assert route["intent"] == "transaction"
        assert body == "lanca 45 no ifood"
        assert "pri lanca 45 no ifood" not in full_message.lower()
        return {"response": "Anotado! R$45,00 em iFood"}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "_execute_intent", _fake_execute)

    result = await atlas.chat_endpoint(user_phone=phone, message="pri lanca 45 no ifood")

    assert "anotado" in result["content"].lower()
    assert result["routed"] is True


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


def test_agent_runs_shortcut_groups_multi_expense_before_agent(atlas):
    phone = "+5511988887777"
    user_id = f"user_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        conn.commit()
    finally:
        conn.close()

    payload = atlas._build_agent_runs_shortcut_payload(
        user_phone=phone,
        session_id=phone,
        body_raw="gastei 35 na padaria e 22 no almoço",
    )

    assert payload is not None
    assert "R$35,00" in payload["content"]
    assert "R$22,00" in payload["content"]
    normalized = atlas._normalize_pt_text(payload["content"])
    assert "total la" in normalized and "r$57,00" in normalized


def test_pr1_schema_adds_merchant_intelligence_columns_and_alias_table(atlas):
    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(transactions)")
        cols = {row[1] for row in cur.fetchall()}
        assert "merchant_raw" in cols
        assert "merchant_canonical" in cols
        assert "merchant_type" in cols

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='merchant_aliases'")
        row = cur.fetchone()
        assert row is not None
    finally:
        conn.close()


def test_pr1_backfills_merchant_raw_and_canonical_from_legacy_merchant(atlas):
    phone = "+5511977700001"
    user_id = f"user_{uuid.uuid4().hex}"
    tx_id = f"tx_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3500, 'Alimentação', 'Mercado Deville', '', '', '2026-03-10T12:00:00')""",
            (tx_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Reexecuta init para disparar backfill de compatibilidade.
    atlas._init_sqlite_tables()

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT merchant, merchant_raw, merchant_canonical FROM transactions WHERE id = ?",
            (tx_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Mercado Deville"
        assert row[1] == "Mercado Deville"
        assert row[2] == "Mercado Deville"
    finally:
        conn.close()


def test_pr2_save_transaction_populates_canonical_merchant(atlas):
    phone = "+5511977700002"

    atlas._call(
        atlas.save_transaction,
        phone,
        "EXPENSE",
        35.0,
        "Alimentação",
        "compra supermercado deville",
    )

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT merchant, merchant_raw, merchant_canonical, merchant_type
               FROM transactions
               ORDER BY created_at DESC
               LIMIT 1"""
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "compra supermercado deville"
        assert row[1] == "compra supermercado deville"
        assert row[2] == "deville"
        assert row[3] in {"mercado", "unknown"}
    finally:
        conn.close()


def test_pr2_get_transactions_by_merchant_matches_canonical_field(atlas):
    phone = "+5511977700003"
    user_id = f"user_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 4200, 'Alimentação', 'compra sv dvl', 'compra sv dvl', 'deville', 'mercado', '2026-03-11T12:00:00')""",
            (str(uuid.uuid4()), user_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_transactions_by_merchant, phone, "deville", "2026-03")
    normalized = atlas._normalize_pt_text(result)
    assert "nenhuma transacao encontrada" not in normalized
    assert "gasto total" in normalized


@pytest.mark.asyncio
async def test_chat_endpoint_groups_multi_expense_before_router(atlas, monkeypatch):
    phone = "+5511988887766"
    user_id = f"user_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para lote claro de gastos")

    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)

    result = await atlas.chat_endpoint(user_phone=phone, message="gastei 35 na padaria e 22 no almoço")

    assert result["routed"] is True
    assert "R$35,00" in result["content"]
    assert "R$22,00" in result["content"]
    normalized = atlas._normalize_pt_text(result["content"])
    assert "total la" in normalized and "r$57,00" in normalized
    assert result["content"].count("Errou?") == 1


@pytest.mark.asyncio
async def test_query_detalhar_mes_forces_full_month_transactions(atlas, monkeypatch):
    phone = "+5511911112222"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3500, 'Alimentação', 'Padaria', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "query", "action": "month_summary", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="detalhar mes")

    content = result["content"].lower()
    assert ("extrato de" in content) or ("detalhamento de" in content)
    assert (month in result["content"]) or ("Mar/2026" in result["content"])


@pytest.mark.asyncio
async def test_query_mes_com_categoria_forces_category_breakdown(atlas, monkeypatch):
    phone = "+5511911113333"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 4200, 'Alimentação', 'Restaurante', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-11T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _fake_mini_route(body: str, user_phone: str, in_mentor: bool):
        return {"intent": "query", "action": "month_summary", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="quanto gastei este mes com alimentacao")

    content = atlas._normalize_pt_text(result["content"])
    assert "alimentacao" in content
    assert "total" in content


@pytest.mark.asyncio
async def test_chat_endpoint_hard_routes_detalhar_mes_before_mini_router(atlas, monkeypatch):
    phone = "+5511911114444"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3500, 'Alimentação', 'Padaria', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para 'detalhar mês'")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="detalhar mês")

    content = result["content"].lower()
    assert ("extrato de" in content) or ("detalhamento de" in content)
    assert (month in result["content"]) or ("Mar/2026" in result["content"])


@pytest.mark.asyncio
async def test_chat_endpoint_hard_routes_month_category_before_mini_router(atlas, monkeypatch):
    phone = "+5511911115555"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 4200, 'Alimentação', 'Restaurante', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-11T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para consulta mês+categoria")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="quanto gastei este mês com alimentação")

    content = atlas._normalize_pt_text(result["content"])
    assert "alimentacao" in content
    assert "total" in content


@pytest.mark.asyncio
async def test_chat_endpoint_hard_routes_detalhar_gastos_mes_before_mini_router(atlas, monkeypatch):
    phone = "+5511911115566"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', 10000, 'Freelance', 'Uber', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T10:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3500, 'Alimentação', 'Padaria', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para 'detalhar gastos do mês'")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="detalhar gastos do mês")

    content = atlas._normalize_pt_text(result["content"])
    assert "detalhamento de gastos" in content
    assert "saidas" in content
    assert "entradas" not in content


@pytest.mark.asyncio
async def test_chat_endpoint_hard_routes_detalhar_quanto_recebi_last7_before_mini_router(atlas, monkeypatch):
    phone = "+5511911115577"
    user_id = f"user_{uuid.uuid4().hex}"
    now = atlas._now_br()

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        d1 = now.strftime("%Y-%m-%d")
        d2 = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', 4200, 'Freelance', '99', ?)""",
            (str(uuid.uuid4()), user_id, f"{d1}T11:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'INCOME', 3800, 'Freelance', 'Uber', ?)""",
            (str(uuid.uuid4()), user_id, f"{d2}T13:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para 'detalhar quanto recebi'")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="detalhar quanto recebi nos últimos 7 dias")

    content = atlas._normalize_pt_text(result["content"])
    assert "detalhamento de entradas" in content
    assert "entradas" in content
    assert "r$42,00" in content or "r$38,00" in content


@pytest.mark.asyncio
async def test_period_overview_today_expense_includes_categories_payment_mode_insight_and_panel(atlas, monkeypatch):
    phone = "+5511911115588"
    user_id = f"user_{uuid.uuid4().hex}"
    today = atlas._now_br().strftime("%Y-%m-%d")
    card_id = str(uuid.uuid4())

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            "INSERT INTO credit_cards (id, user_id, name, closing_day, due_day, limit_cents, available_limit_cents) VALUES (?, ?, ?, 5, 16, 500000, 500000)",
            (card_id, user_id, "Caixa"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at, payment_method)
               VALUES (?, ?, 'EXPENSE', 3500, 'Alimentação', 'Padaria', ?, 'CASH')""",
            (str(uuid.uuid4()), user_id, f"{today}T10:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at, payment_method, card_id)
               VALUES (?, ?, 'EXPENSE', 2200, 'Alimentação', 'Almoço', ?, 'CREDIT', ?)""",
            (str(uuid.uuid4()), user_id, f"{today}T12:00:00", card_id),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    async def _fake_mini_route(*_args, **_kwargs):
        return {"intent": "unknown", "action": "unknown", "params": {}}
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))
    monkeypatch.setattr(atlas, "get_panel_url", lambda _p: "https://render.exemplo/painel")

    result = await atlas.chat_endpoint(user_phone=phone, message="me fale quanto gastei hoje")
    content = atlas._normalize_pt_text(result["content"])

    assert "resumo de gastos em hoje" in content
    assert "fechamento do dia" in content
    assert "gastos por categoria (dia)" in content
    assert "alimentacao" in content
    assert "cartao caixa" in content
    assert "a vista" in content
    assert "impacto no caixa hoje" in content
    assert "vai para proximas faturas" in content
    assert "r$35,00" in content
    assert "media por dia" not in content
    assert ("alerta direto" in content) or ("ponto de atencao" in content) or ("ritmo de gasto" in content)
    assert "render.exemplo/painel" in content


@pytest.mark.asyncio
async def test_period_overview_mostra_gastos_de_hoje_does_not_fall_back_to_month(atlas, monkeypatch):
    phone = "+5511911115599"
    user_id = f"user_{uuid.uuid4().hex}"
    today = atlas._now_br().strftime("%Y-%m-%d")
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 8800, 'Alimentação', 'Herbalife', ?)""",
            (str(uuid.uuid4()), user_id, f"{today}T09:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 999999, 'Moradia', 'Aluguel', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-01T09:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    async def _fake_mini_route(*_args, **_kwargs):
        return {"intent": "unknown", "action": "unknown", "params": {}}
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="mostre os gastos de hoje")
    content = atlas._normalize_pt_text(result["content"])

    assert "hoje" in content
    assert "r$88,00" in content
    assert "r$9.999,99" not in content


@pytest.mark.asyncio
async def test_period_overview_detalhar_gastos_semana_grouped_by_category_with_lines(atlas, monkeypatch):
    phone = "+5511911115601"
    user_id = f"user_{uuid.uuid4().hex}"
    today = atlas._now_br().strftime("%Y-%m-%d")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at, payment_method)
               VALUES (?, ?, 'EXPENSE', 3500, 'Alimentação', 'Padaria', ?, 'CASH')""",
            (str(uuid.uuid4()), user_id, f"{today}T10:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at, payment_method)
               VALUES (?, ?, 'EXPENSE', 2400, 'Saúde', 'Farmácia', ?, 'CASH')""",
            (str(uuid.uuid4()), user_id, f"{today}T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)

    async def _fake_mini_route(*_args, **_kwargs):
        return {"intent": "unknown", "action": "unknown", "params": {}}

    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="detalhar gastos da semana")
    content = atlas._normalize_pt_text(result["content"])

    assert "detalhamento de gastos (semana" in content
    assert "gastos por categoria" in content
    assert "alimentacao" in content
    assert "saude" in content
    assert "padaria" in content
    assert "farmacia" in content
    assert "— alimentacao • padaria" not in content


@pytest.mark.asyncio
async def test_period_overview_ver_mais_expands_specific_category(atlas, monkeypatch):
    phone = "+5511911115602"
    user_id = f"user_{uuid.uuid4().hex}"
    now = atlas._now_br()

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        for i in range(6):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, category, merchant, occurred_at, payment_method)
                   VALUES (?, ?, 'EXPENSE', ?, 'Alimentação', ?, ?, 'CASH')""",
                (str(uuid.uuid4()), user_id, 1000 + i, f"Mercado {i+1}", f"{d}T10:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)

    async def _fake_mini_route(*_args, **_kwargs):
        return {"intent": "unknown", "action": "unknown", "params": {}}

    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    base = await atlas.chat_endpoint(user_phone=phone, message="quanto gastei nos últimos 7 dias")
    base_content = atlas._normalize_pt_text(base["content"])
    assert "ver mais alimentacao" in base_content
    assert "mercado 6" not in base_content

    expanded = await atlas.chat_endpoint(user_phone=phone, message="ver mais alimentacao")
    expanded_content = atlas._normalize_pt_text(expanded["content"])
    assert "mercado 6" in expanded_content
def test_pr5_category_breakdown_shows_safe_compare_without_previous_base(atlas):
    phone = "+5511911119991"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, occurred_at)
               VALUES (?, ?, 'EXPENSE', 4200, 'Alimentação', 'Restaurante Talentos', 'Restaurante Talentos', 'talentos', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-11T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_category_breakdown, phone, "Alimentação", month)
    normalized = atlas._normalize_pt_text(result)
    assert "ticket medio" in normalized
    assert "sem base suficiente para comparar" in normalized


def test_pr5_category_breakdown_compares_when_previous_month_exists(atlas):
    phone = "+5511911119992"
    user_id = f"user_{uuid.uuid4().hex}"
    now = atlas._now_br()
    month = now.strftime("%Y-%m")
    prev_y, prev_m = atlas._shift_year_month(now.year, now.month, -1)
    prev_month = f"{prev_y}-{prev_m:02d}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, occurred_at)
               VALUES (?, ?, 'EXPENSE', 6000, 'Alimentação', 'Restaurante Talentos', 'Restaurante Talentos', 'talentos', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-11T12:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3000, 'Alimentação', 'Restaurante Talentos', 'Restaurante Talentos', 'talentos', ?)""",
            (str(uuid.uuid4()), user_id, f"{prev_month}-11T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_category_breakdown, phone, "Alimentação", month)
    normalized = atlas._normalize_pt_text(result)
    assert "vs" in normalized


def test_pr5_category_breakdown_groups_merchant_variations_and_lists_all(atlas):
    phone = "+5511911119993"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        variants = [
            ("Supermercado Deville", "supermercado deville", 5000),
            ("compra supermercado deville", "compra supermercado deville", 7000),
            ("Mercado Deville", "mercado deville", 3000),
            ("Restaurante Talentos", "restaurante talentos", 2000),
        ]
        for merchant, canonical, amount in variants:
            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, occurred_at)
                   VALUES (?, ?, 'EXPENSE', ?, 'Alimentação', ?, ?, ?, ?)""",
                (str(uuid.uuid4()), user_id, amount, merchant, merchant, canonical, f"{month}-11T12:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_category_breakdown, phone, "Alimentação", month)
    normalized = atlas._normalize_pt_text(result)
    assert "onde mais pesou (todos)" in normalized
    assert "deville" in normalized
    assert "supermercado deville" not in normalized
    assert "compra supermercado deville" not in normalized
    assert "restaurante talentos" in normalized
    assert "reconciliacao" in normalized
    assert "diferenca: r$0,00" in normalized


def test_pr3_get_spend_by_merchant_type_month(atlas):
    phone = "+5511911116666"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 5000, 'Alimentação', 'Mercado Deville', 'Mercado Deville', 'deville', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-08T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_spend_by_merchant_type, phone, "mercado", "month", month)
    normalized = atlas._normalize_pt_text(result)
    assert "gasto com mercado" in normalized
    assert "total" in normalized
    assert "reconciliacao" in normalized


def test_pr3_get_spend_by_merchant_type_lists_all_merchants(atlas):
    phone = "+5511911116670"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        merchants = [
            ("Supermercado Deville", 5000),
            ("Mercado de Ville", 4000),
            ("Atacadão Centro", 3000),
            ("Hortifruti Bairro", 2000),
        ]
        for merchant, amount in merchants:
            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
                   VALUES (?, ?, 'EXPENSE', ?, 'Alimentação', ?, ?, ?, 'mercado', ?)""",
                (str(uuid.uuid4()), user_id, amount, merchant, merchant, merchant.lower(), f"{month}-10T12:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_spend_by_merchant_type, phone, "mercado", "month", month)
    normalized = atlas._normalize_pt_text(result)
    assert "onde mais pesou (todos)" in normalized
    assert "supermercado deville" in normalized
    assert "mercado de ville" in normalized
    assert "atacadao centro" in normalized
    assert "hortifruti bairro" in normalized


def test_pr3_get_spend_by_merchant_type_groups_name_variations(atlas):
    phone = "+5511911116671"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        variants = [
            ("Supermercado Deville", "supermercado deville", 5000),
            ("compra supermercado deville", "compra supermercado deville", 7000),
            ("Mercado Deville", "mercado deville", 3000),
        ]
        for merchant, canonical, amount in variants:
            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
                   VALUES (?, ?, 'EXPENSE', ?, 'Alimentação', ?, ?, ?, 'mercado', ?)""",
                (str(uuid.uuid4()), user_id, amount, merchant, merchant, canonical, f"{month}-10T12:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_spend_by_merchant_type, phone, "mercado", "month", month)
    normalized = atlas._normalize_pt_text(result)
    # as variações devem virar um único agrupamento "deville"
    assert "deville" in normalized
    assert "supermercado deville" not in normalized
    assert "compra supermercado deville" not in normalized


def test_pr3_get_spend_by_merchant_type_uses_fallback_when_type_missing(atlas):
    phone = "+5511911116667"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 7000, 'Alimentação', 'Mercado Deville', 'Mercado Deville', 'deville', '', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-16T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_spend_by_merchant_type, phone, "mercado", "week", "")
    normalized = atlas._normalize_pt_text(result)
    assert "nenhum gasto de *mercado*" not in normalized
    assert "total" in normalized


def test_pr4_type_query_shows_no_comparison_when_no_previous_base(atlas):
    phone = "+5511911116668"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 4500, 'Alimentação', 'Mercado Novo', 'Mercado Novo', 'mercado novo', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_spend_by_merchant_type, phone, "mercado", "month", month)
    normalized = atlas._normalize_pt_text(result)
    assert "sem base suficiente para comparar" in normalized


def test_pr4_type_query_compares_when_previous_base_exists(atlas):
    phone = "+5511911116669"
    user_id = f"user_{uuid.uuid4().hex}"
    now = atlas._now_br()
    month = now.strftime("%Y-%m")
    prev_y, prev_m = atlas._shift_year_month(now.year, now.month, -1)
    prev_month = f"{prev_y}-{prev_m:02d}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 5000, 'Alimentação', 'Mercado Deville', 'Mercado Deville', 'deville', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T12:00:00"),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3000, 'Alimentação', 'Mercado Deville', 'Mercado Deville', 'deville', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{prev_month}-10T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    result = atlas._call(atlas.get_spend_by_merchant_type, phone, "mercado", "month", month)
    normalized = atlas._normalize_pt_text(result)
    assert "vs" in normalized
    assert "subiu" in normalized or "caiu" in normalized


@pytest.mark.asyncio
async def test_chat_endpoint_hard_routes_merchant_type_query_before_mini_router(atlas, monkeypatch):
    phone = "+5511911117777"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 6200, 'Alimentação', 'Supermercado', 'Supermercado', 'deville', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-12T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para consulta por tipo de merchant")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="quanto gastei de mercado este mes")

    content = atlas._normalize_pt_text(result["content"])
    assert "gasto com mercado" in content
    assert "total" in content


@pytest.mark.asyncio
async def test_chat_endpoint_hard_routes_specific_merchant_query_before_mini_router(atlas, monkeypatch):
    phone = "+5511911118888"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 4100, 'Alimentação', 'Restaurante Talentos', 'Restaurante Talentos', 'talentos', 'restaurante', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-13T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para consulta por merchant específico")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="quanto gastei no talentos")

    content = atlas._normalize_pt_text(result["content"])
    assert "gasto total" in content


@pytest.mark.asyncio
async def test_transaction_intent_recebi_uber_is_saved_as_income(atlas, monkeypatch):
    phone = "+5511911118896"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        conn.commit()
    finally:
        conn.close()

    async def _fake_mini_route(*_args, **_kwargs):
        return {"intent": "transaction", "action": "save_transaction", "params": {}}

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _fake_mini_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="Recebi 35.16 uber")
    content = atlas._normalize_pt_text(result["content"])
    assert "resumo da entrada" in content
    assert "categoria: freelance" in content

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT type, category, amount_cents, occurred_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "INCOME"
        assert row[1] == "Freelance"
        assert row[2] == 3516
        assert (row[3] or "").startswith(month)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_pr6_chat_endpoint_hard_routes_alias_command_before_mini_router(atlas, monkeypatch):
    phone = "+5511911118891"
    user_id = f"user_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para comando de alias")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(
        user_phone=phone,
        message="compra supermercado deville e mercado deville sao deville",
    )
    content = atlas._normalize_pt_text(result["content"])
    assert "alias salvo" in content


@pytest.mark.asyncio
async def test_pr6_chat_endpoint_hard_routes_type_command_before_mini_router(atlas, monkeypatch):
    phone = "+5511911118892"
    user_id = f"user_{uuid.uuid4().hex}"

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar para comando de tipo")

    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="talentos e restaurante")
    content = atlas._normalize_pt_text(result["content"])
    assert "tipo atualizado para" in content
    assert "restaurante" in content


def test_pr6_set_merchant_alias_updates_history(atlas):
    phone = "+5511911118893"
    user_id = f"user_{uuid.uuid4().hex}"
    tx_id = str(uuid.uuid4())

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, merchant_canonical, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 5000, 'Alimentação', 'compra supermercado deville', 'compra supermercado deville', 'compra supermercado deville', '', '2026-03-17T12:00:00')""",
            (tx_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()

    out = atlas._call(atlas.set_merchant_alias, phone, "compra supermercado deville", "deville", "mercado")
    assert "Alias salvo" in out

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT merchant_canonical, merchant_type FROM transactions WHERE id = ?", (tx_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "deville"
        assert row[1] == "mercado"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_pr9_feature_flag_off_falls_back_to_category_query(atlas, monkeypatch):
    phone = "+5511911118894"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, occurred_at)
               VALUES (?, ?, 'EXPENSE', 3800, 'Alimentação', 'Mercado Deville', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-10T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    async def _should_not_route(*_args, **_kwargs):
        raise AssertionError("mini-router não deveria rodar no hard-route de categoria")

    monkeypatch.setattr(atlas, "MERCHANT_INTEL_ENABLED", False)
    monkeypatch.setattr(atlas, "_onboard_if_new", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_check_pending_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(atlas, "_mini_route", _should_not_route)
    monkeypatch.setattr(atlas, "atlas_agent", _StubAtlasAgent([]))

    result = await atlas.chat_endpoint(user_phone=phone, message="quanto gastei de mercado este mes")
    content = atlas._normalize_pt_text(result["content"])
    assert "alimentacao" in content


def test_infer_merchant_type_marketplace_is_ecommerce(atlas):
    inferred = atlas._infer_merchant_type("Mercado Livre", "mercado livre", "Outros")
    assert inferred == "ecommerce"


def test_market_query_excludes_mercado_livre_even_if_legacy_tagged_mercado(atlas):
    phone = "+5511911118895"
    user_id = f"user_{uuid.uuid4().hex}"
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        # Histórico antigo, classificado errado como mercado (deve ser excluído da consulta de mercado)
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 243600, 'Outros', 'Mercado Livre', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-06T12:00:00"),
        )
        # Mercado real
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_type, occurred_at)
               VALUES (?, ?, 'EXPENSE', 6541, 'Alimentacao', 'Supermercado Deville', 'mercado', ?)""",
            (str(uuid.uuid4()), user_id, f"{month}-07T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    out = atlas.get_spend_by_merchant_type.entrypoint(phone, "mercado", "month", month)
    assert "Supermercado Deville" in out
    assert "Mercado Livre" not in out


def test_category_expansion_detects_cuidados_pessoais(atlas):
    category = atlas._categorize_merchant_text("cabeleireiro do bairro")
    assert atlas._normalize_pt_text(category) == "cuidados pessoais"


def test_recategorize_history_dry_run_does_not_persist(atlas):
    phone = "+5511911118896"
    user_id = f"user_{uuid.uuid4().hex}"
    tx_id = str(uuid.uuid4())
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, occurred_at)
               VALUES (?, ?, 'EXPENSE', 7000, 'Outros', 'cabeleireiro', 'cabeleireiro', ?)""",
            (tx_id, user_id, f"{month}-12T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    out = atlas._call(atlas.recategorize_transactions_history, phone, "dry-run", "Outros", month, 0, 100)
    normalized = atlas._normalize_pt_text(out)
    assert "dry-run" in normalized
    assert "cuidados pessoais" in normalized
    assert "candidatas para mudanca: 1" in normalized

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT category FROM transactions WHERE id = ?", (tx_id,))
        row = cur.fetchone()
        assert row is not None
        assert atlas._normalize_pt_text(row[0]) == "outros"
    finally:
        conn.close()


def test_recategorize_history_apply_persists(atlas):
    phone = "+5511911118897"
    user_id = f"user_{uuid.uuid4().hex}"
    tx_id = str(uuid.uuid4())
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, occurred_at)
               VALUES (?, ?, 'EXPENSE', 9000, 'Outros', 'barbearia centro', 'barbearia centro', ?)""",
            (tx_id, user_id, f"{month}-13T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_recategorize_history_apply_without_executemany_fallback(atlas, monkeypatch):
    phone = "+5511911118898"
    user_id = f"user_{uuid.uuid4().hex}"
    tx_id = str(uuid.uuid4())
    month = atlas._now_br().strftime("%Y-%m")

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, phone, "Rodrigo Teste", 1200000),
        )
        cur.execute(
            """INSERT INTO transactions
               (id, user_id, type, amount_cents, category, merchant, merchant_raw, occurred_at)
               VALUES (?, ?, 'EXPENSE', 9000, 'Outros', 'barbearia premium', 'barbearia premium', ?)""",
            (tx_id, user_id, f"{month}-14T12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    class _CursorNoExecutemany:
        def __init__(self, real):
            self._real = real
            self.rowcount = 0

        def execute(self, *args, **kwargs):
            out = self._real.execute(*args, **kwargs)
            self.rowcount = getattr(self._real, "rowcount", 0)
            return out

        def fetchall(self):
            return self._real.fetchall()

        def fetchone(self):
            return self._real.fetchone()

    class _ConnWrap:
        def __init__(self, real):
            self._real = real

        def cursor(self):
            return _CursorNoExecutemany(self._real.cursor())

        def commit(self):
            return self._real.commit()

        def close(self):
            return self._real.close()

    real_get_conn = atlas._get_conn

    def _wrapped_conn():
        return _ConnWrap(real_get_conn())

    monkeypatch.setattr(atlas, "_get_conn", _wrapped_conn)

    out = atlas._call(atlas.recategorize_transactions_history, phone, "apply", "Outros", month, 0, 100)
    normalized = atlas._normalize_pt_text(out)
    assert "aplicada" in normalized
    assert "transacoes atualizadas" in normalized

    conn = atlas._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT category FROM transactions WHERE id = ?", (tx_id,))
        row = cur.fetchone()
        assert row is not None
        assert atlas._normalize_pt_text(row[0]) == "cuidados pessoais"
    finally:
        conn.close()


