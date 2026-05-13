from functools import wraps

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse
import traceback

from app.utils.api_error import ApiError
from app.core.error_codes import ErrorCodes
from app.utils.error_utils import should_include_stack_trace
from app.schemas.response import ApiResponse
from app.core.config import settings
from app.utils.logger import logger


class NoOpLimiter:
    """Mock limiter that does nothing. Used for development."""

    def limit(self, limit_string: str):
        """Decorator that does nothing (pass-through)."""
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            # Return async wrapper if function is async, else sync
            return async_wrapper if hasattr(func, "__await__") else sync_wrapper

        return decorator


# Use real limiter in production/testing, no-op limiter in development
limiter = (
    Limiter(key_func=get_remote_address)
    if settings.ENVIRONMENT != "development"
    else NoOpLimiter()
)


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Handle rate limit exceeded errors.

    Converts RateLimitExceeded exceptions to standardized ApiError responses
    with appropriate HTTP status code and error code.
    """
    logger.error(str(exc), exc_info=True)
    include_stack = should_include_stack_trace()

    error = ApiError(
        statusCode=429,
        message="Too many requests. Please try again later.",
        code=ErrorCodes.TOO_MANY_REQUESTS,
    )

    response = ApiResponse(
        statusCode=error.statusCode,
        success=error.success,
        message=error.message,
        code=error.code,
        stack="".join(traceback.format_stack()) if include_stack else None,
    )

    return JSONResponse(
        status_code=error.statusCode,
        content=response.model_dump(exclude_none=True),
    )
