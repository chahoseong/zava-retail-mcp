"""MCP 도구에 제공하는 서버 수명주기 컨텍스트."""

from dataclasses import dataclass

from .models import UserContext
from .schema_service import SchemaService
from .services import SalesService


@dataclass(frozen=True)
class ServerContext:
    service: SalesService
    user: UserContext
    schema_service: SchemaService
