"""MCP 서버 객체를 구성한다. 생성 시 네트워크나 DB에 접속하지 않는다."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from .runtime import RuntimeContext, RuntimeStatus, open_runtime
from .settings import Settings


def create_server(
    settings: Settings, status: RuntimeStatus
) -> MCPServer[RuntimeContext]:
    """풀 수명주기를 연결한다. 실제 풀 생성은 서버 시작 시 수행한다."""

    @asynccontextmanager
    async def lifespan(
        _: MCPServer[RuntimeContext],
    ) -> AsyncGenerator[RuntimeContext, None]:
        status.started = False
        async with open_runtime(settings) as context:
            status.started = True
            yield context

    return MCPServer(name="Zava Retail MCP", version="0.1.0", lifespan=lifespan)
