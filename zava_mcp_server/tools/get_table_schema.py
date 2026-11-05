"""매출 분석 테이블의 메타데이터 조회 MCP 도구."""

from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, StrictStr

from ..schema_service import (
    SchemaColumn,
    SchemaQueryError,
    SchemaQueryTimeoutError,
    TableSchemaNotFoundError,
)
from ..server_context import ServerContext
from ..services import PermissionDeniedError


class ForeignKeyOutput(BaseModel):
    constrained_columns: list[str]
    referenced_table: str
    referenced_columns: list[str]


class TableSchemaOutput(BaseModel):
    table_name: str
    columns: list[SchemaColumn]
    primary_key: list[str]
    foreign_keys: list[ForeignKeyOutput]


async def get_table_schema(
    table_name: Annotated[
        StrictStr,
        Field(description="조회할 테이블 이름 (orders, order_items, products)"),
    ],
    ctx: Context[ServerContext, object],
) -> TableSchemaOutput:
    """매출 분석 테이블의 열, 자료형, 기본 키와 외래 키를 반환합니다."""
    context = ctx.request_context.lifespan_context
    try:
        schema = await context.schema_service.table_schema(context.user, table_name)
    except PermissionDeniedError:
        raise ToolError("스키마 정보 조회 권한이 없습니다") from None
    except TableSchemaNotFoundError:
        raise ToolError(
            "공개 대상이 아닌 테이블이거나 존재하지 않는 테이블입니다"
        ) from None
    except SchemaQueryTimeoutError:
        raise ToolError("스키마 조회 시간이 초과되었습니다") from None
    except SchemaQueryError:
        raise ToolError("데이터베이스에서 스키마 정보를 조회하지 못했습니다") from None

    return TableSchemaOutput(
        table_name=table_name,
        columns=schema.columns,
        primary_key=schema.primary_key,
        foreign_keys=[
            ForeignKeyOutput(
                constrained_columns=key.constrained_columns,
                referenced_table=key.referenced_table,
                referenced_columns=key.referenced_columns,
            )
            for key in schema.foreign_keys
        ],
    )
