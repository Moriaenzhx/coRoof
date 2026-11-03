from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.auth import Db
from app.core.auth import router as auth_router
from app.core.config import settings
from app.core.schemas import ErrorResponse, HealthOut, RuntimeInfo
from app.modules.initiatives.api import router as initiatives_router
from app.modules.members.api import router as members_router
from app.modules.organizations.api import router as organizations_router
from app.modules.organizations.dashboard import router as dashboard_router
from app.modules.work_items.api import router as work_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings().check_deployment()
    yield


app = FastAPI(title="coRoof V1", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_boundary(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (origin and origin != settings().web_origin) or (
            request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "origin_forbidden",
                        "message": "不允许跨站写入",
                    }
                },
            )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {
            "code": "http_error",
            "message": str(exc.detail),
        }
    )
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # No raw input, tokens, emails or sensitive text in error output.
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "字段格式不正确，请检查必填项、长度和日期时区",
            }
        },
    )


@app.exception_handler(IntegrityError)
@app.exception_handler(StaleDataError)
async def conflict(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "write_conflict",
                "message": "记录已存在或发生并发变化，请刷新后重试",
            }
        },
    )


@app.exception_handler(OperationalError)
async def database_error(_: Request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "数据库暂不可用",
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "服务暂不可用，请稍后重试",
            }
        },
    )


@app.get("/healthz", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok")


@app.get("/readyz", response_model=HealthOut)
def ready(db: Db) -> HealthOut:
    version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if version != "0001_slice01":
        raise HTTPException(
            503, detail={"code": "migration_required", "message": "请执行数据库迁移"}
        )
    return HealthOut(status="ready")


@app.get("/api/v1/runtime", response_model=RuntimeInfo)
def runtime() -> RuntimeInfo:
    return RuntimeInfo(
        environment=settings().environment,
        auth_mode=settings().auth_mode,
        analysis_mode=settings().ai_provider,
        deployment_prerequisites=["正式身份验证与邮件发送", "HTTPS 与安全会话", "密钥管理与备份"],
    )


for router in (
    auth_router,
    organizations_router,
    members_router,
    initiatives_router,
    work_router,
    dashboard_router,
):
    app.include_router(
        router,
        prefix="/api/v1",
        responses={
            code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 500, 503)
        },
    )
