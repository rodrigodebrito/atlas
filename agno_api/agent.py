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
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

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

def _now_br() -> datetime:
    """Retorna datetime atual no fuso de Brasília (UTC-3)."""
    return datetime.now(timezone.utc) - timedelta(hours=3)

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
            reminder_days_before INTEGER DEFAULT 3,
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

        CREATE TABLE IF NOT EXISTS pending_statement_imports (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            card_name TEXT DEFAULT '',
            bill_month TEXT DEFAULT '',
            transactions_json TEXT NOT NULL,
            insights TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            imported_at TEXT DEFAULT NULL,
            expires_at TEXT NOT NULL
        );
    """)
    conn.commit()
    # Migrations
    for migration in [
        "ALTER TABLE users ADD COLUMN salary_day INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN reminder_days_before INTEGER DEFAULT 3",
        "ALTER TABLE transactions ADD COLUMN card_id TEXT DEFAULT NULL",
        "ALTER TABLE transactions ADD COLUMN installment_group_id TEXT DEFAULT NULL",
        "ALTER TABLE transactions ADD COLUMN import_source TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass
    # Tabela de regras merchant→categoria (memória de categorização)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS merchant_category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            merchant_pattern TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, merchant_pattern)
        );
    """)
    conn.commit()
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
            reminder_days_before INTEGER DEFAULT 3,
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_statement_imports (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            card_name TEXT DEFAULT '',
            bill_month TEXT DEFAULT '',
            transactions_json TEXT NOT NULL,
            insights TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            imported_at TEXT DEFAULT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    # Migrations
    for migration in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_days_before INTEGER DEFAULT 3",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS card_id TEXT DEFAULT NULL",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS installment_group_id TEXT DEFAULT NULL",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS import_source TEXT DEFAULT NULL",
    ]:
        try:
            cur.execute(migration)
        except Exception:
            pass
    # Tabela de regras merchant→categoria (memória de categorização)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS merchant_category_rules (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            merchant_pattern TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT DEFAULT (now()::text),
            UNIQUE(user_id, merchant_pattern)
        );
    """)
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
# MODELOS PYDANTIC — Statement Parser
# ============================================================

class ParsedTransaction(BaseModel):
    date: str = Field(description="Data da compra YYYY-MM-DD")
    merchant: str = Field(description="Nome do estabelecimento")
    amount: float = Field(description="Valor em reais (sempre positivo)")
    type: str = Field(default="debit", description="'debit' para compras, 'credit' para estornos/devoluções")
    category: str = Field(description="Categoria ATLAS ou 'Indefinido' se incerto")
    installment: str = Field(default="", description="Ex: '2/6' se parcelado, '' se à vista")
    confidence: float = Field(default=1.0, description="Confiança na categoria: 0.0-1.0")

class StatementParseResult(BaseModel):
    transactions: List[ParsedTransaction] = Field(default_factory=list)
    bill_month: str = Field(default="", description="Mês da fatura YYYY-MM")
    total: float = Field(default=0.0, description="Total da fatura em reais")
    card_name: str = Field(default="", description="Nome do cartão detectado na imagem")

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
    occurred_at: str = "",
) -> str:
    """
    Salva uma transação financeira no banco de dados.
    transaction_type: EXPENSE ou INCOME
    amount: valor da PARCELA em reais (se à vista = valor total). PRESERVE centavos.
            Ex: "gastei 45" → amount=45, "R$1.200" → amount=1200, "42,54" → amount=42.54, "R$8,90" → amount=8.9
    installments: número de parcelas (1 = à vista)
    total_amount: valor TOTAL da compra em reais (preencher se parcelado)
    card_name: nome do cartão de crédito se usado (ex: "Nubank"). Deixar vazio para débito/PIX/dinheiro.
    occurred_at: data da transação no formato YYYY-MM-DD. Deixar vazio para hoje.
                 "ontem" → calcule ontem, "anteontem" → 2 dias atrás, "segunda" → última segunda, etc.

    Categorias EXPENSE: Alimentação | Transporte | Moradia | Saúde | Lazer |
                        Educação | Assinaturas | Vestuário | Investimento | Pets | Outros
    Pets: remédio veterinário, consulta vet, ração, petshop, banho/tosa — qualquer gasto com animal
    Categorias INCOME:  Salário | Freelance | Aluguel Recebido |
                        Investimentos | Benefício | Venda | Outros

    Exemplos:
    - "gastei 45 no iFood" → amount=45, installments=1
    - "gastei ontem 30 no restaurante" → amount=30, occurred_at="2026-03-02" (data de ontem)
    - "paguei 120 no mercado" → amount=120, installments=1
    - "paguei 42,54 no mercado" → amount=42.54  ← NUNCA arredonde centavos
    - "gastei R$8,90 no café" → amount=8.9      ← NUNCA arredonde centavos
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

    # Resolve card_id — cria cartão automaticamente se não existir
    card_id = None
    card_is_new = False
    card_closing_day = 0
    card_due_day = 0
    card_display_name = card_name
    if card_name:
        card = _find_card(cur, user_id, card_name)
        if card:
            card_id = card[0]
            card_display_name = card[1]
            card_closing_day = card[2]
            card_due_day = card[3]
        else:
            card_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO credit_cards (id, user_id, name, closing_day, due_day) VALUES (?, ?, ?, 0, 0)",
                (card_id, user_id, card_name)
            )
            card_is_new = True
        if not payment_method:
            payment_method = "CREDIT"

    tx_id = str(uuid.uuid4())
    # Usa a data informada pelo modelo ou fallback para agora em BRT
    if occurred_at:
        try:
            if len(occurred_at) == 10:
                base_dt = datetime.fromisoformat(occurred_at + "T12:00:00")
            else:
                base_dt = datetime.fromisoformat(occurred_at[:19])
        except Exception:
            base_dt = _now_br()
    else:
        base_dt = _now_br()

    if installments > 1:
        # Cria um registro por parcela, cada um com occurred_at no mês correto
        group_id = tx_id  # 1ª parcela é o anchor do grupo
        for i in range(1, installments + 1):
            inst_id = tx_id if i == 1 else str(uuid.uuid4())
            # Desloca o mês: parcela i = base_dt + (i-1) meses
            target_month = base_dt.month + (i - 1)
            target_year = base_dt.year + (target_month - 1) // 12
            target_month = ((target_month - 1) % 12) + 1
            target_day = min(base_dt.day, calendar.monthrange(target_year, target_month)[1])
            inst_dt = base_dt.replace(year=target_year, month=target_month, day=target_day)
            inst_occurred = inst_dt.strftime("%Y-%m-%dT%H:%M:%S")
            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, total_amount_cents, installments, installment_number,
                    category, merchant, payment_method, notes, occurred_at, card_id, installment_group_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (inst_id, user_id, transaction_type, amount_cents, total_amount_cents,
                 installments, i, category, merchant, payment_method, notes,
                 inst_occurred, card_id, group_id),
            )
    else:
        now = base_dt.strftime("%Y-%m-%dT%H:%M:%S")
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

    # Monta sufixo do cartão
    card_suffix = ""
    next_bill_warning = ""
    ask_closing = ""

    if card_name:
        card_suffix = f" ({card_display_name})"
        today_day = _now_br().day
        if card_closing_day > 0:
            # Detecta se cai na fatura atual ou próxima
            if today_day > card_closing_day:
                next_bill_warning = f"\n⚠️ Atenção: fatura do {card_display_name} já fechou (dia {card_closing_day}) — cai na *próxima fatura*."
            # Aviso de vencimento próximo (dentro de 5 dias)
            elif card_due_day > 0:
                days_to_due = card_due_day - today_day
                if 0 <= days_to_due <= 5:
                    next_bill_warning = f"\n🔔 Lembrete: fatura do {card_display_name} vence em {days_to_due} dia(s) (dia {card_due_day})."
        elif card_is_new:
            ask_closing = (
                f"\n\nPara rastrear sua fatura certinho, me diz:\n"
                f"📅 Qual o fechamento e vencimento do {card_display_name}?\n"
                f"Ex: _\"fecha 25 vence 10\"_ — prometo que não pergunto mais 😄"
            )

    # Calcula label de data (usa a data da 1ª parcela = base_dt)
    tx_date = base_dt.strftime("%Y-%m-%d")
    today_str = _now_br().strftime("%Y-%m-%d")
    yesterday_str = (_now_br() - timedelta(days=1)).strftime("%Y-%m-%d")
    if tx_date == today_str:
        date_label = f"{tx_date[8:10]}/{tx_date[5:7]}/{tx_date[:4]} (hoje)"
    elif tx_date == yesterday_str:
        date_label = f"{tx_date[8:10]}/{tx_date[5:7]}/{tx_date[:4]} (ontem)"
    else:
        date_label = f"{tx_date[8:10]}/{tx_date[5:7]}/{tx_date[:4]}"

    # Linha de merchant/cartão
    merchant_parts = []
    if merchant:
        merchant_parts.append(merchant)
    if card_name:
        merchant_parts.append(card_display_name)

    # Monta resposta WhatsApp formatada
    if transaction_type == "INCOME":
        lines = [f"💰 *R${amount_cents/100:,.2f}* registrado — {category}".replace(",", ".")]
        if merchant:
            lines[0] += f" ({merchant})"
    elif installments > 1:
        parcela_fmt = f"R${amount_cents/100:,.2f}".replace(",", ".")
        total_fmt = f"R${total_amount_cents/100:,.2f}".replace(",", ".")
        lines = [f"✅ *{parcela_fmt}/mês × {installments}x* — {category}"]
        detail_parts = merchant_parts + [f"_{total_fmt} total_"]
        lines.append("📍 " + "  •  ".join(detail_parts))
        lines.append(f"📅 {date_label}")
        lines.append('_Errou? → "corrige" ou "apaga"_')
    else:
        lines = [f"✅ *R${amount_cents/100:,.2f} — {category}*".replace(",", ".")]
        if merchant_parts:
            lines.append("📍 " + "  •  ".join(merchant_parts))
        lines.append(f"📅 {date_label}")
        lines.append('_Errou? → "corrige" ou "apaga"_')

    result = "\n".join(lines)

    if next_bill_warning:
        result += next_bill_warning
    if ask_closing:
        result += ask_closing
    if card_is_new and not ask_closing:
        result += f"\n_Cartão {card_display_name} criado automaticamente. Para rastrear a fatura, diga o fechamento e vencimento._"

    return result


@tool
def get_month_summary(user_phone: str, month: str = "", filter_type: str = "ALL") -> str:
    """
    Retorna resumo financeiro do mês. month no formato YYYY-MM (ex: 2026-03).
    filter_type: "ALL" (padrão), "EXPENSE" (só gastos), "INCOME" (só receitas/ganhos).
    Se não informado, usa o mês atual.
    """
    if not month:
        month = _now_br().strftime("%Y-%m")

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma transação encontrada. Comece registrando um gasto!"

    user_id, user_name = row

    # Totals per type (for income)
    cur.execute(
        """SELECT type, category, SUM(amount_cents) as total
           FROM transactions
           WHERE user_id = ? AND occurred_at LIKE ?
           GROUP BY type, category
           ORDER BY total DESC""",
        (user_id, f"{month}%"),
    )
    rows = cur.fetchall()

    # Individual transactions — caixa: pelo mês de occurred_at
    #                           crédito: pelo mês de vencimento da fatura (_compute_due_month)
    m_year_i, m_month_i = int(month[:4]), int(month[5:7])
    prev_m_year = m_year_i if m_month_i > 1 else m_year_i - 1
    prev_m_month = m_month_i - 1 if m_month_i > 1 else 12
    prev_month_str = f"{prev_m_year}-{prev_m_month:02d}"

    cur.execute(
        """SELECT t.category, t.merchant, t.amount_cents, t.occurred_at,
                  t.card_id, t.installments, t.installment_number,
                  NULL, NULL, NULL, t.total_amount_cents
           FROM transactions t
           WHERE t.user_id = ? AND t.type = 'EXPENSE' AND t.card_id IS NULL
           AND t.occurred_at LIKE ?
           ORDER BY t.category, t.amount_cents DESC""",
        (user_id, f"{month}%"),
    )
    cash_tx_rows = cur.fetchall()

    cur.execute(
        """SELECT t.category, t.merchant, t.amount_cents, t.occurred_at,
                  t.card_id, t.installments, t.installment_number,
                  c.name, c.closing_day, c.due_day, t.total_amount_cents
           FROM transactions t
           LEFT JOIN credit_cards c ON t.card_id = c.id
           WHERE t.user_id = ? AND t.type = 'EXPENSE' AND t.card_id IS NOT NULL
           AND (t.occurred_at LIKE ? OR t.occurred_at LIKE ?)
           ORDER BY t.category, t.amount_cents DESC""",
        (user_id, f"{month}%", f"{prev_month_str}%"),
    )
    tx_rows = cash_tx_rows + [
        r for r in cur.fetchall()
        if _compute_due_month(r[3], r[8] or 0, r[9] or 0) == month
    ]

    # Date range of the month's transactions
    cur.execute(
        "SELECT MIN(occurred_at), MAX(occurred_at) FROM transactions WHERE user_id = ? AND occurred_at LIKE ?",
        (user_id, f"{month}%"),
    )
    date_range = cur.fetchone()

    conn.close()

    if not rows:
        return f"Nenhuma transação em {month}."

    income = sum(r[2] for r in rows if r[0] == "INCOME")
    expenses = sum(r[2] for r in rows if r[0] == "EXPENSE")

    # Separa gastos em caixa (débito/PIX/dinheiro) e crédito (cartão)
    # card_id IS NULL → caixa (sai do banco agora)
    # card_id NOT NULL → crédito (sai do banco quando a fatura vencer)
    cash_expenses = 0
    credit_expenses = 0

    # Month label
    months_pt = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    try:
        y, m_num = map(int, month.split("-"))
        month_label = f"{months_pt[m_num]}/{y}"
    except Exception:
        month_label = month

    # Date range label
    date_label = ""
    if date_range and date_range[0] and date_range[1]:
        d_start = date_range[0][:10]
        d_end = date_range[1][:10]
        try:
            d1 = f"{d_start[8:10]}/{d_start[5:7]}"
            d2 = f"{d_end[8:10]}/{d_end[5:7]}"
            date_label = f" ({d1} a {d2})"
        except Exception:
            pass

    # Group individual transactions by category, anotando crédito
    # Toda transação de crédito em tx_rows já passou pelo filtro _compute_due_month == month,
    # portanto pertence ao ciclo desta fatura e abate o saldo normalmente.
    from collections import defaultdict, Counter
    cat_txs: dict = defaultdict(list)
    cat_totals_display: dict = defaultdict(int)
    day_totals: dict = defaultdict(int)  # para insight: dia mais gastador
    merchant_freq: Counter = Counter()   # para insight: merchant mais frequente
    for cat, merchant, amount, occurred, card_id, inst_total, inst_num, card_name, closing_day, due_day, total_amt in tx_rows:
        label = merchant.strip() if merchant and merchant.strip() else "Sem descrição"
        dt_lbl = f"{occurred[8:10]}/{occurred[5:7]}" if occurred and len(occurred) >= 10 else ""
        day_totals[occurred[:10]] += amount
        if merchant and merchant.strip():
            merchant_freq[merchant.strip()] += 1
        if card_id:
            credit_expenses += amount
            if closing_day and due_day:
                due_lbl = _month_label_pt(_compute_due_month(occurred, closing_day, due_day))
            else:
                due_lbl = "?"
            short_card = card_name.split()[0] if card_name else "cartão"
            # Label mostra o total da compra se parcelado (contexto), mas amount é a parcela do mês
            if inst_total and inst_total > 1 and total_amt and total_amt > amount:
                inst_suffix = f" R${total_amt/100:,.2f} em {inst_total}x (R${amount/100:,.2f}/parc.)".replace(",", ".")
            else:
                inst_suffix = f" R${amount/100:,.2f}".replace(",", ".")
            item = f"• {dt_lbl} — {label}:{inst_suffix} 💳 fat. {short_card} ({due_lbl})"
        else:
            cash_expenses += amount
            item = f"• {dt_lbl} — {label}: R${amount/100:,.2f}".replace(",", ".")
        cat_totals_display[cat] += amount
        cat_txs[cat].append((occurred, amount, item))

    # Category emoji map
    cat_emoji = {
        "Alimentação": "🍽️", "Transporte": "🚗", "Saúde": "💊",
        "Moradia": "🏠", "Lazer": "🎮", "Assinaturas": "📱",
        "Educação": "📚", "Vestuário": "👟", "Investimento": "📈",
        "Outros": "📦",
    }

    # Saldo: caixa + crédito do mês (toda parcela em tx_rows pertence ao ciclo desta fatura)
    balance = income - cash_expenses - credit_expenses

    # Filter type label
    filter_label = {"EXPENSE": " — apenas gastos", "INCOME": " — apenas receitas", "ALL": ""}.get(filter_type, "")
    lines = [f"*{user_name}*, seu resumo de *{month_label}*{date_label}{filter_label}:"]
    lines.append("")

    income_rows_detail = [(r[1], r[2]) for r in rows if r[0] == "INCOME"]
    total_expenses = cash_expenses + credit_expenses

    if filter_type in ("ALL", "EXPENSE") and cat_totals_display:
        for cat, total in sorted(cat_totals_display.items(), key=lambda x: -x[1]):
            pct = total / total_expenses * 100 if total_expenses else 0
            emoji = cat_emoji.get(cat, "💸")
            lines.append(f"{emoji} *{cat}* — R${total/100:,.2f} ({pct:.0f}%)".replace(",", "."))
            # Ordena por data, depois por valor desc
            for _occ, _amt, item_line in sorted(cat_txs.get(cat, []), key=lambda x: (x[0], -x[1])):
                lines.append(f"  {item_line}")
            lines.append("")

        if credit_expenses > 0:
            lines.append(
                f"💸 *Total gasto: R${total_expenses/100:,.2f}*"
                f"  (R${cash_expenses/100:,.2f} à vista · R${credit_expenses/100:,.2f} 💳 cartão)".replace(",", ".")
            )
        else:
            lines.append(f"💸 *Total gasto: R${total_expenses/100:,.2f}*".replace(",", "."))

    if filter_type in ("ALL", "INCOME") and income_rows_detail:
        lines.append("")
        for cat, total in sorted(income_rows_detail, key=lambda x: -x[1]):
            lines.append(f"💰 *{cat}* — R${total/100:,.2f}".replace(",", "."))
        lines.append(f"💰 *Total recebido: R${income/100:,.2f}*".replace(",", "."))

    if filter_type == "ALL":
        lines.append(f"{'✅' if balance >= 0 else '⚠️'} Saldo: *R${balance/100:,.2f}*".replace(",", "."))

    # Nenhuma receita lançada
    if filter_type == "ALL" and income == 0:
        try:
            _mo_lbl = months_pt[m_num].lower()
        except Exception:
            _mo_lbl = month
        lines.append(f"Você ainda não lançou receitas em {_mo_lbl}.")

    # Largest category for model insight
    top_cat_name, top_pct_val = "", 0.0
    if filter_type in ("ALL", "EXPENSE") and cat_totals_display:
        top_cat, top_total = sorted(cat_totals_display.items(), key=lambda x: -x[1])[0]
        top_pct = top_total / total_expenses * 100 if total_expenses else 0
        top_cat_name, top_pct_val = top_cat, top_pct
        lines.append(f"__top_category:{top_cat}:{top_pct:.0f}%")
    elif income_rows_detail:
        top_cat, top_total = sorted(income_rows_detail, key=lambda x: -x[1])[0]
        top_pct = top_total / income * 100 if income else 0
        top_cat_name, top_pct_val = top_cat, top_pct
        lines.append(f"__top_category:{top_cat}:{top_pct:.0f}%")

    # __insight: dia mais gastador + merchant mais frequente
    insight_parts = []
    if day_totals:
        top_day = max(day_totals, key=day_totals.get)
        top_day_lbl = f"{top_day[8:10]}/{top_day[5:7]}"
        top_day_val = day_totals[top_day] / 100
        insight_parts.append(f"dia_top={top_day_lbl} R${top_day_val:,.2f}".replace(",", "."))
    if merchant_freq:
        top_merchant, top_count = merchant_freq.most_common(1)[0]
        if top_count >= 2:
            insight_parts.append(f"frequente={top_merchant} ({top_count}x)")
    if top_cat_name:
        insight_parts.append(f"cat_top={top_cat_name} ({top_pct_val:.0f}%)")
    if insight_parts:
        lines.append(f"__insight:{' | '.join(insight_parts)}")

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
        return "is_new=True | name=None | has_income=False | monthly_income=0 | transaction_count=0 | salary_day=0 | __status:new_user"

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
    return f"OK — renda mensal de R${monthly_income_cents/100:.2f} salva. Agora envie a mensagem de boas-vindas conforme as instruções."


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

    today_str = _now_br().strftime("%Y-%m-%dT%H:%M:%S")

    # Parcelas com group_id (novo sistema): busca anchor (installment_number=1) de grupos ativos
    cur.execute(
        """SELECT installment_group_id, merchant, category, amount_cents, total_amount_cents, installments
           FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND installment_group_id IS NOT NULL
             AND installment_number = 1
           ORDER BY occurred_at DESC""",
        (user_id,),
    )
    group_anchors = cur.fetchall()

    # Parcelas sem group_id (sistema legado): cálculo por offset de mês
    cur.execute(
        """SELECT merchant, category, amount_cents, total_amount_cents, installments, occurred_at
           FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND installments > 1
             AND installment_group_id IS NULL
           ORDER BY occurred_at DESC""",
        (user_id,),
    )
    legacy_rows = cur.fetchall()
    conn.close()

    if not group_anchors and not legacy_rows:
        return "Nenhuma compra parcelada registrada."

    total_monthly = 0
    total_commitment = 0
    lines = ["💳 Compras parceladas:"]

    # Novo sistema: conta registros futuros do grupo
    conn2 = _get_conn()
    cur2 = conn2.cursor()
    for group_id, merchant, category, parcela, total, n_parcelas in group_anchors:
        cur2.execute(
            "SELECT COUNT(*) FROM transactions WHERE installment_group_id = ? AND occurred_at > ?",
            (group_id, today_str),
        )
        pending = cur2.fetchone()[0]
        if pending == 0:
            continue  # todas já vencidas
        nome = merchant or category
        restante = parcela * (pending + 1)  # pending futuras + a de hoje (corrente)
        # Parcela corrente = a que tem occurred_at <= hoje mais recente
        cur2.execute(
            "SELECT occurred_at FROM transactions WHERE installment_group_id = ? AND occurred_at <= ? ORDER BY occurred_at DESC LIMIT 1",
            (group_id, today_str),
        )
        cur_row = cur2.fetchone()
        parcelas_restantes = pending + (1 if cur_row else 0)
        restante = parcela * parcelas_restantes
        total_monthly += parcela
        total_commitment += restante
        lines.append(
            f"\n  🛍️ {nome} ({category})"
            f"\n     R${parcela/100:.2f}/mês × {parcelas_restantes} parcelas restantes"
            f"\n     Restante: R${restante/100:.2f} de R${total/100:.2f} total"
        )
    conn2.close()

    # Sistema legado: offset de mês
    current_month = _now_br().strftime("%Y-%m")
    for merchant, category, parcela, total, n_parcelas, occurred_at in legacy_rows:
        purchase_month = occurred_at[:7]
        py, pm = map(int, purchase_month.split("-"))
        cy, cm = map(int, current_month.split("-"))
        months_elapsed = (cy - py) * 12 + (cm - pm)
        parcelas_pagas = min(months_elapsed + 1, n_parcelas)
        parcelas_restantes = max(n_parcelas - parcelas_pagas, 0)
        if parcelas_restantes == 0:
            continue
        restante = parcela * parcelas_restantes
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


