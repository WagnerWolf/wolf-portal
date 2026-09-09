from dataclasses import dataclass

from app.firewall_manager import PROTECTED_ADMIN_MAC


@dataclass(frozen=True)
class NftRule:
    """
    Representa uma regra lógica do Wolf Portal.

    Esta classe NÃO executa comandos nft.
    """

    chain: str
    expression: str
    action: str


class NftablesRules:
    """
    Constrói o fragmento nftables utilizado pelo Wolf Portal.

    IMPORTANTE:

    Este arquivo NÃO gera:

        table inet wolf_portal

    Ele gera somente conteúdo destinado a ser incluído dentro de:

        table inet fw4

    através de:

        /etc/nftables.d/90-wolf-portal.nft

    O Wolf Portal utiliza chains próprias e policy ACCEPT.

    Somente MACs explicitamente presentes em blocked_macs
    recebem DROP ou redirecionamento para o captive portal.

    Fluxo para MAC bloqueado:

        DNS local -> permitido
        HTTP :80 -> redirecionado para Wolf Portal :81
        Wolf Portal :81 -> permitido
        HTTPS administrativo :443 -> bloqueado
        FORWARD -> bloqueado

    Dispositivos autorizados e o dispositivo administrativo
    protegido não sofrem redirecionamento.
    """

    TABLE_NAME = "fw4"

    FAILSAFE_MAC = PROTECTED_ADMIN_MAC

    LAN_INTERFACE = "br-lan"
    ROUTER_IPV4 = "10.0.69.1"
    PORTAL_PORT = 81

    SET_FAILSAFE = "wolf_portal_failsafe_macs"
    SET_AUTHORIZED = "wolf_portal_authorized_macs"
    SET_BLOCKED = "wolf_portal_blocked_macs"

    CHAIN_PREROUTING = "wolf_portal_prerouting"
    CHAIN_INPUT = "wolf_portal_input"
    CHAIN_FORWARD = "wolf_portal_forward"

    def __init__(self):
        self._authorized_macs: set[str] = set()
        self._blocked_macs: set[str] = set()

    # ================================================================
    # MAC
    # ================================================================

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return mac.strip().lower()

    # ================================================================
    # AUTORIZADOS
    # ================================================================

    def add_authorized_mac(self, mac: str) -> None:
        mac = self._normalize_mac(mac)

        self._blocked_macs.discard(mac)
        self._authorized_macs.add(mac)

    def remove_authorized_mac(self, mac: str) -> None:
        mac = self._normalize_mac(mac)

        self._authorized_macs.discard(mac)

    def get_authorized_macs(self) -> set[str]:
        return set(self._authorized_macs)

    def is_authorized(self, mac: str) -> bool:
        return (
            self._normalize_mac(mac)
            in self._authorized_macs
        )

    @property
    def authorized_macs(self) -> set[str]:
        return set(self._authorized_macs)

    # ================================================================
    # BLOQUEADOS
    # ================================================================

    def add_blocked_mac(self, mac: str) -> None:
        mac = self._normalize_mac(mac)

        # Trava de segurança absoluta.
        if mac == self.FAILSAFE_MAC:
            return

        self._authorized_macs.discard(mac)
        self._blocked_macs.add(mac)

    def remove_blocked_mac(self, mac: str) -> None:
        mac = self._normalize_mac(mac)

        self._blocked_macs.discard(mac)

    def get_blocked_macs(self) -> set[str]:
        return self._effective_blocked_macs()

    @property
    def blocked_macs(self) -> set[str]:
        return self._effective_blocked_macs()

    def is_blocked(self, mac: str) -> bool:
        return (
            self._normalize_mac(mac)
            in self._effective_blocked_macs()
        )

    # ================================================================
    # LIMPEZA
    # ================================================================

    def clear(self) -> None:
        self._authorized_macs.clear()
        self._blocked_macs.clear()

    # ================================================================
    # ESTADO EFETIVO
    # ================================================================

    def _effective_blocked_macs(self) -> set[str]:
        """
        Retorna somente os MACs que realmente poderão receber
        bloqueio/redirecionamento.

        Proteções:

        1. FAILSAFE_MAC nunca pode ser bloqueado;
        2. MAC autorizado nunca pode simultaneamente ser bloqueado;
        3. o resultado é uma cópia independente.
        """

        blocked = set(self._blocked_macs)

        blocked.discard(self.FAILSAFE_MAC)

        blocked.difference_update(
            self._authorized_macs
        )

        return blocked

    # ================================================================
    # REGRAS LÓGICAS
    # ================================================================

    def build_failsafe_rule(self) -> NftRule:
        return NftRule(
            chain=self.CHAIN_FORWARD,
            expression=(
                f"ether saddr {self.FAILSAFE_MAC}"
            ),
            action="accept",
        )

    def build_authorized_rule(self) -> NftRule:
        return NftRule(
            chain=self.CHAIN_FORWARD,
            expression=(
                f"ether saddr @{self.SET_AUTHORIZED}"
            ),
            action="accept",
        )

    def build_block_rule(self) -> NftRule:
        return NftRule(
            chain=self.CHAIN_FORWARD,
            expression=(
                f'iifname "{self.LAN_INTERFACE}" '
                f"ether saddr @{self.SET_BLOCKED}"
            ),
            action="drop",
        )

    def build_http_redirect_rule(self) -> NftRule:
        """
        Representação lógica da interceptação HTTP.

        Apenas clientes explicitamente bloqueados são afetados.

        O redirect ocorre no prerouting antes do forward;
        portanto uma tentativa HTTP externa vira acesso local
        ao servidor Wolf Portal na porta 81.
        """

        return NftRule(
            chain=self.CHAIN_PREROUTING,
            expression=(
                "meta nfproto ipv4 "
                f'iifname "{self.LAN_INTERFACE}" '
                f"ether saddr @{self.SET_BLOCKED} "
                "tcp dport 80"
            ),
            action=(
                f"redirect to :{self.PORTAL_PORT}"
            ),
        )

    # ================================================================
    # AUXILIAR DE SET
    # ================================================================

    @staticmethod
    def _append_mac_set(
        lines: list[str],
        name: str,
        macs: set[str],
    ) -> None:

        lines.append(
            f"set {name} {{"
        )

        lines.append(
            "    type ether_addr"
        )

        if macs:
            lines.append(
                "    elements = {"
            )

            lines.append(
                "        "
                + ", ".join(
                    sorted(macs)
                )
            )

            lines.append(
                "    }"
            )

        lines.append(
            "}"
        )

    # ================================================================
    # GERAÇÃO DO FRAGMENTO FW4
    # ================================================================

    def generate_ruleset(self) -> str:
        """
        Retorna um FRAGMENTO nftables.

        Este conteúdo deve ficar dentro de:

            table inet fw4

        Portanto NÃO existe declaração "table" aqui.
        """

        lines: list[str] = []

        authorized = set(
            self._authorized_macs
        )

        blocked = (
            self._effective_blocked_macs()
        )

        failsafe = {
            self.FAILSAFE_MAC
        }

        # ============================================================
        # CABEÇALHO
        # ============================================================

        lines.append(
            "# ========================================================"
        )

        lines.append(
            "# Wolf Portal - regras gerenciadas automaticamente"
        )

        lines.append(
            "# NÃO EDITAR MANUALMENTE ENQUANTO O SERVIÇO ESTIVER ATIVO"
        )

        lines.append(
            "# ========================================================"
        )

        lines.append("")

        # ============================================================
        # SETS
        # ============================================================

        self._append_mac_set(
            lines,
            self.SET_FAILSAFE,
            failsafe,
        )

        lines.append("")

        self._append_mac_set(
            lines,
            self.SET_AUTHORIZED,
            authorized,
        )

        lines.append("")

        self._append_mac_set(
            lines,
            self.SET_BLOCKED,
            blocked,
        )

        # ============================================================
        # PREROUTING / CAPTIVE PORTAL
        # ============================================================

        lines.append("")

        lines.append(
            f"chain {self.CHAIN_PREROUTING} {{"
        )

        # Executa imediatamente antes do dstnat normal do fw4.
        lines.append(
            "    type nat hook prerouting "
            "priority dstnat - 1; policy accept;"
        )

        lines.append("")

        # ------------------------------------------------------------
        # INTERCEPTAÇÃO HTTP
        #
        # Somente IPv4 por enquanto.
        #
        # O portal atual está escutando em 0.0.0.0:81.
        # Portanto não tentamos capturar HTTP IPv6 nesta fase.
        #
        # Cliente bloqueado tentando:
        #
        #     http://qualquer-site/
        #
        # será redirecionado localmente para:
        #
        #     :81
        #
        # O servidor HTTP então responde com redirect para:
        #
        #     http://status.client:81/
        # ------------------------------------------------------------

        lines.append(
            "    meta nfproto ipv4 "
            f'iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_BLOCKED} "
            "tcp dport 80 "
            f"counter redirect to :{self.PORTAL_PORT}"
        )

        lines.append(
            "}"
        )

        # ============================================================
        # INPUT
        # ============================================================

        lines.append("")

        lines.append(
            f"chain {self.CHAIN_INPUT} {{"
        )

        lines.append(
            "    type filter hook input "
            "priority filter - 1; policy accept;"
        )

        lines.append("")

        # ------------------------------------------------------------
        # Failsafe administrativo
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_FAILSAFE} "
            "counter accept"
        )

        # ------------------------------------------------------------
        # Autorizados
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_AUTHORIZED} "
            "counter accept"
        )

        # ------------------------------------------------------------
        # DNS local para dispositivos bloqueados
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_BLOCKED} "
            "udp dport 53 "
            "counter accept"
        )

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_BLOCKED} "
            "tcp dport 53 "
            "counter accept"
        )

        # ------------------------------------------------------------
        # Portal HTTP
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_BLOCKED} "
            f"tcp dport {self.PORTAL_PORT} "
            "counter accept"
        )

        # ------------------------------------------------------------
        # HTTPS administrativo
        #
        # Não interceptamos HTTPS.
        #
        # Isso evita tentar realizar MITM TLS e mantém o LuCI HTTPS
        # inacessível aos dispositivos bloqueados.
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_BLOCKED} "
            "tcp dport 443 "
            "counter drop"
        )

        lines.append(
            "}"
        )

        # ============================================================
        # FORWARD
        # ============================================================

        lines.append("")

        lines.append(
            f"chain {self.CHAIN_FORWARD} {{"
        )

        lines.append(
            "    type filter hook forward "
            "priority filter - 1; policy accept;"
        )

        lines.append("")

        # ------------------------------------------------------------
        # Failsafe
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_FAILSAFE} "
            "counter accept"
        )

        # ------------------------------------------------------------
        # Autorizados
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_AUTHORIZED} "
            "counter accept"
        )

        # ------------------------------------------------------------
        # BLOQUEIO
        #
        # O HTTP IPv4 já terá sido interceptado no prerouting.
        #
        # Todo outro encaminhamento proveniente dos MACs
        # bloqueados é descartado aqui.
        # ------------------------------------------------------------

        lines.append(
            f'    iifname "{self.LAN_INTERFACE}" '
            f"ether saddr @{self.SET_BLOCKED} "
            "counter drop"
        )

        lines.append(
            "}"
        )

        return (
            "\n".join(lines)
            + "\n"
        )