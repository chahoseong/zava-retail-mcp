# Zava MCP Server

PostgreSQL의 행 수준 보안(Row-Level Security, RLS)을 적용하여 소매 데이터(주문, 재고, 매장)를 안전하게 조회하는 Model Context Protocol(MCP) 서버 패키지다.

## 패키지 구성

- `models.py`: 도메인 및 프로토콜 Pydantic 데이터 모델
- `settings.py`: 불변 설정 로딩, 환경변수 및 개발용 사용자 권한 검증
- *(후속 단계)*: 데이터베이스 커넥션 풀 관리(`db/`), MCP 도구 핸들러(`tools/`), 서버 진입점

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
