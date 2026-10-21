# 규정 확보 → 정규화 → 임베딩 → 검색

현재 조문 본문의 **원본 확보·정규화·청킹·임베딩·pgvector 적재와 상태 점검**까지 구현했다. 기준 인덱스는 bge-m3 / 1,024차원 / 1,200자 청크 202개다.

## 지금 DB 상태를 확인하는 명령

```sh
uv run python -m ingest.status
```

모델을 호출하거나 DB를 변경하지 않고, `RAG_INDEX_REPORT`가 가리키는 인덱스의 파일과 실제 DB를 대조한다. 성공 시 `status=ready`, `expected_chunks=202`, `stored_chunks=202`, `expected_dimensions=1024`, 오류 ID 목록은 모두 빈 배열이다. 불일치 또는 DB 접속 실패 시 종료 코드는 1이다.

```sh
# 다른 인덱스 점검
uv run python -m ingest.status --index-report data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-600-v1/index-report-bge-m3.json

# 결과 보관
uv run python -m ingest.status --output .local/troubleshooting/artifacts/vector-db-status.json
```

검사 순서: 파일 해시 → 보고서의 데이터/모델 설정과 예상 테이블명 → 예상 UUID 집합과 실제 DB ID → 본문 및 전체 JSON 메타데이터 → 벡터 존재와 차원. 파일과 DB 모두 202개라도 다른 내용이 들어 있으면 실패한다. 벡터의 수치를 모델로 다시 계산하거나 검색 적합성을 평가하는 검사는 아니다. 구현은 `ingest/status.py`에 있다.

## 같은 자료로 새 DB를 구축하는 순서

프로젝트의 `.env.example`을 참고해 Ollama bge-m3 설정과 DB 접속 정보를 준비한다. 기존 `.env`를 덮어쓰지 않는다.

```sh
uv sync
docker compose -f docker/compose.yml up -d --wait pgvector
ollama pull bge-m3

# 보관된 1,200자 청크를 적재. 빈 DB에는 테이블 생성, 재실행은 없는 행만 적재한다.
uv run python -m ingest.index --input data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-1200-v1

# 적재 보고서뿐 아니라 실제 DB의 완전성을 확인
uv run python -m ingest.status
```

`index-report-bge-m3.json`은 위 명령 실행 결과로 각 환경에서 만들어지는 보고서다. 파일을 복사하는 것만으로 해당 환경의 DB가 구축되지는 않는다. 다른 자료를 적재해도 기존 기본 인덱스가 자동 교체되지는 않으며, 사용하려는 보고서를 `RAG_INDEX_REPORT`로 지정한다. 원본부터 다시 만드는 과정은 아래 1~4단계에 있다. 기존 가공 폴더를 덮어쓰지 않으므로 재생성 시 새 출력 경로를 지정한다.

## 1단계: 원본 수집 (구현)

```sh
uv run python -m ingest.load
```

`LAW_OC`는 터미널 환경변수 또는 루트 `.env`에서 읽는다. 인증값은 출력·저장하지 않는다.

수집 대상:

1. 금융소비자 보호에 관한 법률
2. 금융소비자 보호에 관한 법률 시행령
3. 금융소비자 보호에 관한 감독규정

법률·시행령은 시행일 기준 검색(`target=eflaw`, `nw=3`)에서 이름이 정확히 일치하는 현행 후보 하나만 선택한다. 해당 일련번호(MST)와 시행일(efYd)로 전체 본문을 조회한다. 감독규정은 행정규칙 현행 검색(`target=admrul`, `nw=1`)의 일련번호로 조회한다. 이름이 유사한 다른 규정이나 여러 버전을 임의로 고르지 않는다.

각 실행은 `data/regulations/raw/<UTC시각>/`에 다음을 저장한다.

- `*.search.json`: 원본 검색 결과
- `consumer_protection_act.json`: 금소법 전체 응답
- `enforcement_decree.json`: 시행령 전체 응답
- `supervisory_regulation.json`: 감독규정 전체 응답
- `manifest.json`: 규정 ID·버전·시행일·조회 시각·출처·SHA-256·수집 상태

