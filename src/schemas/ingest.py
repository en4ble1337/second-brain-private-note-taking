from pydantic import BaseModel


class IngestResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail


class JobStatusResponse(BaseModel):
    id: str
    status: str
    note_id: str | None
    error_message: str | None
