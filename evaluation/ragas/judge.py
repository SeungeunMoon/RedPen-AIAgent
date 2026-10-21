"""RAGAS 공개 LLM 인터페이스를 LangChain 구조화 출력에 연결하는 Adapter."""

from langchain_openai import ChatOpenAI
from ragas.llms.base import InstructorBaseRagasLLM

from evaluation.ragas.config import EvaluatorSettings


class LangChainRagasJudge(InstructorBaseRagasLLM):
    def __init__(self, model):
        self.model = model
        self.calls = []

    def _parse(self, output, response_model):
        usage = None
        if isinstance(output,dict) and 'parsed' in output:
            usage = getattr(output.get('raw'),'usage_metadata',None)
            if output.get('parsing_error') is not None:
                raise output['parsing_error']
            output = output['parsed']
        result = response_model.model_validate(output)
        self.calls.append({'response_schema':response_model.__name__,
                           'output':result.model_dump(mode='json'),'usage':usage})
        return result

    def _chain(self, response_model):
        return self.model.with_structured_output(response_model,method='json_schema',include_raw=True).with_config(
            {'run_name':'ragas_openai_judge','tags':['evaluation','ragas']})

    def generate(self, prompt, response_model):
        return self._parse(self._chain(response_model).invoke(prompt),response_model)

    async def agenerate(self, prompt, response_model):
        return self._parse(await self._chain(response_model).ainvoke(prompt),response_model)


def create_judge(settings: EvaluatorSettings):
    if settings.api_key is None:
        raise ValueError('RAGAS_OPENAI_API_KEY 또는 OPENAI_API_KEY가 필요합니다')
    return LangChainRagasJudge(ChatOpenAI(
        model=settings.model,api_key=settings.api_key,base_url=settings.base_url,
        temperature=0,timeout=settings.timeout_seconds,max_retries=settings.max_retries,
    ))
