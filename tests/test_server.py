from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import anyio
import pytest
from mcp import Client

from zava_mcp_server.models import (
    ProductSales,
    SalesQuery,
    SalesQueryError,
    SalesQueryTimeoutError,
    SalesSummary,
    SalesSummaryQuery,
    UserContext,
)
from zava_mcp_server.server import create_server
from zava_mcp_server.server_context import ServerContext
from zava_mcp_server.services import SalesService

ARGS = {"store_id": 1, "start_date": "2020-01-01", "end_date": "2020-01-31", "limit": 5}
SECRET = "FAKE_DRIVER_SECRET"
TOOL = "get_top_products"
SUMMARY_TOOL = "get_sales_summary"
SUMMARY_ARGS = {key: value for key, value in ARGS.items() if key != "limit"}
COMPARE_TOOL = "compare_store_sales"
COMPARE_ACTIONS = ("sales:read", "sales:compare")
COMPARE_ARGS = {
    "store_ids": [2, 1, 2],
    "start_date": "2020-01-01",
    "end_date": "2020-01-31",
}


def server_for(service, actions=("sales:read",), stores=(1,)):
    user = UserContext.model_validate(
        {
            "user_id": "test",
            "allowed_actions": list(actions),
            "allowed_store_ids": list(stores),
        }
    )

    @asynccontextmanager
    async def lifespan(_):
        yield ServerContext(service=service, user=user)

    return create_server(lifespan)


@pytest.mark.asyncio
async def test_tool_contract_and_decimal_response():
    service = AsyncMock()
    service.top_products.return_value = [
        ProductSales(400, "Workbench", Decimal("125.30"))
    ]
    async with Client(server_for(service)) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {TOOL, SUMMARY_TOOL, COMPARE_TOOL}
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
