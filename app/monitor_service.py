from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any

from app.device_access_service import resync_firewall
from app.discovery_cycle import (
    DiscoveryCycle,
    DiscoveryCycleResult,
)


class MonitorService:
    """
    Serviço contínuo de descoberta do Wolf Portal.

    Responsabilidades:

        1. executar ciclos de descoberta da LAN;
        2. detectar quando novos dispositivos foram cadastrados;
        3. sincronizar o firewall somente quando necessário;
        4. repetir uma sincronização que tenha falhado;
        5. NÃO executar fw4 reload a cada ciclo.

    O banco continua sendo a fonte da verdade.

    O DeviceDiscovery continua responsável somente por
    descobrir/atualizar dispositivos no banco.

    Esta camada faz a ponte entre a descoberta e o firewall.
    """

    def __init__(
        self,
        discovery_cycle: DiscoveryCycle | None = None,
        sync_callback: Callable[[], Any] | None = None,
        interval_seconds: float = 3.0,
        log_callback: Callable[[str], None] | None = None,
    ):
        if interval_seconds <= 0:
            raise ValueError(
                "interval_seconds deve ser maior que zero."
            )

        self.discovery_cycle = (
            discovery_cycle
            if discovery_cycle is not None
            else DiscoveryCycle()
        )

        self.sync_callback = (
            sync_callback
            if sync_callback is not None
            else resync_firewall
        )

        self.interval_seconds = interval_seconds

        self.log_callback = (
            log_callback
            if log_callback is not None
            else print
        )

        self._stop_event = Event()

        # Indica que o banco possui uma alteração de acesso
        # que ainda precisa chegar ao firewall.
        #
        # Se fw4 falhar, permanece True e o próximo ciclo
        # tentará novamente.
        self._firewall_dirty = False

    # ================================================================
    # LOG
    # ================================================================

    def _log(
        self,
        message: str,
    ) -> None:
        self.log_callback(
            message
        )

    # ================================================================
    # ESTADO
    # ================================================================

    @property
    def firewall_dirty(self) -> bool:
        """
        True quando existe uma alteração persistida no banco
        que ainda precisa ser sincronizada com o firewall.
        """

        return self._firewall_dirty

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    # ================================================================
    # SINCRONIZAÇÃO
    # ================================================================

    def _sync_firewall_if_needed(
        self,
    ) -> None:
        """
        Sincroniza o firewall apenas se houver alteração pendente.

        Em caso de falha:

            firewall_dirty permanece True.

        Portanto o próximo ciclo tentará novamente.
        """

        if not self._firewall_dirty:
            return

        self._log(
            "[firewall] Sincronizando alterações..."
        )

        try:
            self.sync_callback()

        except Exception as exc:
            self._log(
                "[firewall] ERRO durante sincronização: "
                f"{type(exc).__name__}: {exc}"
            )

            # IMPORTANTÍSSIMO:
            # não limpamos _firewall_dirty.
            #
            # Assim o próximo ciclo tenta novamente.
            raise

        self._firewall_dirty = False

        self._log(
            "[firewall] Sincronização concluída."
        )

    # ================================================================
    # CICLO
    # ================================================================

    def run_once(
        self,
    ) -> DiscoveryCycleResult:
        """
        Executa exatamente um ciclo completo de monitoramento.

        Se um ou mais dispositivos novos forem encontrados,
        o firewall é reconstruído uma única vez ao final do ciclo.
        """

        result = (
            self.discovery_cycle.run_once()
        )

        new_devices = [
            discovery
            for discovery in result.discoveries
            if discovery.new_device
        ]

        if new_devices:
            self._firewall_dirty = True

            for device in new_devices:
                self._log(
                    "[discovery] Novo dispositivo: "
                    f"MAC={device.mac} "
                    f"IP={device.ip or '-'} "
                    f"STATUS={device.status}"
                )

        # Mesmo que nenhum aparelho novo tenha aparecido
        # neste ciclo, executamos esta verificação.
        #
        # Isso permite repetir uma sincronização que tenha
        # falhado no ciclo anterior.
        self._sync_firewall_if_needed()

        return result

    # ================================================================
    # LOOP
    # ================================================================

    def run_forever(
        self,
    ) -> None:
        """
        Executa continuamente até stop() ser chamado
        ou o processo receber interrupção externa.

        Falhas temporárias de descoberta ou firewall são
        registradas, mas não encerram o serviço.
        """

        self._stop_event.clear()

        self._log(
            "=============================================="
        )
        self._log(
            " WOLF PORTAL - MONITORAMENTO ATIVO"
        )
        self._log(
            "=============================================="
        )
        self._log(
            f"Intervalo: {self.interval_seconds:g} segundos"
        )

        while not self._stop_event.is_set():

            try:
                self.run_once()

            except Exception as exc:
                self._log(
                    "[monitor] Ciclo falhou: "
                    f"{type(exc).__name__}: {exc}"
                )

                self._log(
                    "[monitor] O serviço continuará "
                    "e tentará novamente."
                )

            # Event.wait() em vez de time.sleep().
            #
            # Assim stop() consegue interromper a espera
            # imediatamente.
            self._stop_event.wait(
                self.interval_seconds
            )

        self._log(
            "Wolf Portal: monitoramento encerrado."
        )

    # ================================================================
    # STOP
    # ================================================================

    def stop(
        self,
    ) -> None:
        """
        Solicita encerramento gracioso do loop.
        """

        self._stop_event.set()