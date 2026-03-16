# Proximos Passos do ATLAS

## Contexto atual

O ATLAS ja saiu do estagio de "bot financeiro util" e entrou numa fase de produto:

- Pri com estado persistente por telefone
- memoria curta da conversa
- resumo estruturado do caso
- estagios formais de consultoria
- frames de abertura por contexto (mes, dia, ontem, semana, semana passada, ultimos 7 dias, divida, cartao, reserva, investir vs quitar divida)
- respostas curtas de continuidade preservadas dentro do fluxo da Pri
- media mensal so com meses completos fechados
- comando `painel` priorizado mesmo com a Pri ativa
- suite automatizada de regressao da Pri

Estado atual da suite da Pri:
- `12 passed`

---

## O que ja foi concluido recentemente

### Pri consultora pessoal
- estado persistente em banco para a mentoria
- chave formal da pergunta aberta
- tipo esperado da resposta
- memoria curta por telefone
- estagios formais de consultoria
- resumo estruturado do caso
- abertura estruturada da Pri por contexto
- tom mais direto e mais consultora

### Continuidade de conversa
- respostas como `foi por plantao`, `foi pontual`, `tenho reserva sim` e `quero sim` continuam o fluxo
- convites da Pri sem `?` tambem geram pergunta aberta valida
- comando `painel` nao e mais sequestrado pelo modo mentor

### Inteligencia de historico
- media mensal so aparece quando existe pelo menos 1 mes completo fechado
- se nao houver historico suficiente, a Pri explica isso de forma natural

### Qualidade
- testes automatizados dos fluxos da Pri
- testes de regressao para continuidade, frames, historico insuficiente e atalho de painel

---

## Prioridades imediatas

### P0. Continuidade da Pri nos segundos turnos
Impacto: muito alto

A abertura da Pri esta mais forte, mas os turnos seguintes ainda podem ficar mais neutros do que o desejado.

Objetivo:
- fazer a Pri manter o mesmo nivel de consultoria depois da primeira resposta
- garantir que cada resposta traga:
  - problema principal
  - prioridade
  - primeira acao
  - proxima pergunta

Implementacoes sugeridas:
- planner de resposta por estagio
- regras de saida por contexto
- mais testes de follow-up

### P1. Maquina de estados mais rigida
Impacto: muito alto

Hoje a Pri ja tem estagios, mas ainda ha espaco para mais determinismo.

Objetivo:
- reduzir ainda mais situacoes em que o LLM "improvisa" a fase da conversa

Implementacoes sugeridas:
- transicoes explicitas entre `diagnosis`, `diagnosis_clarification`, `income_clarification`, `debt_mapping`, `reserve_check`, `action_plan` e `follow_up`
- impedir saltos incoerentes
- guardar a ultima proxima-acao no estado

### P2. Observabilidade da Pri
Impacto: alto

Hoje ja existe teste. O proximo ganho e entender melhor o comportamento real em producao.

Implementacoes sugeridas:
- log estruturado com:
  - frame usado
  - stage atual
  - open_question_key
  - se houve bypass por atalho explicito
  - se a resposta caiu em fallback
- endpoint/admin view simples para investigar rotas mais frequentes

### P3. Refatoracao do monolito
Impacto: alto

`agno_api/agent.py` continua sendo o principal gargalo de manutencao.

Objetivo:
- extrair responsabilidades para modulos claros

Ordem sugerida:
- `mentor_router.py`
- `mentor_state.py`
- `query_shortcuts.py`
- `panel_shortcuts.py`
- `financial_snapshots.py`

### P4. Seguranca e confianca
Impacto: critico

Antes de escalar usuarios, o produto precisa endurecer pontos operacionais.

Itens:
- revisar rotas de debug
- endurecer auth do painel
- revisar trilha de auditoria
- deixar explicita a origem dos numeros em respostas sensiveis

### P5. Onboarding e wow moment
Impacto: alto

A Pri precisa encantar no primeiro minuto.

Objetivo:
- primeiro insight memoravel em ate 60 segundos
- menos cadastro seco, mais diagnostico imediato

### P6. Produto desejavel
Impacto: alto

Depois da confiabilidade, o maior ganho sera emocional.

Itens:
- painel mais premium
- loops semanais de uso
- recap automatico com linguagem forte
- identidade verbal mais marcante

---

## Ordem recomendada

1. Pri nos segundos turnos com o mesmo nivel da abertura
2. Maquina de estados mais rigida
3. Observabilidade da Pri
4. Refatoracao do monolito
5. Seguranca e confianca
6. Onboarding forte
7. Produto mais desejavel

---

## Arquivos centrais dessa fase

- `agno_api/agent.py`
- `agno_api/mentor_consultant.py`
- `tests/test_pri_mentor_state.py`
- `PRI_CONSULTORA_ARQUITETURA.md`

---

## Principio dessa etapa

Prompt ajuda.  
Estado governa.  
Teste protege.  
Produto conquista.
