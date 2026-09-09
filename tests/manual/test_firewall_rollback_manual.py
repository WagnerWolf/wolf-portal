from app.nftables_rules import NftablesRules
from app.nftables_executor import NftablesExecutor

ruleset = NftablesRules().generate_ruleset()
print(ruleset)

executor = NftablesExecutor(rollback_seconds=30)
executor.apply_with_rollback(ruleset)

print("\nO rollback automático ocorrerá em 30 segundos.")
print("Digite CONFIRMAR para manter.")

while True:
    try:
        resposta = input("> ").strip().upper()
        if resposta == "CONFIRMAR":
            executor.confirm()
            print("APLICAÇÃO CONFIRMADA.")
            break
    except KeyboardInterrupt:
        break