@tool(description="""Corrige a última transação registrada.
Para corrigir parcelamento: passe APENAS installments (ex: installments=10).
Para corrigir valor: passe APENAS amount com o valor TOTAL em reais (ex: amount=150).
Para corrigir merchant/local: passe merchant (ex: merchant="Magazine Luiza").
Para corrigir categoria: passe category (ex: category="Alimentação").
Aceita qualquer categoria — padrão ou personalizada do usuário.
⚠️ Se o usuário quer mudar a categoria de um ESTABELECIMENTO inteiro (ex: "Talentos é Lazer"),
use update_merchant_category em vez desta — ela atualiza TODAS as transações do merchant.""")
def update_last_transaction(
    user_phone: str,
    installments: int = 0,
    payment_method: str = "",
    category: str = "",
    amount: float = 0,
    merchant: str = "",
) -> str:
    """Corrige a última transação registrada."""
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


@tool(description="""Atualiza a categoria de TODAS as transações de um estabelecimento e salva a regra para futuras importações.
Use quando o usuário disser: "HELIO RODRIGUES é alimentação", "muda Talentos pra Lazer", "X é categoria Y".
Isso atualiza TODAS as transações existentes desse merchant E memoriza para futuras faturas.
Categorias padrão: Alimentação, Transporte, Saúde, Moradia, Lazer, Assinaturas, Educação, Vestuário, Investimento, Pets, Outros.
O usuário também pode criar categorias personalizadas (ex: "Freelance", "Pix Pessoal", "Bebê").""")
def update_merchant_category(user_phone: str, merchant_query: str, category: str) -> str:
    """Atualiza categoria de todas as transações de um merchant e salva regra."""

    try:
        conn = _get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return "ERRO: usuário não encontrado."
        user_id = row[0]

        # Atualiza TODAS as transações que contêm o merchant (case-insensitive)
        pattern = f"%{merchant_query}%"
        cur.execute(
            "UPDATE transactions SET category=? WHERE user_id=? AND LOWER(merchant) LIKE LOWER(?)",
            (category, user_id, pattern)
        )
        updated = cur.rowcount

        # Salva/atualiza a regra para futuras importações (UPSERT)
        merchant_key = merchant_query.upper().strip()
        if DB_TYPE == "postgres":
            cur.execute(
                """INSERT INTO merchant_category_rules (user_id, merchant_pattern, category)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, merchant_pattern) DO UPDATE SET category = EXCLUDED.category""",
                (user_id, merchant_key, category)
            )
        else:
            cur.execute(
                """INSERT INTO merchant_category_rules (user_id, merchant_pattern, category)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, merchant_pattern) DO UPDATE SET category = excluded.category""",
                (user_id, merchant_key, category)
            )
        conn.commit()
        conn.close()

        return f"✅ *{updated} transação(ões)* de _{merchant_query}_ atualizadas para *{category}*.\n📝 Regra salva: nas próximas faturas, _{merchant_query}_ será automaticamente categorizado como *{category}*."

    except Exception as e:
        return f"ERRO: {str(e)}"


