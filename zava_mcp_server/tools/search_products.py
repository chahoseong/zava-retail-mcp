"""대상 매장에서 취급하는 상품을 찾는 MCP 도구."""

from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, StrictInt, StrictStr, ValidationError

from ..models import ProductSearchInput, ProductSearchResults, StoreId
from ..product_search_service import (
    ProductSearchEmbeddingError,
    ProductSearchQueryError,
    ProductSearchUnavailableError,
)
from ..server_context import ServerContext
from ..services import PermissionDeniedError


class ProductSearchOutput(BaseModel):
    products: ProductSearchResults


async def search_products(
    query: Annotated[
        StrictStr, Field(description="검색어 (앞뒤 공백 제거 후 1~256자)")
    ],
    store_id: Annotated[StoreId, Field(description="검색할 매장 ID")],
    limit: Annotated[StrictInt, Field(ge=1, le=10, description="최대 결과 수 (1~10)")],
    ctx: Context[ServerContext, object],
) -> ProductSearchOutput:
    """대상 매장의 취급 상품을 유사도순으로 반환합니다. 재고가 0인 상품도 포함할 수 있습니다."""
    try:
        request = ProductSearchInput(query=query, store_id=store_id, limit=limit)
    except ValidationError:
        raise ToolError("상품 검색 조건을 확인하세요") from None

    context = ctx.request_context.lifespan_context
    try:
        products = await context.product_search_service.search(context.user, request)
    except (
        PermissionDeniedError,
        ProductSearchUnavailableError,
        ProductSearchEmbeddingError,
        ProductSearchQueryError,
    ) as error:
        raise ToolError(str(error)) from None
    return ProductSearchOutput(products=products)
