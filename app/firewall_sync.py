from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.access_controller import AccessController
from app.firewall_manager import FirewallManager
from app.models import DeviceStatus
from app.nftables_controller import NftablesController
from app.nftables_executor import NftablesExecutor
from app.device_manager import list_devices


class FirewallSyncError(RuntimeError):
    """
    Erro ao converter o estado persistido no banco para
    o estado lógico do firewall.
    """


def build_firewall_from_devices(
    devices: Iterable[Mapping],
) -> FirewallManager:
    """
    Reconstrói um FirewallManager a partir de uma coleção
    completa de dispositivos.

    O banco/coleção recebida é considerado a fonte da verdade.

    Regras:

        AUTHORIZED -> autorizado

        PENDING
        BLOCKED
        DISABLED   -> bloqueado

    O MAC administrativo protegido continua sendo tratado
    pelo próprio FirewallManager e nunca pode entrar no
    conjunto de bloqueados.

    Um status desconhecido NÃO é interpretado automaticamente.
    Nesse caso levantamos FirewallSyncError para impedir que
    um estado corrompido seja aplicado ao firewall.
    """

    firewall = FirewallManager()

    access = AccessController(
        firewall=firewall,
    )

    for device in devices:

        try:
            mac = str(
                device["mac"]
            ).strip().lower()

            raw_status = str(
                device["status"]
            ).strip().upper()

        except (KeyError, TypeError) as exc:
            raise FirewallSyncError(
                "Registro de dispositivo inválido."
            ) from exc

        if not mac:
            raise FirewallSyncError(
                "Dispositivo sem MAC."
            )

        try:
            status = DeviceStatus(
                raw_status
            )

        except ValueError as exc:
            raise FirewallSyncError(
                f"Status inválido para {mac}: "
                f"{raw_status!r}"
            ) from exc

        access.apply(
            status,
            mac,
        )

    return firewall


def build_firewall_from_database() -> FirewallManager:
    """
    Lê todos os dispositivos do banco e reconstrói
    completamente o estado lógico do firewall.
    """

    return build_firewall_from_devices(
        list_devices()
    )


def build_controller_from_database(
    *,
    executor: NftablesExecutor | None = None,
) -> NftablesController:
    """
    Cria um NftablesController cujo FirewallManager foi
    reconstruído a partir do banco atual.
    """

    firewall = (
        build_firewall_from_database()
    )

    return NftablesController(
        firewall=firewall,
        executor=executor,
    )


def preview_ruleset_from_database() -> str:
    """
    Gera o fragmento nftables correspondente ao banco,
    sem aplicar nenhuma alteração ao sistema.
    """

    controller = (
        build_controller_from_database()
    )

    return controller.build_ruleset()


def apply_firewall_from_database(
    *,
    with_rollback: bool = False,
    rollback_seconds: int | None = None,
) -> NftablesController:
    """
    Reconstrói o firewall inteiro a partir do banco e
    aplica o resultado.

    with_rollback=False:
        aplicação normal/persistente.

    with_rollback=True:
        utiliza o mecanismo de rollback automático do
        NftablesExecutor.

    Retorna o controller utilizado para que o chamador possa:

        controller.confirm()

    ou:

        controller.executor.wait_for_rollback(...)
    """

    controller = (
        build_controller_from_database()
    )

    if rollback_seconds is not None:
        if rollback_seconds <= 0:
            raise ValueError(
                "rollback_seconds deve ser maior que zero."
            )

        controller.executor.rollback_seconds = (
            rollback_seconds
        )

    if with_rollback:
        controller.apply_with_rollback()
    else:
        controller.apply()

    return controller