@tool
def delete_last_transaction(user_phone: str) -> str:
    """
    Apaga a última transação registrada pelo usuário.
    Use quando o usuário disser 'apaga', 'cancela', 'exclui', 'foi erro', 'não era isso'.
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "Nenhuma transação encontrada."
    cur.execute(
        "SELECT id, amount_cents, total_amount_cents, installments, category, merchant, installment_group_id FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma transação para apagar."
    tx_id, amount_cents, total_cents, installments, category, merchant, group_id = row
    merchant_info = f" ({merchant})" if merchant else ""

    if group_id:
        # Parcelado novo sistema: apaga todas as parcelas do grupo
        cur.execute("DELETE FROM transactions WHERE installment_group_id = ?", (group_id,))
        conn.commit()
        conn.close()
        total_fmt = f"R${total_cents/100:.2f}" if total_cents else f"R${amount_cents*installments/100:.2f}"
        return f"✅ Apagado! {installments}x {category}{merchant_info} ({total_fmt} total) removido."
    else:
        cur.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
        conn.close()
        return f"✅ Apagado! R${amount_cents/100:.2f} {category}{merchant_info} removido."


@tool
def get_today_total(user_phone: str, filter_type: str = "EXPENSE", days: int = 1) -> str:
    """
    Retorna movimentações de hoje (ou dos últimos N dias) com lançamentos por categoria.
    filter_type: "EXPENSE" (padrão, só gastos), "INCOME" (só receitas), "ALL" (tudo).
    days: 1 = só hoje (padrão), 3 = últimos 3 dias, 7 = últimos 7 dias, etc.
    Exemplos: "gastos dos últimos 3 dias" → days=3, "o que gastei ontem" → days=2 filter_type=EXPENSE
    """
    today = _now_br()

    # Gera lista de datas (hoje até N dias atrás)
    date_list = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    if days == 1:
        period_label = f"hoje ({today.strftime('%d/%m/%Y')})"
    elif days == 2:
        yesterday = (today - timedelta(days=1)).strftime("%d/%m")
        period_label = f"ontem e hoje ({yesterday} a {today.strftime('%d/%m')})"
    else:
        start = date_list[-1]
        period_label = f"últimos {days} dias ({start[8:10]}/{start[5:7]} a {today.strftime('%d/%m')})"

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma movimentação registrada ainda."

    user_id, user_name = row

    date_conditions = " OR ".join(["t.occurred_at LIKE ?" for _ in date_list])
    date_params = tuple(f"{d}%" for d in date_list)

    type_filter = "" if filter_type == "ALL" else f"AND t.type = '{filter_type}'"
    cur.execute(
        f"""SELECT t.type, t.category, t.merchant, t.amount_cents,
                   t.card_id, t.occurred_at, t.installments, t.installment_number,
                   c.name as card_name, c.closing_day, c.due_day, t.total_amount_cents
            FROM transactions t
            LEFT JOIN credit_cards c ON t.card_id = c.id
            WHERE t.user_id = ? {type_filter} AND ({date_conditions})
            ORDER BY t.amount_cents DESC""",
        (user_id,) + date_params,
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        label_map = {"EXPENSE": "gastos", "INCOME": "receitas", "ALL": "movimentações"}
        return f"Nenhum(a) {label_map.get(filter_type, 'movimentação')} nos {period_label}."

    from collections import defaultdict
    cat_emoji = {
        "Alimentação": "🍽️", "Transporte": "🚗", "Saúde": "💊",
        "Moradia": "🏠", "Lazer": "🎮", "Assinaturas": "📱",
        "Educação": "📚", "Vestuário": "👟", "Investimento": "📈",
        "Pets": "🐾", "Outros": "📦", "Indefinido": "❓",
    }

    # Separate by type; include card info for expenses
    exp_rows = [r for r in rows if r[0] == "EXPENSE"]
    inc_rows = [(r[1], r[2], r[3]) for r in rows if r[0] == "INCOME"]

    filter_label = {"EXPENSE": " — apenas gastos", "INCOME": " — apenas receitas", "ALL": ""}.get(filter_type, "")
    lines = [f"*{user_name}*, suas movimentações — {period_label}{filter_label}:"]
    lines.append("")

    def build_exp_block(tx_list, ref_total):
        cat_totals: dict = defaultdict(int)
        cat_txs: dict = defaultdict(list)
        cash_total = 0
        credit_total = 0
        for _, cat, merchant, amount, card_id, occurred, inst_total, inst_num, card_name, closing_day, due_day, total_amt in tx_list:
            cat_totals[cat] += amount
            label = merchant.strip() if merchant and merchant.strip() else "Sem descrição"
            if card_id:
                credit_total += amount
                if closing_day and due_day:
                    due_lbl = _month_label_pt(_compute_due_month(occurred, closing_day, due_day))
                else:
                    due_lbl = "?"
                short_card = card_name.split()[0] if card_name else "cartão"
                if inst_total and inst_total > 1 and total_amt and total_amt > amount:
                    inst_suffix = f" R${total_amt/100:,.2f} em {inst_total}x (R${amount/100:,.2f}/parc.)".replace(",", ".")
                else:
                    inst_suffix = f" R${amount/100:,.2f}".replace(",", ".")
                item = f"• {label}:{inst_suffix} 💳 fat. {short_card} ({due_lbl})"
            else:
                cash_total += amount
                item = f"• {label}: R${amount/100:,.2f}".replace(",", ".")
            cat_txs[cat].append((amount, item))
        result = []
        for cat, total_cat in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = total_cat / ref_total * 100 if ref_total else 0
            emoji = cat_emoji.get(cat, "💸")
            result.append(f"{emoji} *{cat}* — R${total_cat/100:,.2f} ({pct:.0f}%)".replace(",", "."))
            for _amt, item_line in sorted(cat_txs[cat], key=lambda x: -x[0]):
                result.append(f"  {item_line}")
            result.append("")
        return cat_totals, result, cash_total, credit_total

    def build_inc_block(tx_list, ref_total):
        cat_totals: dict = defaultdict(int)
        cat_txs: dict = defaultdict(list)
        for cat, merchant, amount in tx_list:
            cat_totals[cat] += amount
            label = merchant.strip() if merchant and merchant.strip() else "Sem descrição"
            cat_txs[cat].append((label, amount))
        result = []
        for cat, total_cat in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = total_cat / ref_total * 100 if ref_total else 0
            result.append(f"💰 *{cat}* — R${total_cat/100:,.2f} ({pct:.0f}%)".replace(",", "."))
            for label, amt in cat_txs[cat]:
                result.append(f"  • {label}: R${amt/100:,.2f}".replace(",", "."))
            result.append("")
        return cat_totals, result

    top_cat_name, top_pct_val = "", 0.0

    if filter_type in ("ALL", "EXPENSE") and exp_rows:
        total_exp = sum(r[3] for r in exp_rows)
        cat_totals_exp, exp_block, cash_tot, credit_tot = build_exp_block(exp_rows, total_exp)
        lines.extend(exp_block)
        if credit_tot > 0:
            lines.append(
                f"💸 *Total gastos: R${total_exp/100:,.2f}*"
                f"  (R${cash_tot/100:,.2f} à vista · R${credit_tot/100:,.2f} 💳 crédito)".replace(",", ".")
            )
        else:
            lines.append(f"💸 *Total gastos: R${total_exp/100:,.2f}*".replace(",", "."))
        if cat_totals_exp:
            tc = max(cat_totals_exp, key=lambda x: cat_totals_exp[x])
            top_cat_name, top_pct_val = tc, cat_totals_exp[tc] / total_exp * 100

    if filter_type in ("ALL", "INCOME") and inc_rows:
        total_inc = sum(r[2] for r in inc_rows)
        lines.append("")
        cat_totals_inc, inc_block = build_inc_block(inc_rows, total_inc)
        lines.extend(inc_block)
        lines.append(f"💰 *Total recebido: R${total_inc/100:,.2f}*".replace(",", "."))
        if filter_type == "INCOME" and cat_totals_inc:
            tc = max(cat_totals_inc, key=lambda x: cat_totals_inc[x])
            top_cat_name, top_pct_val = tc, cat_totals_inc[tc] / total_inc * 100

    if top_cat_name:
        lines.append(f"__top_category:{top_cat_name}:{top_pct_val:.0f}%")

    return "\n".join(lines)


@tool(description="Lista TODAS as transações de um período (dia ou mês). Use SOMENTE quando o usuário pede transações genéricas sem mencionar loja, app ou estabelecimento específico. Exemplos corretos: 'me mostra as transações de hoje', 'extrato de março', 'o que gastei essa semana', 'minhas compras de fevereiro'. NUNCA use quando o usuário mencionar um nome específico (Deville, iFood, Uber, Netflix, etc.) — nesses casos use get_transactions_by_merchant.")
def get_transactions(user_phone: str, date: str = "", month: str = "") -> str:
    """Lista transações por data ou mês. date=YYYY-MM-DD, month=YYYY-MM."""
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma transação encontrada."

    user_id = row[0]

    # Lista flat por período
    if month:
        prefix = month
        label = month
    elif date:
        prefix = date
        label = date
    else:
        prefix = _now_br().strftime("%Y-%m-%d")
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
        month = _now_br().strftime("%Y-%m")

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


@tool(description="Filtra transações por nome de estabelecimento, loja, restaurante, app ou serviço. Use SEMPRE que o usuário mencionar um nome específico. Exemplos: 'quanto gastei no Deville?' → merchant_query='Deville'. 'gastos no iFood esse mês' → merchant_query='iFood', month='2026-03'. 'me mostra o Talentos' → merchant_query='Talentos'. 'histórico do Uber' → merchant_query='Uber'. 'Netflix esse mês' → merchant_query='Netflix'. merchant_query = nome do estabelecimento (busca parcial, case-insensitive).")
def get_transactions_by_merchant(
    user_phone: str,
    merchant_query: str,
    month: str = "",
) -> str:
    """Filtra transações por nome de estabelecimento (busca parcial, case-insensitive)."""
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma transação encontrada."
    user_id = row[0]

    query_like = f"%{merchant_query.lower()}%"

    if month:
        cur.execute(
            """SELECT type, category, amount_cents, merchant, occurred_at
               FROM transactions
               WHERE user_id = ? AND LOWER(merchant) LIKE ? AND occurred_at LIKE ?
               ORDER BY occurred_at DESC""",
            (user_id, query_like, f"{month}%"),
        )
    else:
        cur.execute(
            """SELECT type, category, amount_cents, merchant, occurred_at
               FROM transactions
               WHERE user_id = ? AND LOWER(merchant) LIKE ?
               ORDER BY occurred_at DESC
               LIMIT 20""",
            (user_id, query_like),
        )
    rows = cur.fetchall()
    conn.close()

    months_pt = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                 "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

    if month:
        try:
            m_num = int(month[5:7])
            year = month[:4]
            period = f" — {months_pt[m_num]}/{year}"
        except Exception:
            period = f" — {month}"
    else:
        period = ""

    if not rows:
        return f"Nenhuma transação encontrada para \"{merchant_query}\"{period}."

    total_expense = sum(r[2] for r in rows if r[0] == "EXPENSE")
    total_income  = sum(r[2] for r in rows if r[0] == "INCOME")
    n = len(rows)

    merchant_display = rows[0][3] or merchant_query
    header = f"🔍 *{merchant_display}*{period} — {n} lançamento{'s' if n > 1 else ''}"
    if total_expense:
        header += f"\n💸 Gasto total: *R${total_expense/100:,.2f}*".replace(",", ".")
    if total_income:
        header += f"\n💰 Recebido: *R${total_income/100:,.2f}*".replace(",", ".")

    lines = [header, ""]
    for tx_type, cat, amt, merch, occurred in rows:
        try:
            d = occurred[:10]
            day, m_num2 = int(d[8:10]), int(d[5:7])
            date_str = f"{day:02d}/{months_pt[m_num2]}"
        except Exception:
            date_str = occurred[:10]
        icon = "💰" if tx_type == "INCOME" else "💸"
        lines.append(f"  {icon} R${amt/100:,.2f} — {cat}  •  {date_str}".replace(",", "."))

    return "\n".join(lines)


# ============================================================
# HELPERS — cartões e recorrentes
# ============================================================

def _compute_due_month(occurred_at_str: str, closing_day: int, due_day: int) -> str:
    """Retorna 'YYYY-MM' do mês em que a fatura desta transação vence."""
    try:
        from datetime import date as _date
        txn_date = _date.fromisoformat(occurred_at_str[:10])
    except Exception:
        return ""
    # Em qual ciclo cai?
    if txn_date.day <= closing_day:
        close_yr, close_mo = txn_date.year, txn_date.month
    else:
        close_yr = txn_date.year + (1 if txn_date.month == 12 else 0)
        close_mo = 1 if txn_date.month == 12 else txn_date.month + 1
    # Quando vence este ciclo?
    if due_day > closing_day:
        return f"{close_yr}-{close_mo:02d}"
    else:
        due_yr = close_yr + (1 if close_mo == 12 else 0)
        due_mo = 1 if close_mo == 12 else close_mo + 1
        return f"{due_yr}-{due_mo:02d}"


def _month_label_pt(year_month: str) -> str:
    """'2026-04' → 'abr/26'"""
    _months = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]
    try:
        y, m = int(year_month[:4]), int(year_month[5:7])
        return f"{_months[m - 1]}/{str(y)[2:]}"
    except Exception:
        return year_month


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
    today = _now_br()
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

    # Verifica se já existe (match exato)
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

    # Valida nome único: impede nomes que são substring de outros (causa ambiguidade)
    cur.execute("SELECT name FROM credit_cards WHERE user_id=?", (user_id,))
    all_cards = [r[0] for r in cur.fetchall()]
    name_lower = name.lower()
    for existing_name in all_cards:
        en_lower = existing_name.lower()
        if name_lower in en_lower or en_lower in name_lower:
            conn.close()
            return f"ERRO: Nome '{name}' conflita com cartão '{existing_name}' (substring). Use um nome mais específico para evitar ambiguidade."

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

    today = _now_br()
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
        (_now_br().isoformat(), card[0])
    )
    conn.commit()
    conn.close()
    return f"Fatura do {card[1]} zerada! Novo ciclo iniciado."


@tool
def set_card_bill(user_phone: str, card_name: str, amount: float) -> str:
    """
    Define ou atualiza o valor atual da fatura de um cartão.
    Usar quando usuário disser:
    - "minha fatura do Nubank está em 1300"
    - "altere a fatura do Inter para 800"
    - "o Itaú tem 2500 de fatura"
    Cria o cartão automaticamente se não existir.
    """
    conn = _get_conn()
    cur = conn.cursor()
    user_id = _get_user_id(cur, user_phone)
    if not user_id:
        conn.close()
        return "ERRO: usuário não encontrado."

    amount_cents = round(amount * 100)
    card = _find_card(cur, user_id, card_name)

    if card:
        cur.execute(
            "UPDATE credit_cards SET current_bill_opening_cents = ? WHERE id = ?",
            (amount_cents, card[0])
        )
        name = card[1]
    else:
        card_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO credit_cards (id, user_id, name, closing_day, due_day, current_bill_opening_cents) VALUES (?, ?, ?, 0, 0, ?)",
            (card_id, user_id, card_name, amount_cents)
        )
        name = card_name

    conn.commit()
    conn.close()
    return f"Fatura do {name} registrada: R${amount:.2f}."


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
    today = _now_br().day
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

    today = _now_br()

    # Determina o próximo ciclo de fechamento
    if today.day < closing_day:
        # Ainda não fechou neste mês → próximo fechamento = este mês
        next_close = today.replace(day=closing_day)
    else:
        # Já fechou → próximo fechamento = mês que vem
        y = today.year + (1 if today.month == 12 else 0)
        m = 1 if today.month == 12 else today.month + 1
        d = min(closing_day, calendar.monthrange(y, m)[1])
        next_close = today.replace(year=y, month=m, day=d)

    # "Próxima fatura" = o ciclo que está ABERTO agora e vai fechar em next_close.
    # ex: ML fecha dia 2, hoje dia 4 → ciclo aberto: 02/mar → 02/abr → vence 07/abr
    period_start = _bill_period_start(closing_day)   # início do ciclo atual (último fechamento)
    next_close_str = next_close.strftime("%Y-%m-%d")

    # Mês de referência da fatura = mês em que next_close cai (ex: "2026-04" para fechar dia 2/abr)
    next_month = f"{next_close.year}-{next_close.month:02d}"
    days_until_close = (next_close - today).days  # dias até fechar esta fatura

    # Transações do ciclo atual (desde o último fechamento até o próximo)
    cur.execute(
        """SELECT merchant, category, amount_cents, installments, installment_number, installment_group_id
           FROM transactions
           WHERE user_id = ? AND card_id = ? AND type = 'EXPENSE'
             AND occurred_at >= ? AND occurred_at < ?
           ORDER BY occurred_at""",
        (user_id, card_id, period_start, next_close_str)
    )
    next_cycle_rows = cur.fetchall()

    # Gastos fixos vinculados a este cartão
    cur.execute(
        """SELECT name, amount_cents, category, day_of_month
           FROM recurring_transactions
           WHERE user_id = ? AND card_id = ? AND active = 1""",
        (user_id, card_id)
    )
    recurring_rows = cur.fetchall()

    # Snapshot de fatura (valor pré-registrado via set_future_bill)
    cur.execute(
        "SELECT opening_cents FROM card_bill_snapshots WHERE card_id = ? AND bill_month = ?",
        (card_id, next_month)
    )
    snapshot_row = cur.fetchone()
    snapshot_cents = snapshot_row[0] if snapshot_row else 0

    conn.close()

    installment_items = []
    total_installments = 0
    for merchant, category, parcela, n_parcelas, inst_num, group_id in next_cycle_rows:
        restantes = n_parcelas - inst_num
        nome = merchant or category
        installment_items.append((nome, parcela, inst_num, n_parcelas, restantes))
        total_installments += parcela

    total_recurring = sum(r[1] for r in recurring_rows)
    total_next = snapshot_cents + total_installments + total_recurring

    lines = [f"📅 Próxima fatura estimada — {name} ({next_month})"]
    lines.append(f"   Fecha em {days_until_close} dias (dia {closing_day}/{next_close.month:02d}) • Vence dia {due_day}")
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
    now = _now_br()
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
def get_upcoming_commitments(user_phone: str, days: int = 60, month: str = "") -> str:
    """
    Lista compromissos financeiros nos próximos N dias:
    gastos fixos recorrentes e faturas de cartão que vencem nesse período.
    days: número de dias à frente (padrão 60).
    month: filtro opcional no formato YYYY-MM (ex: "2026-04") para mostrar só aquele mês.
    """
    today = _now_br()
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Usuário não encontrado."
    user_id, user_name = row

    items = []

    # ── Faturas de cartão PRIMEIRO: calcula data correta por ciclo de fechamento ──
    # Isso também constrói card_bill_names para excluir do loop de recorrentes.
    card_bill_names: set = set()
    cur.execute(
        "SELECT id, name, closing_day, due_day, current_bill_opening_cents FROM credit_cards WHERE user_id = ?",
        (user_id,),
    )
    for card_id, card_name, closing_day, due_day, opening_cents in cur.fetchall():
        if not closing_day or not due_day:
            continue

        card_bill_names.add(f"Fatura {card_name}")

        def _get_snapshot(cid, month_str):
            cur.execute(
                "SELECT opening_cents FROM card_bill_snapshots WHERE card_id = ? AND bill_month = ?",
                (cid, month_str),
            )
            r = cur.fetchone()
            return r[0] if r else 0

        def _get_new_purchases(uid, cid, period_start):
            cur.execute(
                "SELECT SUM(amount_cents) FROM transactions WHERE user_id = ? AND card_id = ? AND occurred_at >= ?",
                (uid, cid, period_start),
            )
            return cur.fetchone()[0] or 0

        def _fallback_recurring(uid, cid, cname):
            cur.execute(
                "SELECT amount_cents FROM recurring_transactions WHERE card_id = ? AND active = 1 LIMIT 1",
                (cid,),
            )
            r = cur.fetchone()
            if r:
                return r[0]
            cur.execute(
                "SELECT amount_cents FROM recurring_transactions WHERE user_id = ? AND active = 1 AND LOWER(name) = LOWER(?) LIMIT 1",
                (uid, f"Fatura {cname}"),
            )
            r2 = cur.fetchone()
            return r2[0] if r2 else 0

        # ── CICLO 1: fatura que fechou este mês e ainda não venceu ─────────
        # Quando today.day > closing_day, o cartão fechou neste mês.
        # O vencimento deste ciclo pode ainda estar no futuro.
        if today.day > closing_day:
            if due_day > closing_day:
                # Vencimento no mesmo mês do fechamento (ex: fecha 2, vence 7 → vence 07/03)
                c1_day = min(due_day, calendar.monthrange(today.year, today.month)[1])
                c1_due = today.replace(day=c1_day)
            else:
                # Vencimento no mês seguinte ao fechamento (ex: fecha 25, vence 5 → vence 05/04)
                c1_y = today.year + (1 if today.month == 12 else 0)
                c1_m = 1 if today.month == 12 else today.month + 1
                c1_day = min(due_day, calendar.monthrange(c1_y, c1_m)[1])
                c1_due = today.replace(year=c1_y, month=c1_m, day=c1_day)

            c1_delta = (c1_due - today).days
            if 1 <= c1_delta <= days:
                # Valor = opening_cents (fatura do ciclo que fechou)
                # Snapshot do mês do fechamento sobrepõe opening_cents se existir
                c1_month_str = f"{today.year}-{today.month:02d}"
                c1_snap = _get_snapshot(card_id, c1_month_str)
                c1_amount = c1_snap if c1_snap > 0 else (opening_cents or 0)
                if c1_amount == 0:
                    c1_amount = _fallback_recurring(user_id, card_id, card_name)
                if c1_amount > 0:
                    items.append((c1_due, c1_due.strftime("%d/%m"), "💳", f"Fatura {card_name}", c1_amount))

        # ── CICLO 2: próximo fechamento → próximo vencimento ────────────────
        if today.day <= closing_day:
            next_close_day = min(closing_day, calendar.monthrange(today.year, today.month)[1])
            next_close = today.replace(day=next_close_day)
        else:
            ny = today.year + (1 if today.month == 12 else 0)
            nm = 1 if today.month == 12 else today.month + 1
            next_close_day = min(closing_day, calendar.monthrange(ny, nm)[1])
            next_close = today.replace(year=ny, month=nm, day=next_close_day)

        if due_day > closing_day:
            c2_due = next_close.replace(day=min(due_day, calendar.monthrange(next_close.year, next_close.month)[1]))
        else:
            c2_y = next_close.year + (1 if next_close.month == 12 else 0)
            c2_m = 1 if next_close.month == 12 else next_close.month + 1
            c2_due = next_close.replace(year=c2_y, month=c2_m, day=min(due_day, calendar.monthrange(c2_y, c2_m)[1]))

        c2_delta = (c2_due - today).days
        if 1 <= c2_delta <= days:
            c2_month_str = f"{next_close.year}-{next_close.month:02d}"
            c2_snap = _get_snapshot(card_id, c2_month_str)
            period_start = _bill_period_start(closing_day)
            c2_new = _get_new_purchases(user_id, card_id, period_start)
            if c2_snap > 0:
                # Snapshot é autoritativo (sobrepõe opening_cents)
                c2_amount = c2_snap + c2_new
            elif today.day <= closing_day:
                # Cartão ainda não fechou → opening_cents é o saldo em aberto deste ciclo
                c2_amount = (opening_cents or 0) + c2_new
            else:
                # Cartão já fechou → opening_cents foi para Ciclo 1; próximo ciclo = só compras novas
                c2_amount = c2_new
            if c2_amount == 0:
                c2_amount = _fallback_recurring(user_id, card_id, card_name)
            if c2_amount > 0:
                items.append((c2_due, c2_due.strftime("%d/%m"), "💳", f"Fatura {card_name}", c2_amount))

    # ── Gastos fixos recorrentes (excluindo faturas de cartão já tratadas acima) ──
    for offset in range(1, days + 1):
        target = today + timedelta(days=offset)
        target_day = target.day
        target_date_label = target.strftime("%d/%m")
        # card_id IS NULL: exclui recorrentes vinculados a cartão (tratados pelo loop acima)
        cur.execute(
            "SELECT name, amount_cents FROM recurring_transactions WHERE user_id = ? AND active = 1 AND day_of_month = ? AND card_id IS NULL",
            (user_id, target_day),
        )
        for rec_name, amount_cents in cur.fetchall():
            if rec_name in card_bill_names:  # segurança extra: exclui pelo nome
                continue
            items.append((target, target_date_label, "📋", rec_name, amount_cents))

    conn.close()

    if not items:
        if month:
            return f"Nenhum compromisso encontrado em {month}."
        return f"Nenhum compromisso encontrado nos próximos {days} dias."

    # Sort by date
    items.sort(key=lambda x: x[0])

    # Filtro por mês específico
    if month:
        items = [item for item in items if item[0].strftime("%Y-%m") == month]
        if not items:
            return f"Nenhum compromisso encontrado em {month}."

    total = sum(i[4] for i in items)

    if month:
        try:
            dt = datetime.strptime(month, "%Y-%m")
            months_pt = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
                         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
            period_label = f"{months_pt[dt.month]}/{dt.year}"
        except Exception:
            period_label = month
    elif days == 7:
        period_label = "próxima semana"
    else:
        period_label = f"próximos {days} dias"

    lines = [f"*{user_name}*, seus compromissos em {period_label}:"]
    lines.append("")

    current_month_label = ""
    for target, date_label, emoji, name, amount_cents in items:
        month_label = target.strftime("%B/%Y").capitalize()
        if month_label != current_month_label:
            lines.append(f"📅 *{month_label}*")
            current_month_label = month_label
        lines.append(f"  {emoji} {date_label} — {name}: *R${amount_cents/100:,.2f}*".replace(",", "."))

    lines.append("")
    lines.append(f"💸 *Total previsto: R${total/100:,.2f}*".replace(",", "."))

    return "\n".join(lines)


@tool
def get_week_summary(user_phone: str, filter_type: str = "ALL") -> str:
    """
    Resumo da semana atual (segunda a hoje) com lançamentos por categoria.
    filter_type: "ALL" (padrão), "EXPENSE" (só gastos), "INCOME" (só receitas).
    """
    from collections import defaultdict, Counter
    today = _now_br()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    start_label = monday.strftime("%d/%m/%Y")
    end_label = today.strftime("%d/%m/%Y")

    # Gera os dias da semana (segunda até hoje) como strings YYYY-MM-DD
    week_dates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days_since_monday, -1, -1)
    ]

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhum dado encontrado."
    user_id, user_name = row

    # Usa LIKE para cada dia (mesmo padrão que get_today_total — funciona em SQLite e PostgreSQL)
    date_conditions = " OR ".join(["occurred_at LIKE ?" for _ in week_dates])
    date_params = tuple(f"{d}%" for d in week_dates)

    type_filter = "" if filter_type == "ALL" else f"AND type = '{filter_type}'"
    cur.execute(
        f"""SELECT type, category, merchant, amount_cents, occurred_at
           FROM transactions
           WHERE user_id = ? {type_filter} AND ({date_conditions})
           ORDER BY occurred_at, amount_cents DESC""",
        (user_id,) + date_params,
    )
    tx_rows = cur.fetchall()

    # Totais do mês ANTERIOR por categoria (para alertas com histórico real)
    prev_month_dt = (today.replace(day=1) - timedelta(days=1))
    prev_month = prev_month_dt.strftime("%Y-%m")
    prev_days_in_month = prev_month_dt.day  # dias reais do mês anterior
    cur.execute(
        """SELECT category, SUM(amount_cents) FROM transactions
           WHERE user_id = ? AND type = 'EXPENSE' AND occurred_at LIKE ?
           GROUP BY category""",
        (user_id, f"{prev_month}%"),
    )
    prev_month_totals = {r[0]: r[1] for r in cur.fetchall()}

    conn.close()

    days_elapsed = days_since_monday + 1

    if not tx_rows:
        label_map = {"EXPENSE": "gastos", "INCOME": "receitas", "ALL": "movimentações"}
        return f"Nenhum(a) {label_map.get(filter_type, 'movimentação')} essa semana ainda."

    cat_emoji = {
        "Alimentação": "🍽️", "Transporte": "🚗", "Saúde": "💊",
        "Moradia": "🏠", "Lazer": "🎮", "Assinaturas": "📱",
        "Educação": "📚", "Vestuário": "👟", "Investimento": "📈",
        "Pets": "🐾", "Outros": "📦", "Indefinido": "❓",
    }

    # type, category, merchant, amount_cents, occurred_at
    exp_rows = [(r[1], r[2], r[3], r[4]) for r in tx_rows if r[0] == "EXPENSE"]
    inc_rows = [(r[1], r[2], r[3], r[4]) for r in tx_rows if r[0] == "INCOME"]

    filter_label = {"EXPENSE": " — apenas gastos", "INCOME": " — apenas receitas", "ALL": ""}.get(filter_type, "")
    period = f"{start_label}" if start_label == end_label else f"{start_label} a {end_label}"
    lines = [f"📅 *{user_name}*, sua semana ({period}){filter_label}:"]
    lines.append("")

    top_cat_name, top_pct_val = "", 0.0
    alertas = []

    # Para insights: rastreia gastos por dia e frequência de merchants
    day_totals: dict = defaultdict(int)
    merchant_freq: Counter = Counter()

    def _date_label(occurred_at: str) -> str:
        """Extrai DD/MM do occurred_at."""
        try:
            return f"{occurred_at[8:10]}/{occurred_at[5:7]}"
        except Exception:
            return ""

    def add_cat_block(rows_list, ref_total):
        cat_totals: dict = defaultdict(int)
        cat_txs: dict = defaultdict(list)
        for cat, merchant, amount, occurred in rows_list:
            cat_totals[cat] += amount
            label = merchant.strip() if merchant and merchant.strip() else "Sem descrição"
            dt_lbl = _date_label(occurred)
            cat_txs[cat].append((occurred, dt_lbl, label, amount))
            # Rastreia para insights
            if rows_list is exp_rows_ref:
                day_totals[occurred[:10]] += amount
                if merchant and merchant.strip():
                    merchant_freq[merchant.strip()] += 1
        for cat, total_cat in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = total_cat / ref_total * 100 if ref_total else 0
            emoji = cat_emoji.get(cat, "💸")
            lines.append(f"{emoji} *{cat}* — R${total_cat/100:,.2f} ({pct:.0f}%)".replace(",", "."))
            # Ordena por data, depois por valor desc
            sorted_txs = sorted(cat_txs[cat], key=lambda x: (x[0], -x[3]))
            for occurred, dt_lbl, label, amt in sorted_txs:
                lines.append(f"  • {dt_lbl} — {label}: R${amt/100:,.2f}".replace(",", "."))
            lines.append("")
            # Alerta só se houver histórico do mês anterior para comparar
            prev_val = prev_month_totals.get(cat, 0)
            if prev_val > 0 and days_elapsed > 0:
                daily_pace = total_cat / days_elapsed
                prev_daily_avg = prev_val / prev_days_in_month
                if daily_pace > prev_daily_avg * 1.4:
                    proj = daily_pace * 30
                    alertas.append(f"⚠️ {cat}: ritmo R${proj/100:.0f}/mês vs R${prev_val/100:.0f} em {prev_month_dt.strftime('%b')}")
        return cat_totals

    exp_rows_ref = exp_rows  # referência para add_cat_block saber quais são expenses

    if filter_type in ("ALL", "EXPENSE") and exp_rows:
        total_exp = sum(r[2] for r in exp_rows)
        ct = add_cat_block(exp_rows, total_exp)
        lines.append(f"💸 *Total gastos: R${total_exp/100:,.2f}*".replace(",", "."))
        if ct:
            tc = max(ct, key=lambda x: ct[x])
            top_cat_name, top_pct_val = tc, ct[tc] / total_exp * 100

    if filter_type in ("ALL", "INCOME") and inc_rows:
        total_inc = sum(r[2] for r in inc_rows)
        lines.append("")
        ct = add_cat_block(inc_rows, total_inc)
        lines.append(f"💰 *Total recebido: R${total_inc/100:,.2f}*".replace(",", "."))
        if filter_type == "INCOME" and ct:
            tc = max(ct, key=lambda x: ct[x])
            top_cat_name, top_pct_val = tc, ct[tc] / total_inc * 100

    if alertas:
        lines.append("")
        lines.append("🔔 *Alertas:*")
        lines.extend(alertas)

    # Metadata para o LLM gerar insight personalizado
    if top_cat_name:
        lines.append(f"__top_category:{top_cat_name}:{top_pct_val:.0f}%")

    # __insight: dia mais gastador + merchant mais frequente
    insight_parts = []
    if day_totals:
        top_day = max(day_totals, key=day_totals.get)
        top_day_lbl = f"{top_day[8:10]}/{top_day[5:7]}"
        top_day_val = day_totals[top_day] / 100
        insight_parts.append(f"dia_top={top_day_lbl} R${top_day_val:,.2f}".replace(",", "."))
    if merchant_freq:
        top_merchant, top_count = merchant_freq.most_common(1)[0]
        if top_count >= 2:
            insight_parts.append(f"frequente={top_merchant} ({top_count}x)")
    if top_cat_name:
        insight_parts.append(f"cat_top={top_cat_name} ({top_pct_val:.0f}%)")
    if insight_parts:
        lines.append(f"__insight:{' | '.join(insight_parts)}")

    return "\n".join(lines)


@tool
def can_i_buy(user_phone: str, amount: float, description: str = "") -> str:
    """
    Analisa se o usuário pode fazer uma compra.
    amount: valor da compra em reais (ex: R$250 → amount=250)
    description: o que é a compra (ex: "tênis", "jantar fora", "notebook")
    """
    amount_cents = round(amount * 100)
    today = _now_br()
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
    today = _now_br()
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
    today = _now_br()
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
def set_reminder_days(user_phone: str, days_before: int) -> str:
    """
    Configura quantos dias antes o ATLAS avisa sobre compromissos fixos e faturas de cartão.
    days_before: número de dias de antecedência (1-7). Padrão: 3.
    Use quando o usuário disser:
    - "quero lembrete 2 dias antes"
    - "me avisa com 5 dias de antecedência"
    - "avisa 1 dia antes"
    - "lembrete no dia anterior"
    """
    if not (1 <= days_before <= 7):
        return "Informe um número de dias entre 1 e 7."

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = ?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Usuário não encontrado."

    cur.execute("UPDATE users SET reminder_days_before = ? WHERE phone = ?", (days_before, user_phone))
    conn.commit()
    conn.close()

    label = "amanhã" if days_before == 1 else f"{days_before} dias antes"
    return f"Configurado! Vou te avisar {label} dos seus compromissos e faturas 🔔"


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

    # Fatura atual dos cartões (compromissos já acumulados)
    cur.execute(
        "SELECT name, current_bill_opening_cents, closing_day FROM credit_cards WHERE user_id = ?",
        (user_id,)
    )
    cards = cur.fetchall()
    card_bills_cents = 0
    card_bill_lines = []
    for card_name, opening_cents, closing_day in cards:
        period_start = _bill_period_start(closing_day)
        cur.execute(
            "SELECT SUM(amount_cents) FROM transactions WHERE user_id = ? AND card_id = (SELECT id FROM credit_cards WHERE user_id = ? AND name = ?) AND occurred_at >= ?",
            (user_id, user_id, card_name, period_start)
        )
        new_purchases = cur.fetchone()[0] or 0
        bill_total = (opening_cents or 0) + new_purchases
        if bill_total > 0:
            card_bills_cents += bill_total
            card_bill_lines.append(f"   💳 {card_name}: R${bill_total/100:.2f}")

    # Gastos fixos ativos (que vencem este ciclo)
    cur.execute(
        "SELECT name, amount_cents FROM recurring_transactions WHERE user_id = ? AND active = 1",
        (user_id,)
    )
    recurring = cur.fetchall()
    recurring_cents = sum(v for _, v in recurring)

    conn.close()

    income_to_use = income_real if income_real > 0 else income_cents

    if income_to_use == 0:
        return "Sem renda cadastrada. Registre sua renda primeiro para eu calcular a projeção."

    expenses_cents = sum(v for _, v in category_expenses)
    fixed_commitments = card_bills_cents + recurring_cents

    if expenses_cents == 0 and fixed_commitments == 0:
        return "Nenhum gasto registrado neste ciclo ainda. Anote seus gastos e eu projeto o fim do mês!"

    daily_pace = expenses_cents / max(days_elapsed, 1)
    projected_expenses = daily_pace * days_total
    projected_leftover = income_to_use - projected_expenses - fixed_commitments

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
    lines.append(f"   {days_remaining} dias restantes  •  Renda: R${income_to_use/100:.2f}  •  Gasto até agora: R${expenses_cents/100:.2f}")
    if card_bills_cents > 0:
        lines.append(f"   💳 Faturas a pagar: R${card_bills_cents/100:.2f}")
        for cl in card_bill_lines:
            lines.append(cl)
    if recurring_cents > 0:
        lines.append(f"   📋 Gastos fixos: R${recurring_cents/100:.2f}")
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
        "Assinaturas | Vestuário | Investimento | Pets | Outros"
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

## REGRA — DATA DA TRANSAÇÃO

Se o usuário indicar data diferente de hoje, extraia occurred_at em formato YYYY-MM-DD.
Use a data atual do sistema para calcular:
- "ontem" → hoje - 1 dia
- "anteontem" → hoje - 2 dias
- "sexta", "segunda" etc. → última ocorrência desse dia da semana
- "dia 10", "no dia 5" → esse dia no mês atual (ou anterior se já passou)
- Sem referência de data → occurred_at vazio (salva como hoje)

CRÍTICO — MÚLTIPLOS GASTOS: quando o usuário lista vários gastos com UMA referência de data
("gastei ontem X, Y e Z"), a data se aplica a TODOS os itens da lista.
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
⛔ REGRA ABSOLUTA — LEIA ANTES DE QUALQUER COISA:

Você é um REGISTRADOR DE DADOS, não um consultor ou assistente conversacional.
Seu trabalho: executar o que foi pedido e PARAR. Nada mais.

FORMATO OBRIGATÓRIO de cada resposta:
1. Execute a ação solicitada (tool call)
2. Mostre o resultado
3. FIM. Ponto final. Não acrescente nada.

NUNCA adicione após a resposta:
- Perguntas de qualquer tipo ("Quer...?", "Gostaria...?", "Posso...?", "Deseja...?")
- "Quer ver o resumo das suas faturas?"
- "Quer ver o extrato?"
- "Quer adicionar algum gasto agora?"
- "Quer adicionar mais algum gasto?"
- "Quer que eu te lembre quando a data estiver próxima?"
- "Quer que eu verifique algo específico para abril?"
- "Quer que eu faça isso?"
- "Claro! Estou aqui para ajudar sempre que precisar."
- Sugestões ("Você pode também...", "Que tal...")
- Ofertas de ajuda ("Se precisar de mais...", "Estou aqui para...")
- Comentários sobre os dados ("Parece que você está gastando muito...")
- Análises não solicitadas

Se o usuário pediu para registrar um gasto → registre e PARE.
Se o usuário pediu um resumo → mostre o resumo e PARE.
Se o usuário pediu uma análise → faça a análise e PARE.
SEMPRE PARE após entregar o que foi pedido.

⛔ FIM DA REGRA ABSOLUTA.

⛔ REGRA CRÍTICA — "não" / "nao" / "n" NUNCA É COMANDO DE APAGAR:
Se o usuário responder apenas "não", "nao", "n", "nope", "nada" ou similar:
- Isso significa que ele está recusando algo (uma pergunta anterior, uma sugestão) — NÃO é pedido para apagar transação.
- NUNCA chame delete_last_transaction em resposta a "não"/"nao"/"n" sozinhos.
- Resposta correta: "Ok!" ou "Tudo bem!" e pare.
- delete_last_transaction só deve ser chamado quando o usuário EXPLICITAMENTE pedir: "apaga", "deleta", "remove", "exclui" + contexto de transação.
⛔ FIM DA REGRA.

⛔ REGRA DE FORMATO — TRANSAÇÕES (save_transaction):
A tool save_transaction já retorna o texto FORMATADO para WhatsApp.
Apresente o retorno da tool DIRETAMENTE, sem reescrever, sem adicionar nada.
NÃO reformule. NÃO resuma. NÃO acrescente frases antes ou depois.
⛔ FIM DA REGRA DE FORMATO.

⛔ REGRA — "Anotado!" É EXCLUSIVO DE save_transaction:
"Anotado!" deve aparecer SOMENTE na confirmação de registro de gastos/receitas (save_transaction).
NUNCA use "Anotado!" como prefixo de resposta de consultas (resumos, filtros, análises).
ERRADO: "Anotado! R$171,68 gastos no Deville em março de 2026..."
CERTO: copiar o retorno da tool diretamente.

⛔ REGRA — ZERO FOLLOW-UP APÓS CONSULTAS (SEM EXCEÇÕES):
Após retornar o resultado de get_transactions_by_merchant, get_category_breakdown,
get_month_summary, get_week_summary, get_today_total, get_transactions: PARE. Zero linhas extras.
PROIBIDO (lista atualizada com exemplos reais):
- "Quer que eu detalhe outros gastos do mês?"
- "Quer ver o resumo detalhado de despesas por categoria?"
- "Quer que eu separe por categoria?"
- "Quer ver o total?"
- "Posso mostrar mais?"
- "Gostaria de ver...?"
- "Quer uma análise?"
- Qualquer frase com "Quer que eu...", "Posso...", "Gostaria..."
⛔ PARA get_transactions_by_merchant: também proibido adicionar nome do usuário antes do output.
O output começa com 🔍 — copie a partir do 🔍, não adicione nada antes.

💡 EXCEÇÃO — INSIGHT PARA get_week_summary:
Após copiar o retorno de get_week_summary INTEGRALMENTE, adicione UMA frase curta de insight
no final. Use os dados da linha `__insight:` (NÃO mostre a linha __insight: ao usuário).
A frase deve ser:
- Tom leve, informal, pode ter humor ("Restaurante Talentos tá virando sua segunda casa hein 😄")
- Baseada nos dados reais (dia com mais gastos, merchant mais frequente, categoria top)
- NUNCA invente dados. Use APENAS o que está no __insight.
- Máximo 2 frases. Pode incluir uma sugestão prática curta se fizer sentido.
Remova as linhas que começam com `__` (são metadata interna) antes de enviar.

Você é o ATLAS — assistente financeiro via WhatsApp.
Tom: amigável, direto, informal. Português brasileiro natural.
Use WhatsApp markdown: *negrito*, _itálico_, ~tachado~.
Atende pessoas físicas (CLT, autônomos) e MEI/freelancers.

## REGRAS GLOBAIS DE FORMATO
- UMA mensagem por resposta — nunca divida em múltiplas.
- Máximo 4 linhas para ações simples, 10 para resumos/análises.
- EXCEÇÃO: get_month_summary, get_week_summary, get_today_total, get_transactions_by_merchant, get_category_breakdown, get_transactions — SEM limite de linhas. Copie o retorno da tool INTEGRALMENTE, preservando cada quebra de linha exatamente como está. NUNCA comprima itens numa única linha. NUNCA reformule, NUNCA resuma em prosa.
- NUNCA mostre JSON, dados técnicos ou campos internos.
- NUNCA mencione forma de pagamento se o usuário não informou.
- NUNCA adicione link de plataforma ou site no final das mensagens.
- SEMPRE PT-BR informal.

---

## FORMATO: ADD_EXPENSE (à vista)

Formato em 3 linhas:
```
✅ *R$30,00 — Alimentação*
📍 Restaurante Talentos Marmitex
📅 02/03/2026 (ontem)
```
- Linha 1: valor em negrito + categoria
- Linha 2: merchant (só se informado — omita se não souber)
- Linha 3: data no formato DD/MM/YYYY + entre parênteses "hoje" / "ontem" / dia da semana se relevante
- Se método explícito (PIX, débito, dinheiro): adicionar na linha 3 após  •
- Se valor ≥ R$200 e sem mencionar parcelamento: adicionar linha extra: _À vista — foi parcelado? É só falar._
- Última linha SEMPRE: _Errou? → "corrige" ou "apaga"_

## FORMATO: ADD_EXPENSE (parcelado)

```
✅ *R$100,00/mês × 3x* — Vestuário
📍 Nike Store  •  Nubank  •  _R$300,00 total_
📅 03/03/2026 (hoje)
_Errou? → "corrige" ou "apaga"_
```

## FORMATO: ADD_INCOME

```
💰 *R$13.000,00* registrado — Salário
```
+ UMA linha de contexto opcional curta: "Boa! Mês começa bem 💪" / "Freela chegou! 🎉" (varie, às vezes omita)

## FORMATO: MÚLTIPLOS GASTOS (quando salvar vários de uma vez)

Liste todos em bloco compacto + dica no final:
```
✅ Anotados!
• *R$30,00* Alimentação — Talentos
• *R$85,00* Saúde — Vacina cachorro
• *R$65,00* Alimentação — Supermercado
_Errou algum? → "corrige" ou "apaga"_
```

## INSIGHT CONTEXTUAL (opcional, 1 linha máximo)

Somente em casos muito evidentes (última parcela, compra enorme, receita alta).
Silêncio é melhor que comentário genérico.
NUNCA invente insights sem base nos dados.
NUNCA adicione perguntas junto com o insight.

---

## FORMATO: RESUMO MENSAL (get_month_summary)

A tool já retorna o dado formatado com nome, período, datas DD/MM por transação, categorias e lançamentos.
⚠️ COPIE O RETORNO DA TOOL CARACTERE POR CARACTERE — preserve todas as quebras de linha (\n).
NÃO comprima, NÃO reformule, NÃO coloque itens na mesma linha.
Cada item deve ficar em sua própria linha, exatamente como a tool retornou.
Remova TODAS as linhas que começam com `__` (metadata interna: __top_category, __insight).
Use `__insight:` para gerar UMA frase curta de insight personalizado ao final:
- Tom leve, informal, humorado (ex: "D Ville Supermercados tá levando boa parte do orçamento hein 😄")
- Baseada nos dados reais do __insight (dia mais gastador, merchant frequente, categoria top)
- Se saldo negativo: mencione com tom de alerta
- Se saldo muito positivo (>50% da renda): parabenize
- Pode incluir sugestão prática curta se fizer sentido
- NUNCA invente dados. Máximo 2 frases.

Se renda cadastrada mas sem receita lançada no mês: adicione após o insight:
"_(Sua renda de R$X.XXX ainda não foi lançada esse mês)_"

## FORMATO: RESUMO SEMANAL (get_week_summary)

A tool já retorna o dado formatado com nome, período, datas por transação, categorias e lançamentos.
Apresente o dado retornado DIRETAMENTE — não reformate nem resuma.
Remova TODAS as linhas que começam com `__` (metadata interna: __top_category, __insight).
Use `__insight:` para gerar UMA frase curta de insight personalizado ao final:
- Tom leve, informal, humorado (ex: "Restaurante Talentos tá virando sua segunda casa hein 😄")
- Baseada nos dados reais do __insight (dia mais gastador, merchant frequente, categoria top)
- Pode incluir sugestão prática curta se fizer sentido
- NUNCA invente dados. Máximo 2 frases.

## FORMATO: RESUMO DIÁRIO (get_today_total)

A tool já retorna o dado formatado com nome, data, categorias e lançamentos.
Apresente o dado retornado DIRETAMENTE — não reformate nem resuma.
Adicione UMA linha de insight ao final usando `__top_category` (mesma regra do mensal).
Remova a linha `__top_category:...` da resposta final.

## FORMATO: COMPARATIVO MENSAL

Destaque variações com ↑ ↓. Alertas ⚠️ em evidência. Pare aí.

## FORMATO: SALDO RÁPIDO ("qual meu saldo?")

```
💰 *Saldo de março: R$4.415*
Receitas: R$4.500  |  Gastos: R$85
```

## FORMATO: DETALHES DE TRANSAÇÕES

Liste de forma limpa, 1 linha por transação com hora se disponível. Pare aí.

## FORMATO: DETALHES DE CATEGORIA

```
🔍 *Alimentação* — R$X total
• Local A: R$X (XX%)
• Local B: R$X (XX%)
```
Se merchant vazio: "Sem nome registrado". Pare aí.

## FORMATO: FILTRO POR ESTABELECIMENTO (get_transactions_by_merchant)

A tool já retorna tudo formatado. Copie VERBATIM — não reformule, não resuma em prosa.
ERRADO: "Anotado! R$171,68 gastos no Deville em março de 2026, entre supermercado e restaurante."
CERTO: copiar o bloco completo com header 🔍, total 💸 e lista de lançamentos linha a linha.

## FORMATO: POSSO COMPRAR? (can_i_buy)

SEMPRE mostre o raciocínio — nunca só "Pode sim":
```
✅ *Pode comprar* — Tênis R$200
Saldo atual: R$4.415 → após: R$4.215
Representa 1,5% da sua renda — cabe tranquilo.
```
Vereditos: ✅ Pode comprar / ⚠️ Com cautela / ⏳ Melhor adiar / 🚫 Não recomendo

## FORMATO: CARTÃO DE CRÉDITO — cadastro/fatura

Cadastro: "*[Nome]* configurado! Fecha dia [X], vence dia [Y]."
Fatura: Use o formato retornado pela tool. Pare aí.

## FORMATO: PRÓXIMA FATURA (get_next_bill)

Use o formato retornado. Total estimado em negrito.
Se "última parcela!": mencione "O [nome] quita na próxima fatura! 🎊". Pare aí.

## FORMATO: GASTOS FIXOS — cadastro

"*[Nome]* — R$X todo dia [Y]. ✅" Pare aí.

## FORMATO: CICLO DE SALÁRIO

Blocos: renda / gasto / orçamento diário / projeção. Pare aí.

## FORMATO: VAI SOBRAR?

Direto no veredito + 3 cenários resumidos. Pare aí.

## FORMATO: SCORE FINANCEIRO

Use o formato retornado pela tool (já tem emoji e componentes). Pare aí.

## FORMATO: AJUDA / MENU

Quando o usuário digitar "ajuda", "/ajuda", "menu", "o que você faz?", "comandos":
Responda com este menu EXATO (use WhatsApp markdown):

"📋 *O que o ATLAS faz:*

1️⃣ *Lançar gastos*
• _"gastei 45 no iFood"_
• _"tênis 300 em 3x no Nubank"_
• _"mercado 120 — débito"_

2️⃣ *Receitas*
• _"recebi 4500 de salário"_
• _"entrou 1200 de freela"_

3️⃣ *Análises*
• _"como tá meu mês?"_
• _"posso comprar um tênis de 200?"_
• _"vai sobrar até o fim do mês?"_

4️⃣ *Cartões de crédito*
• _"fatura do Nubank"_
• _"próxima fatura do Inter"_
• _"paguei o cartão"_

5️⃣ *Gastos fixos e metas*
• _"aluguel 1500 todo dia 5"_
• _"quero guardar 5k pra viagem"_

💡 *Score financeiro:* _"qual meu score?"_

Fale natural — não precisa de comando exato 😊"

## FORMATO: CLARIFICAÇÃO

UMA pergunta curta. Nunca mais de uma.

## GASTO SEM CONTEXTO

Se não há NENHUMA pista do que foi o gasto ("gastei 18", "saiu 50"):
NÃO salve. Pergunte: "R$18 em quê?" — salve só após a resposta.
"""

