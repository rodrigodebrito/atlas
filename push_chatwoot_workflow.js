const https = require('https');

const API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ';
const WORKFLOW_ID = 'ZksJVEHbOQE7hLan';

// The 5 unchanged nodes
const nodes = [
  {
    id: 'node-schedule',
    name: 'Agendar Diário 12h UTC',
    type: 'n8n-nodes-base.scheduleTrigger',
    typeVersion: 1.1,
    position: [240, 300],
    parameters: {
      rule: {
        interval: [
          {
            field: 'cronExpression',
            expression: '0 12 * * *'
          }
        ]
      }
    }
  },
  {
    id: 'node-get-reminders',
    name: 'GET Lembretes do Dia',
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [460, 300],
    parameters: {
      method: 'GET',
      url: '={{ $env.AGNO_API_URL }}/v1/reminders/daily',
      options: {}
    }
  },
  {
    id: 'node-if-has-reminders',
    name: 'Tem Lembretes?',
    type: 'n8n-nodes-base.if',
    typeVersion: 2,
    position: [680, 300],
    parameters: {
      conditions: {
        options: {
          caseSensitive: true,
          leftValue: '',
          typeValidation: 'strict'
        },
        conditions: [
          {
            id: 'cond-count',
            leftValue: '={{ $json.count }}',
            rightValue: 0,
            operator: {
              type: 'number',
              operation: 'gt'
            }
          }
        ],
        combinator: 'and'
      }
    }
  },
  {
    id: 'node-no-op',
    name: 'Sem Lembretes (Parar)',
    type: 'n8n-nodes-base.noOp',
    typeVersion: 1,
    position: [900, 460],
    parameters: {}
  },
  {
    id: 'node-split-reminders',
    name: 'Dividir Lembretes',
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position: [900, 300],
    parameters: {
      mode: 'runOnceForAllItems',
      jsCode: 'return $input.first().json.reminders.map(r => ({ json: r }));'
    }
  },
  // ---- NEW NODE 5a: Buscar Contato Chatwoot ----
  {
    id: 'node-buscar-contato-chatwoot',
    name: 'Buscar Contato Chatwoot',
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [1120, 300],
    parameters: {
      method: 'GET',
      url: '={{ $env.CHATWOOT_URL }}/api/v1/accounts/{{ $env.CHATWOOT_ACCOUNT_ID }}/contacts/search',
      sendQuery: true,
      queryParameters: {
        parameters: [
          {
            name: 'q',
            value: '={{ $json.phone }}'
          }
        ]
      },
      sendHeaders: true,
      headerParameters: {
        parameters: [
          {
            name: 'api_access_token',
            value: '={{ $env.CHATWOOT_API_TOKEN }}'
          }
        ]
      },
      options: {}
    }
  },
  // ---- NEW NODE 5b: Pegar Conversa ----
  {
    id: 'node-pegar-conversa',
    name: 'Pegar Conversa',
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position: [1340, 300],
    parameters: {
      mode: 'runOnceForEachItem',
      jsCode: `const contacts = $input.item.json.payload;
if (!contacts || contacts.length === 0) {
  return []; // skip se contato não encontrado
}
const contact = contacts[0];
const conversations = contact.conversations || [];
const activeConv = conversations.find(c => c.status === 'open') || conversations[0];
if (!activeConv) {
  return [];
}
return [{
  json: {
    conversation_id: activeConv.id,
    message: $input.item.json.message
  }
}];`
    }
  },
  // ---- NEW NODE 5c: Enviar Mensagem Chatwoot ----
  {
    id: 'node-enviar-mensagem-chatwoot',
    name: 'Enviar Mensagem Chatwoot',
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [1560, 300],
    parameters: {
      method: 'POST',
      url: '={{ $env.CHATWOOT_URL }}/api/v1/accounts/{{ $env.CHATWOOT_ACCOUNT_ID }}/conversations/{{ $json.conversation_id }}/messages',
      sendHeaders: true,
      headerParameters: {
        parameters: [
          {
            name: 'api_access_token',
            value: '={{ $env.CHATWOOT_API_TOKEN }}'
          }
        ]
      },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: '={{ JSON.stringify({ content: $json.message, message_type: "outgoing", private: false }) }}',
      options: {}
    }
  }
];

// Connections: same existing ones, but replace Evolution API connection with Chatwoot chain
const connections = {
  'Agendar Diário 12h UTC': {
    main: [
      [
        {
          node: 'GET Lembretes do Dia',
          type: 'main',
          index: 0
        }
      ]
    ]
  },
  'GET Lembretes do Dia': {
    main: [
      [
        {
          node: 'Tem Lembretes?',
          type: 'main',
          index: 0
        }
      ]
    ]
  },
  'Tem Lembretes?': {
    main: [
      [
        {
          node: 'Dividir Lembretes',
          type: 'main',
          index: 0
        }
      ],
      [
        {
          node: 'Sem Lembretes (Parar)',
          type: 'main',
          index: 0
        }
      ]
    ]
  },
  'Dividir Lembretes': {
    main: [
      [
        {
          node: 'Buscar Contato Chatwoot',
          type: 'main',
          index: 0
        }
      ]
    ]
  },
  'Buscar Contato Chatwoot': {
    main: [
      [
        {
          node: 'Pegar Conversa',
          type: 'main',
          index: 0
        }
      ]
    ]
  },
  'Pegar Conversa': {
    main: [
      [
        {
          node: 'Enviar Mensagem Chatwoot',
          type: 'main',
          index: 0
        }
      ]
    ]
  }
};

const payload = {
  name: 'ATLAS — Lembretes Diários',
  nodes: nodes,
  connections: connections,
  settings: {
    executionOrder: 'v1',
    saveManualExecutions: true,
    callerPolicy: 'workflowsFromSameOwner',
    errorWorkflow: ''
  },
  staticData: null
};

const body = JSON.stringify(payload);

const url = new URL('https://n8n.rodrigobrito.cloud/api/v1/workflows/' + WORKFLOW_ID);

const options = {
  hostname: url.hostname,
  path: url.pathname,
  method: 'PUT',
  headers: {
    'X-N8N-API-KEY': API_KEY,
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body)
  }
};

console.log('Sending PUT to:', url.toString());
console.log('Nodes:', nodes.map(n => n.name).join(', '));

const req = https.request(options, function(res) {
  let data = '';
  res.on('data', function(chunk) { data += chunk; });
  res.on('end', function() {
    console.log('Status:', res.statusCode);
    try {
      const parsed = JSON.parse(data);
      if (res.statusCode === 200 || res.statusCode === 201) {
        console.log('SUCCESS! Workflow updated.');
        console.log('Workflow ID:', parsed.id);
        console.log('Workflow name:', parsed.name);
        console.log('Nodes count:', parsed.nodes ? parsed.nodes.length : 'N/A');
        console.log('Nodes in workflow:', parsed.nodes ? parsed.nodes.map(n => n.name).join(', ') : 'N/A');
      } else {
        console.error('ERROR response:', JSON.stringify(parsed, null, 2));
      }
    } catch (e) {
      console.error('Could not parse response:', data);
    }
  });
});

req.on('error', function(err) {
  console.error('Request error:', err.message);
});

req.write(body);
req.end();
