# RedPen — 유스케이스별 시퀀스 다이어그램 (2일 MVP)

> 기준 문서: 개발 준비 계획, 유저 플로우, ADR-001~012
> 표기: 실선(`->>`)은 호출, 점선(`-->>`)은 응답, 열린 화살표(`--)`)는 SSE 이벤트처럼 비동기로 흘려보내는 메시지입니다.

## 공통 참여자

| 약어 | 참여자 | 비고 |
| --- | --- | --- |
| U | 심의 담당자 | 유일한 사용자 |
| V | Vue SPA | Vue 3 + Vite 단일 페이지 |
| API | FastAPI 라우터 | `/api/*` REST + SSE |
| G | 오케스트레이터 | 상태 그래프, 에이전트 4개 실행 |
| L | LLM 게이트웨이 | 개발은 Ollama, 평가·데모는 OpenAI |
| KB | 로컬 규정 모듈 | `search_articles`, `get_checklist` (BM25 + pgvector) |
| ML | korean-law MCP | stdio 자식 프로세스 |
| MF | fin-disclosure MCP | stdio 자식 프로세스 |
| DB | PostgreSQL + pgvector | 규정 인덱스, 실행 증적, 이벤트 |
| LAW | 법제처 Open API | 외부 |
| FSS | 금감원 공시 API | 외부 |
| EMB | OpenAI 임베딩 | text-embedding-3-small 고정 |

---

## 1. 앱 기동과 종료

FastAPI가 `lifespan`에서 MCP 서버 2개를 자식 프로세스로 한 번만 띄우고, 종료할 때까지 세션을 유지합니다 (ADR-002).

```mermaid
sequenceDiagram
    participant OPS as 개발자
    participant API as FastAPI (main.py)
    participant ML as korean-law MCP (자식 프로세스)
    participant MF as fin-disclosure MCP (자식 프로세스)
    participant DB as PostgreSQL + pgvector

    OPS->>API: uvicorn 실행
    API->>API: lifespan 시작
    API->>ML: stdio로 자식 프로세스 기동
    API->>ML: initialize (JSON-RPC)
    ML-->>API: 도구 목록 (law_get_article)
    API->>MF: stdio로 자식 프로세스 기동
    API->>MF: initialize (JSON-RPC)
    MF-->>API: 도구 목록 (disclosure_get_product_rates, disclosure_search_products)
    API->>DB: 연결 풀 생성, 규정 인덱스 조회
    DB-->>API: 청크 수, 사용한 임베딩 모델명
    API->>API: 임베딩 모델명이 설정과 같은지 확인 (다르면 기동 중단)
    API->>API: 메모리 BM25 인덱스 구성
    Note over API,MF: MCP 세션은 앱이 끝날 때까지 유지. 요청마다 새로 띄우지 않음
    OPS->>API: 종료 신호
    API->>ML: 세션 종료, 프로세스 정리
    API->>MF: 세션 종료, 프로세스 정리
```

---

## 2. 규정 적재 (ingest)

앱과 분리된 스크립트입니다. 조문을 조·항·호 단위로 잘라 시행일을 붙이고, OpenAI 임베딩으로 인덱스를 만듭니다 (ADR-011).

```mermaid
sequenceDiagram
    participant OPS as 개발자
    participant ING as ingest 스크립트
    participant LAW as 법제처 Open API
    participant FSS as 금감원 공시 API
    participant EMB as OpenAI 임베딩
    participant DB as PostgreSQL + pgvector

    OPS->>ING: 적재 실행
    loop 대상 법령 (금소법, 시행령, 감독규정)
        ING->>LAW: 법령 본문 조회 (OC 키)
        LAW-->>ING: 조문 원문
        ING->>ING: 조·항·호 파싱, 시행일 태깅, 상위 조문 문맥 결합
    end
    ING->>ING: 가이드라인 Q&A 수동 분할본 읽기
    ING->>EMB: 청크 묶음 임베딩 요청
    EMB-->>ING: 1536차원 벡터
    ING->>DB: regulation_chunk 저장 (chunk_id, 시행일, 임베딩 모델명)
    Note over ING,DB: 개정 조문은 새 chunk_id로 추가하고 이전 버전은 남김
    opt 골든셋용 공시 스냅샷
        ING->>FSS: 골든셋 상품 금리 조회
        FSS-->>ING: 기간별 금리, 공시 기준월
        ING->>ING: 스냅샷 파일로 고정 저장
    end
    ING-->>OPS: 적재 결과 (법령별 청크 수)
```

---

## 3. 공시 상품 검색과 선택

담당자가 광고 대상 상품을 고릅니다. 평가 중에는 스냅샷 모드로 동작해 결과가 바뀌지 않게 합니다.

