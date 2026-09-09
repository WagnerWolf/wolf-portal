from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from threading import Event, Lock, Timer

from app.firewall_manager import PROTECTED_ADMIN_MAC


DEFAULT_INCLUDE = Path(
    "/etc/nftables.d/90-wolf-portal.nft"
)

DEFAULT_BACKUP = Path(
    "/tmp/wolf-portal-nft-backup.nft"
)

DEFAULT_LOG = Path(
    "/tmp/wolf-portal-nft-executor.log"
)

FW4_FAMILY = "inet"
FW4_TABLE = "fw4"

MANAGED_CHAINS = (
    "wolf_portal_prerouting",
    "wolf_portal_input",
    "wolf_portal_forward",
)

MANAGED_SETS = (
    "wolf_portal_failsafe_macs",
    "wolf_portal_authorized_macs",
    "wolf_portal_blocked_macs",
)

VALIDATION_TABLE = "wolf_portal_validation"


class NftablesExecutionError(RuntimeError):
    pass


class NftablesExecutor:
    """
    Executor nftables do Wolf Portal integrado ao firewall4.

    O executor NÃO cria uma tabela própria.

    O conteúdo gerado pelo Wolf Portal é salvo em:

        /etc/nftables.d/90-wolf-portal.nft

    Esse arquivo é incorporado pelo fw4 dentro de:

        table inet fw4

    OBJETOS GERENCIADOS:

        wolf_portal_prerouting
        wolf_portal_input
        wolf_portal_forward

        wolf_portal_failsafe_macs
        wolf_portal_authorized_macs
        wolf_portal_blocked_macs

    O executor jamais:

        - apaga table inet fw4;
        - usa flush ruleset;
        - usa policy drop;
        - altera chains nativas input/forward/output do fw4.
    """

    def __init__(
        self,
        include_path: Path | str = DEFAULT_INCLUDE,
        backup_path: Path | str = DEFAULT_BACKUP,
        log_path: Path | str = DEFAULT_LOG,
        rollback_seconds: int = 90,
    ):
        self.include_path = Path(include_path)
        self.backup_path = Path(backup_path)
        self.log_path = Path(log_path)

        self.rollback_seconds = rollback_seconds

        self._rollback_timer: Timer | None = None

        self._confirmed = False

        self._rollback_started = Event()
        self._rollback_completed = Event()

        self._lock = Lock()

    # ================================================================
    # LOG
    # ================================================================

    def _log(self, message: str) -> None:
        timestamp = time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        self.log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.log_path.open(
            "a",
            encoding="utf-8",
        ) as log:
            log.write(
                f"[{timestamp}] {message}\n"
            )

    # ================================================================
    # COMANDOS
    # ================================================================

    def _run_command(
        self,
        command: list[str],
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:

        self._log(
            "Executando: "
            + " ".join(command)
        )

        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
        )

        if result.stdout:
            self._log(
                "stdout: "
                + result.stdout.strip()
            )

        if result.stderr:
            self._log(
                "stderr: "
                + result.stderr.strip()
            )

        self._log(
            f"returncode={result.returncode}"
        )

        return result

    def _run_nft(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:

        return self._run_command(
            ["nft", *args],
            input_text=input_text,
        )

    def _run_fw4(
        self,
        action: str,
    ) -> subprocess.CompletedProcess:

        return self._run_command(
            ["fw4", action]
        )

    # ================================================================
    # IDENTIFICAÇÃO
    # ================================================================

    @property
    def table_identifier(self) -> str:
        return (
            f"{FW4_FAMILY} "
            f"{FW4_TABLE}"
        )

    @property
    def managed_include_path(self) -> Path:
        return self.include_path

    # ================================================================
    # FW4
    # ================================================================

    def table_exists(self) -> bool:
        """
        Verifica se table inet fw4 existe.

        IMPORTANTE:
        ela pertence ao OpenWrt, não ao Wolf Portal.
        """

        result = self._run_nft(
            [
                "list",
                "table",
                FW4_FAMILY,
                FW4_TABLE,
            ]
        )

        return result.returncode == 0

    def _ensure_fw4_exists(self) -> None:
        if not self.table_exists():
            raise NftablesExecutionError(
                "A tabela inet/fw4 não existe."
            )

    # ================================================================
    # BACKUP DO INCLUDE
    # ================================================================

    def backup_current_ruleset(self) -> Path:
        """
        Faz backup somente do arquivo administrado pelo Wolf Portal.

        Nunca copia nem sobrescreve o ruleset completo do fw4.
        """

        self.backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.include_path.exists():

            self.backup_path.write_text(
                "",
                encoding="utf-8",
            )

            self._log(
                "Include Wolf Portal não existe. "
                "Backup representa estado vazio."
            )

            return self.backup_path

        content = self.include_path.read_text(
            encoding="utf-8"
        )

        self.backup_path.write_text(
            content,
            encoding="utf-8",
        )

        self._log(
            f"Backup salvo em {self.backup_path}"
        )

        return self.backup_path

    # ================================================================
    # GUARDRAILS
    # ================================================================

    def _validate_guardrails(
        self,
        ruleset: str,
    ) -> None:

        forbidden_patterns = (
            r"(?mi)^\s*flush\s+ruleset\b",
            r"(?mi)^\s*flush\s+table\b",
            r"(?mi)^\s*delete\s+table\b",
            r"(?mi)^\s*table\s+",
            r"(?mi)\bpolicy\s+drop\s*;",
            r"(?mi)^\s*chain\s+input\s*\{",
            r"(?mi)^\s*chain\s+forward\s*\{",
            r"(?mi)^\s*chain\s+output\s*\{",
        )

        for pattern in forbidden_patterns:

            if re.search(
                pattern,
                ruleset,
            ):
                raise NftablesExecutionError(
                    "Ruleset rejeitado pelos guardrails "
                    f"de segurança: {pattern}"
                )

        # ------------------------------------------------------------
        # Somente as chains Wolf Portal conhecidas podem ser
        # declaradas no fragmento.
        # ------------------------------------------------------------

        declared_chains = set(
            re.findall(
                r"(?mi)^\s*chain\s+([A-Za-z0-9_]+)\s*\{",
                ruleset,
            )
        )

        unexpected_chains = (
            declared_chains
            - set(MANAGED_CHAINS)
        )

        if unexpected_chains:
            raise NftablesExecutionError(
                "Ruleset contém chain não gerenciada "
                "pelo Wolf Portal: "
                + ", ".join(
                    sorted(unexpected_chains)
                )
            )

        # ------------------------------------------------------------
        # Todas as chains obrigatórias precisam existir.
        # ------------------------------------------------------------

        for chain in MANAGED_CHAINS:

            if chain not in declared_chains:
                raise NftablesExecutionError(
                    "Ruleset não contém a chain "
                    f"obrigatória {chain}."
                )

        # ------------------------------------------------------------
        # Somente os sets conhecidos podem ser declarados.
        # ------------------------------------------------------------

        declared_sets = set(
            re.findall(
                r"(?mi)^\s*set\s+([A-Za-z0-9_]+)\s*\{",
                ruleset,
            )
        )

        unexpected_sets = (
            declared_sets
            - set(MANAGED_SETS)
        )

        if unexpected_sets:
            raise NftablesExecutionError(
                "Ruleset contém set não gerenciado "
                "pelo Wolf Portal: "
                + ", ".join(
                    sorted(unexpected_sets)
                )
            )

        # ------------------------------------------------------------
        # Todos os sets esperados precisam existir.
        # ------------------------------------------------------------

        for set_name in MANAGED_SETS:

            if set_name not in declared_sets:
                raise NftablesExecutionError(
                    "Ruleset não contém o set "
                    f"obrigatório {set_name}."
                )

        # ------------------------------------------------------------
        # Verifica se cada chain continua ligada ao hook correto.
        #
        # Isso impede, por exemplo, que uma alteração acidental
        # transforme wolf_portal_forward em uma chain de output.
        # ------------------------------------------------------------

        required_hooks = {
            "wolf_portal_prerouting": (
                r"(?ms)"
                r"chain\s+wolf_portal_prerouting\s*\{"
                r".*?"
                r"type\s+nat\s+hook\s+prerouting\b"
            ),
            "wolf_portal_input": (
                r"(?ms)"
                r"chain\s+wolf_portal_input\s*\{"
                r".*?"
                r"type\s+filter\s+hook\s+input\b"
            ),
            "wolf_portal_forward": (
                r"(?ms)"
                r"chain\s+wolf_portal_forward\s*\{"
                r".*?"
                r"type\s+filter\s+hook\s+forward\b"
            ),
        }

        for chain, pattern in required_hooks.items():

            if not re.search(
                pattern,
                ruleset,
            ):
                raise NftablesExecutionError(
                    f"Chain {chain} não utiliza "
                    "o hook esperado."
                )

        # ------------------------------------------------------------
        # Trava administrativa obrigatória.
        # ------------------------------------------------------------

        if (
            PROTECTED_ADMIN_MAC
            not in ruleset.lower()
        ):
            raise NftablesExecutionError(
                "Ruleset não contém o MAC "
                "administrativo de proteção."
            )

    # ================================================================
    # VALIDAÇÃO
    # ================================================================

    def validate_ruleset(
        self,
        ruleset: str,
    ) -> None:

        self._validate_guardrails(
            ruleset
        )

        # ------------------------------------------------------------
        # O arquivo real é um fragmento inserido dentro de fw4.
        #
        # Para validar sua sintaxe isoladamente, criamos em memória
        # uma tabela temporária fictícia.
        #
        # nft -c não aplica nada.
        # ------------------------------------------------------------

        wrapped = (
            f"table inet {VALIDATION_TABLE} {{\n"
            f"{ruleset}\n"
            f"}}\n"
        )

        result = self._run_nft(
            [
                "-c",
                "-f",
                "-",
            ],
            input_text=wrapped,
        )

        if result.returncode != 0:
            raise NftablesExecutionError(
                "Fragmento nftables inválido."
            )

        self._log(
            "Fragmento nftables validado "
            "com sucesso."
        )

    # ================================================================
    # INCLUDE
    # ================================================================

    def _write_include(
        self,
        ruleset: str,
    ) -> None:

        self.include_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = self.include_path.with_name(
            self.include_path.name + ".tmp"
        )

        temporary.write_text(
            ruleset,
            encoding="utf-8",
        )

        os.chmod(
            temporary,
            0o644,
        )

        os.replace(
            temporary,
            self.include_path,
        )

        self._log(
            f"Include escrito em "
            f"{self.include_path}"
        )

    def _remove_include(self) -> None:

        try:
            self.include_path.unlink()

            self._log(
                "Include Wolf Portal removido."
            )

        except FileNotFoundError:

            self._log(
                "Include Wolf Portal já estava ausente."
            )

    # ================================================================
    # CONSULTA DE OBJETOS RUNTIME
    # ================================================================

    def _chain_exists(
        self,
        chain: str,
    ) -> bool:

        result = self._run_nft(
            [
                "list",
                "chain",
                FW4_FAMILY,
                FW4_TABLE,
                chain,
            ]
        )

        return result.returncode == 0

    def _set_exists(
        self,
        set_name: str,
    ) -> bool:

        result = self._run_nft(
            [
                "list",
                "set",
                FW4_FAMILY,
                FW4_TABLE,
                set_name,
            ]
        )

        return result.returncode == 0

    # ================================================================
    # OBJETOS RUNTIME
    # ================================================================

    def _remove_runtime_objects(self) -> None:
        """
        Remove somente objetos cujo nome pertence ao Wolf Portal.

        Necessário porque um `fw4 reload` pode deixar uma chain
        personalizada vazia depois que seu include é removido.

        NUNCA toca nas chains nativas do fw4.

        A ordem é proposital:

            1. chains;
            2. sets.

        As chains referenciam os sets, portanto precisam desaparecer
        primeiro.
        """

        if not self.table_exists():
            return

        # ------------------------------------------------------------
        # Chains primeiro.
        # ------------------------------------------------------------

        for chain in MANAGED_CHAINS:

            if not self._chain_exists(
                chain
            ):
                continue

            self._run_nft(
                [
                    "flush",
                    "chain",
                    FW4_FAMILY,
                    FW4_TABLE,
                    chain,
                ]
            )

            self._run_nft(
                [
                    "delete",
                    "chain",
                    FW4_FAMILY,
                    FW4_TABLE,
                    chain,
                ]
            )

        # ------------------------------------------------------------
        # Depois sets.
        # ------------------------------------------------------------

        for set_name in MANAGED_SETS:

            if not self._set_exists(
                set_name
            ):
                continue

            self._run_nft(
                [
                    "flush",
                    "set",
                    FW4_FAMILY,
                    FW4_TABLE,
                    set_name,
                ]
            )

            self._run_nft(
                [
                    "delete",
                    "set",
                    FW4_FAMILY,
                    FW4_TABLE,
                    set_name,
                ]
            )

    # ================================================================
    # FW4 CHECK / RELOAD
    # ================================================================

    def _check_fw4(self) -> None:

        result = self._run_fw4(
            "check"
        )

        if result.returncode != 0:
            raise NftablesExecutionError(
                "fw4 check falhou."
            )

        self._log(
            "fw4 check concluído com sucesso."
        )

    def _reload_fw4(self) -> None:

        result = self._run_fw4(
            "reload"
        )

        if result.returncode != 0:
            raise NftablesExecutionError(
                "fw4 reload falhou."
            )

        self._log(
            "fw4 reload concluído com sucesso."
        )

    # ================================================================
    # VERIFICAÇÃO PÓS-APLICAÇÃO
    # ================================================================

    def _verify_chain_exists(
        self,
        chain: str,
    ) -> None:

        if not self._chain_exists(
            chain
        ):
            raise NftablesExecutionError(
                f"Chain {chain} não apareceu "
                "após fw4 reload."
            )

    def _verify_set_exists(
        self,
        set_name: str,
    ) -> None:

        if not self._set_exists(
            set_name
        ):
            raise NftablesExecutionError(
                f"Set {set_name} não apareceu "
                "após fw4 reload."
            )

    def _verify_application(self) -> None:

        for chain in MANAGED_CHAINS:
            self._verify_chain_exists(
                chain
            )

        for set_name in MANAGED_SETS:
            self._verify_set_exists(
                set_name
            )

        self._log(
            "Objetos Wolf Portal confirmados "
            "dentro do fw4."
        )

    # ================================================================
    # VERIFICAÇÃO PÓS-REMOÇÃO
    # ================================================================

    def _verify_removal(self) -> None:
        """
        Confirma que nenhum objeto gerenciado pelo Wolf Portal
        permaneceu dentro de inet/fw4.
        """

        remaining: list[str] = []

        for chain in MANAGED_CHAINS:

            if self._chain_exists(
                chain
            ):
                remaining.append(
                    f"chain:{chain}"
                )

        for set_name in MANAGED_SETS:

            if self._set_exists(
                set_name
            ):
                remaining.append(
                    f"set:{set_name}"
                )

        if remaining:
            raise NftablesExecutionError(
                "Objetos Wolf Portal permaneceram "
                "após remoção: "
                + ", ".join(remaining)
            )

        self._log(
            "Nenhum objeto Wolf Portal residual "
            "permanece no fw4."
        )

    # ================================================================
    # RESTAURA BACKUP
    # ================================================================

    def _restore_backup(self) -> None:

        if not self.backup_path.exists():

            self._log(
                "Backup inexistente. "
                "Removendo include atual."
            )

            self._remove_include()

        else:

            backup = self.backup_path.read_text(
                encoding="utf-8"
            )

            if backup.strip():

                self._write_include(
                    backup
                )

                self._log(
                    "Include anterior restaurado."
                )

            else:

                self._remove_include()

                self._log(
                    "Backup representava ausência "
                    "do Wolf Portal."
                )

        # Remove qualquer objeto residual da versão
        # que estava ativa.
        self._remove_runtime_objects()

        self._check_fw4()
        self._reload_fw4()

    # ================================================================
    # APPLY
    # ================================================================

    def apply_ruleset(
        self,
        ruleset: str,
    ) -> None:

        self._ensure_fw4_exists()

        # Sempre fazemos backup antes de alterar o include.
        self.backup_current_ruleset()

        # Validação totalmente sem efeito no firewall.
        self.validate_ruleset(
            ruleset
        )

        self._log(
            "Iniciando aplicação do Wolf Portal "
            "via firewall4."
        )

        try:

            # --------------------------------------------------------
            # Instala o novo include.
            # --------------------------------------------------------

            self._write_include(
                ruleset
            )

            # --------------------------------------------------------
            # Remove somente uma eventual versão antiga dos objetos
            # Wolf Portal.
            #
            # Durante este pequeno intervalo o comportamento é
            # fail-open, nunca fail-closed.
            # --------------------------------------------------------

            self._remove_runtime_objects()

            # --------------------------------------------------------
            # Validação do ruleset completo do OpenWrt.
            # --------------------------------------------------------

            self._check_fw4()

            # --------------------------------------------------------
            # Aplicação real.
            # --------------------------------------------------------

            self._reload_fw4()

            # --------------------------------------------------------
            # Confirma chains E sets.
            # --------------------------------------------------------

            self._verify_application()

            self._log(
                "Wolf Portal aplicado com sucesso."
            )

        except Exception as exc:

            self._log(
                "Falha na aplicação: "
                f"{type(exc).__name__}: {exc}"
            )

            # --------------------------------------------------------
            # RESTAURAÇÃO DE EMERGÊNCIA
            # --------------------------------------------------------

            try:

                self._log(
                    "Tentando restaurar estado anterior."
                )

                self._restore_backup()

                self._log(
                    "Estado anterior restaurado."
                )

            except Exception as restore_exc:

                self._log(
                    "ERRO CRÍTICO durante restauração: "
                    f"{type(restore_exc).__name__}: "
                    f"{restore_exc}"
                )

            raise

    # ================================================================
    # REMOVE WOLF PORTAL
    # ================================================================

    def remove_managed_rules(self) -> None:
        """
        Remove completamente as regras Wolf Portal sem tocar
        no restante do firewall.
        """

        self._remove_include()

        self._remove_runtime_objects()

        self._check_fw4()
        self._reload_fw4()

        # Um reload pode preservar uma chain extra vazia.
        # Portanto fazemos limpeza final também.
        self._remove_runtime_objects()

        # Agora exigimos confirmação explícita de que inclusive
        # wolf_portal_prerouting desapareceu.
        self._verify_removal()

        self._log(
            "Regras Wolf Portal removidas."
        )

    def remove_managed_table(self) -> None:
        """
        Método mantido por compatibilidade com código antigo.

        IMPORTANTE:
        ele NÃO remove table inet fw4.

        Remove somente os objetos Wolf Portal.
        """

        self._remove_runtime_objects()

    # ================================================================
    # ROLLBACK
    # ================================================================

    def _rollback(self) -> None:

        self._rollback_started.set()

        self._log(
            "ROLLBACK AUTOMÁTICO INICIADO."
        )

        try:

            with self._lock:

                if self._confirmed:

                    self._log(
                        "Rollback ignorado: "
                        "aplicação já confirmada."
                    )

                    return

                self._restore_backup()

                self._log(
                    "Rollback concluído com sucesso."
                )

        except Exception as exc:

            self._log(
                "ERRO CRÍTICO durante rollback: "
                f"{type(exc).__name__}: {exc}"
            )

        finally:

            self._rollback_completed.set()

    # ================================================================
    # TIMER
    # ================================================================

    def _start_rollback_timer(self) -> None:

        self._rollback_started.clear()
        self._rollback_completed.clear()

        self._rollback_timer = Timer(
            self.rollback_seconds,
            self._rollback,
        )

        self._rollback_timer.daemon = True

        self._rollback_timer.start()

        self._log(
            f"Rollback programado para "
            f"{self.rollback_seconds} segundos."
        )

    # ================================================================
    # SAFE APPLY
    # ================================================================

    def apply_with_rollback(
        self,
        ruleset: str,
    ) -> None:

        self._confirmed = False

        self.apply_ruleset(
            ruleset
        )

        self._start_rollback_timer()

    # ================================================================
    # CONFIRM
    # ================================================================

    def confirm(self) -> None:

        with self._lock:

            if (
                self._rollback_timer
                is not None
            ):

                self._rollback_timer.cancel()
                self._rollback_timer = None

            self._confirmed = True

            self._log(
                "Aplicação CONFIRMADA. "
                "Rollback cancelado."
            )

    # ================================================================
    # STATUS
    # ================================================================

    @property
    def rollback_started(self) -> bool:
        return self._rollback_started.is_set()

    @property
    def rollback_completed(self) -> bool:
        return self._rollback_completed.is_set()

    def wait_for_rollback(
        self,
        timeout: float | None = None,
    ) -> bool:

        return self._rollback_completed.wait(
            timeout
        )

    @property
    def confirmed(self) -> bool:
        return self._confirmed