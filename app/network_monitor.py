import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Presence(str, Enum):
    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"


@dataclass
class Neighbor:
    ip: str
    mac: str
    state: str
    presence: Presence


class NetworkMonitor:
    """
    Monitora a presença de dispositivos na rede LAN.

    A primeira versão utiliza a tabela IPv4 neighbor do kernel
    através do comando `ip -4 neigh`.
    """

    INTERFACE = "br-lan"

    PRESENT_STATES = {
        "REACHABLE",
        "DELAY",
        "PROBE",
    }

    UNKNOWN_STATES = {
        "STALE",
    }

    ABSENT_STATES = {
        "FAILED",
        "INCOMPLETE",
    }

    MAC_PATTERN = re.compile(
        r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$",
        re.IGNORECASE,
    )

    def __init__(self, interface: str = INTERFACE):
        self.interface = interface

    def _run_ip_neigh(self) -> str:
        result = subprocess.run(
            [
                "ip",
                "-4",
                "neigh",
                "show",
                "dev",
                self.interface,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        return result.stdout

    @classmethod
    def _presence_from_state(cls, state: str) -> Presence:
        state = state.upper()

        if state in cls.PRESENT_STATES:
            return Presence.PRESENT

        if state in cls.ABSENT_STATES:
            return Presence.ABSENT

        return Presence.UNKNOWN

    @classmethod
    def _parse_line(cls, line: str) -> Optional[Neighbor]:
        """
        Converte uma linha de `ip neigh` em Neighbor.

        Exemplos aceitos:

        10.0.69.224 lladdr 70:08:10:b3:3f:71 REACHABLE
        10.0.69.197 FAILED
        """

        parts = line.split()

        if not parts:
            return None

        ip = parts[0]

        mac = None
        state = None

        for index, part in enumerate(parts):
            if part.lower() == "lladdr" and index + 1 < len(parts):
                candidate = parts[index + 1].lower()

                if cls.MAC_PATTERN.match(candidate):
                    mac = candidate

            if part.upper() in (
                cls.PRESENT_STATES
                | cls.UNKNOWN_STATES
                | cls.ABSENT_STATES
            ):
                state = part.upper()

        if state is None:
            return None

        if mac is None:
            return Neighbor(
                ip=ip,
                mac="",
                state=state,
                presence=cls._presence_from_state(state),
            )

        return Neighbor(
            ip=ip,
            mac=mac,
            state=state,
            presence=cls._presence_from_state(state),
        )

    def get_neighbors(self) -> list[Neighbor]:
        output = self._run_ip_neigh()

        neighbors = []

        for line in output.splitlines():
            neighbor = self._parse_line(line)

            if neighbor is not None:
                neighbors.append(neighbor)

        return neighbors

    def find_by_mac(self, mac: str) -> Optional[Neighbor]:
        mac = mac.lower()

        for neighbor in self.get_neighbors():
            if neighbor.mac == mac:
                return neighbor

        return None
