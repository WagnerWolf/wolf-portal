#!/bin/sh

set -eu


# ================================================================
# WOLF PORTAL - INSTALADOR
# ================================================================
#
# Destinos:
#
#   código:
#       /usr/lib/wolf-portal
#
#   configuração:
#       /etc/wolf-portal
#
#   dados persistentes:
#       /etc/wolf-portal/data
#
#   serviço:
#       /etc/init.d/wolf-portal
#
# ================================================================


APP_DST="/usr/lib/wolf-portal"

CONFIG_DIR="/etc/wolf-portal"
DATA_DIR="${CONFIG_DIR}/data"

DATABASE="${DATA_DIR}/wolf-portal.db"
TELEGRAM_CONFIG="${CONFIG_DIR}/telegram.conf"
TELEGRAM_STATE="${DATA_DIR}/telegram-bot-state.json"

INIT_DST="/etc/init.d/wolf-portal"

SYSUPGRADE_CONF="/etc/sysupgrade.conf"

PORTAL_HOSTNAME="status.client"


# ================================================================
# DIRETÓRIO DO REPOSITÓRIO
# ================================================================

SCRIPT_DIR="$(
    CDPATH= cd -- "$(dirname -- "$0")" &&
    pwd
)"


# ================================================================
# LOG / ERRO
# ================================================================

log()
{
    echo
    echo "================================================"
    echo " $1"
    echo "================================================"
}


fail()
{
    echo
    echo "ERRO: $*" >&2
    exit 1
}


# ================================================================
# ROOT
# ================================================================

if [ "$(id -u)" != "0" ]; then
    fail "Execute este instalador como root."
fi


# ================================================================
# VERIFICA REPOSITÓRIO
# ================================================================

log "VERIFICANDO ARQUIVOS"

[ -d "${SCRIPT_DIR}/app" ] || \
    fail "Diretório app/ não encontrado."

[ -f "${SCRIPT_DIR}/app/main.py" ] || \
    fail "app/main.py não encontrado."

[ -f "${SCRIPT_DIR}/app/portal_server.py" ] || \
    fail "app/portal_server.py não encontrado."

[ -f "${SCRIPT_DIR}/app/telegram_bot.py" ] || \
    fail "app/telegram_bot.py não encontrado."

[ -f "${SCRIPT_DIR}/openwrt/wolf-portal.init" ] || \
    fail "openwrt/wolf-portal.init não encontrado."

echo "Arquivos do projeto: OK"


# ================================================================
# OPENWRT
# ================================================================

[ -f /etc/openwrt_release ] || \
    fail "Este instalador foi criado para OpenWrt."

echo "OpenWrt detectado."


# ================================================================
# GERENCIADOR DE PACOTES
# ================================================================

install_packages()
{
    [ "$#" -gt 0 ] || return 0

    if command -v apk >/dev/null 2>&1; then

        echo "Instalando com apk:"
        echo "  $*"

        apk -U add "$@"

        return
    fi

    if command -v opkg >/dev/null 2>&1; then

        echo "Instalando com opkg:"
        echo "  $*"

        opkg update
        opkg install "$@"

        return
    fi

    fail "Nenhum gerenciador de pacotes suportado encontrado."
}


# ================================================================
# DEPENDÊNCIAS
# ================================================================

log "VERIFICANDO DEPENDENCIAS"


# ------------------------------------------------
# Python
# ------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then

    install_packages \
        python3 \
        python3-sqlite3 \
        python3-urllib \
        python3-openssl \
        ca-bundle
fi


# ------------------------------------------------
# SQLite
# ------------------------------------------------

if ! python3 -c 'import sqlite3' \
    >/dev/null 2>&1; then

    install_packages \
        python3-sqlite3
fi


# ------------------------------------------------
# urllib
# ------------------------------------------------

if ! python3 -c 'import urllib.request' \
    >/dev/null 2>&1; then

    install_packages \
        python3-urllib
