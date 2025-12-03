"""
API Routers - Modular organization of API endpoints
"""
from . import health, chat, ai_features, auth, blog, admin, dashboard, data_export, webhooks, profile, graph
# TODO: Voice router temporarily disabled - uncomment to re-enable in the future
# from . import voice

__all__ = ["health", "chat", "ai_features", "auth", "blog", "admin", "dashboard", "data_export", "webhooks", "profile", "graph"]
# TODO: Add "voice" back to __all__ when re-enabling voice functionality
