"""PostgreSQL 시스템 카탈로그에서 테이블 구조를 읽는다."""

from contextlib import AsyncExitStack

from anyio import CancelScope

from .runtime import Pool
from .schema_service import SchemaQueryError, SchemaQueryTimeoutError, TableSchema

TABLE_SCHEMA_SQL = """
WITH target AS (
    SELECT relation.oid
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = $1 AND relation.relname = $2
      AND relation.relkind IN ('r', 'p')
),
columns AS (
    SELECT json_agg(json_build_object(
        'column_name', attribute.attname,
        'data_type', pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
        'is_nullable', NOT attribute.attnotnull
    ) ORDER BY attribute.attnum) AS items
    FROM target
    JOIN pg_catalog.pg_attribute AS attribute ON attribute.attrelid = target.oid
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
),
keys AS (
    SELECT key.conname, key.contype, key.confrelid,
           array_agg(local_col.attname ORDER BY slot.ordinal) AS local_columns,
           array_agg(remote_col.attname ORDER BY slot.ordinal) AS remote_columns
    FROM target
    JOIN pg_catalog.pg_constraint AS key ON key.conrelid = target.oid
    CROSS JOIN LATERAL unnest(key.conkey) WITH ORDINALITY AS slot(attnum, ordinal)
    JOIN pg_catalog.pg_attribute AS local_col
      ON local_col.attrelid = key.conrelid AND local_col.attnum = slot.attnum
    LEFT JOIN pg_catalog.pg_attribute AS remote_col
      ON remote_col.attrelid = key.confrelid
     AND remote_col.attnum = key.confkey[slot.ordinal::integer]
    WHERE key.contype IN ('p', 'f')
    GROUP BY key.oid, key.conname, key.contype, key.confrelid
),
foreign_keys AS (
    SELECT json_agg(json_build_object(
        'constrained_columns', key.local_columns,
        'referenced_schema', namespace.nspname,
        'referenced_table', relation.relname,
        'referenced_columns', key.remote_columns
    ) ORDER BY key.conname) AS items
    FROM keys AS key
    JOIN pg_catalog.pg_class AS relation ON relation.oid = key.confrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE key.contype = 'f'
)
SELECT json_build_object(
    'columns', COALESCE(columns.items, '[]'::json),
    'primary_key', COALESCE((SELECT local_columns FROM keys WHERE contype = 'p'), '{}'),
    'foreign_keys', COALESCE(foreign_keys.items, '[]'::json)
)
FROM target CROSS JOIN columns CROSS JOIN foreign_keys
"""


class SchemaRepository:
    def __init__(self, pool: Pool, acquire_timeout: float) -> None:
        self._pool = pool
        self._acquire_timeout = acquire_timeout

    async def table_schema(
        self, schema_name: str, table_name: str
    ) -> TableSchema | None:
        try:
            with CancelScope() as cleanup:
                async with AsyncExitStack() as resources:
                    try:
                        connection = await resources.enter_async_context(
                            self._pool.acquire(timeout=self._acquire_timeout)
                        )
                        await resources.enter_async_context(
                            connection.transaction(readonly=True)
                        )
                        value = await connection.fetchval(
                            TABLE_SCHEMA_SQL, schema_name, table_name
                        )
                    finally:
                        cleanup.shield = True
            if value is None:
                return None
            if not isinstance(value, str):
                raise TypeError("카탈로그 결과가 JSON 문자열이 아닙니다")
            return TableSchema.model_validate_json(value, strict=True)
        except TimeoutError:
            raise SchemaQueryTimeoutError from None
        except Exception:
            raise SchemaQueryError from None
