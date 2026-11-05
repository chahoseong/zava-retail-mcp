"""MCP 서버를 구성하고 공개할 도구를 등록한다."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from mcp.server import MCPServer

from .server_context import ServerContext
from .tools.compare_store_sales import compare_store_sales
from .tools.get_table_schema import get_table_schema
from .tools.sales_summary import get_sales_summary
from .tools.top_products import get_top_products


def create_server(
    lifespan: Callable[
        [MCPServer[ServerContext]], AbstractAsyncContextManager[ServerContext]
    ],
) -> MCPServer[ServerContext]:
    server = MCPServer(name="Zava Retail MCP", version="0.1.0", lifespan=lifespan)
    server.add_tool(get_top_products, structured_output=True)
    server.add_tool(get_sales_summary, structured_output=True)
    server.add_tool(compare_store_sales, structured_output=True)
    server.add_tool(get_table_schema, structured_output=True)
    return server
