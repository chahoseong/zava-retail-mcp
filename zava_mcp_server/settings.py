"""환경변수와 개발용 사용자 JSON을 읽어 검증된 설정으로 반환한다."""

import ipaddress
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .models import UserContext

PROJECT_ROOT = Path(__file__).resolve().parent.parent
Port = Annotated[int, Field(ge=1, le=65535)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class SettingsError(ValueError):
    """설정 항목과 이유만 표시하는 안전한 설정 오류."""


class SettingsModel(BaseModel):
    """검증 후 설정의 변경과 오류 원문 노출을 막는 공통 모델."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


def _integer(value: object) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        return int(value)
    raise ValueError("정수 문자열이어야 합니다")


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("빈 값이나 공백만 있는 값은 사용할 수 없습니다")
    return value


class DatabaseSettings(SettingsModel):
    """접속 정보의 형식만 확인한다. 실제 인증과 권한은 확인하지 않는다."""

    host: str = Field(strict=True, min_length=1)
    port: Port
    database: str = Field(strict=True, min_length=1)
    user: str = Field(strict=True, min_length=1)
    password: SecretStr = Field(min_length=1)

    @field_validator("host", "database", "user")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value)

    @field_validator("port", mode="before")
    @classmethod
    def parse_port(cls, value: object) -> int:
        return _integer(value)


class ServerSettings(SettingsModel):
    """로컬 개발 서버 주소. 생략한 항목에만 기본값을 사용한다."""

    host: str = Field(default="127.0.0.1", strict=True)
    port: Port = 8000
    path: str = Field(default="/mcp", strict=True)

    @field_validator("host")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        if value.lower() == "localhost":
            return value
        try:
            valid = ipaddress.ip_address(value).is_loopback
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("로컬 루프백 주소만 허용합니다")
        return value

    @field_validator("port", mode="before")
    @classmethod
    def parse_port(cls, value: object) -> int:
        return _integer(value)

    @field_validator("path")
    @classmethod
    def require_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(char.isspace() or char in "?#\\" for char in value)
        ):
            raise ValueError("/로 시작하고 공백·쿼리·프래그먼트가 없는 경로여야 합니다")
        return value


class PoolSettings(SettingsModel):
    """초 단위 시간 제한과 연결 수. 풀 생성은 후속 단계의 책임이다."""

    min_size: int = Field(default=1, ge=0)
    max_size: int = Field(default=5, ge=1)
    connect_timeout: PositiveSeconds = 10.0
    acquire_timeout: PositiveSeconds = 5.0
    query_timeout: PositiveSeconds = 10.0
    shutdown_timeout: PositiveSeconds = 10.0

    @field_validator("min_size", "max_size", mode="before")
    @classmethod
    def parse_size(cls, value: object) -> int:
        return _integer(value)

    @model_validator(mode="after")
    def check_size_order(self) -> Self:
        if self.min_size > self.max_size:
            raise ValueError("최소 연결 수는 최대 연결 수보다 클 수 없습니다")
        return self


class Settings(SettingsModel):
    """서버 구성 시 한 번 읽어 다른 구성 요소에 전달할 설정."""

    db: DatabaseSettings
    server: ServerSettings
    pool: PoolSettings
    dev_user_file: Path
    user: UserContext


_ENV_FIELDS = {
    "db": {
        "host": "POSTGRES_HOST",
        "port": "POSTGRES_PORT",
        "database": "POSTGRES_DB",
        "user": "POSTGRES_USER",
        "password": "POSTGRES_PASSWORD",
    },
    "server": {"host": "MCP_HOST", "port": "MCP_PORT", "path": "MCP_PATH"},
    "pool": {
        "min_size": "DB_POOL_MIN_SIZE",
        "max_size": "DB_POOL_MAX_SIZE",
        "connect_timeout": "DB_CONNECT_TIMEOUT",
        "acquire_timeout": "DB_ACQUIRE_TIMEOUT",
        "query_timeout": "DB_QUERY_TIMEOUT",
        "shutdown_timeout": "DB_SHUTDOWN_TIMEOUT",
    },
}


def _validation_message(error: ValidationError, group: str) -> str:
    """입력값과 예외 컨텍스트를 제외하고 고정된 필드명으로 오류를 표시한다."""
    messages = []
    known_user_fields = {"user_id", "allowed_actions", "allowed_store_ids"}
    for item in error.errors(
        include_input=False, include_context=False, include_url=False
    ):
        location = item["loc"]
        first = location[0] if location else None
        if group == "user":
            field = first if first in known_user_fields else "JSON 구조"
            label = f"DEV_USER_FILE.{field}"
        elif first in _ENV_FIELDS[group]:
            label = _ENV_FIELDS[group][first]
        elif group == "pool":
            label = "DB_POOL_MIN_SIZE/DB_POOL_MAX_SIZE"
        else:
            label = "/".join(_ENV_FIELDS[group].values())
        messages.append(f"{label}: {item['msg']}")
    return "; ".join(messages)


def load_settings(environment: Mapping[str, str] | None = None) -> Settings:
    """uv가 불러온 환경변수에서 읽는다. 명시적 매핑은 독립적인 검사에 쓴다."""
    env = dict(os.environ if environment is None else environment)
    groups = {}
    for group, model in (
        ("db", DatabaseSettings),
        ("server", ServerSettings),
        ("pool", PoolSettings),
    ):
        values = {
            field: env[name]
            for field, name in _ENV_FIELDS[group].items()
            if name in env
        }
        try:
            groups[group] = model.model_validate(values)
        except ValidationError as error:
            raise SettingsError(_validation_message(error, group)) from None

    raw_path = env.get("DEV_USER_FILE", "config/dev-user.json")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise SettingsError("DEV_USER_FILE: 비어 있지 않은 파일 경로를 지정해야 합니다")
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        path = path.resolve()
        with path.open(encoding="utf-8") as stream:
            raw_user = json.load(stream)
    except (OSError, ValueError):
        raise SettingsError(
            "DEV_USER_FILE: 파일을 읽을 수 없거나 JSON 형식이 잘못되었습니다"
        ) from None
    try:
        user = UserContext.model_validate(raw_user)
    except ValidationError as error:
        raise SettingsError(_validation_message(error, "user")) from None
    return Settings(**groups, dev_user_file=path, user=user)
