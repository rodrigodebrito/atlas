const fs = require('fs');
const https = require('https');

const API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ';
const WORKFLOW_ID = 'yjYojxfTCjKGjsJ6';

const wf = JSON.parse(fs.readFileSync('c:/Users/Rodrigo Brito/Desktop/Atlas/atlas_workflow_current.json', 'utf8'));

// Verify URLs were changed
const atlasNodes = wf.nodes.filter(n => n.name === 'ATLAS Agno API');
atlasNodes.forEach((n, i) => {
  console.log(`ATLAS node ${i + 1} URL: ${n.parameters.url}`);
});

const putBody = {
  name: wf.name,
  nodes: wf.nodes,
  connections: wf.connections,
  settings: {
    executionOrder: wf.settings.executionOrder
  }
};

const bodyStr = JSON.stringify(putBody);
console.log('Body size:', bodyStr.length, 'chars');
console.log('Sending PUT...');

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

const req = https.request(options, function(res) {
  console.log('Status:', res.statusCode);
  const chunks = [];
  res.on('data', d => chunks.push(d));
  res.on('end', () => {
    const body = chunks.join('');
    try {
      const parsed = JSON.parse(body);
      // Verify the URL in response
      const respNodes = parsed.nodes.filter(n => n.name === 'ATLAS Agno API');
      respNodes.forEach((n, i) => {
        console.log(`Response node ${i + 1} URL: ${n.parameters.url}`);
      });
      console.log('SUCCESS - workflow updated!');
    } catch(e) {
      console.log('Response:', body.substring(0, 500));
    }
  });
});

req.on('error', e => console.error('Error:', e.message));
req.write(bodyStr);
req.end();
