# ATLAS

Assistente financeiro pessoal via WhatsApp para o mercado brasileiro.

> "O assistente financeiro que mora no seu WhatsApp"

---

## O que é

ATLAS é um copiloto financeiro que funciona 100% dentro do WhatsApp. O usuário manda uma mensagem em linguagem natural — "gastei 50 no iFood", "posso comprar um tênis de 300?" — e o agente responde, registra e analisa em segundos.

Sem app para baixar. Sem planilha para abrir. Sem fricção.

**Público-alvo**: Pessoas físicas, freelancers e MEI, 25-38 anos, capitais brasileiras.

---

## Features (MVP)

| Feature | Status |
|---|---|
| Onboarding (nome + renda) | ✅ |
| Registrar gastos e receitas em linguagem natural | ✅ |
| Categorização automática (iFood → Alimentação, Uber → Transporte...) | ✅ |
| Categorização de renda por fonte (Salário, Freelance, Aluguel, Investimentos...) | ✅ |
| Parcelamento — registra parcela + total, inferência automática | ✅ |
| Correção da última transação ("foi parcelado em 10x") | ✅ |
| Total do dia | ✅ |
| Resumo mensal com fontes de renda separadas | ✅ |
| Comparativo mês atual vs anterior com alertas de alta | ✅ |
| Resumo semanal com alertas de ritmo | ✅ |
| Detalhes de transações por data ou mês | ✅ |
| Resumo de parcelas ativas com compromisso total | ✅ |
| "Posso comprar?" com 4 veredictos (✅ / ⚠️ / ⏳ / 🚫) | ✅ |
| "Posso comprar?" usa receitas reais do mês como renda | ✅ |
| Metas financeiras com barra de progresso | ✅ |
| Score mensal de saúde financeira (0-100, grau A+ a F) | ✅ |
| Sugestões contextuais após cada ação | ✅ |
| Memória de conversa (últimas 10 interações) | ✅ |

---

## Arquitetura

```
WhatsApp (usuário)
    ↓
Evolution API          ← recebe mensagens WhatsApp
    ↓
n8n                    ← orquestração do pipeline
    ↓
ATLAS Agno API         ← agente LLM + tools financeiras
    ↓
PostgreSQL             ← usuários, transações, metas
```

### Agentes

| Agente | Função |
|---|---|
| `atlas` | Conversacional — UI de testes e WhatsApp direto |
| `parse_agent` | Interpreta mensagens → JSON estruturado (pipeline n8n) |
| `response_agent` | Gera resposta em PT-BR informal (pipeline n8n) |

### Tools financeiras (18)

| Tool | O que faz |
|---|---|
| `get_user` | Retorna dados do usuário (novo, nome, renda, has_income) |
| `update_user_name` | Salva nome no onboarding |
| `update_user_income` | Salva renda mensal estimada |
| `save_transaction` | Registra gasto ou receita (suporta parcelamento) |
| `get_last_transaction` | Retorna última transação registrada |
| `update_last_transaction` | Corrige última transação (parcelas, categoria, valor, pagamento) |
| `get_today_total` | Total gasto hoje |
| `get_transactions` | Lista transações por data ou mês |
| `get_installments_summary` | Parcelas ativas com compromisso total restante |
| `get_month_summary` | Resumo mensal com fontes de renda e gastos por categoria |
| `get_month_comparison` | Comparativo mês atual vs anterior com alertas |
| `get_week_summary` | Resumo semanal com alertas de ritmo |
| `can_i_buy` | Analisa se pode fazer uma compra (usa renda real do mês) |
| `create_goal` | Cria meta financeira |
| `get_goals` | Lista metas com barra de progresso |
| `add_to_goal` | Adiciona valor a uma meta |
| `get_financial_score` | Score 0-100 de saúde financeira (grau A+ a F) |

---

## Lógica de parcelamento

O agente infere automaticamente sem perguntar:

| O usuário diz | ATLAS faz |
|---|---|
| "em 12x", "parcelei em 6x" | Registra parcelado direto |
| "à vista", "no débito", "no Pix" | Registra à vista direto |
| "no cartão" + valor ≥ R$200 | Pergunta se foi parcelado |
| Sem mencionar pagamento | Registra à vista, avisa se valor ≥ R$200 |

Fluxo de correção:
```
"gastei 1200 no mercado"
→ Anotado! R$1.200 em Alimentação — à vista. Foi parcelado?

"foi em 3x"
→ OK — corrigido: 3x de R$400,00 (R$1.200 total)
```

