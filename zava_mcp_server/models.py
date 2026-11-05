"""SDK 요청 객체와 독립적으로 전달할 사용자·권한 정보."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

StoreId = Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]
SALES_READ = "sales:read"


class SalesQueryError(RuntimeError):
    """원본 DB 오류를 숨기는 매출 조회 실패."""


class SalesQueryTimeoutError(SalesQueryError):
    """매출 조회 중 시간 초과."""


_store_id_adapter = TypeAdapter(StoreId, config=ConfigDict(hide_input_in_errors=True))


def validate_store_id(value: object) -> int:
    """직접 호출에서도 동일한 매장 ID 규칙을 적용하고 원문은 노출하지 않는다."""
    try:
        return _store_id_adapter.validate_python(value)
    except ValidationError:
        raise ValueError(
            "store_id는 PostgreSQL integer 범위의 양의 정수여야 합니다"
        ) from None


@dataclass(frozen=True)
class SalesQuery:
    store_id: int
    start_date: date
    end_date: date
    limit: int


@dataclass(frozen=True)
class SalesSummaryQuery:
    store_id: int
    start_date: date
    end_date: date


@dataclass(frozen=True)
class SalesSummary:
    total_sales: Decimal
    order_count: int


@dataclass(frozen=True)
class ProductSales:
    product_id: int
    product_name: str
    total_amount: Decimal


class UserContext(BaseModel):
    """서버가 제공하는 개발용 사용자 정보. 실제 인증 결과는 아니다."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    user_id: str = Field(strict=True, min_length=1)
    allowed_actions: frozenset[Literal["sales:read"]]
    allowed_store_ids: frozenset[StoreId]

    @field_validator("user_id")
    @classmethod
    def require_user_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("사용자 식별자는 공백만으로 구성할 수 없습니다")
        return value

    @field_validator("allowed_actions", "allowed_store_ids", mode="before")
    @classmethod
    def require_list(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("권한 목록은 JSON 배열이어야 합니다")
        return value
