from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from threading import Event
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from mcp import Client

from zava_mcp_server.models import (
    ProductSales,
    ProductSearchResult,
    SalesQuery,
    SalesQueryError,
    SalesQueryTimeoutError,
    SalesSummary,
    SalesSummaryQuery,
    UserContext,
)
from zava_mcp_server.product_search_service import ProductSearchService
from zava_mcp_server.schema_service import SchemaService, TableSchema
from zava_mcp_server.server import create_server
from zava_mcp_server.server_context import ServerContext
from zava_mcp_server.services import SalesService

ARGS = {"store_id": 1, "start_date": "2020-01-01", "end_date": "2020-01-31", "limit": 5}
SECRET = "FAKE_DRIVER_SECRET"
TOOL = "get_top_products"
SUMMARY_TOOL = "get_sales_summary"
SUMMARY_ARGS = {key: value for key, value in ARGS.items() if key != "limit"}
COMPARE_TOOL = "compare_store_sales"
SCHEMA_TOOL = "get_table_schema"
SEARCH_TOOL = "search_products"
SEARCH_ARGS = {"query": "  folding workbench  ", "store_id": 1, "limit": 3}
COMPARE_ACTIONS = ("sales:read", "sales:compare")
COMPARE_ARGS = {
    "store_ids": [2, 1, 2],
    "start_date": "2020-01-01",
    "end_date": "2020-01-31",
}


def server_for(
    service,
    actions=("sales:read",),
    stores=(1,),
    schema_repository=None,
    product_search_service=None,
):
    user = UserContext.model_validate(
        {
            "user_id": "test",
            "allowed_actions": list(actions),
            "allowed_store_ids": list(stores),
        }
    )

    @asynccontextmanager
    async def lifespan(_):
        yield ServerContext(
            service=service,
            user=user,
            schema_service=SchemaService(
                schema_repository if schema_repository is not None else AsyncMock()
            ),
            product_search_service=(
                product_search_service
                if product_search_service is not None
                else ProductSearchService(None, AsyncMock())
            ),
        )

    return create_server(lifespan)


@pytest.mark.asyncio
async def test_tool_contract_and_decimal_response():
    service = AsyncMock()
    service.top_products.return_value = [
        ProductSales(400, "Workbench", Decimal("125.30"))
    ]
    async with Client(server_for(service)) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            TOOL,
            SUMMARY_TOOL,
            COMPARE_TOOL,
            SCHEMA_TOOL,
            SEARCH_TOOL,
        }
        tool = tools[0]
        assert "거래 금액" in tool.description
        assert (
            set(tool.input_schema["properties"])
            == set(tool.input_schema["required"])
            == ARGS.keys()
        )
        assert tool.input_schema["properties"]["limit"]["type"] == "integer"
        schema = tool.output_schema
        assert set(schema["required"]) == {
            "store_id",
            "start_date",
            "end_date",
            "products",
        }
        assert (
            schema["$defs"]["ProductOutput"]["properties"]["total_amount"]["type"]
            == "string"
        )
        result = await client.call_tool(TOOL, ARGS)
    assert not result.is_error
    assert result.structured_content == {
        "store_id": 1,
        "start_date": "2020-01-01",
        "end_date": "2020-01-31",
        "products": [
            {"product_id": 400, "product_name": "Workbench", "total_amount": "125.30"}
        ],
    }
    user, query = service.top_products.await_args.args
    assert user.user_id == "test"
    assert query == SalesQuery(1, date(2020, 1, 1), date(2020, 1, 31), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        {k: v for k, v in ARGS.items() if k != "limit"},
        ARGS | {"store_id": "1"},
        ARGS | {"limit": True},
        ARGS | {"limit": 5.0},
        ARGS | {"start_date": "2020-02-30"},
        ARGS | {"start_date": "2020-1-01"},
    ],
)
async def test_invalid_format_does_not_call_service(args):
    service = AsyncMock()
    async with Client(server_for(service)) as client:
        result = await client.call_tool(TOOL, args)
    assert result.is_error
    service.top_products.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes, actions, message",
    [
        ({"store_id": 2}, ("sales:read",), "권한이 없습니다"),
        ({}, (), "권한이 없습니다"),
        ({"end_date": "2019-12-31"}, ("sales:read",), "조회 조건"),
        ({"end_date": "2021-01-01"}, ("sales:read",), "조회 조건"),
        ({"limit": 21}, ("sales:read",), "조회 조건"),
    ],
)
async def test_service_rejection_does_not_call_repository(changes, actions, message):
    repo = AsyncMock()
    async with Client(server_for(SalesService(repo), actions)) as client:
        result = await client.call_tool(TOOL, ARGS | changes)
    assert result.is_error
    assert message in result.content[0].text
    assert result.structured_content is None
    repo.top_products.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, message",
    [
        (SalesQueryError(SECRET), "데이터베이스에서 매출을 조회하지 못했습니다"),
        (SalesQueryTimeoutError(SECRET), "시간이 초과되었습니다"),
    ],
)
@pytest.mark.parametrize(
    "tool, args, method",
    [(TOOL, ARGS, "top_products"), (SUMMARY_TOOL, SUMMARY_ARGS, "sales_summary")],
)
async def test_db_failures_are_safe_tool_errors(error, message, tool, args, method):
    service = AsyncMock()
    getattr(service, method).side_effect = error
    async with Client(server_for(service)) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error
    assert result.structured_content is None
    assert message in result.content[0].text
    assert SECRET not in result.model_dump_json()


