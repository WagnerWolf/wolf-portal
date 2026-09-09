from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

from app import device_manager
from app.firewall_sync import (
    apply_firewall_from_database,
)


class DeviceAccessSyncError(RuntimeError):
    """
    O banco foi alterado, mas a resincronização do firewall
    falhou.

    O banco continua sendo a fonte da verdade.

    Uma nova chamada a resync_firewall(), ou a sincronização
    executada durante o próximo startup, deve reconstruir o
    firewall a partir do estado persistido.
    """

    def __init__(
        self,
        operation: str,
        mac: str,
        cause: Exception,
    ):
        self.operation = operation
        self.mac = mac
        self.cause = cause

        super().__init__(
            f"Banco atualizado durante {operation} para "
            f"{mac}, mas a sincronização do firewall falhou: "
            f"{type(cause).__name__}: {cause}"
        )


class DeviceAccessService:
    """
    Camada operacional entre:

        device_manager
              ↓
        banco SQLite
              ↓
        firewall_sync
              ↓
        fw4 / nftables

    O banco é sempre a fonte da verdade.

    As operações de alteração de status:

        authorize_device()
        block_device()
        disable_device()
        reauthorize_device()

    atualizam primeiro o banco e depois reconstruem todo o
    firewall a partir do banco.

    discover_device() somente sincroniza o firewall quando
    realmente encontra um dispositivo novo. Atualizações
    comuns de last_seen/IP/hostname não provocam fw4 reload.

    Um RLock evita que duas alterações feitas pelo mesmo
    processo tentem reconstruir o firewall simultaneamente.
    """

    def __init__(
        self,
        sync_callback: Callable[[], Any] | None = None,
    ):
        self._lock = RLock()

        self._sync_callback = (
            sync_callback
            or self._default_sync
        )

    # ================================================================
    # SINCRONIZAÇÃO
    # ================================================================

    @staticmethod
    def _default_sync():
        """
        Sincronização operacional normal.

        Quando esta classe for utilizada de verdade,
        a alteração será aplicada persistentemente através
        do include administrado pelo Wolf Portal.
        """

        return apply_firewall_from_database(
            with_rollback=False,
        )

    def resync_firewall(self):
        """
        Reconstrói explicitamente todo o firewall a partir
        do banco atual.
        """

        with self._lock:
            return self._sync_callback()

    def _sync_after_change(
        self,
        operation: str,
        mac: str,
    ):
        try:
            return self._sync_callback()

        except Exception as exc:
            raise DeviceAccessSyncError(
                operation=operation,
                mac=mac,
                cause=exc,
            ) from exc

    # ================================================================
    # DESCOBERTA
    # ================================================================

    def discover_device(
        self,
        mac: str,
        ip: str | None = None,
        hostname: str | None = None,
    ):
        """
        Registra/atualiza um dispositivo.

        Se ele for novo:
            nasce PENDING;
            o firewall é imediatamente reconstruído;
            portanto ele passa a ser bloqueado.

        Se já existir:
            apenas atualiza os dados de descoberta;
            não provoca reload desnecessário do firewall.
        """

        with self._lock:

            existing = (
                device_manager.get_device(
                    mac
                )
            )

            device = (
                device_manager.discover_device(
                    mac=mac,
                    ip=ip,
                    hostname=hostname,
                )
            )

            if existing is None:
                self._sync_after_change(
                    operation="discover_device",
                    mac=mac,
                )

            return device

    # ================================================================
    # AUTORIZAÇÃO
    # ================================================================

    def authorize_device(
        self,
        mac: str,
        source: str = "system",
    ):
        with self._lock:

            device = (
                device_manager.authorize_device(
                    mac,
                    source=source,
                )
            )

            self._sync_after_change(
                operation="authorize_device",
                mac=mac,
            )

            return device

    # ================================================================
    # BLOQUEIO
    # ================================================================

    def block_device(
        self,
        mac: str,
        source: str = "system",
    ):
        with self._lock:

            device = (
                device_manager.block_device(
                    mac,
                    source=source,
                )
            )

            self._sync_after_change(
                operation="block_device",
                mac=mac,
            )

            return device

    # ================================================================
    # DESATIVAÇÃO
    # ================================================================

    def disable_device(
        self,
        mac: str,
        source: str = "system",
    ):
        with self._lock:

            device = (
                device_manager.disable_device(
                    mac,
                    source=source,
                )
            )

            self._sync_after_change(
                operation="disable_device",
                mac=mac,
            )

            return device

    # ================================================================
    # REAUTORIZAÇÃO
    # ================================================================

    def reauthorize_device(
        self,
        mac: str,
        source: str = "system",
    ):
        with self._lock:

            device = (
                device_manager.reauthorize_device(
                    mac,
                    source=source,
                )
            )

            self._sync_after_change(
                operation="reauthorize_device",
                mac=mac,
            )

            return device


# ====================================================================
# INSTÂNCIA PADRÃO
# ====================================================================

_default_service = DeviceAccessService()


# ====================================================================
# API FUNCIONAL
# ====================================================================
#
# Permite que as demais partes do Wolf Portal façam:
#
#     from app.device_access_service import authorize_device
#
# em vez de precisar instanciar manualmente o serviço.
# ====================================================================

def resync_firewall():
    return _default_service.resync_firewall()


def discover_device(
    mac: str,
    ip: str | None = None,
    hostname: str | None = None,
):
    return _default_service.discover_device(
        mac=mac,
        ip=ip,
        hostname=hostname,
    )


def authorize_device(
    mac: str,
    source: str = "system",
):
    return _default_service.authorize_device(
        mac,
        source=source,
    )


def block_device(
    mac: str,
    source: str = "system",
):
    return _default_service.block_device(
        mac,
        source=source,
    )


def disable_device(
    mac: str,
    source: str = "system",
):
    return _default_service.disable_device(
        mac,
        source=source,
    )


def reauthorize_device(
    mac: str,
    source: str = "system",
):
    return _default_service.reauthorize_device(
        mac,
        source=source,
    )
