"""검증된 설정으로 로컬 Streamable HTTP 서버를 실행한다."""

import sys

from mcp.server.transport_security import TransportSecuritySettings

from .server import create_server
from .settings import SettingsError, load_settings


def main() -> int:
    """설정을 한 번 읽고 서버를 실행하며, 설정 오류는 안전하게 보고한다."""
    try:
        settings = load_settings()
        if settings.server.host != "127.0.0.1":
            raise SettingsError("MCP_HOST: 서버 실행에는 127.0.0.1만 허용합니다")
    except SettingsError as error:
        print(f"설정 오류: {error}", file=sys.stderr)
        return 1

    authority = f"127.0.0.1:{settings.server.port}"
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[authority],
        allowed_origins=[f"http://{authority}"],
    )
    server = create_server()
    server.run(
        transport="streamable-http",
        host=settings.server.host,
        port=settings.server.port,
        streamable_http_path=settings.server.path,
        transport_security=security,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
