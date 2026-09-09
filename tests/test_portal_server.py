import inspect
import sys
import threading
import urllib.error
import urllib.request

from app.portal_server import (
    WolfPortalHandler,
    WolfPortalHTTPServer,
)
from app.portal_service import PortalService


class NoRedirectHandler(
    urllib.request.HTTPRedirectHandler
):
    """
    Impede urllib de seguir respostas HTTP 3xx.

    Assim conseguimos inspecionar diretamente o 302
    produzido pelo captive portal.
    """

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


def create_test_server():
    """
    Usa porta 0 para o sistema escolher automaticamente
    uma porta TCP livre.

    Isso evita qualquer interferência com a porta 81
    utilizada pela instalação real do Wolf Portal.
    """

    service = PortalService()

    return WolfPortalHTTPServer(
        ("127.0.0.1", 0),
        WolfPortalHandler,
        portal_service=service,
    )


def start_test_server():
    server = create_test_server()

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    return server, thread


def stop_test_server(
    server,
    thread,
):
    server.shutdown()
    server.server_close()

    thread.join(
        timeout=3
    )


def expected_portal_location(
    server,
) -> str:
    """
    Retorna a URL canônica esperada do portal para
    a instância atual.

    Nos testes a porta é dinâmica.

    Na instalação real, executada na porta 81, o
    resultado será:

        http://status.client:81/
    """

    port = server.server_address[1]

    return (
        f"http://status.client:{port}/"
    )


def test_handler_exists():
    assert WolfPortalHandler is not None


def test_server_class_exists():
    assert WolfPortalHTTPServer is not None


def test_server_can_be_created():
    server = create_test_server()

    try:
        host, port = server.server_address

        assert host == "127.0.0.1"
        assert port > 0

    finally:
        server.server_close()


def test_health_endpoint():
    server, thread = (
        start_test_server()
    )

    try:
        host, port = server.server_address

        with urllib.request.urlopen(
            f"http://{host}:{port}/health",
            timeout=3,
        ) as response:

            body = (
                response.read()
                .decode("utf-8")
            )

            assert (
                response.status
                == 200
            )

            assert (
                '"status": "ok"'
                in body
            )

            assert (
                '"service": "wolf-portal"'
                in body
            )

    finally:
        stop_test_server(
            server,
            thread,
        )


def test_unknown_http_path_redirects_to_portal():
    """
    Em um captive portal, uma URL HTTP arbitrária
    deve ser redirecionada para a página canônica
    do Wolf Portal.
    """

    server, thread = (
        start_test_server()
    )

    opener = urllib.request.build_opener(
        NoRedirectHandler()
    )

    try:
        host, port = server.server_address

        try:
            opener.open(
                f"http://{host}:{port}/nao-existe",
                timeout=3,
            )

        except urllib.error.HTTPError as exc:

            assert (
                exc.code
                == 302
            )

            assert (
                exc.headers.get(
                    "Location"
                )
                == expected_portal_location(
                    server
                )
            )

        else:
            raise AssertionError(
                "URL HTTP arbitrária deveria "
                "ser redirecionada para o portal."
            )

    finally:
        stop_test_server(
            server,
            thread,
        )


def test_android_captive_probe_redirects_to_portal():
    """
    Simula uma requisição ao endpoint /generate_204,
    usado em mecanismos de detecção de captive portal.

    O Wolf Portal deve responder com HTTP 302 para
    sua página canônica.
    """

    server, thread = (
        start_test_server()
    )

    opener = urllib.request.build_opener(
        NoRedirectHandler()
    )

    try:
        host, port = server.server_address

        request = urllib.request.Request(
            f"http://{host}:{port}/generate_204",
            headers={
                "Host":
                    "connectivitycheck.gstatic.com",
            },
        )

        try:
            opener.open(
                request,
                timeout=3,
            )

        except urllib.error.HTTPError as exc:

            assert (
                exc.code
                == 302
            )

            assert (
                exc.headers.get(
                    "Location"
                )
                == expected_portal_location(
                    server
                )
            )

        else:
            raise AssertionError(
                "Probe de captive portal deveria "
                "receber redirecionamento HTTP 302."
            )

    finally:
        stop_test_server(
            server,
            thread,
        )


def test_redirect_uses_current_server_port():
    """
    Garante explicitamente que a URL canônica usa
    a porta real da instância.

    Isso é importante porque:

        testes -> porta dinâmica
        produção -> porta 81
    """

    server, thread = (
        start_test_server()
    )

    opener = urllib.request.build_opener(
        NoRedirectHandler()
    )

    try:
        host, port = server.server_address

        try:
            opener.open(
                f"http://{host}:{port}/teste-porta",
                timeout=3,
            )

        except urllib.error.HTTPError as exc:

            location = (
                exc.headers.get(
                    "Location"
                )
            )

            assert (
                exc.code
                == 302
            )

            assert (
                location
                == f"http://status.client:{port}/"
            )

        else:
            raise AssertionError(
                "Era esperado um redirecionamento."
            )

    finally:
        stop_test_server(
            server,
            thread,
        )


def run_tests():
    tests = [
        obj
        for name, obj in globals().items()
        if (
            name.startswith("test_")
            and inspect.isfunction(obj)
        )
    ]

    failed = 0

    for test in tests:

        try:
            test()

            print(
                f"[PASS] {test.__name__}"
            )

        except Exception as exc:
            failed += 1

            print(
                f"[FAIL] {test.__name__}: "
                f"{type(exc).__name__}: "
                f"{exc!r}"
            )

    print()

    print(
        f"Testes: {len(tests)}"
    )

    print(
        f"Falhas: {failed}"
    )

    return failed


if __name__ == "__main__":
    sys.exit(
        run_tests()
    )