@pytest.mark.asyncio
async def test_empty_period_is_success():
    service = AsyncMock()
    service.top_products.return_value = []
    async with Client(server_for(service)) as client:
        result = await client.call_tool(TOOL, ARGS)
    assert not result.is_error
    assert result.structured_content["products"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount, count, formatted", [("125.3", 2, "125.30"), ("0", 0, "0.00")]
)
async def test_sales_summary_contract(amount, count, formatted):
    repo = AsyncMock()
    repo.sales_summary.return_value = SalesSummary(Decimal(amount), count)
    async with Client(server_for(SalesService(repo))) as client:
        tools = (await client.list_tools()).tools
        tool = next(tool for tool in tools if tool.name == SUMMARY_TOOL)
        assert (
            set(tool.input_schema["properties"])
            == set(tool.input_schema["required"])
            == SUMMARY_ARGS.keys()
        )
        assert tool.output_schema["properties"]["total_sales"]["type"] == "string"
        assert tool.output_schema["properties"]["order_count"]["type"] == "integer"
        result = await client.call_tool(SUMMARY_TOOL, SUMMARY_ARGS)
    assert not result.is_error
    assert result.structured_content == SUMMARY_ARGS | {
        "total_sales": formatted,
        "order_count": count,
    }
    repo.sales_summary.assert_awaited_once_with(
        SalesSummaryQuery(1, date(2020, 1, 1), date(2020, 1, 31))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes, actions, message",
    [
        ({"store_id": 2}, ("sales:read",), "권한이 없습니다"),
        ({}, (), "권한이 없습니다"),
        ({"start_date": "2020/01/01"}, ("sales:read",), None),
        ({"start_date": "2020-02-30"}, ("sales:read",), "유효한 달력 날짜"),
        ({"end_date": "2019-12-31"}, ("sales:read",), "조회 조건"),
        ({"end_date": "2021-01-01"}, ("sales:read",), "조회 조건"),
    ],
)
async def test_sales_summary_rejection_does_not_call_repository(
    changes, actions, message
):
    repo = AsyncMock()
    async with Client(server_for(SalesService(repo), actions)) as client:
        result = await client.call_tool(SUMMARY_TOOL, SUMMARY_ARGS | changes)
    assert result.is_error
    assert result.structured_content is None
    if message:
        assert message in result.content[0].text
    repo.sales_summary.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stores", [(2, 1), tuple(range(10, 0, -1))])
