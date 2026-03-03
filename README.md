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
| Onboarding automático — usa nome do WhatsApp, sem perguntar | ✅ |
| Registrar gastos e receitas em linguagem natural | ✅ |
| Categorização automática (iFood → Alimentação, Uber → Transporte, vet → Pets...) | ✅ |
| **Categoria Pets 🐾** — vet, ração, petshop, banho/tosa | ✅ |
| Categorização de renda por fonte (Salário, Freelance, Aluguel, Investimentos...) | ✅ |
| Parcelamento — registra parcela + total, inferência automática | ✅ |
| Correção/exclusão da última transação ("corrige" / "apaga") | ✅ |
| Total do dia (filtro: só gastos / só receitas / tudo) | ✅ |
| Últimos N dias ("gastos dos últimos 3 dias", "ontem e hoje") | ✅ |
| Resumo semanal com lançamentos por categoria | ✅ |
| Resumo mensal com lançamentos individuais por categoria | ✅ |
| Filtro por tipo em todos os resumos (EXPENSE / INCOME / ALL) | ✅ |
| Comparativo mês atual vs anterior | ✅ |
| Alertas de ritmo semanal (compara contra mês anterior — sem falso positivo) | ✅ |
| Compromissos futuros (gastos fixos + faturas nos próximos N dias) | ✅ |
| Detalhes de transações por data ou mês | ✅ |
| Resumo de parcelas ativas com compromisso total restante | ✅ |
| "Posso comprar?" com 4 veredictos (✅ / ⚠️ / ⏳ / 🚫) | ✅ |
| Metas financeiras com barra de progresso | ✅ |
| Score mensal de saúde financeira (0-100, grau A+ a F) | ✅ |
| Memória de conversa por sessão | ✅ |
| Manual mobile-friendly em `/manual` | ✅ |

---

## Arquitetura

```
WhatsApp (usuário)
    ↓
Chatwoot            ← recebe e envia mensagens WhatsApp
    ↓
n8n                 ← orquestração do pipeline (inclui nome do usuário no header)
    ↓
ATLAS Agno API      ← agente LLM + tools financeiras (Render)
    ↓
PostgreSQL          ← usuários, transações, cartões, fixos, metas
```

### Agentes

| Agente | Função |
|---|---|
| `atlas` | Conversacional — UI de testes e WhatsApp direto |
| `parse_agent` | Interpreta mensagens → JSON estruturado (pipeline n8n) |
| `response_agent` | Gera resposta em PT-BR informal (pipeline n8n) |

### Tools financeiras

| Tool | O que faz |
|---|---|
| `get_user` | Retorna dados do usuário; se novo, retorna `__status:new_user` |
| `update_user_name` | Salva nome (extraído do perfil WhatsApp via n8n) |
| `update_user_income` | Salva renda mensal estimada |
| `save_transaction` | Registra gasto ou receita (suporta parcelamento); retorna texto formatado pronto |
| `get_last_transaction` | Retorna última transação registrada |
| `update_last_transaction` | Corrige última transação (parcelas, categoria, valor, pagamento) |
| `delete_last_transaction` | Apaga a última transação registrada |
| `get_today_total` | Total do dia ou dos últimos N dias, por categoria, com filtro de tipo |
| `get_transactions` | Lista transações por data ou mês |
| `get_installments_summary` | Parcelas ativas com compromisso total restante |
| `get_month_summary` | Resumo mensal com lançamentos individuais por categoria + filtro de tipo |
| `get_month_comparison` | Comparativo mês atual vs anterior |
| `get_week_summary` | Resumo semanal por categoria + alertas contra mês anterior |
| `get_upcoming_commitments` | Compromissos futuros (fixos + faturas) nos próximos N dias |
| `can_i_buy` | Analisa se pode fazer uma compra (usa renda real do mês) |
| `get_cards` | Lista cartões cadastrados |
| `get_card_bill` | Fatura atual de um cartão |
| `pay_card_bill` | Registra pagamento de fatura |
| `add_recurring_transaction` | Cadastra gasto fixo recorrente |
| `get_recurring_transactions` | Lista gastos fixos |
| `create_goal` | Cria meta financeira |
| `get_goals` | Lista metas com barra de progresso |
| `add_to_goal` | Adiciona valor a uma meta |
| `get_financial_score` | Score 0-100 de saúde financeira (grau A+ a F) |

---

## Onboarding

O n8n passa `[user_name: Nome Sobrenome]` no header de cada mensagem ao agente. No primeiro contato:

