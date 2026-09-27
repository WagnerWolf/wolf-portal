from __future__ import annotations
from app.network_monitor import NetworkMonitor
import html
import json
import os
import re
import signal
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.device_access_service import (
    authorize_device,
    block_device,
)
from app.device_manager import (
    get_device,
    list_devices,
    rename_device,
)
from app.firewall_manager import PROTECTED_ADMIN_MAC


# ================================================================
# CONFIGURAÇÃO
# ================================================================
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = PROJECT_DIR / "data"


CONFIG_PATH = Path(
    os.environ.get(
        "WOLF_PORTAL_TELEGRAM_CONFIG",
        str(APP_DIR / "bot_telegram.conf"),
    )
)

STATE_PATH = Path(
    os.environ.get(
        "WOLF_PORTAL_TELEGRAM_STATE",
        str(DATA_DIR / "telegram-bot-state.json"),
    )
)

HOST_NAME = os.uname().nodename

POLL_TIMEOUT = 5

MAC_PATTERN = re.compile(
    r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$",
    re.IGNORECASE,
)

BOT_COMMANDS = [
    {"command": "status", "description": "Resumo do Wolf Portal"},
    {"command": "autorizados", "description": "Listar dispositivos autorizados"},
    {"command": "pendentes", "description": "Listar dispositivos pendentes"},
    {"command": "liberar", "description": "Autorizar um dispositivo por MAC"},
    {"command": "bloquear", "description": "Bloquear um dispositivo por MAC"},
    {"command": "nomear", "description": "Definir o nome de um dispositivo"},
    {"command": "ajuda", "description": "Mostrar comandos disponíveis"},
    {"command": "conectados","description": "Listar dispositivos conectados"},
]

RUNNING = True


# ================================================================
# REDE - PREFERIR IPv4
# ================================================================
# O NanoPi possui resolução IPv6, mas a rota IPv6 até o Telegram
# não está funcional. urllib usa AF_UNSPEC e pode esperar dezenas
# de segundos antes de cair para IPv4. Neste processo, requisições
# sem família explícita usam IPv4 diretamente.

_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def _getaddrinfo_prefer_ipv4(
    host,
    port,
    family=0,
    type=0,
    proto=0,
    flags=0,
):
    if family in (0, socket.AF_UNSPEC):
        family = socket.AF_INET

    return _ORIGINAL_GETADDRINFO(
        host, port, family, type, proto, flags
    )


socket.getaddrinfo = _getaddrinfo_prefer_ipv4


# ================================================================
# UTILITÁRIOS
# ================================================================

def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[{timestamp}] {message}",
        flush=True,
    )


def normalize_mac(mac: str) -> str:
    return mac.strip().lower()


def valid_mac(mac: str) -> bool:
    return bool(
        MAC_PATTERN.fullmatch(
            normalize_mac(mac)
        )
    )


def load_shell_config(
    path: Path,
) -> dict[str, str]:
    """
    Lê um arquivo simples no formato:

        TOKEN='...'
        ADMIN_ID='...'

    Não executa o arquivo como shell.
    """

    if not path.exists():
        raise RuntimeError(
            f"Configuração não encontrada: {path}"
        )

    config: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split(
            "=",
            1,
        )

        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        config[key] = value

    return config


CONFIG = load_shell_config(
    CONFIG_PATH
)

TOKEN = CONFIG.get(
    "TOKEN",
    "",
).strip()

ADMIN_ID = CONFIG.get(
    "ADMIN_ID",
    "",
).strip()

if not TOKEN:
    raise RuntimeError(
        "TOKEN não configurado."
    )

if not ADMIN_ID:
    raise RuntimeError(
        "ADMIN_ID não configurado."
    )

API_URL = (
    f"https://api.telegram.org/bot{TOKEN}"
)


CONNECTED_NEIGHBOR_STATES = {
    "REACHABLE",
    "STALE",
    "DELAY",
    "PROBE",
}


