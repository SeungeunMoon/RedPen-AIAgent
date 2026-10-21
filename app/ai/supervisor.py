"""공유 작업 상태만 보고 다음 작업을 선택하는 결정적 supervisor. LLM 호출 없음."""

from app.schemas.task import ReviewTask, TaskEvent

TERMINAL = {'succeeded', 'skipped', 'failed', 'blocked'}
SATISFIED = {'succeeded', 'skipped'}
MAX_DISPATCHES = 100


def supervisor_node(state) -> dict:
    tasks = [task.model_copy(deep=True) for task in state.get('tasks', [])]
    events = list(state.get('events', []))
    if not tasks:
        tasks = [ReviewTask(task_id='extract', kind='extract')]
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError('작업 ID 중복')
    for task in tasks:
        if any(dep not in by_id for dep in task.depends_on):
            raise ValueError('알 수 없는 선행 작업 ID')
    if state.get('dispatch_count', 0) >= MAX_DISPATCHES:
        for task in tasks:
            if task.status not in TERMINAL:
                task.status='blocked'; task.feedback='실행 예산 소진'
                events.append(TaskEvent(task_id=task.task_id,status='blocked',attempt=task.attempts,reason=task.feedback))
        return {'tasks':tasks,'events':events,'next_node':'finalize','active_task_id':None}
    # 복구 가능한 전송 오류만 제한적으로 재실행한다. 성공 작업은 건드리지 않는다.
    for task in tasks:
        if task.status == 'failed' and task.retryable and task.attempts < task.max_attempts:
            task.status='pending'
    if by_id['extract'].status == 'succeeded' and not state.get('tasks_prepared', False):
        return {'tasks':tasks,'events':events,'next_node':'prepare_tasks','active_task_id':None}
    # 실패한 의존성은 후속 작업으로 전파한다. 고정점까지 반복하여 교착을 방지한다.
    changed=True
    while changed:
        changed=False
        for task in tasks:
            if task.status == 'pending' and any(by_id[dep].status in {'failed','blocked'} for dep in task.depends_on):
                task.status='blocked'; task.feedback='선행 작업 실패'
                events.append(TaskEvent(task_id=task.task_id,status='blocked',attempt=task.attempts,reason=task.feedback))
                changed=True
    for task in tasks:
        if task.status == 'pending' and all(by_id[dep].status in SATISFIED for dep in task.depends_on):
            task.status='running'; task.attempts+=1
            task.error_code=None; task.retryable=False
            events.append(TaskEvent(task_id=task.task_id,status='running',attempt=task.attempts))
            return {'tasks':tasks,'events':events,'next_node':task.kind,'active_task_id':task.task_id,
                    'dispatch_count':state.get('dispatch_count',0)+1}
    for task in tasks:
        if task.status not in TERMINAL:
            task.status='blocked'; task.feedback='실행 가능한 작업이 없는 의존성 막힘'
            events.append(TaskEvent(task_id=task.task_id,status='blocked',attempt=task.attempts,reason=task.feedback))
    return {'tasks':tasks,'events':events,'next_node':'finalize','active_task_id':None}


def finish_task(state, *, status='succeeded', reason=None, error_code=None, retryable=False, diagnostic_id=None) -> dict:
    tasks=[task.model_copy(deep=True) for task in state['tasks']]
    task=next(task for task in tasks if task.task_id == state['active_task_id'])
    task.status=status; task.feedback=reason; task.error_code=error_code; task.retryable=retryable
    task.diagnostic_id=diagnostic_id
    event=TaskEvent(task_id=task.task_id,status=status,attempt=task.attempts,reason=reason,diagnostic_id=diagnostic_id)
    return {'tasks':tasks,'events':[*state.get('events',[]),event]}
