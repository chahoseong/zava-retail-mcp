"""검증된 설정으로 로컬 Streamable HTTP 서버를 실행한다."""

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .database import SalesRepository
from .runtime import RuntimeStatus, open_runtime
from .schema_repository import SchemaRepository
from .schema_service import SchemaService
from .server import create_server
from .server_context import ServerContext
from .services import SalesService
from .settings import Settings, SettingsError, load_settings


def build_server(settings: Settings, status: RuntimeStatus) -> MCPServer[ServerContext]:
    @asynccontextmanager
    async def lifespan(
        _: MCPServer[ServerContext],
    ) -> AsyncGenerator[ServerContext, None]:
        status.started = False
        async with open_runtime(settings) as runtime:
            context = ServerContext(
                service=SalesService(
                    SalesRepository(runtime.pool, runtime.acquire_timeout)
                ),
                user=settings.user,
                schema_service=SchemaService(
                    SchemaRepository(runtime.pool, runtime.acquire_timeout)
                ),
            )
            status.started = True
            yield context

    return create_server(lifespan)


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
    status = RuntimeStatus()
    server = build_server(settings, status)
    try:
        server.run(
            transport="streamable-http",
            host=settings.server.host,
            port=settings.server.port,
            streamable_http_path=settings.server.path,
            transport_security=security,
        )
    except SystemExit:
        if status.started:
            raise
        return 1
    # SDK의 HTTP 실행기는 수명주기 시작 실패를 기록하고 반환할 수 있다.
    return 0 if status.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
