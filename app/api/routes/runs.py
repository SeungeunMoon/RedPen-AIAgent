"""화면용 검토 생성·진행 구독·리포트 API."""

from datetime import date

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.demo_data import SNAPSHOT_DATE

router=APIRouter(prefix='/api')


class CreateRun(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ad_text: str = Field(min_length=1,max_length=10000)
    product_id: str | None = None
    as_of_date: date

    @field_validator('ad_text')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():
            raise ValueError('광고 원문을 입력하세요')
        return value


@router.get('/health')
def health(request: Request):
    provider = request.app.state.manager.provider
    kind = {'RagRegulationProvider':'rag', 'FixedRegulationProvider':'fixed', 'EmptyRegulationProvider':'empty'}[type(provider).__name__]
    return {'status':'ok','data_mode':'stored_snapshots','regulation_provider':kind,'snapshot_date':SNAPSHOT_DATE.isoformat(),
            'verification':'not_performed'}


@router.get('/products')
def products(request: Request,q: str=''):
    return [{'id':key,**p.model_dump(mode='json')} for key,p in request.app.state.manager.products.items()
            if q in p.company_name+p.product_name]


@router.post('/runs',status_code=202)
async def create_run(body: CreateRun,request: Request):
    manager=request.app.state.manager
    if body.as_of_date != SNAPSHOT_DATE:
        raise HTTPException(422,'현재 규정·공시 스냅샷의 검토 기준일은 2026-10-21입니다.')
    if body.product_id is not None and body.product_id not in manager.products:
        raise HTTPException(422,'선택한 공시 상품을 찾지 못했습니다.')
    try:
        record=manager.create(body.ad_text,body.product_id,body.as_of_date)
    except RuntimeError as error:
        raise HTTPException(409,str(error)) from None
    return {'run_id':record.run_id}


def record_or_404(request,run_id):
    record=request.app.state.manager.runs.get(run_id)
    if record is None:
        raise HTTPException(404,'검토를 찾지 못했습니다. 서버 재시작 시 이력은 초기화됩니다.')
    return record


@router.get('/runs/{run_id}')
def get_run(run_id: str,request: Request):
    record=record_or_404(request,run_id)
    return {'run_id':run_id,'status':record.status,
            'report':record.result.model_dump(mode='json') if record.result else None}


@router.get('/runs/{run_id}/events')
async def events(run_id: str,request: Request,last_event_id: str | None=Header(default=None)):
    record=record_or_404(request,run_id)
    try:
        after=int(last_event_id or 0)
        if after < 0: raise ValueError()
    except ValueError:
        raise HTTPException(422,'잘못된 Last-Event-ID') from None
    return StreamingResponse(request.app.state.manager.stream(record,after),media_type='text/event-stream',
        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
