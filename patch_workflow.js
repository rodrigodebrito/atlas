const fs = require('fs');

const wf = JSON.parse(fs.readFileSync('c:/Users/Rodrigo Brito/Desktop/Atlas/atlas_workflow_current.json', 'utf8'));

// --- 1. Add attachment_url and attachment_file_type to Info1 ---
const info1 = wf.nodes.find(n => n.name === 'Info1');
info1.parameters.assignments.assignments.push(
  {
    id: 'a1b2c3d4-0001-0001-0001-000000000001',
    name: 'attachment_url',
    value: "={{ $json.body.attachments?.[0]?.data_url || '' }}",
    type: 'string'
  },
  {
    id: 'a1b2c3d4-0002-0002-0002-000000000002',
    name: 'attachment_file_type',
    value: "={{ $json.body.attachments?.[0]?.file_type || '' }}",
    type: 'string'
  }
);

// --- 2. Add 'Importar' case to Reset ou teste1 (insert at index 2, before fallback) ---
const reset = wf.nodes.find(n => n.name === 'Reset ou teste1');
reset.parameters.rules.values.splice(2, 0, {
  conditions: {
    options: { caseSensitive: false, leftValue: '', typeValidation: 'strict', version: 2 },
    conditions: [
      {
        id: 'imp-cond-0001-0001-0001-000000000001',
        leftValue: "={{ $json.mensagem.toLowerCase().trim() }}",
        rightValue: 'importar',
        operator: { type: 'string', operation: 'equals' }
      }
    ],
    combinator: 'and'
  },
  renameOutput: true,
  outputKey: 'Importar'
});

// --- 3. Update connections for Reset ou teste1 ---
// Before: output 0=Reset→Limpar, 1=Teste→Colocar, 2=Mensagem normal (fallback)→Processar
// After:  output 0=Reset→Limpar, 1=Teste→Colocar, 2=Importar→Buscar, 3=Mensagem normal (fallback)→Processar
const resetConns = wf.connections['Reset ou teste1'].main;
const processarConn = resetConns[2]; // save old output 2 (Processar mensagem?1)
resetConns[2] = [{ node: 'Buscar import pendente1', type: 'main', index: 0 }];
resetConns[3] = processarConn; // move to output 3

// --- 4. Change Tipo de mensagem1 output 1 (Arquivo) → Tipo de arquivo1 ---
const tipoMsgConns = wf.connections['Tipo de mensagem1'].main;
tipoMsgConns[1] = [{ node: 'Tipo de arquivo1', type: 'main', index: 0 }];

// --- 5. Add new nodes ---
const ATLAS_API = 'https://atlas-m3wb.onrender.com';
const CHATWOOT_CRED = { chatwootApi: { id: 'VIcktgIr9MjDltkK', name: 'ChatWoot account' } };

