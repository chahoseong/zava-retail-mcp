# Zava MCP Server

PostgreSQL의 행 수준 보안(Row-Level Security, RLS)을 적용하여 소매 데이터(주문, 재고, 매장)를 안전하게 조회하는 Model Context Protocol(MCP) 서버 패키지다.

## 패키지 구성

- `models.py`: 도메인 및 프로토콜 Pydantic 데이터 모델
- `settings.py`: 불변 설정 로딩, 환경변수 및 개발용 사용자 권한 검증
- `server.py`: MCP 서버 객체 구성
- `__main__.py`: 설정 검증 및 Streamable HTTP 서버 실행 진입점
- `runtime.py`: 공유 DB 연결 풀 생성, 시작 준비 확인 및 종료 정리
- *(후속 단계)*: 매장별 데이터 접근 및 주문 조회 도구

---

## 실행 준비

모든 작업은 프로젝트 루트에서 실행한다. 관리자 설정(`.env`)과 조회 전용 서비스 계정 설정(`.env.reader`)을 엄격히 구분하며, 이미 사용 중인 `.env.reader`를 예시 파일로 덮어쓰지 않는다.

```powershell
uv sync --locked

# 로컬 개발자 설정 파일이 없으면 예시 파일을 복사해 준비한다
if (-not (Test-Path -LiteralPath config/dev-user.json)) {
    Copy-Item -LiteralPath config/dev-user.example.json -Destination config/dev-user.json
}

# 비밀번호를 출력하거나 DB에 접속하지 않고 설정 검증만 수행한다
uv run --locked --env-file .env.reader python -c "from zava_mcp_server.settings import load_settings; s = load_settings(); print(s.server); print(s.pool); print(s.user)"
```

- 새 환경의 DB 접속 정보는 루트의 [.env.reader.example](../.env.reader.example)을 참고하여 실제 조회 계정 정보로 `.env.reader`를 작성한다.
- `uv`가 환경 파일의 값을 실행 환경에 불러오며, Python 코드는 환경변수만 읽는다. 관리자(`.env`) 설정으로 임의 대체하지 않는다.

---

## 서버 실행 및 HTTP 통신 확인

프로젝트 루트의 첫 번째 터미널에서 실행한다.

```powershell
uv run --locked --env-file .env.reader python -m zava_mcp_server
```

두 번째 터미널도 프로젝트 루트에서 열고, 실제 서버 URL로 SDK 클라이언트를 실행한다.
클라이언트에는 DB 환경 파일이 필요하지 않다.

```powershell
uv run --locked python scripts/check_mcp_server.py http://127.0.0.1:8000/mcp
```

도구가 등록되지 않은 현재 단계의 예상 출력은 `[]`이며, 정상 종료 코드는 `0`이다.
이 결과는 실제 HTTP를 통한 MCP 도구 목록 조회가 성공했음을 뜻한다.
클라이언트는 통신에 15초 제한을 두며 실패하면 오류 안내와 종료 코드 `1`을 반환한다.
이후 도구를 추가하면 도구 이름 목록을 출력한다.

기본 주소는 `http://127.0.0.1:8000/mcp`다. `.env.reader`의 `MCP_PORT`나 `MCP_PATH`를
변경했다면 클라이언트 URL도 맞춘다. 서버 실행은 `MCP_HOST=127.0.0.1`만 허용한다.
설정 모델의 일반 루프백 주소 검증과 별도로 실행 진입점에서 이 범위를 제한한다.
Host는 `127.0.0.1:<실행 포트>`, Origin은 `http://127.0.0.1:<실행 포트>`만 허용한다.
Origin 헤더가 없는 SDK 요청은 허용하며, `localhost` 별칭과 다른 포트·출처는 허용하지 않는다.

설정 검증에 실패하면 요청을 받기 전에 종료 코드 `1`로 종료한다.
설정 검증 후 DB 연결 풀을 생성하고 조회 계정과 `retail.orders` 조회 가능 여부를 확인한다.
DB가 실행 중이고 조회 계정 설정이 유효해야 시작할 수 있다. 준비 실패 시에도 종료 코드는 `1`이다.
서버를 종료하려면 첫 번째 터미널에서 `Ctrl+C`를 누르고 종료 완료를 확인한다.

---

## DB 연결 풀 수명주기 (`runtime.py`)

