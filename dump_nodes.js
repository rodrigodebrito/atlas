var fs = require('fs');
var data = JSON.parse(fs.readFileSync('c:/Users/Rodrigo Brito/Desktop/Atlas/workflow_full.json', 'utf8'));
var nodes = data.nodes || [];

// Dump all Set nodes
console.log('=== SET NODES ===');
nodes.filter(function(n){ return n.type === 'n8n-nodes-base.set'; }).forEach(function(n) {
  console.log('\nNAME: ' + n.name);
  console.log('PARAMS: ' + JSON.stringify(n.parameters, null, 2));
});

// Dump all HTTP Request nodes
console.log('\n=== HTTP REQUEST NODES ===');
nodes.filter(function(n){ return n.type === 'n8n-nodes-base.httpRequest'; }).forEach(function(n) {
  console.log('\nNAME: ' + n.name);
  console.log('PARAMS: ' + JSON.stringify(n.parameters, null, 2));
});

// Dump all Code nodes
console.log('\n=== CODE NODES ===');
nodes.filter(function(n){ return n.type === 'n8n-nodes-base.code'; }).forEach(function(n) {
  console.log('\nNAME: ' + n.name);
  console.log('PARAMS: ' + JSON.stringify(n.parameters, null, 2));
});

// Dump all Sticky Notes
console.log('\n=== STICKY NOTES ===');
nodes.filter(function(n){ return n.type === 'n8n-nodes-base.stickyNote'; }).forEach(function(n) {
  console.log('\nNAME: ' + n.name);
  console.log('CONTENT: ' + JSON.stringify(n.parameters, null, 2));
});
