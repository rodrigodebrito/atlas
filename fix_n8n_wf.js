const fs = require('fs');
const wf = JSON.parse(fs.readFileSync('n8n_wf_fixed.json', 'utf8'));

const NEW_CODE = `const phone = $input.item.json.phone;
const message = $input.item.json.message;

// 1. Buscar contato no Chatwoot pelo telefone
const searchData = await this.helpers.httpRequest({
  method: 'GET',
  url: 'https://chatwood.rodrigobrito.cloud/api/v1/accounts/1/contacts/search',
  qs: { q: phone },
  headers: { 'api_access_token': 'KmFTvrjqvLuUSEQwAaUuJe4d' }
});
const contacts = searchData.payload || [];
if (!contacts || contacts.length === 0) {
  return { json: {} };
}
const contactId = contacts[0].id;

// 2. Buscar conversas do contato
const convData = await this.helpers.httpRequest({
  method: 'GET',
  url: 'https://chatwood.rodrigobrito.cloud/api/v1/accounts/1/contacts/' + contactId + '/conversations',
  headers: { 'api_access_token': 'KmFTvrjqvLuUSEQwAaUuJe4d' }
});
const conversations = convData.payload || [];
const activeConv = conversations.find(c => c.status === 'open') || conversations[0];
if (!activeConv) {
  return { json: {} };
}
return {
  json: {
    conversation_id: activeConv.id,
    message: message
  }
};`;

// Update Pegar Conversa code
wf.nodes.forEach(n => {
  if (n.name === 'Pegar Conversa') {
    n.parameters.jsCode = NEW_CODE;
  }
});

// Remove "Buscar Contato Chatwoot" node
wf.nodes = wf.nodes.filter(n => n.name !== 'Buscar Contato Chatwoot');

// Rewire connections: Dividir Lembretes -> Pegar Conversa (skip Buscar Contato)
// Original: Dividir Lembretes -> Buscar Contato Chatwoot -> Pegar Conversa -> Enviar Mensagem
// New:      Dividir Lembretes -> Pegar Conversa -> Enviar Mensagem
if (wf.connections['Dividir Lembretes']) {
  wf.connections['Dividir Lembretes'] = {
    main: [[{ node: 'Pegar Conversa', type: 'main', index: 0 }]]
  };
}
// Remove old Buscar Contato connection
delete wf.connections['Buscar Contato Chatwoot'];

// Fix Enviar Mensagem Chatwoot URL and body
wf.nodes.forEach(n => {
  if (n.name === 'Enviar Mensagem Chatwoot') {
    n.parameters.url = '=https://chatwood.rodrigobrito.cloud/api/v1/accounts/1/conversations/{{ $json.conversation_id }}/messages';
    n.parameters.headerParameters = {
      parameters: [{ name: 'api_access_token', value: 'KmFTvrjqvLuUSEQwAaUuJe4d' }]
    };
    n.parameters.jsonBody = '={{ JSON.stringify({ content: $json.message, message_type: "outgoing", private: false }) }}';
  }
});

const payload = JSON.stringify({ nodes: wf.nodes, connections: wf.connections, settings: wf.settings, name: wf.name });
fs.writeFileSync('n8n_wf_payload.json', payload);
console.log('Payload ready, size:', payload.length);
console.log('Nodes:', wf.nodes.map(n => n.name));
console.log('Connections:', JSON.stringify(wf.connections, null, 2));
