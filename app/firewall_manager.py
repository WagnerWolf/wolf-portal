from dataclasses import dataclass


# ================================================================
# PROTEÇÃO TEMPORÁRIA ABSOLUTA
# ================================================================
#
# Enquanto estivermos implantando o Wolf Portal, este computador
# nunca poderá entrar no conjunto de dispositivos bloqueados.
#
# Essa proteção poderá ser removida posteriormente, quando todo
# o sistema estiver validado.
#
PROTECTED_ADMIN_MAC = "70:08:10:b3:3f:71"


@dataclass(frozen=True)
class FirewallDevice:
    mac: str
    authorized: bool


class FirewallManager:
    """
    Mantém o estado lógico de acesso dos dispositivos.

    Esta classe NÃO executa nftables.

    Existem dois conjuntos explícitos:

    - authorized_macs:
        dispositivos autorizados;

    - blocked_macs:
        dispositivos que devem ser bloqueados pelo Wolf Portal.

    Isso é proposital.

    O Wolf Portal NÃO utiliza uma política global "bloqueie tudo
    que não estiver autorizado". Somente MACs explicitamente
    presentes em blocked_macs podem sofrer DROP.

    Isso torna a política fail-open e reduz drasticamente o risco
    de bloquear acidentalmente um dispositivo administrativo.
    """

    PROTECTED_ADMIN_MAC = PROTECTED_ADMIN_MAC

    def __init__(self):
        self._authorized_macs: set[str] = set()
        self._blocked_macs: set[str] = set()

    # ================================================================
    # Normalização
    # ================================================================

    @staticmethod
    def normalize_mac(mac: str) -> str:
        return mac.strip().lower()

    # ================================================================
    # Proteção administrativa
    # ================================================================

    def is_protected(self, mac: str) -> bool:
        return (
            self.normalize_mac(mac)
            == self.PROTECTED_ADMIN_MAC
        )

    # ================================================================
    # Autorização
    # ================================================================

    def authorize(self, mac: str) -> None:
        """
        Autoriza explicitamente um dispositivo.

        Ao autorizar, ele também é removido do conjunto
        de bloqueados.
        """

        mac = self.normalize_mac(mac)

        self._blocked_macs.discard(mac)
        self._authorized_macs.add(mac)

    # ================================================================
    # Revogação / bloqueio
    # ================================================================

    def revoke(self, mac: str) -> None:
        """
        Revoga o acesso de um dispositivo.

        Para dispositivos normais:
            remove de authorized_macs
            adiciona em blocked_macs

        Para o computador administrativo protegido:
            nunca adiciona em blocked_macs.
        """

        mac = self.normalize_mac(mac)

        if self.is_protected(mac):
            self._blocked_macs.discard(mac)

            # Se alguma camada tentar revogar acidentalmente
            # o computador administrativo, mantemos autorização.
            self._authorized_macs.add(mac)

            return

        self._authorized_macs.discard(mac)
        self._blocked_macs.add(mac)

    def block(self, mac: str) -> None:
        """
        Alias explícito para revoke().
        """

        self.revoke(mac)

    def unblock(self, mac: str) -> None:
        """
        Remove o dispositivo do conjunto de bloqueados sem
        necessariamente autorizá-lo.
        """

        mac = self.normalize_mac(mac)

        self._blocked_macs.discard(mac)

    # ================================================================
    # Consulta
    # ================================================================

    def is_authorized(self, mac: str) -> bool:
        mac = self.normalize_mac(mac)

        return mac in self._authorized_macs

    def is_blocked(self, mac: str) -> bool:
        mac = self.normalize_mac(mac)

        if self.is_protected(mac):
            return False

        return mac in self._blocked_macs

    def list_authorized(self) -> list[str]:
        return sorted(self._authorized_macs)

    def list_blocked(self) -> list[str]:
        return sorted(
            mac
            for mac in self._blocked_macs
            if not self.is_protected(mac)
        )

    # ================================================================
    # Limpeza
    # ================================================================

    def clear(self) -> None:
        self._authorized_macs.clear()
        self._blocked_macs.clear()