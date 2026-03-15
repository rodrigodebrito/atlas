var fs = require('fs');
var data = JSON.parse(fs.readFileSync('c:/Users/Rodrigo Brito/Desktop/Atlas/workflow_full.json', 'utf8'));
var jsonStr = JSON.stringify(data);
var count = 0;
var idx = jsonStr.indexOf('Lucas');
while (idx !== -1) {
  count++;
  var ctx = jsonStr.substring(Math.max(0, idx - 200), idx + 200);
  console.log('--- MATCH ' + count + ' at pos ' + idx + ' ---');
  console.log(ctx);
  console.log();
  idx = jsonStr.indexOf('Lucas', idx + 1);
}
console.log('Total matches: ' + count);
