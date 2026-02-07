"""
Push Notification Service

Handles delivery of notifications to mobile devices via Firebase Cloud Messaging.
This service is designed to be used with the InsightDeliveryService for real-time
proactive notifications.
"""
from typing import Dict, Any, Optional, List
from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class PushNotificationService:
    """Service for sending push notifications to mobile devices."""
    
    def __init__(self, config: Config):
        self.config = config
        self._fcm_client = None
        self._initialized = False
        
    @property
    def is_available(self) -> bool:
        """Check if push notifications are available."""
        return self._initialized and self._fcm_client is not None
        
    @property
    def fcm_client(self):
        """Lazy-load Firebase client."""
        if self._fcm_client is None and not self._initialized:
            self._initialized = True
            try:
                import firebase_admin
                from firebase_admin import messaging, credentials
                
                # Check if Firebase is already initialized
                if not firebase_admin._apps:
                    creds_path = self.config.get('FIREBASE_CREDENTIALS_PATH')
                    if creds_path:
                        cred = credentials.Certificate(creds_path)
                        firebase_admin.initialize_app(cred)
                        logger.info("[PushService] Firebase initialized successfully")
                    else:
                        logger.debug("[PushService] FIREBASE_CREDENTIALS_PATH not set")
                        return None
                    
                self._fcm_client = messaging
                
            except ImportError:
                logger.debug("[PushService] firebase-admin not installed")
            except Exception as e:
                logger.warning(f"[PushService] Firebase initialization failed: {e}")
                
        return self._fcm_client
        
    async def send_notification(
        self,
        user_id: int,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "high"
    ) -> bool:
        """
        Send a push notification to a user's registered devices.
        
        Args:
            user_id: User ID to send notification to
            title: Notification title
            body: Notification body text
            data: Optional additional data payload
            priority: Notification priority ('high' or 'normal')
            
        Returns:
            True if at least one device received the notification
        """
        if not self.fcm_client:
            return False
            
        # Get user's device tokens from database
        tokens = await self._get_user_device_tokens(user_id)
        if not tokens:
            logger.debug(f"[PushService] No device tokens for user {user_id}")
            return False
            
        try:
            # Convert data to string values (FCM requirement)
            string_data = {}
            if data:
                for key, value in data.items():
                    string_data[key] = str(value) if not isinstance(value, str) else value
            
            # Build multicast message
            message = self.fcm_client.MulticastMessage(
                notification=self.fcm_client.Notification(
                    title=title,
                    body=body[:200]  # Truncate for notification preview
                ),
                data=string_data,
                tokens=tokens,
                android=self.fcm_client.AndroidConfig(
                    priority=priority,
                    notification=self.fcm_client.AndroidNotification(
                        click_action="FLUTTER_NOTIFICATION_CLICK"
                    )
                ),
                apns=self.fcm_client.APNSConfig(
                    payload=self.fcm_client.APNSPayload(
                        aps=self.fcm_client.Aps(
                            sound="default",
                            badge=1
                        )
                    )
                )
            )
            
            # Send notification
            response = self.fcm_client.send_multicast(message)
            
            logger.info(
                f"[PushService] Sent to user {user_id}: "
                f"{response.success_count}/{len(tokens)} succeeded"
            )
            
            # Handle failed tokens (remove invalid ones)
            if response.failure_count > 0:
                await self._handle_failed_tokens(tokens, response.responses)
                
            return response.success_count > 0
            
        except Exception as e:
            logger.error(f"[PushService] Push notification failed: {e}")
            return False
            
    async def send_insight_notification(
        self,
        user_id: int,
        insight: Dict[str, Any],
        priority: str = "high"
    ) -> bool:
        """
        Send a formatted notification for an insight.
        
        Args:
            user_id: User ID
            insight: Insight data with type, content, etc.
            priority: Notification priority
            
        Returns:
            True if notification was sent successfully
        """
        # Generate title based on insight type
        insight_type = insight.get('type', 'insight')
        title_map = {
            'calendar_conflict': '⚠️ Schedule Conflict',
            'topic_connection': '🔗 Related Information',
            'person_ooo': '🏖️ Out of Office',
            'follow_up': '📧 Follow-up Needed',
            'urgent_action': '🚨 Urgent Action Required',
            'connection': '💡 New Connection',
        }
        
        title = title_map.get(insight_type, '💡 Insight')
        body = insight.get('content') or insight.get('description', '')
        
        return await self.send_notification(
            user_id=user_id,
            title=title,
            body=body,
            data={
                "insight_id": insight.get('id', ''),
                "insight_type": insight_type,
                "source_node_id": insight.get('source_node_id', '')
            },
            priority=priority
        )
    
    async def _get_user_device_tokens(self, user_id: int) -> List[str]:
        """
        Get registered device tokens for a user.
        
        This queries the database for the user's registered mobile devices.
        """
        try:
            from src.database import get_db_context
            from sqlalchemy import select
            
            # Check if DeviceToken model exists
            try:
                from src.database.models import DeviceToken
            except ImportError:
                # DeviceToken model doesn't exist yet - return empty
                logger.debug("[PushService] DeviceToken model not found")
                return []
            
            with get_db_context() as db:
                stmt = select(DeviceToken.token).where(
                    DeviceToken.user_id == user_id,
                    DeviceToken.is_active == True
                )
                result = db.execute(stmt)
                tokens = [row[0] for row in result.fetchall()]
                return tokens
                
        except Exception as e:
            logger.debug(f"[PushService] Failed to get device tokens: {e}")
            return []
            
    async def _handle_failed_tokens(
        self,
        tokens: List[str],
        responses: List
    ) -> None:
        """Handle failed tokens by marking them as inactive."""
        try:
            from src.database import get_db_context
            from sqlalchemy import update
            
            try:
                from src.database.models import DeviceToken
            except ImportError:
                return
            
            # Find tokens that failed with unregistered error
            invalid_tokens = []
            for idx, response in enumerate(responses):
                if not response.success:
                    error = response.exception
                    if hasattr(error, 'code') and error.code in [
                        'messaging/invalid-registration-token',
                        'messaging/registration-token-not-registered'
                    ]:
                        invalid_tokens.append(tokens[idx])
                        
            if invalid_tokens:
                with get_db_context() as db:
                    stmt = update(DeviceToken).where(
                        DeviceToken.token.in_(invalid_tokens)
                    ).values(is_active=False)
                    db.execute(stmt)
                    db.commit()
                    
                logger.info(f"[PushService] Deactivated {len(invalid_tokens)} invalid tokens")
                
        except Exception as e:
            logger.debug(f"[PushService] Failed to handle invalid tokens: {e}")


# Global singleton
_push_service: Optional[PushNotificationService] = None


def get_push_service() -> Optional[PushNotificationService]:
    """Get the global push notification service instance."""
    return _push_service


def init_push_service(config: Config) -> PushNotificationService:
    """Initialize and return the global push notification service."""
    global _push_service
    _push_service = PushNotificationService(config)
    logger.info("[PushService] Push notification service initialized")
    return _push_service
