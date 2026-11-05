"""MCP 서버 객체를 구성한다. 생성 시 네트워크나 DB에 접속하지 않는다."""

from mcp.server import MCPServer


def create_server() -> MCPServer[None]:
    """후속 단계에서 도구를 등록할 서버를 반환한다."""
    return MCPServer(name="Zava Retail MCP", version="0.1.0")
