"""
Classification Tasks

Background Celery tasks for LLM-based message classification.
Runs periodically to classify new messages from all sources.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

from ..celery_app import celery_app
from ..base_task import BaseTask
from ...utils.logger import setup_logger
from ...utils.config import load_config
from ...database import get_db_context, User, MessageClassification
from ...core.credential_provider import CredentialFactory
from ...services.dashboard.classification_service import MessageClassificationService

logger = setup_logger(__name__)


@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.classification_tasks.classify_recent_messages')
def classify_recent_messages(self):
    """
    Classify recent messages for all active users.
    
    Fetches unclassified emails, Slack messages, and Linear issues,
    then uses LLM to determine priority and required actions.
    
    Returns:
        Dictionary with classification statistics
    """
    logger.info("[ClassificationTask] Starting message classification")
    
    config = load_config()
    classification_service = MessageClassificationService(config)
    
    stats = {
        "users_processed": 0,
        "messages_classified": 0,
        "errors": []
    }
    
    try:
        with get_db_context() as session:
            # Get all active users
            users = session.query(User).filter(User.is_active == True).all()
            user_ids = [u.id for u in users]
        
        for user_id in user_ids:
            try:
                result = _classify_user_messages(user_id, config, classification_service)
                stats["users_processed"] += 1
                stats["messages_classified"] += result.get("classified", 0)
            except Exception as e:
                logger.error(f"[ClassificationTask] Error for user {user_id}: {e}")
                stats["errors"].append(f"User {user_id}: {str(e)}")
        
        logger.info(f"[ClassificationTask] Complete: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"[ClassificationTask] Fatal error: {e}")
        stats["errors"].append(str(e))
        return stats


def _classify_user_messages(
    user_id: int, 
    config, 
    classification_service: MessageClassificationService
) -> Dict[str, Any]:
    """
    Classify messages for a single user.
    
    Args:
        user_id: User ID
        config: App configuration
        classification_service: Classification service instance
        
    Returns:
        Classification statistics
    """
    logger.info(f"[ClassificationTask] Processing user {user_id}")
    
    messages_to_classify = []
    cutoff = datetime.utcnow() - timedelta(hours=48)
    
    # 1. Fetch recent emails
    try:
        email_messages = _fetch_unclassified_emails(user_id, config, cutoff)
        messages_to_classify.extend(email_messages)
        logger.info(f"[ClassificationTask] Found {len(email_messages)} emails for user {user_id}")
    except Exception as e:
        logger.warning(f"[ClassificationTask] Failed to fetch emails for user {user_id}: {e}")
    
    # 2. Fetch Slack messages (if integration exists)
    try:
        slack_messages = _fetch_unclassified_slack(user_id, config, cutoff)
        messages_to_classify.extend(slack_messages)
        logger.info(f"[ClassificationTask] Found {len(slack_messages)} Slack messages for user {user_id}")
    except Exception as e:
        logger.debug(f"[ClassificationTask] Slack not available for user {user_id}: {e}")
    
    # 3. Fetch Linear issues (if integration exists)
    try:
        linear_messages = _fetch_unclassified_linear(user_id, config, cutoff)
        messages_to_classify.extend(linear_messages)
        logger.info(f"[ClassificationTask] Found {len(linear_messages)} Linear items for user {user_id}")
    except Exception as e:
        logger.debug(f"[ClassificationTask] Linear not available for user {user_id}: {e}")
    
    if not messages_to_classify:
        logger.info(f"[ClassificationTask] No new messages to classify for user {user_id}")
        return {"classified": 0}
    
    # 4. Classify with LLM
    async def run_classification():
        return await classification_service.classify_messages(user_id, messages_to_classify)
    
    classifications = asyncio.run(run_classification())
    
    # 5. Store results
    stored = classification_service.store_classifications(
        user_id, 
        messages_to_classify, 
        classifications
    )
    
    return {"classified": stored}


def _fetch_unclassified_emails(user_id: int, config, cutoff: datetime) -> List[Dict[str, Any]]:
    """Fetch emails that haven't been classified yet."""
    from src.integrations.gmail import EmailService
    
    messages = []
    
    try:
        credential_provider = CredentialFactory.create(config, user_id)
        email_service = EmailService(credential_provider, user_id)
        
        # Get recent emails
        query = "newer_than:2d"
        emails = email_service.search_emails(query=query, limit=30, allow_rag=False)
        
        # Get already classified IDs
        with get_db_context() as session:
            classified_ids = set(
                r.source_id for r in session.query(MessageClassification.source_id).filter(
                    MessageClassification.user_id == user_id,
                    MessageClassification.source_type == 'email',
                    MessageClassification.classified_at >= cutoff
                ).all()
            )
        
        # Filter to unclassified
        for email in emails:
            email_id = email.get('id', '')
            if email_id and email_id not in classified_ids:
                messages.append({
                    "id": email_id,
                    "source_type": "email",
                    "title": email.get('subject', 'No Subject'),
                    "sender": email.get('from', ''),
                    "snippet": email.get('snippet', email.get('summary', '')),
                    "date": email.get('date')
                })
        
    except Exception as e:
        logger.warning(f"[ClassificationTask] Email fetch error: {e}")
    
    return messages


