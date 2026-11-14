import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

_LOCK = Lock()
_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limiter() -> None:
    """Clear in-memory rate limit buckets (for automated tests)."""
    with _LOCK:
        _BUCKETS.clear()


def rate_limit_auth(max_requests: int = 10, window_seconds: int = 60):
    """Sliding-window per-IP rate limiter dependency for auth endpoints."""

    def _dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"{request.url.path}:{client_ip}"
        now = time.monotonic()
        cutoff = now - window_seconds

        with _LOCK:
            dq = _BUCKETS[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "code": "rate_limit_exceeded",
                        "message": "Too many authentication requests. Please try again later.",
                    },
                    headers={"Retry-After": str(window_seconds)},
                )
            dq.append(now)

    return _dependency
