# ATLAS

Assistente financeiro pessoal via WhatsApp para o mercado brasileiro.

> "O assistente financeiro que mora no seu WhatsApp"

---

## O que é

ATLAS é um copiloto financeiro que funciona 100% dentro do WhatsApp. O usuário manda uma mensagem em linguagem natural — "gastei 50 no iFood", "posso comprar um tênis de 300?", "qual minha média diária?" — e o agente responde, registra e analisa em segundos.

Sem app para baixar. Sem planilha para abrir. Sem fricção.

**Público-alvo**: Pessoas físicas, freelancers e MEI, 25-38 anos, capitais brasileiras.

---

## Features

| Feature | Status |
|---|---|
| Onboarding automático via pré-roteador (nome do WhatsApp, sem LLM) | ✅ |
| Registrar gastos e receitas em linguagem natural | ✅ |
| Extrator inteligente de gastos (independente de ordem, sem regex rígido) | ✅ |
| Categorização automática com auto-aprendizado (merchant→categoria) | ✅ |
| Auto-aprendizado merchant→cartão padrão | ✅ |
| Parcelamento — registra parcela + total, inferência automática | ✅ |
| Correção/exclusão da última transação | ✅ |
| Deleção em massa com confirmação em 2 etapas (pending_actions) | ✅ |
| Filtro por estabelecimento ("quanto gastei no iFood?") | ✅ |
| Filtro por categoria ("quanto gastei de alimentação?") | ✅ |
| Médias de consumo (diária, semanal, por categoria, projeção) | ✅ |
| Total do dia / últimos N dias | ✅ |
| Resumo semanal com categorias | ✅ |
| Resumo mensal com lançamentos, compromissos e saldo real | ✅ |
| Comparativo mês atual vs anterior | ✅ |
| Extrato separado (entradas vs saídas com totais) | ✅ |
| Suporte a múltiplos meses ("compromissos de março e abril") | ✅ |
| Cartões de crédito (fechamento, vencimento, limite, fatura) | ✅ |
| Extrato por cartão — gastos agrupados por categoria + limite disponível | ✅ |
| Gerenciar cartões pelo painel (criar, editar fatura, excluir) | ✅ |
| Contas a pagar (bills) — fixos + faturas + boletos com status pago/pendente | ✅ |
| Pagamento de contas com fuzzy matching (pay_bill) | ✅ |
| "Posso comprar?" com 4 veredictos (✅ / ⚠️ / ⏳ / 🚫) | ✅ |
| "Vai sobrar?" com 3 cenários | ✅ |
| Score de saúde financeira (A+ a F) | ✅ |
| Orçamento diário baseado no ciclo de salário | ✅ |
| Metas financeiras com barra de progresso | ✅ |
| Lembretes proativos de gastos fixos e faturas (cron) | ✅ |
| Alertas inline (categoria estourou, ritmo acelerado) | ✅ |
| Agenda inteligente (eventos, lembretes recorrentes, intervalos) | ✅ |
| Pré-roteador regex (~70% sem LLM) + keyword router fallback | ✅ |
| Painel HTML visual com gráficos, filtros, CRUD de transações e cartões | ✅ |
| Seção de agenda no painel (eventos agrupados por data) | ✅ |
| Link do painel no resumo mensal (token temporário 30min) | ✅ |
| Pós-processador anti-perguntas (LLM nunca faz pergunta ao usuário) | ✅ |
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
PostgreSQL          ← usuários, transações, cartões, fixos, metas, agenda
```

### Fluxo de processamento

```
Mensagem chega → _pre_route() tenta resolver com regex
    ├─ Match encontrado → resposta imediata (sem custo LLM)
    ├─ Smart expense extract → detecta gastos em qualquer formato
    └─ Sem match → _keyword_route() tenta keywords fuzzy
        └─ Sem match → agente LLM (gpt-4.1) com tools
