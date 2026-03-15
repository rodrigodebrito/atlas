# Programa de Indicacoes e Saques - ATLAS

## Resposta curta
Sim, e uma boa ideia para crescer e ajudar na retencao, desde que o incentivo premie **usuario ativo** (nao apenas cadastro) e tenha limites claros para evitar fraude e custo alto.

## Objetivo
- Aumentar aquisicao via boca a boca no WhatsApp.
- Aumentar retencao com recompensa mensal recorrente por indicados ativos.
- Manter CAC controlado com pagamentos previsiveis (1 saque por mes).

## Modelo recomendado (MVP)
- Convidado: ganha `R$25` em credito no ATLAS (nao saque imediato).
- Indicador: ganha `R$5` por indicado ativado.
- Recorrente: ganha `R$3/mes` por indicado ativo por ate 6 meses.
- Regra de saque: `1 saque por mes`, minimo `R$50`, fechamento no ultimo dia do mes, pagamento no dia 5.

## Por que isso ajuda a crescer e manter assinaturas
- Crescimento: reduz custo de aquisicao com distribuicao organica.
- Retencao do indicador: ele precisa manter base ativa para continuar recebendo recorrencia.
- Retencao do indicado: parte do beneficio pode ser atrelada a permanencia ativa/assinatura.

## Definicoes de elegibilidade
- Indicado validado:
  - Telefone verificado.
  - Nao e autoindicacao.
  - Concluiu onboarding.
- Indicado ativado:
  - Fez ao menos 1 registro financeiro real.
  - Continua ativo por 7-14 dias.
- Indicado ativo mensal:
  - Plano pago ativo no mes (recomendado), ou
  - Regra alternativa free: ao menos X interacoes/transacoes no mes.

## Regras antifraude obrigatorias
- Bloquear autoindicacao (mesmo telefone, mesmo documento/chave Pix, sinais de device/IP).
- Janela de seguranca para liberar bonus (ex.: 14 dias).
- Limite de ganhos por indicador (ex.: teto mensal e teto vitalicio).
- Limite de indicacoes validadas por periodo (ex.: 20/mes no inicio).
- Revisao manual de contas suspeitas.
- Direito de estorno de bonus em caso de fraude/cancelamento.

## Fluxo do usuario no WhatsApp
1. Usuario pede: "quero meu link".
2. Sistema gera `referral_code` unico e responde com link.
3. Novo usuario entra pelo link e conclui onboarding.
4. Sistema registra relacao indicador -> indicado (status `pending_validation`).
5. Ao cumprir ativacao, cria credito de `R$5` para indicador e `R$25` (credito interno) para indicado.
6. Todo fechamento mensal, sistema calcula `R$3` por indicado ativo elegivel.
7. Usuario pede saque; sistema cria solicitacao (se elegivel) para o lote mensal.
8. No dia de pagamento, processa lote e atualiza status.

## Estrutura minima de banco (PostgreSQL)
```sql
-- 1) Codigo de indicacao por usuario
ALTER TABLE users
ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE;

-- 2) Relacao indicador -> indicado
CREATE TABLE IF NOT EXISTS referrals (
  id BIGSERIAL PRIMARY KEY,
  referrer_user_id BIGINT NOT NULL REFERENCES users(id),
  referred_user_id BIGINT NOT NULL REFERENCES users(id),
  referral_code_used TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending_validation', -- pending_validation|activated|rejected|fraud
  activated_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (referred_user_id)
);

-- 3) Ledger imutavel (creditos e debitos)
CREATE TABLE IF NOT EXISTS wallet_ledger (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  event_type TEXT NOT NULL, -- referral_bonus|referral_recurring|withdrawal|reversal|manual_adjustment
  amount_cents BIGINT NOT NULL, -- positivo = credito, negativo = debito
  reference_type TEXT NULL, -- referral|withdrawal_request|admin
  reference_id BIGINT NULL,
  status TEXT NOT NULL DEFAULT 'posted', -- posted|pending|reversed
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_ledger_user_created
ON wallet_ledger (user_id, created_at DESC);

-- 4) Solicitacoes de saque
CREATE TABLE IF NOT EXISTS withdrawal_requests (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  amount_cents BIGINT NOT NULL,
  pix_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|paid|failed|canceled
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  approved_at TIMESTAMPTZ NULL,
  paid_at TIMESTAMPTZ NULL,
  failure_reason TEXT NULL,
  batch_id BIGINT NULL
);

-- 5) Lotes mensais de pagamento
CREATE TABLE IF NOT EXISTS payout_batches (
  id BIGSERIAL PRIMARY KEY,
  period_ym TEXT NOT NULL, -- ex.: 2026-03
  status TEXT NOT NULL DEFAULT 'draft', -- draft|approved|processing|completed|failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ NULL,
  UNIQUE (period_ym)
);
```

