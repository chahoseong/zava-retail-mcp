"""CSV 하나를 기존 retail 테이블에 적재하거나 --verify로 비교합니다."""

import argparse
import asyncio
import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Dataset:
    """지원하는 CSV의 열, 기본 키와 참조 관계입니다."""

    columns: tuple[str, ...]
    key: tuple[str, ...]
    references: tuple = ()
    unique: tuple = ()


DATASETS = {
    "stores": Dataset(
        ("store_id", "store_name", "rls_user_id", "is_online"), ("store_id",),
        unique=(("store_name",),),
    ),
    "categories": Dataset(
        ("category_id", "category_name"), ("category_id",),
        unique=(("category_name",),),
    ),
    "product_types": Dataset(
        ("type_id", "category_id", "type_name"), ("type_id",),
        ((("category_id",), "categories", ("category_id",)),),
        (("type_id", "category_id"),),
    ),
    "products": Dataset(
        ("product_id", "sku", "product_name", "category_id", "type_id", "cost",
         "base_price", "gross_margin_percent", "product_description"),
        ("product_id",),
        ((("category_id",), "categories", ("category_id",)),
         (("type_id", "category_id"), "product_types", ("type_id", "category_id"))),
        (("sku",),),
    ),
    "customers": Dataset(
        ("customer_id", "first_name", "last_name", "email", "phone",
         "primary_store_id", "created_at"), ("customer_id",),
        ((("primary_store_id",), "stores", ("store_id",)),), (("email",),),
    ),
    "orders": Dataset(
        ("order_id", "customer_id", "store_id", "order_date"), ("order_id",),
        ((("customer_id",), "customers", ("customer_id",)),
         (("store_id",), "stores", ("store_id",))), (("order_id", "store_id"),),
    ),
    "order_items": Dataset(
        ("order_item_id", "order_id", "store_id", "product_id", "quantity",
         "unit_price", "discount_percent", "discount_amount", "total_amount"),
        ("order_item_id",),
        ((("order_id", "store_id"), "orders", ("order_id", "store_id")),
         (("product_id",), "products", ("product_id",))),
    ),
    "inventory": Dataset(
        ("store_id", "product_id", "stock_level"), ("store_id", "product_id"),
        ((("store_id",), "stores", ("store_id",)),
         (("product_id",), "products", ("product_id",))),
    ),
}
NULLABLE = {"rls_user_id", "gross_margin_percent", "phone", "primary_store_id"}
MONEY = {"cost", "base_price", "unit_price", "discount_amount", "total_amount"}


class ValidationError(Exception):
    """원문 값 없이 사용자에게 표시할 수 있는 검사 오류입니다."""


def sql_columns(columns):
    """프로그램에 정의된 열 이름만 SQL 식별자로 사용합니다."""
    return ", ".join(f'"{column}"' for column in columns)


def column_type(column):
    if column in MONEY:
        return "numeric(10,2)"
    if column == "gross_margin_percent":
        return "numeric(5,2)"
    if column == "rls_user_id":
        return "uuid"
    if column.endswith("_id") or column in {"quantity", "stock_level", "discount_percent"}:
        return "integer"
    return {"is_online": "boolean", "order_date": "date",
            "created_at": "timestamp without time zone"}.get(column, "text")


def parse_value(column, raw):
    """원본 표현을 정제하지 않고 대상 자료형으로 해석합니다."""
    if raw == r"\N":
        if column not in NULLABLE:
            raise ValueError
        return None
    kind = column_type(column)
    if kind == "integer":
        if not re.fullmatch(r"[+-]?[0-9]+", raw):
            raise ValueError
        value = int(raw)
        if not -(2**31) <= value < 2**31:
            raise ValueError
        if column == "quantity" and value <= 0:
            raise ValueError
        if column == "stock_level" and value < 0:
            raise ValueError
        if column == "discount_percent" and not 0 <= value <= 100:
            raise ValueError
        return value
    if kind.startswith("numeric"):
        if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?", raw):
            raise ValueError
        value = Decimal(raw)
        limit = Decimal("100000000") if column in MONEY else Decimal("1000")
        if abs(value) >= limit or (column in MONEY and value < 0):
            raise ValueError
        return value
    if kind == "boolean":
        if raw not in {"t", "f"}:
            raise ValueError
        return raw == "t"
    if kind == "uuid":
        return UUID(raw)
    if kind == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
            raise ValueError
        return date.fromisoformat(raw)
    if kind == "timestamp without time zone":
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?",
            raw,
        ):
            raise ValueError
        return datetime.fromisoformat(raw)
    if "\x00" in raw:
        raise ValueError
    return raw


