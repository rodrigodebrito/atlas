# Checklist de Execução 1 a 1 (anti-retrabalho)

Atualizado em: 2026-03-18

## Legenda
- [x] Concluído
- [~] Parcial (funciona, mas ainda precisa ajuste fino)
- [ ] Pendente

---

## Bloco A — Base de confiabilidade

1. [x] Pri como interface principal com estado de conversa
- Evidência: `agno_api/agent.py` (query state + roteador contextual)
- Commit: `1d4fe3a`

2. [x] Intent de receita vs despesa (evitar "Recebi Uber" virar gasto)
- Evidência: priorização de intenção de entrada
- Commit: `a845c72`

3. [x] Classificação "Mercado Livre" como e-commerce (não mercado físico)
- Evidência: inferência de merchant_type com prioridade para e-commerce
- Commit: `a34fb48`

4. [x] Auto-aprendizado merchant→categoria/cartão
- Evidência: tabelas `merchant_category_rules`, `merchant_card_rules`
- Arquivo: `agno_api/agent.py`

5. [x] Dry-run/apply de recategorização histórica
- Evidência: fluxo de recategorização em lote
- Commit: `71a3457`

---

## Bloco B — Consultas por gasto (merchant/categoria/período)

6. [x] Consulta por tipo de merchant com período (mês/semana/7d/hoje/ontem)
- Commit: `d94bbce`

7. [x] Priorização de intenção por tipo de merchant no roteamento
- Commit: `e400194`

8. [x] Comparação histórica segura (sem quebrar em base curta)
- Commit: `86c33cd`

9. [x] Saída premium para consultas de merchant/tipo
- Commit: `9460c31`

10. [~] Agrupamento de variações de nome em TODAS as consultas
- Já feito em parte:
  - Commit `70ee9a7` (type spend)
  - Commit `b1d1b1a` (category breakdown)
- Ponto em aberto:
  - consolidar exibição final para evitar lista com variações residuais em alguns cenários

11. [~] "Detalhar mês" realmente diferente de "Resumo do mês"
- Estado: funcional em partes, ainda há relatos de retorno igual ao resumo em alguns fluxos
- Pendente validar e corrigir roteamento final

---

## Bloco C — Qualidade de saída e UX de WhatsApp

12. [x] Confirmação de lançamento mais limpa (sem fechamento pesado a cada item)
- Estado: já melhorou, cards curtos para lançamentos simples

13. [~] Formatação premium consistente em todos os caminhos
- Estado: melhorou bastante, mas ainda há variação de estilo entre rotas

14. [ ] Paginação/segmentação sólida para mensagens longas (evitar truncamento no WhatsApp)
- Pendente hardening em todos os relatórios longos

15. [ ] Insight final inteligente e curto em todos os relatórios
- Pendente padronizar pós-processamento

---

## Bloco D — Categorias (taxonomia)

16. [x] Categoria "Cuidados Pessoais" disponível
- Evidência: mapeamentos e ícone no código

17. [x] Categoria "Pagamento Fatura"/"Pagamento Conta" separada de gasto de consumo
- Evidência: exclusão dos totais de consumo e lógica específica

18. [~] Taxonomia fina para casos ambíguos (ex.: e-commerce vs mercado; serviços pessoais)
- Estado: base pronta + precisa ajustes de regras por frase/contexto real

---

## Bloco E — Próximo passo (executar 1 a 1)

### Passo 1 (próxima execução)
[ ] Corrigir definitivamente o roteamento de **"detalhar mês"** para nunca cair no mesmo caminho de resumo.

Critério de aceite:
- `resumo do mês` => KPIs + top categorias + top lançamentos (compacto)
- `detalhar mês` => listagem completa segmentada (sem truncar e sem voltar no resumo)
- Teste manual com massa real + teste automatizado cobrindo regressão

### Passo 2
[ ] Consolidar agrupamento de variação de merchant na exibição final (sem duplicatas semânticas).

### Passo 3
[ ] Padronizar visual/saída premium única em todos os caminhos de relatório.

---

## Regra de execução
- Sempre executar exatamente 1 passo por vez.
- Só avançar após: código + teste + validação manual do passo atual.
