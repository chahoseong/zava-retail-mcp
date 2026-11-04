"""DB 없는 단위 테스트와 명시적으로 지정한 임시 DB의 통합 테스트."""

import asyncio
import csv
import importlib.util
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
module_spec = importlib.util.spec_from_file_location(
    "csv_to_postgres", ROOT / "scripts/csv_to_postgres.py"
)
loader = importlib.util.module_from_spec(module_spec)
sys.modules[module_spec.name] = loader
module_spec.loader.exec_module(loader)


def make_csv(tmp_path, table, rows, columns=None):
    path = tmp_path / f"{table}.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns or loader.DATASETS[table].columns)
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("column,raw,expected", [
    ("unit_price", "12.30", Decimal("12.30")),
    ("gross_margin_percent", "-1.25", Decimal("-1.25")),
    ("is_online", "f", False),
    ("is_online", "t", True),
    ("phone", "00123", "00123"),
    ("phone", "", ""),
    ("phone", r"\N", None),
    ("first_name", "  가상,이름\n한 줄 더  ", "  가상,이름\n한 줄 더  "),
    ("order_date", "2026-12-31", date(2026, 12, 31)),
    ("created_at", "2024-01-02 03:04:05.123456", datetime(2024, 1, 2, 3, 4, 5, 123456)),
    ("stock_level", "0", 0),
])
def test_values_preserved(column, raw, expected):
    assert loader.parse_value(column, raw) == expected


@pytest.mark.parametrize("column,raw", [
    ("cost", "1.001"), ("cost", "NaN"), ("cost", "100000000.00"),
    ("cost", "-0.01"), ("quantity", "0"), ("stock_level", "-1"),
    ("discount_percent", "101"), ("customer_id", "2147483648"),
    ("customer_id", r"\N"), ("customer_id", "1.0"), ("is_online", "false"),
    ("order_date", "2024-02-30"), ("created_at", "2024-01-01T00:00:00Z"),
    ("created_at", "2024-01-01T00:00:00.1234567"), ("rls_user_id", "bad"),
    ("first_name", "bad\x00text"),
])
def test_invalid_values(column, raw):
    with pytest.raises(ValueError):
        loader.parse_value(column, raw)


def test_csv_quoting_and_header_order(tmp_path):
    path = make_csv(tmp_path, "categories", [('가상,분류\n"이름"', 1)],
                    ["category_name", "category_id"])
    table, rows = loader.read_csv(path)
    assert table == "categories"
    assert rows == {(1,): (1, '가상,분류\n"이름"')}


@pytest.mark.parametrize("rows,columns", [
    ([(1, "a"), (1, "b")], None),
    ([(1, "a"), (2, "a")], None),
    ([(1,)], None),
    ([], None),
    ([(1, "a")], ["category_id", "wrong"]),
])
def test_invalid_csv(tmp_path, rows, columns):
    with pytest.raises(loader.ValidationError):
        loader.read_csv(make_csv(tmp_path, "categories", rows, columns))


def test_does_not_require_manifest(tmp_path):
    path = make_csv(tmp_path, "categories", [(987, "사용자가 바꾼 가상 값")])
    assert loader.read_csv(path)[1] == {(987,): (987, "사용자가 바꾼 가상 값")}


def test_unknown_filename(tmp_path):
    with pytest.raises(loader.ValidationError):
        loader.read_csv(tmp_path / "unknown.csv")


def test_no_private_values_in_input_error(tmp_path, capsys):
    secret = "FAKE_PRIVATE_MARKER"
    path = make_csv(tmp_path, "customers", [
        (secret, "Fake", "Person", "fake@example.invalid", "0000", 1, "2024-01-01 00:00:00")
    ])
    assert loader.main([str(path)]) == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "customer_id" in output.err


def test_no_raw_database_error(monkeypatch, tmp_path, capsys):
    async def fail(*args):
        raise RuntimeError("FAKE_PASSWORD_AND_PRIVATE_VALUE")
    monkeypatch.setattr(loader, "run", fail)
    assert loader.main([str(tmp_path / "customers.csv"), "--verify"]) == 1
    assert "FAKE_PASSWORD" not in capsys.readouterr().err


