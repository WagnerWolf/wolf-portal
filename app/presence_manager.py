from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.network_monitor import Neighbor, Presence


class PresenceEventType(str, Enum):
    DEVICE_ONLINE = "DEVICE_ONLINE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"


@dataclass
class PresenceState:
    mac: str
    ip: Optional[str]
    presence: Presence
    consecutive_absent: int = 0
    notified_online: bool = False


@dataclass
class PresenceEvent:
    event_type: PresenceEventType
    mac: str
    ip: Optional[str]
    presence: Presence


class PresenceManager:
    """
    Mantém o estado de presença dos dispositivos observados pela rede.

    Não conhece SQLite, Telegram, firewall ou DeviceManager.
    Sua responsabilidade é transformar observações individuais
    do NetworkMonitor em eventos de presença confiáveis.
    """

    def __init__(self, absent_threshold: int = 3):
        if absent_threshold < 1:
            raise ValueError("absent_threshold deve ser >= 1")

        self.absent_threshold = absent_threshold
        self._states: dict[str, PresenceState] = {}

    def process(self, neighbors: list[Neighbor]) -> list[PresenceEvent]:
        """
        Processa uma fotografia da tabela de neighbors.

        Retorna os eventos de presença produzidos neste ciclo.
        """

        events: list[PresenceEvent] = []

        current: dict[str, Neighbor] = {
            neighbor.mac: neighbor
            for neighbor in neighbors
            if neighbor.mac
        }

        # Processa dispositivos atualmente encontrados.
        for mac, neighbor in current.items():
            event = self._process_present(neighbor)

            if event is not None:
                events.append(event)

        # Processa dispositivos que desapareceram da tabela.
        for mac, state in list(self._states.items()):
            if mac in current:
                continue

            event = self._process_absent(state)

            if event is not None:
                events.append(event)

        return events

    def _process_present(
        self,
        neighbor: Neighbor,
    ) -> Optional[PresenceEvent]:

        state = self._states.get(neighbor.mac)

        if state is None:
            state = PresenceState(
                mac=neighbor.mac,
                ip=neighbor.ip,
                presence=Presence.UNKNOWN,
            )

            self._states[neighbor.mac] = state

        old_presence = state.presence

        state.ip = neighbor.ip
        state.consecutive_absent = 0
        state.presence = neighbor.presence

        # A partir daqui o dispositivo está presente.
        if neighbor.presence != Presence.PRESENT:
            return None

        if old_presence != Presence.PRESENT:
            state.notified_online = True

            return PresenceEvent(
                event_type=PresenceEventType.DEVICE_ONLINE,
                mac=neighbor.mac,
                ip=neighbor.ip,
                presence=Presence.PRESENT,
            )

        return None

    def _process_absent(
        self,
        state: PresenceState,
    ) -> Optional[PresenceEvent]:

        state.consecutive_absent += 1

        if state.presence == Presence.ABSENT:
            return None

        if state.consecutive_absent < self.absent_threshold:
            return None

        state.presence = Presence.ABSENT
        state.notified_online = False

        return PresenceEvent(
            event_type=PresenceEventType.DEVICE_OFFLINE,
            mac=state.mac,
            ip=state.ip,
            presence=Presence.ABSENT,
        )

    def get_state(self, mac: str) -> Optional[PresenceState]:
        """
        Retorna o estado atual conhecido de um MAC.
        """

        return self._states.get(mac.lower())

    def get_states(self) -> list[PresenceState]:
        """
        Retorna uma cópia dos estados conhecidos.
        """

        return list(self._states.values())

    def clear(self) -> None:
        """
        Limpa todos os estados mantidos em memória.
        """

        self._states.clear()
