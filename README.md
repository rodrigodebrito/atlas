# ATLAS

Assistente financeiro pessoal via WhatsApp para o mercado brasileiro.

> "O assistente financeiro que mora no seu WhatsApp"

---

## O que é

ATLAS é um copiloto financeiro que funciona 100% dentro do WhatsApp. O usuário manda uma mensagem em linguagem natural — "gastei 50 no iFood", "posso comprar um tênis de 300?" — e o agente responde, registra e analisa em segundos.

Sem app para baixar. Sem planilha para abrir. Sem fricção.

**Público-alvo**: Pessoas físicas, freelancers e MEI, 25-38 anos, capitais brasileiras.

---

## Features

| Feature | Status |
|---|---|
| Onboarding automático via pré-roteador (nome do WhatsApp, sem LLM) | ✅ |
| Registrar gastos e receitas em linguagem natural | ✅ |
| Categorização automática com auto-aprendizado (merchant→categoria) | ✅ |
| Auto-aprendizado merchant→cartão padrão | ✅ |
| Parcelamento — registra parcela + total, inferência automática | ✅ |
| Correção/exclusão da última transação | ✅ |
| Deleção em massa com confirmação em 2 etapas (pending_actions) | ✅ |
| Filtro por estabelecimento ("quanto gastei no iFood?") | ✅ |
| Total do dia / últimos N dias | ✅ |
| Resumo semanal com categorias | ✅ |
| Resumo mensal com lançamentos, compromissos e saldo real | ✅ |
| Comparativo mês atual vs anterior | ✅ |
| Extrato separado (entradas vs saídas com totais) | ✅ |
| Suporte a múltiplos meses ("compromissos de março e abril") | ✅ |
| Cartões de crédito (fechamento, vencimento, limite, fatura) | ✅ |
| Extrato por cartão — gastos agrupados por categoria + limite disponível | ✅ |
| Atualização de limite do cartão | ✅ |
| Contas a pagar (bills) — fixos + faturas + boletos com status pago/pendente | ✅ |
| Pagamento de contas com fuzzy matching (pay_bill) | ✅ |
| "Posso comprar?" com 4 veredictos (✅ / ⚠️ / ⏳ / 🚫) | ✅ |
| "Vai sobrar?" com 3 cenários | ✅ |
| Score de saúde financeira (A+ a F) | ✅ |
| Orçamento diário baseado no ciclo de salário | ✅ |
| Metas financeiras com barra de progresso | ✅ |
| Lembretes proativos de gastos fixos e faturas (cron) | ✅ |
| Alertas inline (categoria estourou, ritmo acelerado) | ✅ |
| Pré-roteador regex (~70% sem LLM) | ✅ |
| Manual mobile-friendly em `/manual` | ✅ |

---

## Arquitetura

```
WhatsApp (usuário)
    ↓
Chatwoot            ← recebe e envia mensagens WhatsApp
    ↓
n8n                 ← orquestração (texto/áudio → /v1/chat)
    ↓
ATLAS API           ← pré-roteador + agente LLM + tools (Render)
    ↓
PostgreSQL          ← usuários, transações, cartões, fixos, metas, bills
```

### Fluxo de processamento

```
Mensagem chega → _pre_route() tenta resolver com regex
    ├─ Match encontrado → resposta imediata (sem custo LLM)
    └─ Sem match → agente LLM (gpt-4.1) com tools
```

O pré-roteador resolve ~70% das mensagens (resumos, saldos, compromissos, confirmações, ajuda) sem chamar o LLM, reduzindo custo e latência.

### Tools financeiras

| Tool | O que faz |
|---|---|
| `get_user` | Retorna dados do usuário + preferências aprendidas |
| `update_user_name` | Salva nome do usuário |
| `update_user_income` | Salva renda mensal |
| `save_transaction` | Registra gasto ou receita (parcelamento, cartão, alertas inline) |
| `get_last_transaction` | Retorna última transação |
| `update_last_transaction` | Corrige última transação |
| `delete_last_transaction` | Apaga última transação |
| `delete_transactions` | Deleção em massa com confirmação em 2 etapas |
| `get_today_total` | Total do dia ou últimos N dias por categoria |
| `get_transactions` | Extrato por data/mês (separado entradas vs saídas) |
| `get_transactions_by_merchant` | Filtra por estabelecimento |
| `get_category_breakdown` | Detalhe por categoria |
| `get_month_summary` | Resumo mensal + compromissos pendentes + saldo real |
| `get_month_comparison` | Comparativo mês atual vs anterior |
| `get_week_summary` | Resumo semanal + alertas |
| `get_installments_summary` | Parcelas ativas e compromisso total |
| `can_i_buy` | Analisa se pode comprar (4 veredictos) |
| `will_i_have_leftover` | Projeção fim do mês (3 cenários) |
| `get_financial_score` | Score 0-100 (A+ a F) |
| `set_salary_day` | Configura dia do salário |
| `get_salary_cycle` | Orçamento diário no ciclo |
| `register_card` | Cadastra cartão de crédito |
| `get_cards` | Lista cartões com faturas |
| `get_card_statement` | Extrato detalhado por cartão (categorias, limite, fatura) |
| `update_card_limit` | Atualiza limite do cartão |
| `close_bill` | Registra pagamento de fatura de cartão |
| `set_card_bill` | Define valor de fatura atual |
| `set_future_bill` | Registra saldo pré-existente de fatura futura |
| `get_next_bill` | Estima próxima fatura |
| `register_recurring` | Cadastra gasto fixo recorrente |
| `get_recurring` | Lista gastos fixos |
| `deactivate_recurring` | Desativa gasto fixo |
| `register_bill` | Registra conta a pagar (boleto, fatura avulsa) |
| `pay_bill` | Paga conta com fuzzy matching |
| `get_bills` | Lista contas do mês com status pago/pendente |
| `get_upcoming_commitments` | Compromissos futuros (próximos N dias) |
| `create_goal` | Cria meta financeira |
| `get_goals` | Lista metas com progresso |
| `add_to_goal` | Adiciona valor a uma meta |
| `set_reminder_days` | Configura antecedência dos lembretes |