```

O pré-roteador resolve ~70% das mensagens (resumos, saldos, compromissos, gastos, confirmações, ajuda) sem chamar o LLM, reduzindo custo e latência.

### Smart Expense Extractor

Extrator inteligente de gastos independente de ordem. Funciona com qualquer estrutura de frase:
- Encontra VALOR (R$X, X reais, número solto)
- Detecta INTENÇÃO (verbos de gasto + merchants conhecidos + palavra "cartão")
- Encontra CARTÃO (compara com cartões reais do usuário no DB — longest match)
- Extrai MERCHANT (remove valor, cartão e noise words do texto)
- Auto-categoriza com regras de keyword

Exemplos que funcionam: "abasteci 32 de gasolina no posto shell no cartão mercado pago", "uber 15", "pagamento gasolina 130 mercado pago", "paguei R$53,80 na padaria".

### Roteamento inteligente de consultas

O pré-roteador detecta padrões com preposição (de/em/no/na/com) para rotear consultas:
- "quanto gastei de alimentação este mês?" → `get_category_breakdown` (filtro por categoria)
- "quanto gastei no deville?" → `get_transactions_by_merchant` (filtro por merchant)
- "qual minha média diária?" → `get_spending_averages` (médias de consumo)
- "quanto gastei este mês?" → `get_month_summary` (resumo geral)

Categorias conhecidas (alimentação, transporte, saúde, etc.) são mapeadas automaticamente. Termos desconhecidos são tratados como busca por merchant.

---

## Tools financeiras

| Tool | O que faz |
|---|---|
| `save_transaction` | Registra gasto ou receita (parcelamento, cartão, alertas inline) |
| `get_month_summary` | Resumo mensal + compromissos pendentes + saldo real |
| `get_week_summary` | Resumo semanal + alertas |
| `get_today_total` | Total do dia ou últimos N dias por categoria |
| `get_transactions` | Extrato por data/mês (separado entradas vs saídas) |
| `get_transactions_by_merchant` | Filtra por estabelecimento (busca parcial) |
| `get_category_breakdown` | Detalhe por categoria com agrupamento por merchant |
| `get_all_categories_breakdown` | Breakdown geral de todas as categorias do mês |
| `get_spending_averages` | Médias diária/semanal, projeção, por categoria |
| `get_month_comparison` | Comparativo mês atual vs anterior |
| `get_last_transaction` | Retorna última transação |
| `update_last_transaction` | Corrige última transação |
| `delete_last_transaction` | Apaga última transação |
| `delete_transactions` | Deleção em massa com confirmação em 2 etapas |
| `update_merchant_category` | Reclassifica merchant ("iFood é Lazer") |
| `can_i_buy` | Analisa se pode comprar (4 veredictos) |
| `will_i_have_leftover` | Projeção fim do mês (3 cenários) |
| `get_financial_score` | Score 0-100 (A+ a F) |
| `set_salary_day` | Configura dia do salário |
| `get_salary_cycle` | Orçamento diário no ciclo |
| `register_card` | Cadastra cartão de crédito |
| `get_cards` | Lista cartões com faturas |
| `get_card_statement` | Extrato detalhado por cartão |
| `update_card_limit` | Atualiza limite do cartão |
| `close_bill` | Registra pagamento de fatura de cartão |
| `set_card_bill` | Define valor de fatura atual |
| `get_next_bill` | Estima próxima fatura |
| `get_installments_summary` | Parcelas ativas e compromisso total |
| `register_recurring` | Cadastra gasto fixo recorrente |
| `get_recurring` | Lista gastos fixos |
| `deactivate_recurring` | Desativa gasto fixo |
| `register_bill` | Registra conta a pagar |
| `pay_bill` | Paga conta com fuzzy matching |
| `get_bills` | Lista contas do mês com status pago/pendente |
| `get_upcoming_commitments` | Compromissos futuros (próximos N dias) |
| `create_goal` | Cria meta financeira |
| `get_goals` | Lista metas com progresso |
| `add_to_goal` | Adiciona valor a uma meta |
| `create_agenda_event` | Cria evento/lembrete (once, daily, weekly, monthly, interval) |
| `list_agenda_events` | Lista próximos eventos agrupados por data |
| `complete_agenda_event` | Marca evento como concluído (ou avança recorrente) |
| `delete_agenda_event` | Exclui evento com confirmação |
| `get_panel_url` | Gera link temporário (30min) para o painel visual |

---

## Agenda inteligente

Sistema completo de lembretes e eventos via WhatsApp:

- **Evento único**: "me lembra amanhã às 14h reunião"
- **Diário**: "tomar remédio todo dia às 8h"
- **Semanal**: "toda segunda reunião 9h"
- **Intervalo**: "tomar água de 4 em 4 horas" (respeita horário ativo 8h-22h)
- **Alertas configuráveis**: após criar, pergunta "quanto tempo antes quer que eu avise?"
- **Endpoint de check**: `GET /v1/reminders/check` — chamado pelo n8n a cada 15min
- **Integrado ao painel**: seção de agenda com visualização e exclusão

### Tabela `agenda_events`

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT | FK para users |
| `title` | TEXT | Nome do evento |
| `event_at` | TEXT | ISO datetime do próximo disparo |
| `all_day` | INTEGER | 0/1 evento de dia inteiro |
| `recurrence_type` | TEXT | once/daily/weekly/monthly/interval |
| `recurrence_rule` | TEXT | JSON: `{"weekdays":[0,2]}` ou `{"interval_hours":4}` |
| `alert_minutes_before` | INTEGER | Minutos antes para alertar (0=sem alerta) |
| `active_start_hour` | INTEGER | Hora início para intervals (default 8) |
| `active_end_hour` | INTEGER | Hora fim para intervals (default 22) |
| `status` | TEXT | active/done/dismissed/paused |
| `next_alert_at` | TEXT | Pré-computado: quando disparar o próximo alerta |
| `category` | TEXT | geral/saude/trabalho/pessoal/financeiro |

---

## Painel HTML

Dashboard web acessível via link temporário (30min). Gerado pelo endpoint `GET /v1/painel?t=TOKEN`.

### Seções
- **Resumo financeiro**: receitas, despesas, saldo, score
- **Gráfico de pizza**: gastos por categoria
- **Gráfico de linha**: gastos diários no mês
- **Breakdown por categoria**: com barras visuais
- **Lista de transações**: com filtro por categoria/cartão, edição e exclusão inline
- **Cartões**: fatura atual, limite, uso, ciclo — botão para editar/excluir/adicionar
- **Agenda**: eventos agrupados por data com exclusão

### API endpoints do painel

| Endpoint | Método | O que faz |
|---|---|---|
| `/v1/painel` | GET | Renderiza o painel HTML completo |
| `/v1/api/transaction/{id}` | PUT | Edita transação (amount, category, merchant, date) |
| `/v1/api/transaction/{id}` | DELETE | Exclui transação |
| `/v1/api/card/{id}` | PUT | Edita cartão (closing_day, due_day, limit, available, fatura) |
| `/v1/api/card/{id}` | DELETE | Exclui cartão (desvincula transações) |
| `/v1/api/card` | POST | Cria novo cartão |
| `/v1/api/agenda/{id}` | DELETE | Exclui evento da agenda |

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

## Estrutura do projeto

```
Atlas/
├── agno_api/
│   ├── agent.py          ← Arquivo principal (~10.000 linhas): API, tools, roteadores, painel
│   └── static/
│       └── manual.html   ← Manual mobile-friendly
├── pyproject.toml        ← Dependências e config
├── README.md
└── .env                  ← Variáveis de ambiente (não commitado)
```

### Anatomia do `agent.py`

O arquivo é monolítico por design (single-file deploy no Render). Seções principais:

| Linhas (aprox.) | Seção |
|---|---|
| 1-500 | Imports, config, DB init (SQLite + PostgreSQL), tabelas |
| 500-900 | `save_transaction`, alertas inline, helpers financeiros |
| 900-2200 | Tools de consulta: resumo, semana, hoje, categorias, merchant |
| 2200-3500 | Tools de cartão: register, statement, limit, bill, next_bill |
| 3500-5000 | Tools avançados: can_i_buy, will_i_have_leftover, score, goals |
| 5000-5700 | Agenda: create/list/complete/delete events, helpers de recorrência |
| 5700-6500 | ATLAS_INSTRUCTIONS (prompt do sistema para o LLM) |
| 6500-6900 | Painel: `_get_panel_data`, `_render_panel_html` (dados) |
| 6900-7800 | Painel: HTML template, CSS, JavaScript (renderização, CRUD) |
| 7800-8100 | API endpoints do painel (PUT/DELETE/POST para transações, cartões, agenda) |
| 8100-8400 | Pré-roteador: `_extract_*`, `_onboard_if_new`, `_pre_route` início |
| 8400-8900 | Pré-roteador: smart extractor, keyword router, rotas de consulta |
| 8900-9200 | Chat endpoint, cron de lembretes diários e agenda check |
| 9200-9700 | Import de faturas, endpoints de debug |
| 9700-10100 | Manual endpoint, middleware, AgentOS config |

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

## Deploy (Render)

- **URL**: `https://atlas-m3wb.onrender.com`
- **Tipo**: Free tier (sleeps after inactivity, deploys em 2-5 min)
- **Build**: `pip install .` + `uvicorn agno_api.agent:app`
- O deploy é automático a cada push no `main`