fi


# ------------------------------------------------
# SSL
# ------------------------------------------------

if ! python3 -c 'import ssl' \
    >/dev/null 2>&1; then

    install_packages \
        python3-openssl \
        ca-bundle
fi


# ------------------------------------------------
# nftables
# ------------------------------------------------

if ! command -v nft >/dev/null 2>&1; then
    install_packages nftables
fi


# ------------------------------------------------
# firewall4
# ------------------------------------------------

if ! command -v fw4 >/dev/null 2>&1; then
    install_packages firewall4
fi


# ------------------------------------------------
# ip neigh
# ------------------------------------------------

if ! command -v ip >/dev/null 2>&1; then
    install_packages ip-full
fi


# ------------------------------------------------
# UCI
# ------------------------------------------------

command -v uci >/dev/null 2>&1 || \
    fail "uci não encontrado."


# ------------------------------------------------
# Validação final
# ------------------------------------------------

python3 - <<'PY'
import sqlite3
import ssl
import urllib.request

print("Python: OK")
print("sqlite3:", sqlite3.sqlite_version)
print("SSL:", ssl.OPENSSL_VERSION)
PY

command -v nft >/dev/null
command -v fw4 >/dev/null
command -v ip >/dev/null

echo "Dependências: OK"


# ================================================================
# DIRETÓRIOS
# ================================================================

log "CRIANDO DIRETORIOS"

mkdir -p "$APP_DST"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"

chmod 700 "$CONFIG_DIR"
chmod 700 "$DATA_DIR"


# ================================================================
# PARA SERVIÇO EXISTENTE
# ================================================================

if [ -x "$INIT_DST" ]; then

    echo "Parando instalação anterior..."

    "$INIT_DST" stop \
        2>/dev/null || true

    sleep 1
fi


# ================================================================
# COPIA APLICAÇÃO
# ================================================================

log "INSTALANDO APLICACAO"

rm -rf "${APP_DST}/app"

cp -R \
    "${SCRIPT_DIR}/app" \
    "${APP_DST}/"

# Credenciais jamais devem ficar dentro do código instalado.
rm -f \
    "${APP_DST}/app/bot_telegram.conf"


# ------------------------------------------------
# Remove bytecode eventualmente existente no
# diretório do repositório.
# ------------------------------------------------

find "${APP_DST}/app" \
    -type d \
    -name '__pycache__' \
    -prune \
    -exec rm -rf {} \; \
    2>/dev/null || true

find "${APP_DST}/app" \
    -type f \
    -name '*.pyc' \
    -delete \
    2>/dev/null || true


echo "Código instalado em $APP_DST"


# ================================================================
# DADOS PERSISTENTES
# ================================================================

log "DADOS PERSISTENTES"


# ------------------------------------------------
# Banco antigo na árvore do projeto
# ------------------------------------------------

if [ ! -f "$DATABASE" ] &&
   [ -f "${SCRIPT_DIR}/data/wolf-portal.db" ]; then

    echo "Migrando banco existente..."

    cp \
        "${SCRIPT_DIR}/data/wolf-portal.db" \
        "$DATABASE"
fi


# ------------------------------------------------
# Estado antigo do Telegram
# ------------------------------------------------

if [ ! -f "$TELEGRAM_STATE" ] &&
   [ -f "${SCRIPT_DIR}/data/telegram-bot-state.json" ]; then

    echo "Migrando estado existente do Telegram..."

    cp \
        "${SCRIPT_DIR}/data/telegram-bot-state.json" \
        "$TELEGRAM_STATE"
fi


# ------------------------------------------------
# Compatibilidade com configuração antiga
# ------------------------------------------------

if [ ! -f "$TELEGRAM_CONFIG" ] &&
   [ -f "${SCRIPT_DIR}/app/bot_telegram.conf" ]; then

    echo "Migrando configuração Telegram antiga..."

    cp \
        "${SCRIPT_DIR}/app/bot_telegram.conf" \
        "$TELEGRAM_CONFIG"
