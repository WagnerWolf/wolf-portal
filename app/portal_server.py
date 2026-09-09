from __future__ import annotations

import argparse
import html
import json

from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from app.models import DeviceStatus
from app.portal_service import (
    AccessRequestResult,
    PortalClient,
    PortalService,
)


# ================================================================
# CONFIGURAÇÃO PÚBLICA DO PORTAL
# ================================================================

PORTAL_HOSTNAME = "status.client"
ROUTER_IPV4 = "10.0.69.1"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 81


class WolfPortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        portal_service: PortalService,
    ):
        super().__init__(
            server_address,
            RequestHandlerClass,
        )

        self.portal_service = portal_service


class WolfPortalHandler(BaseHTTPRequestHandler):
    server_version = "WolfPortal/1.1"

    # ================================================================
    # Logging HTTP
    # ================================================================

    def log_message(
        self,
        format,
        *args,
    ):
        print(
            "[portal-http] "
            + format % args,
            flush=True,
        )

    # ================================================================
    # Helpers
    # ================================================================

    @property
    def portal_service(self) -> PortalService:
        return self.server.portal_service

    @property
    def remote_ip(self) -> str:
        return self.client_address[0]

    @property
    def portal_url(self) -> str:
        port = self.server.server_address[1]

        return (
            f"http://{PORTAL_HOSTNAME}:{port}/"
        )

    def _host_is_portal(self) -> bool:
        """
        Retorna True quando o request já está sendo feito
        diretamente para o Wolf Portal.

        Requisições HTTP interceptadas normalmente chegam com:

            Host: connectivitycheck.gstatic.com

        ou:

            Host: www.msftconnecttest.com

        etc.

        Nesse caso o servidor envia redirect HTTP para o endereço
        canônico:

            http://status.client:81/
        """

        host = str(
            self.headers.get(
                "Host",
                "",
            )
        ).strip().lower()

        if not host:
            return False

        # Remove porta quando presente.
        hostname = host

        if host.startswith("["):
            # Não utilizamos IPv6 no captive portal nesta fase,
            # mas não interpretamos incorretamente um literal IPv6.
            return False

        if ":" in hostname:
            hostname = hostname.split(
                ":",
                1,
            )[0]

        allowed = {
            PORTAL_HOSTNAME.lower(),
            ROUTER_IPV4,
            "127.0.0.1",
            "localhost",
        }

        return hostname in allowed

    def _send_headers(
        self,
        status_code: int,
        content_type: str,
        content_length: int,
    ):
        self.send_response(
            status_code
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(content_length),
        )

        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate",
        )

        self.send_header(
            "Pragma",
            "no-cache",
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )

        self.send_header(
            "X-Frame-Options",
            "DENY",
        )

        self.send_header(
            "Referrer-Policy",
            "no-referrer",
        )

        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'none'; "
                "style-src 'unsafe-inline'; "
                "form-action 'self'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'"
            ),
        )

        self.end_headers()

    def _send_html(
        self,
        html_text: str,
        status_code: int = 200,
    ):
        body = html_text.encode(
            "utf-8"
        )

        self._send_headers(
            status_code,
            "text/html; charset=utf-8",
            len(body),
        )

        self.wfile.write(
            body
        )

    def _send_json(
        self,
        data,
        status_code: int = 200,
    ):
        body = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ).encode(
            "utf-8"
        )

        self._send_headers(
            status_code,
            "application/json; charset=utf-8",
            len(body),
        )

        self.wfile.write(
            body
        )

    def _send_redirect(
        self,
        location: str | None = None,
        status_code: int = 302,
    ):
        """
        Envia redirect para o endereço canônico do Wolf Portal.

        Utilizado principalmente quando uma conexão HTTP externa
        foi interceptada pelo nftables.
        """

        destination = (
            location
            or self.portal_url
        )

        self.send_response(
            status_code
        )

        self.send_header(
            "Location",
            destination,
        )

        self.send_header(
            "Content-Length",
            "0",
        )

        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate",
        )

        self.send_header(
            "Pragma",
            "no-cache",
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )

        self.end_headers()

    # ================================================================
    # Página
    # ================================================================

    @staticmethod
    def _status_information(
        client: PortalClient,
    ) -> tuple[str, str, bool]:

        if not client.identified:
            return (
                "Dispositivo não identificado",
                (
                    "Não foi possível localizar este dispositivo "
                    "no cadastro do Wolf Portal."
                ),
                False,
            )

        if client.status == DeviceStatus.PENDING.value:
            return (
                "Aguardando autorização",
                (
                    "Este dispositivo ainda não possui acesso "
                    "à Internet. Você pode solicitar autorização "
                    "ao administrador."
                ),
                True,
            )

        if client.status == DeviceStatus.AUTHORIZED.value:
            return (
                "Acesso autorizado",
                (
                    "Este dispositivo está autorizado a utilizar "
                    "a rede."
                ),
                False,
            )

        if client.status == DeviceStatus.BLOCKED.value:
            return (
                "Acesso bloqueado",
                (
                    "O acesso deste dispositivo foi bloqueado "
                    "pelo administrador."
                ),
                False,
            )

        if client.status == DeviceStatus.DISABLED.value:
            return (
                "Dispositivo desativado",
                (
                    "Este dispositivo está desativado no "
                    "Wolf Portal."
                ),
                False,
            )

        return (
            "Estado desconhecido",
            (
                "Não foi possível determinar o estado "
                "do dispositivo."
            ),
            False,
        )

    @staticmethod
    def _notice_for_result(
        result: AccessRequestResult | None,
    ) -> tuple[str, str] | None:

        if result is None:
            return None

        mapping = {
            AccessRequestResult.REQUEST_RECORDED: (
                "success",
                (
                    "Solicitação enviada. Aguarde a autorização "
                    "do administrador."
                ),
            ),

            AccessRequestResult.ALREADY_REQUESTED: (
                "info",
                (
                    "Sua solicitação já foi registrada. "
                    "Aguarde a autorização."
                ),
            ),

            AccessRequestResult.ALREADY_AUTHORIZED: (
                "success",
                "Este dispositivo já está autorizado.",
            ),

            AccessRequestResult.BLOCKED: (
                "error",
                (
                    "Este dispositivo está bloqueado pelo "
                    "administrador."
                ),
            ),

            AccessRequestResult.DISABLED: (
                "error",
                "Este dispositivo está desativado.",
            ),

            AccessRequestResult.DEVICE_UNKNOWN: (
                "error",
                (
                    "Não foi possível identificar o dispositivo "
                    "para registrar a solicitação."
                ),
            ),
        }

        return mapping[
            result
        ]

    def _render_page(
        self,
        client: PortalClient,
        request_result: AccessRequestResult | None = None,
    ) -> str:

        title, description, can_request = (
            self._status_information(
                client
            )
        )

        notice = (
            self._notice_for_result(
                request_result
            )
        )

        mac = (
            client.mac
            if client.mac
            else "Não identificado"
        )

        hostname = (
            client.hostname
            if client.hostname
            else "Não informado"
        )

        notice_html = ""

        if notice is not None:
            notice_type, notice_text = notice

            notice_html = f"""
            <div class="notice {html.escape(notice_type)}">
                {html.escape(notice_text)}
            </div>
            """

        form_html = ""

        if can_request:
            form_html = """
            <form method="post" action="/request-access">
                <button type="submit">
                    Solicitar acesso
                </button>
            </form>
            """

        return f"""<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>Wolf Portal</title>

    <style>
        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
            background: #0f1115;
            color: #e8e8e8;
            font-family:
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
        }}

        .card {{
            width: 100%;
            max-width: 520px;
            background: #191c22;
            border: 1px solid #2c313a;
            border-radius: 18px;
            padding: 30px;
            box-shadow:
                0 18px 60px rgba(0, 0, 0, .35);
        }}

        .logo {{
            font-size: 42px;
            line-height: 1;
            margin-bottom: 12px;
        }}

        h1 {{
            margin: 0;
            font-size: 28px;
        }}

        .subtitle {{
            margin-top: 7px;
            color: #939baa;
        }}

        .status {{
            margin-top: 28px;
            padding: 18px;
            border-radius: 13px;
            background: #101319;
            border: 1px solid #292f39;
        }}

        .status strong {{
            display: block;
            font-size: 18px;
            margin-bottom: 7px;
        }}

        .status p {{
            margin: 0;
            color: #b6bdc9;
            line-height: 1.5;
        }}

        .details {{
            margin-top: 22px;
        }}

        .row {{
            display: flex;
            justify-content: space-between;
            gap: 18px;
            padding: 10px 0;
            border-bottom: 1px solid #292f39;
        }}

        .row span:first-child {{
            color: #858e9e;
        }}

        .row span:last-child {{
            text-align: right;
            word-break: break-all;
        }}

        .notice {{
            margin-top: 22px;
            padding: 14px 16px;
            border-radius: 10px;
            line-height: 1.45;
        }}

        .notice.success {{
            background: #163524;
            border: 1px solid #245d3a;
        }}

        .notice.info {{
            background: #172d3e;
            border: 1px solid #285170;
        }}

        .notice.error {{
            background: #3b1d20;
            border: 1px solid #6b3036;
        }}

        form {{
            margin-top: 25px;
        }}

        button {{
            width: 100%;
            border: 0;
            border-radius: 12px;
            padding: 15px 20px;
            background: #2473d2;
            color: white;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
        }}

        button:active {{
            transform: translateY(1px);
        }}

        .footer {{
            margin-top: 25px;
            text-align: center;
            color: #656d7b;
            font-size: 12px;
        }}
    </style>
</head>

<body>
    <main class="card">

        <div class="logo">🐺</div>

        <h1>Wolf Portal</h1>

        <div class="subtitle">
            Controle de acesso à rede
        </div>

        <section class="status">

            <strong>
                {html.escape(title)}
            </strong>

            <p>
                {html.escape(description)}
            </p>

        </section>

        <section class="details">

            <div class="row">
                <span>IP</span>
                <span>{html.escape(client.ip)}</span>
            </div>

            <div class="row">
                <span>MAC</span>
                <span>{html.escape(mac)}</span>
            </div>

            <div class="row">
                <span>Dispositivo</span>
                <span>{html.escape(hostname)}</span>
            </div>

            <div class="row">
                <span>Status</span>
                <span>{html.escape(client.status or "DESCONHECIDO")}</span>
            </div>

        </section>

        {notice_html}

        {form_html}

        <div class="footer">
            Wolf Portal
        </div>

    </main>
</body>
</html>
"""

    # ================================================================
    # GET
    # ================================================================

    def do_GET(self):
        path = urlparse(
            self.path
        ).path

        # ------------------------------------------------------------
        # Endpoints internos nunca são redirecionados.
        # ------------------------------------------------------------

        if path == "/health":

            self._send_json(
                {
                    "status": "ok",
                    "service": "wolf-portal",
                }
            )

            return

        if path == "/api/status":

            client = (
                self.portal_service.identify_client(
                    self.remote_ip
                )
            )

            self._send_json(
                {
                    "ip": client.ip,
                    "mac": client.mac,
                    "hostname": client.hostname,
                    "status": client.status,
                    "identified": client.identified,
                }
            )

            return

        # ------------------------------------------------------------
        # CAPTIVE PORTAL
        #
        # Uma requisição capturada pelo nftables ainda possui o Host
        # original:
        #
        #   connectivitycheck.gstatic.com
        #   captive.apple.com
        #   www.msftconnecttest.com
        #
        # Não servimos a página usando esse domínio.
        #
        # Mandamos o navegador para o endereço canônico local.
        # ------------------------------------------------------------

        if not self._host_is_portal():

            self._send_redirect()

            return

        # ------------------------------------------------------------
        # Qualquer path de probe recebido no endereço do portal
        # também converge para a raiz.
        #
        # Exemplos:
        #
        #   /generate_204
        #   /gen_204
        #   /hotspot-detect.html
        #   /connecttest.txt
        #   /ncsi.txt
        #
        # Não precisamos depender de uma lista fechada.
        # ------------------------------------------------------------

        if path != "/":

            self._send_redirect()

            return

        client = (
            self.portal_service.identify_client(
                self.remote_ip
            )
        )

        self._send_html(
            self._render_page(
                client
            )
        )

    # ================================================================
    # HEAD
    # ================================================================

    def do_HEAD(self):
        """
        Alguns verificadores de conectividade podem usar HEAD.

        Requisições externas são redirecionadas para o portal.
        """

        path = urlparse(
            self.path
        ).path

        if path == "/health":

            self._send_headers(
                200,
                "application/json; charset=utf-8",
                0,
            )

            return

        if not self._host_is_portal():

            self._send_redirect()

            return

        if path != "/":

            self._send_redirect()

            return

        client = (
            self.portal_service.identify_client(
                self.remote_ip
            )
        )

        body = self._render_page(
            client
        ).encode(
            "utf-8"
        )

        self._send_headers(
            200,
            "text/html; charset=utf-8",
            len(body),
        )

    # ================================================================
    # POST
    # ================================================================

    def do_POST(self):
        path = urlparse(
            self.path
        ).path

        # POST vindo de host externo/interceptado não deve realizar
        # ação nenhuma. Primeiro converge para o endereço canônico.
        if not self._host_is_portal():

            self._send_redirect(
                status_code=303
            )

            return

        if path != "/request-access":

            self._send_html(
                "<h1>404</h1>",
                status_code=404,
            )

            return

        # Consome eventual corpo enviado pelo navegador.
        try:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

        except ValueError:
            content_length = 0

        if content_length > 0:
            self.rfile.read(
                min(
                    content_length,
                    4096,
                )
            )

        result = (
            self.portal_service.request_access(
                self.remote_ip
            )
        )

        client = (
            self.portal_service.identify_client(
                self.remote_ip
            )
        )

        self._send_html(
            self._render_page(
                client,
                request_result=result,
            )
        )


def run_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
):
    service = (
        PortalService()
    )

    server = WolfPortalHTTPServer(
        (host, port),
        WolfPortalHandler,
        portal_service=service,
    )

    print(
        "=============================================="
    )

    print(
        " WOLF PORTAL - SERVIDOR HTTP"
    )

    print(
        "=============================================="
    )

    print()

    print(
        f"Escutando em http://{host}:{port}"
    )

    print(
        f"URL pública: http://{PORTAL_HOSTNAME}:{port}/"
    )

    print(
        "Pressione Ctrl+C para encerrar."
    )

    print()

    try:
        server.serve_forever()

    except KeyboardInterrupt:

        print()

        print(
            "Encerrando servidor HTTP..."
        )

    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Servidor HTTP do Wolf Portal"
        )
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
    )

    args = parser.parse_args()

    run_server(
        host=args.host,
        port=args.port,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )