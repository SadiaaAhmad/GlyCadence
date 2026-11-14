from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.core.database import MIN_POSTGRES_MAJOR_VERSION, check_db_connection
from app.schemas.health import DatabaseHealthResponse, HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse, summary="Service liveness check")
def get_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )


@router.get(
    "/db",
    response_model=DatabaseHealthResponse,
    summary="PostgreSQL connectivity and minimum version check",
)
def get_database_health(response: Response) -> DatabaseHealthResponse:
    is_healthy, major_version, db_status = check_db_connection()
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DatabaseHealthResponse(
            status="unavailable",
            database=db_status,  # type: ignore[arg-type]
            min_required_major_version=MIN_POSTGRES_MAJOR_VERSION,
            detected_major_version=major_version if db_status == "unsupported_database_version" else None,
        )

    return DatabaseHealthResponse(
        status="ok",
        database="connected",
        min_required_major_version=MIN_POSTGRES_MAJOR_VERSION,
        detected_major_version=major_version,
    )
