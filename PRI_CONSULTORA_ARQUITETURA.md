# Pri Consultora Pessoal

## Objetivo

Transformar a Pri de um modo conversacional guiado principalmente por prompt em um sistema de consultoria com:

- memoria confiavel
- continuidade forte
- opiniao de consultora
- menos "assistente", mais "especialista pessoal"

---

## O que ja foi implementado

### 1. Estado persistente da consultoria
Cada telefone agora pode manter um estado estruturado com:

- `mode`
- `consultant_stage`
- `last_open_question`
- `open_question_key`
- `expected_answer_type`
- `case_summary_json`
- `memory_json`
- `expires_at`

### 2. Estagios formais da Pri
Estagios ativos hoje:

- `diagnosis`
- `diagnosis_clarification`
- `income_clarification`
- `debt_mapping`
- `reserve_check`
- `action_plan`
- `follow_up`

### 3. Resumo estruturado do caso
Campos principais hoje:

- `income_extra_type`
- `income_extra_origin`
- `has_emergency_reserve`
- `debt_outside_cards`
- `card_payment_behavior`
- `main_issue_hypothesis`
- `last_user_signal`
- `notes`

### 4. Frames estruturados de abertura
A primeira resposta da Pri agora pode sair por molduras especificas para:

- analise do mes
- analise do dia
- analise de ontem
- analise da semana
- analise da semana passada
- ultimos 7 dias
- divida cara / cheque especial
- cartao
- reserva
- investir vs quitar divida

### 5. Continuidade protegida
Ja cobre:

- respostas curtas como `foi por plantao`, `foi pontual`, `tenho reserva sim`, `quero sim`
- convites da Pri sem `?` que ainda assim abrem follow-up valido
- comando `painel` priorizado fora da Pri mesmo com sessao mentor ativa

### 6. Historico financeiro mais honesto

- media mensal so usa meses completos fechados
- se ainda nao houver historico suficiente, a Pri pode explicar isso em linguagem natural

### 7. Testes automatizados
Existe suite de regressao dedicada em:

- `tests/test_pri_mentor_state.py`

Estado atual:
- `23 passed`

### 8. Controller arquitetural da Pri
Agora existe uma camada dedicada em:

- `agno_api/pri_controller.py`

Essa camada centraliza:

- deteccao de mensagens explicitamente enderecadas a Pri
- deteccao de comandos explicitos de escrita
- classificacao de rotas de escrita
- regra arquitetural de consultoria read-only por padrao
- bloqueio de confirmacoes pendentes antigas durante a consultoria

### 9. Fase 1 implementada
A primeira fase da nova arquitetura ja foi implementada:

- Pri explicita tem prioridade
- onboarding Atlas nao sequestra mensagens da Pri
- consultoria da Pri nao escreve no banco por padrao
- respostas contextuais com valor nao viram lancamento automatico
- respostas contextuais sobre categoria nao viram recategorizacao automatica
- comandos como `painel` continuam prioritarios

---

## O que ainda falta

### Fase 1. Validacao manual final
A Fase 1 ja esta implementada tecnicamente.

O que falta agora:
- validar no WhatsApp os cenarios do arquivo `CHECKLIST_FASE_1_PRI.md`
- marcar a fase como encerrada formalmente

### Fase 2. Pri forte nos segundos turnos
A abertura melhorou bastante, mas os turnos seguintes ainda podem perder intensidade.

Meta:
- todo turno da Pri manter:
  - tese principal
  - prioridade
  - primeira acao
  - proxima pergunta

### Fase 3. Planner por estagio
Hoje a Pri ja conhece o estagio. O proximo salto e usar um planner explicito por fase.

Exemplo:
- `diagnosis` -> apontar o problema
- `diagnosis_clarification` -> reduzir ambiguidade
- `debt_mapping` -> descobrir o peso das dividas
- `reserve_check` -> medir folego
- `action_plan` -> gerar passos
- `follow_up` -> cobrar execucao

### Fase 4. Mais determinismo
O LLM ainda interpreta demais em alguns turnos.

Meta:
- app governa ainda mais a fase da conversa
- reduzir improviso em transicoes

### Fase 5. Observabilidade
Precisamos enxergar melhor o comportamento da Pri em producao.

Itens:
- log do frame usado
- log do stage
- log da pergunta aberta
- log de fallback

### Fase 6. Extracao do monolito
Parte da logica da Pri ainda esta acoplada ao monolito principal.

Meta:
- modularizar sem perder comportamento

---

## Arquitetura alvo

### Camada 1. Estado
O app guarda o estado vivo da consultoria.

### Camada 2. Frames
A aplicacao escolhe a moldura de resposta inicial por contexto.

### Camada 3. Planner
A Pri decide como conduzir o proximo passo com base no stage atual.

### Camada 4. LLM
O modelo interpreta texto, escreve bem e mantem o tom.

### Camada 5. Testes
Os testes protegem os fluxos criticos e evitam regressao.

---

## Principio tecnico

Prompt ajuda.  
Estado governa.  
Planner direciona.  
Teste protege.