```mermaid
sequenceDiagram
    participant U as 심의 담당자
    participant V as Vue SPA
    participant API as FastAPI
    participant MF as fin-disclosure MCP
    participant FSS as 금감원 공시 API

    U->>V: 은행명, 상품명 입력
    V->>API: GET /api/products?bank=&q=
    API->>MF: disclosure_search_products(bank, q)
    alt DISCLOSURE_MODE = snapshot
        MF->>MF: 스냅샷 파일에서 검색
    else DISCLOSURE_MODE = live
        alt 캐시 적중
            MF->>MF: TTL 캐시에서 반환
        else 캐시 없음
            MF->>FSS: 상품 목록 조회
            FSS-->>MF: 상품 목록, 기간별 금리
            MF->>MF: TTL 캐시에 저장
        end
    end
    MF-->>API: 후보 상품 (금융사 코드, 상품 코드, 기본·최고 금리)
    API-->>V: 후보 목록
    V-->>U: 목록과 금리 미리보기
    U->>V: 상품 선택 (또는 건너뛰기)
```

---

## 4. 광고 검토 실행 (핵심 흐름)

실행과 구독을 나눕니다. `POST`는 백그라운드 실행만 시작하고, 진행 상황은 SSE로 흘려보냅니다 (ADR-005, 006).

```mermaid
sequenceDiagram
    participant U as 심의 담당자
    participant V as Vue SPA
    participant API as FastAPI
    participant G as 오케스트레이터
    participant L as LLM 게이트웨이
    participant KB as 로컬 규정 모듈
    participant MF as fin-disclosure MCP
    participant ML as korean-law MCP
    participant DB as PostgreSQL

    U->>V: 문안 입력 후 검토 시작
    V->>API: POST /api/runs {ad_text, product}
    API->>DB: review_run 생성
    API->>G: 백그라운드 실행 시작
    API-->>V: 202 {run_id}
    V->>API: GET /api/runs/{run_id}/events (SSE 구독)
    Note over G,V: 이벤트는 run별 큐와 run_event 테이블을 거쳐 전송

    G--)V: stage: extract 시작
    G->>L: 추출 요청 (Claim 스키마)
    L-->>G: 클레임 목록, 광고 해당 여부
    G->>G: 스키마 검증, locate_span으로 위치 계산

    par 공시 대조
        G->>MF: disclosure_get_product_rates
        MF-->>G: 기간별 금리, 공시 기준월
        G->>G: compare_rates로 숫자 비교
    and 규정 검색 (클레임별)
        loop 최대 3회
            G->>L: 질의 생성 또는 재작성
            L-->>G: 검색 질의
            G->>KB: search_articles(query, as_of_date)
            KB-->>G: 후보 청크 (BM25 + 벡터)
        end
        G->>KB: get_checklist(deposit)
        KB-->>G: 필수 기재사항 목록
    end
    G--)V: stage: retrieve, factcheck 완료

    par 판정 워커 (문구 x 위반 유형)
        G->>L: 판정 요청 (article_id는 후보 ID enum)
        L-->>G: Verdict
    end

    loop 판정마다
        G->>ML: law_get_article(..., as_of_date)
        ML-->>G: 현행 원문, 조회 시각
        G->>L: 근거 적합성 평가
        L-->>G: 통과 또는 실패
        G--)V: verdict 이벤트
    end

    G->>DB: 상태 객체 전체를 증적으로 저장
    G--)V: done 이벤트 (요약)
    V->>API: GET /api/runs/{run_id}
    API-->>V: 최종 리포트
    V-->>U: 문구 하이라이트와 판정 카드
```

---

## 5. 인용 검증 실패와 강등

조문은 실재하고 문언도 맞지만 판정을 뒷받침하지 않는 경우(misgrounded)입니다. 1회 되돌린 뒤에도 실패하면 숨기지 않고 "사람 확인 필요"로 넘깁니다.

```mermaid
sequenceDiagram
    participant G as 오케스트레이터
    participant L as LLM 게이트웨이
    participant KB as 로컬 규정 모듈
    participant ML as korean-law MCP
    participant V as Vue SPA

    G->>ML: law_get_article(인용 조문, as_of_date)
    ML-->>G: 현행 원문
    G->>G: 실재, 문언 일치 확인 (통과)
    G->>L: 근거 적합성 평가
    L-->>G: 실패 + 피드백 (예: 예금성 상품에 맞지 않음)

    G->>L: 피드백을 반영해 질의 재작성
    L-->>G: 새 질의
    G->>KB: search_articles(새 질의, as_of_date)
    KB-->>G: 새 후보 청크
    G->>L: 재판정 (새 후보 ID enum)
    L-->>G: 새 Verdict
    G->>ML: law_get_article(새 인용 조문)
    ML-->>G: 현행 원문
    G->>L: 근거 적합성 재평가

    alt 통과
        L-->>G: 통과
        G--)V: verdict (verified)
    else 재실패
        L-->>G: 실패
        G->>G: 사람 확인 필요로 강등, 수정안 제거, 실패 이유 기록
        G--)V: verdict (needs_review)
    end
```

