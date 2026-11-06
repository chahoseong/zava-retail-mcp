# CSV를 PostgreSQL에 적재하기

`csv_to_postgres.py`는 한 번에 CSV 하나를 같은 이름의 `retail` 테이블에 저장합니다.
대상 테이블과 선행 데이터를 준비하고, `.env`에 준비용 계정의 DB 접속 정보를 설정하세요.
아래 명령은 프로젝트 루트에서 실행합니다.

```powershell
# CSV 하나 적재
uv run --locked --env-file .env python scripts/csv_to_postgres.py data/source/stores.csv

# DB 변경 없이 CSV와 모든 저장값 비교
uv run --locked --env-file .env python scripts/csv_to_postgres.py data/source/stores.csv --verify
```

## 적재 순서

아래 순서로 파일을 하나씩 실행합니다. 같은 단계의 두 파일은 순서를 바꿔도 됩니다.
선행 데이터는 자동으로 적재하지 않습니다.

1. `stores.csv`, `categories.csv`
2. `product_types.csv`, `customers.csv`
3. `products.csv`, `orders.csv`
4. `inventory.csv`, `order_items.csv`

## 실행 결과

결과는 콘솔에 표시됩니다. 집계는 선택한 CSV에 해당하는 항목만 출력합니다.

| 출력 | 의미 |
| :--- | :--- |
| `입력 검사 통과`, `접속 대상` | 처리할 파일·테이블·행 수와 접속한 DB·계정 |
| `적재 전 행 수` | 적재 대상 테이블의 기존 행 수 (`--verify`에서는 생략) |
| `검증 통과`, `집계` | 모든 행·열과 참조 관계의 비교 결과 및 관련 수량·금액 합계 |
| `완료: 커밋 후 검증 통과.` | 저장 확정과 후속 확인 완료 |
| `완료: 검증 전용, DB 변경 없음.` | `--verify` 비교 완료 |
| `검사 실패`, `실행 실패`, `상태` | 실패 이유와 롤백·커밋 확정 여부 |

중간의 `검증 통과`는 적재 완료를 뜻하지 않습니다. 마지막 `완료` 메시지를 확인하세요.

## 주의사항

- 대상 테이블에 기존 데이터가 있으면 변경 없이 중단하며, 커밋 전 실패하면 이번 적재를 롤백합니다.
- 커밋 여부가 불명확하거나 커밋 후 검증이 실패하면 재적재 전에 `--verify`와 DB 조회로 확인하세요.

## 상품 임베딩 준비하기

임베딩 저장 구조를 처음 구성할 때는 기존 실습 DB 설정을 마친 뒤 PostgreSQL 관리자로 다음 SQL을 순서대로 실행합니다.

1. [벡터 확장 활성화](../sql/16_vector_extension.sql)
2. [상품 임베딩 테이블 생성](../sql/17_product_embeddings.sql)
3. [임베딩 쓰기 역할 생성](../sql/18_embedding_writer_role.sql)
4. [임베딩 권한 부여](../sql/19_embedding_privileges.sql)

`zava_embedding_writer`의 비밀번호를 설정하고, Git에서 제외된 `.env.embeddings`에 `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`를 설정합니다.

```powershell
uv sync --locked
uv run --locked --env-file .env.embeddings python -m scripts.prepare_product_embeddings
```

첫 실행에서는 고정된 모델 파일을 내려받습니다. 터미널에는 임베딩 진행률이 표시되며, 출력을 파일에 남길 때는 `2> embedding-preparation.log`를 붙이면 단계와 배치 완료 로그가 기록됩니다. 재실행하면 상품별 벡터를 갱신합니다. 모델이나 입력 규약을 변경하면 상품 전체를 다시 임베딩합니다.