def read_csv(path):
    """한 번 읽은 값을 적재와 비교에 함께 사용합니다. manifest는 읽지 않습니다."""
    table = path.stem
    if path.suffix != ".csv" or table not in DATASETS:
        raise ValidationError("지원하는 CSV 파일명을 사용하세요.")
    spec = DATASETS[table]
    records = {}
    unique_values = [set() for _ in spec.unique]
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if header is None or len(header) != len(spec.columns) or set(header) != set(spec.columns):
                raise ValidationError("CSV 열 이름이 대상 데이터의 열과 일치하지 않습니다.")
            positions = [header.index(column) for column in spec.columns]
            for number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    raise ValidationError(f"CSV 레코드 {number}: 열 개수가 다릅니다.")
                values = []
                for column, index in zip(spec.columns, positions):
                    try:
                        values.append(parse_value(column, row[index]))
                    except (ValueError, ArithmeticError):
                        raise ValidationError(
                            f"CSV 레코드 {number}, 열 {column}: 자료형·NULL·범위 오류."
                        ) from None
                record = tuple(values)
                key = tuple(record[spec.columns.index(column)] for column in spec.key)
                if key in records:
                    raise ValidationError(f"CSV 레코드 {number}: 기본 키 중복.")
                for columns, seen in zip(spec.unique, unique_values):
                    unique_key = tuple(record[spec.columns.index(column)] for column in columns)
                    if unique_key in seen:
                        raise ValidationError(f"CSV 레코드 {number}: 고유 키 중복.")
                    seen.add(unique_key)
                records[key] = record
    except (OSError, UnicodeError, csv.Error):
        raise ValidationError("CSV 파일을 읽을 수 없거나 UTF-8·CSV 형식이 잘못되었습니다.") from None
    if not records:
        raise ValidationError("CSV에 데이터 행이 없습니다.")
    return table, records


async def check_table(connection, table, writing):
    """대상 구조·키·외래 키·권한과 전체 행 조회 가능 여부를 확인합니다."""
    spec = DATASETS[table]
    relation = await connection.fetchrow(
        "SELECT c.oid, c.relkind, row_security_active(c.oid) AS filtered "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='retail' AND c.relname=$1", table,
    )
    if relation is None or relation["relkind"] != b"r":
        raise ValidationError(f"retail.{table}: 일반 테이블이 준비되지 않았습니다.")
    if relation["filtered"]:
        raise ValidationError("RLS로 행이 제한되는 계정은 사용할 수 없습니다.")
    oid = relation["oid"]
    permitted = await connection.fetchval(
        "SELECT has_schema_privilege('retail', 'USAGE') "
        "AND has_table_privilege($1::oid, 'SELECT') "
        "AND (NOT $2::boolean OR has_table_privilege($1::oid, 'INSERT'))", oid, writing,
    )
    if not permitted:
        raise ValidationError(f"retail.{table}: 필요한 조회·적재 권한이 없습니다.")
    columns = await connection.fetch(
        "SELECT attname, format_type(atttypid, atttypmod) AS type, attnotnull, "
        "attgenerated, attidentity FROM pg_attribute "
        "WHERE attrelid=$1 AND attnum>0 AND NOT attisdropped", oid,
    )
    actual = {row["attname"]: row for row in columns}
    if set(actual) != set(spec.columns):
        raise ValidationError(f"retail.{table}: 테이블 열 구성이 다릅니다.")
    for name in spec.columns:
        column = actual[name]
        if (column["type"] != column_type(name)
                or column["attnotnull"] != (name not in NULLABLE)
                or column["attgenerated"] != b"\x00"
                or column["attidentity"] != b"\x00"):
            raise ValidationError(f"retail.{table}, 열 {name}: 자료형·NULL·자동 생성 정의가 다릅니다.")
    constraints = await connection.fetch(
        "SELECT c.contype, c.convalidated, "
        "ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(num,pos) "
        "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.pos) AS cols, "
        "n.nspname AS ref_schema, r.relname AS ref_table, "
        "ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(num,pos) "
        "JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY k.pos) AS ref_cols "
        "FROM pg_constraint c LEFT JOIN pg_class r ON r.oid=c.confrelid "
        "LEFT JOIN pg_namespace n ON n.oid=r.relnamespace WHERE c.conrelid=$1", oid,
    )
    keys = {(c["contype"], tuple(c["cols"])) for c in constraints if c["convalidated"]}
    if (b"p", spec.key) not in keys or any((b"u", key) not in keys for key in spec.unique):
        raise ValidationError(f"retail.{table}: 필요한 기본 키·고유 제약조건이 없습니다.")
    for columns, parent, parent_columns in spec.references:
        if not any(c["contype"] == b"f" and c["convalidated"]
                   and tuple(c["cols"]) == columns and c["ref_schema"] == "retail"
                   and c["ref_table"] == parent and tuple(c["ref_cols"]) == parent_columns
                   for c in constraints):
            raise ValidationError(f"retail.{table}: 필요한 외래 키가 없습니다.")


