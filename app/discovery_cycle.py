from dataclasses import dataclass
from typing import Optional

from app.device_discovery import DeviceDiscovery, DiscoveryResult
from app.network_monitor import NetworkMonitor
from app.network_monitor import Presence
from app.presence_manager import PresenceEvent, PresenceManager


@dataclass
class DiscoveryCycleResult:
    events: list[PresenceEvent]
    discoveries: list[DiscoveryResult]


class DiscoveryCycle:
    """
    Executa um ciclo completo de monitoramento.

    Fluxo:

        NetworkMonitor
            ↓
        PresenceManager
            ↓
        DeviceDiscovery

    O PresenceManager controla eventos de presença.

    O DeviceDiscovery observa continuamente os dispositivos
    presentes para manter last_seen, IP e cadastro atualizados.
    """

    def __init__(
        self,
        network_monitor: Optional[NetworkMonitor] = None,
        presence_manager: Optional[PresenceManager] = None,
        device_discovery: Optional[DeviceDiscovery] = None,
    ):
        self.network_monitor = (
            network_monitor
            if network_monitor is not None
            else NetworkMonitor()
        )

        self.presence_manager = (
            presence_manager
            if presence_manager is not None
            else PresenceManager()
        )

        self.device_discovery = (
            device_discovery
            if device_discovery is not None
            else DeviceDiscovery()
        )

    def run_once(self) -> DiscoveryCycleResult:
        """
        Executa exatamente um ciclo de monitoramento.
        """

        neighbors = self.network_monitor.get_neighbors()

        # 1. Processa presença.
        events = self.presence_manager.process(neighbors)

        # 2. Processa todos os dispositivos atualmente presentes.
        discoveries = []

        for neighbor in neighbors:
            if neighbor.presence != Presence.PRESENT:
                continue

            result = self.device_discovery.observe(
                mac=neighbor.mac,
                ip=neighbor.ip,
            )

            discoveries.append(result)

        return DiscoveryCycleResult(
            events=events,
            discoveries=discoveries,
        )