fi


# ------------------------------------------------
# Configuração Telegram via ambiente
# ------------------------------------------------

if [ ! -f "$TELEGRAM_CONFIG" ]; then

    if [ -n "${WOLF_PORTAL_TELEGRAM_TOKEN:-}" ] &&
       [ -n "${WOLF_PORTAL_TELEGRAM_ADMIN_ID:-}" ]; then

        cat > "$TELEGRAM_CONFIG" <<EOF
TOKEN="${WOLF_PORTAL_TELEGRAM_TOKEN}"
ADMIN_ID="${WOLF_PORTAL_TELEGRAM_ADMIN_ID}"
EOF

        echo "Configuração Telegram criada."

    else

        echo
        echo "Telegram ainda não configurado."
        echo
        echo "Crie:"
        echo
        echo "  $TELEGRAM_CONFIG"
        echo
        echo "com:"
        echo
        echo '  TOKEN="..."'
        echo '  ADMIN_ID="..."'
    fi
fi


# ------------------------------------------------
# Permissões
# ------------------------------------------------

[ ! -f "$DATABASE" ] || \
    chmod 600 "$DATABASE"

[ ! -f "$TELEGRAM_STATE" ] || \
    chmod 600 "$TELEGRAM_STATE"

[ ! -f "$TELEGRAM_CONFIG" ] || \
    chmod 600 "$TELEGRAM_CONFIG"


# ================================================================
# INICIALIZA BANCO
# ================================================================

log "INICIALIZANDO BANCO"

PYTHONPATH="$APP_DST" \
WOLF_PORTAL_DATABASE="$DATABASE" \
python3 - <<'PY'
from app.database import initialize_database

initialize_database()

print("Banco inicializado.")
PY

chmod 600 "$DATABASE"


# ================================================================
# DESCOBRE IP DA LAN
# ================================================================

log "CONFIGURANDO DNS DO PORTAL"


# ------------------------------------------------
# Algumas versões/configurações retornam:
#
#     10.0.69.1
#
# outras podem retornar:
#
#     10.0.69.1/24
#
# O dnsmasq necessita somente do endereço IP.
# ------------------------------------------------

LAN_IP_RAW="$(
    uci -q get network.lan.ipaddr ||
    true
)"

[ -n "$LAN_IP_RAW" ] || \
    fail "Não foi possível descobrir network.lan.ipaddr."


# Remove eventual prefixo CIDR.
LAN_IP="${LAN_IP_RAW%%/*}"


[ -n "$LAN_IP" ] || \
    fail "Endereço IPv4 da LAN inválido: $LAN_IP_RAW"


# Validação básica para impedir que uma string inesperada
# seja escrita na configuração do dnsmasq.
case "$LAN_IP" in

    *[!0-9.]*)

        fail \
            "Endereço IPv4 LAN inválido: $LAN_IP"
        ;;

esac


echo "IP LAN detectado: $LAN_IP_RAW"
echo "IP usado pelo portal: $LAN_IP"


# ================================================================
# STATUS.CLIENT
# ================================================================

CURRENT_ADDRESSES="$(
    uci -q get dhcp.@dnsmasq[0].address ||
    true
)"


# ------------------------------------------------
# Remove somente entradas antigas do Wolf Portal.
#
# Não mexe em outras entradas address= existentes.
# ------------------------------------------------

