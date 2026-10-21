# RedPen-AIAgent

## AI 모델 설정

Python 3.11 이상과 uv를 사용합니다.

```sh
uv sync
cp .env.example .env
```

프로젝트 루트의 `.env`에서 설정합니다. 실제 환경변수가 `.env`보다 우선합니다.

- `LLM_PROVIDER`: `ollama` 또는 `openai`
- `LLM_MODEL`: 기본 모델명. Ollama는 로컬에 내려받은 모델 태그를 지정합니다.
- `LLM_BASE_URL`: 비우면 공급자의 기본 주소를 사용합니다. Ollama는 `http://localhost:11434`이며 `/v1`을 붙이지 않습니다. 공급자를 바꿀 때 기존 주소도 지우거나 변경합니다.
- `OPENAI_API_KEY`: OpenAI 선택 시 필수입니다.
- `LLM_EXTRACT_MODEL`, `LLM_RETRIEVE_MODEL`, `LLM_JUDGE_MODEL`, `LLM_VERIFY_MODEL`: 해당 단계만 다른 모델명을 사용합니다. 비우면 기본 모델로 동작합니다. 공급자는 공통입니다.
- `LLM_TEMPERATURE`: 기본은 미지정입니다. 모델이 지원할 때만 설정합니다.
- `LLM_TIMEOUT_SECONDS`: 요청 제한 시간. `LLM_MAX_RETRIES`는 현재 OpenAI 전송 재시도에 적용하며 Ollama 재시도는 후속 워크플로에서 구현합니다.

OpenAI 전환 예시(두 항목 외 API 키도 입력):

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=사용할_OpenAI_모델명
LLM_BASE_URL=
```

LangChain 모델 사용 예시:

```python
from app.ai.llm import get_chat_model

model = get_chat_model("extract")
result = model.invoke("안녕하세요")
print(result.content)
# 비동기 환경에서는 await model.ainvoke(...)
```

모델 생성만으로는 요청하지 않습니다. `invoke` 실행 시 로컬 Ollama 서버 또는 OpenAI API로 요청합니다. 모델·서버 설치와 실제 연결은 별도로 준비해야 합니다.

설정은 프로세스에서 캐시하므로 `.env` 변경 후 재시작합니다. 임베딩 설정은 LLM 설정과 독립이며 `text-embedding-3-small`로 고정합니다. 임베딩 호출과 구조화 출력·검증 체인은 아직 구현하지 않았습니다.

네트워크 호출 없는 설정 테스트:

```sh
uv run pytest
```

LangChain의 [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)와 [ChatOllama](https://docs.langchain.com/oss/python/integrations/chat/ollama) 통합을 사용합니다.