---

## Banco de dados

**Local**: SQLite em `data/atlas.db` — criado automaticamente.

**Produção**: PostgreSQL no Render — definir `DATABASE_URL`.

### Tabelas

```
users                    — cadastro, nome, renda mensal, dia do salário
transactions             — gastos e receitas (parcelamento, cartão, merchant)
credit_cards             — cartões com fechamento, vencimento, limite, fatura
recurring_transactions   — gastos fixos recorrentes por dia do mês
bills                    — contas a pagar (auto-geradas + avulsas) com status pago/pendente
card_bill_snapshots      — histórico de faturas por cartão/mês
financial_goals          — metas com progresso
pending_actions          — ações pendentes de confirmação (deleção em massa, alertas agenda)
merchant_category_rules  — auto-aprendizado merchant→categoria
merchant_card_rules      — auto-aprendizado merchant→cartão
panel_tokens             — tokens temporários (30min) para acesso ao painel visual
agenda_events            — eventos e lembretes da agenda inteligente
pending_statement_imports — importações de fatura pendentes
unrouted_messages        — mensagens que não foram roteadas (para análise)
```

---

## Endpoints principais

| Endpoint | Método | Descrição |
|---|---|---|
| `/v1/chat` | POST | Chat principal (form-data: message, user_phone, session_id) |
| `/v1/painel` | GET | Painel HTML com token |
| `/v1/reminders/daily` | GET | Cron de lembretes diários (fixos + faturas) |
| `/v1/reminders/check` | GET | Check de lembretes da agenda (cada 15min) |
| `/manual` | GET | Manual mobile-friendly |
| `/health` | GET | Health check |
| `/v1/debug/extract` | GET | Debug do extrator inteligente |

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

