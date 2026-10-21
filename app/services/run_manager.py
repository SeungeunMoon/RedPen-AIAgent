"""단일 프로세스 데모용 실행·SSE 이력. 재시작하면 데이터가 사라진다."""

import asyncio
import json
from dataclasses import dataclass, field
from uuid import uuid4

from app.services.review_service import review_ad


@dataclass
class RunRecord:
    run_id: str
    events: list[dict] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = 'running'
    result: object | None = None
    task: asyncio.Task | None = None

    def emit(self, kind, data):
        self.events.append({'id':len(self.events)+1,'event':kind,'data':data})
        self.changed.set()


class RunManager:
    def __init__(self, provider, products, *, runner=review_ad):
        self.provider=provider
        self.products=products
        self.runner=runner
        self.runs={}

    def create(self, ad_text, product_id, as_of_date):
        if any(r.status == 'running' for r in self.runs.values()):
            raise RuntimeError('현재 검토가 실행 중입니다. 완료 후 다시 시도해 주세요.')
        if len(self.runs) >= 30:
            oldest=next((key for key,r in self.runs.items() if r.status != 'running'),None)
            if oldest is not None:
                del self.runs[oldest]
        record=RunRecord(run_id=uuid4().hex)
        self.runs[record.run_id]=record
        record.task=asyncio.create_task(self._execute(record,ad_text,product_id,as_of_date))
        return record

    async def _execute(self,record,ad_text,product_id,as_of_date):
        event_cursor=0
        async def on_update(node,data):
            nonlocal event_cursor
            events=data.get('events',[])
            for event in events[event_cursor:]:
                record.emit('stage',event.model_dump(mode='json'))
            event_cursor=max(event_cursor,len(events))
            if node == 'judge' and data.get('judgment'):
                for verdict in data['judgment'].verdicts:
                    record.emit('verdict',verdict.model_dump(mode='json'))
        try:
            record.result=await self.runner(
                ad_text,provider=self.provider,as_of_date=as_of_date,
                product=self.products.get(product_id),on_update=on_update)
            record.status=record.result.run_status
            if record.status == 'failed':
                invalid_output=any(t.error_code == 'StageOutputError' for t in record.result.tasks)
                message=('모델 응답이 출력·근거 계약을 만족하지 못했습니다. 작업 내역을 확인하고 문안을 수정하거나 다시 시도해 주세요.'
                         if invalid_output else 'AI 검토가 실패했습니다. 작업 내역과 모델 서버 상태를 확인해 주세요.')
                record.emit('error',{'message':message})
        except asyncio.CancelledError:
            record.status='failed'
            record.emit('error',{'message':'서버 종료로 검토가 중단되었습니다.'})
            raise
        except Exception:
            # 응답에 공급자 원본 예외·인증 URL을 노출하지 않는다.
            record.status='failed'
            record.emit('error',{'message':'검토 실행 중 오류가 발생했습니다. 모델 서버와 설정을 확인해 주세요.'})
        finally:
            record.emit('done',{'run_id':record.run_id,'status':record.status})

    async def stream(self,record,after=0):
        cursor=after
        while True:
            record.changed.clear()
            for event in record.events:
                if event['id'] > cursor:
                    cursor=event['id']
                    yield f"id: {cursor}\nevent: {event['event']}\ndata: {json.dumps(event['data'],ensure_ascii=False)}\n\n"
            if record.status != 'running':
                return
            try:
                await asyncio.wait_for(record.changed.wait(),timeout=15)
            except TimeoutError:
                yield ': heartbeat\n\n'

    async def close(self):
        tasks=[r.task for r in self.runs.values() if r.task and not r.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