@pytest_asyncio.fixture
async def db():
    """이름이 zava_csv_test로 시작하는 별도 DB에서만 스키마를 재구성합니다."""
    dsn = os.environ.get("CSV_TEST_DSN")
    if not dsn:
        pytest.skip("격리 DB의 CSV_TEST_DSN을 지정해야 통합 테스트를 실행합니다.")
    connection = await asyncpg.connect(dsn, command_timeout=120)
    try:
        name = await connection.fetchval("SELECT current_database()")
        if not name.startswith("zava_csv_test"):
            pytest.fail("통합 테스트 DB 이름은 zava_csv_test로 시작해야 합니다.", pytrace=False)
        await connection.execute("DROP SCHEMA IF EXISTS retail CASCADE")
        for path in sorted((ROOT / "sql").glob("*.sql")):
            await connection.execute(path.read_text(encoding="utf-8"))
        yield connection
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_load_verify_and_existing_data(db, tmp_path):
    table, records = loader.read_csv(make_csv(tmp_path, "categories", [(1, "가상 분류")]))
    await loader.process(db, table, records)
    await loader.process(db, table, records, verify=True)
    with pytest.raises(loader.ValidationError, match="기존 데이터"):
        await loader.process(db, table, records)
    assert await db.fetchval("SELECT count(*) FROM retail.categories") == 1
    assert await db.fetchval("SELECT category_name FROM retail.categories") == "가상 분류"


@pytest.mark.asyncio
@pytest.mark.parametrize("alter", [
    "DROP TABLE retail.inventory",
    "ALTER TABLE retail.inventory DROP COLUMN stock_level",
    "ALTER TABLE retail.inventory ALTER COLUMN stock_level TYPE bigint",
    "ALTER TABLE retail.inventory DROP CONSTRAINT inventory_pkey",
    "ALTER TABLE retail.inventory DROP CONSTRAINT inventory_store_id_fkey",
])
async def test_invalid_target(db, tmp_path, alter):
    await db.execute(alter)
    table, rows = loader.read_csv(make_csv(tmp_path, "inventory", [(1, 1, 0)]))
    with pytest.raises((loader.ValidationError, asyncpg.UndefinedTableError)):
        await loader.process(db, table, rows)


@pytest.mark.asyncio
async def test_missing_reference(db, tmp_path):
    table, rows = loader.read_csv(make_csv(tmp_path, "product_types", [(1, 999, "가상 유형")]))
    with pytest.raises(loader.ValidationError, match="선행 참조"):
        await loader.process(db, table, rows)
    assert await db.fetchval("SELECT count(*) FROM retail.product_types") == 0


@pytest.mark.asyncio
async def test_partial_copy_rolls_back(db, tmp_path):
    # 허용된 CSV 값을 DB의 추가 제약조건이 거부하는 실제 COPY 오류입니다.
    await db.execute("ALTER TABLE retail.categories ADD CHECK (category_id < 2)")
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "a"), (2, "b")]))
    with pytest.raises(asyncpg.CheckViolationError):
        await loader.process(db, table, rows)
    assert await db.fetchval("SELECT count(*) FROM retail.categories") == 0


@pytest.mark.asyncio
async def test_verification_failure_rolls_back(db, tmp_path):
    # 트리거로 값이 달라져도 커밋 전에 탐지하고 취소해야 합니다.
    await db.execute("""
        CREATE FUNCTION retail.change_name() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.category_name := 'changed'; RETURN NEW; END $$;
        CREATE TRIGGER change_name BEFORE INSERT ON retail.categories
        FOR EACH ROW EXECUTE FUNCTION retail.change_name();
    """)
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "original")]))
    with pytest.raises(loader.ValidationError, match="저장값 불일치"):
        await loader.process(db, table, rows)
    assert await db.fetchval("SELECT count(*) FROM retail.categories") == 0


@pytest.mark.asyncio
async def test_verify_detects_different_value_without_writes(db, tmp_path):
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "a"), (2, "b")]))
    await db.execute("INSERT INTO retail.categories VALUES (1,'b'),(2,'a')")
    before = await db.fetch("SELECT * FROM retail.categories ORDER BY category_id")
    with pytest.raises(loader.ValidationError, match="저장값 불일치"):
        await loader.process(db, table, rows, verify=True)
    assert await db.fetch("SELECT * FROM retail.categories ORDER BY category_id") == before


