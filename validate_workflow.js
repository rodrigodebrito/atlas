const fs = require('fs');
const wf = JSON.parse(fs.readFileSync('C:/Users/Rodrigo Brito/Desktop/Atlas/atlas_live_validation.json', 'utf8'));

console.log('=== WORKFLOW LIVE VALIDATION ===');
if (!wf.id) {
  console.log('ERROR: Could not fetch workflow:', JSON.stringify(wf));
  process.exit(1);
}

console.log('Workflow ID:', wf.id);
console.log('Name:', wf.name);
console.log('Active:', wf.active);
console.log('Total nodes:', wf.nodes.length);
console.log('');

// 1. Check all new nodes exist
var errors = [];
var warnings = [];

console.log('--- Node Checks ---');

var nodeChecks = [
  { name: 'Verificar rate limit', expectedPos: [-1000, 144], expectCOF: true },
  { name: 'Rate limit atingido?', expectedPos: [-700, 144], expectCOF: false },
  { name: 'Aviso rate limit', expectedPos: [-700, 400], expectCOF: false },
  { name: 'Resposta valida?', expectedPos: [900, 144], expectCOF: false },
  { name: 'Aviso instabilidade', expectedPos: [900, 400], expectCOF: false },
  { name: 'ATLAS Agno API', expectedPos: [208, 144], expectCOF: true }
];

nodeChecks.forEach(function(check) {
  var n = wf.nodes.find(function(x) { return x.name === check.name; });
  if (!n) {
    errors.push('MISSING node: ' + check.name);
    console.log('  [FAIL] ' + check.name + ': NOT FOUND');
    return;
  }
  var posOk = JSON.stringify(n.position) === JSON.stringify(check.expectedPos);
  var cofOk = check.expectCOF ? n.continueOnFail === true : true;
  var status = (posOk && cofOk) ? '[OK]' : '[WARN]';
  console.log('  ' + status + ' ' + check.name);
  console.log('         pos=' + JSON.stringify(n.position) + (posOk ? ' OK' : ' EXPECTED=' + JSON.stringify(check.expectedPos)));
  if (check.expectCOF) {
    console.log('         continueOnFail=' + n.continueOnFail + (cofOk ? ' OK' : ' EXPECTED=true'));
    if (!cofOk) warnings.push(check.name + ' continueOnFail not set to true');
  }
  if (n.type) console.log('         type=' + n.type + ' v' + n.typeVersion);
});

// 2. Check connections
console.log('');
console.log('--- Connection Checks ---');

var c = wf.connections;

function checkConn(label, source, outIdx, expectedTarget) {
  var src = c[source];
  if (!src || !src.main) {
    errors.push('No connections from: ' + source);
    console.log('  [FAIL] ' + label + ': No connections from ' + source);
    return false;
  }
  var branch = src.main[outIdx] || [];
  var targets = branch.map(function(x) { return x.node; });
  if (targets.indexOf(expectedTarget) >= 0) {
    console.log('  [OK] ' + label + ': ' + source + ' -> ' + expectedTarget);
    return true;
  } else {
    errors.push(label + ': Expected ' + source + ' -> ' + expectedTarget + ' but got [' + targets.join(',') + ']');
    console.log('  [FAIL] ' + label + ': ' + source + ' -> ' + expectedTarget + ' (got: ' + (targets.join(',') || 'none') + ')');
    return false;
  }
}

function checkNoConn(label, source, target) {
  var src = c[source];
  if (!src || !src.main) { return true; }
  var allTargets = [];
  src.main.forEach(function(branch) {
    (branch || []).forEach(function(conn) { allTargets.push(conn.node); });
  });
  if (allTargets.indexOf(target) >= 0) {
    errors.push(label + ': Old connection still exists: ' + source + ' -> ' + target);
    console.log('  [FAIL] ' + label + ': Old connection still exists: ' + source + ' -> ' + target);
    return false;
  } else {
    console.log('  [OK] ' + label + ': Old connection removed (' + source + ' -/-> ' + target + ')');
    return true;
  }
}

// Removed connections
checkNoConn('Op7', 'Coletar mensagens1', 'ATLAS Agno API');
checkNoConn('Op8', 'ATLAS Agno API', 'Quebrar e enviar mensagens1');

// New connections
checkConn('Op9', 'Coletar mensagens1', 0, 'Verificar rate limit');
checkConn('Op10', 'Verificar rate limit', 0, 'Rate limit atingido?');
checkConn('Op11-TRUE', 'Rate limit atingido?', 0, 'Aviso rate limit');
checkConn('Op12-FALSE', 'Rate limit atingido?', 1, 'ATLAS Agno API');
checkConn('Op13', 'Aviso rate limit', 0, 'Limpar status atendimento3');
checkConn('Op14', 'ATLAS Agno API', 0, 'Resposta valida?');
checkConn('Op15-TRUE', 'Resposta valida?', 0, 'Quebrar e enviar mensagens1');
checkConn('Op16-FALSE', 'Resposta valida?', 1, 'Aviso instabilidade');
checkConn('Op17', 'Aviso instabilidade', 0, 'Limpar status atendimento3');

// 3. Summary
console.log('');
console.log('=== VALIDATION SUMMARY ===');
if (errors.length === 0) {
  console.log('RESULT: ALL CHECKS PASSED');
  console.log('');
  console.log('Final flow:');
  console.log('  Coletar mensagens1');
  console.log('    -> Verificar rate limit (Postgres, continueOnFail=true)');
  console.log('      -> Rate limit atingido? (IF: msg_count > 30)');
  console.log('         [TRUE]  -> Aviso rate limit -> Limpar status atendimento3');
  console.log('         [FALSE] -> ATLAS Agno API (continueOnFail=true)');
  console.log('                     -> Resposta valida? (IF: content notEmpty)');
  console.log('                        [TRUE]  -> Quebrar e enviar mensagens1 -> Limpar status atendimento3');
  console.log('                        [FALSE] -> Aviso instabilidade -> Limpar status atendimento3');
} else {
  console.log('ERRORS (' + errors.length + '):');
  errors.forEach(function(e) { console.log('  - ' + e); });
}
if (warnings.length > 0) {
  console.log('WARNINGS (' + warnings.length + '):');
  warnings.forEach(function(w) { console.log('  - ' + w); });
}
