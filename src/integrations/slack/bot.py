"""
Slack Bot Main Entry Point

Main bot class that ties everything together:
- Socket Mode client initialization
- Event handler registration
- Message ingestion pipeline
- Graceful shutdown
"""
import asyncio
import signal
from typing import Optional, Any, Dict

from .client import SlackClient
from .event_handler import SlackEventHandler
from .ingestion import SlackIngestionPipeline
from .config import SlackConfig
from ..integration_base import BaseIntegration
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class SlackBot(BaseIntegration):
    """
    Main Slack bot class.
    
    Initializes and manages:
    - Slack Socket Mode client
    - Event handlers
    - Ingestion pipeline
    - Graceful shutdown
    """
    
    def __init__(
        self,
        config: Optional[Any] = None,
        db: Optional[Any] = None,
        enable_ingestion: bool = True,
        enable_services: bool = True,
        enable_ai: bool = True
    ):
        """
        Initialize Slack bot.
        
        Args:
            config: Optional configuration object
            db: Optional database session
            enable_ingestion: Whether to enable message ingestion pipeline
            enable_services: Whether to initialize services (inherited from BaseIntegration)
            enable_ai: Whether to initialize AI components (inherited from BaseIntegration)
        """
        # Validate configuration
        if not SlackConfig.validate():
            raise ValueError("Slack configuration is invalid. Please check environment variables.")
        
        # Initialize base integration (services, AI)
        super().__init__(
            config=config,
            db=db,
            enable_services=enable_services,
            enable_ai=enable_ai
        )
        
        self.enable_ingestion = enable_ingestion
        
        # Initialize Slack client
        self.slack_client = SlackClient()

        
        # Initialize event handler
        self.event_handler = SlackEventHandler(
            slack_client=self.slack_client,
            config=self.config,
            db=self.db
        )
        
        # Initialize ingestion pipeline if enabled
        self.ingestion_pipeline = None
        if enable_ingestion:
            try:
                graph_manager = self._get_graph_manager()
                rag_engine = self.ai_components.get('rag_engine')
                
                if graph_manager and rag_engine:
                    self.ingestion_pipeline = SlackIngestionPipeline(
                        slack_client=self.slack_client,
                        graph_manager=graph_manager,
                        rag_engine=rag_engine,
                        config=self.config
                    )
                    logger.info("Slack ingestion pipeline initialized")
            except Exception as e:
                logger.warning(f"Could not initialize ingestion pipeline: {e}")
        
        # Register event handlers
        self._register_handlers()
        
        logger.info("Slack bot initialized with full integration")
    
    async def process_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process a query through the Slack integration (implements BaseIntegration)
        
        Args:
            query: User query string
            context: Optional context (slack_user_id, slack_channel_id, etc.)
            
        Returns:
            Response string
        """
        from .orchestrator import clavr_orchestrator
        
        slack_user_id = context.get('slack_user_id', '') if context else ''
        slack_channel_id = context.get('slack_channel_id', '') if context else ''
        
        return await clavr_orchestrator(
            user_query=query,
            slack_user_id=slack_user_id,
            slack_channel_id=slack_channel_id,
            config=self.config,
            db=self.db,
            slack_client=self.slack_client
        )
    
    def _register_handlers(self):
        """Register Slack event handlers"""
        # Register app_mention handler (when @clavr is mentioned)
        self.slack_client.socket_client.socket_mode_request_listeners.append(
            ("app_mention", self.event_handler.handle_app_mention)
        )
        logger.info("Registered app_mention event handler")
        
        # Optionally register message handler for ingestion (if ingestion enabled)
        if self.enable_ingestion:
            # Note: For ingestion, you might want to listen to all messages in channels
            # This requires additional scopes and setup
            logger.info("Message ingestion enabled (requires message:read scope)")
    
    def start(self):
        """Start the Slack bot (blocking)"""
        logger.info("Starting Slack bot...")
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # Start Socket Mode client (blocking)
            self.slack_client.start()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
            self.stop()
        except Exception as e:
            logger.error(f"Error in Slack bot: {e}", exc_info=True)
            self.stop()
            raise
    
    async def start_async(self):
        """Start the Slack bot (async)"""
        logger.info("Starting Slack bot (async)...")
        
        try:
            await self.slack_client.start_async()
            # Keep running
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in Slack bot: {e}", exc_info=True)
            self.stop()
            raise
    
    def stop(self):
        """Stop the Slack bot"""
        logger.info("Stopping Slack bot...")
        self.slack_client.stop()
        logger.info("Slack bot stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.stop()
        exit(0)