def get_connected_devices() -> list[dict]:
    """
    Retorna uma fotografia dos dispositivos atualmente
    conhecidos na LAN através da tabela neighbor do kernel.

    Para esta consulta consideramos ativos:

        REACHABLE
        STALE
        DELAY
        PROBE

    FAILED e INCOMPLETE não são considerados conectados.
    """

    monitor = NetworkMonitor()

    devices_by_mac: dict[str, dict] = {}

    # Preferência caso o mesmo MAC apareça mais de uma vez.
    state_priority = {
        "REACHABLE": 4,
        "DELAY": 3,
        "PROBE": 2,
        "STALE": 1,
    }

    for neighbor in monitor.get_neighbors():

        if not neighbor.mac:
            continue

        state = neighbor.state.upper()

        if state not in CONNECTED_NEIGHBOR_STATES:
            continue

        mac = normalize_mac(
            neighbor.mac
        )

        previous = devices_by_mac.get(
            mac
        )

        if previous is not None:

            if (
                state_priority.get(
                    previous["neighbor_state"],
                    0,
                )
                >=
                state_priority.get(
                    state,
                    0,
                )
            ):
                continue

        devices_by_mac[mac] = {
            "mac": mac,
            "ip": neighbor.ip,
            "neighbor_state": state,
            "hostname": None,
            "status": None,
        }

    if not devices_by_mac:
        return []

    macs = list(
        devices_by_mac.keys()
    )

    placeholders = ",".join(
        "?"
        for _ in macs
    )

    with get_connection() as conn:

        rows = conn.execute(
            f"""
            SELECT
                mac,
                hostname,
                status
            FROM devices
            WHERE lower(mac) IN ({placeholders})
            """,
            macs,
        ).fetchall()

    for row in rows:

        mac = normalize_mac(
            row["mac"]
        )

        device = devices_by_mac.get(
            mac
        )

        if device is None:
            continue

        device["hostname"] = (
            row["hostname"]
        )

        device["status"] = (
            row["status"]
        )

    devices = list(
        devices_by_mac.values()
    )

    devices.sort(
        key=lambda device: (
            (
                device["hostname"]
                or ""
            ).lower(),
            device["mac"],
        )
    )

    return devices

# ================================================================
# ESTADO PERSISTENTE DO BOT
# ================================================================

def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}

    try:
        return json.loads(
            STATE_PATH.read_text(
                encoding="utf-8"
            )
        )

    except Exception as exc:
        log(
            "Aviso: não foi possível ler "
            f"o estado anterior: {exc}"
        )

        return {}


def write_state(
    state: dict[str, Any],
) -> None:

    STATE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = STATE_PATH.with_suffix(
        ".tmp"
    )

    temp.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    temp.replace(
        STATE_PATH
    )


STATE = read_state()


# ================================================================
# TELEGRAM API
# ================================================================

class TelegramError(RuntimeError):
    pass


def telegram_request(
    method: str,
    parameters: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:

    params = parameters or {}

    encoded = urllib.parse.urlencode(
        params
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        f"{API_URL}/{method}",
        data=encoded,
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except Exception as exc:
        raise TelegramError(
            f"Falha em {method}: {exc}"
        ) from exc

    if not payload.get(
        "ok",
        False,
    ):
        raise TelegramError(
            f"Telegram retornou erro em "
            f"{method}: {payload}"
        )

    return payload.get(
        "result"
    )


def send_message(
    text: str,
    *,
    reply_markup: dict | None = None,
) -> Any:

    parameters: dict[str, Any] = {
        "chat_id": ADMIN_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }

    if reply_markup is not None:
        parameters[
            "reply_markup"
        ] = json.dumps(
            reply_markup
        )

    return telegram_request(
        "sendMessage",
        parameters,
    )


def edit_message(
    chat_id: str | int,
    message_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
) -> None:

    parameters: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }

    if reply_markup is not None:
        parameters["reply_markup"] = json.dumps(
            reply_markup
        )

    telegram_request(
        "editMessageText",
        parameters,
    )


def answer_callback(
    callback_id: str,
    text: str = "",
) -> None:

    telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
        },
    )


def configure_bot_commands() -> None:
    """Atualiza o menu nativo de comandos do Telegram."""
    telegram_request(
        "setMyCommands",
        {
            "commands": json.dumps(
                BOT_COMMANDS,
                ensure_ascii=False,
            ),
        },
    )


# ================================================================
# BANCO / CONSULTAS
# ================================================================

