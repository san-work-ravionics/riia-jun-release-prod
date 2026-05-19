from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog
from rita.logging_config import log_event

router = APIRouter(prefix="/api/v1", tags=["system"])
log = structlog.get_logger(__name__)


class ClientErrorPayload(BaseModel):
    message: str = Field(..., max_length=2000)
    source: str | None = None
    lineno: int | None = None
    colno: int | None = None
    stack: str | None = Field(default=None, max_length=8000)
    url: str | None = None
    trace_id: str | None = None


@router.post("/client-error", status_code=204)
async def ingest_client_error(payload: ClientErrorPayload):
    log_event(log, "error", "client.error",
              message=payload.message,
              source=payload.source,
              lineno=payload.lineno,
              url=payload.url,
              trace_id=payload.trace_id)
