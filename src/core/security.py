import secrets
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


class IngestTokenAuth(HTTPBearer):
    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials:
        credentials = await super().__call__(request)
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid authentication scheme."}},
            )
        from src.core.config import Settings
        settings = Settings()
        if not secrets.compare_digest(credentials.credentials, settings.INGEST_TOKEN):
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing token."}},
            )
        return credentials


ingest_auth = IngestTokenAuth()
