"""스키마 조회 권한과 공개할 테이블 범위를 관리한다."""

from typing import Protocol

from pydantic import BaseModel

from .models import SCHEMA_READ, UserContext
from .services import PermissionDeniedError

SCHEMA_NAME = "retail"
PUBLIC_TABLES = frozenset({"orders", "order_items", "products"})


class TableSchemaNotFoundError(LookupError):
    """공개 대상이 아니거나 존재하지 않는 테이블."""


class SchemaQueryError(RuntimeError):
    """원본 DB 오류를 숨기는 스키마 조회 실패."""


class SchemaQueryTimeoutError(SchemaQueryError):
    """스키마 조회 중 시간 초과."""


class SchemaColumn(BaseModel):
    column_name: str
    data_type: str
    is_nullable: bool


class SchemaForeignKey(BaseModel):
    constrained_columns: list[str]
    referenced_schema: str
    referenced_table: str
    referenced_columns: list[str]


class TableSchema(BaseModel):
    columns: list[SchemaColumn]
    primary_key: list[str]
    foreign_keys: list[SchemaForeignKey]


class SchemaReader(Protocol):
    async def table_schema(
        self, schema_name: str, table_name: str
    ) -> TableSchema | None: ...


class SchemaService:
    def __init__(self, repository: SchemaReader) -> None:
        self._repository = repository

    async def table_schema(self, user: UserContext, table_name: str) -> TableSchema:
        if SCHEMA_READ not in user.allowed_actions:
            raise PermissionDeniedError("스키마 정보 조회 권한이 없습니다")
        if table_name not in PUBLIC_TABLES:
            raise TableSchemaNotFoundError

        schema = await self._repository.table_schema(SCHEMA_NAME, table_name)
        if schema is None:
            raise TableSchemaNotFoundError
        return schema.model_copy(
            update={
                "foreign_keys": [
                    key
                    for key in schema.foreign_keys
                    if key.referenced_schema == SCHEMA_NAME
                    and key.referenced_table in PUBLIC_TABLES
                ],
            }
        )
