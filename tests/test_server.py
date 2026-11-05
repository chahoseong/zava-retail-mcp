from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from mcp import Client

from zava_mcp_server.models import (
    ProductSales,
    SalesQuery,
    SalesQueryError,
    SalesQueryTimeoutError,
    UserContext,
)
from zava_mcp_server.server import create_server
from zava_mcp_server.services import SalesService

ARGS = {"store_id": 1, "start_date": "2020-01-01", "end_date": "2020-01-31", "limit": 5}
SECRET = "FAKE_DRIVER_SECRET"
TOOL = "get_top_products"


def server_for(service, actions=("sales:read",)):
    user = UserContext.model_validate(
        {
            "user_id": "test",
            "allowed_actions": list(actions),
            "allowed_store_ids": [1],
        }
    )

    @asynccontextmanager
    async def lifespan(_):
        yield service

    return create_server(lifespan, user)


@pytest.mark.asyncio
async def test_tool_contract_and_decimal_response():
    service = AsyncMock()
    service.top_products.return_value = [
        ProductSales(400, "Workbench", Decimal("125.30"))
    ]
    async with Client(server_for(service)) as client:
        tools = (await client.list_tools()).tools
        assert [tool.name for tool in tools] == [TOOL]
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
async def test_db_failures_are_safe_tool_errors(error, message):
    service = AsyncMock()
    service.top_products.side_effect = error
    async with Client(server_for(service)) as client:
        result = await client.call_tool(TOOL, ARGS)
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
