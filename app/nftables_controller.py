from app.firewall_manager import FirewallManager
from app.nftables_executor import NftablesExecutor
from app.nftables_rules import NftablesRules


class NftablesController:
    """
    Faz a ponte entre:

        FirewallManager
            ↓
        NftablesRules
            ↓
        NftablesExecutor
            ↓
        firewall4

    O FirewallManager continua sendo a fonte do estado lógico.
    """

    def __init__(
        self,
        firewall: FirewallManager | None = None,
        rules: NftablesRules | None = None,
        executor: NftablesExecutor | None = None,
    ):
        self.firewall = (
            firewall
            or FirewallManager()
        )

        self.rules = (
            rules
            or NftablesRules()
        )

        self.executor = (
            executor
            or NftablesExecutor()
        )

    # ================================================================
    # COMPATIBILIDADE COM INTERFACE ANTIGA
    # ================================================================

    @property
    def authorized_macs(self) -> set[str]:
        return set(
            self.firewall.list_authorized()
        )

    @property
    def blocked_macs(self) -> set[str]:
        return set(
            self.firewall.list_blocked()
        )

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return mac.strip().lower()

    def add_authorized_mac(
        self,
        mac: str,
    ) -> None:

        self.firewall.authorize(
            mac
        )

    def remove_authorized_mac(
        self,
        mac: str,
    ) -> None:

        self.firewall.revoke(
            mac
        )

    # ================================================================
    # BLOQUEIO
    # ================================================================

    def block_mac(
        self,
        mac: str,
    ) -> None:

        self.firewall.block(
            mac
        )

    def unblock_mac(
        self,
        mac: str,
    ) -> None:

        self.firewall.unblock(
            mac
        )

    # ================================================================
    # GERAÇÃO
    # ================================================================

    def build_ruleset(self) -> str:
        """
        Converte o estado atual do FirewallManager em regras nftables.
        """

        self.rules.clear()

        for mac in self.firewall.list_authorized():

            self.rules.add_authorized_mac(
                mac
            )

        for mac in self.firewall.list_blocked():

            self.rules.add_blocked_mac(
                mac
            )

        return self.rules.generate_ruleset()

    # ================================================================
    # APLICAÇÃO
    # ================================================================

    def apply(self) -> str:
        """
        Aplica imediatamente o estado atual.
        """

        ruleset = self.build_ruleset()

        self.executor.apply_ruleset(
            ruleset
        )

        return ruleset

    def apply_with_rollback(self) -> str:
        """
        Aplica com rollback automático.
        """

        ruleset = self.build_ruleset()

        self.executor.apply_with_rollback(
            ruleset
        )

        return ruleset

    def confirm(self) -> None:
        """
        Confirma a aplicação e cancela o rollback.
        """

        self.executor.confirm()

    # ================================================================
    # REMOÇÃO
    # ================================================================

    def remove(self) -> None:
        """
        Remove somente as regras gerenciadas pelo Wolf Portal.
        """

        self.executor.remove_managed_rules()