서버 시작 시 공유 풀 하나를 생성하고 SDK Lifespan으로 종료 시까지 관리한다.
서버 객체 구성이나 모듈 import만으로 DB에 접속하지 않는다.
설정의 접속 사용자와 DB의 실제 `current_user`·`session_user`가 모두 `zava_mcp_reader`여야 한다.
이후 `SELECT order_id FROM retail.orders LIMIT 1`의 실행 성공을 확인한다.
RLS 매장 정보가 없어 빈 결과가 나와도 정상이며, 조회한 값은 출력하지 않는다.
이 확인은 테이블 조회 준비 검사이며 매장 권한이나 RLS 격리 정확성 검증은 아니다.

| 설정 | 적용 대상 |
| :--- | :--- |
| `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE` | 풀의 최소·최대 연결 수 |
| `DB_CONNECT_TIMEOUT` | 새 DB 연결 생성 |
| `DB_ACQUIRE_TIMEOUT` | 준비 확인용 연결 대여 및 이후 데이터 접근에 전달할 대여 제한 |
| `DB_QUERY_TIMEOUT` | 연결의 기본 명령 제한 및 준비 확인 쿼리 |
| `DB_SHUTDOWN_TIMEOUT` | 풀 종료 대기 |

준비 확인용 연결은 성공·실패 모두에서 반환한다. 최소 연결 수가 `0`이어도 준비 확인에서
실제 연결을 빌려 검사한다. 준비를 통과한 풀과 대여 시간 제한은 `RuntimeContext`로 공유한다.
후속 데이터 접근 코드는 이 풀을 전달받아 사용하며 요청마다 새 풀을 만들지 않는다.

풀 생성 후 준비 실패와 정상 종료에서는 시간 제한 안에서 풀을 닫는다.
초기 풀 생성 도중 실패하거나 취소된 연결은 고정된 asyncpg 0.32 드라이버가 정리한다.
풀 종료 시간이 초과되거나 종료 오류·취소가 발생하면 `terminate()`로 강제 정리한다.
취소 신호는 정리 후 다시 전달하며 정상 종료와 강제 정리 로그를 구분한다.
DB 원본 예외·비밀번호·전체 접속 문자열·조회 결과를 로그로 출력하지 않는다.

DB 대역을 사용하는 자동 테스트는 실제 DB에 접속하거나 스키마를 변경하지 않는다.

```powershell
uv run --locked python -m pytest tests/test_runtime.py -q -o asyncio_default_fixture_loop_scope=function
```

실제 접속 확인은 앞의 서버·클라이언트 명령을 사용한다.
시작 시 `DB 준비 완료`, 종료 시 `DB 풀 정상 종료 완료` 로그를 확인한다.
`DB 풀 강제 정리 완료`는 시간 초과 등으로 정상 종료 대신 강제 정리한 결과다.
자동 테스트는 실패 경로의 정리·반환을 검사하며, 실제 확인에서는 DB 접속·HTTP 응답과
풀의 종료 상태도 함께 확인한다. 로그 한 줄만으로 자원 정리가 완료됐다고 판단하지 않는다.

---

## 코드 품질 검사

코드 수정 후 아래 명령으로 정적 분석과 서식을 검사한다. 세부 린트 규칙과 Strict 타입 설정은 루트 [pyproject.toml](../pyproject.toml)을 단일 진실 공급원(SSOT)으로 따른다.

```powershell
uv run --locked ruff check zava_mcp_server
uv run --locked ruff format --check zava_mcp_server
uv run --locked mypy zava_mcp_server
# 서식 자동 적용: uv run --locked ruff format zava_mcp_server
```

---

## 서버 설정 및 환경 검증 (`settings.py`)

`settings.py`는 환경변수와 개발용 사용자 JSON을 읽어 Pydantic으로 검증한다. 설정값의 유효성만 확인하며, DB 접속, 커넥션 풀 생성, MCP 서버 구동은 수행하지 않는다 (단일 책임 원칙).

### 환경변수 규격

