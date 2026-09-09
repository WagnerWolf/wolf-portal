#!/bin/sh

TABLE="inet wolf_portal"
CHAIN="test_forward"
LOG="/tmp/wolf_portal_forward_hook_test.log"

exec > >(tee "$LOG") 2>&1

echo "========================================"
echo " WOLF PORTAL - TESTE REAL DO FORWARD"
echo "========================================"
echo

cleanup() {
    echo
    echo "===== CLEANUP ====="

    nft delete table $TABLE 2>/dev/null || true

    echo
    echo "Tabela wolf_portal após cleanup:"
    nft list table $TABLE 2>/dev/null || echo "(tabela não existe)"

    echo
    echo "FW4:"
    nft list table inet fw4 >/dev/null 2>&1 \
        && echo "OK: inet fw4 continua presente." \
        || echo "ERRO: inet fw4 não foi encontrada!"

    echo
    echo "===== TESTE FINALIZADO ====="
}

trap cleanup EXIT INT TERM

echo "===== ESTADO INICIAL ====="

if nft list table $TABLE >/dev/null 2>&1; then
    echo "ATENÇÃO: tabela wolf_portal já existe."
    echo "Não vamos sobrescrevê-la."
    echo
    echo "Conteúdo atual:"
    nft list table $TABLE
    exit 1
else
    echo "OK: tabela wolf_portal não existe."
fi

echo
echo "===== VERIFICANDO FW4 ====="

if nft list table inet fw4 >/dev/null 2>&1; then
    echo "OK: inet fw4 existe."
else
    echo "ERRO: inet fw4 não existe!"
    exit 1
fi

echo
echo "===== APLICANDO HOOK DE TESTE ====="

nft -f - <<'NFT'
table inet wolf_portal {
    chain test_forward {
        type filter hook forward priority -100;
        policy accept;

        iifname "br-lan" counter
    }
}
NFT

if [ $? -ne 0 ]; then
    echo "ERRO: não foi possível aplicar o ruleset."
    exit 1
fi

echo "Ruleset aplicado com sucesso."
echo

echo "===== REGRAS APLICADAS ====="
nft list table inet wolf_portal

echo
echo "========================================"
echo " GERE TRÁFEGO AGORA A PARTIR DE UM"
echo " COMPUTADOR/CELULAR CONECTADO À BR-LAN"
echo
echo " Exemplos:"
echo "   ping 1.1.1.1"
echo "   curl http://example.com"
echo
echo " O contador abaixo será atualizado."
echo " ========================================"

i=15

while [ $i -gt 0 ]; do
    echo
    echo "===== ${i}s restantes ====="
    nft list chain inet wolf_portal test_forward

    sleep 1
    i=$((i - 1))
done

echo
echo "===== RESULTADO FINAL DO CONTADOR ====="
nft list chain inet wolf_portal test_forward

echo
echo "===== VERIFICANDO FW4 ANTES DO ROLLBACK ====="
nft list table inet fw4 >/dev/null 2>&1 \
    && echo "OK: fw4 continua presente." \
    || echo "ERRO: fw4 desapareceu!"

echo
echo "O cleanup será executado agora."