def get_status_counts() -> dict[str, int]:

    counts = {
        "PENDING": 0,
        "AUTHORIZED": 0,
        "BLOCKED": 0,
        "DISABLED": 0,
    }

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM devices
            GROUP BY status
            """
        ).fetchall()

    for row in rows:
        counts[
            str(row["status"])
        ] = int(
            row["total"]
        )

    return counts


def get_pending_devices():

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM devices
            WHERE status = 'PENDING'
            ORDER BY last_seen DESC
            """
        ).fetchall()


def get_device_detected_events(
    after_id: int,
):
    """
    Retorna novos eventos DEVICE_DETECTED posteriores ao cursor.

    Esses eventos são a via de notificação para equipamentos que
    podem não possuir navegador/captive portal, como TVs, consoles
    e dispositivos IoT.
    """

    with get_connection() as conn:

        return conn.execute(
            """
            SELECT
                events.id AS event_id,
                events.timestamp,
                devices.id AS device_id,
                devices.mac,
                devices.ip,
                devices.hostname,
                devices.status
            FROM events
            JOIN devices
                ON devices.id = events.device_id
            WHERE
                events.event_type = 'DEVICE_DETECTED'
                AND events.id > ?
            ORDER BY events.id ASC
            """,
            (
                after_id,
            ),
        ).fetchall()


def current_max_device_detected_id() -> int:

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT COALESCE(MAX(id), 0) AS max_id
            FROM events
            WHERE event_type = 'DEVICE_DETECTED'
            """
        ).fetchone()

    return int(
        row["max_id"]
    )


def get_access_request_events(
    after_id: int,
):

    with get_connection() as conn:

        return conn.execute(
            """
            SELECT
                events.id AS event_id,
                events.timestamp,
                devices.id AS device_id,
                devices.mac,
                devices.ip,
                devices.hostname,
                devices.status
            FROM events
            JOIN devices
                ON devices.id = events.device_id
            WHERE
                events.event_type = 'ACCESS_REQUESTED'
                AND events.id > ?
            ORDER BY events.id ASC
            """,
            (
                after_id,
            ),
        ).fetchall()


def current_max_access_request_id() -> int:

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT COALESCE(MAX(id), 0) AS max_id
            FROM events
            WHERE event_type = 'ACCESS_REQUESTED'
            """
        ).fetchone()

    return int(
        row["max_id"]
    )


# ================================================================
# FORMATAÇÃO
# ================================================================

def device_display_name(
    device,
) -> str:

    if device is None:
        return "Desconhecido"

    name = device[
        "hostname"
    ]

    if not name:
        return "Sem nome"

    return str(
        name
    )


def build_detection_message(
    row,
) -> str:

    name = html.escape(
        row["hostname"]
        or "Sem nome"
    )

    mac = html.escape(
        row["mac"]
    )

    ip = html.escape(
        row["ip"]
        or "Desconhecido"
    )

    return (
        "🐺 <b>Novo dispositivo detectado</b>\n\n"
        f"👤 <b>Nome:</b> {name}\n"
        f"📱 <b>MAC:</b> <code>{mac}</code>\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"📌 <b>Status:</b> {html.escape(row['status'])}\n\n"
        "O equipamento entrou na rede e está aguardando decisão.\n"
        "Isso também funciona para TVs, consoles e dispositivos "
        "sem navegador.\n\n"
        "Escolha uma ação:"
    )


def build_request_message(
    row,
) -> str:

    name = html.escape(
        row["hostname"]
        or "Sem nome"
    )

    mac = html.escape(
        row["mac"]
    )

    ip = html.escape(
        row["ip"]
        or "Desconhecido"
    )

    return (
        "🐺 <b>Nova solicitação de acesso</b>\n\n"
        f"👤 <b>Nome:</b> {name}\n"
        f"📱 <b>MAC:</b> <code>{mac}</code>\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"📌 <b>Status:</b> {html.escape(row['status'])}\n\n"
        "Escolha uma ação:"
    )


def request_keyboard(
    mac: str,
) -> dict:

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Autorizar",
                    "callback_data": (
                        f"wolf:allow:{mac}"
                    ),
                },
                {
                    "text": "⛔ Bloquear",
                    "callback_data": (
                        f"wolf:block:{mac}"
                    ),
                },
            ],
        ],
    }


def rename_keyboard(
    mac: str,
) -> dict:
    """Botão exibido depois que um dispositivo é autorizado."""

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✏️ Definir nome",
                    "callback_data": (
                        f"wolf:rename:{mac}"
                    ),
                },
            ],
        ],
    }


