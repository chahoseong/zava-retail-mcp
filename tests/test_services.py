from dataclasses import replace
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest

from zava_mcp_server.models import SalesQuery, UserContext
from zava_mcp_server.services import PermissionDeniedError, SalesService

QUERY = SalesQuery(1, date(2024, 1, 1), date(2024, 12, 31), 20)


def user(actions=None, stores=None):
    return UserContext.model_validate(
        {
            "user_id": "test",
            "allowed_actions": ["sales:read"] if actions is None else actions,
            "allowed_store_ids": [1] if stores is None else stores,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("actions, stores", [([], [1]), (["sales:read"], [2])])
async def test_rejects_permissions_before_repository(actions, stores):
    repo = AsyncMock()
    with pytest.raises(PermissionDeniedError):
        await SalesService(repo).top_products(user(actions, stores), QUERY)
    repo.top_products.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query", [QUERY, replace(QUERY, end_date=QUERY.start_date, limit=1)]
)
async def test_accepts_inclusive_period_and_result_limits(query):
    repo = AsyncMock()
    repo.top_products.return_value = []
    assert await SalesService(repo).top_products(user(), query) == []
    repo.top_products.assert_awaited_once_with(query)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"end_date": date(2025, 1, 1)},
        {"end_date": date(2023, 12, 31)},
        {"start_date": datetime(2024, 1, 1)},
        {"end_date": "2024-12-31"},
        {"store_id": True},
        {"limit": 0},
        {"limit": 21},
        {"limit": True},
        {"limit": "10"},
        {"limit": 10.0},
    ],
)
async def test_invalid_conditions_never_reach_repository(changes):
    repo = AsyncMock()
    with pytest.raises(ValueError):
        await SalesService(repo).top_products(user(), replace(QUERY, **changes))
    repo.top_products.assert_not_called()