1. `get_user` detecta `is_new=True` → retorna `__status:new_user`
2. Agente extrai o primeiro nome do header, chama `update_user_name` automaticamente
3. Envia apresentação do ATLAS já com o nome + pergunta de renda
4. Sem etapa de "qual é o seu nome?" — experiência fluida desde a primeira mensagem

---

## Categorias de gasto

| Emoji | Categoria | Exemplos |
|---|---|---|
| 🍽️ | Alimentação | restaurante, mercado, iFood, delivery |
| 🚗 | Transporte | uber, combustível, ônibus, estacionamento |
| 💊 | Saúde | farmácia, consulta, exame, plano de saúde |
| 🏠 | Moradia | aluguel, condomínio, energia, água, internet |
| 🎮 | Lazer | cinema, viagem, bar, Netflix, jogos |
| 📱 | Assinaturas | Spotify, streaming, apps recorrentes |
| 📚 | Educação | curso, livro, escola, faculdade |
| 👟 | Vestuário | roupa, tênis, acessórios |
| 📈 | Investimento | aportes, previdência |
| 🐾 | **Pets** | vet, remédio animal, ração, petshop, banho/tosa |
| 📦 | Outros | tudo que não se encaixa acima |

---

## Lógica de parcelamento

| O usuário diz | ATLAS faz |
|---|---|
| "em 12x", "parcelei em 6x" | Registra parcelado direto |
| "à vista", "no débito", "no Pix" | Registra à vista direto |
| "no cartão" + valor ≥ R$200 | Pergunta se foi parcelado |
| Sem mencionar pagamento | Registra à vista |

---

## Stack

- **Python 3.13**
- **Agno** — framework de agentes LLM com AgentOS (FastAPI)
- **OpenAI GPT-4.1-mini** — modelo principal
- **SQLite** (local) / **PostgreSQL** (produção no Render)
- **Chatwoot** — inbox WhatsApp
- **n8n** — orquestração do pipeline
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
```

---

## Banco de dados

**Local**: SQLite em `data/atlas.db` — criado automaticamente na primeira execução.

**Produção**: PostgreSQL no Render — definir `DATABASE_URL` no ambiente.

### Tabelas

```
users                    — cadastro, nome, renda mensal, dia do salário
transactions             — gastos e receitas (suporta parcelamento e cartão)
credit_cards             — cartões com fechamento, vencimento e limite
recurring_transactions   — gastos fixos recorrentes por dia do mês
card_bill_snapshots      — histórico de faturas por cartão/mês
financial_goals          — metas com progresso
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
category              TEXT           -- inclui Pets 🐾
merchant              TEXT           -- estabelecimento (filtrável no futuro)
payment_method        TEXT           -- CREDIT | DEBIT | PIX | CASH | TED
card_id               TEXT           -- FK credit_cards (nullable)
notes                 TEXT
occurred_at           TEXT           -- ISO 8601 local (UTC-3)
```

---

## Score de Saúde Financeira (AFHS)

Nota 0-100, graus A+ / A / B+ / B / C / D / F.

| Componente | Peso | Cálculo |
|---|---|---|
| Taxa de poupança | 30% | % da renda guardada (meta: 20%+) |
| Consistência | 20% | Dias com registro / dias do mês |
| Adesão às metas | 25% | Progresso médio nas metas ativas |
| Volatilidade | 15% | Variação de gastos vs mês anterior |
| Dívidas/fixos | 10% | % da renda comprometida com fixos |

---

## Roadmap

### Fase 1 — MVP em teste (atual)
- [x] Deploy Render + PostgreSQL
- [x] Pipeline n8n + Chatwoot
- [x] Onboarding com nome do WhatsApp
- [x] Resumos diário / semanal / mensal com categorias detalhadas
- [x] Categoria Pets, filtro por tipo, últimos N dias
- [x] Cartões de crédito + gastos fixos + compromissos futuros
- [ ] 50 usuários beta

### Fase 2 — Produto
- [ ] Alertas proativos (APScheduler)
- [ ] Indicador "digitando..." no WhatsApp durante processamento
- [ ] Card mensal compartilhável (PNG)
- [ ] Score histórico mês a mês
- [ ] Filtro por estabelecimento ("quanto gastei no Talentos?")
- [ ] Cobrança via Pix (Mercado Pago)
- [ ] Plano Fundador R$9,90 (primeiros 100 usuários)

### Fase 3 — Escala
- [ ] Open Finance via Pluggy/Belvo (input zero)
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
