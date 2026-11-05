"""MCP 도구에 제공하는 서버 수명주기 컨텍스트."""

from dataclasses import dataclass

from .models import UserContext
from .services import SalesService


@dataclass(frozen=True)
class ServerContext:
    service: SalesService
    user: UserContext
