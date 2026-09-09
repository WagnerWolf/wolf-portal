#!/bin/sh

set -eu


APP_DST="/usr/lib/wolf-portal"

CONFIG_DIR="/etc/wolf-portal"

INIT_SCRIPT="/etc/init.d/wolf-portal"

NFT_INCLUDE="/etc/nftables.d/90-wolf-portal.nft"

SYSUPGRADE_CONF="/etc/sysupgrade.conf"

PURGE=0


if [ "${1:-}" = "--purge" ]; then
    PURGE=1
fi


log()
{
    echo
    echo "================================================"
    echo " $1"
    echo "================================================"
}


fail()
{
    echo "ERRO: $*" >&2
    exit 1
}


if [ "$(id -u)" != "0" ]; then
    fail "Execute como root."
fi


# ================================================================
# STOP
# ================================================================

log "PARANDO WOLF PORTAL"

if [ -x "$INIT_SCRIPT" ]; then

    "$INIT_SCRIPT" stop \
        2>/dev/null || true

    "$INIT_SCRIPT" disable \
        2>/dev/null || true
fi


# ================================================================
# FIREWALL
# ================================================================

log "REMOVENDO REGRAS DO FIREWALL"

if [ -d "${APP_DST}/app" ] &&
   command -v python3 >/dev/null 2>&1; then

    PYTHONPATH="$APP_DST" \
    python3 - <<'PY' || true
from app.nftables_executor import NftablesExecutor

executor = NftablesExecutor()

executor.remove_managed_rules()

print("Regras Wolf Portal removidas.")
PY

else

    echo "Aplicação Python não disponível; usando limpeza de fallback."

    rm -f "$NFT_INCLUDE"

    if command -v nft >/dev/null 2>&1; then

        for CHAIN in \
            wolf_portal_prerouting \
            wolf_portal_input \
            wolf_portal_forward
        do

            nft flush chain \
                inet fw4 "$CHAIN" \
                2>/dev/null || true

            nft delete chain \
                inet fw4 "$CHAIN" \
                2>/dev/null || true
        done

        for SET_NAME in \
            wolf_portal_failsafe_macs \
            wolf_portal_authorized_macs \
            wolf_portal_blocked_macs
        do

            nft flush set \
                inet fw4 "$SET_NAME" \
                2>/dev/null || true

            nft delete set \
                inet fw4 "$SET_NAME" \
                2>/dev/null || true
        done
    fi

    if command -v fw4 >/dev/null 2>&1; then
        fw4 check 2>/dev/null || true
        fw4 reload 2>/dev/null || true
    fi
fi


# ================================================================
# DNS STATUS.CLIENT
# ================================================================

log "REMOVENDO DNS DO PORTAL"

if command -v uci >/dev/null 2>&1; then

    CURRENT_ADDRESSES="$(
        uci -q get dhcp.@dnsmasq[0].address ||
        true
    )"

    for ENTRY in $CURRENT_ADDRESSES; do

        case "$ENTRY" in

            /status.client/*)

                uci -q del_list \
                    dhcp.@dnsmasq[0].address="$ENTRY" \
                    2>/dev/null || true
                ;;

        esac
    done

    uci commit dhcp

    /etc/init.d/dnsmasq restart \
        2>/dev/null || true
fi


# ================================================================
# ARQUIVOS
# ================================================================

log "REMOVENDO APLICACAO"

rm -rf "$APP_DST"

rm -f "$INIT_SCRIPT"

rm -f "$NFT_INCLUDE"


# ================================================================
# PURGE
# ================================================================

if [ "$PURGE" -eq 1 ]; then

    log "APAGANDO DADOS"

    rm -rf "$CONFIG_DIR"

    if [ -f "$SYSUPGRADE_CONF" ]; then

        sed -i \
            '\|^/etc/wolf-portal/$|d' \
            "$SYSUPGRADE_CONF"
    fi

    echo "Banco e configuração removidos."

else

    echo
    echo "Dados preservados em:"
    echo
    echo "  $CONFIG_DIR"
    echo
    echo "Para apagar também os dados:"
    echo
    echo "  $0 --purge"
fi


log "DESINSTALACAO CONCLUIDA"