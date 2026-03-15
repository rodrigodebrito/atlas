import json, urllib.request

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ"
WF_ID = "yjYojxfTCjKGjsJ6"
BASE = "https://n8n.rodrigobrito.cloud"

# GET
req = urllib.request.Request(f"{BASE}/api/v1/workflows/{WF_ID}", headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req) as r:
    wf = json.loads(r.read().decode("utf-8", errors="replace"))

# Inspecionar e corrigir ATLAS Agno API
for node in wf["nodes"]:
    if node["name"] == "ATLAS Agno API":
        print("Node encontrado. Params atuais:")
        print(json.dumps(node["parameters"], indent=2, ensure_ascii=False)[:800])

        # Reescrever completamente os bodyParameters
        node["parameters"]["bodyParameters"] = {
            "parameters": [
                {"name": "message",    "value": "={{ $json.mensagem }}"},
                {"name": "session_id", "value": "={{ $('Info1').item.json.telefone }}"},
                {"name": "stream",     "value": "false"},
            ]
        }
        print("\nCorrigido para:")
        for p in node["parameters"]["bodyParameters"]["parameters"]:
            print(f"  {p['name']} = {p['value']}")
        break

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
    f"{BASE}/api/v1/workflows/{WF_ID}", data=body, method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}
)
with urllib.request.urlopen(req2) as r:
    resp = json.loads(r.read().decode("utf-8", errors="replace"))

if "id" in resp:
    # Verificar que foi salvo corretamente
    for node in resp["nodes"]:
        if node["name"] == "ATLAS Agno API":
            params = node["parameters"]["bodyParameters"]["parameters"]
            print("\nVerificacao pos-PUT:")
            for p in params:
                print(f"  {p['name']} = {p['value']}")
    print("\nOK — workflow atualizado!")
else:
    print(f"ERRO: {str(resp)[:300]}")
