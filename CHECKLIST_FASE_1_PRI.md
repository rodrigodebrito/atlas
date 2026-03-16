# Checklist Fase 1 - Pri como interface segura

## Objetivo

Fechar a primeira fase da nova arquitetura:

- Pri como interface prioritaria
- consultoria em modo read-only por padrao
- conversa nao executa acao automaticamente
- Atlas deixa de interferir no fluxo da Pri

---

## O que esta implementado

- [x] Mensagem que comeca com `pri` ou `priscila` entra no dominio da Pri
- [x] `painel` continua prioritario mesmo com a Pri ativa
- [x] Onboarding do Atlas nao sequestra mensagens explicitamente enderecadas a Pri
- [x] Confirmacoes pendentes antigas nao sequestram respostas durante a consultoria
- [x] Consultoria da Pri fica read-only por padrao
- [x] Rotas legadas de escrita (`save_transaction`, `update_transaction`, `update_merchant_category`, etc.) entram no bloqueio arquitetural
- [x] Resposta contextual com valor nao vira lancamento automatico
- [x] Resposta contextual sobre categoria nao vira recategorizacao automatica
- [x] Regras centralizadas em `agno_api/pri_controller.py`
- [x] Testes automatizados cobrindo a Fase 1

Estado atual da suite:
- `23 passed`

---

## Como validar manualmente

### 1. Contexto com valor nao vira lancamento

Fluxo:
1. `pri faz uma analise do meu mes`
2. esperar a Pri perguntar algo
3. responder: `esses 2.000 e uma ajuda pra pagar o aluguel que minha irma me passou`

Esperado:
- continua a conversa com a Pri
- nao registra receita automaticamente
- nao aparece card de lancamento

Status:
- [ ] Validado manualmente

### 2. Contexto sobre categoria nao vira recategorizacao automatica

Fluxo:
1. `pri essa categoria outros e uma fatura da caixa de cartao que eu paguei`

Esperado:
- continua no papo da Pri
- nao aparece confirmacao operacional
- nao altera categoria automaticamente

Status:
- [ ] Validado manualmente

### 3. Pri nao cai no onboarding Atlas

Fluxo:
1. `pri me ajuda`

Esperado:
- resposta da Pri
- nao aparece `Sou o ATLAS`

Status:
- [ ] Validado manualmente

### 4. Confirmacao antiga nao sequestra a conversa

Fluxo:
1. entrar na Pri
2. responder `sim`, `nao`, `quero sim` em contexto consultivo

Esperado:
- continua a mentoria
- nao confirma nenhuma acao antiga

Status:
- [ ] Validado manualmente

### 5. Painel continua funcionando

Fluxo:
1. com a Pri ativa, enviar `painel`

Esperado:
- abre/envia o painel
- nao volta para a mentoria

Status:
- [ ] Validado manualmente

---

## Criterio de aceite da Fase 1

A Fase 1 so sera considerada concluida quando:

- [x] A arquitetura read-only da Pri estiver implementada
- [x] As rotas perigosas estiverem protegidas por teste
- [ ] Os 5 fluxos manuais acima estiverem validados no WhatsApp

---

## Proximo passo depois da Fase 1

Fase 2:
- criar um controller unico da Pri
- tirar mais decisao de roteamento de dentro de `agent.py`
- separar de vez:
  - conversa
  - acao
  - atalhos