---

## 6. 외부 API 장애와 부분 결과

한 단계가 실패해도 이미 받은 판정은 유지하고, 실패한 단계만 표시합니다. 에러는 예외가 아니라 도구 결과로 돌아옵니다.

```mermaid
sequenceDiagram
    participant G as 오케스트레이터
    participant MGR as MCP 클라이언트 관리자
    participant MF as fin-disclosure MCP
    participant FSS as 금감원 공시 API
    participant V as Vue SPA

    G->>MGR: disclosure_get_product_rates 호출 (제한 10초)
    MGR->>MF: tools/call
    alt 원천 API 시간 초과
        MF->>FSS: 금리 조회
        FSS--xMF: 응답 없음
        MF-->>MGR: 도구 결과 (에러: UPSTREAM_TIMEOUT)
        MGR-->>G: 에러 결과
    else 자식 프로세스 종료됨
        MGR-xMF: 전송 실패
        MGR->>MF: 프로세스 재기동, 세션 재연결
        MGR->>MF: tools/call 1회 재시도
        MF-->>MGR: 결과 또는 에러
        MGR-->>G: 결과 또는 에러
    end
    G--)V: error 이벤트 (stage: factcheck)
    G->>G: 금리 판정은 건너뛰고 표현·필수사항 판정 계속
    G--)V: 나머지 verdict 이벤트
    G--)V: done 이벤트
    V->>V: 화면 상태를 partial로 표시
```

---

## 7. SSE 재연결과 새로고침 복구

이벤트마다 `id`를 붙이고 DB에도 저장하므로, 끊겼다 붙어도 놓친 이벤트부터 다시 받습니다.

```mermaid
sequenceDiagram
    participant U as 심의 담당자
    participant V as Vue SPA
    participant API as FastAPI
    participant DB as PostgreSQL

    Note over V,API: 15초마다 하트비트 주석 줄로 연결 유지
    U->>V: 검토 중 새로고침
    V->>V: sessionStorage에서 run_id 읽기
    V->>API: GET /api/runs/{run_id}/events (Last-Event-ID: 7)
    API->>DB: run_event에서 id 7 이후 조회
    DB-->>API: 놓친 이벤트 목록
    API--)V: 놓친 이벤트 재전송
    alt 검토가 아직 진행 중
        API->>API: run별 큐 구독
        API--)V: 이후 이벤트 실시간 전송
    else 이미 완료
        API--)V: done 이벤트
    end
    V-->>U: 받은 판정 카드 복원
```

---

## 8. 판정 동의·기각 (시간 남으면)

담당자의 기각 사유는 오탐 데이터가 되어 골든셋 후보로 쌓입니다.

```mermaid
sequenceDiagram
    participant U as 심의 담당자
    participant V as Vue SPA
    participant API as FastAPI
    participant DB as PostgreSQL

    U->>V: 판정 카드에서 기각 선택, 사유 입력
    V->>API: POST /api/runs/{run_id}/verdicts/{claim_id}/feedback {decision, reason}
    API->>DB: reviewer_feedback 저장
    API-->>V: 204
    V-->>U: 카드에 처리 상태 표시
    Note over DB: 기각 사례는 골든셋 후보로 내보내 다음 평가에 반영
```

---

## 9. 골든셋 평가 실행

평가는 HTTP를 거치지 않고 그래프를 직접 실행합니다. 공급자는 OpenAI, 공시는 스냅샷으로 고정합니다 (ADR-010).

```mermaid
sequenceDiagram
    participant OPS as 개발자
    participant EV as 평가 스크립트
    participant G as 오케스트레이터
    participant ML as korean-law MCP
    participant MF as fin-disclosure MCP (snapshot)
    participant LS as LangSmith

    OPS->>EV: 평가 실행 (구성: rag_verify, 분할: dev)
    EV->>EV: LLM_PROVIDER=openai, DISCLOSURE_MODE=snapshot 설정
    EV->>ML: 자식 프로세스 기동
    EV->>MF: 자식 프로세스 기동
    loop 골든셋 건별
        EV->>G: 그래프 직접 실행 (광고 문안, 상품)
        G->>G: 추출, 검색, 대조, 판정, 검증 (4번과 같음)
        G->>LS: 트레이스 전송 (구성 이름, 프롬프트 버전 태그)
        G-->>EV: 상태 객체
        EV->>EV: 정답 라벨과 비교 (문구 위치, 위반 유형, 정답 조문)
    end
    EV->>EV: 지표 집계 (재현율, 근거 정확도, 환각 인용 수, p95 지연)
    EV-->>OPS: 지표 표
    Note over OPS,EV: ablation 3개 구성을 dev로 비교한 뒤, test는 마지막에 1회만 실행
```
