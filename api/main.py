"""
Clavr - Intelligent Email AI Agent API - Main Application
Clean, modular FastAPI application with proper separation of concerns
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

# Set Google Cloud credentials if not already set
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    project_dir = Path(__file__).parent.parent
    creds_path = project_dir / "credentials" / "gen-lang-client-0315808706-ab46487e2f00.json"
    if creds_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
    else:
        # Try to find any JSON file in credentials directory
        creds_dir = project_dir / "credentials"
        if creds_dir.exists():
            json_files = list(creds_dir.glob("*.json"))
            if json_files:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(json_files[0])

# Add parent directory to path for src imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded


from src.utils.logger import setup_logger
from api.rate_limit_handler import rate_limit_exceeded_handler

# Import routers
from api.routers import (
    auth, chat, graph,
    integrations, webhooks,
    notifications, blog, dashboard,
    analytics, proactive, health,
    admin, ghost, ai_features, data_export, profile, conversations
)
from api.routers.gmail_push import router as gmail_push_router
# from api.auth_routes import router as google_auth_router  # DEPRECATED
# Voice router for voice input processing
try:
    from api.routers import voice
except ImportError:
    voice = None

logger = setup_logger(__name__)


from api.lifespan import lifespan


# ============================================
# APPLICATION SETUP
# ============================================

# Initialize rate limiter for SlowAPI
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Email AI Agent API",
    description="Intelligent email management with AI-powered features",
    version="2.0.0",
    lifespan=lifespan  # Modern lifespan management
)

# Add SlowAPI state to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS middleware - allows Chrome extension access
# In production, set ALLOWED_ORIGINS environment variable (comma-separated)
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
if not allowed_origins_env:
    # Default to localhost for development if not specified
    allowed_origins = ["http://localhost:3000", "http://localhost:8000"]
    logger.warning("ALLOWED_ORIGINS not set. Defaulting to localhost only.")
else:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware for session management, error handling, and security
from api.middleware import SessionMiddleware, ErrorHandlingMiddleware, RequestLoggingMiddleware, CSRFMiddleware
from api.distributed_rate_limiter import DistributedRateLimitMiddleware
from api.security_headers import SecurityHeadersMiddleware
from src.auth.rotation_middleware import TokenRotationMiddleware
from api.dependencies import AppState

config = AppState.get_config()
security_config = config.security if config.security else None

# Rate limiting configuration from environment
rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
rate_limit_per_hour = int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))
redis_url = os.getenv("REDIS_URL")  # Optional Redis URL for distributed rate limiting

# Token rotation interval (in hours)
token_rotation_interval = int(os.getenv("TOKEN_ROTATION_INTERVAL_HOURS", "24"))

# Security headers configuration
enable_hsts = os.getenv("ENABLE_HSTS", "true").lower() == "true"
is_development = os.getenv("ENVIRONMENT", "development").lower() == "development"

# Add middleware in reverse order (last added = first executed)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)

# Initialize SessionMiddleware with values from config
if security_config:
    app.add_middleware(
        SessionMiddleware,
        ttl_minutes=security_config.session_ttl_minutes,
        cache_ttl_seconds=security_config.session_cache_ttl_seconds,
        cache_max_size=security_config.session_cache_max_size
    )
else:
    app.add_middleware(SessionMiddleware)

app.add_middleware(TokenRotationMiddleware, rotation_interval_hours=token_rotation_interval)

# Use distributed rate limiter (falls back to in-memory if Redis not available)
if config.server:
    app.add_middleware(
        DistributedRateLimitMiddleware,
        requests_per_minute=config.server.rate_limit_per_minute,
        requests_per_hour=config.server.rate_limit_per_hour,
        redis_url=redis_url,
        excluded_paths=config.server.rate_limit_excluded_paths
    )
else:
    app.add_middleware(
        DistributedRateLimitMiddleware,
        requests_per_minute=rate_limit_per_minute,
        requests_per_hour=rate_limit_per_hour,
        redis_url=redis_url
    )

# Add security headers (disable HSTS in development)
if security_config:
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=enable_hsts and not is_development,
        sensitive_paths=security_config.sensitive_paths
    )
else:
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=enable_hsts and not is_development
    )
logger.info("[OK] Security headers middleware enabled")

# Add CSRF protection (if secret_key is set)
if security_config and security_config.secret_key:
    app.add_middleware(
        CSRFMiddleware,
        secret_key=security_config.secret_key,
        token_expires=security_config.csrf_token_expires,
        excluded_paths=security_config.csrf_excluded_paths
    )
    logger.info("[OK] CSRF protection enabled")
else:
    logger.warning("[WARNING] CSRF protection disabled - not recommended for production!")


# ============================================
# INCLUDE ROUTERS
# ============================================

# Google OAuth authentication (new re-authentication flow)
# app.include_router(google_auth_router)  # DEPRECATED: Replaced by auth.router

# Standard API Routes (Prefixed with /api)
app.include_router(auth.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(proactive.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(ghost.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(ai_features.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(data_export.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(gmail_push_router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(chat.query_router, prefix="/api")  # Legacy /api/query/*

# Base Routes (Without prefix)
app.include_router(auth.router)
app.include_router(health.router)
app.include_router(integrations.router)   # Also at /integrations for frontend compatibility
app.include_router(chat.router)          # Chat and query endpoints
app.include_router(blog.router)          # Blog management
# Voice router for voice input processing
try:
    from api.routers import voice
    app.include_router(voice.router)        # Voice interactions
    logger.info("[OK] Voice router enabled")
except ImportError as e:
    logger.warning(f"[WARNING] Voice router not available: {e}")
except Exception as e:
    logger.warning(f"[WARNING] Voice router not available: {e}")

# Workflows router for productivity automation
try:
    from api.routers import workflows
    app.include_router(workflows.router)    # Productivity workflows
    logger.info("[OK] Workflows router enabled")
except ImportError as e:
    logger.warning(f"[WARNING] Workflows router not available: {e}")
except Exception as e:
    logger.warning(f"[WARNING] Workflows router not available: {e}")

# Autonomy router for action execution settings and management
try:
    from api.routers import autonomy
    app.include_router(autonomy.router)     # Autonomous action settings & management
    logger.info("[OK] Autonomy router enabled")
except ImportError as e:
    logger.warning(f"[WARNING] Autonomy router not available: {e}")
except Exception as e:
    logger.warning(f"[WARNING] Autonomy router not available: {e}")

# Notifications router for in-app notification management
try:
    from api.routers import notifications
    app.include_router(notifications.router)  # In-app notifications
    logger.info("[OK] Notifications router enabled")
except ImportError as e:
    logger.warning(f"[WARNING] Notifications router not available: {e}")
except Exception as e:
    logger.warning(f"[WARNING] Notifications router not available: {e}")


# APPLICATION INFO

port = int(os.getenv("PORT", "8000"))
host = os.getenv("HOST", "0.0.0.0")
api_base_url = os.getenv("API_BASE_URL", f"http://localhost:{port}")

logger.info("=" * 60)
logger.info("Email AI Agent API - Starting")
logger.info("=" * 60)
logger.info(f" API will be available at: {api_base_url}")
logger.info(f" Docs available at: {api_base_url}/docs")
logger.info(f" Health check: {api_base_url}/health")
logger.info("=" * 60)


# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == "__main__":
    import uvicorn
    import socket
    import errno
    
    # Check if port is already in use
    port = int(os.getenv("PORT", "8000"))
    # Removed redundant manual socket check - uvicorn handles this gracefully

    
    try:
        uvicorn.run(
            "api.main:app",
            host=host,
            port=port,
            reload=False,  # Auto-reload disabled (macOS permission issues)
            log_level="info"
        )
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            logger.error(f" Port {port} is already in use. Please stop the existing server first.")
            logger.error(f" To find and kill the process: lsof -ti:{port} | xargs kill")
            logger.error(f" Or use: kill $(lsof -ti:{port})")
            sys.exit(1)
        else:
            raise
