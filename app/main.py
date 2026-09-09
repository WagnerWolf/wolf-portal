from __future__ import annotations

import os

from collections.abc import Callable
from typing import Any

from .database import initialize_database
from .device_access_service import resync_firewall
from .monitor_service import MonitorService


DEFAULT_SCAN_INTERVAL = 3.0


def startup(
    sync_callback: Callable[[], Any] | None = None,
):
    """
    Inicialização operacional do Wolf Portal.

    Ordem obrigatória:

        1. inicializa/verifica o banco;
        2. reconstrói o firewall a partir do banco.

    O banco é a fonte da verdade.

    sync_callback existe principalmente para testes, permitindo
    validar o startup sem tocar no nftables real.
    """

    print(
        "=============================================="
    )
    print(
        " WOLF PORTAL - INICIALIZAÇÃO"
    )
    print(
        "=============================================="
    )

    print()
    print(
        "[1/2] Inicializando banco de dados..."
    )

    initialize_database()

    print(
        "Banco inicializado com sucesso."
    )

    print()
    print(
        "[2/2] Sincronizando firewall com o banco..."
    )

    sync = (
        sync_callback
        or resync_firewall
    )

    result = sync()

    print(
        "Firewall sincronizado com sucesso."
    )

    print()
    print(
        "=============================================="
    )
    print(
        " WOLF PORTAL INICIALIZADO"
    )
    print(
        "=============================================="
    )

    return result


# ====================================================================
# CONFIGURAÇÃO
# ====================================================================

def get_scan_interval() -> float:
    """
    Retorna o intervalo entre ciclos de descoberta.

    Pode ser configurado através de:

        WOLF_PORTAL_SCAN_INTERVAL

    Padrão:

        3 segundos
    """

    raw_value = os.environ.get(
        "WOLF_PORTAL_SCAN_INTERVAL",
        str(DEFAULT_SCAN_INTERVAL),
    )

    try:
        value = float(
            raw_value
        )

    except ValueError as exc:
        raise ValueError(
            "WOLF_PORTAL_SCAN_INTERVAL inválido: "
            f"{raw_value!r}"
        ) from exc

    if value <= 0:
        raise ValueError(
            "WOLF_PORTAL_SCAN_INTERVAL deve ser "
            "maior que zero."
        )

    return value


# ====================================================================
# MONITORAMENTO
# ====================================================================

def run_monitoring(
    monitor_factory: Callable[[], MonitorService] | None = None,
) -> MonitorService:
    """
    Inicia o monitoramento contínuo.

    monitor_factory existe para permitir testes sem iniciar
    um loop real de rede.
    """

    if monitor_factory is not None:
        monitor = (
            monitor_factory()
        )

    else:
        monitor = MonitorService(
            interval_seconds=get_scan_interval(),
        )

    try:
        monitor.run_forever()

    except KeyboardInterrupt:
        print()
        print(
            "Interrupção recebida."
        )

        monitor.stop()

    return monitor


# ====================================================================
# ENTRY POINT
# ====================================================================

def main(
    sync_callback: Callable[[], Any] | None = None,
    *,
    run_monitor: bool = False,
    monitor_factory: Callable[[], MonitorService] | None = None,
) -> int:
    """
    Entry point executável.

    Retorna:

        0 -> execução concluída normalmente;
        1 -> falha durante inicialização.

    Por padrão run_monitor=False para preservar a capacidade
    dos testes de executar main() sem entrar em loop infinito.

    Quando o arquivo é iniciado diretamente através de:

        python3 -m app.main

    run_monitor=True é utilizado no bloco __main__ abaixo.
    """

    try:
        startup(
            sync_callback=sync_callback
        )

    except Exception as exc:
        print()
        print(
            "=============================================="
        )
        print(
            " ERRO DURANTE INICIALIZAÇÃO"
        )
        print(
            "=============================================="
        )
        print(
            f"{type(exc).__name__}: {exc}"
        )

        return 1

    if run_monitor:

        try:
            run_monitoring(
                monitor_factory=monitor_factory
            )

        except Exception as exc:
            print()
            print(
                "=============================================="
            )
            print(
                " ERRO NO MONITORAMENTO"
            )
            print(
                "=============================================="
            )
            print(
                f"{type(exc).__name__}: {exc}"
            )

            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main(
            run_monitor=True
        )
    )