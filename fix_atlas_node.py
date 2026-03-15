import json, urllib.request, urllib.error

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ"
WF_ID = "yjYojxfTCjKGjsJ6"
BASE = "https://n8n.rodrigobrito.cloud"

# GET workflow
req = urllib.request.Request(
    f"{BASE}/api/v1/workflows/{WF_ID}",
    headers={"X-N8N-API-KEY": API_KEY}
)
with urllib.request.urlopen(req) as r:
    raw = r.read().decode("utf-8", errors="replace")
wf = json.loads(raw)

# Fix ATLAS Agno API node
for node in wf["nodes"]:
    if node["name"] == "ATLAS Agno API":
        params = node["parameters"]["bodyParameters"]["parameters"]
        for p in params:
            if p["name"] == "message":
                p["value"] = "={{ $json.mensagem }}"
            elif p["name"] == "session_id":
                p["value"] = "={{ $('Info1').item.json.telefone }}"
        print("Expressoes corrigidas:")
        for p in params:
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
    f"{BASE}/api/v1/workflows/{WF_ID}",
    data=body,
    method="PUT",
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}
)
with urllib.request.urlopen(req2) as r:
    resp = json.loads(r.read().decode("utf-8", errors="replace"))

if "id" in resp:
    print(f"OK — workflow atualizado! nodes={len(resp.get('nodes', []))}")
else:
    print(f"ERRO: {str(resp)[:300]}")