def rename_force_reply() -> dict:
    """Solicita o nome usando a resposta nativa do Telegram."""

    return {
        "force_reply": True,
        "selective": True,
        "input_field_placeholder": "Ex.: TV Sala, Celular Wagner...",
    }


# ================================================================
# NOTIFICAÇÃO DE NOVOS DISPOSITIVOS
# ================================================================

def initialize_device_detection_cursor() -> None:
    """
    Na primeira inicialização não envia todos os DEVICE_DETECTED
    históricos existentes.

    Depois disso, cada novo dispositivo descoberto pelo monitor
    gera uma notificação automática no Telegram.
    """

    if (
        "last_device_detected_event_id"
        in STATE
    ):
        return

    STATE[
        "last_device_detected_event_id"
    ] = current_max_device_detected_id()

    write_state(
        STATE
    )

    log(
        "Cursor inicial de dispositivos detectados definido em "
        f"{STATE['last_device_detected_event_id']}."
    )


def process_new_device_detections() -> None:

    last_id = int(
        STATE.get(
            "last_device_detected_event_id",
            0,
        )
    )

    rows = get_device_detected_events(
        last_id
    )

    for row in rows:

        event_id = int(
            row["event_id"]
        )

        # O evento pode ter sido criado e o administrador ter tomado
        # uma decisão antes de o bot processá-lo. Nesse caso apenas
        # consumimos o evento para não enviar aviso obsoleto.
        if row["status"] != "PENDING":

            STATE[
                "last_device_detected_event_id"
            ] = event_id

            write_state(
                STATE
            )

            continue

        log(
            "Novo dispositivo detectado: "
            f"{row['mac']} {row['ip']}"
        )

        send_message(
            build_detection_message(
                row
            ),
            reply_markup=request_keyboard(
                row["mac"]
            ),
        )

        # Avança somente após envio bem-sucedido. Se o Telegram estiver
        # indisponível, o evento será tentado novamente no próximo ciclo.
        STATE[
            "last_device_detected_event_id"
        ] = event_id

        write_state(
            STATE
        )


# ================================================================
# NOTIFICAÇÃO DE NOVOS PEDIDOS DO PORTAL
# ================================================================

def initialize_request_cursor() -> None:
    """
    Na primeira inicialização não despeja no Telegram todos
    os pedidos históricos já existentes.

    A partir daí o último ID processado fica persistido.
    """

    if (
        "last_access_request_event_id"
        in STATE
    ):
        return

    STATE[
        "last_access_request_event_id"
    ] = current_max_access_request_id()

    write_state(
        STATE
    )

    log(
        "Cursor inicial dos pedidos definido em "
        f"{STATE['last_access_request_event_id']}."
    )


def process_new_access_requests() -> None:

    last_id = int(
        STATE.get(
            "last_access_request_event_id",
            0,
        )
    )

    rows = get_access_request_events(
        last_id
    )

    for row in rows:

        event_id = int(
            row["event_id"]
        )

        # Se a situação do aparelho já mudou,
        # apenas consumimos o evento antigo.
        if row["status"] != "PENDING":

            STATE[
                "last_access_request_event_id"
            ] = event_id

            write_state(
                STATE
            )

            continue

        log(
            "Solicitação de acesso detectada: "
            f"{row['mac']} {row['ip']}"
        )

        send_message(
            build_request_message(
                row
            ),
            reply_markup=request_keyboard(
                row["mac"]
            ),
        )

        # Avança somente depois do envio bem-sucedido.
        STATE[
            "last_access_request_event_id"
        ] = event_id

        write_state(
            STATE
        )


# ================================================================
# AÇÕES
# ================================================================

def authorize_mac(
    mac: str,
    *,
    name: str | None = None,
    source: str = "telegram",
):

    mac = normalize_mac(
        mac
    )

    if not valid_mac(
        mac
    ):
        raise ValueError(
            "MAC inválido."
        )

    device = get_device(
        mac
    )

    if device is None:
        raise ValueError(
            f"Dispositivo não encontrado: {mac}"
        )

    if name is not None:
        clean_name = name.strip()

        if clean_name:
            rename_device(
                mac,
                clean_name,
                source=source,
            )

    device = authorize_device(
        mac,
        source=source,
    )

    return device


