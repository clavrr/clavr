"""
Clavr - Intelligent Email AI Agent API - Main Application
Clean, modular FastAPI application with proper separation of concerns
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Load environment variables
load_dotenv()

# Add parent directory to path for src imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.database import init_db, init_async_db
from src.utils.logger import setup_logger
from api.rate_limit_handler import rate_limit_exceeded_handler

# Import routers
from api.routers import health, chat, ai_features, auth, blog, admin, data_export, webhooks, profile, dashboard
from api.routers.gmail_push import router as gmail_push_router
from api.auth_routes import router as google_auth_router
# Voice router temporarily disabled - uncomment to re-enable when voice feature is implemented
# from api.routers import voice

logger = setup_logger(__name__)


# ============================================
# APPLICATION LIFECYCLE
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    Replaces deprecated @app.on_event("startup")
    """
    # Startup
    try:
        # Initialize sync database (for backward compatibility and sync operations)
        # TODO: Remove this once we have a proper async database implementation
        init_db()
        logger.info("[OK] Sync database initialized successfully")
        
        # Initialize async database (for async routes and operations)
        await init_async_db()
        logger.info("[OK] Async database initialized successfully")
        
        # Start background email indexing for authenticated users
        # This ensures real-time indexing continues after server restart
        try:
            from api.dependencies import AppState
            from src.services.indexing.indexer import start_user_background_indexing
            from src.database.models import User, Session as DBSession
            from src.core.email.google_client import GoogleGmailClient
            from src.auth.token_refresh import get_valid_credentials
            from google.oauth2.credentials import Credentials
            import os
            
            config = AppState.get_config()
            rag_engine = AppState.get_rag_engine()
            
            if rag_engine:
                logger.info("[INFO] Starting background email indexing for authenticated users...")
                
                # Get all users with Gmail authentication
                from src.database import get_db_context
                with get_db_context() as db:
                    authenticated_users = db.query(User).join(DBSession).filter(
                        DBSession.gmail_access_token.isnot(None)
                    ).distinct().all()
                    
                    started_count = 0
                    for user in authenticated_users:
                        try:
                            # Get user's session with credentials
                            user_session = db.query(DBSession).filter(
                                DBSession.user_id == user.id,
                                DBSession.gmail_access_token.isnot(None)
                            ).order_by(DBSession.id.desc()).first()
                            
                            if user_session:
                                # Get valid credentials (use async version in async context)
                                from src.auth.token_refresh import get_valid_credentials_async
                                credentials_obj = await get_valid_credentials_async(db, user_session, auto_refresh=True)
                                
                                if credentials_obj:
                                    # Create Google client
                                    client_id = os.getenv('GOOGLE_CLIENT_ID')
                                    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
                                    
                                    if client_id and client_secret:
                                        google_credentials = Credentials(
                                            token=credentials_obj.token,
                                            refresh_token=credentials_obj.refresh_token,
                                            token_uri="https://oauth2.googleapis.com/token",
                                            client_id=client_id,
                                            client_secret=client_secret,
                                            scopes=credentials_obj.scopes
                                        )
                                        
                                        google_client = GoogleGmailClient(config=config, credentials=google_credentials)
                                        
                                        # Start background indexing
                                        await start_user_background_indexing(
                                            user_id=user.id,
                                            config=config,
                                            rag_engine=rag_engine,
                                            google_client=google_client,
                                            initial_batch_size=50  # Small batch for existing users
                                        )
                                        
                                        started_count += 1
                                        logger.info(f"[OK] Started background indexing for user {user.id} ({user.email})")
                                        
                        except Exception as e:
                            logger.warning(f"Could not start indexing for user {user.id}: {e}")
                            continue
                    
                    if started_count > 0:
                        logger.info(f"[OK] Background email indexing started for {started_count} user(s)")
                    else:
                        logger.info("[INFO] No authenticated users found - indexing will start on next OAuth")
            else:
                logger.info("[INFO] Background email indexing not available (RAG tool not configured)")
        except Exception as e:
            logger.warning(f"Could not start background email indexing: {e}")
            # Don't fail startup if background indexing check fails
        
        # Start background profile update service
        try:
            from src.services.profile_service import start_profile_service
            await start_profile_service()
            logger.info("[OK] Background profile update service started")
        except Exception as e:
            logger.warning(f"Could not start profile update service: {e}")
            # Don't fail startup if profile service fails to start
        
    except Exception as e:
        logger.error(f"[ERROR] Failed to initialize database: {e}", exc_info=True)
    
    yield
    
    # Shutdown
    import asyncio
    try:
        from src.services.indexing.indexer import stop_background_indexing
        await stop_background_indexing()
        logger.info("[OK] Background email indexing stopped")
    except asyncio.CancelledError:
        # Expected during shutdown - tasks are already cancelled
        logger.info("Background indexing cancellation handled during shutdown")
    except Exception as e:
        logger.warning(f"Error stopping background indexing: {e}")
    
    try:
        from src.services.profile_service import stop_profile_service
        await stop_profile_service()
        logger.info("[OK] Background profile service stopped")
    except asyncio.CancelledError:
        # Expected during shutdown
        logger.info("Profile service cancellation handled during shutdown")
    except Exception as e:
        logger.warning(f"Error stopping profile service: {e}")
    
    # Close database connections gracefully
    try:
        from src.database.database import close_db_connections
        from src.database.async_database import close_async_db_connections
        
        close_db_connections()
        await close_async_db_connections()
        logger.info("[OK] Database connections closed")
    except asyncio.CancelledError:
        # Expected during shutdown
        logger.info("Database connection closure cancelled during shutdown")
    except Exception as e:
        logger.warning(f"Error closing database connections: {e}")
    
    logger.info("Shutting down Email AI Agent API")


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
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",")] if allowed_origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware for session management, error handling, and security
from api.middleware import SessionMiddleware, ErrorHandlingMiddleware, RequestLoggingMiddleware, CSRFMiddleware
from api.rate_limiter import RateLimitMiddleware
from src.auth.rotation_middleware import TokenRotationMiddleware

