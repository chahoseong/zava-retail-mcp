"""담당 매장 간 매출 비교 MCP 도구."""

from datetime import date
from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, StrictInt

from ..models import SalesQueryError, SalesQueryTimeoutError
from ..server_context import ServerContext
from ..services import CompareStoreCountError, PermissionDeniedError
from .types import ToolDate


class StoreSalesOutput(BaseModel):
    store_id: int
    total_sales: str = Field(description="소수점 두 자리로 표시한 매출 합계")
    order_count: int


class CompareStoreSalesOutput(BaseModel):
    start_date: date
    end_date: date
    stores: list[StoreSalesOutput]


async def compare_store_sales(
    store_ids: Annotated[list[StrictInt], Field(description="비교할 매장 ID 목록")],
    start_date: Annotated[ToolDate, Field(description="시작일 (YYYY-MM-DD, 포함)")],
    end_date: Annotated[ToolDate, Field(description="종료일 (YYYY-MM-DD, 포함)")],
    ctx: Context[ServerContext, object],
) -> CompareStoreSalesOutput:
    """지정한 기간의 매출 합계와 주문 건수를 여러 매장에 대해 비교합니다."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise ToolError("시작일과 종료일은 유효한 달력 날짜여야 합니다") from None

    context = ctx.request_context.lifespan_context
    try:
        rows = await context.service.compare_store_sales(
            context.user, store_ids, start, end
        )
    except PermissionDeniedError:
        raise ToolError("요청한 매장의 매출 비교 권한이 없습니다") from None
    except CompareStoreCountError as exc:
        raise ToolError(str(exc)) from None
    except ValueError:
        raise ToolError(
            "조회 조건을 확인하세요. 매장 ID, 날짜 순서와 최대 366일을 확인하세요"
        ) from None
    except SalesQueryTimeoutError:
        raise ToolError("매출 조회 시간이 초과되었습니다") from None
    except SalesQueryError:
        raise ToolError("데이터베이스에서 매출을 조회하지 못했습니다") from None

    return CompareStoreSalesOutput(
        start_date=start,
        end_date=end,
        stores=[
            StoreSalesOutput(
                store_id=store_id,
                total_sales=format(summary.total_sales, ".2f"),
                order_count=summary.order_count,
            )
            for store_id, summary in rows
        ],
    )
