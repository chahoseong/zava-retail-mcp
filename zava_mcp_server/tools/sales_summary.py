"""매장별 매출 요약 MCP 도구."""

from datetime import date
from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, StrictInt

from ..models import SalesQueryError, SalesQueryTimeoutError, SalesSummaryQuery
from ..server_context import ServerContext
from ..services import PermissionDeniedError
from .types import ToolDate


class SalesSummaryOutput(BaseModel):
    store_id: int
    start_date: date
    end_date: date
    total_sales: str = Field(description="소수점 두 자리로 표시한 매출 합계")
    order_count: int


async def get_sales_summary(
    store_id: Annotated[StrictInt, Field(description="조회할 매장 ID")],
    start_date: Annotated[ToolDate, Field(description="시작일 (YYYY-MM-DD, 포함)")],
    end_date: Annotated[ToolDate, Field(description="종료일 (YYYY-MM-DD, 포함)")],
    ctx: Context[ServerContext, object],
) -> SalesSummaryOutput:
    """지정한 매장과 기간의 매출 합계와 주문 건수를 반환합니다."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise ToolError("시작일과 종료일은 유효한 달력 날짜여야 합니다") from None

    context = ctx.request_context.lifespan_context
    try:
        summary = await context.service.sales_summary(
            context.user, SalesSummaryQuery(store_id, start, end)
        )
    except PermissionDeniedError:
        raise ToolError("요청한 매장의 매출 조회 권한이 없습니다") from None
    except ValueError:
        raise ToolError(
            "조회 조건을 확인하세요. 매장 ID, 날짜 순서와 최대 366일을 확인하세요"
        ) from None
    except SalesQueryTimeoutError:
        raise ToolError("매출 조회 시간이 초과되었습니다") from None
    except SalesQueryError:
        raise ToolError("데이터베이스에서 매출을 조회하지 못했습니다") from None

    return SalesSummaryOutput(
        store_id=store_id,
        start_date=start,
        end_date=end,
        total_sales=format(summary.total_sales, ".2f"),
        order_count=summary.order_count,
    )