async def test_compare_store_sales_preserves_order_and_awaits_each_store(stores):
    completed = []
    started = []

    async def summarize(query):
        assert started == completed
        assert query == SalesSummaryQuery(
            stores[len(completed)], date(2020, 1, 1), date(2020, 1, 31)
        )
        started.append(query.store_id)
        await anyio.sleep(0)
        completed.append(query.store_id)
        return SalesSummary(Decimal("125.3"), 2)

    repo = AsyncMock()
    repo.sales_summary.side_effect = summarize
    args = COMPARE_ARGS | {"store_ids": [*stores, stores[0]]}
    async with Client(
        server_for(SalesService(repo), COMPARE_ACTIONS, stores)
    ) as client:
        result = await client.call_tool(COMPARE_TOOL, args)
    assert not result.is_error
    assert completed == list(stores)
    assert result.structured_content == {
        "start_date": args["start_date"],
        "end_date": args["end_date"],
        "stores": [
            {"store_id": store_id, "total_sales": "125.30", "order_count": 2}
            for store_id in stores
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes, actions, stores, message",
    [
        ({}, ("sales:compare",), (1, 2), "매출 비교 권한"),
        ({}, ("sales:read",), (1,), "매출 비교 권한"),
        ({}, COMPARE_ACTIONS, (2,), "매출 비교 권한"),
        ({"store_ids": []}, COMPARE_ACTIONS, (1, 2), "2개 이상 10개 이하"),
        ({"store_ids": [1, 1]}, COMPARE_ACTIONS, (1, 2), "2개 이상 10개 이하"),
        (
            {"store_ids": list(range(1, 12))},
            COMPARE_ACTIONS,
            tuple(range(1, 12)),
            "2개 이상 10개 이하",
        ),
        ({"store_ids": [0, 2]}, COMPARE_ACTIONS, (1, 2), "조회 조건"),
        ({"store_ids": [True, 2]}, COMPARE_ACTIONS, (1, 2), None),
        ({"end_date": "2020-02-30"}, COMPARE_ACTIONS, (1, 2), "유효한 달력 날짜"),
        ({"end_date": "2021-01-01"}, COMPARE_ACTIONS, (1, 2), "조회 조건"),
    ],
)
async def test_compare_rejects_entire_request_before_db(
    changes, actions, stores, message
):
    repo = AsyncMock()
    async with Client(server_for(SalesService(repo), actions, stores)) as client:
        result = await client.call_tool(COMPARE_TOOL, COMPARE_ARGS | changes)
    assert result.is_error
    assert result.structured_content is None
    if message:
        assert message in result.content[0].text
    repo.sales_summary.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, message",
    [
        (SalesQueryTimeoutError(SECRET), "시간이 초과되었습니다"),
        (SalesQueryError(SECRET), "데이터베이스에서 매출을 조회하지 못했습니다"),
    ],
)
async def test_compare_db_failure_discards_partial_results(error, message):
    repo = AsyncMock()
    repo.sales_summary.side_effect = [SalesSummary(Decimal("125.30"), 2), error]
    async with Client(
        server_for(SalesService(repo), COMPARE_ACTIONS, (1, 2, 3))
    ) as client:
        result = await client.call_tool(
            COMPARE_TOOL, COMPARE_ARGS | {"store_ids": [2, 1, 3]}
        )
    assert result.is_error
    assert result.structured_content is None
    assert message in result.content[0].text
    assert SECRET not in result.model_dump_json()
    assert [call.args[0].store_id for call in repo.sales_summary.await_args_list] == [
        2,
        1,
    ]


@pytest.mark.asyncio
async def test_table_schema_filters_foreign_keys_by_schema_and_table():
    repo = AsyncMock()
    order_key = {
        "constrained_columns": ["order_id", "store_id"],
        "referenced_table": "orders",
        "referenced_columns": ["order_id", "store_id"],
    }
    columns = [
        {"column_name": "order_id", "data_type": "integer", "is_nullable": False}
    ]
    repo.table_schema.return_value = TableSchema.model_validate(
        {
            "columns": columns,
            "primary_key": ["order_id", "store_id"],
            "foreign_keys": [
                order_key | {"referenced_schema": "retail"},
                order_key | {"referenced_schema": "other"},
                order_key
                | {"referenced_schema": "retail", "referenced_table": "customers"},
            ],
        }
    )
    async with Client(server_for(AsyncMock(), ("schema:read",), (), repo)) as client:
        result = await client.call_tool(SCHEMA_TOOL, {"table_name": "order_items"})
    assert not result.is_error
    assert result.structured_content == {
        "table_name": "order_items",
        "columns": columns,
        "primary_key": ["order_id", "store_id"],
        "foreign_keys": [order_key],
    }
    repo.table_schema.assert_awaited_once_with("retail", "order_items")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actions, table_name, message",
    [
        (("sales:read",), "orders", "스키마 정보 조회 권한이 없습니다"),
        (("schema:read",), "customers", "공개 대상이 아닌 테이블"),
        (("schema:read",), "other.orders", "공개 대상이 아닌 테이블"),
    ],
)
async def test_table_schema_rejects_before_repository(actions, table_name, message):
    repo = AsyncMock()
    async with Client(server_for(AsyncMock(), actions, (), repo)) as client:
        result = await client.call_tool(SCHEMA_TOOL, {"table_name": table_name})
    assert result.is_error
    assert message in result.content[0].text
    repo.table_schema.assert_not_called()


