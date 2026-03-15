"""Cria workflow n8n para retrospectiva mensal dia 1 as 10h BRT."""
import json
import urllib.request

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiYTgxM2EyMTAtODE1Zi00NDRjLWJjOWMtNjMxZjI1ZWU4MTFiIiwiaWF0IjoxNzczMTc5NTUwfQ.IMw_wQvahzvk415AUe7lfCH67kOSLQXfaum0TNohC5k"
BASE = "https://n8n.rodrigobrito.cloud"

workflow = {
    "name": "ATLAS \u2014 Retrospectiva Mensal (dia 1, 10h)",
    "nodes": [
        {
            "parameters": {
                "rule": {
                    "interval": [
                        {
                            "field": "cronExpression",
                            "expression": "0 13 1 * *"
                        }
                    ]
                }
            },
            "name": "Cron Dia 1 \u2014 10h BRT",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 0],
            "id": "cron-recap-d1"
        },
        {
            "parameters": {
                "url": "https://atlas-m3wb.onrender.com/v1/reports/monthly-recap",
                "options": {}
            },
            "name": "GET Retrospectiva",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [220, 0],
            "id": "get-recap"
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict"
                    },
                    "conditions": [
                        {
                            "id": "cond-count",
                            "leftValue": "={{ $json.count }}",
                            "rightValue": 0,
                            "operator": {
                                "type": "number",
                                "operation": "gt"
                            }
                        }
                    ],
                    "combinator": "and"
                },
                "options": {}
            },
            "name": "Tem recaps?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [440, 0],
            "id": "if-has-recap"
        },
        {
            "parameters": {},
            "name": "Ningu\u00e9m (Parar)",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [660, 120],
            "id": "no-op-stop"
        },
        {
            "parameters": {
                "jsCode": "return $input.first().json.messages.map(r => ({ json: r }));"
            },
            "name": "Dividir Mensagens",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [660, -60],
            "id": "split-messages"
        },
        {
            "parameters": {
                "mode": "runOnceForEachItem",
                "jsCode": "const phone = $input.item.json.phone;\nconst message = $input.item.json.message;\n\nconst searchData = await this.helpers.httpRequest({\n  method: 'GET',\n  url: 'https://chatwood.rodrigobrito.cloud/api/v1/accounts/1/contacts/search',\n  qs: { q: phone },\n  headers: { 'api_access_token': 'KmFTvrjqvLuUSEQwAaUuJe4d' }\n});\nconst contacts = searchData.payload || [];\nif (!contacts || contacts.length === 0) {\n  return { json: { skip: true } };\n}\nconst contactId = contacts[0].id;\n\nconst convData = await this.helpers.httpRequest({\n  method: 'GET',\n  url: 'https://chatwood.rodrigobrito.cloud/api/v1/accounts/1/contacts/' + contactId + '/conversations',\n  headers: { 'api_access_token': 'KmFTvrjqvLuUSEQwAaUuJe4d' }\n});\nconst conversations = convData.payload || [];\nconst activeConv = conversations.find(c => c.status === 'open') || conversations[0];\nif (!activeConv) {\n  return { json: { skip: true } };\n}\nreturn {\n  json: {\n    conversation_id: activeConv.id,\n    message: message,\n    skip: false\n  }\n};"
            },
            "name": "Pegar Conversa",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [880, -60],
            "id": "get-conversation"
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict"
                    },
                    "conditions": [
                        {
                            "id": "cond-skip",
                            "leftValue": "={{ $json.skip }}",
                            "rightValue": True,
                            "operator": {
                                "type": "boolean",
                                "operation": "notEquals"
                            }
                        }
                    ],
                    "combinator": "and"
                },
                "options": {}
            },
            "name": "Tem conversa?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [1100, -60],
            "id": "if-has-conv"
        },
        {
            "parameters": {
                "method": "POST",
                "url": "=https://chatwood.rodrigobrito.cloud/api/v1/accounts/1/conversations/{{ $json.conversation_id }}/messages",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {
                            "name": "api_access_token",
                            "value": "KmFTvrjqvLuUSEQwAaUuJe4d"
                        }
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ content: $json.message, message_type: \"outgoing\", private: false, content_type: \"text\" }) }}",
                "options": {}
            },
            "name": "Enviar via Chatwoot",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1320, -120],
            "id": "send-chatwoot"
        },
        {
            "parameters": {
                "amount": 45,
                "unit": "seconds"
            },
            "name": "Esperar 45s",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [1540, -120],
            "webhookId": "recap-wait-45s",
            "id": "wait-45s"
        },
        {
            "parameters": {},
            "name": "Sem conversa (skip)",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [1320, 40],
            "id": "no-op-skip"
        }
    ],
    "connections": {
        "Cron Dia 1 \u2014 10h BRT": {
            "main": [[{"node": "GET Retrospectiva", "type": "main", "index": 0}]]
        },
        "GET Retrospectiva": {
            "main": [[{"node": "Tem recaps?", "type": "main", "index": 0}]]
        },
        "Tem recaps?": {
            "main": [
                [{"node": "Dividir Mensagens", "type": "main", "index": 0}],
                [{"node": "Ningu\u00e9m (Parar)", "type": "main", "index": 0}]
            ]
        },
        "Dividir Mensagens": {
            "main": [[{"node": "Pegar Conversa", "type": "main", "index": 0}]]
        },
        "Pegar Conversa": {
            "main": [[{"node": "Tem conversa?", "type": "main", "index": 0}]]
        },
        "Tem conversa?": {
            "main": [
                [{"node": "Enviar via Chatwoot", "type": "main", "index": 0}],
                [{"node": "Sem conversa (skip)", "type": "main", "index": 0}]
            ]
        },
        "Enviar via Chatwoot": {
            "main": [[{"node": "Esperar 45s", "type": "main", "index": 0}]]
        }
    },
    "settings": {
        "executionOrder": "v1"
    }
}

data = json.dumps(workflow).encode()
req = urllib.request.Request(
    f"{BASE}/api/v1/workflows",
    data=data,
    headers={
        "X-N8N-API-KEY": API_KEY,
        "Content-Type": "application/json"
    },
    method="POST"
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
wf_id = result["id"]
print(f"Workflow criado! ID: {wf_id}, Nome: {result['name']}")

# Ativar
activate_req = urllib.request.Request(
    f"{BASE}/api/v1/workflows/{wf_id}/activate",
    headers={"X-N8N-API-KEY": API_KEY},
    method="POST"
)
urllib.request.urlopen(activate_req)
print("Workflow ativado!")
