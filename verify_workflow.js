const fs = require('fs');
const resp = JSON.parse(fs.readFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_put_response2.json', 'utf8'));
if (resp.id) {
  console.log('SUCCESS! Workflow updated.');
  console.log('ID:', resp.id);
  console.log('Name:', resp.name);
  console.log('VersionId:', resp.versionId);
  console.log('Node count:', resp.nodes.length);

  // Verify new nodes exist
  const newNodes = ['Verificar rate limit', 'Rate limit atingido?', 'Aviso rate limit', 'Resposta valida?', 'Aviso instabilidade'];
  console.log('');
  console.log('=== NODE VERIFICATION ===');
  newNodes.forEach(function(name) {
    const found = resp.nodes.find(function(n) { return n.name === name; });
    if (found) {
      console.log(name + ': FOUND pos=' + JSON.stringify(found.position) + ' continueOnFail=' + found.continueOnFail);
    } else {
      console.log(name + ': NOT FOUND');
    }
  });

  // Verify ATLAS Agno API
  const atlas = resp.nodes.find(function(n) { return n.name === 'ATLAS Agno API'; });
  console.log('ATLAS Agno API continueOnFail:', atlas ? atlas.continueOnFail : 'NOT FOUND');

  // Verify connections
  console.log('');
  console.log('=== CONNECTION VERIFICATION ===');
  const conns = resp.connections;
  const checks = ['Coletar mensagens1', 'Verificar rate limit', 'Rate limit atingido?', 'Aviso rate limit', 'ATLAS Agno API', 'Resposta valida?', 'Aviso instabilidade'];
  checks.forEach(function(name) {
    if (conns[name]) {
      const main = conns[name].main || [];
      const out0 = (main[0] || []).map(function(c) { return c.node; }).join(', ');
      const out1 = (main[1] || []).map(function(c) { return c.node; }).join(', ');
      let msg = '[' + name + '] out[0]=' + (out0 || 'none');
      if (main.length > 1) msg += ' out[1]=' + (out1 || 'none');
      console.log(msg);
    } else {
      console.log('[' + name + '] NO CONNECTIONS FOUND');
    }
  });
} else {
  console.log('ERROR:');
  console.log(JSON.stringify(resp, null, 2).substring(0, 1000));
}