# Rate limiting configuration from environment
rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
rate_limit_per_hour = int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))

# Token rotation interval (in hours)
token_rotation_interval = int(os.getenv("TOKEN_ROTATION_INTERVAL_HOURS", "24"))

# CSRF token expiration (in seconds)
csrf_token_expires = int(os.getenv("CSRF_TOKEN_EXPIRES", "3600"))  # 1 hour default

# Get secret key for CSRF protection
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    logger.warning("SECRET_KEY not set - CSRF protection disabled!")
    logger.warning("Set SECRET_KEY in .env for production security")

# Add middleware in reverse order (last added = first executed)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(SessionMiddleware)
app.add_middleware(TokenRotationMiddleware, rotation_interval_hours=token_rotation_interval)
app.add_middleware(RateLimitMiddleware, requests_per_minute=rate_limit_per_minute, requests_per_hour=rate_limit_per_hour)

# Add CSRF protection (only if SECRET_KEY is set)
if secret_key:
    app.add_middleware(CSRFMiddleware, secret_key=secret_key, token_expires=csrf_token_expires)
    logger.info("[OK] CSRF protection enabled")
else:
    logger.warning("[WARNING] CSRF protection disabled - not recommended for production!")


# ============================================
# INCLUDE ROUTERS
# ============================================

# Google OAuth authentication (new re-authentication flow)
app.include_router(google_auth_router)

# Authentication (user login/logout)
app.include_router(auth.router)

# Core features
app.include_router(health.router)        # Health checks and stats
app.include_router(chat.router)          # Chat and query endpoints
app.include_router(ai_features.router)   # AI-powered features
app.include_router(profile.router)       # User writing profile management
app.include_router(dashboard.router)     # Dashboard statistics (emails, events, tasks)
app.include_router(blog.router)          # Blog management
app.include_router(admin.router)         # Admin endpoints (admin only)
app.include_router(data_export.router)   # GDPR data export (user data portability)
app.include_router(webhooks.router)      # Webhook subscriptions and deliveries
app.include_router(gmail_push_router)    # Gmail push notifications (real-time email indexing)
# Voice router temporarily disabled - uncomment to re-enable when voice feature is implemented
# app.include_router(voice.router)        # Voice interactions


# ============================================
# APPLICATION INFO
# ============================================

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
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('0.0.0.0', port))
        sock.close()
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            logger.error(f" Port {port} is already in use. Please stop the existing server first.")
            logger.error(f" To find and kill the process: lsof -ti:{port} | xargs kill")
            logger.error(f" Or use: kill $(lsof -ti:{port})")
            sys.exit(1)
        else:
            raise
    
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
