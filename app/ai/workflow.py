"""Supervisor가 작업 상태를 읽고 워커를 선택하는 LangGraph."""

from dataclasses import dataclass

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.ai.state import ReviewInput, ReviewOutput, ReviewState
from app.ai.errors import StageOutputError
from app.ai.stages.extract import extract_claims
from app.ai.stages.factcheck import compare_rate
from app.ai.stages.judge import judge_ad
from app.ai.stages.prepare_tasks import prepare_tasks_node
from app.ai.supervisor import MAX_DISPATCHES, finish_task, supervisor_node
from app.kb.provider import RegulationProvider, UnsupportedRegulationDateError
from app.schemas.run import ReviewDraft

# 예상 가능한 외부/출력 오류만 작업 상태로 바꾼다. 프로그래밍 오류는 전파한다.
EXPECTED_ERRORS = (TimeoutError, ConnectionError, httpx.TransportError,
                   UnsupportedRegulationDateError, StageOutputError, ValidationError, OutputParserException)
TRANSIENT_ERRORS = (TimeoutError, ConnectionError, httpx.TransportError)


@dataclass(frozen=True)
class ReviewContext:
    provider: RegulationProvider
    extract_model: BaseChatModel | None = None
    judge_model: BaseChatModel | None = None


def failure(state, error) -> dict:
    # 원본 예외 메시지에는 URL/키가 있을 수 있어 저장하지 않는다.
    reason = error.public_reason if isinstance(error, StageOutputError) else '단계 실행 실패'
    return finish_task(state,status='failed',reason=reason,
                       diagnostic_id=getattr(error,'diagnostic_id',None),
                       error_code=type(error).__name__,retryable=isinstance(error,TRANSIENT_ERRORS))


async def extract_node(state: ReviewState, runtime: Runtime[ReviewContext]) -> dict:
    try:
        extraction = await extract_claims(state['ad_text'],model=runtime.context.extract_model)
        return {**finish_task(state),'extraction':extraction}
    except EXPECTED_ERRORS as error:
        return failure(state,error)


async def retrieve_node(state: ReviewState, runtime: Runtime[ReviewContext]) -> dict:
    try:
        regulations = await runtime.context.provider.provide(
            state['extraction'].claims,as_of_date=state['as_of_date'])
        return {**finish_task(state),'regulations':regulations}
    except EXPECTED_ERRORS as error:
        return failure(state,error)


def factcheck_node(state: ReviewState) -> dict:
    task = next(t for t in state['tasks'] if t.task_id == state['active_task_id'])
    claim = next(c for c in state['extraction'].claims if c.id == task.target_id)
    comparison = compare_rate(claim,state['product'],as_of_date=state['as_of_date'])
    return {**finish_task(state),'comparisons_by_claim':{
        **state.get('comparisons_by_claim',{}),claim.id:comparison,
    }}


async def judge_node(state: ReviewState, runtime: Runtime[ReviewContext]) -> dict:
    try:
        judgment = await judge_ad(
            state['ad_text'],state['extraction'],state['regulations'],
            list(state.get('comparisons_by_claim',{}).values()),
            product=state['product'],model=runtime.context.judge_model)
        return {**finish_task(state),'judgment':judgment}
    except EXPECTED_ERRORS as error:
        return failure(state,error)


def finalize_node(state: ReviewState) -> dict:
    tasks=state['tasks']
    failed=any(t.status in {'failed','blocked'} for t in tasks)
    status='failed' if 'judgment' not in state else ('partial' if failed else 'completed')
    return {'draft': ReviewDraft(
        extraction=state.get('extraction'),regulations=state.get('regulations',[]),
        comparisons=list(state.get('comparisons_by_claim',{}).values()),
        judgment=state.get('judgment'),verification_status='not_performed',
        run_status=status,tasks=tasks,events=state.get('events',[]),
    )}


def next_node(state: ReviewState) -> str:
    return state['next_node']


def build_review_graph() -> CompiledStateGraph:
    builder=StateGraph(ReviewState,context_schema=ReviewContext,
                       input_schema=ReviewInput,output_schema=ReviewOutput)
    builder.add_node('supervisor',supervisor_node)
    builder.add_node('prepare_tasks',prepare_tasks_node)
    for name,node in [('extract',extract_node),('retrieve',retrieve_node),
                      ('factcheck',factcheck_node),('judge',judge_node)]:
        builder.add_node(name,node)
        builder.add_edge(name,'supervisor')
    builder.add_node('finalize',finalize_node)
    builder.add_edge(START,'supervisor')
    builder.add_edge('prepare_tasks','supervisor')
    routes={name:name for name in ['extract','prepare_tasks','retrieve','factcheck','judge','finalize']}
    builder.add_conditional_edges('supervisor',next_node,routes)
    builder.add_edge('finalize',END)
    # supervisor 왕복을 포함한다. 업무 예산은 별도로 dispatch 수로 제한한다.
    return builder.compile().with_config({'recursion_limit':MAX_DISPATCHES*2+10})
