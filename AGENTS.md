# AGENTS.md

## Project Overview

**Zava Retail MCP Server**: PostgreSQL(RLS) 기반 소매 데이터(주문, 재고, 매장 등) 조회를 제공하는 Model Context Protocol (MCP) 서버.

- **런타임**: Python 3.12+, `uv` (Strict `uv.lock`)
- **주요 라이브러리**: MCP Python SDK (Streamable HTTP), `asyncpg`, `pydantic` v2
- **데이터베이스**: PostgreSQL 18 with pgvector (`compose.yaml` 참조)

---

## Essential Commands

아래 명령은 프로젝트 루트에서 실행하며, 환경 동기화와 Python 실행에는 `--locked`를 사용한다.

### 환경 동기화 & 로컬 설정 준비

```powershell
uv sync --locked
if (-not (Test-Path -LiteralPath config/dev-user.json)) {
    Copy-Item -LiteralPath config/dev-user.example.json -Destination config/dev-user.json
}
```

### 정적 분석 & 테스트

변경에 맞는 검사를 선택한다. `pytest`의 DB 통합 테스트 실행 조건은 아래 검증 절차를 따른다.

```powershell
uv run --locked ruff check zava_mcp_server
uv run --locked ruff format --check zava_mcp_server
uv run --locked mypy zava_mcp_server
uv run --locked pytest
```

### 서식 자동 적용

```powershell
uv run --locked ruff format zava_mcp_server
```

### 설정 검증

```powershell
# 비밀번호 및 시크릿을 노출하지 않고 설정 객체만 검증
uv run --locked --env-file .env.reader python -c "from zava_mcp_server.settings import load_settings; s = load_settings(); print(s.server); print(s.pool); print(s.user)"
```

---

## Architecture & Layered Responsibilities

- **Protocol Layer**: MCP 도구 등록, Pydantic 입력 검증, 서버가 제공하는 `UserContext` 전달을 담당하며 직접 SQL을 실행하거나 DB 풀에 접근하지 않는다.
- **Business Layer**: `UserContext`의 `allowed_actions`와 `allowed_store_ids`를 확인하고, 권한이 없으면 풀에서 연결을 대여하기 전에 요청을 거부한다.
- **Data Access Layer**: 아래 DB 접근 규칙에 따라 승인된 매장의 데이터를 조회하고 연결 객체 대신 도메인 값이나 모델을 반환한다.
- **Infrastructure Layer**: 시작 시 `load_settings()`로 환경변수를 한 번 검증해 불변 설정을 제공하고 연결 풀의 수명주기를 관리한다.

---

## Boundaries & Guardrails (Never Do This)

1. **Security**:
   - MCP 서버 구동 및 서버의 조회에는 관리자 계정(`.env`)을 사용하지 않는다. 최소 권한 계정인 `--env-file .env.reader`를 사용한다.
   - 비밀번호, 연결 문자열, 시크릿을 로그나 콘솔에 평문 출력하지 않는다.
   - `.env`, `.env.reader`, `config/dev-user.json`은 절대 Git에 커밋하지 않는다.
2. **Database**:
   - 비즈니스 권한 검증 통과 전에 DB 커넥션을 풀에서 대여하지 않는다.
   - 같은 연결의 `async with connection.transaction()` 안에서 `set_config('app.current_store_id', $1, true)`로 승인된 매장 ID를 설정하고 조회한다. 매장 ID는 문자열 값으로 바인딩하며, SQL 값은 문자열 조합 없이 매개변수로 전달한다.
   - 연결은 `async with pool.acquire()`로 대여하고 컨텍스트 종료 시 풀에 반환한다. 직접 대여한 경우에는 `finally`에서 `pool.release()`를 호출한다.
   - 파괴적 작업(`DROP`, `TRUNCATE`, 조건 없는 `DELETE`)은 금지한다. 아래 조건을 충족한 DB 통합 테스트의 스키마 재구성만 예외로 허용한다.
3. **Directory Boundaries**:
   - `zava_mcp_server/`: 주 개발 작업 대상.
   - `sql/`: 데이터베이스 스키마 및 RLS 정책 정의 (명시적 요청이 없는 한 읽기 전용 참조).
   - `.agents/`: 에이전트 확장 스킬 (`archify` 등) - 임의 수정 금지.
4. **Dependencies**:
   - 사용자 승인 없이 신규 의존성을 추가하거나 변경하지 않는다. 승인된 의존성 변경은 `pyproject.toml`과 `uv.lock`을 함께 갱신하고 `uv sync --locked`로 검증한다.
   - 일반 실행에는 `--locked`를 사용한다. 전체 업그레이드인 `uv lock --upgrade`는 별도 요청 없이 실행하지 않는다.

---

## Agent Verification Workflow

위 명령 목록에서 변경 내용에 맞는 검사를 선택한다.

- 서버 코드 변경: Ruff 린트·서식 검사와 mypy를 실행한다. 동작에 영향을 주는 변경에는 관련 테스트도 실행한다.
- 그 밖의 코드 변경: 해당 코드와 동작에 맞는 검사를 실행한다.
- 문서만 변경: 내용, 명령, 파일 경로와 링크를 확인하고 변경 내용을 검토한다.
- 결과 보고: 실행한 검사와 통과·실패·중단·건너뜀을 구분한다. 건너뛴 검사는 통과로 보고하지 않는다.

### DB 통합 테스트

- 기존 CSV 적재 테스트는 `CSV_TEST_DSN`이 없으면 DB 통합 테스트를 건너뛴다. DB 없는 단위 테스트를 실행할 때는 이 변수가 설정되지 않았는지 확인한다.
- DB 통합 테스트는 사용자에게 실행 승인을 받고, 대상이 기존 실습 DB와 분리된 전용 테스트 DB임을 확인한 뒤 실행한다. 환경변수 설정만으로 실행 승인을 간주하지 않는다.
- 기존 테스트의 `zava_csv_test` DB 이름 접두사 검사를 유지한다. 이름 검사만으로 격리가 확인되는 것은 아니며, 해당 DB에는 보존할 데이터가 없어야 한다.
- 승인된 전용 테스트 DB에서만 테스트에 필요한 권한을 사용하고, 테스트가 수행하는 스키마 삭제·재구성을 허용한다. MCP 서버의 조회 계정 원칙은 그대로 유지한다.