## Regras de negocio (server-side)
- Saldo disponivel = soma do ledger `posted` - saques `approved/paid` - valores em disputa.
- Apenas 1 solicitacao de saque por usuario por mes calendario.
- Saque minimo: `R$50`.
- Bonus de indicacao so vira `posted` apos ativacao valida.
- Recorrencia de `R$3` so para indicados ativos no periodo e dentro do limite de meses.
- Estorno gera novo lancamento no ledger (nunca editar lancamento antigo).

## Queries uteis
```sql
-- Saldo atual por usuario
SELECT user_id, COALESCE(SUM(amount_cents), 0) AS balance_cents
FROM wallet_ledger
WHERE status = 'posted'
GROUP BY user_id;

-- Verificar se ja pediu saque no mes
SELECT COUNT(*) > 0 AS already_requested
FROM withdrawal_requests
WHERE user_id = $1
  AND date_trunc('month', requested_at) = date_trunc('month', NOW())
  AND status IN ('pending','approved','paid');
```

## Operacao mensal (manual no inicio)
1. Dia 1: job calcula bonus recorrente elegivel e credita ledger.
2. Dias 1-3: usuarios solicitam saque.
3. Dia 4: voce revisa `pending` (fraude, duplicidade, chave Pix).
4. Dia 5: pagamento manual via Pix (lote).
5. Mesmo dia: marcar `paid` e enviar mensagem automatica de confirmacao.

## Automacao em 3 fases
- Fase 1 (agora): fechamento e pagamento manual.
- Fase 2: geracao automatica de lote + aprovacao manual.
- Fase 3: payout Pix automatico via PSP (Mercado Pago/Asaas/Pagar.me) com webhook de confirmacao.

## Mensagens prontas (WhatsApp)
- Link de indicacao:
  - "Seu link ATLAS: {{link}}. Cada amigo ativo te rende R$5 + R$3/mes por ate 6 meses. Saque mensal a partir de R$50."
- Bonus aprovado:
  - "Indicacao validada. Voce ganhou R$5. Saldo atual: R${{saldo}}."
- Fechamento mensal:
  - "Fechamento concluido. Voce recebeu R${{valor_mes}} de recorrencia. Saldo disponivel: R${{saldo}}."
- Saque pago:
  - "Seu saque de R${{valor}} foi pago via Pix em {{data}}."

## KPIs para validar se esta funcionando
- Convites enviados por usuario ativo.
- Taxa cadastro por convite.
- Taxa ativacao por cadastro.
- Custo de recompensa por usuario ativo.
- Retencao 30/60/90 dias de usuarios indicados.
- Payback (receita liquida - recompensas) por cohort mensal.

## Guardrails financeiros (importante)
- Nao pagar `R$25` em dinheiro; use credito de assinatura/beneficio interno.
- Definir teto mensal por indicador (ex.: R$300) no MVP.
- Revisar unidade economica a cada 30 dias antes de liberar limites maiores.

## Plano de execucao (2 semanas)
1. Semana 1: schema, endpoints basicos, fluxo de link e tracking.
2. Semana 1: regras de ativacao + credito inicial + mensagens.
3. Semana 2: solicitacao de saque, lote mensal e painel admin simples.
4. Semana 2: logs antifraude + relatorios de KPI.

## Decisao recomendada agora
- Lancar com:
  - `R$5` por indicado ativado.
  - `R$3/mes` por 6 meses por indicado ativo.
  - `R$25` em credito interno para convidado.
  - `1 saque/mes`, minimo `R$50`, pagamento manual no dia 5.
- Reavaliar apos 30 dias com dados de ativacao, fraude e retencao.
