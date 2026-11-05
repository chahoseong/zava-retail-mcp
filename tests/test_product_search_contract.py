import pytest
from pydantic import TypeAdapter, ValidationError

from zava_mcp_server.models import (
    CATALOG_READ,
    ProductSearchInput,
    ProductSearchResults,
    UserContext,
)

SEARCH = {"query": "접이식 작업대", "store_id": 1, "limit": 5}
RESULT = {
    "product_id": 10,
    "product_name": "접이식 작업대",
    "product_description": "좁은 공간에서 접어 보관할 수 있는 작업대",
}


@pytest.mark.parametrize("query, limit", [("작", 1), ("작" * 256, 10)])
def test_search_input_trims_whitespace_before_length_validation(query, limit):
    request = ProductSearchInput.model_validate(
        SEARCH | {"query": f"  {query}\t", "limit": limit}
    )
    assert request.query == query
    assert request.limit == limit


@pytest.mark.parametrize(
    "change",
    [
        {"query": " \t"},
        {"query": "작" * 257},
        {"query": 123},
        {"store_id": 0},
        {"store_id": 2**31},
        {"store_id": "1"},
        {"store_id": True},
        {"limit": 0},
        {"limit": 11},
        {"limit": "1"},
        {"limit": True},
    ],
)
def test_search_input_rejects_invalid_values(change):
    with pytest.raises(ValidationError):
        ProductSearchInput.model_validate(SEARCH | change)


@pytest.mark.parametrize("field", SEARCH)
def test_search_input_requires_each_field(field):
    with pytest.raises(ValidationError):
        ProductSearchInput.model_validate(
            {key: value for key, value in SEARCH.items() if key != field}
        )


def test_search_results_accept_empty_list_and_score_boundaries():
    adapter = TypeAdapter(ProductSearchResults)
    rows = [RESULT | {"similarity_score": score} for score in (-1.0, 1.0)]
    assert adapter.validate_python([]) == []
    assert adapter.dump_python(adapter.validate_python(rows)) == rows


@pytest.mark.parametrize("score", [-1.01, 1.01, float("nan"), float("inf")])
def test_search_results_reject_invalid_scores(score):
    with pytest.raises(ValidationError):
        TypeAdapter(ProductSearchResults).validate_python(
            [RESULT | {"similarity_score": score}]
        )


def test_user_context_accepts_catalog_read_without_other_actions():
    user = {
        "user_id": "search-user",
        "allowed_actions": [CATALOG_READ],
        "allowed_store_ids": [1],
    }
    assert UserContext.model_validate(user).allowed_actions == {CATALOG_READ}
    with pytest.raises(ValidationError):
        UserContext.model_validate(user | {"allowed_actions": ["catalog:unknown"]})