def block_mac(
    mac: str,
    *,
    source: str = "telegram",
):

    mac = normalize_mac(
        mac
    )

    if not valid_mac(
        mac
    ):
        raise ValueError(
            "MAC inválido."
        )

    if mac == normalize_mac(
        PROTECTED_ADMIN_MAC
    ):
        raise ValueError(
            "O dispositivo administrativo "
            "protegido não pode ser bloqueado."
        )

    device = get_device(
        mac
    )

    if device is None:
        raise ValueError(
            f"Dispositivo não encontrado: {mac}"
        )

    return block_device(
        mac,
        source=source,
    )


def rename_mac(
    mac: str,
    name: str,
    *,
    source: str = "telegram",
):
    mac = normalize_mac(mac)
    clean_name = name.strip()

    if not valid_mac(mac):
        raise ValueError("MAC inválido.")

    if not clean_name:
        raise ValueError("O nome não pode ficar vazio.")

    if len(clean_name) > 80:
        raise ValueError("O nome deve ter no máximo 80 caracteres.")

    device = get_device(mac)

    if device is None:
        raise ValueError(
            f"Dispositivo não encontrado: {mac}"
        )

    return rename_device(
        mac,
        clean_name,
        source=source,
    )


def remember_rename_prompt(
    prompt_message_id: int,
    mac: str,
) -> None:
    pending = STATE.setdefault(
        "pending_rename_replies",
        {},
    )

    pending[str(prompt_message_id)] = normalize_mac(mac)
    write_state(STATE)


def pop_rename_prompt(
    prompt_message_id: int,
) -> str | None:
    pending = STATE.get(
        "pending_rename_replies",
        {},
    )

    if not isinstance(pending, dict):
        STATE["pending_rename_replies"] = {}
        write_state(STATE)
        return None

    mac = pending.pop(
        str(prompt_message_id),
        None,
    )

    if mac is not None:
        write_state(STATE)

    return mac


