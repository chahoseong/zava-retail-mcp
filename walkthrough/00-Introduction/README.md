# MCP 데이터베이스 통합 소개 (Introduction to MCP Database Integration)

## 이 모듈에서 다루는 내용

`11-MCPServerHandsOnLabs`는 PostgreSQL을 백엔드로 사용하는 소매 분석 MCP 서버를 구축하는 **13개의 실습(Lab 00~12)**으로 구성된 학습 과정입니다. 데이터베이스 기능을 도구(Tools)로 외부에 노출하고, 행 수준 보안(Row Level Security, RLS)을 적용하여 매장별 데이터를 격리하며, 시맨틱 제품 검색(Semantic Product Search)을 추가하고, 테스트 및 운영 전반을 살펴봅니다.

본 실습의 사례 연구 대상은 가상의 DIY 소매업체인 **Zava Retail**입니다. 실습 과정에서 활용하는 실제 구현 코드는 부속 [소매 서버 저장소(retail server repository)](https://github.com/microsoft/MCP-Server-and-PostgreSQL-Sample-Retail)에서 제공합니다. 현재 커리큘럼 디렉터리에는 학습 문서와 주요 코드 스니펫이 수록되어 있으므로, 전체 애플리케이션 소스 코드와 의존성 파일은 해당 부속 프로젝트의 안내를 따라 준비하시기 바랍니다.

> [!IMPORTANT]
> **2026년 10월 30일 공식 문서 기준 검토 완료.** 현재 공식 사양은 MCP `2026-07-28`입니다. 본 과정의 목표 서버 스택은 공식 `mcp` Python SDK입니다. 이후 실습 문서에는 독립형 FastMCP, 이전 방식인 HTTP+SSE, 초기화 핸드셰이크, 세션 기반 예제가 남아 있습니다. 공식 SDK 기반 구현으로 전환할 때는 클라이언트 및 SDK 릴리스의 호환성을 확인해야 합니다. 본 개요 문서는 후속 실습의 구현 코드를 직접 마이그레이션하지 않습니다. 자세한 내용은 [프로토콜 호환성 참고사항](#protocol-compatibility-notes)을 참조하세요.

## 학습 목표

이 학습 과정을 마치면 다음을 수행할 수 있게 됩니다:

- MCP 호스트(Host), 클라이언트(Client), 서버(Server), 데이터베이스(Database)의 역할을 명확히 설명할 수 있습니다.
- 스키마 탐색(Schema Discovery) 및 제어된 데이터베이스 쿼리를 위한 도구(Tools)를 구현할 수 있습니다.
- 사용자 인증(Authentication), 애플리케이션 수준 인가(Application Authorization), 데이터베이스 행 수준 보안(Row Level Security, RLS)의 책임을 명확히 구분하여 설계할 수 있습니다.
- 임베딩(Embeddings)을 생성하고 pgvector를 활용하여 제품 벡터 유사도 검색(Vector Similarity Search)을 수행할 수 있습니다.
- 테넌트 격리(Tenant Isolation), 도구 동작, 장애 상황 및 성능을 테스트하고 검증할 수 있습니다.
- 서버를 안전하게 배포하고 운영하기 위해 필요한 추가 작업과 보안 모범 사례를 설명할 수 있습니다.

## MCP의 역할과 제공 가치

**모델 컨텍스트 프로토콜(Model Context Protocol, MCP)**은 AI 애플리케이션이 외부 서버와 컨텍스트를 교환하고 외부에서 제공하는 기능을 호출하는 방식을 표준화한 개방형 프로토콜입니다. VS Code와 같은 호스트(Host)는 AI 모델과 MCP 클라이언트를 조율하며, 클라이언트는 도구(Tools), 리소스(Resources), 프롬프트(Prompts)를 노출하는 서버와 통신합니다. 이번 실습 시리즈는 데이터베이스 도구 구현에 집중합니다. 전체적인 구조는 [공식 아키텍처 문서](https://modelcontextprotocol.io/specification/2026-07-28/architecture)를 참조하세요.

예를 들어, 사용자가 "우리 매장에서 가장 많은 매출을 올린 제품은 무엇인가요?"라고 질문할 수 있습니다. AI 애플리케이션은 사용 가능한 도구를 탐색(Discovery)하고, 스키마 정보를 요청한 뒤, 도구를 통해 데이터베이스 쿼리를 실행합니다. 서버는 호출자의 권한을 확인하고 허용된 데이터베이스 작업만 실행한 후 결과를 반환하며, AI 모델은 이 결과를 바탕으로 사용자에게 자연스러운 설명을 제공합니다.

호스트와 AI 모델은 사용자의 자연어를 해석하는 역할을 맡고, 서버와 데이터베이스는 접근 제한과 보안을 강제합니다. 데이터의 최신성은 연결된 데이터베이스와 데이터 수집(Ingestion) 파이프라인에 따라 달라집니다. MCP 자체가 올바른 SQL 작성, 데이터 최신성, 안전한 배포 환경을 자동으로 보장해 주는 것은 아닙니다.

## 학습 사례 연구: Zava Retail

본 실습에서는 오프라인 매장과 온라인 채널 전반의 매출 분석 및 제품 탐색을 살펴보기 위해 매장(Stores), 고객(Customers), 제품(Products), 주문(Orders), 주문 항목(Order Items) 데이터를 활용합니다. 예제마다 매장 수와 초기 데이터(Seed Data) 구성이 다를 수 있으므로, 매장 수가 고정되어 있다고 가정하기보다는 데이터베이스에 실제로 적재된 데이터를 직접 확인하시기 바랍니다.

| 시나리오 | 요청 예시 | 구현 및 검증 내용 |
| :--- | :--- | :--- |
| **매장별 분석(Store analytics)** | "우리 매장에서 매출 상위 10개 제품을 보여줘." | 쿼리 도구, 집계(Aggregation), 매장별 접근 권한 인가 |
| **제품 탐색(Product discovery)** | "실외에서 사용하기에 적합한 커넥터를 찾아줘." | 텍스트 임베딩(Text Embeddings) 및 벡터 유사도 검색 |
| **지역별 보고(Regional reporting)** | "내가 담당하는 매장들의 매출을 비교해줘." | 다중 매장 접근을 위한 명시적 권한 및 보안 정책 |

보고서 기간을 조회할 때는 초기 적재 데이터의 날짜 범위 내에서 선택해야 합니다. 유사도 검색은 제품의 재고 유무를 확인해 주지 않으므로, 재고 분석을 위해서는 관련 데이터와 별도 도구가 필요합니다. 또한 지역 단위 접근 역시 명시적으로 구현된 보안 정책이 있어야 가능합니다. 단순히 프롬프트에 직책(예: '지역 관리자')을 명시한다고 해서 권한이 자동으로 부여되는 것은 아닙니다.

## 아키텍처 및 요청 흐름

다음 다이어그램은 최신 HTTP 구현을 위한 목표 아키텍처를 보여줍니다. 후속 실습의 일부 레거시 전송 코드는 향후 마이그레이션이 필요합니다.

```text
사용자 질문 입력
        |
        v
AI 호스트 (예: VS Code) + 모델
        |
        v
MCP 클라이언트
        | Streamable HTTP: 기능 탐색 / 도구 호출
        v
Python MCP 서버 (공식 mcp SDK)
  - 신원 및 애플리케이션 권한 검증
  - 도구 인자 유효성 검사 및 데이터베이스 작업 제한
  - DB 트랜잭션별 신뢰할 수 있는 매장 컨텍스트 수립
        |
        +-- asyncpg --> PostgreSQL + pgvector
        |               소매(Retail) 테이블, RLS, 저장된 제품 벡터
        |
        +-- HTTPS ----> Azure OpenAI 임베딩 엔드포인트
                        시맨틱 검색을 위한 텍스트-벡터 생성
```

1. 호스트는 모델과 도구 설명을 참조하여 수행할 작업을 선택합니다.
2. 클라이언트는 구조화된 MCP 도구 호출 요청과 해당 인자를 전달합니다.
3. 서버는 호출자의 신원을 인증(Authenticate)하고, 허용된 매장 접근 범위(Store Scope)를 결정합니다.
4. SQL 분석 작업의 경우, 서버는 작업을 검증한 후 적절한 데이터베이스 권한과 RLS 컨텍스트 하에서 PostgreSQL에 쿼리를 실행합니다.
5. 시맨틱 검색 작업의 경우, 애플리케이션 코드가 임베딩 엔드포인트에서 벡터를 받아와 저장된 제품 벡터를 검색합니다. (제품 임베딩은 사전에 데이터베이스에 저장되어 있어야 하며, 검색 쿼리 임베딩은 호환 가능한 모델과 동일한 벡터 차원을 사용해야 합니다.)
6. 서버는 호스트가 사용자에게 표시할 수 있도록 MCP를 통해 처리 결과를 반환합니다.

본 설계에서 임베딩 엔드포인트를 호출하는 주체는 **애플리케이션(MCP 서버)**입니다. PostgreSQL은 벡터를 저장하고 유사도를 계산할 뿐, pgvector 자체가 텍스트 임베딩을 직접 생성하지는 않습니다. 자세한 내용은 [pgvector 공식 문서](https://github.com/pgvector/pgvector) 및 [Azure OpenAI 임베딩 가이드](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/embeddings?view=foundry-classic)를 참조하세요.

## 기술 스택 및 사전 요구사항 <a id="technology-stack-and-prerequisites"></a>

기본적인 Python 프로그래밍, 비동기 프로그래밍, SQL, HTTP 및 명령줄 환경(CLI)에 익숙하면 실습에 큰 도움이 됩니다. MCP 개념이 처음이라면 커리큘럼의 앞선 입문 과정부터 시작하는 것을 권장합니다. 실습을 시작하려면 Git, Python 3.12 이상 환경, Docker가 기본적으로 필요합니다. Azure 기반 시맨틱 검색 실습을 진행하려면 Azure 계정 자격 증명과 임베딩 모델 배포가 필요하며, 클라우드 배포 실습에는 관련 Azure 리소스와 CLI 도구가 추가로 요구됩니다. VS Code의 AI 기능 설정은 [최신 VS Code MCP 공식 가이드](https://code.visualstudio.com/docs/agent-customization/mcp-servers)를 참조하시기 바랍니다.

### 기본 사항

| 구성 요소 | 버전 | 주요 역할 및 설명 |
| :--- | :--- | :--- |
| **Python** | `3.12+` | MCP 서버 및 데이터베이스 연동 코드를 실행하는 언어 런타임 |
| **uv** | `0.13.6` | Python 버전 관리, 가상환경 구성 및 프로젝트 패키지 의존성 관리 |
| **MCP Python SDK** | `2.3.0` | 데이터베이스 도구(Tools) 정의 및 고수준 MCP 서버 구축 |
| **PostgreSQL** | `18` | 소매 비즈니스 데이터 저장, 관계형 쿼리 처리 및 행 수준 보안(RLS) 적용 |
| **pgvector** | `0.8.7` | 제품 임베딩 벡터 저장 및 코사인 유사도 검색 지원 |
| **asyncpg** | `0.32.0` | 비동기 데이터베이스 연결 풀링(Connection Pooling) 및 쿼리 실행 |
| **EmbeddingGemma 2** | `2B` | 제품 설명 및 검색어에 대한 768차원 로컬 텍스트 임베딩 생성 (기본 모델) |
| **Docker Engine & Compose** | `29.9.2 / 5.6.1` | PostgreSQL 및 MCP 서버 컨테이너 기반 로컬 통합 실행 환경 |
| **VS Code** | `1.144.0` | 코드 개발·디버깅 및 AI Chat 기반 MCP 호스트 연동 테스트 환경 |
| **pytest & pytest-asyncio** | `9.2.0 / 1.4.1` | 단위·통합 테스트 및 비동기 쿼리 동작 검증 (개발·테스트용) |

### 선택 사항 (클라우드 서비스 및 확장 환경)

| 구성 요소 | 버전 | 주요 역할 및 설명 |
| :--- | :--- | :--- |
| **Azure OpenAI** | `-` | 클라우드 기반 텍스트 임베딩 생성 서비스 (로컬 모델 대신 클라우드 모델 전환 시 활용) |
| **Azure 서비스** | `-` | 클라우드 호스팅(Container Apps), 시크릿 보관(Key Vault) 및 모니터링(Application Insights) |

## 학습 경로: Lab 00–12

| 단계 | 실습(Labs) | 주요 학습 내용 |
| :--- | :--- | :--- |
| **기초 (Foundations)** | 00 개요(Introduction), [01 아키텍처(Architecture)](../01-Architecture/README.md), [02 보안(Security)](../02-Security/README.md), [03 환경 설정(Setup)](../03-Setup/README.md) | 각 계층의 책임, 신뢰 경계(Trust Boundary), 실습 환경 구축. |
| **구현 (Implementation)** | [04 데이터베이스(Database)](../04-Database/README.md), [05 MCP 서버(MCP Server)](../05-MCP-Server/README.md), [06 도구(Tools)](../06-Tools/README.md) | 스키마 설계, DB 연결 풀 구성, 제어된 쿼리 도구 작성. |
| **검색 및 검증 (Search and validation)** | [07 시맨틱 검색(Semantic Search)](../07-Semantic-Search/README.md), [08 테스트(Testing)](../08-Testing/README.md), [09 VS Code](../09-VS-Code/README.md) | 임베딩 생성, 동작 검증, AI 클라이언트 연동. |
| **배포 및 운영 (Deployment and operations)** | [10 배포(Deployment)](../10-Deployment/README.md), [11 모니터링(Monitoring)](../11-Monitoring/README.md), [12 모범 사례(Best Practices)](../12-Best-Practices/README.md) | 호스팅, 관측 가능성(Observability), 성능 최적화, 보안 강화. |

처음 학습할 때는 순서대로 실습을 진행하는 것이 좋습니다. 특정 주제에 집중하여 복습하려면 데이터베이스 도구는 04~06, 데이터 격리 및 검증은 02와 08, 시맨틱 검색은 07, 배포와 운영은 10~12를 중점적으로 확인하세요. 전체 실습 목록은 [모듈 안내서(Module Guide)](../README.md)에서 확인할 수 있습니다.

## 보안 책임 및 구현 요건

RLS는 데이터베이스 인가 메커니즘이며, **사용자 인증 시스템(Authentication System)이 아닙니다**. 인증은 호출자가 누구인지 확인하고, 애플리케이션 인가는 해당 사용자가 접근할 수 있는 매장과 허용된 작업을 결정하며, RLS는 쿼리를 실행하는 데이터베이스 역할(Role)에 대해 조회 가능한 행(Row)을 엄격히 제한합니다. 지원되는 전송 인가 흐름에 대한 내용은 [MCP HTTP 인가 사양](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)을 참조하세요.

실제 구현 시 다음 요구사항에 각별히 유의해야 합니다:

- **신뢰할 수 있는 신원 (Trusted identity):** 매장 접근 범위(Store Scope)는 반드시 검증된 사용자 신원과 서버 측 권한 정보로부터 도출해야 합니다. 클라이언트가 임의로 전달한 `store_id`나 `rls_user_id` 값 자체는 인가의 증거가 될 수 없습니다.
- **데이터베이스 역할 (Database roles):** 보안 대상 테이블에 RLS를 명시적으로 활성화해야 합니다. 슈퍼유저(Superusers) 및 `BYPASSRLS` 권한을 가진 역할은 RLS를 우회하며, 테이블 소유자 역시 기본적으로 우회합니다. 따라서 런타임에는 권한이 제한된 데이터베이스 역할을 사용하고, 필요에 따라 `FORCE ROW LEVEL SECURITY` 설정을 검토하세요. 자세한 내용은 [PostgreSQL 행 보안 정책 공식 문서](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)를 참조하세요.
- **연결 풀 (Connection pools):** 매장 컨텍스트는 반드시 쿼리를 실행하는 해당 트랜잭션 범위 내로 한정(Scope)해야 합니다. 연결 풀 재사용으로 인해 이전 호출자의 컨텍스트가 후속 요청으로 유출되는 문제를 원천 차단해야 합니다.
- **쿼리 경계 (Query boundaries):** 사전 정의된 쿼리에서 파라미터화(Parameterize)를 적용하고 허용된 작업만 수행하도록 제한해야 합니다. 임의의 SQL 문자열 전체를 단순히 파라미터화나 키워드 필터링만으로 안전하게 만들 수는 없습니다. 데이터베이스 계정 권한, 호출 가능한 함수, 쿼리 실행 시간, 결과 반환 건수도 함께 제한해야 합니다.
- **운영 통제 (Operational controls):** TLS 암호화, 시크릿(Secret) 안전 보관, 감사 로깅(Audit Logging), 민감한 데이터가 노출되지 않는 오류 처리 체계를 갖추어야 합니다. RLS 자체가 감사 로그를 자동으로 남겨주지는 않습니다.

학습용 코드 스니펫은 입문을 위한 출발점일 뿐입니다. 실습 튜토리얼을 완료했다고 해서 해당 구현이 상용 환경(Production)에 바로 배포될 준비가 되었음을 의미하지는 않습니다.

## 프로토콜 호환성 참고사항 <a id="protocol-compatibility-notes"></a>

[MCP 2026-07-28 변경 로그(Changelog)](https://modelcontextprotocol.io/specification/2026-07-28/changelog)에 명시된 바와 같이, 최신 프로토콜에서는 기존의 `initialize` 핸드셰이크와 프로토콜 수준의 세션(Session) 개념이 제거되었습니다. 각 요청은 자체적으로 프로토콜 버전과 지원 기능을 전달합니다. 서버는 `server/discover` 엔드포인트를 구현하여 지원 가능한 기능과 버전을 외부에 알립니다.

원격 HTTP 서버의 경우 [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)를 사용합니다. 이는 이전의 HTTP+SSE 전송 계층을 대체하며, 필요한 경우 여전히 SSE 응답 스트림을 반환할 수 있습니다. 원시(Raw) HTTP 요청을 직접 전송할 때는 `MCP-Protocol-Version`과 `Mcp-Method` 헤더를 포함해야 하며, 특정 메서드의 경우 `Mcp-Name` 헤더도 함께 전송해야 합니다. 가능한 경우 호환되는 SDK가 이러한 세부 처리를 담당하도록 구성하는 것이 좋습니다.

예제 코드 중 `sse_app()`, 초기화 핸드셰이크 또는 프로토콜 세션 ID를 사용하는 부분은 이전 방식의 동작을 설명합니다. 단순히 전송 이름만 바꾼다고 해서 프로토콜 마이그레이션이 완료되는 것은 아닙니다. [공식 SDK 가이드](https://modelcontextprotocol.io/docs/sdk)와 사용 중인 프레임워크의 릴리스 문서를 참조하여 클라이언트 및 서버 간의 상호 운용성과 패키지 지원 여부를 확인하시기 바랍니다.

## 다음 단계

서버 레이어 구조와 데이터베이스 설계를 자세히 학습하려면 [Lab 01: 핵심 아키텍처 개념(Core Architecture Concepts)](../01-Architecture/README.md)으로 이동하세요.
