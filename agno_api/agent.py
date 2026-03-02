# ============================================================
# agno_api/agent.py — ATLAS Agno Agents + AgentOS
# ============================================================
# Agentes:
#   atlas        — conversacional (UI / testes)
#   parse_agent  — retorna JSON estruturado (n8n pipeline)
#   response_agent — gera resposta PT-BR (n8n pipeline)
#
# Banco:
#   LOCAL      → SQLite  (DATABASE_URL não definida)
#   PRODUÇÃO   → PostgreSQL no Render (DATABASE_URL definida)
# ============================================================

import os
import sqlite3
import uuid
import calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.decorator import tool
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

# ============================================================
# BANCO — SQLite local ou PostgreSQL no Render
# ============================================================

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip() or None

if DATABASE_URL:
    from agno.db.postgres import PostgresDb
    db = PostgresDb(db_url=DATABASE_URL)
    DB_TYPE = "postgres"
else:
    from agno.db.sqlite import SqliteDb
    Path("data").mkdir(exist_ok=True)
    db = SqliteDb(db_file="data/atlas.db")
    DB_TYPE = "sqlite"

print(f"[ATLAS] Banco: {DB_TYPE}")

# ============================================================
# TABELAS FINANCEIRAS — criadas automaticamente no SQLite
# (No PostgreSQL do Render, rodar o script SQL uma vez)
# ============================================================

