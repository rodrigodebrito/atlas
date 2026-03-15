import json

with open('c:/Users/Rodrigo Brito/Desktop/Atlas/workflow_validated.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

errors = []
found = False
for n in data.get('nodes', []):
    if 'Rate limit' in n.get('name', ''):
        found = True
        conds = n['parameters']['conditions']
        tv = conds['options']['typeValidation']
        lv = conds['conditions'][0]['leftValue']
        rv = conds['conditions'][0]['rightValue']
        op = conds['conditions'][0]['operator']

        expected_lv = '={{ parseInt($json.msg_count) || 0 }}'
        if tv != 'loose':
            errors.append('typeValidation is %r, expected loose' % tv)
        if lv != expected_lv:
            errors.append('leftValue is %r, expected %r' % (lv, expected_lv))
        if rv != 30:
            errors.append('rightValue is %r, expected 30' % rv)
        if op.get('type') != 'number' or op.get('operation') != 'gt':
            errors.append('operator is %r, expected number/gt' % op)

if not found:
    errors.append('Node "Rate limit atingido?" not found')

if errors:
    print('VALIDATION ERRORS (%d):' % len(errors))
    for e in errors:
        print(' -', e)
else:
    print('Validation PASSED: 0 errors')
    print()
    print('Confirmed state of "Rate limit atingido?" node:')
    print('  typeValidation:', tv)
    print('  leftValue:', lv)
    print('  rightValue:', rv)
    print('  operator:', op)
