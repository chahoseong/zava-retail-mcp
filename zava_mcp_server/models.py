"""SDK 요청 객체와 독립적으로 전달할 사용자·권한 정보."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserContext(BaseModel):
    """서버가 제공하는 개발용 사용자 정보. 실제 인증 결과는 아니다."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    user_id: str = Field(strict=True, min_length=1)
    allowed_actions: frozenset[Literal["orders:count"]]
    allowed_store_ids: frozenset[Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]]

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