---

## Stack

- **Python 3.13**
- **Agno** — framework de agentes LLM com AgentOS (FastAPI)
- **OpenAI GPT-4.1-mini** — modelo principal
- **SQLite** (local) / **PostgreSQL** (produção no Render)
- **Agent UI** — frontend Next.js para testes

---

## Rodando localmente

### Pré-requisitos

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Chave de API OpenAI

### Setup

```bash
# 1. Clonar o repositório
git clone <repo>
cd Atlas

# 2. Instalar dependências
uv sync

# 3. Configurar variáveis de ambiente
cp .env.example .env
# editar .env e adicionar OPENAI_API_KEY

# 4. Subir o backend (porta 7777)
uv run python -m agno_api.agent
```

### Frontend (Agent UI)

```bash
cd ../agent-ui
npm install
npm run dev
# abre em http://localhost:3000
```

Acesse `http://localhost:3000` e selecione o agente `atlas`.

### Resetar banco de dados

```bash
rm data/atlas.db
uv run python -m agno_api.agent
```

---

## Variáveis de ambiente

```env
# Obrigatória
OPENAI_API_KEY=sk-...

# Produção (Render) — sem esta variável usa SQLite local
DATABASE_URL=postgresql://user:password@host/db

# Futuro
REDIS_URL=redis://localhost:6379
EVOLUTION_API_URL=https://...
EVOLUTION_API_KEY=...
```

---

## Banco de dados

**Local**: SQLite em `data/atlas.db` — criado automaticamente na primeira execução.

**Produção**: PostgreSQL no Render — definir `DATABASE_URL` no ambiente.

### Tabelas

```
users                  — cadastro, nome, renda mensal estimada
transactions           — gastos e receitas (suporta parcelamento)
financial_goals        — metas com progresso
```

### Schema de transactions

```sql
id                    TEXT PRIMARY KEY
user_id               TEXT
type                  TEXT           -- EXPENSE | INCOME
amount_cents          INTEGER        -- valor da parcela (ou total se à vista)
total_amount_cents    INTEGER        -- valor total da compra
installments          INTEGER        -- número de parcelas (1 = à vista)
installment_number    INTEGER        -- parcela atual
category              TEXT
merchant              TEXT
payment_method        TEXT           -- CREDIT | DEBIT | PIX | CASH | TED
notes                 TEXT
occurred_at           TEXT           -- ISO 8601 local
```

---

## Score de Saúde Financeira (AFHS)

Nota 0-100, graus A+ / A / B+ / B / C+ / C / D / F.

| Componente | Peso | Cálculo |
|---|---|---|
| Taxa de poupança | 35% | % da renda guardada (meta: 20%+) |
| Consistência | 25% | Dias com registro / dias do mês |
| Metas | 20% | Progresso médio nas metas ativas |
| Controle do orçamento | 20% | Ficou dentro da renda? |

---

## Roadmap

### Fase 1 — Beta (próximo passo)
- [ ] Deploy no Render + PostgreSQL
- [ ] Evolution API + número WhatsApp dedicado
- [ ] Pipeline n8n completo
- [ ] 50 usuários beta

### Fase 2 — Produto
- [ ] Alertas proativos (APScheduler)
- [ ] Gastos fixos recorrentes
- [ ] Card mensal compartilhável (PNG)
- [ ] Score histórico mês a mês
- [ ] Cobrança via Mercado Pago (Pix no WhatsApp)
- [ ] Rate limiting (anti-ban WhatsApp)
- [ ] Plano Fundador R$9,90 (primeiros 100 usuários)

### Fase 3 — Escala
- [ ] Open Finance via Pluggy/Belvo (input zero, ~200 usuários Pro)
- [ ] Registro no BCB como Iniciador de Pagamentos
- [ ] ATLAS Score como alternativa ao Serasa para MEI

---

## Monetização

| Plano | Preço | Limite |
|---|---|---|
| Básico | R$0 | 30 transações/mês, 5 "Posso comprar?", 1 meta |
| Fundador | R$9,90/mês | Ilimitado — primeiros 100 usuários |
| Pro | R$19,90/mês | Ilimitado + alertas proativos + histórico 12 meses |
| MEI | R$39,90/mês | Pro + 2 carteiras (PF/PJ) + relatório para declaração |