for ENTRY in $CURRENT_ADDRESSES; do

    case "$ENTRY" in

        /status.client/*)

            uci -q del_list \
                dhcp.@dnsmasq[0].address="$ENTRY" \
                2>/dev/null || true
            ;;

    esac
done


# ------------------------------------------------
# Adiciona a entrada correta.
# ------------------------------------------------

uci add_list \
    dhcp.@dnsmasq[0].address="/${PORTAL_HOSTNAME}/${LAN_IP}"

uci commit dhcp

/etc/init.d/dnsmasq restart


echo "${PORTAL_HOSTNAME} -> ${LAN_IP}"


# ================================================================
# REMOVE DHCP OPTION 114 LEGADA
# ================================================================

OLD_FORCE_OPTIONS="$(
    uci -q get dhcp.lan.dhcp_option_force ||
    true
)"


for ENTRY in $OLD_FORCE_OPTIONS; do

    case "$ENTRY" in

        114,http://status.client|\
        114,http://status.client/|\
        114,http://status.client:81|\
        114,http://status.client:81/)

            uci -q del_list \
                dhcp.lan.dhcp_option_force="$ENTRY" \
                2>/dev/null || \
            uci -q delete \
                dhcp.lan.dhcp_option_force \
                2>/dev/null || true
            ;;

    esac
done


uci commit dhcp


# ================================================================
# INIT SCRIPT
# ================================================================

log "INSTALANDO SERVICO"

cp \
    "${SCRIPT_DIR}/openwrt/wolf-portal.init" \
    "$INIT_DST"

chmod 755 "$INIT_DST"

sh -n "$INIT_DST"

echo "Init script: OK"


# ================================================================
# SYSUPGRADE
# ================================================================

log "CONFIGURANDO SYSUPGRADE"

touch "$SYSUPGRADE_CONF"

if ! grep -qxF \
    '/etc/wolf-portal/' \
    "$SYSUPGRADE_CONF" \
    2>/dev/null; then

    echo '/etc/wolf-portal/' \
        >> "$SYSUPGRADE_CONF"
fi


echo "/etc/wolf-portal/ será preservado."


# ================================================================
# FW4
# ================================================================

log "VALIDANDO FIREWALL4"

fw4 check

echo "fw4: OK"


# ================================================================
# HABILITA E INICIA
# ================================================================

log "INICIANDO WOLF PORTAL"

"$INIT_DST" enable

"$INIT_DST" start

sleep 4


# ================================================================
# HEALTHCHECK
# ================================================================

log "VERIFICANDO PORTAL"

python3 - <<'PY'
import json
import urllib.request


url = "http://127.0.0.1:81/health"


with urllib.request.urlopen(
    url,
    timeout=5,
) as response:

    data = json.loads(
        response.read().decode(
            "utf-8"
        )
    )

    if data.get("status") != "ok":
        raise SystemExit(
            "Healthcheck retornou estado inválido."
        )


print("Portal HTTP: OK")
PY


# ================================================================
# VERIFICA DNS
# ================================================================

log "VERIFICANDO DNS DO PORTAL"

CONFIGURED_ADDRESS="$(
    uci -q get dhcp.@dnsmasq[0].address ||
    true
)"


case " $CONFIGURED_ADDRESS " in

    *" /${PORTAL_HOSTNAME}/${LAN_IP} "*)

        echo \
            "${PORTAL_HOSTNAME}: configuração DNS OK"
        ;;

    *)

        fail \
            "Entrada DNS de ${PORTAL_HOSTNAME} não foi encontrada."
        ;;

esac


# ================================================================
# PROCD
# ================================================================

if command -v ubus >/dev/null 2>&1; then

    echo
    echo "Estado procd:"
    echo

    ubus call service list \
        '{"name":"wolf-portal"}' \
        2>/dev/null || true
fi


# ================================================================
# FINAL
# ================================================================

log "INSTALACAO CONCLUIDA"

echo
echo "Wolf Portal instalado com sucesso."
echo
echo "Portal:"
echo "  http://${PORTAL_HOSTNAME}:81/"
echo
echo "Dados:"
echo "  $DATA_DIR"
echo
echo "Configuração Telegram:"
echo "  $TELEGRAM_CONFIG"
echo
echo "Serviço:"
echo "  $INIT_DST"
echo