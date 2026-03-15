# Próximos Passos do ATLAS

## Contexto
ATLAS é um assistente financeiro no WhatsApp, MVP completo com: gastos, cartões, compromissos, agenda com notificações, painel visual. Tudo funciona para 1 usuário. Agora precisa evoluir para engajamento + escala (50 beta users).

## Estado Atual
- ~10.700 linhas em `agno_api/agent.py`
- Agenda inteligente funcionando com notificações via n8n (1min)
- Pagamento de faturas/contas com categorias separadas no resumo
- Painel HTML com CRUD completo
- Pre-roteador resolve ~70% sem LLM

---

## Bloco 1: Engajamento (reter o usuário)

### 1.1 Relatório Semanal Automático
**Esforço**: Baixo | **Impacto**: Alto
- Cron domingo 20h via n8n (novo workflow)
- Endpoint `GET /v1/reports/weekly` que chama `get_week_summary()` pra cada usuário ativo
- Mensagem formatada: "Resumo da semana: gastou X, top categoria Y, comparação com semana anterior"
- Reutiliza lógica existente de `get_week_summary`

### 1.2 Recap Mensal ("Spotify Wrapped" das finanças)
**Esforço**: Médio | **Impacto**: Alto
- Dispara dia 1 de cada mês (cron n8n)
- Endpoint `GET /v1/reports/monthly-recap`
- Conteúdo: top 5 merchants, categoria campeã, dia mais gastador, streak de registro, score do mês, comparativo com mês anterior
- Formato visual com emojis e dados curiosos ("Você gastou o equivalente a X pizzas em delivery")

### 1.3 Snooze de Alertas da Agenda
**Esforço**: Baixo | **Impacto**: Médio
- Detectar "adia 1h", "adia 30 min", "adia pra amanhã" no pre-roteador
- Recalcular `next_alert_at` do evento mais recente notificado
- Pattern: busca `last_notified_at` recente + recalcula

### 1.4 Editar/Pausar Eventos via WhatsApp
**Esforço**: Médio | **Impacto**: Médio
- "pausar lembrete água" → status = 'paused'
- "retomar lembrete água" → status = 'active', recomputa next_alert_at
- "editar reunião pra 15h" → atualiza event_at
- Usa pending_actions para confirmação quando ambíguo

---

## Bloco 2: Qualidade & Robustez

### 2.1 Atualizar Manual HTML
**Esforço**: Baixo | **Impacto**: Médio
- Adicionar seções: painel (CRUD, gráficos), agenda (criar, listar, snooze), filtros (categoria, merchant), médias, pagamento de faturas
- Exemplos interativos para cada feature

### 2.2 Tratamento de Erros no Áudio
**Esforço**: Baixo | **Impacto**: Médio
- Detectar quando n8n envia erro de transcrição
- Responder: "Não consegui entender o áudio. Tenta de novo ou manda por texto?"
- Guard no `/v1/chat` para mensagens vazias ou com markers de erro

### 2.3 Análise de Mensagens Não-Roteadas
**Esforço**: Baixo | **Impacto**: Médio
- Endpoint `/v1/debug/unrouted-analysis` que agrupa por padrão/frequência
- Identificar top 10 mensagens que o bot não entende
- Usar para criar novas rotas no pre-roteador

### 2.4 Connection Pooling / Leak Prevention
**Esforço**: Médio | **Impacto**: Alto (escala)
- Revisar funções sem `conn.close()` em finally
- Considerar usar `with _db()` uniformemente
- Ou implementar pool simples com psycopg2.pool

---

## Bloco 3: Preparação para Escala (50 beta)

### 3.1 Limites por Plano (Rate Limiting)
**Esforço**: Médio | **Impacto**: Crítico
- Coluna `plan` na tabela `users` (free/founder/pro)
- Contadores: transações/mês, consultas "posso comprar?", metas
- Free: 30 tx/mês, 5 "posso comprar?", 1 meta
- Guard no `save_transaction` e tools limitadas
- Mensagem amigável quando atinge limite + upsell

### 3.2 Observabilidade Básica
**Esforço**: Médio | **Impacto**: Alto
- Logging estruturado (JSON) em vez de prints espalhados
- Contadores: requests/min, erros/min, LLM calls/user, latência
- Endpoint `/v1/admin/stats` protegido
- Alerta se erro rate > threshold

### 3.3 Score Histórico (mês a mês)
**Esforço**: Médio | **Impacto**: Médio
- Tabela `monthly_scores` (user_id, month, score, breakdown_json)
- Snapshot automático no recap mensal
- "Meu score dos últimos 6 meses" → gráfico de evolução
- Gamificação: "Subiu de C para B+!"

---

## Bloco 4: Integrações Futuras (pós-beta)

### 4.1 Google Calendar Sync
- OAuth flow via link no WhatsApp
- Sync unidirecional: Atlas → Google Calendar
- Botão no painel "Conectar Google Agenda"

### 4.2 Open Finance (Pluggy/Belvo)
- Importação automática de transações bancárias
- Reconciliação com gastos manuais

### 4.3 Cobrança via Pix (Mercado Pago / Asaas)
- Integrar com workflow Asaas que já existe no n8n
- Fluxo: "quero ser founder" → link de pagamento → webhook confirma → ativa plano

---

## Ordem de Implementação Recomendada

| Prioridade | Item | Esforço | Impacto |
|---|---|---|---|
| 1 | 1.1 Relatório semanal | Baixo | Alto |
| 2 | 2.1 Manual atualizado | Baixo | Médio |
| 3 | 1.3 Snooze de alertas | Baixo | Médio |
| 4 | 2.2 Tratamento de áudio | Baixo | Médio |
| 5 | 1.2 Recap mensal | Médio | Alto |
| 6 | 1.4 Editar/pausar agenda | Médio | Médio |
| 7 | 3.1 Rate limiting | Médio | Crítico (escala) |
| 8 | 2.4 Connection pooling | Médio | Alto (escala) |
| 9 | 3.2 Observabilidade | Médio | Alto (escala) |
| 10 | 3.3 Score histórico | Médio | Médio |

## Arquivos a Modificar
- `agno_api/agent.py` — tudo (monolítico)
- `agno_api/static/manual.html` — manual atualizado
- Workflows n8n — novos crons (semanal, mensal)

## Verificação
- Relatório semanal: simular cron, verificar mensagem no WhatsApp
- Snooze: "adia 1h" após lembrete → next_alert_at recalculado
- Rate limit: atingir 30 tx → mensagem de limite
- Score histórico: "meu score dos últimos meses" → lista evolução
