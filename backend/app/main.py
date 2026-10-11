from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import LOCAL_ORIGIN_REGEX, settings
from app.routes import analyses, feedback, health, jobs

app = FastAPI(title="Monologue Coach API")


@app.middleware("http")
async def refuse_oversized_uploads(request: Request, call_next):
    """Turns away an upload that declares itself too big, before reading its body."""
    if request.method == "POST" and request.url.path == "/api/analyses":
        message = analyses.upload_is_too_large(request.headers.get("content-length"))
        if message:
            return JSONResponse(
                status_code=413, content={"detail": {"code": "file_too_large", "message": message}}
            )
    return await call_next(request)


# Added after the size check so that it wraps it: refusals carry the CORS headers too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analyses.router)
app.include_router(jobs.router)
app.include_router(feedback.router)


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    """Gives malformed requests the same {code, message} shape as every other error."""
    problems = []
    for item in error.errors():
        field = ".".join(str(part) for part in item.get("loc", ()) if part not in ("body", "query"))
        problems.append(f"{field}: {item.get('msg', 'invalid')}" if field else item.get("msg", ""))
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "invalid_request", "message": "; ".join(problems)}},
    )
