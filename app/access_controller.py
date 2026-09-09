from app.access_policy import AccessDecision, AccessPolicy
from app.firewall_manager import FirewallManager
from app.models import DeviceStatus


class AccessController:
    """
    Converte o estado de um dispositivo em uma ação sobre
    o estado lógico do firewall.

    Não executa nftables.
    """

    def __init__(
        self,
        policy: AccessPolicy | None = None,
        firewall: FirewallManager | None = None,
    ):
        self.policy = policy or AccessPolicy()
        self.firewall = firewall or FirewallManager()

    def apply(self, status: DeviceStatus | str, mac: str) -> AccessDecision:
        decision = self.policy.evaluate(status)

        if decision == AccessDecision.ALLOW:
            self.firewall.authorize(mac)
        else:
            self.firewall.revoke(mac)

        return decision