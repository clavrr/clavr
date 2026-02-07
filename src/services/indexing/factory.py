"""
Indexer Factory.
Creates specific indexers/crawlers based on configuration.
"""
from typing import Any, Optional
from src.utils.logger import setup_logger
from src.services.indexing.indexing_constants import (
    CRAWLER_EMAIL, CRAWLER_DRIVE, CRAWLER_SLACK, CRAWLER_NOTION, CRAWLER_ASANA,
    CRAWLER_CALENDAR, CRAWLER_TASKS, CRAWLER_KEEP, CRAWLER_LINEAR,
    PROVIDER_GMAIL, PROVIDER_GOOGLE_DRIVE, PROVIDER_SLACK, PROVIDER_NOTION, PROVIDER_ASANA,
    PROVIDER_CALENDAR, PROVIDER_GOOGLE_TASKS, PROVIDER_GOOGLE_KEEP, PROVIDER_LINEAR
)

logger = setup_logger(__name__)

class IndexerFactory:
    """
    Factory to create crawler instances.
    """
    
    @staticmethod
    def create_crawler(
        crawler_type: str, 
        config: Any, 
        creds: Any,
        user_id: int,
        rag_engine: Any = None,
        graph_manager: Any = None,
        topic_extractor: Any = None,
        temporal_indexer: Any = None,
        relationship_manager: Any = None,
        entity_resolver: Any = None,
        observer_service: Any = None,
        token_saver_callback: Optional[Any] = None
    ) -> Optional[Any]:
        """
        Create a specific crawler/indexer instance.
        """
        try:
            if crawler_type == CRAWLER_EMAIL:
                from src.services.indexing.crawlers.email import EmailCrawler
                from src.core.email.google_client import GoogleGmailClient
                
                # Check required method on creds for Gmail Client
                if not hasattr(creds, 'token'):
                     logger.warning("Invalid credentials for EmailCrawler")
                     return None
                     
                client = GoogleGmailClient(config=config, credentials=creds)
                
                # Attach token saver
                if token_saver_callback:
                    client.on_token_refresh = token_saver_callback
                    
                return EmailCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    google_client=client,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service
                )
                
            elif crawler_type == CRAWLER_DRIVE:
                from src.services.indexing.crawlers.drive import DriveCrawler
                from src.integrations.google_drive.service import GoogleDriveService
                
                # Create service wrap
                service = GoogleDriveService(config=config, credentials=creds)
                if token_saver_callback:
                    service.on_token_refresh = token_saver_callback
                    
                return DriveCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    drive_service=service,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service
                )
                
            elif crawler_type == CRAWLER_NOTION:
                from src.services.indexing.crawlers.notion import NotionCrawler
                from src.integrations.notion.client import NotionClient
                
                client = NotionClient(api_key=creds if isinstance(creds, str) else creds.access_token)
                
                return NotionCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    notion_client=client,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service
                )
                
            elif crawler_type == CRAWLER_SLACK:
                from src.services.indexing.crawlers.slack import SlackCrawler
                from src.integrations.slack.client import SlackClient
                
                # Handle extended credentials for Slack (bot token + app token)
                bot_token = creds.access_token if hasattr(creds, 'access_token') else creds.get('bot_token')
                app_token = creds.refresh_token if hasattr(creds, 'refresh_token') else creds.get('app_token')
                
                client = SlackClient(bot_token=bot_token, app_token=app_token)
                
                return SlackCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    slack_client=client,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service
                )
            
            elif crawler_type == CRAWLER_ASANA:
                from src.services.indexing.crawlers.asana import AsanaCrawler
                from src.integrations.asana.service import AsanaService
                
                token = creds.access_token if hasattr(creds, 'access_token') else creds
                
                asana_service = AsanaService(
                    config=config,
                    access_token=token
                )
                
                return AsanaCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    asana_service=asana_service,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service
                )
                
            elif crawler_type == CRAWLER_CALENDAR:
                from src.services.indexing.crawlers.calendar import CalendarCrawler
                from src.integrations.google_calendar.service import CalendarService
                
                # Check required method on creds for Google Client
                if not hasattr(creds, 'token'):
                     logger.warning("Invalid credentials for CalendarCrawler")
                     return None
                     
                service = CalendarService(config=config, credentials=creds)
                
                return CalendarCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    calendar_service=service,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service,
                    token_saver_callback=token_saver_callback
                )
                
            elif crawler_type == CRAWLER_TASKS:
                from src.services.indexing.crawlers.tasks import TasksCrawler
                from src.integrations.google_tasks.service import TaskService
                
                # Check required method on creds for Google Client
                if not hasattr(creds, 'token'):
                     logger.warning("Invalid credentials for TasksCrawler")
                     return None
                     
                service = TaskService(config=config, credentials=creds)
                
                return TasksCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    task_service=service,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service,
                    token_saver_callback=token_saver_callback
                )
                
            elif crawler_type == CRAWLER_KEEP:
                from src.services.indexing.crawlers.keep import KeepCrawler
                from src.integrations.google_keep.service import KeepService
                
                # Check required method on creds for Google Client
                if not hasattr(creds, 'token'):
                     logger.warning("Invalid credentials for KeepCrawler")
                     return None
                     
                service = KeepService(config=config, credentials=creds)
                
                return KeepCrawler(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    keep_service=service,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service,
                    token_saver_callback=token_saver_callback
                )
                
            elif crawler_type == CRAWLER_LINEAR:
                from src.services.indexing.crawlers.linear import LinearIndexer
                from src.integrations.linear.service import LinearService
                
                # Linear uses API key or OAuth token
                linear_service = LinearService(config=config)
                
                return LinearIndexer(
                    config=config,
                    user_id=user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=entity_resolver,
                    observer_service=observer_service
                )
                
            else:
                logger.warning(f"Unknown crawler type: {crawler_type}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to create crawler {crawler_type}: {e}")
            return None