본문 저장은 인증값 마스킹 후 수행한다. manifest의 SHA-256은 저장 파일 기준이다. HTTP 오류, 비JSON 응답, 정확한 검색 결과 부재, 본문명·내용 불일치는 실패로 취급한다. 실패 manifest나 `partial` 실행을 검색 자료로 자동 선택하지 않는다.

`downloaded_unprocessed`는 원문 수신과 최소 구조 확인 상태다. **청킹·임베딩·검토 기준일 유효성 검증까지 완료했다는 뜻이 아니다.** `ready_for_embedding`은 아직 false다. 현재 수집은 현행 스냅샷이며 과거 이력·효력 종료일을 확보하지 않는다.

## 확보한 실제 자료

`data/regulations/raw/20261021T043743991211Z/`에서 세 원문을 확인했다.

- 금소법: 응답 조문단위 87개 중 `조문여부=조문` 73개. 나머지는 장·절 등 구조 항목이다.
- 시행령: 조문단위 53개.
- 감독규정: `AdmRulService` 아래 별도 기본정보와 `조문내용` 목록 36개. 법령 스키마와 다르다.
- 시행령·감독규정에는 별표가 있고 부칙 등 부속 자료도 있다. 다음 단계에서 본문·부칙·별표의 처리 범위와 출처 연결을 명시해야 한다.
- 기존 `external/law.py`를 감독규정에 그대로 적용하지 않는다. 전체 법령의 제목 항목도 실제 규정 조문으로 처리하지 않는다.

## 2단계: 전체 응답 정규화 (구현)

```sh
uv run python -m ingest.normalize --input data/regulations/raw/20261021T043743991211Z
```

출력은 `data/regulations/processed/20261021T043743991211Z-whole-article-v1/`에 저장한다. 기존 출력은 덮어쓰지 않으며 다시 실행하려면 `--output`으로 새 폴더를 지정한다.

원본 해시와 규정 식별자를 검증하고, 외부 Pydantic 모델을 거쳐 `RegulationChunk`로 변환한다. 금소법 73개, 시행령 53개, 감독규정 36개로 총 **162개 조문**이다. 금소법의 장·절 제목 14개는 별도 보존하고 해당 조문의 `hierarchy`에도 연결한다.

- 항 번호 없이 호만 있는 구조와 중첩 목록인 목 본문을 처리하며 각 원문 문자열을 보존한다.
- 감독규정은 별도 외부 모델로 읽고, 응답에 있는 조문 문자열 전체를 보존한다. 문단을 임의로 분리하지 않는다.
- 각 조문에는 규정 ID·버전·시행일·출처 URL과 원본 JSON 위치(`source_path`)가 연결된다.
- 부칙·별표·개정문·제개정이유·첨부 링크는 `supplementary`에 원본 JSON 구조로 보존한다. 첨부파일 다운로드와 부속 자료의 검색용 정규화는 아직 수행하지 않는다.
- 출력 manifest는 조문 수·구조 제목 수·부속 영역·파일 해시를 기록한다. 검색용 분할과 부속 자료 처리 전이므로 `ready_for_embedding`은 false다.

검증에는 수집한 실제 세 응답을 사용한다. 원문 문자열, 중첩 구조, 부속 자료, 출처 위치와 해시 변조 거부를 확인한다. 미확인 입력 형태를 사용하는 테스트는 합성 테스트로 표시한다.

## 3단계: 검색용 청킹 (구현)

```sh
uv run python -m ingest.chunk --input data/regulations/processed/20261021T043743991211Z-whole-article-v1
```

`ingest/chunk.py`는 LangChain `RecursiveCharacterTextSplitter`를 사용한다. 조문을 서로 합치지 않고 1,200자 이하로 나누며 줄바꿈 → 문장 구분 → 공백 → 문자 순으로 경계를 선택한다. 이는 항·호 번호를 해석하는 구조적 분할이 아닌 첫 검색 기준선이다. 크기는 `--chunk-size`로 바꿀 수 있다. 토큰 수가 아닌 본문 문자 수 기준이며, 임베딩 모델의 토큰 제한 확인은 인덱싱 단계에서 필요하다.

현재 overlap은 0이다. 모든 청크를 순서대로 이어 붙이면 부모 조문의 원문이 정확히 복원되는지 검사한다. 각 `SearchChunk`는 다음을 보존한다.

