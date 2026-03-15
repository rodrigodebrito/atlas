const fs = require('fs');
const https = require('https');

const wf = JSON.parse(fs.readFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_workflow_fresh.json', 'utf8'));

const API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ';
const WORKFLOW_ID = 'yjYojxfTCjKGjsJ6';

// =============================================
// 1. UPDATE ATLAS Agno API node: continueOnFail: true
// =============================================
const atlasNode = wf.nodes.find(function(n) { return n.name === 'ATLAS Agno API'; });
atlasNode.continueOnFail = true;
console.log('1. Updated ATLAS Agno API continueOnFail: true');

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
        typeValidation: 'strict',
        version: 2
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
    },
    options: {}
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
          value: 'Calma a\u00ed! \uD83D\uDE05 Voc\u00ea est\u00e1 enviando muitas mensagens. Aguarda alguns minutinhos e tenta de novo.'
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
        typeValidation: 'strict',
        version: 2
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
    },
    options: {}
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
          value: 'Opa! Tive uma instabilidade aqui \uD83D\uDE05 Pode tentar de novo em alguns minutinhos?'
        }
      ]
    },
    options: {}
  }
};
wf.nodes.push(avisoInstabilidade);
console.log('6. Added Aviso instabilidade node');

// =============================================
// 7. REMOVE: Coletar mensagens1 -> ATLAS Agno API
// =============================================
wf.connections['Coletar mensagens1'].main[0] = wf.connections['Coletar mensagens1'].main[0].filter(
  function(c) { return c.node !== 'ATLAS Agno API'; }
);
console.log('7. Removed Coletar mensagens1 -> ATLAS Agno API');

// =============================================
// 8. REMOVE: ATLAS Agno API -> Quebrar e enviar mensagens1
// =============================================
wf.connections['ATLAS Agno API'].main[0] = wf.connections['ATLAS Agno API'].main[0].filter(
  function(c) { return c.node !== 'Quebrar e enviar mensagens1'; }
);
console.log('8. Removed ATLAS Agno API -> Quebrar e enviar mensagens1');

// =============================================
// 9. ADD: Coletar mensagens1 -> Verificar rate limit
// =============================================
wf.connections['Coletar mensagens1'].main[0].push({
  node: 'Verificar rate limit',
  type: 'main',
  index: 0
});
console.log('9. Added Coletar mensagens1 -> Verificar rate limit');

// =============================================
// 10. ADD: Verificar rate limit -> Rate limit atingido?
// =============================================
wf.connections['Verificar rate limit'] = {
  main: [
    [{ node: 'Rate limit atingido?', type: 'main', index: 0 }]
  ]
};
console.log('10. Added Verificar rate limit -> Rate limit atingido?');

// =============================================
// 11+12. Rate limit atingido? TRUE/FALSE branches
// =============================================
wf.connections['Rate limit atingido?'] = {
  main: [
    [{ node: 'Aviso rate limit', type: 'main', index: 0 }],
    [{ node: 'ATLAS Agno API', type: 'main', index: 0 }]
  ]
};
console.log('11. Added Rate limit atingido? TRUE -> Aviso rate limit');
console.log('12. Added Rate limit atingido? FALSE -> ATLAS Agno API');

// =============================================
// 13. ADD: Aviso rate limit -> Limpar status atendimento3
// =============================================
wf.connections['Aviso rate limit'] = {
  main: [
    [{ node: 'Limpar status atendimento3', type: 'main', index: 0 }]
  ]
};
console.log('13. Added Aviso rate limit -> Limpar status atendimento3');

// =============================================
// 14. ADD: ATLAS Agno API -> Resposta valida?
// =============================================
wf.connections['ATLAS Agno API'].main[0].push({
  node: 'Resposta valida?',
  type: 'main',
  index: 0
});
console.log('14. Added ATLAS Agno API -> Resposta valida?');

