"""
Simulacao de conversa real com o ATLAS.
Cada mensagem usa o prefixo [user_phone: ...] como o n8n faz.
"""
import urllib.request, urllib.parse, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://atlas-m3wb.onrender.com"
SESSION_ID = "test_sim_user_002"
USER_PHONE = "+5534999990002"

def chat(message: str, label: str = "") -> str:
    full_message = f"[user_phone: {USER_PHONE}]\n{message}"
    data = urllib.parse.urlencode({
        "message": full_message,
        "session_id": SESSION_ID,
        "stream": "false",
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/agents/atlas/runs",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())

    content = resp.get("content", str(resp))
    tag = f"[{label}] " if label else ""
    print(f"\n{'='*60}")
    print(f"👤 USER{' — ' + label if label else ''}: {message}")
    print(f"{'='*60}")
    print(f"🤖 ATLAS: {content}")
    return content

# --- SIMULAÇÃO ---

print("\n🧪 INICIANDO SIMULAÇÃO DE USUÁRIO REAL\n")

# 1. Primeira mensagem — onboarding
chat("Oi", "1. primeiro contato")
time.sleep(3)

# 2. Nome
chat("Carlos", "2. nome")
time.sleep(3)

# 3. Renda
chat("4500", "3. renda")
time.sleep(3)

# 4. Primeiro gasto — simples
chat("gastei 45 no iFood", "4. gasto simples")
time.sleep(3)

# 5. Gasto com estabelecimento explícito
chat("paguei 120 no mercado extra", "5. gasto com merchant")
time.sleep(3)

# 6. Gasto parcelado
chat("comprei um tênis por 360 em 3x no cartão de crédito", "6. parcelado")
time.sleep(3)

# 7. Receita
chat("recebi meu salário 4500", "7. receita")
time.sleep(3)

# 8. Resumo do mês
chat("resumo do mês", "8. resumo")
time.sleep(3)

# 9. Detalhes de categoria
chat("onde gastei em Alimentação?", "9. category breakdown")
time.sleep(3)

# 10. Posso comprar?
chat("posso comprar um celular de 800 reais?", "10. can i buy")
time.sleep(3)

# 11. Correção de merchant
chat("espera, o tênis foi na Nike Store", "11. corrigir merchant")
time.sleep(3)

# 12. Pergunta fora do escopo
chat("qual a previsão do tempo amanhã?", "12. fora do escopo")
time.sleep(3)

# 13. Pergunta de saldo
chat("qual meu saldo?", "13. saldo")
time.sleep(3)

# 14. Gasto sem merchant
chat("gastei 18", "14. gasto sem contexto")
time.sleep(3)

print("\n\n🏁 SIMULAÇÃO CONCLUÍDA")
