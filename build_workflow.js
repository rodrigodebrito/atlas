const fs = require('fs');
const wf = JSON.parse(fs.readFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_workflow_current.json', 'utf8'));

// =============================================
// 1. UPDATE ATLAS Agno API node: continueOnFail: true
// =============================================
const atlasNode = wf.nodes.find(n => n.name === 'ATLAS Agno API');
atlasNode.continueOnFail = true;
console.log('1. Updated ATLAS Agno API continueOnFail:', atlasNode.continueOnFail);

// =============================================
// 2. ADD 'Verificar rate limit' node (Postgres executeQuery)
// =============================================
const verificarRateLimit = {
  id: 'verificar-rate-limit-001',
  name: 'Verificar rate limit',
  type: 'n8n-nodes-base.postgres',
  typeVersion: 2.6,
  position: [-1000, 144],
  continueOnFail: true,
  credentials: {
    postgres: {
      id: 'sWHxhseXu220kAeK',
      name: 'Postgres account 2'
    }
  },
  parameters: {
    operation: 'executeQuery',
    query: "=SELECT COUNT(*) as msg_count FROM public.n8n_historico_mensagens WHERE session_id = '{{ $('Info1').item.json.telefone }}' AND created_at > NOW() - INTERVAL '60 minutes'",
    options: {}
  }
};
wf.nodes.push(verificarRateLimit);
console.log('2. Added Verificar rate limit node');

// =============================================
// 3. ADD 'Rate limit atingido?' (IF node)
// =============================================
const rateLimitIF = {
  id: 'rate-limit-atingido-001',
  name: 'Rate limit atingido?',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [-700, 144],
  parameters: {
    conditions: {
      options: {
        caseSensitive: true,
        leftValue: '',
        typeValidation: 'strict'
      },
      conditions: [
        {
          id: 'cond-rate-limit-001',
          leftValue: '={{ $json.msg_count }}',
          rightValue: 30,
          operator: {
            type: 'number',
            operation: 'gt'
          }
        }
      ],
      combinator: 'and'
    }
  }
};
wf.nodes.push(rateLimitIF);
console.log('3. Added Rate limit atingido? node');

// =============================================
// 4. ADD 'Aviso rate limit' (HTTP Request to Chatwoot)
// =============================================
const avisoRateLimit = {
  id: 'aviso-rate-limit-001',
  name: 'Aviso rate limit',
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-700, 400],
  credentials: {
    chatwootApi: {
      id: 'VIcktgIr9MjDltkK',
      name: 'ChatWoot account'
    }
  },
  parameters: {
    method: 'POST',
    url: "={{ $('Info1').item.json.url_chatwoot }}/api/v1/accounts/{{ $('Info1').item.json.id_conta }}/conversations/{{ $('Info1').item.json.id_conversa }}/messages",
    authentication: 'predefinedCredentialType',
    nodeCredentialType: 'chatwootApi',
    sendBody: true,
    bodyParameters: {
      parameters: [
        {
          name: 'content',
          value: 'Calma ai! Voce esta enviando muitas mensagens. Aguarda alguns minutinhos e tenta de novo.'
        }
      ]
    },
    options: {}
  }
};
wf.nodes.push(avisoRateLimit);
console.log('4. Added Aviso rate limit node');

// =============================================
// 5. ADD 'Resposta valida?' (IF node)
// =============================================
const respostaValidaIF = {
  id: 'resposta-valida-001',
  name: 'Resposta valida?',
  type: 'n8n-nodes-base.if',
  typeVersion: 2.2,
  position: [900, 144],
  parameters: {
    conditions: {
      options: {
        caseSensitive: true,
        leftValue: '',
        typeValidation: 'strict'
      },
      conditions: [
        {
          id: 'cond-resposta-valida-001',
          leftValue: '={{ $json.content }}',
          rightValue: '',
          operator: {
            type: 'string',
            operation: 'notEmpty',
            singleValue: true
          }
        }
      ],
      combinator: 'and'
    }
  }
};
wf.nodes.push(respostaValidaIF);
console.log('5. Added Resposta valida? node');

// =============================================
// 6. ADD 'Aviso instabilidade' (HTTP Request to Chatwoot)
// =============================================
const avisoInstabilidade = {
  id: 'aviso-instabilidade-001',
  name: 'Aviso instabilidade',
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [900, 400],
  credentials: {
    chatwootApi: {
      id: 'VIcktgIr9MjDltkK',
      name: 'ChatWoot account'
    }
  },
  parameters: {
    method: 'POST',
    url: "={{ $('Info1').item.json.url_chatwoot }}/api/v1/accounts/{{ $('Info1').item.json.id_conta }}/conversations/{{ $('Info1').item.json.id_conversa }}/messages",
    authentication: 'predefinedCredentialType',
    nodeCredentialType: 'chatwootApi',
    sendBody: true,
    bodyParameters: {
      parameters: [
        {
          name: 'content',
          value: 'Opa! Tive uma instabilidade aqui. Pode tentar de novo em alguns minutinhos?'
        }
      ]
    },
    options: {}
  }
};
wf.nodes.push(avisoInstabilidade);
console.log('6. Added Aviso instabilidade node');