@pytest.mark.asyncio
async def test_table_schema_missing_public_table_uses_same_error():
    repo = AsyncMock()
    repo.table_schema.return_value = None
    async with Client(server_for(AsyncMock(), ("schema:read",), (), repo)) as client:
        result = await client.call_tool(SCHEMA_TOOL, {"table_name": "orders"})
    assert result.is_error
    assert (
        "공개 대상이 아닌 테이블이거나 존재하지 않는 테이블입니다"
        in result.content[0].text
    )
    repo.table_schema.assert_awaited_once_with("retail", "orders")


@pytest.mark.asyncio
@pytest.mark.parametrize("has_products", [True, False])
async def test_product_search_returns_structured_products(has_products):
    repository = AsyncMock()
    products = (
        [
            ProductSearchResult(
                product_id=1,
                product_name="Workbench",
                product_description="Folding",
                similarity_score=0.7,
            )
        ]
        if has_products
        else []
    )
    repository.search.return_value = products
    embedder = Mock()
    embedder.embed_query.return_value = [0.1]
    service = ProductSearchService(embedder, repository)
    async with Client(
        server_for(AsyncMock(), ("catalog:read",), product_search_service=service)
    ) as client:
        tools = (await client.list_tools()).tools
        tool = next(tool for tool in tools if tool.name == SEARCH_TOOL)
        assert set(tool.input_schema["required"]) == SEARCH_ARGS.keys()
        assert tool.output_schema["required"] == ["products"]
        result = await client.call_tool(SEARCH_TOOL, SEARCH_ARGS)
    assert not result.is_error
    assert result.structured_content == {"products": [p.model_dump() for p in products]}
    embedder.embed_query.assert_called_once_with("folding workbench")
    repository.search.assert_awaited_once_with(1, [0.1], 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actions, stores, query, message",
    [
        (("sales:read",), (1,), "workbench", "상품 검색 권한이 없습니다"),
        (("catalog:read",), (2,), "workbench", "상품 검색 권한이 없습니다"),
        (("catalog:read",), (1,), "  ", "상품 검색 조건을 확인하세요"),
    ],
)
async def test_product_search_rejects_before_embedding(actions, stores, query, message):
    repository, embedder = AsyncMock(), Mock()
    service = ProductSearchService(embedder, repository)
    async with Client(
        server_for(AsyncMock(), actions, stores, product_search_service=service)
    ) as client:
        result = await client.call_tool(SEARCH_TOOL, SEARCH_ARGS | {"query": query})
    assert result.is_error and message in result.content[0].text
    embedder.embed_query.assert_not_called()
    repository.search.assert_not_called()


@pytest.mark.asyncio
async def test_product_search_embedding_error_does_not_call_repository():
    repository, embedder = AsyncMock(), Mock()
    embedder.embed_query.side_effect = ValueError(SECRET)
    service = ProductSearchService(embedder, repository)
    async with Client(
        server_for(AsyncMock(), ("catalog:read",), product_search_service=service)
    ) as client:
        result = await client.call_tool(SEARCH_TOOL, SEARCH_ARGS)
    assert (
        result.is_error and "검색어를 임베딩하지 못했습니다" in result.content[0].text
    )
    assert SECRET not in result.model_dump_json()
    repository.search.assert_not_called()


@pytest.mark.asyncio
async def test_product_search_serializes_inference_without_blocking_other_tools():
    first_started, release_first = Event(), Event()
    second_requested = anyio.Event()
    repository = AsyncMock()
    repository.search.return_value = []
    completed = []

    class Embedder:
        def embed_query(self, query):
            if query == "first":
                first_started.set()
                assert release_first.wait(10)
            else:
                assert completed == ["first"]
            completed.append(query)
            return [0.1]

    class ObservedService(ProductSearchService):
        async def search(self, user, request):
            if request.query == "second":
                second_requested.set()
            return await super().search(user, request)

    sales = AsyncMock()
    sales.top_products.return_value = []
    service = ObservedService(Embedder(), repository)
    async with Client(
        server_for(
            sales, ("sales:read", "catalog:read"), product_search_service=service
        )
    ) as client:

        async def search(query):
            result = await client.call_tool(SEARCH_TOOL, SEARCH_ARGS | {"query": query})
            assert not result.is_error

        async with anyio.create_task_group() as group:
            try:
                group.start_soon(search, "first")
                with anyio.fail_after(5):
                    while not first_started.is_set():
                        await anyio.sleep(0.01)
                    group.start_soon(search, "second")
                    await second_requested.wait()
                    result = await client.call_tool(TOOL, ARGS)
                    assert not result.is_error
                    assert completed == []
                    repository.search.assert_not_called()
            finally:
                release_first.set()
    assert completed == ["first", "second"]
    assert repository.search.await_count == 2
