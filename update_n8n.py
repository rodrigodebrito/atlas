"""Update n8n workflow: sanitize content expression in Quebrar node."""
import json
import urllib.request

API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiZDQyOTA1MTAtM2E3MS00NDliLWJlYWYtMGRhOWRlYjYyMDY1IiwiaWF0IjoxNzcyNjU0MjYyLCJleHAiOjE3NzUxODUyMDB9.zo7lmdUdUXm3FyB8PcUTL2XSBBMTrxKu3ZRGCj4Nlr0"
BASE = "https://n8n.rodrigobrito.cloud/api/v1/workflows/yjYojxfTCjKGjsJ6"

# 1. Read workflow
req = urllib.request.Request(BASE, headers={"X-N8N-API-KEY": API_KEY})
with urllib.request.urlopen(req) as resp:
    raw = resp.read()

wf = json.loads(raw.decode("utf-8", errors="surrogatepass"))

# 2. Find and update the "Quebrar e enviar mensagens1" node
changed = False
for node in wf["nodes"]:
    if node["name"] == "Quebrar e enviar mensagens1":
        params = node["parameters"]["workflowInputs"]["value"]
        old_val = params.get("mensagem", "")
        # Replace direct content reference with sanitized version
        new_val = '={{ ($json.content || "").replace(/\\x00/g, "") }}'
        params["mensagem"] = new_val
        print(f"OLD: {old_val}")
        print(f"NEW: {new_val}")
        changed = True
        break

if not changed:
    print("ERROR: Node not found!")
    exit(1)

# 3. PUT back - only nodes and connections
payload_obj = {
    "name": wf["name"],
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": {"executionOrder": wf.get("settings", {}).get("executionOrder", "v1")},
}
# Serialize with ensure_ascii to avoid encoding issues
payload = json.dumps(payload_obj, ensure_ascii=True).encode("utf-8")

req2 = urllib.request.Request(
    BASE,
    data=payload,
    headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
    method="PUT",
)
try:
    with urllib.request.urlopen(req2) as resp2:
        result = json.loads(resp2.read().decode("utf-8", errors="replace"))
        print(f"OK: {result.get('name')} (active={result.get('active')})")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    print(f"HTTP {e.code}: {body[:500]}")
