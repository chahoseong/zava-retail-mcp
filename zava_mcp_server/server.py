"""MCP 서버 객체를 구성하고 준비된 서비스의 수명주기를 등록한다."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from mcp.server import MCPServer

from .services import SalesService


def create_server(
    lifespan: Callable[
        [MCPServer[SalesService]], AbstractAsyncContextManager[SalesService]
    ],
) -> MCPServer[SalesService]:
    return MCPServer(name="Zava Retail MCP", version="0.1.0", lifespan=lifespan)