// =============================================
// 7 & 8. REMOVE OLD CONNECTIONS
// =============================================
// Remove Coletar mensagens1 -> ATLAS Agno API
wf.connections['Coletar mensagens1'].main[0] = wf.connections['Coletar mensagens1'].main[0].filter(
  c => c.node !== 'ATLAS Agno API'
);
console.log('7. Removed Coletar mensagens1 -> ATLAS Agno API');

// Remove ATLAS Agno API -> Quebrar e enviar mensagens1
wf.connections['ATLAS Agno API'].main[0] = wf.connections['ATLAS Agno API'].main[0].filter(
  c => c.node !== 'Quebrar e enviar mensagens1'
);
console.log('8. Removed ATLAS Agno API -> Quebrar e enviar mensagens1');

// =============================================
// 9. ADD CONNECTION: Coletar mensagens1 -> Verificar rate limit
// =============================================
wf.connections['Coletar mensagens1'].main[0].push({
  node: 'Verificar rate limit',
  type: 'main',
  index: 0
});
console.log('9. Added Coletar mensagens1 -> Verificar rate limit');

// =============================================
// 10. ADD CONNECTION: Verificar rate limit -> Rate limit atingido?
// =============================================
wf.connections['Verificar rate limit'] = {
  main: [
    [{ node: 'Rate limit atingido?', type: 'main', index: 0 }]
  ]
};
console.log('10. Added Verificar rate limit -> Rate limit atingido?');

// =============================================
// 11 & 12. Rate limit atingido? TRUE -> Aviso rate limit, FALSE -> ATLAS Agno API
// =============================================
wf.connections['Rate limit atingido?'] = {
  main: [
    // true branch (output 0)
    [{ node: 'Aviso rate limit', type: 'main', index: 0 }],
    // false branch (output 1)
    [{ node: 'ATLAS Agno API', type: 'main', index: 0 }]
  ]
};
console.log('11. Added Rate limit atingido? TRUE -> Aviso rate limit');
console.log('12. Added Rate limit atingido? FALSE -> ATLAS Agno API');

// =============================================
// 13. ADD CONNECTION: Aviso rate limit -> Limpar status atendimento3
// =============================================
wf.connections['Aviso rate limit'] = {
  main: [
    [{ node: 'Limpar status atendimento3', type: 'main', index: 0 }]
  ]
};
console.log('13. Added Aviso rate limit -> Limpar status atendimento3');

// =============================================
// 14. ADD CONNECTION: ATLAS Agno API -> Resposta valida?
// =============================================
wf.connections['ATLAS Agno API'].main[0].push({
  node: 'Resposta valida?',
  type: 'main',
  index: 0
});
console.log('14. Added ATLAS Agno API -> Resposta valida?');

// =============================================
// 15 & 16. Resposta valida? TRUE -> Quebrar e enviar, FALSE -> Aviso instabilidade
// =============================================
wf.connections['Resposta valida?'] = {
  main: [
    // true branch (output 0)
    [{ node: 'Quebrar e enviar mensagens1', type: 'main', index: 0 }],
    // false branch (output 1)
    [{ node: 'Aviso instabilidade', type: 'main', index: 0 }]
  ]
};
console.log('15. Added Resposta valida? TRUE -> Quebrar e enviar mensagens1');
console.log('16. Added Resposta valida? FALSE -> Aviso instabilidade');

// =============================================
// 17. ADD CONNECTION: Aviso instabilidade -> Limpar status atendimento3
// =============================================
wf.connections['Aviso instabilidade'] = {
  main: [
    [{ node: 'Limpar status atendimento3', type: 'main', index: 0 }]
  ]
};
console.log('17. Added Aviso instabilidade -> Limpar status atendimento3');

// =============================================
// SAVE MODIFIED WORKFLOW
// =============================================
// Remove read-only fields not accepted by PUT
const { updatedAt, createdAt, id, versionCounter, triggerCount, shared, tags, activeVersion, ...putBody } = wf;

fs.writeFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_workflow_modified_v2.json', JSON.stringify(putBody, null, 2));
console.log('');
console.log('Saved modified workflow to atlas_workflow_modified_v2.json');

// Verify connections summary
console.log('');
console.log('=== FINAL CONNECTIONS SUMMARY ===');
const relevantConns = ['Coletar mensagens1', 'Verificar rate limit', 'Rate limit atingido?', 'Aviso rate limit', 'ATLAS Agno API', 'Resposta valida?', 'Aviso instabilidade'];
relevantConns.forEach(name => {
  if (putBody.connections[name]) {
    const branches = putBody.connections[name].main.map((arr, i) => ({ branch: i === 0 ? 'true/main' : 'false', targets: (arr||[]).map(c=>c.node) }));
    console.log('[' + name + '] ->', JSON.stringify(branches));
  }
});

// Verify new nodes added
console.log('');
console.log('=== NEW NODES ADDED ===');
const newNodeNames = ['Verificar rate limit', 'Rate limit atingido?', 'Aviso rate limit', 'Resposta valida?', 'Aviso instabilidade'];
newNodeNames.forEach(name => {
  const found = putBody.nodes.find(n => n.name === name);
  console.log(name + ': ' + (found ? 'FOUND at pos=' + JSON.stringify(found.position) : 'NOT FOUND'));
});

// Verify ATLAS Agno API continueOnFail
const atlas = putBody.nodes.find(n => n.name === 'ATLAS Agno API');
console.log('ATLAS Agno API continueOnFail:', atlas.continueOnFail);
