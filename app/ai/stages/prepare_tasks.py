"""LLM 계획 없이 추출 결과에 따라 허용된 종류의 작업만 생성한다."""

from app.ai.stages.factcheck import compare_rate
from app.schemas.task import ReviewTask, TaskEvent


def prepare_tasks_node(state) -> dict:
    if state.get('tasks_prepared', False):
        return {}
    tasks=[task.model_copy(deep=True) for task in state['tasks']]
    events=list(state.get('events',[]))
    tasks.append(ReviewTask(task_id='retrieve',kind='retrieve',depends_on=['extract'],max_attempts=2))
    comparison_map={}
    for claim in state['extraction'].claims:
        if claim.kind != 'interest_rate':
            continue
        task=ReviewTask(task_id=f'factcheck:{claim.id}',kind='factcheck',target_id=claim.id,
                        target_kind='claim',depends_on=['extract'])
        if state['product'] is None:
            task.status='skipped';task.feedback='상품 미선택'
            comparison_map[claim.id]=compare_rate(claim,None,as_of_date=state['as_of_date'])
            events.append(TaskEvent(task_id=task.task_id,status='skipped',attempt=0,reason=task.feedback))
        tasks.append(task)
    # 대상별 judge 분리는 후속 단계. 현재는 광고 단위 판정을 한 작업으로 감싼다.
    tasks.append(ReviewTask(task_id='judge',kind='judge',depends_on=[t.task_id for t in tasks]))
    return {'tasks':tasks,'events':events,'tasks_prepared':True,'comparisons_by_claim':comparison_map}