- `regulation`: 분할한 원문과 기존 규정 메타데이터. 항·호 번호를 임의 추정하지 않는다.
- `parent_chunk_id`, `start_char`, `end_char`: 부모 정규화 조문과 그 text의 문자 범위 `[start,end)`.
- `context`: 규정명·상위 장절·조문 제목. 원문과 분리해서 저장한다.
- `to_document()`: context와 원문을 묶은 LangChain Document. 실제 임베딩은 수행하지 않는다.

청크 ID에는 부모 ID·분할 설정·문자 범위를 반영한다. 출력은 새 `*-chunks-1200-v1/` 폴더의 문서별 JSONL과 manifest다. 입력 파일 해시를 검사하고 기존 출력을 덮어쓰지 않는다. 부칙·별표는 정규화 파일에 남으며 이번 검색 청크에는 들어가지 않는다. 효력 종료일 미확정 상태도 그대로 유지한다.

분할 구현은 [LangChain 공식 문서](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)를 따른다. 이 크기와 overlap이 최적이라는 의미는 아니며 이후 검색 성능을 비교해 조정한다.

## 4단계: 임베딩 및 pgvector 적재 (구현)

`app/ai/embeddings.py`는 적재와 향후 검색에서 공유할 임베딩 팩토리다. 기본값은 로컬 Ollama `bge-m3` / 1,024차원이다. OpenAI `text-embedding-3-small` / 1,536차원도 지원하며 채팅 모델 설정과 독립적으로 선택한다. 환경변수는 `.env.example`을 참고한다. 이번 전환에서는 `.env`의 임베딩 제공자·모델·주소 세 항목만 로컬 설정으로 변경했다.

```sh
uv sync
docker compose -f docker/compose.yml up -d --wait pgvector

# 파일·해시·중복 ID·입력 토큰만 검증. 최초 실행에는 토크나이저 사전 다운로드가 필요할 수 있다.
uv run python -m ingest.index --input data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-1200-v1 --dry-run

# Ollama가 실행되어 있어야 한다. bge-m3를 처음 사용할 때 다운로드한다.
ollama pull bge-m3
EMBEDDING_PROVIDER=ollama EMBEDDING_MODEL=bge-m3 EMBEDDING_BASE_URL=http://localhost:11434 \
uv run python -m ingest.index --input data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-1200-v1 --output data/regulations/processed/20261021T043743991211Z-whole-article-v1-chunks-1200-v1/index-report-bge-m3.json
```

로컬 DB는 `127.0.0.1:5433`, 개발 계정/DB는 `redpen`이다. 데이터는 도커 볼륨에 보존된다. 비밀번호를 바꾸려면 Compose 실행의 `REDPEN_DB_PASSWORD`와 애플리케이션의 `PGVECTOR_CONNECTION`을 함께 맞춘다. 이미 초기화한 볼륨의 계정 비밀번호는 환경변수만 바꿔도 자동 변경되지 않는다.

`ingest/index.py`의 흐름:

1. `load_documents()`: 청킹 manifest와 파일 SHA-256, 개수, ID, 문자 범위를 확인하고 LangChain Document로 읽는다.
2. `prepare_documents()`: OpenAI는 제목 문맥을 포함한 입력을 tiktoken으로 검사한다(현재 최대 1,405토큰). bge-m3에는 다른 모델의 토크나이저를 적용하지 않는다. Ollama 실행 시 `truncate=False`, `num_ctx=8192`로 길이 초과를 오류로 처리한다. 로컬 dry-run은 파일 검증만 하며 `max_input_tokens=null`이다. 데이터 해시와 임베딩 설정으로 전용 테이블명 및 안정적인 UUID를 만든다.
3. `open_store()`: 공식 `PGEngine` / `PGVectorStore`로 테이블을 생성하거나 기존 테이블을 연다. 기존 테이블 삭제는 하지 않는다.
4. `write_documents()`: 이미 같은 내용으로 저장된 청크는 임베딩을 생략하고, 없는 청크를 배치 적재한다. 저장한 모든 행의 내용·메타데이터를 다시 검증한다.

DB에는 문맥을 포함한 검색 텍스트, 임베딩 벡터와 JSONB 메타데이터가 저장된다. 메타데이터에는 원문 `regulation` 모델, 출처·문자 위치, 데이터 해시와 임베딩 설정을 포함하므로 향후 검색 결과를 `RegulationChunk`로 복원할 수 있다.

