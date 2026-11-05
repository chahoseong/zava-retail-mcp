"""MCP 도구의 공통 입력 타입."""

from typing import Annotated

from pydantic import Field

ToolDate = Annotated[str, Field(strict=True, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
