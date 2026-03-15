import json, urllib.request

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ"
WF_ID = "yjYojxfTCjKGjsJ6"
BASE = "https://n8n.rodrigobrito.cloud"

req = urllib.request.Request(f"{BASE}/api/v1/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req) as r:
    wf = json.loads(r.read())

TELEFONE_EXPR = "={{ $('Info1').item.json.telefone }}"

for node in wf["nodes"]:
    # Limpar memória1 — troca para executeQuery com SQL completo do ATLAS
    if node["name"] == "Limpar memória1":
        node["parameters"] = {
            "operation": "executeQuery",
            "query": (
                "DELETE FROM ai.agno_sessions WHERE session_id = '{{ $('Info1').item.json.telefone }}';\n"
                "DELETE FROM ai.agno_memories WHERE session_id = '{{ $('Info1').item.json.telefone }}';\n"
                "DELETE FROM public.transactions WHERE user_id IN (SELECT id FROM public.users WHERE phone = '{{ $('Info1').item.json.telefone }}');\n"
                "DELETE FROM public.financial_goals WHERE user_id IN (SELECT id FROM public.users WHERE phone = '{{ $('Info1').item.json.telefone }}');\n"
                "DELETE FROM public.users WHERE phone = '{{ $('Info1').item.json.telefone }}';\n"
                "DELETE FROM public.n8n_historico_mensagens WHERE session_id = '{{ $('Info1').item.json.telefone }}';"
            ),
            "options": {}
        }
        print(f"Atualizado: {node['name']}")

    # Limpar fila de mensagens3 — já correto, confirma tabela
    elif node["name"] == "Limpar fila de mensagens3":
        node["parameters"]["schema"] = {"__rl": True, "mode": "list", "value": "public"}
        node["parameters"]["table"] = {"__rl": True, "value": "n8n_fila_mensagens", "mode": "list"}
        print(f"Confirmado: {node['name']}")

    # Resetar status atendimento1 — já correto, confirma tabela
    elif node["name"] == "Resetar status atendimento1":
        node["parameters"]["schema"] = {"__rl": True, "mode": "list", "value": "public"}
        node["parameters"]["table"] = {"__rl": True, "value": "n8n_status_atendimento", "mode": "list"}
        print(f"Confirmado: {node['name']}")

# PUT
payload = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": "v1"},
    "staticData": wf.get("staticData"),
}
body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
req2 = urllib.request.Request(
    f"{BASE}/api/v1/workflows/{WF_ID}",
    data=body, method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}
)
with urllib.request.urlopen(req2) as r:
    resp = json.loads(r.read())

if "id" in resp:
    print("\nOK — workflow atualizado!")
else:
    print(f"ERRO: {str(resp)[:300]}")
