"""저장된 RAGAS 결과를 재채점 없이 LangSmith 실험에 등록한다."""

import hashlib
import json

from langsmith import Client
from langsmith.evaluation import evaluate


def feedback(run, example):
    results = []
    for name, metric in run.outputs['metrics'].items():
        scored = metric['status'] == 'scored'
        results.append({'key':f'{name}_scored','score':int(scored)})
        if scored:
            results.append({'key':name,'score':metric['value']})
        else:
            results.append({'key':f'{name}_status','value':metric['status'],
                            'comment':json.dumps(metric,ensure_ascii=False)})
    return {'results':results}


def upload_result(payload, experiment_name, *, client=None, evaluate_fn=evaluate):
    if payload.get('status') not in {'scored','incomplete'}:
        raise ValueError('채점된 결과 파일이 필요합니다')
    # 검색 설정과 무관하게 질문·참고답안·선택한 질문 집합으로 데이터셋을 고정한다.
    examples = sorted(({
        'inputs':{'case_id':s['case_id'],'user_input':s['user_input']},
        'outputs':{'reference':s['reference'],'reference_contexts':s['reference_contexts']},
    } for s in payload['samples']),key=lambda item:item['inputs']['case_id'])
    fingerprint = hashlib.sha256(json.dumps(examples,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    dataset_name = f'redpen-regulation-ragas-{fingerprint[:16]}'
    client = client or Client()
    if client.has_dataset(dataset_name=dataset_name):
        dataset = client.read_dataset(dataset_name=dataset_name)
    else:
        dataset = client.create_dataset(dataset_name=dataset_name,
            description='규정 검색 평가. 질문/참고답안/선택한 질문 집합이 바뀌면 별도 데이터셋.')
    existing = {e.inputs['case_id']:e for e in client.list_examples(dataset_id=dataset.id)}
    for item in examples:
        case_id = item['inputs']['case_id']
        if case_id not in existing:
            existing[case_id] = client.create_example(**item,dataset_id=dataset.id)
        elif existing[case_id].inputs != item['inputs'] or existing[case_id].outputs != item['outputs']:
            raise ValueError('LangSmith 데이터셋 내용이 로컬 평가 입력과 다릅니다')
    records = {r['case_id']:r for r in payload['records']}
    samples = {s['case_id']:s for s in payload['samples']}

    def target(inputs):
        case_id = inputs['case_id']
        sample = samples[case_id]
        return {'retrieved_contexts':sample['retrieved_contexts'],
                'retrieved_ids':sample['retrieved_ids'],'metrics':records[case_id]['metrics']}

    result = evaluate_fn(target,data=[existing[e['inputs']['case_id']] for e in examples],
        evaluators=[feedback],client=client,experiment_prefix=experiment_name,
        metadata={'retrieval':payload.get('retrieval'),'judge':payload.get('judge'),
                  'ragas_version':payload.get('ragas_version'),'evaluation_input_sha256':fingerprint,
                  'result_status':payload['status'],'summary':payload['summary'],
                  'original_created_at':payload.get('created_at')},
        max_concurrency=1,blocking=True)
    project = client.read_project(project_name=result.experiment_name)
    return {'status':'uploaded','dataset_name':dataset_name,
            'experiment_name':result.experiment_name,'url':project.url}
