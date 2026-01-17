"""
Token Persistence Utility.
Handles saving refreshed tokens to the database context-aware.
"""
from typing import Any
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

def create_token_saver_callback(target_id: int, target_type: str = "integration"):
    """
    Creates a callback to persist refreshed tokens to the database.
    
    Args:
        target_id: ID of the UserIntegration or Session record
        target_type: "integration" (UserIntegration table) or "session" (Session table)
    
    Returns:
        Callable that accepts (creds) object and saves to DB.
    """
    def save_tokens(creds: Any):
        try:
            from src.database import get_db_context
            from src.utils import encrypt_token
            from sqlalchemy import update
            from src.database.models import UserIntegration, Session
            
            with get_db_context() as db:
                # Map table-specific columns
                access_col = "access_token" if target_type == "integration" else "gmail_access_token"
                refresh_col = "refresh_token" if target_type == "integration" else "gmail_refresh_token"
                expiry_col = "expires_at" if target_type == "integration" else "token_expiry"
                
                enc_access = encrypt_token(creds.token)
                enc_refresh = encrypt_token(creds.refresh_token) if creds.refresh_token else None
                
                values = {
                    access_col: enc_access,
                    expiry_col: creds.expiry.replace(tzinfo=None) if creds.expiry else None
                }
                if enc_refresh:
                    values[refresh_col] = enc_refresh
                    
                model = UserIntegration if target_type == "integration" else Session
                db.execute(
                    update(model)
                    .where(model.id == target_id)
                    .values(**values)
                )
                db.commit()
                logger.info(f"[TokenPersistence] Persisted refreshed tokens for {target_type} {target_id}")
        except Exception as e:
            logger.error(f"[TokenPersistence] Failed to persist tokens for {target_type} {target_id}: {e}")
            
    return save_tokens