response_agent = Agent(
    name="response_agent",
    description="Gera respostas em português brasileiro.",
    instructions=RESPONSE_INSTRUCTIONS,
    model=get_fast_model(),
    markdown=True,
)

# ============================================================
# STATEMENT AGENT — Parser de faturas via visão
# ============================================================

STATEMENT_INSTRUCTIONS = """
Você é um parser especializado em faturas de cartão de crédito brasileiras.

Sua tarefa: extrair TODAS as transações visíveis na imagem da fatura.

Para cada transação, identifique:
- date: data da compra no formato YYYY-MM-DD (use o ano da fatura; se não houver ano, deduza pelo mês)
- merchant: nome do estabelecimento exatamente como aparece na fatura
- amount: valor em reais como número POSITIVO (ex: 89.90)
- type: "debit" para compras/gastos (coluna DÉBITO), "credit" para estornos/devoluções (coluna CRÉDITO)
- category: classifique em UMA das categorias:
  Alimentação | Transporte | Saúde | Moradia | Lazer | Assinaturas | Educação | Vestuário | Investimento | Pets | Outros | Indefinido
  Use "Indefinido" quando não tiver certeza razoável sobre a categoria.
- confidence: número de 0.0 a 1.0 indicando sua confiança na categoria escolhida.
  Use < 0.6 quando o merchant for ambíguo (ex: nomes de pessoas, siglas, códigos).
- installment: se parcelado, escreva "X/Y" (ex: "2/6"); se à vista, deixe "".
  ATENÇÃO: faturas mostram parcelas como "MERCHANT PARC 03/12", "MERCHANT 3/12", "MERCHANT P3/12",
  "MERCHANT PARCELA 03 DE 12". Extraia o número da parcela atual e total nestes casos.

REGRAS CRÍTICAS — DÉBITO vs CRÉDITO:
- Faturas têm colunas DÉBITO e CRÉDITO. Valores na coluna CRÉDITO são estornos/devoluções.
- Marque type="credit" para valores na coluna CRÉDITO (estornos, devoluções, cancelamentos).
- Marque type="debit" para valores na coluna DÉBITO (compras normais).
- NUNCA some créditos como se fossem débitos. Eles REDUZEM o total da fatura.
- DICA: na Caixa, linhas com prefixo "HTM" na coluna CRÉDITO são estornos → type="credit".
- Se a fatura mostra um total final (ex: "Total R$4.837,32C"), USE esse valor como "total" no JSON.
  O sufixo "C" significa crédito (saldo a pagar). Confie no total impresso na fatura.
- VALIDAÇÃO: some seus débitos e subtraia créditos. Se divergir do total impresso, revise os types.

REGRAS DE CATEGORIZAÇÃO:
- Hostinger, EBN, DM HOSTINGER → Assinaturas (hosting)
- ANTHROPIC, CLAUDE AI, ELEVENLABS, OpenAI → Assinaturas (IA/tech)
- IOF COMPRA INTERNACIONAL → Outros (taxa bancária)
- NET PGT, CLARO, VIVO, TIM → Moradia (telecom)
- FARM, RIACHUELO, RENNER, C&A, ZARA → Vestuário
- COBASI, PET, PETSHOP, RAÇÃO → Pets
- DROGASIL, DROGARIA, DROGACITY, DROGA LIDER → Saúde
- SUPERMERCADO, D VILLE, CARREFOUR → Alimentação
- POSTO, COMBUSTI, AUTO POSTO → Transporte
- RESTAURAN, BURGER, PIZZARIA, ESPETO, SABOR → Alimentação
- Nomes de pessoas (ex: HELIO RODRIGUES, NILSON DIAS) → Indefinido (confidence 0.3)

OUTRAS REGRAS:
- Ignore linhas de pagamento de fatura anterior, saldo anterior e ajustes
- Não invente transações — só extraia o que está claramente visível
- Se não conseguir ler uma linha, pule-a
- Detecte o nome do cartão/banco e o mês/ano de referência da fatura
- Se confidence < 0.6, defina category como "Indefinido"
- O "total" retornado deve ser: soma dos débitos MENOS soma dos créditos

Retorne APENAS JSON válido, sem texto adicional, neste formato exato:
{"transactions":[{"date":"YYYY-MM-DD","merchant":"...","amount":0.0,"type":"debit","category":"...","installment":"","confidence":1.0}],"bill_month":"YYYY-MM","total":0.0,"card_name":"..."}
"""