def _fetch_unclassified_slack(user_id: int, config, cutoff: datetime) -> List[Dict[str, Any]]:
    """Fetch Slack messages that haven't been classified yet."""
    # TODO: Implement once Slack DM ingestion is available
    # For now, return empty list
    return []


def _fetch_unclassified_linear(user_id: int, config, cutoff: datetime) -> List[Dict[str, Any]]:
    """Fetch Linear issues/notifications that haven't been classified yet."""
    from src.integrations.linear import LinearService
    from src.database.models import UserIntegration
    
    messages = []
    
    try:
        # Check if Linear is connected
        with get_db_context() as session:
            integration = session.query(UserIntegration).filter(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == 'linear',
                UserIntegration.is_active == True
            ).first()
            
            if not integration:
                return []
        
        linear_service = LinearService(config, user_id=user_id)
        
        if not linear_service.is_available():
            return []
        
        # Get issues assigned to user with recent activity
        issues = linear_service.get_my_issues(limit=20)
        
        # Get already classified IDs
        with get_db_context() as session:
            classified_ids = set(
                r.source_id for r in session.query(MessageClassification.source_id).filter(
                    MessageClassification.user_id == user_id,
                    MessageClassification.source_type == 'linear',
                    MessageClassification.classified_at >= cutoff
                ).all()
            )
        
        for issue in issues:
            issue_id = issue.get('id', '')
            if issue_id and issue_id not in classified_ids:
                messages.append({
                    "id": issue_id,
                    "source_type": "linear",
                    "title": issue.get('title', 'Untitled Issue'),
                    "sender": f"Linear ({issue.get('state', {}).get('name', 'Unknown')})",
                    "snippet": issue.get('description', '')[:300] if issue.get('description') else '',
                    "date": issue.get('updatedAt') or issue.get('createdAt')
                })
        
        linear_service.close()
        
    except Exception as e:
        logger.warning(f"[ClassificationTask] Linear fetch error: {e}")
    
    return messages


@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.classification_tasks.classify_user_messages')
def classify_user_messages(self, user_id: int):
    """
    Classify messages for a specific user.
    
    Can be triggered manually or by webhooks when new messages arrive.
    
    Args:
        user_id: User ID to classify messages for
        
    Returns:
        Classification statistics
    """
    logger.info(f"[ClassificationTask] Manual trigger for user {user_id}")
    
    config = load_config()
    classification_service = MessageClassificationService(config)
    
    try:
        result = _classify_user_messages(user_id, config, classification_service)
        logger.info(f"[ClassificationTask] User {user_id} classification complete: {result}")
        return result
    except Exception as e:
        logger.error(f"[ClassificationTask] Error for user {user_id}: {e}")
        return {"error": str(e)}
