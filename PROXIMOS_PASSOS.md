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
- controller arquitetural da Pri para consultoria read-only
- onboarding Atlas ignorado quando a mensagem e explicitamente da Pri
- confirmacoes pendentes antigas bloqueadas durante consultoria
- rotas legadas de escrita bloqueadas por padrao durante a Pri

Estado atual da suite da Pri:
- `23 passed`

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
- testes arquiteturais da Fase 1 para impedir escrita automatica em consultoria

---

## Prioridades imediatas

### P0. Fechar validacao manual da Fase 1
Impacto: critico

Arquitetura ja implementada:
- Pri explicita com prioridade
- consultoria read-only por padrao
- conversa nao executa acao automaticamente

O que falta:
- validar os cenarios reais no WhatsApp usando `CHECKLIST_FASE_1_PRI.md`
- marcar a Fase 1 como concluida formalmente

### P1. Continuidade da Pri nos segundos turnos
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

### P2. Maquina de estados mais rigida
Impacto: muito alto

Hoje a Pri ja tem estagios, mas ainda ha espaco para mais determinismo.

Objetivo:
- reduzir ainda mais situacoes em que o LLM "improvisa" a fase da conversa

Implementacoes sugeridas:
- transicoes explicitas entre `diagnosis`, `diagnosis_clarification`, `income_clarification`, `debt_mapping`, `reserve_check`, `action_plan` e `follow_up`
- impedir saltos incoerentes
- guardar a ultima proxima-acao no estado

### P3. Observabilidade da Pri
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

### P4. Refatoracao do monolito
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

### P5. Seguranca e confianca
Impacto: critico

Antes de escalar usuarios, o produto precisa endurecer pontos operacionais.

Itens:
- revisar rotas de debug
- endurecer auth do painel
- revisar trilha de auditoria
- deixar explicita a origem dos numeros em respostas sensiveis

### P6. Onboarding e wow moment
Impacto: alto

A Pri precisa encantar no primeiro minuto.

Objetivo:
- primeiro insight memoravel em ate 60 segundos
- menos cadastro seco, mais diagnostico imediato

### P7. Produto desejavel
Impacto: alto

Depois da confiabilidade, o maior ganho sera emocional.

Itens:
- painel mais premium
- loops semanais de uso
- recap automatico com linguagem forte
- identidade verbal mais marcante

---

## Ordem recomendada

1. Fechar validacao manual da Fase 1
2. Pri nos segundos turnos com o mesmo nivel da abertura
3. Maquina de estados mais rigida
4. Observabilidade da Pri
5. Refatoracao do monolito
6. Seguranca e confianca
7. Onboarding forte
8. Produto mais desejavel

---

## Arquivos centrais dessa fase

- `agno_api/agent.py`
- `agno_api/mentor_consultant.py`
- `agno_api/pri_controller.py`
- `tests/test_pri_mentor_state.py`
- `PRI_CONSULTORA_ARQUITETURA.md`
- `CHECKLIST_FASE_1_PRI.md`

---

## Principio dessa etapa

Prompt ajuda.  
Estado governa.  
Teste protege.  
Produto conquista.
