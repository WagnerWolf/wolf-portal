import subprocess
import time

TABLE = "inet wolf_portal"


def run(cmd):
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout, end="")

    if result.stderr:
        print(result.stderr, end="")

    return result


def cleanup():
    run(["nft", "delete", "table", "inet", "wolf_portal"])


print("========================================")
print(" TESTE REAL DE CONTROLE DE ACESSO")
print("========================================")
print()
print("WAN: pppoe-wan")
print("LAN: br-lan")
print()

# MAC autorizado para o teste.
# SUBSTITUA pelo MAC REAL do computador que deverá permanecer autorizado.
AUTHORIZED_MAC = "70:08:10:B3:3F:71"

ruleset = f"""
table inet wolf_portal {{

    set authorized_macs {{
        type ether_addr
        elements = {{ {AUTHORIZED_MAC} }}
    }}

    chain forward {{
        type filter hook forward priority -100; policy accept;

        # MAC autorizado pode sair para a Internet.
        iifname "br-lan" oifname "pppoe-wan" \
            ether saddr @authorized_macs counter accept

        # Qualquer outro MAC vindo da LAN não pode chegar à WAN.
        iifname "br-lan" oifname "pppoe-wan" \
            counter drop
    }}
}}
"""

print("===== VALIDANDO RULESET =====")
check = subprocess.run(
    ["nft", "-c", "-f", "-"],
    input=ruleset,
    text=True,
    capture_output=True,
)

if check.returncode != 0:
    print("ERRO: ruleset inválido.")
    print(check.stderr)
    raise SystemExit(1)

print("Ruleset válido.")
print()

print("===== APLICANDO =====")

apply = subprocess.run(
    ["nft", "-f", "-"],
    input=ruleset,
    text=True,
    capture_output=True,
)

if apply.returncode != 0:
    print("ERRO ao aplicar ruleset.")
    print(apply.stderr)
    raise SystemExit(1)

print("Ruleset aplicado.")
print()

print("===== REGRAS ATIVAS =====")
run(["nft", "list", "table", "inet", "wolf_portal"])

print()
print("========================================")
print(" TESTE AGORA A PARTIR DOS CLIENTES")
print("========================================")
print()
print("1. No computador cujo MAC foi colocado")
print("   como autorizado:")
print()
print("       ping 1.1.1.1")
print()
print("2. De outro dispositivo NÃO autorizado:")
print()
print("       ping 1.1.1.1")
print()
print("3. No dispositivo não autorizado:")
print()
print("       ping 10.0.69.1")
print()
print("O último teste deve continuar funcionando.")
print()
print("Aguardando 30 segundos...")
print()

for remaining in range(30, 0, -1):
    print(f"\r===== {remaining:02d}s restantes =====", end="", flush=True)
    time.sleep(1)

print()
print()

print("===== CONTADORES FINAIS =====")
run(["nft", "list", "table", "inet", "wolf_portal"])

print()
print("===== VERIFICANDO FW4 =====")

fw4 = run(["nft", "list", "table", "inet", "fw4"])

if fw4.returncode == 0:
    print("OK: inet fw4 continua presente.")
else:
    print("ERRO: inet fw4 não pôde ser consultada.")

print()
print("===== CLEANUP =====")

cleanup()

print("Tabela wolf_portal removida.")
print()

print("===== VERIFICAÇÃO FINAL =====")

wolf = run(["nft", "list", "table", "inet", "wolf_portal"])

if wolf.returncode != 0:
    print("OK: wolf_portal não existe mais.")
else:
    print("ATENÇÃO: wolf_portal ainda existe!")

fw4_final = run(["nft", "list", "table", "inet", "fw4"])

if fw4_final.returncode == 0:
    print("OK: inet fw4 continua presente.")
else:
    print("ERRO CRÍTICO: inet fw4 não está acessível.")

print()
print("===== TESTE FINALIZADO =====")
