# 원천 API 응답 확인

인증값은 `LAW_OC`(국가법령정보 공동활용 인증값), `FSS_API_KEY`(금융상품 한눈에 인증키)를 사용합니다. 터미널 환경변수가 루트 `.env`보다 우선합니다. 키는 출력하지 않습니다.

```sh
uv run python -m scripts.probes.law_api
# 검색 응답에서 실제 법령ID를 확인한 뒤 실행
uv run python -m scripts.probes.law_api --law-id 실제법령ID --article 002200
uv run python -m scripts.probes.disclosure_api
uv run python -m scripts.probes.disclosure_api --product saving
```

각 호출은 원본 응답(인증값이 포함되면 마스킹)과 조회 시각·인증값을 제외한 요청 조건·HTTP 상태를 별도 파일로 저장합니다. HTTP 200도 업무 오류일 수 있으므로 종료 메시지를 함께 확인합니다. 비JSON 오류 응답도 저장합니다. 목록은 기본적으로 첫 페이지만 조회합니다.

이 코드는 응답 탐색용이며 MCP·AI 비즈니스 로직과 독립적입니다. 아직 정상 응답을 수신했다고 가정하지 않으며, 실제 실행 결과로 필드를 확인합니다.

공식 문서:
- [법령 검색](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwListGuide)
- [법령 조항호목 조회](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwJoListGuide)
- [금융상품 한눈에 예금 API](https://finlife.fss.or.kr/finlife/api/fdrmDpstApi/list.do?menuNo=700052)
