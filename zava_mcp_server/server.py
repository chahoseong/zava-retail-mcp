"""MCP 서버 객체를 구성하고 준비된 서비스의 수명주기를 등록한다."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, StrictInt

from .models import SalesQuery, SalesQueryError, SalesQueryTimeoutError, UserContext
from .services import PermissionDeniedError, SalesService

ToolDate = Annotated[str, Field(strict=True, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]


class ProductOutput(BaseModel):
    product_id: int
    product_name: str
    total_amount: str = Field(description="정확한 매출 금액의 십진 문자열")


class TopProductsOutput(BaseModel):
    store_id: int
    start_date: date
    end_date: date
    products: list[ProductOutput]


def create_server(
    lifespan: Callable[
        [MCPServer[SalesService]], AbstractAsyncContextManager[SalesService]
    ],
    user: UserContext,
) -> MCPServer[SalesService]:
    server = MCPServer(name="Zava Retail MCP", version="0.1.0", lifespan=lifespan)

    @server.tool(structured_output=True)
    async def get_top_products(
        store_id: Annotated[StrictInt, Field(description="조회할 매장 ID")],
        start_date: Annotated[ToolDate, Field(description="시작일 (YYYY-MM-DD, 포함)")],
        end_date: Annotated[ToolDate, Field(description="종료일 (YYYY-MM-DD, 포함)")],
        limit: Annotated[StrictInt, Field(description="반환할 상품 수 (1~20)")],
        ctx: Context[SalesService, object],
    ) -> TopProductsOutput:
        """지정한 매장과 기간의 주문 상세 거래 금액을 상품별로 합산해 매출 상위 상품을 반환합니다. 동률은 상품 ID 오름차순으로 정렬합니다."""
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            raise ToolError("시작일과 종료일은 유효한 달력 날짜여야 합니다") from None

        service = ctx.request_context.lifespan_context
        try:
            rows = await service.top_products(
                user, SalesQuery(store_id, start, end, limit)
            )
        except PermissionDeniedError:
            raise ToolError("요청한 매장의 매출 조회 권한이 없습니다") from None
        except ValueError:
            raise ToolError(
                "조회 조건을 확인하세요. 매장 ID, 날짜 순서와 최대 366일, 결과 수 1~20을 확인하세요"
            ) from None
        except SalesQueryTimeoutError:
            raise ToolError("매출 조회 시간이 초과되었습니다") from None
        except SalesQueryError:
            raise ToolError("데이터베이스에서 매출을 조회하지 못했습니다") from None

        return TopProductsOutput(
            store_id=store_id,
            start_date=start,
            end_date=end,
            products=[
                ProductOutput(
                    product_id=row.product_id,
                    product_name=row.product_name,
                    total_amount=format(row.total_amount, "f"),
                )
                for row in rows
            ],
        )

    return server
