"""FastAPI 진입점. 데모에서는 Vue 빌드 결과를 같은 서버에서 제공한다."""

from app.core.environment import load_runtime_environment
load_runtime_environment()

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.api.routes.runs import router
from app.services.demo_data import load_demo_data
from app.services.run_manager import RunManager

DIST=Path(__file__).resolve().parents[1]/'web/dist'


@asynccontextmanager
async def lifespan(app):
    provider,products=load_demo_data()
    app.state.manager=RunManager(provider,products)
    yield
    await app.state.manager.close()


def create_app():
    app=FastAPI(title='RedPen',lifespan=lifespan)
    app.include_router(router)

    @app.get('/{path:path}',include_in_schema=False)
    async def frontend(path: str):
        if path == 'api' or path.startswith('api/'):
            raise HTTPException(404,'API 경로를 찾지 못했습니다.')
        target=(DIST/path).resolve()
        if not target.is_relative_to(DIST.resolve()):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        if path and '.' in Path(path).name:
            raise HTTPException(404)
        index=DIST/'index.html'
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(503,'프론트 빌드가 없습니다. web에서 npm run build를 실행하세요.')

    return app


app=create_app()