statement_agent = Agent(
    name="statement_analyzer",
    description="Parser de faturas de cartão — extrai e classifica transações de imagens.",
    instructions=STATEMENT_INSTRUCTIONS,
    model=OpenAIChat(id="gpt-4o", api_key=os.getenv("OPENAI_API_KEY")),
)

# ============================================================
# ATLAS AGENT — Conversacional com memória e banco
# ============================================================

ATLAS_INSTRUCTIONS = """
╔══════════════════════════════════════════════════════════════╗
║  REGRAS CRÍTICAS — LEIA ANTES DE TUDO                       ║
╚══════════════════════════════════════════════════════════════╝

REGRA 1 — RETORNAR TOOL OUTPUT VERBATIM (A MAIS IMPORTANTE):
Após qualquer tool de CONSULTA, copie o resultado EXATAMENTE como veio.
NÃO reformule. NÃO resuma em prosa. NÃO prefixe com "Anotado!".
NÃO adicione o nome do usuário antes do output (ex: "Rodrigo," é proibido).
NÃO reformule o cabeçalho (ex: "🔍 *Deville*" não vira "Lançamentos no Deville:").
NÃO troque emojis (💸 permanece 💸, não vira 💰, não vira 💸📦 etc).
O PRIMEIRO CARACTERE da sua resposta = primeiro caractere do output da tool.
Tools de consulta (retorno verbatim obrigatório):
  get_month_summary, get_week_summary, get_today_total,
  get_transactions_by_merchant, get_category_breakdown, get_transactions,
  get_installments_summary, get_salary_cycle, get_financial_score,
  get_upcoming_commitments, get_cards, get_next_bill, get_goals, get_recurring
Você PODE adicionar UMA linha de insight ao final dos resumos (mensal/semanal/diário).
Para get_transactions_by_merchant e get_category_breakdown: ENCERRE após o output. ZERO linhas extras.
ERRADO: "Rodrigo, lançamentos no Supermercado Deville em Mar/2026: ..."
ERRADO: "Anotado! R$171,68 gastos no Deville em março, entre supermercado e restaurante."
CERTO: colar o bloco exato que a tool retornou, começando pelo primeiro caractere (ex: 🔍).

REGRA 2 — ZERO PERGUNTAS APÓS CONSULTAS (SEM EXCEÇÕES PARA FILTROS):
Para get_transactions_by_merchant e get_category_breakdown: regra ABSOLUTA, zero exceções.
Para outros resumos: não adicione perguntas de follow-up.
PROIBIDO após qualquer ação (consulta, registro, cadastro de cartão, etc.).
A resposta TERMINA após a confirmação ou output da tool. ZERO perguntas de acompanhamento.
- "Quer ver o resumo das suas faturas?"
- "Quer ver o extrato?"
- "Quer adicionar algum gasto agora?"
- "Quer adicionar mais algum gasto?"
- "Quer que eu te lembre quando a data estiver próxima?"
- "Quer que eu detalhe outros gastos do mês?"
- "Quer ver o resumo detalhado de despesas por categoria?"
- "Quer que eu separe por categoria?"
- "Quer ver o total?"
- "Quer que eu verifique algo específico para abril?"
- "Quer que eu faça isso?"
- "Gostaria de ver mais?"
- "Posso mostrar...?"
- "Claro! Estou aqui para ajudar sempre que precisar."
- Qualquer frase com "Quer que eu...", "Posso...", "Gostaria...", "Estou aqui para..."

REGRA 3 — "Anotado!" EXCLUSIVO DE save_transaction:
"Anotado!" aparece SOMENTE na confirmação de registro de gasto/receita.
NUNCA use "Anotado!" em respostas de consulta ou análise.

REGRA 4 — "não"/"nao"/"n" NUNCA APAGA:
"não", "nao", "n", "nope" = recusa ou negação. delete_last_transaction só com:
"apaga", "deleta", "remove", "exclui" + contexto claro de transação.

REGRA 5 — PRESERVAR CENTAVOS EXATAMENTE:
"42,54" → amount=42.54 | "R$8,90" → amount=8.9 | "R$1.234,56" → amount=1234.56
NUNCA arredonde. NUNCA converta centavos em inteiro.

REGRA 6 — SALVAR SEM PEDIR CONFIRMAÇÃO PRÉVIA:
Valor + qualquer contexto (item/local/categoria) → salve IMEDIATAMENTE.
Não pergunte "Pode ser?" antes. Confirmação vem depois, na resposta.
Exceção: valor sem NENHUM contexto ("gastei 18") → pergunte "R$18 em quê?"

╔══════════════════════════════════════════════════════════════╗
║  IDENTIDADE E TOM                                           ║
╚══════════════════════════════════════════════════════════════╝

Você é o ATLAS — assistente financeiro pessoal via WhatsApp.
Tom: amigável, direto, informal. Português brasileiro natural.
WhatsApp markdown: *negrito*, _itálico_, ~tachado~.
UMA mensagem por resposta. NUNCA mostre JSON ou campos técnicos internos.

╔══════════════════════════════════════════════════════════════╗
║  HEADER DE CADA MENSAGEM                                    ║
╚══════════════════════════════════════════════════════════════╝

Cada mensagem começa com:
  [user_phone: +55XXXXXXXXXX]
  [user_name: João da Silva]
→ Extraia user_phone (use em TODAS as chamadas de tool).
→ Extraia user_name (nome do perfil WhatsApp).
→ NUNCA use "demo_user".

╔══════════════════════════════════════════════════════════════╗
║  ONBOARDING                                                 ║
╚══════════════════════════════════════════════════════════════╝

Chame get_user(user_phone=<user_phone>) SEMPRE na primeira mensagem da sessão.

CASO A — get_user retorna "__status:new_user":
  1. Chame update_user_name(user_phone=<user_phone>, name=<primeiro nome de user_name>)
  2. Envie EXATAMENTE (substitua [nome]):
     "Oi, [nome]! 👋 Sou o *ATLAS*, seu assistente financeiro no WhatsApp.
     Anoto seus gastos, receitas e te ajudo a entender pra onde vai seu dinheiro — tudo aqui na conversa, sem precisar de app.
     💰 Pra te ajudar melhor, qual é sua renda mensal aproximada? Pode pular se preferir."
  3. Aguarde renda ou pulo ("pular", "não sei", "depois", "0"). Não pergunte mais nada.
  4. Se informou renda: chame update_user_income(user_phone=<user_phone>, monthly_income=<valor>)
  5. Envie EXATAMENTE este texto de boas-vindas (com ou sem renda — o mesmo texto):
"Tudo certo, [nome]! 🎉 Pode me mandar seus gastos assim:

💸 *Gastos do dia a dia:*
• _"almocei 35 no Restaurante Talentos — PIX"_
• _"mercado 120 no Supermercado Deville — débito"_
• _"uber 18 pro aeroporto — débito"_

💳 *Compras no cartão:*
• _"comprei tênis 300 no Nubank"_
• _"notebook 3000 em 6x no Inter"_

📊 *Ver como está:*
• _"como tá meu mês?"_
• _"posso comprar um tênis de 200?"_

Digite *ajuda* a qualquer hora pra ver tudo que sei fazer 🎯"

CASO B — is_new=False, has_income=False:
  - Cumprimente pelo nome normalmente.
  - Após responder, sugira UMA vez: "Quer cadastrar sua renda pra eu te ajudar melhor com alertas e análises?"

CASO C — is_new=False, has_income=True (usuário completo):
  - Saudação curta e variada (escolha aleatória):
    "Oi, [name]! 👋 Como posso te ajudar?" | "Oi, [name]! 😊 O que aconteceu hoje?"
    "Ei, [name]! 👋 Me conta." | "Oi, [name]! O que anotamos hoje?"
  - Se salary_day=0 e transaction_count >= 5: sugira UMA vez ao final:
    "Você é CLT? Me fala o dia que seu salário cai — aí acompanho seu ciclo!"

╔══════════════════════════════════════════════════════════════╗
║  CATEGORIAS                                                 ║
╚══════════════════════════════════════════════════════════════╝

GASTOS (EXPENSE):
- iFood, Rappi, restaurante, lanche, mercado, almoço, comida → Alimentação
- Uber, 99, gasolina, pedágio, ônibus, metrô, táxi → Transporte
- Netflix, Spotify, Amazon Prime, assinatura digital → Assinaturas
- Farmácia, médico, plano de saúde, remédio, consulta → Saúde
- Aluguel, condomínio, luz, água, internet, gás → Moradia
- Academia, bar, cinema, show, viagem, lazer → Lazer
- Curso, livro, faculdade, treinamento → Educação
- Roupa, tênis, acessório, moda → Vestuário
- CDB, ação, fundo, tesouro, cripto → Investimento
- Ração, veterinário, pet shop, banho animal → Pets
- Presente, doação, outros → Outros

RECEITAS (INCOME):
- Salário, holerite, pagamento empresa → Salário
- Freela, projeto, cliente, PJ → Freelance
- Aluguel recebido, inquilino → Aluguel Recebido
- Dividendo, rendimento, CDB, juros → Investimentos
- Aposentadoria, INSS, benefício → Benefício
- Venda, marketplace, Mercado Livre → Venda
- Presente, Pix recebido sem contexto → Outros

╔══════════════════════════════════════════════════════════════╗
║  PARCELAMENTO                                               ║
╚══════════════════════════════════════════════════════════════╝

Detecte automaticamente:
- "em Nx" / "parcelei" / "12 vezes" → parcelado, extraia installments
- "à vista" / "débito" / "Pix" / "dinheiro" / "espécie" → installments=1
- Valor < R$200 sem mencionar forma → installments=1
- Assinaturas, delivery, transporte → sempre installments=1

Pergunte APENAS se: "cartão" ou "crédito" + valor ≥ R$200 + sem informar parcelas.

╔══════════════════════════════════════════════════════════════╗
║  INTENT → TOOL                                              ║
╚══════════════════════════════════════════════════════════════╝

── REGISTRAR ──────────────────────────────────────────────────

Gasto à vista: save_transaction(user_phone, transaction_type="EXPENSE", amount=<R$>, installments=1, category, merchant, payment_method, occurred_at)
Gasto parcelado: save_transaction(..., amount=<parcela>, installments=<n>, total_amount=<total>)
  Ex "tênis 1200 em 12x" → amount=100, installments=12, total_amount=1200
Receita: save_transaction(..., transaction_type="INCOME", amount=<R$>, category)
Gasto no cartão: adicione card_name="Nubank" — cartão criado automaticamente, não peça cadastro.

MÚLTIPLOS GASTOS: 1 gasto = 1 chamada save_transaction. 3 gastos = 3 chamadas.
DATA: "ontem"→hoje-1 | "anteontem"→hoje-2 | "dia X"→YYYY-MM-X | sem data→omitir occurred_at
  Múltiplos gastos com data: mesma occurred_at em TODAS as chamadas.

── CONSULTAR PERÍODO ──────────────────────────────────────────

filter_type: "gastos"/"o que gastei" → EXPENSE | "receitas"/"entradas" → INCOME | resto → ALL

MÊS: "como tá meu mês?" / "resumo do mês" / "me mostra o mês" / "mês de fevereiro" / "como foi março" / "me mostra fevereiro" → get_month_summary(user_phone, month="YYYY-MM", filter_type="ALL")
  ⚠️ REGRA: qualquer pedido sobre um MÊS inteiro (sem pedir "transações" ou "lista" explicitamente) → get_month_summary. NUNCA get_transactions para "me mostra o mês".
SEMANA: "como foi minha semana?" → get_week_summary(user_phone, filter_type="ALL")
HOJE/N DIAS: "gastos de hoje" → get_today_total(filter_type="EXPENSE", days=1)
  "movimentações de hoje" → get_today_total(filter_type="ALL", days=1)
  "últimos 3 dias" → get_today_total(filter_type="EXPENSE", days=3)
  "ontem" → get_today_total(filter_type="EXPENSE", days=2)
  ⚠️ Qualquer "hoje"/"ontem"/"últimos N dias" → get_today_total com days=N, NUNCA get_transactions.

── FILTROS ────────────────────────────────────────────────────

POR ESTABELECIMENTO — qualquer menção a nome próprio de loja/app/serviço:
  "quanto gastei no X?" / "me mostra os gastos no X" / "gastos no X" / "gastos com X"
  "o que comprei na X?" / "mostra o X" / "X esse mês" / "X essa semana"
  "histórico do X" / "transações no X" / "compras no X" / "quantas vezes no X?"
  REGRA: nome próprio (Deville, iFood, Uber, Herbalife, Talentos, Nubank, Amazon...) →
    SEMPRE get_transactions_by_merchant — NUNCA get_today_total, NUNCA get_transactions
  → get_transactions_by_merchant(user_phone, merchant_query="<nome>")
  → Com mês: get_transactions_by_merchant(user_phone, merchant_query="<nome>", month="YYYY-MM")

POR CATEGORIA: "onde gastei em X?" / "detalhes de Alimentação"
  → get_category_breakdown(user_phone, category="<categoria>")

LISTA DETALHADA (só quando pedir "transações" ou "lista" ou "extrato" explicitamente):
  "todas as transações de março" / "transações do dia 10" / "lista de gastos de fev" / "extrato de março"
  → get_transactions(user_phone, month="YYYY-MM") ou get_transactions(user_phone, date="YYYY-MM-DD")
  ⚠️ NÃO use get_transactions para "me mostra o mês" / "como foi março" → use get_month_summary

── ANÁLISES ───────────────────────────────────────────────────

"posso comprar X?" / "tenho dinheiro pra Y?" → can_i_buy(user_phone, amount=<R$>, description="<item>")
"comparado ao mês passado" / "como evoluí?" → get_month_comparison(user_phone)
"vai sobrar?" / "vai faltar?" → will_i_have_leftover(user_phone)
"como estou no ciclo?" / "quanto tenho por dia?" → get_salary_cycle(user_phone)
"qual meu score?" / "saúde financeira" → get_financial_score(user_phone)

── METAS ──────────────────────────────────────────────────────

"quero guardar X pra Y" → create_goal(user_phone, name="<nome>", target_amount=<R$>)
"quero reserva de emergência" → create_goal(..., is_emergency_fund=True)
"ver minhas metas" → get_goals(user_phone)
"guardei X pra meta Y" → add_to_goal(user_phone, goal_name="<nome parcial>", amount=<R$>)

── CARTÕES ────────────────────────────────────────────────────

"fatura do Nubank" / "meus cartões" → get_cards(user_phone)
"minha fatura do Nubank está em 1.300" → set_card_bill(user_phone, card_name="Nubank", amount=1300)
"em abril tenho 400 no Nubank" → set_future_bill(user_phone, card_name="Nubank", bill_month="2026-04", amount=400)
"a fatura do ML em abril é 887" / "está errado, a fatura é 887" → set_future_bill imediatamente, sem pedir confirmação
"paguei o Nubank" → close_bill(user_phone, card_name="Nubank")
"Nubank fecha 25 vence 10" → register_card(user_phone, name="Nubank", closing_day=25, due_day=10)
"próxima fatura do Inter" → get_next_bill(user_phone, card_name="Inter")
Cartão criado automaticamente em save_transaction com card_name — nunca peça cadastro antecipado.

── GASTOS FIXOS ───────────────────────────────────────────────

"aluguel 1500 todo dia 5" → register_recurring(user_phone, name="Aluguel", amount=1500, category="Moradia", day_of_month=5)
"quais meus gastos fixos?" → get_recurring(user_phone)
"cancelei a Netflix" → deactivate_recurring(user_phone, name="Netflix")
"compromissos futuros" / "o que tenho pra pagar" → get_upcoming_commitments(user_phone, days=60)
"o que pago em abril" / "compromissos de abril" / "o que tenho em abril" → get_upcoming_commitments(user_phone, days=60, month="2026-04")
"o que pago em maio" → get_upcoming_commitments(user_phone, days=90, month="2026-05")
"minhas parcelas" → get_installments_summary(user_phone)

── SALÁRIO / CICLO ────────────────────────────────────────────

"meu salário cai dia X" → set_salary_day(user_phone, salary_day=X)
"quero lembrete 2 dias antes" → set_reminder_days(user_phone, days_before=2)

── CORREÇÕES ──────────────────────────────────────────────────

"apaga" / "cancela" / "foi erro" → delete_last_transaction(user_phone) → "✅ Apagado! R$X [categoria] removido."
"corrige" / "errei" / "na verdade" / "foi parcelado" → update_last_transaction(user_phone, <só o campo que muda>)
  installments → recalcula parcela automaticamente (não passe amount junto)
  payment_method → CREDIT | DEBIT | PIX | CASH
  "foi 150 não 200" → update_last_transaction(user_phone, amount=150)
  "o local era Magazine Luiza" → update_last_transaction(user_phone, merchant="Magazine Luiza")

RECATEGORIZAR MERCHANT (atualiza TODAS as transações + salva regra para futuras faturas):
  "HELIO RODRIGUES NAZAR é alimentação" / "muda Talentos pra Lazer" / "X é categoria Y"
  → update_merchant_category(user_phone, merchant_query="HELIO RODRIGUES NAZAR", category="Alimentação")
  ⚠️ REGRA: quando o usuário disser que um ESTABELECIMENTO pertence a uma CATEGORIA,
  use update_merchant_category (atualiza tudo + memoriza), NÃO update_last_transaction.

── AJUDA ──────────────────────────────────────────────────────

"ajuda" / "menu" / "o que você faz?" / "comandos" → responda com menu EXATO abaixo, sem chamar tool:

"📋 *O que o ATLAS faz:*

1️⃣ *Lançar gastos*
• _"gastei 45 no iFood"_
• _"tênis 300 em 3x no Nubank"_
• _"mercado 120 — débito"_

2️⃣ *Receitas*
• _"recebi 4500 de salário"_
• _"entrou 1200 de freela"_

3️⃣ *Análises*
• _"como tá meu mês?"_
• _"posso comprar um tênis de 200?"_
• _"vai sobrar até o fim do mês?"_

4️⃣ *Cartões de crédito*
• _"fatura do Nubank"_
• _"próxima fatura do Inter"_
• _"paguei o cartão"_

5️⃣ *Gastos fixos e metas*
• _"aluguel 1500 todo dia 5"_
• _"quero guardar 5k pra viagem"_

💡 *Score financeiro:* _"qual meu score?"_

Fale natural — não precisa de comando exato 😊"

╔══════════════════════════════════════════════════════════════╗
║  FORMATOS DE RESPOSTA                                       ║
╚══════════════════════════════════════════════════════════════╝

── GASTO À VISTA (save_transaction EXPENSE, installments=1) ──
✅ *R$30,00 — Alimentação*
📍 Restaurante Talentos  (omita se sem merchant)
📅 02/03/2026 (ontem)  •  PIX  (omita método se não informado)
_Errou? → "corrige" ou "apaga"_
Se valor ≥ R$200 sem mencionar parcelamento: linha extra "_À vista — foi parcelado? É só falar._"

── GASTO PARCELADO ───────────────────────────────────────────
✅ *R$100,00/mês × 3x* — Vestuário
📍 Nike Store  •  Nubank  •  _R$300,00 total_
📅 03/03/2026 (hoje)
_Errou? → "corrige" ou "apaga"_

── MÚLTIPLOS GASTOS ──────────────────────────────────────────
✅ Anotados!
• *R$30,00* Alimentação — Talentos
• *R$85,00* Saúde — Vacina cachorro
• *R$65,00* Alimentação — Supermercado
_Errou algum? → "corrige" ou "apaga"_

── RECEITA ───────────────────────────────────────────────────
💰 *R$13.000,00* registrado — Salário
(UMA linha de contexto opcional: "Boa! Mês começa bem 💪" — às vezes omita)

── RESUMOS (copiar verbatim + 1 insight opcional) ────────────
Copie o retorno da tool LINHA POR LINHA.
Ao final, adicione UMA linha de insight baseada nos dados reais.
Remova a linha `__top_category:...` da resposta (use só para o insight).
Se renda cadastrada mas sem receita lançada: "_Sua renda de R$X ainda não foi lançada esse mês_"

── POSSO COMPRAR? ────────────────────────────────────────────
✅ *Pode comprar* — Tênis R$200
Saldo atual: R$4.415 → após: R$4.215
Representa 1,5% da sua renda — cabe tranquilo.
Vereditos: ✅ Pode comprar / ⚠️ Com cautela / ⏳ Melhor adiar / 🚫 Não recomendo

── SALDO RÁPIDO ──────────────────────────────────────────────
💰 *Saldo de março: R$4.415*
Receitas: R$4.500  |  Gastos: R$85

── CARTÃO — CONFIGURAÇÃO ─────────────────────────────────────
"*[Nome]* configurado! Fecha dia [X], vence dia [Y]."

── GASTO FIXO — CADASTRO ─────────────────────────────────────
"*[Nome]* — R$X todo dia [Y]. ✅"

── COMPARATIVO MENSAL ────────────────────────────────────────
Destaque variações com ↑ ↓. Alertas ⚠️ em evidência. Pare aí.

── INSIGHT CONTEXTUAL (opcional) ────────────────────────────
Só em casos evidentes (última parcela, compra grande, receita alta).
Silêncio é melhor que comentário genérico. Nunca invente dados.

╔══════════════════════════════════════════════════════════════╗
║  MODO MENTOR                                                ║
╚══════════════════════════════════════════════════════════════╝

Ative quando:
- Usuário pede "análise dos meus gastos", "fala como mentor", "onde estou errando"
- Usuário importa uma fatura (endpoint /v1/import-statement retorna resultado)
- Usuário pede comparação de meses ("compara com mês passado")

Tom e comportamento:
- Consultor financeiro amigo: direto, sem julgamento, acionável
- Frase de abertura: "Olhando seus gastos..." ou "Analisando sua fatura..."
- Dê 1-2 insights específicos (não genéricos como "gaste menos")
  ✅ "Você foi ao iFood 11x este mês — R$310. Equivale a 17% dos seus gastos."
  ✅ "Alimentação subiu R$120 vs fevereiro — puxado pelo Supermercado Deville."
  ❌ "Tente economizar em alimentação."
- Compare com histórico quando disponível (use get_month_comparison)
- Uma sugestão concreta no final, se cabível
- NÃO faça perguntas ao final — entregue o diagnóstico completo e pare

╔══════════════════════════════════════════════════════════════╗
║  FONTE DE DADOS — FATURA vs ATLAS vs AMBOS                  ║
╚══════════════════════════════════════════════════════════════╝

Sempre que o usuário perguntar sobre gastos/transações, identifique a fonte correta:

🧾 FATURA PENDENTE → use get_pending_statement
Sinais: "desta fatura", "na fatura", "no pdf", "na imagem que mandei",
        "que eu enviei", "da fatura que mandei", "o que tinha na fatura"
Exemplos:
  "quais as transações de alimentação desta fatura" → get_pending_statement(category="Alimentação")
  "quanto gastei em pets na fatura" → get_pending_statement(category="Pets")
  "quais são as transações?" (após enviar fatura) → get_pending_statement()
  NUNCA use get_transactions ou get_category_breakdown para essas perguntas.

🏦 ATLAS (banco de dados) → use get_transactions, get_month_summary, get_category_breakdown etc.
Sinais: "este mês", "março", "histórico", "o que gastei" sem mencionar fatura,
        "meu extrato", "minhas compras de fevereiro"
Exemplos:
  "o que gastei em março" → get_month_summary(month="2026-03")
  "quanto no Deville?" → get_transactions_by_merchant(merchant_query="Deville")

🔄 AMBOS → use get_pending_statement E tools de histórico
Sinais: "compara a fatura com o histórico", "vs mês passado", "a fatura está acima da média?"
Exemplos:
  "a fatura de alimentação está acima do normal?" → get_pending_statement(category="Alimentação")
  + get_month_summary para comparar com meses anteriores

REGRA: na dúvida entre fatura e banco, verifique se há fatura pendente com
get_pending_statement. Se retornar dados, use-os. Se não, use o banco.

╔══════════════════════════════════════════════════════════════╗
║  CHECKLIST — REVISE ANTES DE ENVIAR                         ║
╚══════════════════════════════════════════════════════════════╝

Antes de enviar qualquer resposta de consulta (filtro, resumo, análise):

1. Minha resposta começa com o output exato da tool (🔍, 💸, 📊...)?
   NÃO → Reescreva começando com o output da tool, linha por linha.
   LEMBRETE: para get_transactions_by_merchant o output começa com 🔍.

2. Adicionei o nome do usuário antes do output? (ex: "Rodrigo, lançamentos...")
   SIM → ERRADO. Delete o prefixo. Comece direto no 🔍.

3. Minha resposta contém "Anotado!" sem ter chamado save_transaction?
   SIM → Remova "Anotado!" — use só para registros de gasto/receita.

4. Minha resposta termina com uma pergunta ("Quer que eu...?", "Posso...?")?
   SIM → Delete a pergunta. Pare no conteúdo. Sem exceções para filtros.

5. Resumi o output da tool em uma frase em vez de copiar o bloco inteiro?
   SIM → Errado. Copie o bloco inteiro. Cada linha da tool = uma linha na resposta.

6. Troquei algum emoji? (💸 → 💰, ou qualquer outra troca)?
   SIM → Errado. Copie os emojis exatamente como vieram da tool.
"""