def process_rename_reply(
    message: dict[str, Any],
    text: str,
) -> bool:
    """
    Processa uma resposta ao prompt criado pelo botão
    "Definir nome". Retorna True quando a mensagem pertencia
    a um fluxo de renomeação.
    """

    reply_to = message.get(
        "reply_to_message",
        {},
    )

    prompt_message_id = reply_to.get(
        "message_id"
    )

    if prompt_message_id is None:
        return False

    pending = STATE.get(
        "pending_rename_replies",
        {},
    )

    if not isinstance(pending, dict):
        return False

    mac = pending.get(
        str(prompt_message_id)
    )

    if mac is None:
        return False

    try:
        device = rename_mac(
            mac,
            text,
        )

    except Exception as exc:
        send_message(
            "❌ Falha ao definir nome:\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )
        return True

    pop_rename_prompt(
        int(prompt_message_id)
    )

    send_message(
        "✏️ <b>Nome atualizado</b>\n\n"
        f"Nome: <b>{html.escape(device['hostname'] or 'Sem nome')}</b>\n"
        f"MAC: <code>{html.escape(device['mac'])}</code>\n"
        f"IP: <code>{html.escape(device['ip'] or '-')}</code>"
    )

    return True


# ================================================================
# COMANDOS
# ================================================================

def command_help() -> None:

    send_message(
        f"🐺 <b>Wolf Portal — {html.escape(HOST_NAME)}</b>\n\n"
        "Comandos disponíveis:\n\n"
        "✅ <code>/liberar MAC Nome</code>\n"
        "⛔ <code>/bloquear MAC</code>\n"
        "✏️ <code>/nomear MAC Nome</code>\n"
        "⏳ <code>/pendentes</code>\n"
        "📋 <code>/autorizados</code>\n"
        "ℹ️ <code>/status</code>\n"
        "❓ <code>/ajuda</code>\n"
        "📶 <code>/conectados</code>"
    )


def command_status() -> None:

    counts = get_status_counts()

    connected = get_connected_devices()

    send_message(
        f"ℹ️ <b>Status {html.escape(HOST_NAME)}</b>\n\n"
        f"✅ Autorizados: {counts.get('AUTHORIZED', 0)}\n"
        f"⏳ Pendentes: {counts.get('PENDING', 0)}\n"
        f"⛔ Bloqueados: {counts.get('BLOCKED', 0)}\n"
        f"🚫 Desativados: {counts.get('DISABLED', 0)}\n"
        f"📶 Conectados agora: {len(connected)}"
    )


def command_connected() -> None:

    devices = get_connected_devices()

    if not devices:

        send_message(
            "📶 Nenhum dispositivo conectado foi detectado."
        )

        return

    lines = [
        "📶 <b>Dispositivos conectados</b>",
        "",
        f"Total: <b>{len(devices)}</b>",
        "",
    ]

    status_icons = {
        "AUTHORIZED": "✅",
        "PENDING": "⏳",
        "BLOCKED": "⛔",
        "DISABLED": "🚫",
    }

    for device in devices:

        name = html.escape(
            device["hostname"]
            or "Sem nome"
        )

        mac = html.escape(
            device["mac"]
        )

        ip = html.escape(
            device["ip"]
            or "-"
        )

        status = (
            device["status"]
            or "NÃO CADASTRADO"
        )

        icon = status_icons.get(
            status,
            "❔",
        )

        lines.extend(
            [
                f"👤 <b>{name}</b>",
                f"<code>{mac}</code>",
                f"IP: <code>{ip}</code>",
                (
                    f"Status: {icon} "
                    f"{html.escape(status)}"
                ),
                "",
            ]
        )

    send_message(
        "\n".join(
            lines
        )
    )


def command_authorized() -> None:

    rows = [
        row
        for row in list_devices()
        if row["status"] == "AUTHORIZED"
    ]

    if not rows:

        send_message(
            "📋 Nenhum dispositivo autorizado."
        )

        return

    lines = [
        "📋 <b>Dispositivos autorizados</b>",
        "",
    ]

    for row in rows:

        name = html.escape(
            row["hostname"]
            or "Sem nome"
        )

        mac = html.escape(
            row["mac"]
        )

        ip = html.escape(
            row["ip"]
            or "-"
        )

        lines.extend(
            [
                f"👤 <b>{name}</b>",
                f"<code>{mac}</code>",
                f"IP: <code>{ip}</code>",
                "",
            ]
        )

    send_message(
        "\n".join(
            lines
        )
    )


def command_pending() -> None:

    rows = get_pending_devices()

    if not rows:

        send_message(
            "✅ Nenhum dispositivo pendente."
        )

        return

    lines = [
        "⏳ <b>Dispositivos pendentes</b>",
        "",
    ]

    for row in rows:

        name = html.escape(
            row["hostname"]
            or "Sem nome"
        )

        mac = html.escape(
            row["mac"]
        )

        ip = html.escape(
            row["ip"]
            or "-"
        )

        lines.extend(
            [
                f"👤 {name}",
                f"<code>{mac}</code>",
                f"IP: <code>{ip}</code>",
                "",
            ]
        )

    send_message(
        "\n".join(
            lines
        )
    )


def command_allow(
    text: str,
) -> None:

    parts = text.strip().split(
        maxsplit=2
    )

    if len(parts) < 2:

        send_message(
            "⚠️ Use:\n\n"
            "<code>/liberar MAC Nome</code>"
        )

        return

    mac = normalize_mac(
        parts[1]
    )

    name = (
        parts[2]
        if len(parts) >= 3
        else None
    )

    try:

        device = authorize_mac(
            mac,
            name=name,
        )

    except Exception as exc:

        send_message(
            "❌ Falha ao autorizar:\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )

        return

    send_message(
        "✅ <b>Acesso autorizado</b>\n\n"
        f"MAC: <code>{html.escape(device['mac'])}</code>\n"
        f"IP: <code>{html.escape(device['ip'] or '-')}</code>\n"
        f"Nome: {html.escape(device['hostname'] or 'Sem nome')}",
        reply_markup=rename_keyboard(
            device["mac"]
        ),
    )


def command_block(
    text: str,
) -> None:

    parts = text.strip().split()

    if len(parts) < 2:

        send_message(
            "⚠️ Use:\n\n"
            "<code>/bloquear MAC</code>"
        )

        return

    mac = normalize_mac(
        parts[1]
    )

    try:

        device = block_mac(
            mac
        )

    except Exception as exc:

        send_message(
            "❌ Falha ao bloquear:\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )

        return

    send_message(
        "⛔ <b>Acesso bloqueado</b>\n\n"
        f"MAC: <code>{html.escape(device['mac'])}</code>\n"
        f"IP: <code>{html.escape(device['ip'] or '-')}</code>"
    )


def command_rename(
    text: str,
) -> None:

    parts = text.strip().split(
        maxsplit=2
    )

    if len(parts) < 3:
        send_message(
            "⚠️ Use:\n\n"
            "<code>/nomear MAC Nome</code>"
        )
        return

    mac = normalize_mac(
        parts[1]
    )
    name = parts[2]

    try:
        device = rename_mac(
            mac,
            name,
        )

    except Exception as exc:
        send_message(
            "❌ Falha ao definir nome:\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )
        return

    send_message(
        "✏️ <b>Nome atualizado</b>\n\n"
        f"Nome: <b>{html.escape(device['hostname'] or 'Sem nome')}</b>\n"
        f"MAC: <code>{html.escape(device['mac'])}</code>\n"
        f"IP: <code>{html.escape(device['ip'] or '-')}</code>"
    )


def process_message(
    message: dict[str, Any],
) -> None:

    chat = message.get(
        "chat",
        {}
    )

    chat_id = str(
        chat.get(
            "id",
            "",
        )
    )

    if chat_id != ADMIN_ID:

        log(
            "Mensagem ignorada de chat não autorizado: "
            f"{chat_id}"
        )

        return

    text = str(
        message.get(
            "text",
            "",
        )
    ).strip()

    if not text:
        return

    # Resposta direta ao prompt "Definir nome".
    if process_rename_reply(
        message,
        text,
    ):
        return

    # Remove @nome_do_bot de comandos.
    command = text.split(
        None,
        1,
    )[0]

    command_base = command.split(
        "@",
        1,
    )[0].lower()

    remainder = ""

    if " " in text:
        remainder = text.split(
            " ",
            1,
        )[1]

    normalized_text = (
        command_base
        + (
            f" {remainder}"
            if remainder
            else ""
        )
    )

    if command_base in (
        "/start",
        "/ajuda",
        "/help",
    ):
        command_help()

    elif command_base == "/status":
        command_status()

    elif command_base == "/conectados":
        command_connected()

    elif command_base == "/autorizados":
        command_authorized()

    elif command_base == "/pendentes":
        command_pending()

    elif command_base == "/liberar":
        command_allow(
            normalized_text
        )

    elif command_base == "/bloquear":
        command_block(
            normalized_text
        )

    elif command_base == "/nomear":
        command_rename(
            normalized_text
        )

    elif command_base.startswith("/"):
        send_message(
            "❓ Comando desconhecido. Use <code>/ajuda</code>."
        )


# ================================================================
# CALLBACKS DOS BOTÕES
# ================================================================

def process_callback(
    callback: dict[str, Any],
) -> None:

    callback_id = str(
        callback.get(
            "id",
            "",
        )
    )

    from_user = callback.get(
        "from",
        {}
    )

    user_id = str(
        from_user.get(
            "id",
            "",
        )
    )

    if user_id != ADMIN_ID:

        answer_callback(
            callback_id,
            "Não autorizado.",
        )

        return

    data = str(
        callback.get(
            "data",
            "",
        )
    )

    message = callback.get(
        "message",
        {}
    )

    chat_id = message.get(
        "chat",
        {},
    ).get(
        "id"
    )

    message_id = message.get(
        "message_id"
    )

    try:

        namespace, action_name, mac = data.split(
            ":",
            2,
        )

    except ValueError:

        answer_callback(
            callback_id,
            "Comando inválido.",
        )

        return

    action = f"{namespace}:{action_name}"

    mac = normalize_mac(
        mac
    )

    try:

        if action == "wolf:allow":

            device = authorize_mac(
                mac
            )

            answer_callback(
                callback_id,
                "Acesso autorizado.",
            )

            if (
                chat_id is not None
                and message_id is not None
            ):
                edit_message(
                    chat_id,
                    int(message_id),
                    (
                        "✅ <b>Solicitação autorizada</b>\n\n"
                        f"MAC: <code>{html.escape(device['mac'])}</code>\n"
                        f"IP: <code>{html.escape(device['ip'] or '-')}</code>\n"
                        f"Nome: {html.escape(device['hostname'] or 'Sem nome')}"
                    ),
                    reply_markup=rename_keyboard(
                        device["mac"]
                    ),
                )

        elif action == "wolf:rename":

            device = get_device(
                mac
            )

            if device is None:
                raise ValueError(
                    f"Dispositivo não encontrado: {mac}"
                )

            prompt = send_message(
                "✏️ <b>Definir nome do dispositivo</b>\n\n"
                f"MAC: <code>{html.escape(mac)}</code>\n\n"
                "Responda a esta mensagem com o nome que deseja usar.",
                reply_markup=rename_force_reply(),
            )

            prompt_message_id = int(
                prompt["message_id"]
            )

            remember_rename_prompt(
                prompt_message_id,
                mac,
            )

            answer_callback(
                callback_id,
                "Envie o nome na resposta.",
            )

        elif action == "wolf:block":

            device = block_mac(
                mac
            )

            answer_callback(
                callback_id,
                "Dispositivo bloqueado.",
            )

            if (
                chat_id is not None
                and message_id is not None
            ):
                edit_message(
                    chat_id,
                    int(message_id),
                    (
                        "⛔ <b>Solicitação bloqueada</b>\n\n"
                        f"MAC: <code>{html.escape(device['mac'])}</code>\n"
                        f"IP: <code>{html.escape(device['ip'] or '-')}</code>"
                    ),
                )

        else:

            answer_callback(
                callback_id,
                "Ação desconhecida.",
            )

    except Exception as exc:

        log(
            "Erro ao processar callback: "
            f"{type(exc).__name__}: {exc}"
        )

        answer_callback(
            callback_id,
            "Falha ao executar ação.",
        )


# ================================================================
# UPDATES
# ================================================================

def process_update(
    update: dict[str, Any],
) -> None:

    if "message" in update:

        process_message(
            update["message"]
        )

    if "callback_query" in update:

        process_callback(
            update["callback_query"]
        )


def poll_updates(
    offset: int,
) -> tuple[list[dict[str, Any]], int]:

    result = telegram_request(
        "getUpdates",
        {
            "offset": offset,
            "timeout": POLL_TIMEOUT,
            "allowed_updates": json.dumps(
                [
                    "message",
                    "callback_query",
                ]
            ),
        },
        timeout=POLL_TIMEOUT + 10,
    )

    updates = list(
        result or []
    )

    new_offset = offset

    for update in updates:

        update_id = int(
            update.get(
                "update_id",
                0,
            )
        )

        if update_id >= new_offset:
            new_offset = (
                update_id + 1
            )

    return (
        updates,
        new_offset,
    )


# ================================================================
# SINAIS / LOOP
# ================================================================

def stop_handler(
    signum,
    frame,
) -> None:

    global RUNNING

    RUNNING = False

    log(
        f"Sinal {signum} recebido. Encerrando."
    )


signal.signal(
    signal.SIGTERM,
    stop_handler,
)

signal.signal(
    signal.SIGINT,
    stop_handler,
)


def main() -> int:

    initialize_device_detection_cursor()
    initialize_request_cursor()

    try:
        configure_bot_commands()
        log("Menu de comandos do Telegram atualizado.")
    except TelegramError as exc:
        log(
            "Aviso: não foi possível atualizar o menu "
            f"do Telegram: {exc}"
        )

    log(
        f"Wolf Portal Telegram Bot iniciado em {HOST_NAME}."
    )

    log(
        f"Administrador Telegram: {ADMIN_ID}"
    )

    offset = int(
        STATE.get(
            "telegram_update_offset",
            0,
        )
    )

    while RUNNING:

        try:
            # Primeiro verifica eventos produzidos localmente.
            # DEVICE_DETECTED cobre inclusive TVs/IoT sem navegador;
            # ACCESS_REQUESTED indica interação explícita com o portal.
            process_new_device_detections()
            process_new_access_requests()

            updates, offset = poll_updates(
                offset
            )

            for update in updates:
                process_update(
                    update
                )

            STATE[
                "telegram_update_offset"
            ] = offset

            write_state(
                STATE
            )

            # Eventos locais podem ter surgido durante o long-poll.
            process_new_device_detections()
            process_new_access_requests()

        except TelegramError as exc:

            log(
                f"Telegram indisponível: {exc}"
            )

            time.sleep(
                5
            )

        except Exception as exc:

            log(
                "Erro no loop principal: "
                f"{type(exc).__name__}: {exc}"
            )

            time.sleep(
                3
            )

    log(
        "Wolf Portal Telegram Bot encerrado."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