---

## Onboarding

Feito 100% no pré-roteador (sem LLM):

1. Mensagem chega → `_onboard_if_new()` checa se o telefone existe no banco
2. Se novo: cria usuário, extrai nome do header, salva
3. Retorna mensagem de boas-vindas fixa com exemplos + link do manual
4. Sem perguntas, sem improvisação do modelo

---

## Categorias de gasto

| Emoji | Categoria | Exemplos |
|---|---|---|
| 🍽️ | Alimentação | restaurante, mercado, iFood, delivery |
| 🚗 | Transporte | uber, combustível, ônibus, estacionamento |
| 💊 | Saúde | farmácia, consulta, exame, plano de saúde |
| 🏠 | Moradia | aluguel, condomínio, energia, água, internet |
| 🎮 | Lazer | cinema, viagem, bar, jogos |
| 📱 | Assinaturas | Spotify, Netflix, streaming, apps recorrentes |
| 📚 | Educação | curso, livro, escola, faculdade |
| 👟 | Vestuário | roupa, tênis, acessórios |
| 📈 | Investimento | aportes, previdência |
| 🐾 | Pets | vet, ração, petshop, banho/tosa |
| 📦 | Outros | tudo que não se encaixa acima |

---

## Stack

- **Python 3.13**
- **Agno** — framework de agentes LLM com AgentOS (FastAPI)
- **OpenAI GPT-4.1** — modelo principal
- **SQLite** (local) / **PostgreSQL** (produção no Render)
- **Chatwoot** — inbox WhatsApp
- **n8n** — orquestração do pipeline (texto e áudio)

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

**Local**: SQLite em `data/atlas.db` — criado automaticamente.

**Produção**: PostgreSQL no Render — definir `DATABASE_URL`.

### Tabelas

```
users                    — cadastro, nome, renda mensal, dia do salário
transactions             — gastos e receitas (parcelamento, cartão, merchant)
credit_cards             — cartões com fechamento, vencimento, limite
recurring_transactions   — gastos fixos recorrentes por dia do mês
bills                    — contas a pagar (auto-geradas + avulsas) com status pago/pendente
card_bill_snapshots      — histórico de faturas por cartão/mês
financial_goals          — metas com progresso
pending_actions          — ações pendentes de confirmação (deleção em massa)
merchant_category_rules  — auto-aprendizado merchant→categoria
merchant_card_rules      — auto-aprendizado merchant→cartão
pending_statement_imports — importações pendentes (legacy)
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

### Fase 1 — MVP funcional (concluída)
- [x] Deploy Render + PostgreSQL
- [x] Pipeline n8n + Chatwoot (texto + áudio)
- [x] Onboarding via pré-roteador (sem LLM)
- [x] Pré-roteador regex (~70% economia)
- [x] Resumos diário / semanal / mensal
- [x] Cartões, gastos fixos, compromissos futuros
- [x] Filtro por estabelecimento
- [x] Deleção em massa com confirmação (pending_actions)
- [x] Sistema de contas a pagar (bills) com pagamento
- [x] Extrato por cartão com categorias e limite
- [x] Suporte a múltiplos meses
- [x] Alertas inline (categoria estourou, ritmo acelerado)
- [x] Auto-aprendizado merchant→categoria e merchant→cartão

### Fase 2 — Engajamento (em andamento)
- [ ] Painel HTML inteligente (gráficos, insights, link temporário)
- [ ] Relatório semanal automático (cron domingo 20h)
- [ ] Recap mensal ("Spotify Wrapped" das finanças)
- [ ] Modo Desafio (gamificação de economia)
- [ ] 50 usuários beta
- [ ] Cobrança via Pix (Mercado Pago)

### Fase 3 — Escala
- [ ] Open Finance via Pluggy/Belvo
- [ ] Score histórico mês a mês
- [ ] Plano Fundador R$9,90 (primeiros 100 usuários)

---

## Monetização

| Plano | Preço | Limite |
|---|---|---|
| Básico | R$0 | 30 transações/mês, 5 "Posso comprar?", 1 meta |
| Fundador | R$9,90/mês | Ilimitado — primeiros 100 usuários |
| Pro | R$19,90/mês | Ilimitado + alertas proativos + histórico 12 meses |
| MEI | R$39,90/mês | Pro + 2 carteiras (PF/PJ) + relatório para declaração |