@tool(description="""Consulta a fatura que o usuário enviou (imagem/PDF) e ainda não importou.
Use SEMPRE que o usuário mencionar 'fatura', 'esta fatura', 'da fatura', 'no pdf', 'na imagem que mandei' para perguntas sobre transações, categorias ou valores.
Exemplos de quando usar:
- 'quais as transações de alimentação desta fatura'
- 'quanto gastei em transporte na fatura'
- 'quais são as transações?'
- 'o que tinha na fatura?'
- 'me mostra os gastos da fatura'
- 'qual o total da fatura?'
Parâmetro category: filtra por categoria específica (ex: 'Alimentação', 'Transporte'). Deixe '' para retornar todas.
NÃO use get_transactions, get_category_breakdown ou get_month_summary para perguntas sobre 'esta fatura' ou 'a fatura que enviei'.""")
def get_pending_statement(user_phone: str, category: str = "") -> str:
    """Retorna as transações da fatura pendente, com filtro opcional por categoria."""
    import json as _json_ps
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "Nenhuma fatura pendente encontrada."
    user_id = row[0]
    now_str = _now_br().strftime("%Y-%m-%dT%H:%M:%S")
    cur.execute(
        "SELECT transactions_json, card_name, bill_month FROM pending_statement_imports "
        "WHERE user_id=? AND imported_at IS NULL AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
        (user_id, now_str)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return "Nenhuma fatura pendente encontrada. Envie a imagem da fatura para analisar."
    txs = _json_ps.loads(row[0])
    card = row[1] or "cartão"
    month = row[2] or ""

    # Filtra por categoria se informada
    cat_filter = category.strip().lower()
    if cat_filter:
        txs_filtered = [tx for tx in txs if tx.get("category", "").lower() == cat_filter]
        if not txs_filtered:
            # tenta match parcial
            txs_filtered = [tx for tx in txs if cat_filter in tx.get("category", "").lower()]
        if not txs_filtered:
            return f"Nenhuma transação de '{category}' encontrada na fatura {card} ({month})."
        total_cat = sum(tx["amount"] for tx in txs_filtered)
        lines = [f"📋 *{category} na fatura {card} — {month}* ({len(txs_filtered)} itens | R${total_cat:,.2f})\n".replace(",", ".")]
        txs = txs_filtered
    else:
        total = sum(tx["amount"] for tx in txs)
        lines = [f"📋 *Transações da fatura {card} — {month}* ({len(txs)} itens | R${total:,.2f})\n".replace(",", ".")]

    for i, tx in enumerate(txs, 1):
        cat = tx.get("category", "?")
        conf = tx.get("confidence", 1.0)
        flag = " ❓" if cat == "Indefinido" or conf < 0.6 else ""
        inst = f" ({tx['installment']})" if tx.get("installment") else ""
        lines.append(f"{i}. {tx['merchant']}{inst} — R${tx['amount']:,.2f} | {cat}{flag}".replace(",", "."))
    lines.append("\n_Para importar, responda_ *importar*")
    return "\n".join(lines)


atlas_agent = Agent(
    name="atlas",
    description="ATLAS — Assistente financeiro pessoal via WhatsApp",
    instructions=ATLAS_INSTRUCTIONS,
    model=get_model(),
    db=db,
    add_history_to_context=True,
    num_history_runs=6,
    tools=[get_user, update_user_name, update_user_income, save_transaction, get_last_transaction, update_last_transaction, update_merchant_category, delete_last_transaction, get_month_summary, get_month_comparison, get_week_summary, get_today_total, get_transactions, get_transactions_by_merchant, get_category_breakdown, get_installments_summary, can_i_buy, create_goal, get_goals, add_to_goal, get_financial_score, set_salary_day, get_salary_cycle, will_i_have_leftover, register_card, get_cards, close_bill, set_card_bill, set_future_bill, register_recurring, get_recurring, deactivate_recurring, get_next_bill, set_reminder_days, get_upcoming_commitments, get_pending_statement],
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
# MIDDLEWARE — sanitiza lone surrogates das respostas JSON
# (GPT gera surrogates quebrados que causam "null byte" no Chatwoot)
# ============================================================
import re as _re_mid
from starlette.middleware.base import BaseHTTPMiddleware as _BaseMiddleware
from starlette.responses import Response as _StarletteResponse

_LONE_SURROGATE_RE = _re_mid.compile(r'[\ud800-\udfff]')

class _SanitizeSurrogateMiddleware(_BaseMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            body_bytes = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    body_bytes += chunk.encode("utf-8", errors="surrogatepass")
                else:
                    body_bytes += chunk
            text = body_bytes.decode("utf-8", errors="replace")
            text = _LONE_SURROGATE_RE.sub("", text)
            return _StarletteResponse(
                content=text,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json",
            )
        return response

app.add_middleware(_SanitizeSurrogateMiddleware)

# ============================================================
# MANUAL — página HTML mobile-friendly
# ============================================================

from fastapi.responses import FileResponse as _FileResponse

@app.get("/manual")
def get_manual():
    """Manual HTML do ATLAS — mobile-friendly, sem login."""
    path = Path(__file__).parent / "static" / "manual.html"
    return _FileResponse(str(path), media_type="text/html")

# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/v1/reminders/daily")
def get_daily_reminders():
    """
    Retorna lista de lembretes a enviar hoje.
    Chamado pelo cron job do n8n diariamente às 9h BRT.
    Retorna: {"reminders": [{"phone": "+55...", "message": "...", "user_id": "..."}], "count": N}
    """
    today = _now_br()
    today_day = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    conn = _get_conn()
    cur = conn.cursor()

    # Apenas usuários que completaram o onboarding (tem renda cadastrada)
    cur.execute(
        "SELECT id, phone, name, reminder_days_before FROM users WHERE name != 'Usuário' AND monthly_income_cents > 0",
    )
    users = cur.fetchall()

    results = []

    for user_id, phone, name, reminder_days in users:
        reminder_days = reminder_days or 3

        # Dia alvo = hoje + reminder_days (com rollover de mês)
        target_day = today_day + reminder_days
        if target_day > days_in_month:
            target_day = target_day - days_in_month

        items = []

        # Gastos fixos com vencimento no dia alvo
        cur.execute(
            "SELECT name, amount_cents FROM recurring_transactions WHERE user_id = ? AND active = 1 AND day_of_month = ?",
            (user_id, target_day)
        )
        for rec_name, amount_cents in cur.fetchall():
            items.append(f"📋 {rec_name} — R${amount_cents/100:.2f}")

        # Faturas de cartão com vencimento no dia alvo
        cur.execute(
            "SELECT id, name, closing_day, current_bill_opening_cents FROM credit_cards WHERE user_id = ? AND due_day = ?",
            (user_id, target_day)
        )
        for card_id, card_name, closing_day, opening_cents in cur.fetchall():
            period_start = _bill_period_start(closing_day)
            cur.execute(
                "SELECT SUM(amount_cents) FROM transactions WHERE user_id = ? AND card_id = ? AND occurred_at >= ?",
                (user_id, card_id, period_start)
            )
            new_purchases = cur.fetchone()[0] or 0
            bill_total = (opening_cents or 0) + new_purchases
            if bill_total > 0:
                items.append(f"💳 Fatura {card_name} — R${bill_total/100:.2f}")

        if items:
            days_label = "amanhã" if reminder_days == 1 else f"em {reminder_days} dias"
            header = f"🔔 Oi, {name}! Seus compromissos que vencem {days_label} (dia {target_day:02d}):"
            message = header + "\n\n" + "\n".join(items) + "\n\nJá planejou? 😊"
            results.append({"phone": phone, "message": message, "user_id": user_id})

    conn.close()
    return {"reminders": results, "date": today.strftime("%Y-%m-%d"), "count": len(results)}


# ============================================================
# FATURA ANALYZER — parse + import endpoints
# ============================================================

from fastapi import Form as _Form

def _generate_statement_insights(transactions: list, user_id: str, bill_month: str, stated_total: float = 0.0) -> str:
    """Gera texto de insights do mentor a partir das transações parseadas.
    stated_total: total impresso na fatura (do LLM). Se fornecido e diferente do calculado, prevalece.
    """
    if not transactions:
        return ""

    cat_emoji = {
        "Alimentação": "🍽️", "Transporte": "🚗", "Saúde": "💊",
        "Moradia": "🏠", "Lazer": "🎮", "Assinaturas": "📱",
        "Educação": "📚", "Vestuário": "👟", "Investimento": "📈",
        "Pets": "🐾", "Outros": "📦", "Indefinido": "❓",
    }
    from collections import defaultdict

    # Separa débitos e créditos
    debits = [tx for tx in transactions if tx.get("type", "debit") == "debit"]
    credits = [tx for tx in transactions if tx.get("type", "debit") == "credit"]

    # Agrupamentos (só débitos para categorias e merchants)
    cat_totals: dict = defaultdict(float)
    merchant_totals: dict = defaultdict(float)
    for tx in debits:
        cat_totals[tx["category"]] += tx["amount"]
        merchant_totals[tx["merchant"]] += tx["amount"]

    total_debits = sum(cat_totals.values())
    total_credits = sum(tx["amount"] for tx in credits)
    calculated_total = total_debits - total_credits

    # Se o total impresso na fatura foi informado, usa ele (mais confiável)
    if stated_total > 0:
        total = stated_total
    else:
        total = calculated_total
    top_merchants = sorted(merchant_totals.items(), key=lambda x: -x[1])[:3]
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:5]

    # Comparação com histórico (últimos 3 meses)
    history_lines = []
    try:
        conn = _get_conn()
        cur = conn.cursor()
        m_year, m_month = int(bill_month[:4]), int(bill_month[5:7])
        for delta in [1, 2, 3]:
            prev_mo = m_month - delta
            prev_yr = m_year
            if prev_mo <= 0:
                prev_mo += 12
                prev_yr -= 1
            prev_str = f"{prev_yr}-{prev_mo:02d}"
            cur.execute(
                "SELECT SUM(amount_cents) FROM transactions WHERE user_id=? AND type='EXPENSE' AND occurred_at LIKE ?",
                (user_id, f"{prev_str}%")
            )
            row = cur.fetchone()
            if row and row[0]:
                history_lines.append(row[0] / 100)
        conn.close()
    except Exception:
        pass

    # Monta o texto
    _month_names = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    try:
        mo_label = _month_names[int(bill_month[5:7]) - 1] + "/" + bill_month[2:4]
    except Exception:
        mo_label = bill_month

    lines = [f"📊 *Fatura — {mo_label}*", ""]
    if credits:
        lines.append(f"💸 *Total: R${total:,.2f}* (R${total_debits:,.2f} em débitos — R${total_credits:,.2f} em créditos) · {len(transactions)} transações".replace(",", "."))
    else:
        lines.append(f"💸 *Total: R${total:,.2f}* em {len(transactions)} transações".replace(",", "."))
    lines.append("")

    if top_merchants:
        lines.append("🏆 *Top estabelecimentos:*")
        for i, (m, v) in enumerate(top_merchants, 1):
            pct = v / total * 100 if total else 0
            lines.append(f"  {i}. {m} — R${v:,.2f} ({pct:.0f}%)".replace(",", "."))
        lines.append("")

    lines.append("📂 *Por categoria:*")
    for cat, val in top_cats:
        pct = val / total * 100 if total else 0
        emoji = cat_emoji.get(cat, "📦")
        lines.append(f"  {emoji} {cat} — R${val:,.2f} ({pct:.0f}%)".replace(",", "."))
    lines.append("")

    if history_lines:
        avg = sum(history_lines) / len(history_lines)
        diff = total - avg
        sign = "+" if diff >= 0 else ""
        lines.append(f"📈 *vs. média dos últimos {len(history_lines)} meses:*")
        lines.append(f"  Total: {sign}R${diff:,.2f} vs R${avg:,.2f} de média".replace(",", "."))
        lines.append("")

    # Destaca transações com categoria indefinida
    indefinidos = [tx for tx in transactions if tx.get("category") == "Indefinido" or tx.get("confidence", 1.0) < 0.6]
    if indefinidos:
        lines.append(f"❓ *{len(indefinidos)} transação(ões) com categoria indefinida:*")
        for tx in indefinidos[:5]:
            lines.append(f"  • {tx['merchant']} — R${tx['amount']:,.2f}".replace(",", "."))
        lines.append("_Você pode definir a categoria após importar._")
        lines.append("")

    return "\n".join(lines)


@app.post("/v1/parse-statement")
async def parse_statement_endpoint(
    user_phone: str = _Form(...),
    image_url: str = _Form(""),
    image_base64: str = _Form(""),
    card_name: str = _Form(""),
):
    """
    Recebe imagem de fatura (URL ou base64), extrai transações com visão e gera insights.
    Retorna texto formatado para enviar ao usuário + import_id para confirmação.
    """
    import base64 as _b64
    import httpx as _httpx
    from agno.media import Image as _AgnoImage

    # Normaliza telefone: "+" vira espaço em query strings não-encoded (n8n)
    user_phone = user_phone.strip()
    if user_phone and not user_phone.startswith("+"):
        user_phone = "+" + user_phone

    conn = _get_conn()
    cur = conn.cursor()

    # Resolve user_id
    cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": "Usuário não encontrado.", "message": "Usuário não encontrado."}
    user_id = row[0]

    # Obtém o arquivo (imagem ou PDF)
    raw_bytes = None
    content_type = "image/jpeg"
    if image_base64:
        raw_bytes = _b64.b64decode(image_base64)
        content_type = "application/pdf" if raw_bytes[:4] == b"%PDF" else "image/jpeg"
    elif image_url:
        try:
            async with _httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                raw_bytes = resp.content
                content_type = resp.headers.get("content-type", "image/jpeg")
        except Exception as e:
            conn.close()
            return {"error": str(e), "message": "Não consegui baixar a fatura. Tente enviar novamente."}

    if not raw_bytes:
        conn.close()
        return {"error": "Sem arquivo.", "message": "Envie uma foto, print ou PDF da fatura."}

    file_b64 = _b64.b64encode(raw_bytes).decode()
    is_pdf = (
        "pdf" in content_type.lower()
        or (image_url or "").lower().endswith(".pdf")
        or raw_bytes[:4] == b"%PDF"
    )

    # Extrai transações via visão — OpenAI gpt-4o direto (imagem ou PDF)
    try:
        import openai as _openai_lib
        import json as _json_vision
        _oai = _openai_lib.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        if is_pdf:
            media_type = "application/pdf"
            file_content = {"type": "file", "file": {"filename": "fatura.pdf", "file_data": f"data:{media_type};base64,{file_b64}"}}
        else:
            media_type = content_type if content_type.startswith("image/") else "image/jpeg"
            file_content = {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{file_b64}"}}

        completion = await _oai.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extraia TODAS as transações desta fatura, incluindo TODAS as páginas. Não pare antes de processar o documento inteiro. Retorne JSON válido.\n\n{STATEMENT_INSTRUCTIONS}"},
                    file_content,
                ],
            }],
            response_format={"type": "json_object"},
            max_tokens=16000,
        )
        raw_json = completion.choices[0].message.content
        parsed = StatementParseResult.model_validate(_json_vision.loads(raw_json))
    except Exception as e:
        conn.close()
        err_type = "PDF" if is_pdf else "imagem"
        return {"error": str(e), "message": f"Não consegui analisar o {err_type}. Tente novamente com um print mais claro."}

    if not parsed.transactions:
        conn.close()
        return {"message": "Não encontrei transações nessa imagem. É um print da fatura do cartão?"}

    # Usa card_name da imagem se não foi informado
    detected_card = card_name or parsed.card_name or "cartão"
    bill_month = parsed.bill_month or _now_br().strftime("%Y-%m")

    # Aplica regras de categorização do usuário antes de gerar insights
    tx_dicts = [t.model_dump() for t in parsed.transactions]
    cur.execute(
        "SELECT merchant_pattern, category FROM merchant_category_rules WHERE user_id=?",
        (user_id,)
    )
    user_rules = {row[0].upper(): row[1] for row in cur.fetchall()}
    if user_rules:
        for tx in tx_dicts:
            merchant_upper = tx.get("merchant", "").upper()
            for pattern, cat in user_rules.items():
                if pattern in merchant_upper:
                    tx["category"] = cat
                    tx["confidence"] = 1.0
                    break

    # Gera insights (passa total da fatura como referência)
    insights_text = _generate_statement_insights(tx_dicts, user_id, bill_month, parsed.total)

    # Salva pending import (TTL 30 min)
    import_id = str(uuid.uuid4())
    now_str = _now_br().strftime("%Y-%m-%dT%H:%M:%S")
    expires_str = (_now_br() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    import json as _json
    cur.execute(
        """INSERT INTO pending_statement_imports
           (id, user_id, card_name, bill_month, transactions_json, insights, created_at, expires_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (import_id, user_id, detected_card, bill_month,
         _json.dumps(tx_dicts, ensure_ascii=False), insights_text, now_str, expires_str)
    )
    conn.commit()
    conn.close()

    # Monta resposta final
    n = len(parsed.transactions)
    response_text = (
        insights_text
        + f"\nQuer importar essas *{n} transações* para o ATLAS?\n"
        + f"Responda *importar* para confirmar. _(válido por 30 min)_"
    )

    return {
        "message": response_text,
        "import_id": import_id,
        "transaction_count": n,
        "bill_month": bill_month,
        "card_name": detected_card,
    }


@app.post("/v1/import-statement")
async def import_statement_endpoint(
    user_phone: str = _Form(...),
    import_id: str = _Form(""),
):
    """
    Confirma a importação das transações de uma fatura parseada.
    Se import_id não fornecido, usa o mais recente do usuário (nos últimos 30 min).
    """
    import json as _json

    # Normaliza telefone: "+" vira espaço em query strings não-encoded (n8n)
    user_phone = user_phone.strip()
    if user_phone and not user_phone.startswith("+"):
        user_phone = "+" + user_phone

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": "Usuário não encontrado.", "message": "Usuário não encontrado."}
    user_id = row[0]

    now_str = _now_br().strftime("%Y-%m-%dT%H:%M:%S")

    if import_id:
        cur.execute(
            "SELECT id, transactions_json, card_name, bill_month, imported_at, expires_at FROM pending_statement_imports WHERE id=? AND user_id=?",
            (import_id, user_id)
        )
    else:
        # Pega o mais recente ainda válido
        cur.execute(
            "SELECT id, transactions_json, card_name, bill_month, imported_at, expires_at FROM pending_statement_imports WHERE user_id=? AND imported_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
    row = cur.fetchone()

    if not row:
        conn.close()
        return {"message": "Nenhuma fatura pendente para importar. Envie o print novamente."}

    imp_id, txns_json, det_card, bill_month, imported_at, expires_at = row

    if imported_at:
        conn.close()
        return {"message": "Essas transações já foram importadas anteriormente."}

    if now_str > expires_at:
        conn.close()
        return {"message": "O prazo para importar expirou (30 min). Envie o print da fatura novamente."}

    transactions = _json.loads(txns_json)

    # Aplica regras de categorização do usuário (merchant_category_rules)
    cur.execute(
        "SELECT merchant_pattern, category FROM merchant_category_rules WHERE user_id=?",
        (user_id,)
    )
    user_rules = {row[0].upper(): row[1] for row in cur.fetchall()}
    if user_rules:
        for tx in transactions:
            merchant_upper = tx.get("merchant", "").upper()
            for pattern, cat in user_rules.items():
                if pattern in merchant_upper:
                    tx["category"] = cat
                    tx["confidence"] = 1.0
                    break

    # Resolve card_id — busca cartão existente ou cria automaticamente
    card_id = None
    card_created = False
    if det_card:
        card = _find_card(cur, user_id, det_card)
        if card:
            card_id = card[0]
        else:
            # Auto-cria cartão com dados da fatura (closing/due = 0, usuário ajusta depois)
            card_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO credit_cards (id, user_id, name, closing_day, due_day) VALUES (?, ?, ?, 0, 0)",
                (card_id, user_id, det_card)
            )
            card_created = True

    # Importa cada transação
    imported = 0
    skipped = 0
    potential_duplicates = []
    import_source = f"fatura:{det_card}:{bill_month}"

    credit_count = 0
    card_dup_count = 0
    total_imported_cents = 0
    for tx in transactions:
        try:
            # Pula créditos (estornos/devoluções) — não são gastos
            if tx.get("type", "debit") == "credit":
                credit_count += 1
                skipped += 1
                continue

            amount_cents = round(tx["amount"] * 100)
            if amount_cents <= 0:
                skipped += 1
                continue

            # 0. Duplicata por cartão: mesmo card + valor + data (independente do merchant)
            #    Pega "Cueca" manual vs "LOJA X" fatura — mesmo cartão, mesmo valor, mesma data
            if card_id:
                cur.execute(
                    "SELECT id FROM transactions WHERE user_id=? AND card_id=? AND amount_cents=? AND occurred_at LIKE ?",
                    (user_id, card_id, amount_cents, f"{tx['date']}%")
                )
                if cur.fetchone():
                    card_dup_count += 1
                    skipped += 1
                    continue

            # 1. Duplicata exata: mesmo merchant (case-insensitive) + valor + data
            cur.execute(
                "SELECT id FROM transactions WHERE user_id=? AND LOWER(merchant)=LOWER(?) AND amount_cents=? AND occurred_at LIKE ?",
                (user_id, tx["merchant"], amount_cents, f"{tx['date']}%")
            )
            if cur.fetchone():
                skipped += 1
                continue

            # 2. Provável duplicata: mesmo valor + mesma data, merchant diferente, sem card_id (lançamento manual)
            cur.execute(
                "SELECT id, merchant FROM transactions WHERE user_id=? AND amount_cents=? AND occurred_at LIKE ? AND card_id IS NULL",
                (user_id, amount_cents, f"{tx['date']}%")
            )
            dup_row = cur.fetchone()
            if dup_row:
                potential_duplicates.append({
                    "fatura": tx["merchant"],
                    "atlas": dup_row[1],
                    "amount": tx["amount"],
                    "date": tx["date"],
                })
                # importa mesmo assim, mas marca como possível duplicata

            tx_id = str(uuid.uuid4())
            inst_total, inst_num = 1, 1
            if tx.get("installment") and "/" in tx["installment"]:
                parts = tx["installment"].split("/")
                try:
                    inst_num = int(parts[0])
                    inst_total = int(parts[1])
                except Exception:
                    pass

            # Gera installment_group_id para parcelas — agrupa por merchant+total+mês
            group_id = None
            if inst_total > 1:
                group_key = f"{user_id}:{tx['merchant'].upper()}:{inst_total}:{bill_month}"
                group_id = hashlib.md5(group_key.encode()).hexdigest()[:16]

            total_amount_cents = amount_cents * inst_total if inst_total > 1 else 0

            # Confidence → notes para auditoria
            conf = tx.get("confidence", 1.0)
            notes = f"[conf:{conf:.1f}]" if conf < 1.0 else None

            cur.execute(
                """INSERT INTO transactions
                   (id, user_id, type, amount_cents, total_amount_cents, installments, installment_number,
                    category, merchant, payment_method, occurred_at, card_id, import_source,
                    installment_group_id, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tx_id, user_id, "EXPENSE", amount_cents,
                 total_amount_cents,
                 inst_total, inst_num,
                 tx["category"], tx["merchant"], "CREDIT",
                 tx["date"] + "T12:00:00", card_id, import_source,
                 group_id, notes)
            )
            imported += 1
            total_imported_cents += amount_cents
        except Exception:
            skipped += 1

    # Atualiza current_bill_opening_cents se divergir do total importado
    bill_update_note = ""
    if card_id and total_imported_cents > 0:
        cur.execute(
            "SELECT current_bill_opening_cents FROM credit_cards WHERE id=?", (card_id,)
        )
        cb_row = cur.fetchone()
        old_bill = cb_row[0] if cb_row and cb_row[0] else 0
        if old_bill != total_imported_cents:
            cur.execute(
                "UPDATE credit_cards SET current_bill_opening_cents=? WHERE id=?",
                (total_imported_cents, card_id)
            )
            old_fmt = f"R${old_bill/100:,.2f}".replace(",", ".")
            new_fmt = f"R${total_imported_cents/100:,.2f}".replace(",", ".")
            bill_update_note = f"\n💳 Valor da fatura do {det_card} atualizado: {old_fmt} → {new_fmt}\n_Errou? Diga \"fatura do {det_card} é {old_fmt}\" para desfazer._"

    # Marca como importado
    cur.execute(
        "UPDATE pending_statement_imports SET imported_at=? WHERE id=?",
        (now_str, imp_id)
    )
    conn.commit()
    conn.close()

    _month_names = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    try:
        mo_label = _month_names[int(bill_month[5:7]) - 1] + "/" + bill_month[2:4]
    except Exception:
        mo_label = bill_month

    if card_created:
        card_link = f" _(cartão '{det_card}' criado automaticamente — ajuste fechamento/vencimento depois)_"
    elif card_id:
        card_link = f" _(vinculadas ao cartão {det_card})_"
    else:
        card_link = ""
    card_dup_note = f"\n🔄 {card_dup_count} já existiam no cartão — ignoradas automaticamente." if card_dup_count else ""
    skip_note = f"\n{skipped} ignoradas (duplicatas ou valor zero)." if skipped else ""

    dup_note = ""
    if potential_duplicates:
        dup_note = f"\n\n⚠️ *{len(potential_duplicates)} possível(eis) duplicata(s)* com lançamentos manuais:"
        for d in potential_duplicates[:5]:
            dup_note += f"\n  • {d['fatura']} vs '{d['atlas']}' — R${d['amount']:,.2f} em {d['date']}".replace(",", ".")
        dup_note += "\n_Verifique e delete manualmente se necessário._"

    report_url = f"https://atlas-m3wb.onrender.com/v1/report/fatura?id={imp_id}"

    return {
        "message": (
            f"✅ *{imported} transações importadas*{card_link}{card_dup_note}{skip_note}{bill_update_note}{dup_note}\n\n"
            f"Origem salva: `{import_source}`\n"
            f"Pergunte _\"como tá meu mês?\"_ para ver o resumo atualizado.\n\n"
            f"📊 *Ver relatório detalhado:*\n{report_url}"
        ),
        "import_id": imp_id,
        "report_url": report_url,
        "imported": imported,
        "skipped": skipped,
        "potential_duplicates": len(potential_duplicates),
    }


@app.post("/v1/clear-imports")
async def clear_imports_endpoint(
    user_phone: str = _Form(...),
    import_source_filter: str = _Form(""),
):
    """
    Apaga todas as transações importadas de fatura do usuário.
    Se import_source_filter fornecido, apaga só as com aquele import_source.
    Também limpa pending_statement_imports correspondentes.
    """
    user_phone = user_phone.strip()
    if user_phone and not user_phone.startswith("+"):
        user_phone = "+" + user_phone

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": "Usuário não encontrado.", "message": "Usuário não encontrado."}
    user_id = row[0]

    if import_source_filter:
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id=? AND import_source=?",
            (user_id, import_source_filter)
        )
        count = cur.fetchone()[0]
        cur.execute(
            "DELETE FROM transactions WHERE user_id=? AND import_source=?",
            (user_id, import_source_filter)
        )
    else:
        cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id=? AND import_source IS NOT NULL",
            (user_id,)
        )
        count = cur.fetchone()[0]
        cur.execute(
            "DELETE FROM transactions WHERE user_id=? AND import_source IS NOT NULL",
            (user_id,)
        )

    # Limpa pending_statement_imports também (reseta imported_at)
    cur.execute(
        "UPDATE pending_statement_imports SET imported_at=NULL WHERE user_id=?",
        (user_id,)
    )

    conn.commit()
    conn.close()

    return {
        "message": f"🗑️ {count} transações importadas removidas com sucesso.",
        "deleted": count,
    }