// =============================================
// 15+16. Resposta valida? TRUE/FALSE branches
// =============================================
wf.connections['Resposta valida?'] = {
  main: [
    [{ node: 'Quebrar e enviar mensagens1', type: 'main', index: 0 }],
    [{ node: 'Aviso instabilidade', type: 'main', index: 0 }]
  ]
};
console.log('15. Added Resposta valida? TRUE -> Quebrar e enviar mensagens1');
console.log('16. Added Resposta valida? FALSE -> Aviso instabilidade');

// =============================================
// 17. ADD: Aviso instabilidade -> Limpar status atendimento3
// =============================================
wf.connections['Aviso instabilidade'] = {
  main: [
    [{ node: 'Limpar status atendimento3', type: 'main', index: 0 }]
  ]
};
console.log('17. Added Aviso instabilidade -> Limpar status atendimento3');

// Build PUT body with only allowed fields
const putBody = {
  name: wf.name,
  nodes: wf.nodes,
  connections: wf.connections,
  settings: wf.settings,
  staticData: wf.staticData,
  meta: wf.meta,
  pinData: wf.pinData
};

const bodyStr = JSON.stringify(putBody);
fs.writeFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_put_body_final.json', bodyStr);
console.log('');
console.log('Body size:', bodyStr.length, 'chars');
console.log('Saved to atlas_put_body_final.json');

// Now do the PUT request
const url = new URL('https://n8n.rodrigobrito.cloud/api/v1/workflows/' + WORKFLOW_ID);
const options = {
  hostname: url.hostname,
  path: url.pathname,
  method: 'PUT',
  headers: {
    'X-N8N-API-KEY': API_KEY,
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(bodyStr)
  }
};

console.log('');
console.log('Sending PUT request...');

const req = https.request(options, function(res) {
  console.log('Status code:', res.statusCode);
  const chunks = [];
  res.on('data', function(d) { chunks.push(d); });
  res.on('end', function() {
    const responseBody = chunks.join('');
    fs.writeFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_put_response_final.json', responseBody);

    let parsed;
    try {
      parsed = JSON.parse(responseBody);
    } catch(e) {
      console.log('Could not parse response:', responseBody.substring(0, 500));
      return;
    }

    if (res.statusCode === 200 && parsed.id) {
      console.log('');
      console.log('=== SUCCESS ===');
      console.log('Workflow ID:', parsed.id);
      console.log('Name:', parsed.name);
      console.log('Total nodes:', parsed.nodes.length);

      // Verify new nodes
      const newNodes = ['Verificar rate limit', 'Rate limit atingido?', 'Aviso rate limit', 'Resposta valida?', 'Aviso instabilidade'];
      console.log('');
      console.log('--- New nodes ---');
      newNodes.forEach(function(name) {
        const n = parsed.nodes.find(function(x) { return x.name === name; });
        console.log(name + ': ' + (n ? 'OK pos=' + JSON.stringify(n.position) : 'MISSING!'));
      });

      // Verify ATLAS
      const atlas = parsed.nodes.find(function(n) { return n.name === 'ATLAS Agno API'; });
      console.log('ATLAS Agno API continueOnFail:', atlas ? atlas.continueOnFail : 'node not found');

      // Verify connections
      const c = parsed.connections;
      console.log('');
      console.log('--- Connections ---');
      const flow = ['Coletar mensagens1', 'Verificar rate limit', 'Rate limit atingido?', 'Aviso rate limit', 'ATLAS Agno API', 'Resposta valida?', 'Aviso instabilidade'];
      flow.forEach(function(name) {
        if (c[name]) {
          const m = c[name].main || [];
          const branches = m.map(function(arr, i) {
            return 'out[' + i + ']->' + (arr || []).map(function(x) { return x.node; }).join('+');
          }).join(' | ');
          console.log('[' + name + '] ' + branches);
        } else {
          console.log('[' + name + '] NO CONNECTIONS');
        }
      });
    } else {
      console.log('Error response:', JSON.stringify(parsed, null, 2).substring(0, 2000));
    }
  });
});

req.on('error', function(e) {
  console.error('Request error:', e);
});

req.write(bodyStr);
req.end();
