"""
Adiciona nós de Typing Indicator (ON/OFF) no workflow do n8n Atlas.

Fluxo atual:
  Coletar mensagens1 → ATLAS Agno API → Quebrar e enviar mensagens1

Fluxo novo:
  Coletar mensagens1 → Typing ON → ATLAS Agno API → Typing OFF → Quebrar e enviar mensagens1
"""

import json
import uuid
import urllib.request
import urllib.error

WORKFLOW_ID = "yjYojxfTCjKGjsJ6"
N8N_URL = "https://n8n.rodrigobrito.cloud"
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxODM5M2NmZi1iZjZlLTRkNzctOGUxZi1hZGYwYmYxMTZkYjQiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNWY2M2MwYTYtMWNmOS00MjMyLTk2YmMtNDA5NDFlMzYwYWExIiwiaWF0IjoxNzcyNDUxNzk1LCJleHAiOjE3NzUwMTI0MDB9.q5TnS7XYAU5ziiAMcXnv4rcqxAIPldXprLutDjvaWtQ"
CHATWOOT_CRED = {"id": "VIcktgIr9MjDltkK", "name": "ChatWoot account"}


def make_typing_node(name: str, typing_status: str, position: list) -> dict:
    """Cria um nó HTTP Request para toggle_typing_status do Chatwoot."""
    return {
        "parameters": {
            "method": "POST",
            "url": "={{ $('Info1').item.json.url_chatwoot }}/api/v1/accounts/{{ $('Info1').item.json.id_conta }}/conversations/{{ $('Info1').item.json.id_conversa }}/toggle_typing_status",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "chatwootApi",
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {
                        "name": "typing_status",
                        "value": typing_status,
                    }
                ]
            },
            "options": {
                "timeout": 5000,  # não trava o fluxo se Chatwoot demorar
            },
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
        "id": str(uuid.uuid4()),
        "name": name,
        "credentials": {
            "chatwootApi": CHATWOOT_CRED,
        },
        "continueOnFail": True,  # se typing falhar, o fluxo continua normalmente
    }


def main():
    # 1. Carregar workflow atual
    with open("atlas_workflow_current.json", "r", encoding="utf-8") as f:
        wf = json.load(f)

    nodes = wf["nodes"]
    connections = wf["connections"]

    # 2. Encontrar posições dos nós relevantes
    atlas_node = next(n for n in nodes if n["name"] == "ATLAS Agno API")
    quebrar_node = next(n for n in nodes if n["name"] == "Quebrar e enviar mensagens1")

    atlas_x, atlas_y = atlas_node["position"]
    quebrar_x, quebrar_y = quebrar_node["position"]

    # Posicionar Typing ON antes do ATLAS e Typing OFF depois
    typing_on_pos = [atlas_x - 240, atlas_y]
    typing_off_pos = [atlas_x + 240, atlas_y]

    # 3. Criar os dois nós
    node_typing_on = make_typing_node("Typing ON", "on", typing_on_pos)
    node_typing_off = make_typing_node("Typing OFF", "off", typing_off_pos)

    print(f"Typing ON  id: {node_typing_on['id']} pos: {typing_on_pos}")
    print(f"Typing OFF id: {node_typing_off['id']} pos: {typing_off_pos}")

    # 4. Adicionar nós ao workflow
    nodes.append(node_typing_on)
    nodes.append(node_typing_off)

    # 5. Atualizar conexões
    # 5a. Encontrar qual nó aponta para "ATLAS Agno API" e redirecionar para "Typing ON"
    for src_name, src_conns in connections.items():
        for branch in src_conns.get("main", []):
            for edge in branch:
                if edge.get("node") == "ATLAS Agno API":
                    edge["node"] = "Typing ON"
                    print(f"  Redirecionado: {src_name} -> Typing ON")

    # 5b. Inserir Typing ON → ATLAS Agno API
    connections["Typing ON"] = {
        "main": [[{"node": "ATLAS Agno API", "type": "main", "index": 0}]]
    }

    # 5c. Redirecionar saída de ATLAS Agno API para Typing OFF
    if "ATLAS Agno API" in connections:
        for branch in connections["ATLAS Agno API"].get("main", []):
            for edge in branch:
                if edge.get("node") == "Quebrar e enviar mensagens1":
                    edge["node"] = "Typing OFF"
                    print("  Redirecionado: ATLAS Agno API -> Typing OFF")

    # 5d. Inserir Typing OFF → Quebrar e enviar mensagens1
    connections["Typing OFF"] = {
        "main": [[{"node": "Quebrar e enviar mensagens1", "type": "main", "index": 0}]]
    }

    # 6. Salvar workflow atualizado
    with open("atlas_workflow_current.json", "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    print("\nWorkflow salvo em atlas_workflow_current.json")

    # 7. Preparar payload para n8n
    payload = {
        "name": wf.get("name", "Atlas"),
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "staticData": wf.get("staticData"),
    }

    body = json.dumps(payload).encode("utf-8")
    url = f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}"

    req = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "X-N8N-API-KEY": API_KEY,
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )

    print(f"\nEnviando PUT para {url}...")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            print(f"✅ Sucesso! Status: {resp.status}")
            print(f"   Workflow ID: {result.get('id')}")
            print(f"   Nós: {len(result.get('nodes', []))}")
            # Confirmar que os novos nós estão lá
            node_names = [n["name"] for n in result.get("nodes", [])]
            for name in ["Typing ON", "Typing OFF"]:
                status = "✅" if name in node_names else "❌"
                print(f"   {status} {name}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"❌ HTTP Error {e.code}: {error_body[:500]}")
    except Exception as e:
        print(f"❌ Erro: {e}")


if __name__ == "__main__":
    main()