def _init_sqlite_tables():
    """Cria as tabelas financeiras no SQLite se não existirem."""
    conn = sqlite3.connect("data/atlas.db")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            monthly_income_cents INTEGER DEFAULT 0,
            salary_day INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            total_amount_cents INTEGER DEFAULT 0,
            installments INTEGER DEFAULT 1,
            installment_number INTEGER DEFAULT 1,
            category TEXT NOT NULL,
            merchant TEXT,
            payment_method TEXT,
            notes TEXT,
            occurred_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS financial_goals (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            target_amount_cents INTEGER NOT NULL,
            current_amount_cents INTEGER DEFAULT 0,
            is_emergency_fund INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS credit_cards (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            closing_day INTEGER NOT NULL,
            due_day INTEGER NOT NULL,
            limit_cents INTEGER DEFAULT 0,
            current_bill_opening_cents INTEGER DEFAULT 0,
            last_bill_paid_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recurring_transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            category TEXT NOT NULL,
            merchant TEXT DEFAULT '',
            card_id TEXT DEFAULT NULL,
            day_of_month INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS card_bill_snapshots (
            id TEXT PRIMARY KEY,
            card_id TEXT NOT NULL,
            bill_month TEXT NOT NULL,
            opening_cents INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(card_id, bill_month)
        );
    """)
    conn.commit()
    # Migrations
    for migration in [
        "ALTER TABLE users ADD COLUMN salary_day INTEGER DEFAULT 0",
        "ALTER TABLE transactions ADD COLUMN card_id TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass
    conn.close()

if DB_TYPE == "sqlite":
    _init_sqlite_tables()


def _init_postgres_tables():
    """Cria as tabelas financeiras no PostgreSQL se não existirem."""
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            monthly_income_cents INTEGER DEFAULT 0,
            salary_day INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            total_amount_cents INTEGER DEFAULT 0,
            installments INTEGER DEFAULT 1,
            installment_number INTEGER DEFAULT 1,
            category TEXT NOT NULL,
            merchant TEXT,
            payment_method TEXT,
            notes TEXT,
            occurred_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS financial_goals (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            target_amount_cents INTEGER NOT NULL,
            current_amount_cents INTEGER DEFAULT 0,
            is_emergency_fund INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS credit_cards (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            closing_day INTEGER NOT NULL,
            due_day INTEGER NOT NULL,
            limit_cents INTEGER DEFAULT 0,
            current_bill_opening_cents INTEGER DEFAULT 0,
            last_bill_paid_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recurring_transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            category TEXT NOT NULL,
            merchant TEXT DEFAULT '',
            card_id TEXT DEFAULT NULL,
            day_of_month INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_bill_snapshots (
            id TEXT PRIMARY KEY,
            card_id TEXT NOT NULL,
            bill_month TEXT NOT NULL,
            opening_cents INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(card_id, bill_month)
        )
    """)
    # Migrations
    for migration in [
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS card_id TEXT DEFAULT NULL",
    ]:
        try:
            cur.execute(migration)
        except Exception:
            pass
    conn.commit()
    cur.close()
    conn.close()


if DB_TYPE == "postgres":
    _init_postgres_tables()

# ============================================================
# MODELOS
# ============================================================

def get_model():
    return OpenAIChat(id="gpt-4.1-mini", api_key=os.getenv("OPENAI_API_KEY"))

def get_fast_model():
    return OpenAIChat(id="gpt-4.1-mini", api_key=os.getenv("OPENAI_API_KEY"))

# ============================================================
# TOOLS FINANCEIRAS — leitura/escrita no banco
# ============================================================

class _PGCursor:
    """Cursor wrapper que converte placeholders ? → %s para PostgreSQL."""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("?", "%s"), params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PGConn:
    """Connection wrapper que retorna cursors adaptados para PostgreSQL."""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _PGCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _get_conn():
    if DB_TYPE == "sqlite":
        return sqlite3.connect("data/atlas.db")
    import psycopg2
    return _PGConn(psycopg2.connect(DATABASE_URL))


@tool
def save_transaction(
    user_phone: str,
    transaction_type: str,
    amount: float,
    category: str,
    merchant: str = "",
    payment_method: str = "",
    notes: str = "",
    installments: int = 1,
    total_amount: float = 0,
    card_name: str = "",
) -> str:
    """
    Salva uma transação financeira no banco de dados.
    transaction_type: EXPENSE ou INCOME
    amount: valor da PARCELA em reais (se à vista = valor total).
            Ex: "gastei 45" → amount=45, "R$1.200" → amount=1200
    installments: número de parcelas (1 = à vista)
    total_amount: valor TOTAL da compra em reais (preencher se parcelado)
    card_name: nome do cartão de crédito se usado (ex: "Nubank"). Deixar vazio para débito/PIX/dinheiro.

    Categorias EXPENSE: Alimentação | Transporte | Moradia | Saúde | Lazer |
                        Educação | Assinaturas | Vestuário | Investimento | Outros
    Categorias INCOME:  Salário | Freelance | Aluguel Recebido |
                        Investimentos | Benefício | Venda | Outros

    Exemplos:
    - "gastei 45 no iFood" → amount=45, installments=1
    - "paguei 120 no mercado" → amount=120, installments=1
    - "tênis 1200 em 12x no Nubank" → amount=100, installments=12, total_amount=1200, card_name="Nubank"
    - "notebook 3000 em 6x no Inter" → amount=500, installments=6, total_amount=3000, card_name="Inter"
    """
    # converter reais → centavos
    amount_cents = round(amount * 100)
    total_amount_cents = round(total_amount * 100)

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        user_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO users (id, phone, name) VALUES (?, ?, ?)",
            (user_id, user_phone, "Usuário"),
        )
    else:
        user_id = row[0]

    # se parcelado e total não informado, calcula
    if installments > 1 and total_amount_cents == 0:
        total_amount_cents = amount_cents * installments

    # Resolve card_id
    card_id = None
    if card_name:
        card = _find_card(cur, user_id, card_name)
        if card:
            card_id = card[0]
            if not payment_method:
                payment_method = "CREDIT"

    tx_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    cur.execute(
        """INSERT INTO transactions
           (id, user_id, type, amount_cents, total_amount_cents, installments, installment_number,
            category, merchant, payment_method, notes, occurred_at, card_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tx_id, user_id, transaction_type, amount_cents, total_amount_cents,
         installments, 1, category, merchant, payment_method, notes, now, card_id),
    )
    conn.commit()
    conn.close()

    if installments > 1:
        parcela = f"R${amount_cents/100:.2f}/mês"
        total = f"R${total_amount_cents/100:.2f} total"
        return f"Transação salva: {parcela} × {installments}x ({total}) em {category}{' (' + merchant + ')' if merchant else ''}."

    valor = f"R${amount_cents/100:.2f}"
    return f"Transação salva: {valor} em {category}{' (' + merchant + ')' if merchant else ''}."


@tool
def get_month_summary(user_phone: str, month: str = "") -> str:
    """
    Retorna resumo financeiro do mês. month no formato YYYY-MM (ex: 2026-03).
    Se não informado, usa o mês atual.
    """
    if not month:
        month = datetime.now().strftime("%Y-%m")

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma transação encontrada. Comece registrando um gasto!"

    user_id = row[0]

    cur.execute(
        """SELECT type, category, SUM(amount_cents) as total, COUNT(*) as qtd
           FROM transactions
           WHERE user_id = ? AND occurred_at LIKE ?
           GROUP BY type, category
           ORDER BY total DESC""",
        (user_id, f"{month}%"),
    )
    rows = cur.fetchall()

    # Check if there's data from any month before the requested month
    cur.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND occurred_at < ?",
        (user_id, f"{month}-01"),
    )
    has_previous_data = cur.fetchone()[0] > 0
    conn.close()

    if not rows:
        return f"Nenhuma transação em {month}."

    income = sum(r[2] for r in rows if r[0] == "INCOME")
    expenses = sum(r[2] for r in rows if r[0] == "EXPENSE")
    balance = income - expenses

    lines = [f"📊 Resumo {month} | has_previous_data={has_previous_data}"]
    lines.append(f"💰 Receitas: R${income/100:.2f}")
    lines.append(f"💸 Gastos:   R${expenses/100:.2f}")
    lines.append(f"{'✅' if balance >= 0 else '⚠️'} Saldo:    R${balance/100:.2f}")

    income_rows = [(r[1], r[2], r[3]) for r in rows if r[0] == "INCOME"]
    if income_rows:
        lines.append("\nFontes de renda:")
        for cat, total, qtd in sorted(income_rows, key=lambda x: -x[1]):
            lines.append(f"  💚 {cat}: R${total/100:.2f}")

    expense_rows = [(r[1], r[2], r[3]) for r in rows if r[0] == "EXPENSE"]
    if expense_rows:
        lines.append("\nGastos por categoria:")
        for cat, total, qtd in sorted(expense_rows, key=lambda x: -x[1]):
            lines.append(f"  • {cat}: R${total/100:.2f} ({qtd}x)")

    return "\n".join(lines)


@tool
def get_user(user_phone: str) -> str:
    """
    Retorna dados do usuário. Use SEMPRE na primeira mensagem de cada conversa.
    Retorna: is_new, name, has_income, monthly_income, transaction_count.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, monthly_income_cents, salary_day FROM users WHERE phone = ?",
        (user_phone,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "is_new=True | name=None | has_income=False | monthly_income=0 | transaction_count=0 | salary_day=0"

    user_id, name, income, salary_day = row
    cur.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (user_id,))
    count = cur.fetchone()[0]
    conn.close()

    is_new = name == "Usuário"
    has_income = (income or 0) > 0
    return (
        f"is_new={is_new} | name={name} | has_income={has_income} "
        f"| monthly_income=R${(income or 0)/100:.2f} | transaction_count={count}"
        f" | salary_day={salary_day or 0}"
    )


@tool
def update_user_name(user_phone: str, name: str) -> str:
    """Salva o nome do usuário coletado no onboarding."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        user_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO users (id, phone, name) VALUES (?, ?, ?)",
            (user_id, user_phone, name),
        )
    else:
        cur.execute("UPDATE users SET name = ? WHERE phone = ?", (name, user_phone))
    conn.commit()
    conn.close()
    return f"Nome '{name}' salvo com sucesso."


@tool
def update_user_income(user_phone: str, monthly_income: float) -> str:
    """
    Salva a renda mensal do usuário em reais.
    Exemplo: R$3.500 → monthly_income=3500
    """
    monthly_income_cents = round(monthly_income * 100)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        user_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO users (id, phone, name, monthly_income_cents) VALUES (?, ?, ?, ?)",
            (user_id, user_phone, "Usuário", monthly_income_cents),
        )
    else:
        cur.execute(
            "UPDATE users SET monthly_income_cents = ? WHERE phone = ?",
            (monthly_income_cents, user_phone),
        )
    conn.commit()
    conn.close()
    return f"Renda mensal de R${monthly_income_cents/100:.2f} salva com sucesso."


@tool
def get_installments_summary(user_phone: str) -> str:
    """
    Lista todas as compras parceladas ativas com compromisso total restante.
    Útil para entender o total de dívida no cartão.
    """
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Nenhum dado encontrado."

    cur.execute(
        """SELECT merchant, category, amount_cents, total_amount_cents,
                  installments, occurred_at
           FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND installments > 1
           ORDER BY occurred_at DESC""",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Nenhuma compra parcelada registrada."

    total_monthly = 0
    total_commitment = 0
    lines = ["💳 Compras parceladas:"]

    for merchant, category, parcela, total, n_parcelas, occurred_at in rows:
        purchase_month = occurred_at[:7]
        current_month = datetime.now().strftime("%Y-%m")

        # meses desde a compra
        py, pm = map(int, purchase_month.split("-"))
        cy, cm = map(int, current_month.split("-"))
        months_elapsed = (cy - py) * 12 + (cm - pm)
        parcelas_pagas = min(months_elapsed + 1, n_parcelas)
        parcelas_restantes = max(n_parcelas - parcelas_pagas, 0)
        restante = parcela * parcelas_restantes

        if parcelas_restantes == 0:
            continue  # quitada

        nome = merchant or category
        total_monthly += parcela
        total_commitment += restante
        lines.append(
            f"\n  🛍️ {nome} ({category})"
            f"\n     R${parcela/100:.2f}/mês × {parcelas_restantes} parcelas restantes"
            f"\n     Restante: R${restante/100:.2f} de R${total/100:.2f} total"
        )

    if total_monthly == 0:
        return "Nenhuma parcela ativa no momento."

    lines.append(f"\n💸 Total comprometido/mês: R${total_monthly/100:.2f}")
    lines.append(f"🔒 Compromisso total restante: R${total_commitment/100:.2f}")
    return "\n".join(lines)


@tool
def get_last_transaction(user_phone: str) -> str:
    """
    Retorna a última transação registrada pelo usuário.
    Use antes de update_last_transaction para confirmar o que será corrigido.
    """
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Nenhuma transação encontrada."

    cur.execute(
        """SELECT id, type, amount_cents, total_amount_cents, installments,
                  category, merchant, payment_method, occurred_at
           FROM transactions
           WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return "Nenhuma transação encontrada."

    tx_id, type_, amount, total, inst, cat, merchant, method, occurred = row
    parcel_info = f" | {inst}x (total R${total/100:.2f})" if inst and inst > 1 else ""
    merchant_info = f" | {merchant}" if merchant else ""
    method_info = f" | {method}" if method else ""

    return (
        f"id={tx_id} | tipo={type_} | valor=R${amount/100:.2f}{parcel_info}"
        f" | categoria={cat}{merchant_info}{method_info} | data={occurred[:10]}"
    )


@tool
def update_last_transaction(
    user_phone: str,
    installments: int = 0,
    payment_method: str = "",
    category: str = "",
    amount: float = 0,
    merchant: str = "",
) -> str:
    """
    Corrige a última transação registrada.
    Para corrigir parcelamento: passe APENAS installments (ex: installments=10).
    Para corrigir valor: passe APENAS amount com o valor TOTAL em reais (ex: amount=150).
    Para corrigir merchant/local: passe merchant (ex: merchant="Magazine Luiza").
    Para corrigir outros campos: passe payment_method ou category.
    """
    try:
        conn = _get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
        user_row = cur.fetchone()
        if not user_row:
            conn.close()
            return "ERRO: usuário não encontrado."
        user_id = user_row[0]

        cur.execute(
            """SELECT id, amount_cents, total_amount_cents, installments
               FROM transactions WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return "ERRO: nenhuma transação encontrada."

        amount_cents = round(amount * 100)

        tx_id, curr_amount, curr_total, curr_inst = row
        curr_total = curr_total or 0
        base_total = curr_total if curr_total > 0 else curr_amount
        if amount_cents > 0:
            base_total = amount_cents

        fields = {}
        if installments > 0:
            fields["installments"] = installments
            fields["installment_number"] = 1
            fields["total_amount_cents"] = base_total
            fields["amount_cents"] = base_total // installments
        elif amount_cents > 0:
            fields["total_amount_cents"] = amount_cents
            fields["amount_cents"] = amount_cents

        if payment_method:
            fields["payment_method"] = payment_method
        if category:
            fields["category"] = category
        if merchant:
            fields["merchant"] = merchant

        if not fields:
            conn.close()
            return "Nenhuma alteração informada."

        set_clause = ", ".join(f"{col} = ?" for col in fields)
        cur.execute(
            f"UPDATE transactions SET {set_clause} WHERE id = ?",
            list(fields.values()) + [tx_id],
        )
        conn.commit()
        conn.close()

        parts = []
        if installments > 0:
            parts.append(f"{installments}x de R${(base_total // installments)/100:.2f} (R${base_total/100:.2f} total)")
        elif amount_cents > 0:
            parts.append(f"valor: R${amount:.2f}")
        if payment_method:
            parts.append(f"pagamento: {payment_method}")
        if category:
            parts.append(f"categoria: {category}")
        if merchant:
            parts.append(f"local: {merchant}")

        return f"OK — corrigido: {' | '.join(parts)}."

    except Exception as e:
        return f"ERRO: {str(e)}"


@tool
def get_today_total(user_phone: str) -> str:
    """Retorna o total gasto hoje."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum gasto registrado hoje ainda."

    user_id = row[0]
    cur.execute(
        """SELECT category, merchant, amount_cents FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at LIKE ?
           ORDER BY occurred_at DESC""",
        (user_id, f"{today}%"),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Nenhum gasto registrado hoje ainda."

    total = sum(r[2] for r in rows)
    items = []
    for cat, merchant, amount in rows:
        label = merchant if merchant else cat
        items.append(f"R${amount/100:.2f} em {label}")

    return f"Hoje: R${total/100:.2f} — {' | '.join(items)}"


@tool
def get_transactions(user_phone: str, date: str = "", month: str = "") -> str:
    """
    Lista transações individuais com merchant, valor e categoria.
    date: data específica no formato YYYY-MM-DD (ex: hoje = data atual)
    month: mês no formato YYYY-MM (ex: 2026-03)
    Se nenhum informado, usa hoje.
    """
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma transação encontrada."

    user_id = row[0]

    if month:
        prefix = month
        label = month
    elif date:
        prefix = date
        label = date
    else:
        prefix = datetime.now().strftime("%Y-%m-%d")
        label = "hoje"

    cur.execute(
        """SELECT type, amount_cents, category, merchant, occurred_at
           FROM transactions
           WHERE user_id = ? AND occurred_at LIKE ?
           ORDER BY occurred_at DESC""",
        (user_id, f"{prefix}%"),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return f"Nenhuma transação em {label}."

    lines = [f"📋 Transações de {label}:"]
    for r in rows:
        tipo = "💰" if r[0] == "INCOME" else "💸"
        merchant_str = f" ({r[3]})" if r[3] else ""
        hora = r[4][11:16] if len(r[4]) >= 16 else ""
        hora_str = f" às {hora}" if hora else ""
        lines.append(f"  {tipo} R${r[1]/100:.2f} — {r[2]}{merchant_str}{hora_str}")

    return "\n".join(lines)


@tool
def get_category_breakdown(user_phone: str, category: str, month: str = "") -> str:
    """
    Mostra todas as transações de uma categoria específica com detalhe de merchant.
    Responde perguntas como "onde gastei em Alimentação?", "quais restaurantes fui esse mês?"
    category: ex. "Alimentação", "Transporte", "Saúde"
    month: YYYY-MM (padrão = mês atual)
    """
    if not month:
        month = datetime.now().strftime("%Y-%m")

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return f"Nenhuma transação em {category}."
    user_id = row[0]

    # individual transactions
    cur.execute(
        """SELECT merchant, amount_cents, occurred_at
           FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND category = ? AND occurred_at LIKE ?
           ORDER BY occurred_at DESC""",
        (user_id, category, f"{month}%"),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return f"Nenhuma transação em {category} em {month}."

    total = sum(r[1] for r in rows)
    lines = [f"🔍 {category} em {month} — R${total/100:.2f} total ({len(rows)} transações):"]

    # group by merchant
    merchants: dict[str, int] = {}
    for merchant, amount, _ in rows:
        key = merchant or "Sem nome"
        merchants[key] = merchants.get(key, 0) + amount

    for m, amt in sorted(merchants.items(), key=lambda x: -x[1]):
        pct = amt / total * 100
        lines.append(f"  • {m}: R${amt/100:.2f} ({pct:.0f}%)")

    return "\n".join(lines)


# ============================================================
# HELPERS — cartões e recorrentes
# ============================================================

def _get_user_id(cur, user_phone: str):
    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    return row[0] if row else None


def _find_card(cur, user_id: str, card_name: str):
    """Busca cartão por nome (case-insensitive, parcial)."""
    cur.execute("SELECT id, name, closing_day, due_day, limit_cents, current_bill_opening_cents, last_bill_paid_at FROM credit_cards WHERE user_id = ?", (user_id,))
    cards = cur.fetchall()
    name_lower = card_name.lower()
    for card in cards:
        if name_lower in card[1].lower() or card[1].lower() in name_lower:
            return card
    return None


def _bill_period_start(closing_day: int) -> str:
    """Calcula a data de início do período de fatura atual."""
    today = datetime.now()
    if today.day >= closing_day:
        start = today.replace(day=closing_day, hour=0, minute=0, second=0, microsecond=0)
    else:
        # Mês anterior
        if today.month == 1:
            start = today.replace(year=today.year - 1, month=12, day=closing_day)
        else:
            start = today.replace(month=today.month - 1, day=closing_day)
    return start.isoformat()


@tool
def register_card(
    user_phone: str,
    name: str,
    closing_day: int,
    due_day: int,
    limit: float = 0,
    current_bill: float = 0,
) -> str:
    """
    Cadastra um cartão de crédito do usuário.
    name: nome do cartão (ex: "Nubank", "Inter", "Bradesco")
    closing_day: dia do fechamento da fatura (1-31)
    due_day: dia do vencimento (1-31)
    limit: limite total em reais (ex: 10000)
    current_bill: fatura já acumulada ANTES de começar a rastrear, em reais (ex: 2000)
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "ERRO: usuário não encontrado."

    # Verifica se já existe
    existing = _find_card(cur, user_id, name)
    if existing:
        # Atualiza
        cur.execute(
            """UPDATE credit_cards SET closing_day=?, due_day=?, limit_cents=?, current_bill_opening_cents=? WHERE id=?""",
            (closing_day, due_day, round(limit * 100), round(current_bill * 100), existing[0])
        )
        conn.commit()
        conn.close()
        return f"Cartão {existing[1]} atualizado. Fecha dia {closing_day}, vence dia {due_day}, limite R${limit:.0f}."

    card_id = str(uuid.uuid4())
    cur.execute(
        """INSERT INTO credit_cards (id, user_id, name, closing_day, due_day, limit_cents, current_bill_opening_cents)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (card_id, user_id, name, closing_day, due_day, round(limit * 100), round(current_bill * 100))
    )
    conn.commit()
    conn.close()

    bill_str = f" | Fatura atual: R${current_bill:.0f}" if current_bill > 0 else ""
    return f"Cartão {name} cadastrado! Fecha dia {closing_day}, vence dia {due_day}, limite R${limit:.0f}{bill_str}."


@tool
def get_cards(user_phone: str) -> str:
    """
    Lista todos os cartões do usuário com fatura atual e limite disponível.
    Use quando o usuário perguntar sobre faturas, cartões ou limite disponível.
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Nenhum cartão cadastrado."

    cur.execute(
        "SELECT id, name, closing_day, due_day, limit_cents, current_bill_opening_cents, last_bill_paid_at FROM credit_cards WHERE user_id = ?",
        (user_id,)
    )
    cards = cur.fetchall()

    if not cards:
        conn.close()
        return "Nenhum cartão cadastrado. Use register_card para adicionar."

    today = datetime.now()
    lines = [f"💳 Seus cartões ({today.strftime('%d/%m/%Y')}):"]
    for card_id, name, closing_day, due_day, limit_cents, opening_cents, last_paid in cards:
        # Calcula período da fatura atual
        period_start = _bill_period_start(closing_day)
        if last_paid and last_paid > period_start:
            period_start = last_paid

        cur.execute(
            """SELECT SUM(amount_cents) FROM transactions
               WHERE user_id = ? AND card_id = ? AND occurred_at >= ?""",
            (user_id, card_id, period_start)
        )
        row = cur.fetchone()

        new_purchases = row[0] or 0
        bill_total = (opening_cents or 0) + new_purchases
        available = (limit_cents or 0) - bill_total

        # Dias para fechar/vencer
        if today.day < closing_day:
            days_to_close = closing_day - today.day
        else:
            # Próximo mês
            days_to_close = (30 - today.day) + closing_day

        limit_str = f" | Limite: R${limit_cents/100:.0f}" if limit_cents else ""
        avail_str = f" | Disponível: R${available/100:.0f}" if limit_cents else ""
        lines.append(
            f"\n💳 {name}\n"
            f"   Fatura: R${bill_total/100:.2f} (fecha em {days_to_close} dias — dia {closing_day}){limit_str}{avail_str}\n"
            f"   Vencimento: dia {due_day}"
        )

    conn.close()
    return "\n".join(lines)


@tool
def close_bill(user_phone: str, card_name: str) -> str:
    """
    Registra o pagamento da fatura do cartão — zera a fatura atual.
    Chamar quando o usuário disser "paguei a fatura do X".
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "ERRO: usuário não encontrado."

    card = _find_card(cur, user_id, card_name)
    if not card:
        conn.close()
        return f"Cartão '{card_name}' não encontrado. Verifique o nome com get_cards."

    cur.execute(
        "UPDATE credit_cards SET current_bill_opening_cents=0, last_bill_paid_at=? WHERE id=?",
        (datetime.now().isoformat(), card[0])
    )
    conn.commit()
    conn.close()
    return f"Fatura do {card[1]} zerada! Novo ciclo iniciado."


@tool
def register_recurring(
    user_phone: str,
    name: str,
    amount: float,
    category: str,
    day_of_month: int,
    merchant: str = "",
    card_name: str = "",
) -> str:
    """
    Cadastra um gasto fixo/recorrente mensal.
    name: nome do gasto (ex: "Aluguel", "Parcela Carro", "Netflix")
    amount: valor em reais
    category: Moradia | Transporte | Assinaturas | Saúde | Educação | Outros
    day_of_month: dia do mês que vence ou é debitado (1-31)
    merchant: estabelecimento (opcional)
    card_name: nome do cartão se for no crédito (opcional, ex: "Nubank")
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "ERRO: usuário não encontrado."

    card_id = None
    if card_name:
        card = _find_card(cur, user_id, card_name)
        if card:
            card_id = card[0]

    # Verifica se já existe com esse nome
    cur.execute("SELECT id FROM recurring_transactions WHERE user_id = ? AND LOWER(name) = LOWER(?)", (user_id, name))
    existing = cur.fetchone()
    if existing:
        cur.execute(
            "UPDATE recurring_transactions SET amount_cents=?, category=?, merchant=?, card_id=?, day_of_month=?, active=1 WHERE id=?",
            (round(amount * 100), category, merchant, card_id, day_of_month, existing[0])
        )
        conn.commit()
        conn.close()
        return f"Gasto fixo '{name}' atualizado: R${amount:.0f} todo dia {day_of_month}."

    rec_id = str(uuid.uuid4())
    cur.execute(
        """INSERT INTO recurring_transactions (id, user_id, name, amount_cents, category, merchant, card_id, day_of_month)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (rec_id, user_id, name, round(amount * 100), category, merchant, card_id, day_of_month)
    )
    conn.commit()
    conn.close()

    card_str = f" no {card_name}" if card_name else ""
    return f"Gasto fixo cadastrado: {name} — R${amount:.0f} todo dia {day_of_month}{card_str}."


@tool
def get_recurring(user_phone: str) -> str:
    """
    Lista todos os gastos fixos/recorrentes cadastrados com total mensal.
    Use quando o usuário perguntar sobre gastos fixos, compromissos mensais ou contas fixas.
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Nenhum gasto fixo cadastrado."

    cur.execute(
        """SELECT r.name, r.amount_cents, r.category, r.day_of_month, r.merchant, c.name
           FROM recurring_transactions r
           LEFT JOIN credit_cards c ON r.card_id = c.id
           WHERE r.user_id = ? AND r.active = 1
           ORDER BY r.day_of_month""",
        (user_id,)
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Nenhum gasto fixo cadastrado. Use register_recurring para adicionar."

    total = sum(r[1] for r in rows)
    today = datetime.now().day
    lines = [f"📋 Gastos fixos mensais — Total: R${total/100:.2f}"]
    for name, amount, category, day, merchant, card_name in rows:
        paid = "✅" if day < today else "⏳"
        card_str = f" ({card_name})" if card_name else ""
        merch_str = f" — {merchant}" if merchant else ""
        lines.append(f"  {paid} Dia {day:02d}: {name}{merch_str} — R${amount/100:.2f} [{category}]{card_str}")

    return "\n".join(lines)


@tool
def deactivate_recurring(user_phone: str, name: str) -> str:
    """
    Desativa um gasto fixo (quando o usuário cancelou uma assinatura, quitou parcela, etc).
    name: nome do gasto a desativar (parcial, case-insensitive)
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "ERRO: usuário não encontrado."

    cur.execute(
        "SELECT id, name FROM recurring_transactions WHERE user_id = ? AND active = 1 AND LOWER(name) LIKE LOWER(?)",
        (user_id, f"%{name}%")
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return f"Gasto fixo '{name}' não encontrado."

    cur.execute("UPDATE recurring_transactions SET active = 0 WHERE id = ?", (row[0],))
    conn.commit()
    conn.close()
    return f"'{row[1]}' desativado dos gastos fixos."


@tool
def set_future_bill(
    user_phone: str,
    card_name: str,
    bill_month: str,
    amount: float,
) -> str:
    """
    Registra o saldo pré-existente de uma fatura futura do cartão.
    Usar quando o usuário informar compromissos já existentes antes de adotar o ATLAS.

    card_name: nome do cartão (ex: "Nubank")
    bill_month: mês da fatura no formato YYYY-MM (ex: "2026-04")
    amount: valor já comprometido naquela fatura em reais (ex: 400)

    Exemplos de fala do usuário:
    - "minha fatura de abril no Nubank já está em 400" → bill_month="2026-04", amount=400
    - "em maio tenho 150 no Inter" → bill_month="2026-05", amount=150
    - "Nubank: março 500, abril 400, maio 150" → chamar 3x, uma por mês
    """
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Usuário não encontrado."

    card = _find_card(cur, user_id, card_name)
    if not card:
        conn.close()
        return f"Cartão '{card_name}' não encontrado. Cadastre primeiro com register_card."

    card_id = card[0]
    amount_cents = round(amount * 100)
    snapshot_id = str(uuid.uuid4())

    # INSERT OR REPLACE para permitir atualização
    if DB_TYPE == "sqlite":
        cur.execute(
            """INSERT OR REPLACE INTO card_bill_snapshots (id, card_id, bill_month, opening_cents)
               VALUES (
                 COALESCE((SELECT id FROM card_bill_snapshots WHERE card_id=? AND bill_month=?), ?),
                 ?, ?, ?
               )""",
            (card_id, bill_month, snapshot_id, card_id, bill_month, amount_cents)
        )
    else:
        cur.execute(
            """INSERT INTO card_bill_snapshots (id, card_id, bill_month, opening_cents)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (card_id, bill_month) DO UPDATE SET opening_cents = EXCLUDED.opening_cents""",
            (snapshot_id, card_id, bill_month, amount_cents)
        )

    conn.commit()
    conn.close()

    month_label = bill_month
    try:
        dt = datetime.strptime(bill_month, "%Y-%m")
        months_pt = ["", "jan", "fev", "mar", "abr", "mai", "jun",
                     "jul", "ago", "set", "out", "nov", "dez"]
        month_label = f"{months_pt[dt.month]}/{dt.year}"
    except Exception:
        pass

    return f"Registrado: fatura de {month_label} do {card[1]} — R${amount:.2f} de compromisso pré-existente."


@tool
def get_next_bill(user_phone: str, card_name: str) -> str:
    """
    Estima a próxima fatura do cartão com base em:
    1. Parcelas de compras anteriores que caem no próximo ciclo
    2. Gastos fixos recorrentes vinculados a esse cartão
    Use quando o usuário perguntar "quanto vai ser minha próxima fatura do X?",
    "o que vai cair no próximo mês no cartão?", "próxima fatura do Nubank".
    """
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Usuário não encontrado."

    card = _find_card(cur, user_id, card_name)
    if not card:
        conn.close()
        return f"Cartão '{card_name}' não encontrado. Use get_cards para ver seus cartões."

    card_id, name, closing_day, due_day, limit_cents, opening_cents, last_paid = card

    today = datetime.now()

    # Parcelas ativas vinculadas a este cartão
    cur.execute(
        """SELECT merchant, category, amount_cents, installments, occurred_at
           FROM transactions
           WHERE user_id = ? AND card_id = ? AND type = 'EXPENSE' AND installments > 1
           ORDER BY occurred_at""",
        (user_id, card_id)
    )
    installment_rows = cur.fetchall()

    # Gastos fixos vinculados a este cartão
    cur.execute(
        """SELECT name, amount_cents, category, day_of_month
           FROM recurring_transactions
           WHERE user_id = ? AND card_id = ? AND active = 1""",
        (user_id, card_id)
    )
    recurring_rows = cur.fetchall()

    # Snapshots de faturas futuras pré-existentes (registrados com set_future_bill)
    # Próximo mês
    if today.month == 12:
        next_month = f"{today.year + 1}-01"
    else:
        next_month = f"{today.year}-{today.month + 1:02d}"

    cur.execute(
        "SELECT opening_cents FROM card_bill_snapshots WHERE card_id = ? AND bill_month = ?",
        (card_id, next_month)
    )
    snapshot_row = cur.fetchone()
    snapshot_cents = snapshot_row[0] if snapshot_row else 0

    conn.close()

    # Dias até fechamento do PRÓXIMO ciclo
    if today.day < closing_day:
        days_to_close = closing_day - today.day
    else:
        days_to_close = (30 - today.day) + closing_day

    # Calcular parcelas que caem no próximo ciclo
    installment_items = []
    total_installments = 0

    for merchant, category, parcela, n_parcelas, occurred_at in installment_rows:
        purchase_date = datetime.fromisoformat(occurred_at[:19])
        py, pm = purchase_date.year, purchase_date.month
        cy, cm = today.year, today.month
        months_elapsed = (cy - py) * 12 + (cm - pm)

        current_inst = months_elapsed + 1
        next_inst = current_inst + 1

        if next_inst <= n_parcelas:
            parcelas_restantes = n_parcelas - next_inst
            nome = merchant or category
            installment_items.append((nome, parcela, next_inst, n_parcelas, parcelas_restantes))
            total_installments += parcela

    total_recurring = sum(r[1] for r in recurring_rows)
    total_next = snapshot_cents + total_installments + total_recurring

    lines = [f"📅 Próxima fatura estimada — {name} ({next_month})"]
    lines.append(f"   Fecha em ~{days_to_close} dias (dia {closing_day}) • Vence dia {due_day}")
    lines.append("")

    if snapshot_cents > 0:
        lines.append(f"📌 Compromissos anteriores ao ATLAS: R${snapshot_cents/100:.2f}")

    if not installment_items and not recurring_rows and snapshot_cents == 0:
        lines.append("Nenhuma parcela ou gasto fixo programado para a próxima fatura.")
        return "\n".join(lines)

    if installment_items:
        if snapshot_cents > 0:
            lines.append("")
        lines.append("💳 Parcelas:")
        for nome, parcela, inst_num, total_inst, restantes in installment_items:
            suffix = f" — ainda faltam {restantes} depois" if restantes > 0 else " — última parcela! 🎉"
            lines.append(f"  • {nome}: R${parcela/100:.2f} ({inst_num}/{total_inst}){suffix}")

    if recurring_rows:
        if installment_items or snapshot_cents > 0:
            lines.append("")
        lines.append("📋 Gastos fixos no cartão:")
        for rec_name, rec_amount, rec_cat, rec_day in recurring_rows:
            lines.append(f"  • {rec_name}: R${rec_amount/100:.2f} (dia {rec_day})")

    lines.append("")
    lines.append(f"💰 Total estimado: R${total_next/100:.2f}")

    if limit_cents and total_next > 0:
        available = limit_cents - total_next
        lines.append(f"📊 Limite disponível após: R${available/100:.0f}")

    return "\n".join(lines)


@tool
def get_month_comparison(user_phone: str) -> str:
    """
    Compara o mês atual com o mês anterior por categoria.
    Ideal para resumo mensal com contexto e evolução.
    """
    now = datetime.now()
    current_month = now.strftime("%Y-%m")

    # mês anterior
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum dado encontrado."
    user_id = row[0]

    def fetch_totals(month: str) -> dict:
        cur.execute(
            """SELECT type, category, SUM(amount_cents)
               FROM transactions
               WHERE user_id = ? AND occurred_at LIKE ?
               GROUP BY type, category""",
            (user_id, f"{month}%"),
        )
        result: dict = {"INCOME": {}, "EXPENSE": {}}
        for type_, cat, total in cur.fetchall():
            result[type_][cat] = total
        return result

    curr = fetch_totals(current_month)
    prev = fetch_totals(prev_month)
    conn.close()

    curr_expenses = curr["EXPENSE"]
    prev_expenses = prev["EXPENSE"]
    curr_income   = sum(curr["INCOME"].values())
    curr_total    = sum(curr_expenses.values())
    prev_total    = sum(prev_expenses.values())

    lines = [f"📊 Comparativo {prev_month} → {current_month}"]
    lines.append(f"💸 Gastos: R${curr_total/100:.2f}", )
    if prev_total:
        diff = curr_total - prev_total
        sinal = "+" if diff >= 0 else ""
        lines.append(f"   vs mês anterior: {sinal}R${diff/100:.2f} ({sinal}{diff/prev_total*100:.0f}%)")
    if curr_income:
        lines.append(f"💰 Receitas: R${curr_income/100:.2f}")

    # categorias com variação relevante
    all_cats = set(curr_expenses) | set(prev_expenses)
    alertas = []
    for cat in all_cats:
        c = curr_expenses.get(cat, 0)
        p = prev_expenses.get(cat, 0)
        if p > 0 and c > p * 1.3:
            pct = (c - p) / p * 100
            alertas.append(f"  ⚠️  {cat}: R${c/100:.2f} (+{pct:.0f}% vs mês passado)")
        elif c > 0 and p == 0:
            alertas.append(f"  🆕 {cat}: R${c/100:.2f} (novo este mês)")

    if alertas:
        lines.append("\n🔔 Categorias em alta:")
        lines.extend(alertas)

    lines.append("\nPor categoria (mês atual):")
    for cat, val in sorted(curr_expenses.items(), key=lambda x: -x[1]):
        prev_val = prev_expenses.get(cat, 0)
        arrow = " ↑" if val > prev_val else (" ↓" if val < prev_val and prev_val else "")
        lines.append(f"  • {cat}: R${val/100:.2f}{arrow}")

    return "\n".join(lines)


@tool
def get_week_summary(user_phone: str) -> str:
    """
    Resumo e alertas da semana atual (segunda a hoje).
    Detecta categorias com gasto acima do ritmo esperado para o mês.
    """
    today = datetime.now()
    # início da semana (segunda-feira)
    start_of_week = today.strftime("%Y-%m-%d")
    days_since_monday = today.weekday()  # 0 = segunda
    if days_since_monday > 0:
        from datetime import timedelta
        start_of_week = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")

    current_month = today.strftime("%Y-%m")
    days_in_month = 30  # aproximação

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum dado encontrado."
    user_id = row[0]

    # gastos da semana
    cur.execute(
        """SELECT category, SUM(amount_cents), COUNT(*)
           FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at >= ?
           GROUP BY category ORDER BY SUM(amount_cents) DESC""",
        (user_id, f"{start_of_week}T00:00:00"),
    )
    week_rows = cur.fetchall()

    # média diária do mês para comparar
    cur.execute(
        """SELECT category, SUM(amount_cents)
           FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at LIKE ?
           GROUP BY category""",
        (user_id, f"{current_month}%"),
    )
    month_rows = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()

    if not week_rows:
        return "Nenhum gasto registrado essa semana ainda."

    week_total = sum(r[1] for r in week_rows)
    days_elapsed = days_since_monday + 1  # dias desde segunda incluindo hoje

    lines = [f"📅 Semana atual ({start_of_week} → hoje)"]
    lines.append(f"💸 Total: R${week_total/100:.2f} em {days_elapsed} dia{'s' if days_elapsed > 1 else ''}")
    lines.append("")

    alertas = []
    for cat, week_val, qtd in week_rows:
        month_val = month_rows.get(cat, 0)
        daily_avg = month_val / days_in_month if month_val else 0
        expected_week = daily_avg * 7
        lines.append(f"  • {cat}: R${week_val/100:.2f} ({qtd}x)")
        if expected_week > 0 and week_val > expected_week * 1.4:
            alertas.append(f"  ⚠️  {cat}: no ritmo de R${week_val / days_elapsed * 30 / 100:.0f}/mês (acima da média)")

    if alertas:
        lines.append("\n🔔 Alertas:")
        lines.extend(alertas)

    return "\n".join(lines)


@tool
def can_i_buy(user_phone: str, amount: float, description: str = "") -> str:
    """
    Analisa se o usuário pode fazer uma compra.
    amount: valor da compra em reais (ex: R$250 → amount=250)
    description: o que é a compra (ex: "tênis", "jantar fora", "notebook")
    """
    amount_cents = round(amount * 100)
    today = datetime.now()
    current_month = today.strftime("%Y-%m")
    days_in_month = 30
    days_elapsed = today.day
    days_remaining = max(days_in_month - days_elapsed, 1)

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, monthly_income_cents FROM users WHERE phone = ?",
        (user_phone,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Usuário não encontrado. Comece registrando um gasto!"

    user_id, income_static = row
    income_static = income_static or 0

    # receitas reais registradas no mês (prioridade sobre campo estático)
    cur.execute(
        """SELECT SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'INCOME' AND occurred_at LIKE ?""",
        (user_id, f"{current_month}%"),
    )
    income_real = cur.fetchone()[0] or 0
    cur.execute(
        """SELECT DISTINCT category FROM transactions
           WHERE user_id = ? AND type = 'INCOME' AND occurred_at LIKE ?""",
        (user_id, f"{current_month}%"),
    )
    income_sources = ", ".join(r[0] for r in cur.fetchall())

    # usa receita real se disponível, senão fallback para campo estático
    income_cents = income_real if income_real > 0 else income_static

    # gastos do mês atual
    cur.execute(
        """SELECT SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at LIKE ?""",
        (user_id, f"{current_month}%"),
    )
    expenses_cents = cur.fetchone()[0] or 0

    # parcelas de meses anteriores que ainda estão ativas (comprometimento futuro/mês)
    cur.execute(
        """SELECT SUM(amount_cents), COUNT(*) FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND installments > 1
             AND occurred_at NOT LIKE ?""",
        (user_id, f"{current_month}%"),
    )
    installments_row = cur.fetchone()
    active_installments_monthly = installments_row[0] or 0
    active_installments_count = installments_row[1] or 0

    # Gastos fixos ainda por vir esse mês (recurring não lançados)
    upcoming_recurring = 0
    try:
        cur.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM recurring_transactions WHERE user_id = ? AND active = 1 AND day_of_month > ?",
            (user_id, today.day)
        )
        upcoming_recurring = cur.fetchone()[0] or 0
    except Exception:
        pass

    # Fatura de cartão pré-rastreamento (saldo anterior à adoção do ATLAS)
    card_pretracking_cents = 0
    try:
        cur.execute(
            "SELECT COALESCE(SUM(current_bill_opening_cents), 0) FROM credit_cards WHERE user_id = ?",
            (user_id,)
        )
        card_pretracking_cents = cur.fetchone()[0] or 0
    except Exception:
        pass

    conn.close()

    item_label = f'"{description}"' if description else f"R${amount_cents/100:.2f}"

    # --- sem renda cadastrada ---
    if income_cents == 0:
        pct_of_expenses = (amount_cents / expenses_cents * 100) if expenses_cents else 0
        lines = [f"🤔 Análise: {item_label} por R${amount_cents/100:.2f}"]
        lines.append(f"💸 Você já gastou R${expenses_cents/100:.2f} este mês.")
        if expenses_cents:
            lines.append(f"   Essa compra representa +{pct_of_expenses:.0f}% do que já gastou.")
        lines.append("")
        lines.append("⚠️  Sem renda registrada esse mês não consigo calcular seu orçamento.")
        lines.append('   Registre uma receita: "recebi 3000 de salário"')
        return "\n".join(lines)

    # --- com renda ---
    fixed_commitments = upcoming_recurring + card_pretracking_cents
    budget_remaining = income_cents - expenses_cents - fixed_commitments
    budget_after = budget_remaining - amount_cents
    pct_income = amount_cents / income_cents * 100
    savings_rate_before = max(budget_remaining / income_cents * 100, 0)
    savings_rate_after = max(budget_after / income_cents * 100, 0)

    # projeção: ritmo de gasto diário × dias restantes
    daily_pace = expenses_cents / days_elapsed if days_elapsed else 0
    projected_month_expenses = expenses_cents + (daily_pace * days_remaining)
    projected_budget_after_purchase = income_cents - projected_month_expenses - amount_cents

    # decisão
    if budget_remaining <= 0:
        verdict = "NO"
    elif budget_after < 0:
        verdict = "NO"
    elif projected_budget_after_purchase < 0:
        verdict = "DEFER"
    elif savings_rate_after < 10:
        verdict = "CAUTION"
    elif pct_income > 20:
        verdict = "CAUTION"
    else:
        verdict = "YES"

    icon = {"YES": "✅", "CAUTION": "⚠️", "DEFER": "⏳", "NO": "🚫"}[verdict]
    label = {"YES": "Pode comprar", "CAUTION": "Com cautela", "DEFER": "Melhor adiar", "NO": "Não recomendo"}[verdict]

    lines = [f"{icon} {label} — {item_label} (R${amount_cents/100:.2f})"]
    lines.append("")
    renda_label = f"R${income_cents/100:.2f}"
    if income_real > 0 and income_sources:
        renda_label += f"  ({income_sources})"
    elif income_static > 0 and income_real == 0:
        renda_label += "  (estimativa — registre suas receitas para cálculo exato)"
    lines.append(f"💰 Renda este mês: {renda_label}")
    lines.append(f"💸 Gastos este mês: R${expenses_cents/100:.2f}")
    if active_installments_monthly > 0:
        lines.append(f"💳 Parcelas ativas: R${active_installments_monthly/100:.2f}/mês ({active_installments_count} compra{'s' if active_installments_count > 1 else ''})")
    if upcoming_recurring > 0:
        lines.append(f"📋 Gastos fixos a vencer: R${upcoming_recurring/100:.2f}")
    if card_pretracking_cents > 0:
        lines.append(f"💳 Saldo anterior cartões: R${card_pretracking_cents/100:.2f}")
    lines.append(f"📊 Saldo real: R${budget_remaining/100:.2f} → após compra: R${budget_after/100:.2f}")
    lines.append(f"📈 Taxa de poupança: {savings_rate_before:.0f}% → {savings_rate_after:.0f}%")

    if verdict == "YES":
        lines.append(f"\n✅ Cabe tranquilo. Representa {pct_income:.0f}% da sua renda.")
    elif verdict == "CAUTION":
        if pct_income > 20:
            lines.append(f"\n⚠️  Representa {pct_income:.0f}% da sua renda mensal — é bastante.")
        else:
            lines.append(f"\n⚠️  Sobrarão apenas R${budget_after/100:.2f} até o fim do mês.")
    elif verdict == "DEFER":
        lines.append(f"\n⏳ No ritmo atual você projeta gastar R${projected_month_expenses/100:.2f} este mês.")
        lines.append("   Adiar para o próximo mês seria mais seguro.")
    elif verdict == "NO":
        lines.append(f"\n🚫 Você já está {'no limite' if budget_remaining > 0 else 'acima'} do orçamento.")
        if budget_remaining > 0:
            lines.append(f"   Saldo restante (R${budget_remaining/100:.2f}) não cobre essa compra.")

    return "\n".join(lines)


# ============================================================
# TOOLS — METAS FINANCEIRAS
# ============================================================

def _get_cycle_dates(salary_day: int) -> tuple:
    """
    Retorna (cycle_start, next_salary, days_total, days_elapsed, days_remaining).
    salary_day=0 → usa mês calendário.
    """
    today = datetime.now()
    today_midnight = today.replace(hour=0, minute=0, second=0, microsecond=0)

    if salary_day > 0:
        safe_day = min(salary_day, 28)
        if today.day >= safe_day:
            cycle_start = today.replace(day=safe_day, hour=0, minute=0, second=0, microsecond=0)
            if today.month == 12:
                next_salary = today.replace(year=today.year + 1, month=1, day=safe_day,
                                            hour=0, minute=0, second=0, microsecond=0)
            else:
                next_salary = today.replace(month=today.month + 1, day=safe_day,
                                            hour=0, minute=0, second=0, microsecond=0)
        else:
            if today.month == 1:
                cycle_start = today.replace(year=today.year - 1, month=12, day=safe_day,
                                            hour=0, minute=0, second=0, microsecond=0)
            else:
                cycle_start = today.replace(month=today.month - 1, day=safe_day,
                                            hour=0, minute=0, second=0, microsecond=0)
            next_salary = today.replace(day=safe_day, hour=0, minute=0, second=0, microsecond=0)
    else:
        cycle_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if today.month == 12:
            next_salary = today.replace(year=today.year + 1, month=1, day=1,
                                        hour=0, minute=0, second=0, microsecond=0)
        else:
            next_salary = today.replace(month=today.month + 1, day=1,
                                        hour=0, minute=0, second=0, microsecond=0)

    days_total = max((next_salary - cycle_start).days, 1)
    days_elapsed = max((today_midnight - cycle_start).days + 1, 1)
    days_remaining = max((next_salary - today_midnight).days, 0)
    return cycle_start, next_salary, days_total, days_elapsed, days_remaining


def _progress_bar(current: int, target: int, width: int = 16) -> str:
    pct = min(current / target, 1.0) if target else 0
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


@tool
def create_goal(
    user_phone: str,
    name: str,
    target_amount: float,
    is_emergency_fund: bool = False,
) -> str:
    """
    Cria uma meta financeira.
    name: nome da meta (ex: "Viagem Europa", "Reserva de emergência")
    target_amount: valor alvo em reais (ex: R$5.000 → target_amount=5000)
    is_emergency_fund: True se for reserva de emergência
    """
    target_amount_cents = round(target_amount * 100)
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        user_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO users (id, phone, name) VALUES (?, ?, ?)",
            (user_id, user_phone, "Usuário"),
        )

    # verifica se já existe meta com mesmo nome
    cur.execute(
        "SELECT id FROM financial_goals WHERE user_id = ? AND name = ?",
        (user_id, name),
    )
    if cur.fetchone():
        conn.close()
        return f"Você já tem uma meta chamada '{name}'. Quer adicionar valor a ela?"

    goal_id = str(uuid.uuid4())
    cur.execute(
        """INSERT INTO financial_goals
           (id, user_id, name, target_amount_cents, current_amount_cents, is_emergency_fund)
           VALUES (?, ?, ?, ?, 0, ?)""",
        (goal_id, user_id, name, target_amount_cents, 1 if is_emergency_fund else 0),
    )
    conn.commit()
    conn.close()
    return f"Meta '{name}' criada: R${target_amount_cents/100:.2f}"


@tool
def get_goals(user_phone: str) -> str:
    """Lista todas as metas financeiras com progresso."""
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Nenhuma meta encontrada. Crie uma com 'quero guardar R$5k pra viagem'."

    cur.execute(
        """SELECT name, target_amount_cents, current_amount_cents, is_emergency_fund
           FROM financial_goals WHERE user_id = ?
           ORDER BY is_emergency_fund DESC, created_at ASC""",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Você ainda não tem metas. Crie uma com 'quero guardar R$5k pra viagem'."

    lines = ["🎯 Suas metas:"]
    for name, target, current, is_ef in rows:
        pct = min(current / target * 100, 100) if target else 0
        bar = _progress_bar(current, target)
        label = "🛡️ Reserva" if is_ef else "🎯"
        falta = max(target - current, 0)
        lines.append(f"\n{label} {name}")
        lines.append(f"   {bar} {pct:.0f}%")
        lines.append(f"   R${current/100:.2f} / R${target/100:.2f}  •  faltam R${falta/100:.2f}")

    return "\n".join(lines)


@tool
def add_to_goal(user_phone: str, goal_name: str, amount: float) -> str:
    """
    Adiciona valor a uma meta existente.
    goal_name: nome (ou parte do nome) da meta
    amount: valor em reais a adicionar (ex: R$500 → amount=500)
    """
    amount_cents = round(amount * 100)
    conn = _get_conn()
    cur = conn.cursor()

    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Usuário não encontrado."

    # busca por nome parcial (case-insensitive)
    cur.execute(
        """SELECT id, name, target_amount_cents, current_amount_cents
           FROM financial_goals
           WHERE user_id = ? AND LOWER(name) LIKE ?""",
        (user_id, f"%{goal_name.lower()}%"),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return f"Meta '{goal_name}' não encontrada. Verifique o nome com 'ver minhas metas'."

    goal_id, name, target, current = row
    new_current = current + amount_cents
    completed = new_current >= target

    cur.execute(
        "UPDATE financial_goals SET current_amount_cents = ? WHERE id = ?",
        (new_current, goal_id),
    )
    conn.commit()
    conn.close()

    bar = _progress_bar(new_current, target)
    pct = min(new_current / target * 100, 100)
    falta = max(target - new_current, 0)

    lines = [f"💰 +R${amount_cents/100:.2f} na meta '{name}'"]
    lines.append(f"   {bar} {pct:.0f}%")
    lines.append(f"   R${new_current/100:.2f} / R${target/100:.2f}")

    if completed:
        lines.append(f"\n🎉 META ATINGIDA! Parabéns, você chegou lá!")
    else:
        lines.append(f"   Faltam R${falta/100:.2f}")

    return "\n".join(lines)


@tool
def get_financial_score(user_phone: str) -> str:
    """
    Calcula o score de saúde financeira do mês atual (0-100, grau A+ a F).
    Baseado em: taxa de poupança, consistência de registros, controle do orçamento e metas.
    """
    today = datetime.now()
    current_month = today.strftime("%Y-%m")
    days_elapsed = today.day

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name, monthly_income_cents FROM users WHERE phone = ?",
        (user_phone,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum dado encontrado. Comece registrando seus gastos!"

    user_id, user_name, income_cents = row
    income_cents = income_cents or 0

    # gastos e receitas do mês
    cur.execute(
        """SELECT type, SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND occurred_at LIKE ?
           GROUP BY type""",
        (user_id, f"{current_month}%"),
    )
    totals = {r[0]: r[1] for r in cur.fetchall()}
    expenses_cents = totals.get("EXPENSE", 0)
    income_registered = totals.get("INCOME", 0)

    # dias com pelo menos 1 transação
    cur.execute(
        """SELECT COUNT(DISTINCT substr(occurred_at, 1, 10)) FROM transactions
           WHERE user_id = ? AND occurred_at LIKE ?""",
        (user_id, f"{current_month}%"),
    )
    active_days = cur.fetchone()[0] or 0

    # metas
    cur.execute(
        "SELECT target_amount_cents, current_amount_cents FROM financial_goals WHERE user_id = ?",
        (user_id,),
    )
    goals = cur.fetchall()
    conn.close()

    # ── COMPONENTES DO SCORE ──────────────────────────────────

    # 1. Taxa de poupança (35%) — só calcula com renda
    effective_income = income_cents or income_registered
    if effective_income > 0:
        savings_rate = max((effective_income - expenses_cents) / effective_income, 0)
        # curva: 0%→20pts, 10%→55pts, 20%→85pts, 30%+→100pts
        if savings_rate >= 0.30:
            s_score = 100
        elif savings_rate >= 0.20:
            s_score = 85 + (savings_rate - 0.20) / 0.10 * 15
        elif savings_rate >= 0.10:
            s_score = 55 + (savings_rate - 0.10) / 0.10 * 30
        else:
            s_score = savings_rate / 0.10 * 55
        has_income = True
    else:
        s_score = 50  # neutro se sem renda
        savings_rate = 0
        has_income = False

    # 2. Consistência (25%) — dias com registro / dias decorridos
    c_score = min(active_days / days_elapsed * 100, 100) if days_elapsed else 0

    # 3. Controle do orçamento (20%) — ficou dentro da renda?
    if effective_income > 0:
        if expenses_cents <= effective_income:
            b_score = 100
        else:
            overspend_pct = (expenses_cents - effective_income) / effective_income
            b_score = max(0, 100 - overspend_pct * 200)
    else:
        b_score = 70  # neutro

    # 4. Aderência a metas (20%)
    if goals:
        goal_scores = [min(cur_/tgt, 1.0) * 100 for tgt, cur_ in goals if tgt > 0]
        g_score = sum(goal_scores) / len(goal_scores) if goal_scores else 0
    else:
        g_score = 50  # neutro se sem metas

    # score final ponderado
    final = (s_score * 0.35) + (c_score * 0.25) + (b_score * 0.20) + (g_score * 0.20)
    final = round(min(max(final, 0), 100))

    # grau
    grade = (
        "A+" if final >= 90 else
        "A"  if final >= 80 else
        "B+" if final >= 70 else
        "B"  if final >= 60 else
        "C+" if final >= 50 else
        "C"  if final >= 40 else
        "D"  if final >= 30 else "F"
    )

    grade_emoji = {
        "A+": "🏆", "A": "🌟", "B+": "💪", "B": "👍",
        "C+": "😐", "C": "⚠️", "D": "😟", "F": "🚨"
    }[grade]

    lines = [f"{grade_emoji} Score de {today.strftime('%B/%Y')}: {final}/100 — {grade}"]
    lines.append("")

    # detalhes dos componentes
    lines.append("📊 Componentes:")
    lines.append(f"  💰 Poupança      {s_score:.0f}/100  (peso 35%)")
    lines.append(f"  📅 Consistência  {c_score:.0f}/100  (peso 25%)")
    lines.append(f"  🎯 Metas         {g_score:.0f}/100  (peso 20%)")
    lines.append(f"  🧮 Orçamento     {b_score:.0f}/100  (peso 20%)")

    # contexto adicional
    lines.append("")
    if has_income and savings_rate > 0:
        lines.append(f"💸 Taxa de poupança: {savings_rate*100:.1f}%")
    lines.append(f"📅 Registrou em {active_days} de {days_elapsed} dias do mês")
    if goals:
        lines.append(f"🎯 {len(goals)} meta(s) ativas")

    # principal dica de melhoria
    worst = min(
        [("poupança", s_score), ("consistência", c_score), ("metas", g_score), ("orçamento", b_score)],
        key=lambda x: x[1],
    )
    lines.append(f"\n💡 Para melhorar: foque em {worst[0]} ({worst[1]:.0f}/100 agora)")

    if not has_income:
        lines.append("\n⚠️  Cadastre sua renda para um score mais preciso.")

    return "\n".join(lines)


# ============================================================
# TOOLS — CICLO DE SALÁRIO / CLT
# ============================================================

@tool
def set_salary_day(user_phone: str, salary_day: int) -> str:
    """
    Salva o dia do mês em que o salário/renda principal cai.
    salary_day: dia do mês, entre 1 e 28.
    Ex: 5 → salário cai todo dia 5.
    Use quando o usuário disser "meu salário é todo dia X", "recebo no dia X".
    """
    if not (1 <= salary_day <= 28):
        return "Dia inválido. Informe um dia entre 1 e 28."

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Usuário não encontrado."

    cur.execute("UPDATE users SET salary_day = ? WHERE phone = ?", (salary_day, user_phone))
    conn.commit()
    conn.close()
    return f"Ciclo configurado: salário cai todo dia {salary_day}. Agora posso acompanhar seu ciclo de perto!"


@tool
def get_salary_cycle(user_phone: str) -> str:
    """
    Retorna o status completo do ciclo de salário atual.
    Mostra: renda, gasto até agora, orçamento diário, ritmo atual, dias restantes e projeção de fim de ciclo.
    Use quando o usuário perguntar "como estou no ciclo?", "quanto tenho por dia?", "como tá o mês?"
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, monthly_income_cents, salary_day FROM users WHERE phone = ?",
        (user_phone,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum dado encontrado."

    user_id, income_cents, salary_day = row
    income_cents = income_cents or 0
    salary_day = salary_day or 0

    cycle_start, next_salary, days_total, days_elapsed, days_remaining = _get_cycle_dates(salary_day)
    cycle_start_str = cycle_start.strftime("%Y-%m-%dT%H:%M:%S")

    # Gastos no ciclo
    cur.execute(
        """SELECT SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at >= ?""",
        (user_id, cycle_start_str),
    )
    expenses_cents = cur.fetchone()[0] or 0

    # Receitas reais do ciclo
    cur.execute(
        """SELECT SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'INCOME' AND occurred_at >= ?""",
        (user_id, cycle_start_str),
    )
    income_real = cur.fetchone()[0] or 0
    conn.close()

    income_to_use = income_real if income_real > 0 else income_cents

    if income_to_use == 0:
        return (
            "Sem renda cadastrada para calcular o ciclo.\n"
            "Registre: 'recebi 4000 de salário' ou me diga: 'minha renda é 4000'."
        )

    daily_budget = income_to_use / days_total
    daily_pace = expenses_cents / days_elapsed
    projected_expenses = daily_pace * days_total
    projected_leftover = income_to_use - projected_expenses

    budget_used_pct = expenses_cents / income_to_use * 100
    expected_by_now = daily_budget * days_elapsed
    on_track = expenses_cents <= expected_by_now
    status_icon = "✅" if on_track else "⚠️"

    cycle_label = f"dia {salary_day}" if salary_day > 0 else "mês atual"

    lines = [f"📅 Ciclo de salário ({cycle_label})"]
    lines.append(f"   Dia {days_elapsed} de {days_total}  •  {days_remaining} dias restantes")
    lines.append("")
    lines.append(f"💰 Renda do ciclo:  R${income_to_use/100:.2f}")
    lines.append(f"💸 Gasto até agora: R${expenses_cents/100:.2f} ({budget_used_pct:.0f}% da renda)  {status_icon}")
    lines.append(f"📊 Orçamento diário: R${daily_budget/100:.2f}/dia")
    lines.append(f"📈 Ritmo atual:      R${daily_pace/100:.2f}/dia")
    lines.append("")

    if projected_leftover >= 0:
        pct_savings = projected_leftover / income_to_use * 100
        lines.append(f"✅ Projeção: sobram R${projected_leftover/100:.2f} ({pct_savings:.0f}% de poupança)")
    else:
        lines.append(f"⚠️  Projeção: vai exceder em R${abs(projected_leftover)/100:.2f}")
        if days_remaining > 0:
            corte_dia = abs(projected_leftover) / days_remaining
            lines.append(f"   Para equilibrar: corte R${corte_dia/100:.2f}/dia nos próximos {days_remaining} dias")

    if not on_track:
        excesso = expenses_cents - expected_by_now
        lines.append(f"\n⚠️  Você está R${excesso/100:.2f} acima do esperado para o dia {days_elapsed}.")

    return "\n".join(lines)


@tool
def will_i_have_leftover(user_phone: str) -> str:
    """
    Responde 'Vai sobrar?' — projeção de quanto vai restar ao fim do ciclo/mês
    com base no ritmo atual. Mostra 3 cenários: atual, cortando supérfluo, e meta de 20% poupança.
    Use quando o usuário perguntar "vai sobrar?", "vai ter dinheiro até o fim do mês?", "vai faltar?"
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, monthly_income_cents, salary_day FROM users WHERE phone = ?",
        (user_phone,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum dado encontrado."

    user_id, income_cents, salary_day = row
    income_cents = income_cents or 0
    salary_day = salary_day or 0

    cycle_start, next_salary, days_total, days_elapsed, days_remaining = _get_cycle_dates(salary_day)
    cycle_start_str = cycle_start.strftime("%Y-%m-%dT%H:%M:%S")

    # Gastos por categoria no ciclo
    cur.execute(
        """SELECT category, SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at >= ?
           GROUP BY category ORDER BY SUM(amount_cents) DESC""",
        (user_id, cycle_start_str),
    )
    category_expenses = cur.fetchall()

    # Receitas
    cur.execute(
        """SELECT SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'INCOME' AND occurred_at >= ?""",
        (user_id, cycle_start_str),
    )
    income_real = cur.fetchone()[0] or 0
    conn.close()

    income_to_use = income_real if income_real > 0 else income_cents

    if income_to_use == 0:
        return "Sem renda cadastrada. Registre sua renda primeiro para eu calcular a projeção."

    expenses_cents = sum(v for _, v in category_expenses)

    if expenses_cents == 0:
        return "Nenhum gasto registrado neste ciclo ainda. Anote seus gastos e eu projeto o fim do mês!"

    daily_pace = expenses_cents / days_elapsed
    projected_expenses = daily_pace * days_total
    projected_leftover = income_to_use - projected_expenses

    # Categorias não-essenciais (cortáveis)
    cuttable = {"Alimentação", "Lazer", "Assinaturas", "Vestuário", "Outros"}
    cuttable_daily = sum(v for cat, v in category_expenses if cat in cuttable) / days_elapsed

    # Cenário 2: cortar 30% do supérfluo
    reduced_daily = daily_pace - (cuttable_daily * 0.30)
    projected_reduced = income_to_use - (reduced_daily * days_total)
    savings_ganho = (reduced_daily * 0.30) * days_remaining  # quanto economiza daqui pra frente cortando 30%

    # Cenário 3: meta de 20% poupança
    max_expenses_for_20pct = income_to_use * 0.80
    max_daily_for_20pct = max_expenses_for_20pct / days_total

    lines = ["💭 Vai sobrar?"]
    lines.append(f"   {days_remaining} dias restantes  •  Renda: R${income_to_use/100:.2f}  •  Gasto: R${expenses_cents/100:.2f}")
    lines.append("")

    # Cenário 1 — ritmo atual
    icon1 = "✅" if projected_leftover > 0 else "🚨"
    lines.append(f"{icon1} No ritmo atual (R${daily_pace/100:.2f}/dia):")
    if projected_leftover > 0:
        pct = projected_leftover / income_to_use * 100
        lines.append(f"   → Sobram R${projected_leftover/100:.2f} ({pct:.0f}% de poupança)")
    else:
        lines.append(f"   → Vai faltar R${abs(projected_leftover)/100:.2f} antes do próximo salário")
        corte_dia = abs(projected_leftover) / days_remaining if days_remaining > 0 else 0
        lines.append(f"   → Para equilibrar: cortar R${corte_dia/100:.2f}/dia")

    # Cenário 2 — cortando supérfluo
    if cuttable_daily > 0:
        lines.append("")
        icon2 = "✅" if projected_reduced > 0 else "⚠️"
        lines.append(f"✂️  Cortando 30% do supérfluo (economiza R${savings_ganho/100:.2f}):")
        if projected_reduced > 0:
            pct2 = projected_reduced / income_to_use * 100
            lines.append(f"   → Sobram R${projected_reduced/100:.2f} ({pct2:.0f}% poupança)")
        else:
            lines.append(f"   → Ainda faltariam R${abs(projected_reduced)/100:.2f}")

    # Cenário 3 — meta 20%
    lines.append("")
    if daily_pace <= max_daily_for_20pct:
        lines.append(f"🎯 Poupança de 20%: você está dentro! (máx R${max_daily_for_20pct/100:.2f}/dia)")
    else:
        diff = daily_pace - max_daily_for_20pct
        lines.append(f"🎯 Para poupar 20%: corte R${diff/100:.2f}/dia (máx R${max_daily_for_20pct/100:.2f}/dia)")

    # Maior gasto da categoria
    if category_expenses:
        top_cat, top_val = category_expenses[0]
        top_pct = top_val / expenses_cents * 100 if expenses_cents else 0
        lines.append(f"\n📊 Maior gasto: {top_cat} — R${top_val/100:.2f} ({top_pct:.0f}% do total)")

    return "\n".join(lines)


# ============================================================
# SCHEMAS — ParseAgent
# ============================================================

class ParsedMessage(BaseModel):
    intent: str = Field(..., description=(
        "ADD_EXPENSE | ADD_INCOME | QUERY_CAN_I_BUY | SUMMARY | SET_GOAL | HELP | UNKNOWN"
    ))
    amount_cents: Optional[int] = Field(None, description="Valor em centavos. Ex: R$45,50 = 4550")
    currency: str = Field(default="BRL")
    merchant: Optional[str] = Field(None, description="Nome do estabelecimento")
    category_hint: Optional[str] = Field(None, description=(
        "Alimentação | Transporte | Moradia | Saúde | Lazer | Educação | "
        "Assinaturas | Vestuário | Investimento | Renda | Outros"
    ))
    payment_method: Optional[str] = Field(None, description="CREDIT | DEBIT | PIX | CASH | TED")
    occurred_at: Optional[str] = Field(None, description="ISO 8601. None = agora.")
    notes: Optional[str] = None
    confidence: float = Field(..., description="0.0 a 1.0")
    needs_clarification: bool
    question: Optional[str] = Field(None, description="Pergunta em PT-BR se needs_clarification=True")


# ============================================================
# PARSE AGENT
# ============================================================

PARSE_INSTRUCTIONS = """
Você é o interpretador financeiro do ATLAS.

Analise mensagens em português brasileiro e extraia intent e dados financeiros.

Intents:
- ADD_EXPENSE: gasto ("gastei", "paguei", "comprei", "saiu")
- ADD_INCOME: receita ("recebi", "caiu", "entrou", "salário")
- QUERY_CAN_I_BUY: pergunta se pode gastar ("posso comprar?", "tenho budget?")
- SUMMARY: resumo ("como estou?", "quanto gastei?", "resumo")
- SET_GOAL: meta ("quero economizar", "minha meta")
- HELP: ajuda ("como funciona?", "oi", "olá")
- UNKNOWN: fora do escopo

Valores: "50 reais" = 5000, "R$45,50" = 4550, "mil" = 100000

Categorias de GASTO (EXPENSE):
- iFood, Rappi, restaurante, lanche, mercado → Alimentação
- Uber, 99, gasolina, pedágio, ônibus, metrô → Transporte
- Netflix, Spotify, Amazon Prime, assinatura → Assinaturas
- Farmácia, médico, plano de saúde, remédio → Saúde
- Aluguel, condomínio, luz, água, internet, gás → Moradia
- Academia, bar, cinema, show, viagem → Lazer
- Curso, livro, faculdade → Educação
- Roupa, tênis, acessório → Vestuário
- CDB, ação, fundo, tesouro, cripto → Investimento
- Presente, doação → Outros

Categorias de RENDA (INCOME):
- Salário, holerite, pagamento empresa → Salário
- Freela, projeto, cliente, PJ, nota fiscal → Freelance
- Aluguel recebido, inquilino → Aluguel Recebido
- Dividendo, rendimento, CDB, juros, tesouro → Investimentos
- Aposentadoria, INSS, pensão, benefício → Benefício
- Venda de item, marketplace, Mercado Livre → Venda
- Presente, transferência recebida, Pix recebido sem contexto → Outros

## REGRAS DE PARCELAMENTO

Detecte automaticamente sem perguntar:
- Usuário menciona "em Nx", "parcelei", "12 vezes", "6x" → parcelado, extraia installments
- Usuário menciona "à vista", "débito", "Pix", "dinheiro", "espécie" → à vista (installments=1)
- Valor baixo (< R$200) sem mencionar forma → à vista (installments=1)
- Assinaturas, delivery, transporte → sempre à vista (installments=1)

Pergunte APENAS quando ambíguo:
- Usuário menciona "cartão" ou "crédito" + valor ≥ R$200 + sem informar parcelas
- Neste caso: needs_clarification=True, question="Foi à vista ou parcelado? Se parcelado, em quantas vezes?"

Nunca pergunte sobre parcelamento para:
- Gastos do dia a dia (alimentação, transporte, assinaturas)
- Valores abaixo de R$200
- Quando o usuário já informou a forma de pagamento
"""

parse_agent = Agent(
    name="parse_agent",
    description="Interpreta mensagens financeiras e retorna JSON estruturado.",
    instructions=PARSE_INSTRUCTIONS,
    model=get_model(),
    output_schema=ParsedMessage,
    add_datetime_to_context=True,
)

# ============================================================
# RESPONSE AGENT
# ============================================================

RESPONSE_INSTRUCTIONS = """
Você é o ATLAS — assistente financeiro via WhatsApp.
Tom: amigável, direto, informal. Português brasileiro natural.
Emojis com moderação (1-2 por mensagem).
Atende tanto pessoas físicas (CLT, autônomos) quanto MEI e freelancers.

## REGRA DE FORMATO — CRÍTICA
Envie SEMPRE UMA única mensagem por resposta.
Nunca divida em múltiplas mensagens separadas.
Máximo 5 linhas por resposta. Seja direto.
SEMPRE termine com UMA pergunta ou sugestão — nunca duas.
PROIBIDO usar "ou" para oferecer duas opções no final. Escolha A opção mais relevante e ponto.
ERRADO: "Quer ver o total de hoje ou anotar mais algum gasto?"
CERTO:  "Quer ver o total de hoje?"

## REGRA DE FORMA DE PAGAMENTO
NÃO mencione forma de pagamento quando o usuário não informou.
Só inclua se o usuário disse explicitamente: "no débito", "no Pix", "no crédito", "dinheiro".
ERRADO: "Anotado! R$120 no mercado extra — via PIX." (usuário não disse Pix)
CERTO:  "Anotado! R$120 no mercado extra."

## FORMATO POR AÇÃO

ADD_EXPENSE / ADD_INCOME:
  Formato: "Anotado! [emoji] R$XX em [Categoria] — [merchant se disponível][detalhe de pagamento]."
  Depois de 1 linha em branco: UMA sugestão. Ex: "Quer ver o total de hoje?"
  - À vista implícito (sem menção): não mencione pagamento para valores < R$200
  - À vista para valores ≥ R$200: adicione "— à vista. Foi parcelado? É só me falar."
  - Parcelado: "Anotado! 👟 R$120/mês × 3x (R$360 total) em Vestuário — Nike Store."
  - PIX/débito/dinheiro explícito: inclua o método, não pergunte sobre parcelamento

GASTO SEM CONTEXTO ("gastei 18", "saiu 50" sem indicar o que foi):
  NÃO salve. Pergunte primeiro: "R$18 em quê?" ou "Onde foi esse gasto de R$50?"
  Só salve depois que o usuário responder.

SALDO / "qual meu saldo?":
  Formato direto — UMA linha de saldo, UMA linha de detalhe, UMA sugestão:
  "💰 Saldo de março: R$4.415
  Receitas: R$4.500 | Gastos: R$85
  Quer ver como foi por categoria?"

RESUMO MENSAL:
  Mostre totais por categoria com emoji (1 linha por categoria).
  Se não tiver receita lançada mas tiver renda cadastrada: mencione "Sua renda cadastrada é R$X.XXX — ainda não lançou salário esse mês?"
  Sugestão final — baseada em has_previous_data:
  - has_previous_data=True → "Quer comparar com o mês passado?"
  - has_previous_data=False → "Quer anotar mais algum gasto?" (não sugira comparativo — não há histórico)

COMPARATIVO MENSAL:
  Destaque variações (↑ subiu, ↓ caiu). Alertas ⚠️ em evidência.
  Termine com: "Quer ver os detalhes de alguma categoria?"

RESUMO SEMANAL:
  Total da semana + alertas se houver.
  Termine com: "Quer o resumo do mês completo?"

DETALHES DE TRANSAÇÕES:
  Liste de forma limpa, 1 linha por transação.
  Termine com: "Quer anotar mais algum gasto?"

DETALHES DE CATEGORIA (get_category_breakdown):
  Formato: "🔍 [Categoria]: R$X total
  • [Local A]: R$X (XX%)
  • [Local B]: R$X (XX%)"
  Se merchant vazio: mostre como "Sem nome registrado"
  Termine com: "Quer ver outra categoria?"

HELP / ONBOARDING:
  Apresente o ATLAS em 2 linhas. 3 exemplos de uso.

AJUDA / MENU ("ajuda", "/ajuda", "menu", "o que você faz?"):
  Responda com o menu completo formatado com categorias:
  💸 Gastos | 💰 Receitas | 📊 Análises | 💳 Cartões | 📋 Gastos fixos | 🎯 Metas
  2-3 exemplos por categoria. Termine com: "Fale natural — não precisa de comando exato 😊"

POSSO COMPRAR? (can_i_buy):
  SEMPRE mostre o raciocínio em 3 linhas — nunca só "Pode sim" sem dados:
  Linha 1: veredito com emoji (✅ Pode / ⚠️ Com cautela / ⏳ Melhor adiar / 🚫 Não recomendo)
  Linha 2: "Saldo atual: R$X.XXX → após compra: R$X.XXX"
  Linha 3: insight contextual (ex: "Isso é X% da sua renda" ou "Vai sobrar pouco até o fim do mês")
  UMA sugestão final (ex: "Quer parcelar pra não pesar tanto?")

CARTÃO DE CRÉDITO — cadastro:
  "Cartão [Nome] cadastrado! Fecha dia [X], vence dia [Y], limite R$[Z]."
  Se fatura informada: "Fatura atual: R$X registrada como saldo anterior."
  Sugestão: "Quer registrar seus gastos fixos também?"

FATURAS (get_cards):
  Use o formato retornado pela tool — não reescreva.
  Termine com: "Quer ver os gastos em algum cartão específico?"

PRÓXIMA FATURA (get_next_bill):
  Use o formato retornado. Destaque o total estimado em negrito.
  Se tiver parcela marcada como "última parcela!", mencione: "O [nome] quita na próxima fatura!"
  Termine com: "Quer ver a fatura atual também?"

GASTOS FIXOS — cadastro:
  "Anotado! [Nome] — R$X todo dia [Y]. Total fixo mensal: R$Z." (se puder calcular)
  Ou simplesmente: "Gasto fixo cadastrado: [Nome] R$X todo dia [Y]."

GASTOS FIXOS (get_recurring):
  Use o formato retornado — não reescreva.
  Termine com: "Quer ver quanto ainda vai sair esse mês?"

CICLO DE SALÁRIO:
  Blocos: renda / gasto / orçamento diário / projeção.
  Termine com: "Quer ver o que vai sobrar até o fim do ciclo?"

VAI SOBRAR?:
  Direto no veredito + 3 cenários resumidos.
  Termine com: "Quer estratégias pra economizar mais?"

CLARIFICAÇÃO:
  UMA pergunta curta. Nunca mais de uma.

## REGRAS
- UMA mensagem, máximo 5 linhas, UMA sugestão no final
- NUNCA faça cálculos — use os dados fornecidos
- NUNCA mostre JSON ou dados técnicos
- SEMPRE PT-BR informal
"""

response_agent = Agent(
    name="response_agent",
    description="Gera respostas em português brasileiro.",
    instructions=RESPONSE_INSTRUCTIONS,
    model=get_fast_model(),
    markdown=True,
)

# ============================================================
# ATLAS AGENT — Conversacional com memória e banco
# ============================================================

ATLAS_INSTRUCTIONS = f"""
{PARSE_INSTRUCTIONS}

---

{RESPONSE_INSTRUCTIONS}

---

## REGRA GLOBAL
A PRIMEIRA LINHA de cada mensagem tem o formato: [user_phone: +55XXXXXXXXXX]
Extraia esse valor e use-o como user_phone em TODAS as chamadas de tool.
Nunca use "demo_user". Se a linha não estiver presente, use o número de sessão disponível.

---

## ONBOARDING — primeira mensagem de cada sessão

1. Chame get_user(user_phone=<user_phone extraído da 1ª linha>) SEMPRE na primeira mensagem.

2. Se is_new=True (usuário novo) — fluxo em 3 etapas:

   ETAPA A — Apresentação + nome:
   - Apresente o ATLAS em 2 linhas, tom animado
   - Exemplo: "Oi! 👋 Sou o ATLAS, seu assistente financeiro no WhatsApp. Anoto seus gastos, receitas e te ajudo a entender pra onde vai seu dinheiro — tudo aqui na conversa, sem app."
   - Pergunte APENAS o nome: "Qual é o seu nome?"
   - Aguarde. NÃO pergunte mais nada nessa etapa.

   ETAPA B — Após receber o nome:
   REGRA CRÍTICA: use EXATAMENTE o nome que o usuário acabou de digitar nesta mensagem.
   IGNORE qualquer nome que apareça no histórico de conversas anteriores — ele pertence a outro contexto.
   - Chame update_user_name(user_phone=<user_phone>, name="<nome_desta_mensagem>")
   - Pergunte a renda de forma leve e opcional:
     "Prazer, [nome_desta_mensagem]! 💰 Pra te ajudar melhor, qual é sua renda mensal aproximada? Pode ser um número redondo como 3000, 5000... (pode pular se preferir)"
   - Aguarde. NÃO pergunte mais nada nessa etapa.
   - NÃO avance para ETAPA C até receber a renda OU o usuário pular explicitamente.

   ETAPA C — Após receber a renda (ou pulo explícito com "pular", "não sei", "depois"):
   - Se informou renda: chame update_user_income(user_phone=<user_phone>, monthly_income=<valor em reais>)
   - Se pulou: ok, siga sem renda.
   - Guie para o primeiro uso com exemplos variados e práticos:
     "Tudo certo! Agora é só me mandar seus gastos assim:

💸 *Gastos do dia a dia:*
• "gastei 45 no iFood"
• "paguei 120 no Mercado Extra"
• "uber 18 pra academia"

💳 *Compras no cartão:*
• "comprei tênis 300 no Nubank"
• "notebook 3000 em 6x no Inter"

📊 *Ver como está:*
• "como tá meu mês?"
• "posso comprar um tênis de 200?"

Digite *ajuda* a qualquer hora pra ver tudo que eu sei fazer 🎯"

3. Se is_new=False e has_income=False (usuário sem renda cadastrada):
   - Cumprimente pelo nome normalmente
   - Após qualquer interação, sugira uma vez: "Quer cadastrar sua renda pra eu te ajudar melhor com alertas e análises?"

4. Se is_new=False e has_income=True (usuário completo):
   - Cumprimente pelo nome de forma curta e variada. USE UMA DESSAS (escolha aleatória, nunca a mesma sempre):
     • "Oi, [name]! 👋 Como posso te ajudar?"
     • "Oi, [name]! 😊 O que aconteceu hoje?"
     • "Ei, [name]! 👋 Me conta."
     • "Oi, [name]! O que anotamos hoje?"
   - NUNCA use sempre a mesma saudação — varie a cada sessão.
   - Pule todo o onboarding.
   - Se salary_day=0 e transaction_count >= 5: após responder, sugira UMA vez:
     "Você é CLT? Me fala o dia que seu salário cai (ex: 'meu salário é todo dia 5') — aí consigo acompanhar seu ciclo!"

---

## FLUXO FINANCEIRO (após onboarding)

## AJUDA / MENU

Quando o usuário digitar "ajuda", "/ajuda", "menu", "o que você faz?", "como funciona?", "comandos", "oi" (sem ser primeira vez), "olá" genérico:
Responda com este menu formatado — sem chamar nenhum tool:

"📋 *O que o ATLAS faz:*

💸 *Lançar gastos:*
• "gastei 45 no iFood"
• "paguei 120 no Mercado Extra"
• "uber 18 pro aeroporto"
• "tênis 300 em 3x no Nubank" _(lança no cartão Nubank)_
• "paguei 200 no débito"

💰 *Lançar receitas:*
• "recebi 4500 de salário"
• "entrou 1200 de freela"

📊 *Análises:*
• "como tá meu mês?"
• "quanto gastei hoje?"
• "onde gastei em Alimentação?"
• "posso comprar um tênis de 200?"
• "vai sobrar até o fim do mês?"

💳 *Cartões:*
• "qual minha fatura do Nubank?"
• "próxima fatura do Nubank"
• "paguei o cartão Inter"

📌 *Cadastrar cartão:*
• "quero cadastrar meu cartão Nubank"
  → ATLAS vai perguntar: dia de fechamento, vencimento, limite e fatura atual

📌 *Registrar fatura de meses futuros:*
• "minha fatura de abril no Nubank é 800"
• "fatura de maio no Itaú vai ser 1200"
  → Use quando você já tem compras no cartão antes de começar a usar o ATLAS

📋 *Gastos fixos:*
• "tenho aluguel 1500 todo dia 5"
• "quais meus gastos fixos?"

🎯 *Metas:*
• "quero guardar 5000 pra viagem"
• "guardei 500 na meta viagem"
• "ver minhas metas"

*Dica:* fale natural — não precisa de comando exato 😊"

REGRA CRÍTICA — SALVAR SEM PEDIR CONFIRMAÇÃO:
Sempre que o usuário informar valor + qualquer contexto (item, local, categoria), salve IMEDIATAMENTE.
Não peça "Pode ser?" antes de salvar. A confirmação vem DEPOIS de salvar no texto da resposta.
O usuário pode corrigir depois se precisar.

EXCEÇÃO — Gasto sem contexto algum ("gastei 18", "saiu 50"):
Se não há NENHUMA pista do que foi (sem item, sem local, sem categoria), NÃO salve.
Pergunte primeiro: "R$18 em quê?" — salve só após a resposta.

- ADD_EXPENSE à vista: save_transaction(user_phone=<user_phone>, transaction_type="EXPENSE", amount=<valor_reais>, installments=1, ...)
- ADD_EXPENSE parcelado: save_transaction(user_phone=<user_phone>, transaction_type="EXPENSE", amount=<parcela_reais>, installments=<n>, total_amount=<total_reais>, ...)
  Exemplo "tênis 1200 em 12x": save imediatamente → amount=100, installments=12, total_amount=1200
- ADD_INCOME: save_transaction(user_phone=<user_phone>, transaction_type="INCOME", amount=<valor_reais>, ...)
- SUMMARY / "quanto gastei?" / "resumo do mês": get_month_summary(user_phone=<user_phone>)
- "como evoluí?" / "comparado ao mês passado": get_month_comparison(user_phone=<user_phone>)
- "como foi minha semana?" / "resumo da semana": get_week_summary(user_phone=<user_phone>)
- "quanto gastei hoje?": get_today_total(user_phone=<user_phone>)
- Detalhes / lista de transações: get_transactions(user_phone=<user_phone>, date="YYYY-MM-DD") ou get_transactions(user_phone=<user_phone>, month="YYYY-MM")
- "onde gastei em X?" / "quais [lugares] em X?" / "detalhes de [categoria]": get_category_breakdown(user_phone=<user_phone>, category="<categoria>")
  Exemplos: "onde gastei em Alimentação?" → category="Alimentação" | "quais restaurantes fui?" → category="Alimentação"
- "minhas parcelas" / "quanto tenho parcelado": get_installments_summary(user_phone=<user_phone>)

## CORREÇÕES
Quando usuário disser "espera", "errei", "corrige", "na verdade", "foi parcelado", "foi no débito", "o local era X":
1. Chame get_last_transaction(user_phone=<user_phone>) para ver o que foi registrado
2. Confirme em UMA linha: "Vou corrigir [o que muda]. Pode ser?"
3. Chame update_last_transaction(user_phone=<user_phone>, <apenas os campos a corrigir>)
4. Confirme a correção em UMA linha

Campos que update_last_transaction suporta:
- installments → corrige parcelamento (recalcula parcela automaticamente)
- payment_method → CREDIT | DEBIT | PIX | CASH
- category → categoria
- amount → valor total em reais
- merchant → nome do local/estabelecimento

Exemplos:
- "foi parcelado em 6x" → update_last_transaction(user_phone=<user_phone>, installments=6)
- "foi no débito" → update_last_transaction(user_phone=<user_phone>, payment_method="DEBIT")
- "foi 150 não 200" → update_last_transaction(user_phone=<user_phone>, amount=150)
- "foi em Alimentação" → update_last_transaction(user_phone=<user_phone>, category="Alimentação")
- "o local era Magazine Luiza" → update_last_transaction(user_phone=<user_phone>, merchant="Magazine Luiza")

IMPORTANTE: nunca passe installments e amount juntos a menos que o usuário corrija os dois ao mesmo tempo.
Ao corrigir parcelamento, passe APENAS installments — o valor total é calculado automaticamente.
- "posso comprar X?" / "tenho dinheiro pra Y?": can_i_buy(user_phone=<user_phone>, amount=<valor_reais>, description="<item>")
- "quero guardar X pra Y" / "criar meta": create_goal(user_phone=<user_phone>, name="<nome>", target_amount=<valor_reais>)
- "quero reserva de emergência": create_goal(..., is_emergency_fund=True)
- "ver minhas metas" / "como estão minhas metas?": get_goals(user_phone=<user_phone>)
- "guardei X pra meta Y" / "adicionei X na meta": add_to_goal(user_phone=<user_phone>, goal_name="<nome parcial>", amount=<valor_reais>)
- "qual meu score?" / "saúde financeira" / "como estou?": get_financial_score(user_phone=<user_phone>)

## CARTÕES DE CRÉDITO

Cadastrar cartão: "tenho Nubank, fecha dia 25, vence dia 10, limite 10000" / "minha fatura do Inter já está em 2000"
→ register_card(user_phone=<user_phone>, name="Nubank", closing_day=25, due_day=10, limit=10000)
→ register_card(user_phone=<user_phone>, name="Inter", closing_day=X, due_day=Y, current_bill=2000)
   Se fechamento/vencimento não informados, pergunte: "Qual o dia de fechamento e vencimento do [nome]?"

Gasto no cartão: "comprei X no Nubank" / "gastei 300 no Inter" / "parcelei no Bradesco"
→ save_transaction(..., card_name="Nubank")
   Se cartão informado mas não cadastrado: "Você tem o [nome] cadastrado? Me passa o dia de fechamento e limite pra eu rastrear a fatura."

Ver faturas: "como estão minhas faturas?" / "fatura do Nubank" / "quanto está no cartão?"
→ get_cards(user_phone=<user_phone>)

Pagar fatura: "paguei a fatura do Nubank" / "quitei o Inter" / "paguei o cartão"
→ close_bill(user_phone=<user_phone>, card_name="Nubank")

Próxima fatura: "quanto vai ser minha próxima fatura do Nubank?" / "o que cai no mês que vem no Inter?" / "próxima fatura"
→ get_next_bill(user_phone=<user_phone>, card_name="Nubank")

Registrar compromissos pré-existentes no cartão (faturas já acumuladas ANTES do ATLAS):
"minha fatura de abril no Nubank já está em 400" / "em maio tenho 150 no Inter" / "Nubank: março 500, abril 400, maio 150"
→ set_future_bill(user_phone=<user_phone>, card_name="Nubank", bill_month="2026-04", amount=400)
   Se o usuário informar múltiplos meses de uma vez, chame set_future_bill UMA VEZ POR MÊS.
   bill_month sempre no formato YYYY-MM (ex: "2026-04").

## GASTOS FIXOS / RECORRENTES

Cadastrar gasto fixo: "tenho aluguel 1500 todo dia 5" / "pago Netflix 55 todo dia 15" / "parcela do carro 800 no Nubank todo dia 10"
→ register_recurring(user_phone=<user_phone>, name="Aluguel", amount=1500, category="Moradia", day_of_month=5)
→ register_recurring(user_phone=<user_phone>, name="Netflix", amount=55, category="Assinaturas", day_of_month=15)
→ register_recurring(user_phone=<user_phone>, name="Parcela Carro", amount=800, category="Transporte", day_of_month=10, card_name="Nubank")

Ver gastos fixos: "quais meus gastos fixos?" / "minhas contas mensais" / "meus compromissos" / "o que pago todo mês?"
→ get_recurring(user_phone=<user_phone>)

Cancelar gasto fixo: "cancelei a Netflix" / "quitei o parcela do carro" / "não tenho mais academia"
→ deactivate_recurring(user_phone=<user_phone>, name="Netflix")

## CICLO DE SALÁRIO (CLT / PF)

- "meu salário é todo dia X" / "recebo no dia X" / "salário cai dia X":
    set_salary_day(user_phone=<user_phone>, salary_day=X)

- "como estou no ciclo?" / "quanto tenho por dia?" / "como tá meu mês?" / "quanto gastei no ciclo?":
    get_salary_cycle(user_phone=<user_phone>)

- "vai sobrar?" / "vai ter dinheiro até o fim do mês?" / "vai faltar?" / "quanto vai sobrar?":
    will_i_have_leftover(user_phone=<user_phone>)

Após salvar: confirme com feedback curto + insight se relevante.
Se get_month_comparison ou get_week_summary retornar alertas (⚠️), destaque-os na resposta.
NUNCA mostre JSON. SEMPRE PT-BR informal.
"""

atlas_agent = Agent(
    name="atlas",
    description="ATLAS — Assistente financeiro pessoal via WhatsApp",
    instructions=ATLAS_INSTRUCTIONS,
    model=get_model(),
    db=db,
    add_history_to_context=True,
    num_history_runs=6,
    tools=[get_user, update_user_name, update_user_income, save_transaction, get_last_transaction, update_last_transaction, get_month_summary, get_month_comparison, get_week_summary, get_today_total, get_transactions, get_category_breakdown, get_installments_summary, can_i_buy, create_goal, get_goals, add_to_goal, get_financial_score, set_salary_day, get_salary_cycle, will_i_have_leftover, register_card, get_cards, close_bill, set_future_bill, register_recurring, get_recurring, deactivate_recurring, get_next_bill],
    add_datetime_to_context=True,
    markdown=True,
)

# ============================================================
# AGENT OS — Runtime FastAPI
# ============================================================

agent_os = AgentOS(
    id="atlas",
    description="ATLAS — Assistente financeiro pessoal via WhatsApp",
    agents=[atlas_agent, parse_agent, response_agent],
    cors_allowed_origins=["*"],
)

app = agent_os.get_app()

# ============================================================
# CORS — AgentOS define allow_credentials=True que bloqueia "*"
# ============================================================
from starlette.middleware.cors import CORSMiddleware

app.user_middleware = [m for m in app.user_middleware if m.cls is not CORSMiddleware]
app.middleware_stack = None
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.build_middleware_stack()

# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "atlas-agno-api",
        "db": DB_TYPE,
        "agents": ["atlas", "parse_agent", "response_agent"],
        "model": "gpt-4.1-mini",
    }


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    agent_os.serve(
        app="agno_api.agent:app",
        host="0.0.0.0",
        port=7777,
        reload=True,
    )