@app.get("/v1/pending-import")
def get_pending_import(user_phone: str):
    """Retorna o import_id pendente mais recente do usuário (para o n8n usar no fluxo 'importar')."""
    # Normaliza telefone: "+" vira espaço em query strings não-encoded (n8n)
    user_phone = user_phone.strip()
    if user_phone and not user_phone.startswith("+"):
        user_phone = "+" + user_phone
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"import_id": None}
    user_id = row[0]
    now_str = _now_br().strftime("%Y-%m-%dT%H:%M:%S")
    cur.execute(
        "SELECT id FROM pending_statement_imports WHERE user_id=? AND imported_at IS NULL AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
        (user_id, now_str)
    )
    row = cur.fetchone()
    conn.close()
    return {"import_id": row[0] if row else None}


@app.get("/v1/report/fatura")
def report_fatura(id: str = "", user_phone: str = ""):
    """Gera relatório HTML interativo de uma fatura importada ou pendente."""
    from fastapi.responses import HTMLResponse as _HTMLResponse
    import json as _json_r

    # Normaliza telefone: "+" vira espaço em query strings não-encoded
    if user_phone:
        user_phone = user_phone.strip()
        if not user_phone.startswith("+"):
            user_phone = "+" + user_phone

    conn = _get_conn()
    cur = conn.cursor()

    row = None
    if id:
        cur.execute(
            "SELECT transactions_json, card_name, bill_month, created_at, imported_at, expires_at "
            "FROM pending_statement_imports WHERE id=?", (id,)
        )
        row = cur.fetchone()
    elif user_phone:
        cur.execute("SELECT id FROM users WHERE phone=?", (user_phone,))
        u = cur.fetchone()
        if u:
            cur.execute(
                "SELECT transactions_json, card_name, bill_month, created_at, imported_at, expires_at "
                "FROM pending_statement_imports WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (u[0],)
            )
            row = cur.fetchone()
    conn.close()

    if not row:
        return _HTMLResponse("<h2>Relatório não encontrado ou expirado.</h2>", status_code=404)

    txs_json, card_name, bill_month, created_at, imported_at, expires_at = row
    now_str = _now_br().strftime("%Y-%m-%dT%H:%M:%S")
    if not imported_at and expires_at and now_str > expires_at:
        return _HTMLResponse("<h2>Este relatório expirou (30 min). Envie a fatura novamente.</h2>", status_code=410)

    txs = _json_r.loads(txs_json)

    def _fmt_brl(v: float) -> str:
        """Formata valor como R$ no padrão BR: 1.234,56"""
        s = f"{v:,.2f}"  # 1,234.56
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    # Separa débitos e créditos
    debits = [t for t in txs if t.get("type", "debit") == "debit"]
    credits = [t for t in txs if t.get("type", "debit") == "credit"]
    total_debits = sum(t["amount"] for t in debits)
    total_credits = sum(t["amount"] for t in credits)
    total = total_debits - total_credits

    _months_pt = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    try:
        mo_label = _months_pt[int(bill_month[5:7])-1] + "/" + bill_month[2:4]
    except Exception:
        mo_label = bill_month

    # Agrupamento por categoria para o gráfico (só débitos)
    from collections import defaultdict as _dd
    cat_totals = _dd(float)
    for t in debits:
        cat_totals[t.get("category", "Outros")] += t["amount"]
    cat_labels = list(cat_totals.keys())
    cat_values = [cat_totals[c] for c in cat_labels]

    cat_colors = {
        "Alimentação":"#4CAF50","Transporte":"#2196F3","Saúde":"#E91E63",
        "Moradia":"#FF9800","Lazer":"#9C27B0","Assinaturas":"#00BCD4",
        "Educação":"#3F51B5","Vestuário":"#F44336","Investimento":"#009688",
        "Pets":"#795548","Outros":"#9E9E9E","Indefinido":"#FF5722",
    }
    colors_js = "[" + ",".join(f'"{cat_colors.get(c,"#9E9E9E")}"' for c in cat_labels) + "]"
    labels_js = "[" + ",".join(f'"{c}"' for c in cat_labels) + "]"
    values_js = "[" + ",".join(f'{v:.2f}' for v in cat_values) + "]"

    # Linhas da tabela
    rows_html = ""
    for t in txs:
        cat = t.get("category","?")
        conf = t.get("confidence", 1.0)
        is_credit = t.get("type", "debit") == "credit"
        badge = '<span class="badge-indef">❓</span>' if cat == "Indefinido" or conf < 0.6 else ""
        inst = f' <small>({t["installment"]})</small>' if t.get("installment") else ""
        color = cat_colors.get(cat, "#9E9E9E")
        credit_style = ' style="color:#4CAF50;font-weight:600"' if is_credit else ""
        credit_prefix = "-" if is_credit else ""
        rows_html += f"""<tr data-cat="{cat}">
          <td>{t.get("date","")}</td>
          <td>{t.get("merchant","")}{inst}{' <small style="color:#4CAF50">CRÉDITO</small>' if is_credit else ''}</td>
          <td style="text-align:right{';color:#4CAF50;font-weight:600' if is_credit else ''}">{credit_prefix}R${_fmt_brl(t["amount"])}</td>
          <td><span class="cat-tag" style="background:{color}">{cat}</span>{badge}</td>
        </tr>"""

    # Botões de filtro
    all_cats = sorted(set(t.get("category","Outros") for t in txs))
    filter_btns = '<button class="filter-btn active" onclick="filterCat(\'all\',this)">Todas</button>'
    for c in all_cats:
        color = cat_colors.get(c, "#9E9E9E")
        filter_btns += f'<button class="filter-btn" onclick="filterCat(\'{c}\',this)" style="--cat-color:{color}">{c}</button>'

    status_badge = '✅ Importada' if imported_at else '⏳ Pendente de importação'

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fatura {card_name} — {mo_label}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f0f2f5; color: #111; }}
  .header {{ background: linear-gradient(135deg, #128c7e, #075e54);
             color: white; padding: 20px 16px 16px; }}
  .header h1 {{ font-size: 1.3rem; font-weight: 700; }}
  .header .sub {{ font-size: 0.85rem; opacity: 0.85; margin-top: 4px; }}
  .total {{ font-size: 2rem; font-weight: 800; margin: 8px 0 4px; }}
  .status {{ display: inline-block; background: rgba(255,255,255,0.2);
             border-radius: 12px; padding: 2px 10px; font-size: 0.78rem; }}
  .card {{ background: white; border-radius: 12px; margin: 12px;
           padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .card h2 {{ font-size: 0.9rem; color: #666; text-transform: uppercase;
              letter-spacing: .05em; margin-bottom: 12px; }}
  .chart-wrap {{ max-width: 280px; margin: 0 auto; }}
  .filters {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .filter-btn {{ border: none; border-radius: 20px; padding: 6px 14px;
                 font-size: 0.82rem; cursor: pointer; background: #eee;
                 color: #333; transition: all .15s; }}
  .filter-btn.active {{ background: var(--cat-color, #128c7e); color: white; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; padding: 8px 6px; border-bottom: 2px solid #eee;
        font-size: 0.75rem; color: #888; text-transform: uppercase; }}
  td {{ padding: 10px 6px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  .cat-tag {{ display: inline-block; border-radius: 10px; padding: 2px 8px;
              font-size: 0.75rem; color: white; white-space: nowrap; }}
  .badge-indef {{ margin-left: 4px; }}
  tr.hidden {{ display: none; }}
  .legend {{ display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 0.82rem; }}
  .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
</style>
</head>
<body>

<div class="header">
  <div class="sub">💳 {card_name}</div>
  <div class="total">R${_fmt_brl(total)}</div>
  <div class="sub">{len(txs)} transações · {mo_label}{f' · <span style="font-size:0.75rem">R${_fmt_brl(total_debits)} débitos — R${_fmt_brl(total_credits)} créditos</span>' if credits else ''} &nbsp;·&nbsp; <span class="status">{status_badge}</span></div>
</div>

<div class="card">
  <h2>Por Categoria</h2>
  <div class="chart-wrap">
    <canvas id="pieChart"></canvas>
  </div>
  <div class="legend" id="legend"></div>
</div>

<div class="card">
  <h2>Filtrar</h2>
  <div class="filters">{filter_btns}</div>
</div>

<div class="card">
  <h2>Transações <span id="count-label" style="font-weight:400;color:#999">({len(txs)})</span></h2>
  <table>
    <thead><tr><th>Data</th><th>Estabelecimento</th><th style="text-align:right">Valor</th><th>Categoria</th></tr></thead>
    <tbody id="txTable">{rows_html}</tbody>
  </table>
</div>

<script>
const labels = {labels_js};
const values = {values_js};
const colors = {colors_js};

const ctx = document.getElementById('pieChart').getContext('2d');
new Chart(ctx, {{
  type: 'doughnut',
  data: {{ labels, datasets: [{{ data: values, backgroundColor: colors, borderWidth: 2 }}] }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    cutout: '60%',
  }}
}});

// Legenda manual
const legend = document.getElementById('legend');
labels.forEach((l, i) => {{
  const pct = (values[i] / {total} * 100).toFixed(0);
  const valStr = values[i].toFixed(2).replace('.',',').replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, '.');
  legend.innerHTML += `<div class="legend-item">
    <div class="legend-dot" style="background:${{colors[i]}}"></div>
    <span>${{l}}</span>
    <span style="margin-left:auto;color:#666">R$${{valStr}} (${{pct}}%)</span>
  </div>`;
}});

// Filtro por categoria
function filterCat(cat, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const rows = document.querySelectorAll('#txTable tr');
  let count = 0;
  rows.forEach(r => {{
    const show = cat === 'all' || r.dataset.cat === cat;
    r.classList.toggle('hidden', !show);
    if (show) count++;
  }});
  document.getElementById('count-label').textContent = '(' + count + ')';
}}
</script>
</body>
</html>"""

    return _HTMLResponse(content=html)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "atlas-agno-api",
        "db": DB_TYPE,
        "agents": ["atlas", "parse_agent", "response_agent"],
        "model": "gpt-5-mini",
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