wf.nodes.push(
  // Tipo de arquivo1 — sub-switch: image/document → Fatura, outros → Enfileirar
  {
    parameters: {
      rules: {
        values: [
          {
            conditions: {
              options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
              conditions: [
                {
                  id: 'arq-cond-0001-0001-0001-000000000001',
                  leftValue: "={{ $('Info1').item.json.attachment_file_type }}",
                  rightValue: 'image',
                  operator: { type: 'string', operation: 'equals' }
                },
                {
                  id: 'arq-cond-0002-0002-0002-000000000002',
                  leftValue: "={{ $('Info1').item.json.attachment_file_type }}",
                  rightValue: 'document',
                  operator: { type: 'string', operation: 'equals' }
                },
                {
                  id: 'arq-cond-0003-0003-0003-000000000003',
                  leftValue: "={{ $('Info1').item.json.attachment_url }}",
                  rightValue: '.pdf',
                  operator: { type: 'string', operation: 'endsWith' }
                }
              ],
              combinator: 'or'
            },
            renameOutput: true,
            outputKey: 'Fatura'
          }
        ]
      },
      options: { fallbackOutput: 'extra', renameFallbackOutput: 'Outro arquivo' }
    },
    type: 'n8n-nodes-base.switch',
    typeVersion: 3.2,
    position: [-3150, 450],
    id: 'f1a2b3c4-0001-0001-0001-fatura000001',
    name: 'Tipo de arquivo1'
  },

  // Analisar Fatura1 — POST /v1/parse-statement
  {
    parameters: {
      method: 'POST',
      url: ATLAS_API + '/v1/parse-statement',
      sendBody: true,
      contentType: 'multipart-form-data',
      bodyParameters: {
        parameters: [
          { name: 'user_phone', value: "={{ $('Info1').item.json.telefone }}" },
          { name: 'image_url', value: "={{ $('Info1').item.json.attachment_url }}" },
          { name: 'card_name', value: "={{ $('Info1').item.json.mensagem }}" }
        ]
      },
      options: {}
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-2820, 560],
    id: 'f1a2b3c4-0002-0002-0002-fatura000002',
    name: 'Analisar Fatura1'
  },

  // Enviar análise fatura1 — POST Chatwoot message
  {
    parameters: {
      method: 'POST',
      url: "={{ $('Info1').item.json.url_chatwoot }}/api/v1/accounts/{{ $('Info1').item.json.id_conta }}/conversations/{{ $('Info1').item.json.id_conversa }}/messages",
      authentication: 'predefinedCredentialType',
      nodeCredentialType: 'chatwootApi',
      sendBody: true,
      bodyParameters: {
        parameters: [
          { name: 'content', value: '={{ $json.message }}' }
        ]
      },
      options: {}
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-2520, 560],
    id: 'f1a2b3c4-0003-0003-0003-fatura000003',
    name: 'Enviar análise fatura1',
    credentials: CHATWOOT_CRED
  },

  // Buscar import pendente1 — GET /v1/pending-import
  {
    parameters: {
      method: 'GET',
      url: "=" + ATLAS_API + "/v1/pending-import?user_phone={{ $('Info1').item.json.telefone }}",
      options: {}
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-3550, -150],
    id: 'f1a2b3c4-0004-0004-0004-import00004',
    name: 'Buscar import pendente1'
  },

  // Confirmar importação1 — POST /v1/import-statement
  {
    parameters: {
      method: 'POST',
      url: ATLAS_API + '/v1/import-statement',
      sendBody: true,
      contentType: 'multipart-form-data',
      bodyParameters: {
        parameters: [
          { name: 'user_phone', value: "={{ $('Info1').item.json.telefone }}" },
          { name: 'import_id', value: '={{ $json.import_id }}' }
        ]
      },
      options: {}
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-3250, -150],
    id: 'f1a2b3c4-0005-0005-0005-import00005',
    name: 'Confirmar importação1'
  },

  // Enviar confirmação importação1 — POST Chatwoot message
  {
    parameters: {
      method: 'POST',
      url: "={{ $('Info1').item.json.url_chatwoot }}/api/v1/accounts/{{ $('Info1').item.json.id_conta }}/conversations/{{ $('Info1').item.json.id_conversa }}/messages",
      authentication: 'predefinedCredentialType',
      nodeCredentialType: 'chatwootApi',
      sendBody: true,
      bodyParameters: {
        parameters: [
          { name: 'content', value: '={{ $json.message }}' }
        ]
      },
      options: {}
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-2950, -150],
    id: 'f1a2b3c4-0006-0006-0006-import00006',
    name: 'Enviar confirmação importação1',
    credentials: CHATWOOT_CRED
  }
);

// --- 6. Add new connections ---
wf.connections['Tipo de arquivo1'] = {
  main: [
    [{ node: 'Analisar Fatura1', type: 'main', index: 0 }],          // Fatura (output 0)
    [{ node: 'Enfileirar mensagem.1', type: 'main', index: 0 }]       // Outro arquivo (fallback/output 1)
  ]
};

wf.connections['Analisar Fatura1'] = {
  main: [[{ node: 'Enviar análise fatura1', type: 'main', index: 0 }]]
};

wf.connections['Buscar import pendente1'] = {
  main: [[{ node: 'Confirmar importação1', type: 'main', index: 0 }]]
};

wf.connections['Confirmar importação1'] = {
  main: [[{ node: 'Enviar confirmação importação1', type: 'main', index: 0 }]]
};

// --- 7. Save ---
fs.writeFileSync(
  'c:/Users/Rodrigo Brito/Desktop/Atlas/atlas_workflow_current.json',
  JSON.stringify(wf, null, 2),
  'utf8'
);

console.log('Done!');
console.log('New nodes:', ['Tipo de arquivo1', 'Analisar Fatura1', 'Enviar análise fatura1', 'Buscar import pendente1', 'Confirmar importação1', 'Enviar confirmação importação1'].map(n => wf.nodes.find(x => x.name === n) ? '✓ ' + n : '✗ MISSING ' + n).join('\n'));
console.log('\nReset ou teste1 connections:');
wf.connections['Reset ou teste1'].main.forEach((c, i) => console.log('  output', i, '->', c[0]?.node));
console.log('\nTipo de mensagem1 connections:');
wf.connections['Tipo de mensagem1'].main.forEach((c, i) => console.log('  output', i, '->', c[0]?.node));
console.log('\nTipo de arquivo1 connections:');
wf.connections['Tipo de arquivo1'].main.forEach((c, i) => console.log('  output', i, '->', c[0]?.node));
console.log('\nReset ou teste1 rules:', reset.parameters.rules.values.map(v => v.outputKey).join(', '));
