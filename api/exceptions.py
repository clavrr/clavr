"""
API Exceptions and Error Response Models
Standardized error handling for consistent API responses
"""
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ============================================
# ERROR RESPONSE MODELS
# ============================================

class ErrorDetail(BaseModel):
    """Detailed error information"""
    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standardized error response"""
    success: bool = False
    error: str
    message: Optional[str] = None
    details: Optional[List[ErrorDetail]] = None
    request_id: Optional[str] = None
    timestamp: Optional[str] = None


class SuccessResponse(BaseModel):
    """Standardized success response"""
    success: bool = True
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


# ============================================
# CUSTOM EXCEPTIONS
# ============================================

class APIException(HTTPException):
    """Base API exception with standardized response"""
    
    def __init__(
        self,
        status_code: int,
        error: str,
        message: Optional[str] = None,
        details: Optional[List[Dict[str, str]]] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        super().__init__(status_code=status_code, detail=error, headers=headers)
        self.error = error
        self.message = message
        self.details = details
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response"""
        return {
            "success": False,
            "error": self.error,
            "message": self.message,
            "details": self.details
        }


class AuthenticationError(APIException):
    """Authentication failed"""
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error="authentication_required",
            message=message
        )


class AuthorizationError(APIException):
    """Authorization failed - insufficient permissions"""
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            error="authorization_failed",
            message=message
        )


class ValidationError(APIException):
    """Request validation failed"""
    def __init__(self, errors: List[Dict[str, str]], message: str = "Validation failed"):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error="validation_error",
            message=message,
            details=errors
        )


class NotFoundError(APIException):
    """Resource not found"""
    def __init__(self, resource: str = "Resource", message: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            error="not_found",
            message=message or f"{resource} not found"
        )


class ConflictError(APIException):
    """Resource conflict (e.g., already exists)"""
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            error="conflict",
            message=message
        )


class RateLimitError(APIException):
    """Rate limit exceeded"""
    def __init__(self, retry_after: int = 60, message: str = "Rate limit exceeded"):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error="rate_limit_exceeded",
            message=message,
            headers={"Retry-After": str(retry_after)}
        )


class InternalServerError(APIException):
    """Internal server error (should be logged)"""
    def __init__(self, message: str = "Internal server error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error="internal_server_error",
            message=message
        )


# ============================================
# ERROR RESPONSE HANDLERS
# ============================================

def create_error_response(
    error_type: str,
    message: str,
    details: Optional[List[Dict[str, str]]] = None,
    status_code: int = 400
) -> JSONResponse:
    """
    Create a standardized error response
    
    Args:
        error_type: Error code/type
        message: Human-readable error message
        details: Optional list of detailed errors
        status_code: HTTP status code
        
    Returns:
        JSONResponse with standardized error format
    """
    response_data = {
        "success": False,
        "error": error_type,
        "message": message
    }
    
    if details:
        response_data["details"] = details
    
    return JSONResponse(status_code=status_code, content=response_data)


def create_success_response(
    data: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a standardized success response
    
    Args:
        data: Response data
        message: Optional success message
        meta: Optional metadata
        
    Returns:
        Dictionary with standardized success format
    """
    response = {
        "success": True
    }
    
    if data is not None:
        response["data"] = data
    
    if message:
        response["message"] = message
    
    if meta:
        response["meta"] = meta
    
    return response


# ============================================
# EXCEPTION MAPPING
# ============================================

ERROR_MAPPING = {
    ValueError: (status.HTTP_400_BAD_REQUEST, "validation_error"),
    KeyError: (status.HTTP_400_BAD_REQUEST, "missing_field"),
    TypeError: (status.HTTP_400_BAD_REQUEST, "type_error"),
    PermissionError: (status.HTTP_403_FORBIDDEN, "permission_denied"),
    FileNotFoundError: (status.HTTP_404_NOT_FOUND, "not_found"),
    NotImplementedError: (status.HTTP_501_NOT_IMPLEMENTED, "not_implemented"),
}

