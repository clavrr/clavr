"""
Authentication and Authorization Utilities
Provides decorators and helpers for endpoint protection
"""
import asyncio
from functools import wraps
from typing import Optional, Callable
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.database import get_db
from src.database.models import Session as DBSession, User
from src.utils.logger import setup_logger
from .exceptions import AuthenticationError, AuthorizationError

logger = setup_logger(__name__)

security = HTTPBearer(auto_error=False)


# ============================================
# AUTHENTICATION DEPENDENCIES
# ============================================

def get_current_user_required(request: Request) -> User:
    """
    FastAPI dependency that requires valid authentication
    
    Usage:
        @router.get("/protected")
        def endpoint(user: User = Depends(get_current_user_required)):
            return {"user_id": user.id}
    
    Raises:
        AuthenticationError: If not authenticated
    """
    if not hasattr(request.state, 'session') or request.state.session is None:
        raise AuthenticationError("No active session - please log in")
    
    if not hasattr(request.state, 'user') or request.state.user is None:
        raise AuthenticationError("User not found in session")
    
    return request.state.user


def get_current_user_optional(request: Request) -> Optional[User]:
    """
    FastAPI dependency that optionally returns user if authenticated
    
    Usage:
        @router.get("/profile")
        def profile(user: User = Depends(get_current_user_optional)):
            if user:
                return {"user_id": user.id}
            return {"anonymous": True}
    """
    if hasattr(request.state, 'user') and request.state.user:
        return request.state.user
    return None


def require_admin(user: User = Depends(get_current_user_required)) -> User:
    """
    FastAPI dependency that requires admin privileges
    
    Usage:
        @router.delete("/admin/user/{user_id}")
        def delete_user(admin: User = Depends(require_admin)):
            ...
    
    Raises:
        AuthorizationError: If user is not admin
    """
    if not user.is_admin:
        raise AuthorizationError("Admin access required")
    return user


def require_active_user(user: User = Depends(get_current_user_required)) -> User:
    """
    FastAPI dependency that requires active (non-deleted) user
    
    Usage:
        @router.post("/action")
        def action(user: User = Depends(require_active_user)):
            ...
    """
    # Note: Active status checking will be implemented when user status tracking is added
    return user


# ============================================
# SESSION MANAGEMENT
# ============================================

def get_user_session(request: Request) -> DBSession:
    """
    FastAPI dependency that requires valid session
    
    Usage:
        @router.post("/data")
        def get_data(session: DBSession = Depends(get_user_session)):
            user_id = session.user_id
            ...
    
    Raises:
        AuthenticationError: If no valid session
    """
    if not hasattr(request.state, 'session') or request.state.session is None:
        raise AuthenticationError("No active session - please log in")
    
    return request.state.session


# ============================================
# ROLE-BASED ACCESS CONTROL
# ============================================

def require_role(role: str):
    """
    Decorator to require specific role
    
    Usage:
        @require_role("admin")
        @router.get("/admin/users")
        def list_users(user: User = Depends(get_current_user_required)):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get user from dependencies
            user = kwargs.get('user') or kwargs.get('admin')
            
            if not user:
                # Try to find user in args
                for arg in args:
                    if isinstance(arg, User):
                        user = arg
                        break
            
            if not user:
                logger.warning(f"Auth warning: User not found in request state/args for role check ({role})")
                raise AuthenticationError("User not found in request")
            
            # Note: Role checking will be implemented when user roles are added
            # For now, all authenticated users are allowed
            logger.debug(f"Role check for {role} - user {user.id} (roles not yet implemented)")
            
            return await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
        
        return wrapper
    return decorator


# ============================================
# PERMISSION HELPERS
# ============================================

def check_resource_ownership(user: User, resource_user_id: int) -> bool:
    """
    Check if user owns a resource
    
    Args:
        user: Current user
        resource_user_id: User ID that owns the resource
        
    Returns:
        True if user owns the resource
    """
    return user.id == resource_user_id


def require_resource_ownership(resource_user_id: int):
    """
    Decorator to require resource ownership
    
    Usage:
        @require_resource_ownership(user_id)
        @router.get("/user/{user_id}/data")
        def get_user_data(user: User = Depends(get_current_user_required)):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get('user')
            
            if not user:
                logger.warning(f"Auth warning: User not found in request state for ownership check (ResUser: {resource_user_id})")
                raise AuthenticationError("User not found in request")
            
            if not check_resource_ownership(user, resource_user_id):
                raise AuthorizationError("You don't have permission to access this resource")
            
            return await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
        
        return wrapper
    return decorator

