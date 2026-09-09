from enum import Enum

from .models import DeviceStatus


class AccessDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class AccessPolicy:
    """
    Define se um dispositivo deve possuir acesso à rede.

    Esta classe contém apenas a regra de negócio.
    Não executa comandos de rede e não conhece o firewall.
    """

    def evaluate(self, status: DeviceStatus) -> AccessDecision:
        if status == DeviceStatus.AUTHORIZED:
            return AccessDecision.ALLOW

        return AccessDecision.DENY