async def check_references(connection, table, records):
    spec = DATASETS[table]
    for columns, parent, parent_columns in spec.references:
        if await connection.fetchval("SELECT row_security_active($1::regclass)", f"retail.{parent}"):
            raise ValidationError("참조 테이블의 전체 행을 조회할 수 없습니다.")
        available = {tuple(row) for row in await connection.fetch(
            f'SELECT {sql_columns(parent_columns)} FROM retail."{parent}"'
        )}
        positions = [spec.columns.index(column) for column in columns]
        for number, record in enumerate(records.values(), start=2):
            key = tuple(record[index] for index in positions)
            if all(value is not None for value in key) and key not in available:
                raise ValidationError(
                    f"CSV 레코드 {number}: retail.{parent}의 선행 참조 데이터가 없습니다."
                )


async def verify_records(connection, table, records):
    """기본 키로 모든 행·열을 비교합니다. DB 원문 값은 출력하지 않습니다."""
    spec = DATASETS[table]
    count = 0
    totals = {column: Decimal(0) for column in spec.columns
              if column in {"quantity", "stock_level", "total_amount"}}
    async for row in connection.cursor(
        f'SELECT {sql_columns(spec.columns)} FROM retail."{table}"', prefetch=2000
    ):
        count += 1
        key = tuple(row[column] for column in spec.key)
        expected = records.get(key)
        if expected is None:
            raise ValidationError(f"retail.{table}: CSV에 없는 행이 있습니다.")
        for index, column in enumerate(spec.columns):
            if row[index] != expected[index]:
                raise ValidationError(f"retail.{table}, 열 {column}: 저장값 불일치.")
        for column in totals:
            totals[column] += row[column]
    if count != len(records):
        raise ValidationError(f"행 수 불일치: CSV={len(records)}, DB={count}.")
    for column, actual in totals.items():
        expected = sum((record[spec.columns.index(column)] for record in records.values()), Decimal(0))
        if actual != expected:
            raise ValidationError(f"열 {column}: 집계 불일치.")
    await check_references(connection, table, records)
    print(f"검증 통과: 행 수={count}, 모든 행·열 일치, 참조 관계 일치.")
    for column, value in totals.items():
        print(f"집계: {column}={value}")


def lock_tables(table):
    """동시 적재와 참조 데이터 변경을 막을 잠금 대상을 정합니다."""
    names = {table}
    for _, parent, _ in DATASETS[table].references:
        names.add(parent)
    return sorted(names)


