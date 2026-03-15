# Pri Consultora Pessoal

## Objetivo
Transformar a Pri de um modo conversacional guiado por prompt em um sistema de consultoria com:
- memoria confiavel
- continuidade perfeita
- opiniao forte de consultora
- menos assistente, mais especialista pessoal

## Arquitetura alvo

### 1. Estado persistente da consultoria
Cada telefone deve manter um estado estruturado com:
- `mode`
- `consultant_stage`
- `last_open_question`
- `open_question_key`
- `expected_answer_type`
- `case_summary_json`
- `memory_json`
- `expires_at`

### 2. Estagios formais da Pri
- `diagnosis`
- `diagnosis_clarification`
- `income_clarification`
- `debt_mapping`
- `reserve_check`
- `action_plan`
- `follow_up`

O app governa o estagio. O LLM interpreta o texto, mas nao decide sozinho em que fase do trabalho esta.

### 3. Resumo estruturado do caso
Primeira versao do resumo:
- `income_extra_type`
- `income_extra_origin`
- `has_emergency_reserve`
- `debt_outside_cards`
- `card_payment_behavior`
- `main_issue_hypothesis`
- `last_user_signal`
- `notes`

Esse resumo acompanha a conversa e entra no prompt para a Pri responder como consultora.

### 4. Regras de resposta da Pri
Toda resposta da Pri deve:
1. identificar o problema principal
2. explicar por que isso importa
3. dizer o que faria primeiro
4. terminar com uma pergunta util para o proximo passo

## Plano de implementacao

### Fase 1
- adicionar `consultant_stage` e `case_summary_json` ao estado persistente
- introduzir modulo separado com heuristicas de consultoria
- injetar estagio e resumo do caso no contexto do modo mentor
- cobrir com testes automatizados

### Fase 2
- criar transicoes mais deterministicas por estagio
- impedir saltos incoerentes entre diagnostico e plano
- gerar planos de acao por prioridade

### Fase 3
- separar a Pri do monolito principal
- adicionar metricas de sucesso por estagio
- criar score de qualidade das respostas da Pri

## Principio tecnico
Prompt ajuda.
Estado governa.
Teste protege.
