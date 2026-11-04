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
