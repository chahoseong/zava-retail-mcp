"""매출 조회의 권한과 업무 조건을 확인한다."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from .models import (
    SALES_COMPARE,
    SALES_READ,
    ProductSales,
    SalesQuery,
    SalesSummary,
    SalesSummaryQuery,
    UserContext,
    validate_store_id,
)


class PermissionDeniedError(PermissionError):
    """매출 조회 또는 요청한 매장에 대한 권한이 없다."""


class CompareStoreCountError(ValueError):
    """서로 다른 비교 대상 매장 수가 허용 범위를 벗어났다."""


class SalesReader(Protocol):
    """승인된 조건으로 매출을 조회한다."""

    async def top_products(self, query: SalesQuery) -> list[ProductSales]: ...

    async def sales_summary(self, query: SalesSummaryQuery) -> SalesSummary: ...


class SalesService:
    def __init__(self, repository: SalesReader) -> None:
        self._repository = repository

    async def top_products(
        self, user: UserContext, query: SalesQuery
    ) -> list[ProductSales]:
        """권한과 조건을 확인한 뒤 집계를 요청한다."""
        _validate_sales_query(user, query)
        if type(query.limit) is not int or not 1 <= query.limit <= 20:
            raise ValueError("결과 수는 1~20 사이의 정수여야 합니다")
        return await self._repository.top_products(query)

    async def sales_summary(
        self, user: UserContext, query: SalesSummaryQuery
    ) -> SalesSummary:
        """권한과 기간을 확인한 뒤 매출 요약을 조회한다."""
        _validate_sales_query(user, query)
        return await self._repository.sales_summary(query)

    async def compare_store_sales(
        self,
        user: UserContext,
        store_ids: Sequence[int],
        start_date: date,
        end_date: date,
    ) -> list[tuple[int, SalesSummary]]:
        """전체 요청을 검증한 뒤 매장별 집계를 순차 실행한다."""
        stores = dict.fromkeys(validate_store_id(store_id) for store_id in store_ids)
        if not 2 <= len(stores) <= 10:
            raise CompareStoreCountError("비교할 매장은 2개 이상 10개 이하여야 합니다")
        _require_sales_read(user)
        if SALES_COMPARE not in user.allowed_actions:
            raise PermissionDeniedError("매장 매출 비교 권한이 없습니다")
        for store_id in stores:
            _require_store_access(user, store_id)
        _validate_period(start_date, end_date)

        results = []
        for store_id in stores:
            summary = await self._repository.sales_summary(
                SalesSummaryQuery(store_id, start_date, end_date)
            )
            results.append((store_id, summary))
        return results


def _validate_sales_query(
    user: UserContext, query: SalesQuery | SalesSummaryQuery
) -> None:
    validate_store_id(query.store_id)
    _require_sales_read(user)
    _require_store_access(user, query.store_id)
    _validate_period(query.start_date, query.end_date)


def _require_sales_read(user: UserContext) -> None:
    if SALES_READ not in user.allowed_actions:
        raise PermissionDeniedError("매출 조회 권한이 없습니다")


def _require_store_access(user: UserContext, store_id: int) -> None:
    if store_id not in user.allowed_store_ids:
        raise PermissionDeniedError("매장 접근 권한이 없습니다")


def _validate_period(start_date: date, end_date: date) -> None:
    if type(start_date) is not date or type(end_date) is not date:
        raise ValueError("시작일과 종료일은 날짜여야 합니다")
    if not 0 <= (end_date - start_date).days < 366:
        raise ValueError("조회 기간은 양쪽 날짜를 포함해 1~366일이어야 합니다")