@pytest.mark.asyncio
async def test_read_only_role_and_rls(db, tmp_path):
    await db.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='csv_test_reader') THEN
            CREATE ROLE csv_test_reader;
          END IF;
        END $$;
        GRANT USAGE ON SCHEMA retail TO csv_test_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA retail TO csv_test_reader;
        INSERT INTO retail.categories VALUES (1,'a');
    """)
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "a")]))
    await db.execute("SET ROLE csv_test_reader")
    try:
        await loader.process(db, table, rows, verify=True)
    finally:
        await db.execute("RESET ROLE")
    await db.execute("ALTER TABLE retail.categories ENABLE ROW LEVEL SECURITY")
    await db.execute("SET ROLE csv_test_reader")
    try:
        with pytest.raises(loader.ValidationError, match="RLS"):
            await loader.process(db, table, rows, verify=True)
    finally:
        await db.execute("RESET ROLE")


@pytest.mark.asyncio
async def test_concurrent_load_only_commits_once(db, tmp_path):
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "a")]))
    other = await asyncpg.connect(os.environ["CSV_TEST_DSN"])
    try:
        results = await asyncio.gather(
            loader.process(db, table, rows), loader.process(other, table, rows),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, loader.ValidationError) for result in results) == 1
        assert await db.fetchval("SELECT count(*) FROM retail.categories") == 1
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_post_commit_failure_reports_persisted_data(db, tmp_path, monkeypatch, capsys):
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "a")]))
    original = loader.verify_records
    calls = 0

    async def fail_second_check(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise loader.ValidationError("후속 검증의 가상 오류")
        return await original(*args)

    monkeypatch.setattr(loader, "verify_records", fail_second_check)
    with pytest.raises(loader.ValidationError):
        await loader.process(db, table, rows)
    assert await db.fetchval("SELECT count(*) FROM retail.categories") == 1
    output = capsys.readouterr().out
    assert "커밋 완료, 후속 검증 실패" in output
    assert "롤백 완료" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [[(1, "a")], [(1, "a"), (2, "b"), (3, "c")]])
async def test_verify_detects_missing_or_extra_rows(db, tmp_path, stored):
    table, rows = loader.read_csv(make_csv(tmp_path, "categories", [(1, "a"), (2, "b")]))
    await db.executemany("INSERT INTO retail.categories VALUES ($1,$2)", stored)
    with pytest.raises(loader.ValidationError):
        await loader.process(db, table, rows, verify=True)
    assert await db.fetchval("SELECT count(*) FROM retail.categories") == len(stored)


@pytest.mark.asyncio
async def test_same_count_and_sum_different_rows(db, tmp_path):
    # 같은 합계여도 행별 값이 뒤바뀌면 실패해야 합니다.
    for table in ("stores", "categories", "product_types", "products"):
        _, records = loader.read_csv(ROOT / "data/source" / f"{table}.csv")
        await loader.process(db, table, records)
    ids = await db.fetch("SELECT product_id FROM retail.products ORDER BY product_id LIMIT 2")
    first, second = ids[0][0], ids[1][0]
    table, rows = loader.read_csv(make_csv(tmp_path, "inventory", [(1, first, 10), (1, second, 20)]))
    await db.executemany("INSERT INTO retail.inventory VALUES ($1,$2,$3)",
                         [(1, first, 20), (1, second, 10)])
    assert await db.fetchval("SELECT sum(stock_level) FROM retail.inventory") == 30
    with pytest.raises(loader.ValidationError, match="저장값 불일치"):
        await loader.process(db, table, rows, verify=True)
    assert await db.fetchval("SELECT sum(stock_level) FROM retail.inventory") == 30


@pytest.mark.asyncio
async def test_all_provided_csvs(db):
    # 실제 CSV를 읽되 원문은 출력하거나 테스트 스냅샷으로 저장하지 않습니다.
    order = ("stores", "categories", "product_types", "customers", "products",
             "orders", "inventory", "order_items")
    for table in order:
        _, rows = loader.read_csv(ROOT / "data/source" / f"{table}.csv")
        await loader.process(db, table, rows)
        await loader.process(db, table, rows, verify=True)
    assert await db.fetchval("SELECT sum(quantity) FROM retail.order_items") == 670351
    assert await db.fetchval("SELECT sum(total_amount) FROM retail.order_items") == Decimal("46184647.52")