## Decisões técnicas importantes

### Por que monolítico (single file)?
- Deploy simples no Render free tier
- Todas as tools e rotas no mesmo namespace — sem import circular
- Search/replace fácil com IDE
- Trade-off aceito: file grande (~10k linhas) mas tudo num lugar só

### Por que pré-roteador + keyword router + LLM?
- Pré-roteador (regex): rápido, previsível, ~70% das mensagens
- Keyword router: tolerante a typos, fallback antes do LLM
- LLM (gpt-4.1): só para casos complexos/ambíguos — reduz custo

### Smart extractor vs regex rígido
- Regex rígido quebrava com variações ("abasteci 32 de gasolina no posto shell")
- Smart extractor é independente de ordem: acha componentes (valor, cartão, merchant) separadamente
- Consulta cartões reais do DB para matching preciso

### Alertas inline conservadores
- Só alerta se mês anterior teve >R$50 na categoria (evita 1º mês)
- Max 500% de variação (evita % absurdos com poucos dados)
- Projeção só após dia 8 com >R$100 gastos

### `closing_day=0` guard
- Cartões auto-criados têm `closing_day=0, due_day=0`
- `today.replace(day=0)` crashava com ValueError
- Guard aplicado em 5+ locais: retorna início do mês ou pula o cartão

---

## Roadmap

### Fase 1 — MVP funcional (concluída)
- [x] Deploy Render + PostgreSQL
- [x] Pipeline n8n + Chatwoot (texto + áudio)
- [x] Onboarding via pré-roteador (sem LLM)
- [x] Pré-roteador regex + keyword router
- [x] Smart expense extractor
- [x] Resumos diário / semanal / mensal
- [x] Cartões, gastos fixos, compromissos futuros
- [x] Filtro por estabelecimento e por categoria
- [x] Médias de consumo (diária, semanal, projeção)
- [x] Deleção em massa com confirmação
- [x] Sistema de contas a pagar com pagamento
- [x] Alertas inline conservadores
- [x] Auto-aprendizado merchant→categoria e merchant→cartão
- [x] Agenda inteligente (eventos, recorrentes, intervalos)
- [x] Painel HTML com CRUD completo (transações, cartões, agenda)

### Fase 2 — Engajamento (em andamento)
- [x] Painel HTML inteligente (gráficos, filtros, CRUD)
- [x] Agenda inteligente com notificações
- [ ] Relatório semanal automático (cron domingo 20h)
- [ ] Recap mensal ("Spotify Wrapped" das finanças)
- [ ] Editar/pausar eventos da agenda pelo WhatsApp
- [ ] Snooze de alertas ("adia 1h", "adia pra amanhã")
- [ ] Google Calendar sync (OAuth via WhatsApp)
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

---

## Para contribuidores

### Como dar continuidade

1. **Tudo está em `agno_api/agent.py`** — é o único arquivo de código
2. Use o mapa de seções acima para navegar (busque por `# ==` para separadores)
3. Tools usam decorator `@tool` do Agno — para chamar programaticamente use `.entrypoint`
4. Pré-roteador (`_pre_route`): variável normalizada é `msg` (lowercase)
5. Keyword router (`_keyword_route`): variável normalizada é `n` (sem acentos)
6. O painel HTML é gerado como f-string Python — `{{` escapa chaves no JS
7. DB: `_get_conn()` retorna conexão, `_db()` é context manager (use com `with`)
8. Deploy: push no main → Render auto-deploy (2-5 min, free tier pode dormir)

### Cuidados
- **`_call()` scope**: definida dentro de `_pre_route()` como closure — não acessível de fora
- **`closing_day=0`**: sempre checar antes de `today.replace(day=closing_day)`
- **`_PGCursor`**: faz `sql.replace("%", "%%").replace("?", "%s")` — cuidado com `%s` em SQL
- **Variável `n` vs `msg`**: `n` só existe em `_keyword_route`, `msg` em `_pre_route`
- **`@tool` wrapper**: funções são `agno.tools.function.Function`, não callables diretos
