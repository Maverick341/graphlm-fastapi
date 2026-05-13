"""
Custom exception classes and error handlers for the FastAPI application.

Implements ApiError exception class and global error handlers for consistent
error handling across the application using standardized response format.
Mirrors Express.js error handling patterns.
"""

import traceback
from typing import Any, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded

from app.core.error_codes import ErrorCodes
from app.core.config import settings
from app.utils.error_utils import should_include_stack_trace, format_validation_errors
from app.schemas.response import ApiResponse
from app.utils.logger import logger


class ApiError(Exception):
    """
    Custom exception for API errors with structured error information.

    Mirrors Express.js ApiError pattern for consistent error handling across
    the application. Includes status code, human-readable message, machine-readable
    error code and detailed error list.

    Attributes:
        statusCode (int): HTTP status code for the error response
        message (str): Human-readable error message
        success (bool): Always False for error instances
        code (str, optional): Machine-readable error code (e.g., 'USER_ALREADY_EXISTS')
        errors (List[Any], optional): List of detailed error objects for validation errors
    """

    def __init__(
        self,
        statusCode: int,
        message: str,
        code: Optional[str] = None,
        errors: Optional[List[Any]] = None,
    ):
        """
        Initialize ApiError with structured error information.

        Args:
            statusCode: HTTP status code (e.g., 400, 401, 404)
            message: Human-readable error message
            code: Optional machine-readable error code
            errors: Optional list of detailed error objects

        Example:
            raise ApiError(
                statusCode=400,
                message="Username already exists",
                code="USER_ALREADY_EXISTS",
                errors=[{"field": "username", "detail": "already taken"}]
            )
        """
        super().__init__(message)
        self.statusCode = statusCode
        self.message = message
        self.success = False
        self.code = code or ErrorCodes.INTERNAL_SERVER_ERROR
        self.errors = errors or []

    def __repr__(self) -> str:
        return (
            f"ApiError(statusCode={self.statusCode}, message='{self.message}', "
            f"code='{self.code}', success={self.success})"
        )

    def to_dict(self, include_stack: bool = False) -> dict:
        """
        Convert error to dictionary for JSON serialization.

        Args:
            include_stack: Whether to include stack trace in output

        Returns:
            Dictionary representation of the error with all relevant fields
        """
        error_dict = {
            "statusCode": self.statusCode,
            "success": self.success,
            "message": self.message,
            "code": self.code,
        }

        if self.errors:
            error_dict["errors"] = self.errors

        if include_stack:
            error_dict["stack"] = "".join(traceback.format_stack())

        return error_dict


# Exception Handlers


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """
    Global exception handler for ApiError.

    Converts ApiError exceptions to standardized JSON response format with
    optional stack trace inclusion based on environment configuration.
    Uses proper log levels: ERROR for 5xx, WARNING for 4xx and lower.
    """
    if exc.statusCode >= 500:
        logger.error(f"[{exc.statusCode}] {exc.code}: {str(exc)}", exc_info=True)
    else:
        logger.warning(f"[{exc.statusCode}] {exc.code}: {str(exc)}")
    include_stack = should_include_stack_trace()

    response = ApiResponse(
        statusCode=exc.statusCode,
        success=exc.success,
        message=exc.message,
        code=exc.code,
        errors=exc.errors if exc.errors else None,
        stack="".join(traceback.format_stack()) if include_stack else None,
    )

    return JSONResponse(
        status_code=exc.statusCode,
        content=response.model_dump(exclude_none=True),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Global exception handler for Pydantic validation errors.

    Formats validation errors with standardized error response structure
    and provides detailed error information to the client.
    Logs as WARNING since these are client-side validation failures (422).
    """
    # Extract validation errors from Pydantic
    validation_errors = format_validation_errors(exc.errors())
    logger.warning(f"[422] VALIDATION_ERROR: Request validation failed - {exc.errors()}")

    error = ApiError(
        statusCode=422,
        message="Request validation failed",
        code=ErrorCodes.VALIDATION_ERROR,
        errors=validation_errors,
    )

    include_stack = should_include_stack_trace()

    response = ApiResponse(
        statusCode=error.statusCode,
        success=error.success,
        message=error.message,
        code=error.code,
        errors=error.errors,
        stack="".join(traceback.format_stack()) if include_stack else None,
    )

    return JSONResponse(
        status_code=error.statusCode,
        content=response.model_dump(exclude_none=True),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global fallback exception handler for uncaught exceptions.

    Handles any exception that doesn't match specific handlers and returns
    a generic error response without exposing implementation details in production.
    Logs as ERROR with full traceback since these are server-side failures (500).
    """
    logger.error(f"[500] INTERNAL_SERVER_ERROR: {str(exc)}", exc_info=True)
    include_stack = should_include_stack_trace()
    message = str(exc) if include_stack else "An internal error occurred. Please try again later."

    error = ApiError(
        statusCode=500,
        message=message,
        code=ErrorCodes.INTERNAL_SERVER_ERROR,
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


def register_exception_handlers(app):
    """
    Register all exception handlers with the FastAPI application.

    Should be called during app initialization before starting the server.

    Args:
        app: FastAPI application instance
    """
    from app.api.limiter import _rate_limit_exceeded_handler

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    # Only register rate limit handler when rate limiting is enabled (non-development)
    if settings.ENVIRONMENT != "development":
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