| 환경변수 | 필수 여부·기본값 | 검사 조건 |
| :--- | :--- | :--- |
| `POSTGRES_HOST` | 필수 | 공백만으로 구성되지 않은 문자열 |
| `POSTGRES_PORT` | 필수 | 정수, 1~65,535 |
| `POSTGRES_DB` | 필수 | 공백만으로 구성되지 않은 문자열 |
| `POSTGRES_USER` | 필수 | 공백만으로 구성되지 않은 문자열 (조회 계정 사용) |
| `POSTGRES_PASSWORD` | 필수 | 비어 있지 않은 비밀 문자열 (`SecretStr`) |
| `MCP_HOST` | `127.0.0.1` | 루프백 IP 또는 `localhost` |
| `MCP_PORT` | `8000` | 정수, 1~65,535 |
| `MCP_PATH` | `/mcp` | `/`로 시작하며 `//`·공백·쿼리·프래그먼트·역슬래시 제외 |
| `DB_POOL_MIN_SIZE` | `1` | 0 이상의 정수 |
| `DB_POOL_MAX_SIZE` | `5` | 1 이상의 정수 |
| `DB_CONNECT_TIMEOUT` | `10`초 | 유한한 양수 (소수 허용) |
| `DB_ACQUIRE_TIMEOUT` | `5`초 | 유한한 양수 (소수 허용) |
| `DB_QUERY_TIMEOUT` | `10`초 | 유한한 양수 (소수 허용) |
| `DB_SHUTDOWN_TIMEOUT` | `10`초 | 유한한 양수 (소수 허용) |
| `DEV_USER_FILE` | `config/dev-user.json` | 비어 있지 않고 읽기 가능한 UTF-8 JSON 파일 경로 |

#### 풀 설정 및 경로 해석 규칙
- **연결 수 제약**: 최소 연결 수는 최대 연결 수보다 클 수 없다 (`DB_POOL_MIN_SIZE <= DB_POOL_MAX_SIZE`).
- **기본값 정책**: 환경변수가 지정되지 않았을 때만 기본값을 적용한다. 빈 문자열이나 잘못된 형식은 기본값으로 대체하지 않고 검증 오류로 처리한다.
- **경로 해석 기준**: `DEV_USER_FILE`의 상대 경로는 실행 위치와 무관하게 항상 **프로젝트 루트**를 기준으로 해석한다 (절대 경로는 그대로 유지).

---

## 개발용 사용자 권한 (`dev-user.json`)

[config/dev-user.example.json](../config/dev-user.example.json)을 복사해 로컬 설정 파일을 준비한다. 예시 파일은 버전 관리 대상이지만, 실제 로컬 파일(`config/dev-user.json`)은 Git 추적에서 제외한다.

```json
{
  "user_id": "dev-manager",
  "allowed_actions": ["orders:count"],
  "allowed_store_ids": [1]
}
```

### 검증 규칙
- **필수 필드**: `user_id`, `allowed_actions`, `allowed_store_ids` 세 필드 모두 필수이며 누락 시 오류가 발생한다.
- **사용자 식별자**: 공백만으로 구성된 문자열은 허용하지 않는다.
- **허용 작업 및 매장**: JSON 배열이어야 하며, 매장 ID는 PostgreSQL `INTEGER` 범위의 양의 정수만 허용한다 (문자열·소수·불리언 불가).
- **빈 배열(`[]`) 처리**: 명시적인 빈 배열은 '권한 없음'으로 정상 처리하며, 필드 누락이나 형식 오류와 엄격히 구분한다.
- **알 수 없는 필드 금지**: 스키마에 정의되지 않은 필드가 포함되면 즉시 검증 오류를 발생시킨다 (`extra='forbid'`).
- **불변 집합 변환**: 중복을 제거하여 불변 집합(`frozenset`)으로 변환해 반환한다.
- **보안 주체와 권한 범위**: 이 정보는 개발 편의를 위한 가상 보안 주체(Principal) 정보이며 실제 인증 결과가 아니다. 작업과 매장 접근을 허용할지 결정하는 인가(Authorization)는 후속 비즈니스 로직에서 수행한다.

---

## 반환값 및 보안 처리

- **불변 설정 객체**: `load_settings()`는 변경 불가능한 `Settings` 객체(`db`, `server`, `pool`, `user`, `dev_user_file`)를 반환한다. 서버 시작 시 단 1회 로드하여 각 계층에 전달한다.
- **테스트 환경 지원**: 단위 테스트 등에서 환경변수 대신 딕셔너리를 직접 전달할 수 있도록 `load_settings(environment)` 호출도 지원한다.
- **설정 예외**: 검증 실패 시 `SettingsError`가 발생하며 대상 항목과 원인을 명시한다. 보안을 위해 오류 메시지에는 사용자가 입력한 원본 값을 포함하지 않는다.
- **비밀번호 보호**: 비밀번호는 `SecretStr`로 보호되어 로그나 문자열 출력 시 평문이 가려진다. 실제 DB 연결 시에만 `.get_secret_value()`로 추출해 사용한다.
- **검증의 한계**: 이 모듈의 검증 성공은 설정값의 존재·자료형·형식 조건이 유효함을 의미한다. 실제 DB 계정 권한, 네트워크 연결 상태, 서버 포트 사용 여부는 후속 단계에서 확인한다.
