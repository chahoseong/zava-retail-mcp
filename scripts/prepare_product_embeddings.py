"""공용 상품 카탈로그의 임베딩을 생성해 PostgreSQL에 저장한다."""

import asyncio
import json
import os

import asyncpg
from rich.console import Console
from rich.progress import (
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from zava_mcp_server.embeddings import EmbeddingAdapter
from zava_mcp_server.settings import DatabaseSettings

WRITER_ROLE = "zava_embedding_writer"
BATCH_SIZE = 32
READ_PRODUCTS = """
SELECT product_id, product_name, product_description
FROM retail.products
ORDER BY product_id
"""
UPSERT_EMBEDDING = """
INSERT INTO retail.product_embeddings (product_id, embedding)
VALUES ($1, $2::text::vector)
ON CONFLICT (product_id) DO UPDATE SET embedding = $2::text::vector
"""


def load_database_settings() -> DatabaseSettings:
    settings = DatabaseSettings.model_validate(
        {
            "host": os.environ.get("POSTGRES_HOST"),
            "port": os.environ.get("POSTGRES_PORT"),
            "database": os.environ.get("POSTGRES_DB"),
            "user": os.environ.get("POSTGRES_USER"),
            "password": os.environ.get("POSTGRES_PASSWORD"),
        }
    )
    if settings.user != WRITER_ROLE:
        raise ValueError("임베딩 준비 전용 계정이 필요합니다.")
    return settings


async def connect(settings: DatabaseSettings):
    return await asyncpg.connect(
        host=settings.host,
        port=settings.port,
        database=settings.database,
        user=settings.user,
        password=settings.password.get_secret_value(),
        timeout=10,
        command_timeout=120,
    )


async def prepare(settings: DatabaseSettings, console: Console) -> None:
    console.print("[1/3] 상품 카탈로그 읽는 중")
    connection = await connect(settings)
    try:
        products = await connection.fetch(READ_PRODUCTS)
    finally:
        await connection.close(timeout=5)
    if not products:
        raise ValueError("상품 카탈로그가 비어 있습니다.")
    total = len(products)
    console.print(f"[1/3] 상품 카탈로그 읽기 완료 ({total}개)")

    rows = []
    interactive = console.is_interactive
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}", markup=False),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        disable=not interactive,
    ) as progress:
        task = progress.add_task("[2/3] 임베딩 모델 로드 중", total=total)
        if not interactive:
            console.print("[2/3] 임베딩 모델 로드 중")
        model = EmbeddingAdapter.load()
        for start in range(0, total, BATCH_SIZE):
            batch = products[start : start + BATCH_SIZE]
            number = start // BATCH_SIZE + 1
            progress.update(task, description=f"[2/3] 임베딩 생성 중 · 배치 {number}")
            vectors = model.embed_documents(
                [(row["product_name"], row["product_description"]) for row in batch]
            )
            rows.extend(
                (
                    row["product_id"],
                    json.dumps(vector, separators=(",", ":"), allow_nan=False),
                )
                for row, vector in zip(batch, vectors, strict=True)
            )
            progress.advance(task, len(batch))
            if not interactive:
                console.print(f"[2/3] 배치 {number} 완료 ({len(rows)}/{total}개)")

    console.print(f"[2/3] 임베딩 생성 및 검증 완료 ({total}/{total}개)")
    console.print("[3/3] PostgreSQL에 벡터 저장 중")
    connection = await connect(settings)
    try:
        async with connection.transaction():
            await connection.executemany(UPSERT_EMBEDDING, rows)
        console.print(f"[3/3] 저장 완료 ({total}개, 커밋 완료)")
    finally:
        await connection.close(timeout=5)


def main() -> int:
    # 모델 다운로드·로딩 라이브러리의 진행 바 대신 이 명령의 진행 표시를 사용한다.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    console = Console(stderr=True, markup=False, highlight=False)
    try:
        settings = load_database_settings()
    except ValueError:
        console.print(f"POSTGRES_* 접속 설정과 전용 계정({WRITER_ROLE})을 확인하세요.")
        return 1
    try:
        asyncio.run(prepare(settings, console))
    except KeyboardInterrupt:
        console.print("임베딩 준비를 중단했습니다.")
        return 130
    except Exception as error:
        console.print(
            f"임베딩 준비 실패 ({type(error).__name__}). 직전 단계를 확인하세요."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