async def process(connection, table, records, verify=False):
    """적재와 검증을 실행하며 트랜잭션 상태를 구분해 보고합니다."""
    if verify:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            await check_table(connection, table, writing=False)
            await verify_records(connection, table, records)
        print("완료: 검증 전용, DB 변경 없음.")
        return
    phase = "준비"
    transaction = connection.transaction()
    try:
        await transaction.start()
        await connection.execute("SET LOCAL lock_timeout = '5s'")
        for name in lock_tables(table):
            mode = "EXCLUSIVE" if name == table else "SHARE"
            await connection.execute(f'LOCK TABLE retail."{name}" IN {mode} MODE')
        await check_table(connection, table, writing=True)
        count = await connection.fetchval(f'SELECT count(*) FROM retail."{table}"')
        print(f"적재 전 행 수: {count}")
        if count:
            raise ValidationError("대상 테이블에 기존 데이터가 있어 적재를 중단합니다.")
        await check_references(connection, table, records)
        phase = "적재"
        await connection.copy_records_to_table(
            table, schema_name="retail", columns=DATASETS[table].columns,
            records=records.values(), timeout=120,
        )
        await connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        await verify_records(connection, table, records)
        phase = "커밋 요청"
        await transaction.commit()
        phase = "커밋 완료"
        print("커밋 완료: 선택한 CSV의 저장을 확정했습니다.")
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            await check_table(connection, table, writing=False)
            await verify_records(connection, table, records)
        print("완료: 커밋 후 검증 통과.")
    except BaseException:
        if phase == "커밋 요청":
            print("상태: 커밋 확정 여부를 확인해야 합니다. --verify로 재확인하세요.")
        elif phase == "커밋 완료":
            print("상태: 커밋 완료, 후속 검증 실패. 저장된 데이터는 유지됩니다.")
        else:
            try:
                await transaction.rollback()
                print("상태: 적재 중단·롤백 완료. 이번 실행의 변경은 없습니다.")
            except BaseException:
                print("상태: 연결 종료 후 미확정 트랜잭션은 취소됩니다. 재실행 전 상태를 확인하세요.")
        raise


def connection_settings():
    names = ("HOST", "PORT", "DB", "USER", "PASSWORD")
    if any(not os.environ.get(f"POSTGRES_{name}") for name in names):
        raise ValidationError("POSTGRES_HOST·PORT·DB·USER·PASSWORD 환경 변수를 설정하세요.")
    try:
        port = int(os.environ["POSTGRES_PORT"])
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValidationError("POSTGRES_PORT가 올바르지 않습니다.") from None
    return dict(host=os.environ["POSTGRES_HOST"], port=port,
                database=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"], timeout=10, command_timeout=120)


async def run(path, verify):
    table, records = read_csv(path)
    print(f"입력 검사 통과: {table}.csv → retail.{table}, 데이터 행 수={len(records)}")
    settings = connection_settings()
    connection = await asyncpg.connect(**settings)
    try:
        target = await connection.fetchrow(
            "SELECT current_database() AS db, current_user AS role, "
            "inet_server_addr()::text AS host, inet_server_port() AS port"
        )
        # 환경 설정이나 예외 원문에 비밀값이 섞일 수 있어 안전한 서버 응답만 표시합니다.
        print(f"접속 대상: {target['host']}:{target['port']}, DB={target['db']}, 계정={target['role']}")
        await process(connection, table, records, verify)
    finally:
        await connection.close(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="지원하는 CSV 파일 경로")
    parser.add_argument("--verify", action="store_true", help="DB 변경 없이 저장 결과만 검증")
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(args.csv, args.verify))
        return 0
    except ValidationError as error:
        print(f"검사 실패: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("실행이 취소되었습니다.", file=sys.stderr)
        return 130
    except Exception as error:
        # PostgreSQL DETAIL, CSV 값, 접속 예외·트레이스백은 개인정보를 포함할 수 있습니다.
        code = getattr(error, "sqlstate", None)
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[0-9A-Z]{5}", code) else "없음"
        reason = {
            "42P01": "대상 또는 선행 테이블이 없습니다",
            "42501": "필요한 DB 권한이 없습니다",
            "23503": "외래 키 제약조건 위반",
            "23505": "고유 키 제약조건 위반",
            "23514": "검사 제약조건 위반",
            "55P03": "잠금 대기 시간 초과",
            "57014": "DB 명령 취소 또는 시간 초과",
            "28P01": "DB 인증 실패",
        }.get(safe_code, "DB·연결·처리 오류")
        print(f"실행 실패: {reason}, SQLSTATE={safe_code}. 원문은 출력하지 않습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