기본 결과 보고서는 입력 폴더의 `index-report-모델명.json`이다(bge-m3는 `index-report-bge-m3.json`, `--output`으로 변경 가능). `indexed` 상태만 적재 완료로 취급한다. 라이브러리가 행 단위로 commit하므로 오류 시 일부 행이 남을 수 있지만, 같은 명령을 다시 실행하면 저장된 행을 검증하고 누락분부터 이어간다. 다른 데이터/모델 설정은 다른 테이블을 사용하며, 검색 대상을 자동 변경하지 않는다. 재실행에서 `inserted=0`이면 규정 청크를 다시 임베딩하지 않은 것이다. 실제 차원 확인을 위한 짧은 임베딩 호출 1건은 수행한다. 모델 호출 없이 점검하려면 `ingest.status`를 사용한다.

OpenAI의 최초 202청크 적재 시도는 429 오류로 완료되지 않았고 기존 `index-report.json`에 실패 기록이 있다. 이후 **bge-m3로 202개 실제 청크 적재를 완료**했다. 보고서는 `index-report-bge-m3.json`, 테이블은 `regulations_93b564fdf7a4fff6157d8b1b`이다. 기존 실패 테이블과 합성 테스트 테이블은 그대로 둔다. 부칙·별표와 과거 효력 검증은 여전히 대상 밖이다.

OpenAI로 비교 실행하려면 `EMBEDDING_PROVIDER=openai EMBEDDING_MODEL=text-embedding-3-small EMBEDDING_BASE_URL=https://api.openai.com/v1`과 `OPENAI_API_KEY`를 사용한다. 설정 세 항목을 함께 지정한다. 검색에도 적재 보고서와 같은 임베딩 설정을 사용해야 한다.

로컬 구현 참고: [LangChain OllamaEmbeddings](https://docs.langchain.com/oss/python/integrations/embeddings/ollama), [Ollama embed의 truncate 옵션](https://docs.ollama.com/api/embed), [bge-m3 모델 정보](https://huggingface.co/BAAI/bge-m3). 현재 LangChain OllamaEmbeddings가 truncate 옵션을 노출하지 않아 얇은 하위 클래스에서 공식 클라이언트 호출에 `truncate=False`를 추가한다. 동기/비동기 경로 모두 동일하다.

선택 통합 테스트(전용 `test_regulation_ingest_v1` 테이블, 합성 임베딩):

```sh
REDPEN_PGVECTOR_INTEGRATION=1 uv run python -m pytest tests/ingest/test_pgvector_integration.py -q
```

공식 구현 참고: [OpenAIEmbeddings](https://docs.langchain.com/oss/python/integrations/embeddings/openai), [langchain-postgres](https://github.com/langchain-ai/langchain-postgres). 기존 `PGVector`가 deprecated되어 새 `PGVectorStore`를 사용한다. 현재 202개 자료는 기본 정확 검색을 사용하며, HNSW 근사 검색 인덱스는 추가하지 않았다. 검색 provider는 연결되어 있다.

## 검색 연결과 이후 범위

5. `app/kb/search.py`: 동일 provider 계약의 RAG 구현을 연결했다. 설정과 제약은 `app/kb/README.md` 참고.
6. 합성 질문10개로 600/1,200자 청킹 × dense/MMR의 Recall@K 비교를 실행했다. 명령과 결과는 `evaluation/retrieval/README.md`, `evaluation/retrieval/RESULTS.md` 참고. 전문가 검수 및 독립 평가셋은 다음 과제다.

DB 구축 완료 범위는 법률73조문·시행령53조문·감독규정36조문의 본문이다. 부칙·별표·첨부자료는 원본/정규화 파일에 보존됐지만 벡터 DB에는 넣지 않았다. 효력 종료일 및 과거 이력도 미확정이다. 따라서 모든 금융광고 규정과 모든 기준일을 포괄하는 DB로 간주하지 않는다.

공식 문서:

- [시행일 기준 법령 검색](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdListGuide)
- [시행일 기준 법령 본문](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdInfoGuide)
- [행정규칙 검색](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=admrulListGuide)
- [행정규칙 본문](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=admrulInfoGuide)
