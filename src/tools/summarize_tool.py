"""
Summarize Tool - Intelligent Document Summarization
Orchestrates modular summarization components for flexible content processing
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from .base_tool import ClavrBaseTool
from .summarize import (
    # Summarizers
    ExtractiveSummarizer,
    AbstractiveSummarizer,
    EmailThreadSummarizer,
    CalendarEventSummarizer,
    ConversationSummarizer,
    # Utils
    SummaryCache,
    InputValidator,
    ContentPreprocessor,
    generate_cache_key,
    # Quality
    QualityMetrics,
    # Constants
    NLP_ENHANCEMENT_MIN_LENGTH,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
)
from ..ai.llm_factory import LLMFactory
from ..utils.config import Config
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class SummarizeInput(BaseModel):
    """Input schema for summarization"""
    content: str = Field(description="Content to summarize (email, document, thread)")
    format: Optional[str] = Field(
        default="paragraph",
        description="Output format: paragraph, bullet_points, key_points"
    )
    length: Optional[str] = Field(
        default="medium",
        description="Summary length: short, medium, long"
    )
    focus: Optional[str] = Field(
        default=None,
        description="Specific focus or aspect to emphasize"
    )
    source_type: Optional[str] = Field(
        default=None,
        description="Type of content: email, document, thread, calendar_event, conversation"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional context: sender, recipients, dates, participants, etc."
    )


class SummarizeTool(ClavrBaseTool):
    """
    Intelligent document and email summarization tool
    
    Capabilities:
    - LLM-powered abstractive summarization
    - Extractive fallback summarization
    - Multi-format output (paragraph, bullet points, key takeaways)
    - Email thread summarization
    - Calendar event summarization
    - Conversation summarization
    - Quality metrics and validation
    - Intelligent caching
    """
    
    name: str = "summarize"
    description: str = (
        "Summarize emails, documents, and text content using intelligent NLP. "
        "Can generate bullet points, key takeaways, or paragraph summaries. "
        "Use this tool to extract important information from long content."
    )
    args_schema: type[BaseModel] = SummarizeInput
    config: Optional[Config] = Field(default=None, exclude=True)
    
    def __init__(self, config: Optional[Config] = None, **kwargs):
        """
        Initialize summarize tool with modular components
        
        Args:
            config: Configuration object for LLM and NLP utilities
        """
        super().__init__(config=config, **kwargs)
        
        # Initialize modular components (lazy loading)
        self._cache = SummaryCache()
        self._validator = InputValidator()
        self._preprocessor = ContentPreprocessor()
        self._quality = QualityMetrics()
        
        # Summarizers (initialized lazily when needed)
        self._extractive = None
        self._abstractive = None
        self._email_summarizer = None
        self._calendar_summarizer = None
        self._conversation_summarizer = None
        
        # Initialize LLM client with custom settings for summarization
        if config and self.llm_client is None:
            try:
                self._set_attr('llm_client', LLMFactory.get_llm_for_provider(
                    config, 
                    temperature=LLM_TEMPERATURE, 
                    max_tokens=LLM_MAX_TOKENS
                ))
            except Exception as e:
                logger.warning(f"LLM initialization failed: {e}")
    
    # === LAZY LOADING PROPERTIES ===
    
    @property
    def extractive(self) -> ExtractiveSummarizer:
        """Get or create extractive summarizer"""
        if self._extractive is None:
            self._extractive = ExtractiveSummarizer()
        return self._extractive
    
    @property
    def abstractive(self) -> AbstractiveSummarizer:
        """Get or create abstractive summarizer"""
        if self._abstractive is None:
            self._abstractive = AbstractiveSummarizer(self.llm_client)
        return self._abstractive
    
    @property
    def email_summarizer(self) -> EmailThreadSummarizer:
        """Get or create email thread summarizer"""
        if self._email_summarizer is None:
            self._email_summarizer = EmailThreadSummarizer(self.llm_client)
        return self._email_summarizer
    
    @property
    def calendar_summarizer(self) -> CalendarEventSummarizer:
        """Get or create calendar event summarizer"""
        if self._calendar_summarizer is None:
            self._calendar_summarizer = CalendarEventSummarizer(self.llm_client)
        return self._calendar_summarizer
    
    @property
    def conversation_summarizer(self) -> ConversationSummarizer:
        """Get or create conversation summarizer"""
        if self._conversation_summarizer is None:
            self._conversation_summarizer = ConversationSummarizer(self.llm_client)
        return self._conversation_summarizer
    
    # === MAIN EXECUTION ===
    
    def _run(
        self,
        content: str,
        format: str = "paragraph",
        length: str = "medium",
        focus: Optional[str] = None,
        action: Optional[str] = None,
        source_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Summarize content using modular components
        
        Args:
            content: Content to summarize
            format: Output format (paragraph, bullet_points, key_points)
            length: Summary length (short, medium, long)
            focus: Specific focus area
            source_type: Type of content for context
            metadata: Additional context metadata
            
        Returns:
            Formatted summary
        """
        try:
            # Validate inputs
            is_valid, error = self._validator.validate_all(content, format, length)
            if not is_valid:
                return f"[ERROR] {error}"
            
            self._log_execution(
                "summarize",
                format=format,
                length=length,
                focus=focus,
                content_length=len(content),
                source_type=source_type
            )
            
            # Check cache first
            cache_key = generate_cache_key(content, format, length, focus)
            cached_summary = self._cache.get(cache_key)
            if cached_summary:
                logger.info(f"[CACHE HIT] Returning cached summary")
                return cached_summary
            
            # Preprocess content
            cleaned_content = self._preprocessor.clean_text(content)
            
            # Use NLP enhancement if available
            enhanced_content = cleaned_content
            if self.classifier and len(cleaned_content) > NLP_ENHANCEMENT_MIN_LENGTH:
                enhanced_content = self._enhance_with_nlp(cleaned_content)
            
            # Generate summary (try abstractive first, fallback to extractive)
            summary = None
            if self.llm_client:
                logger.info("[ABSTRACTIVE] Using AI summarization")
                summary = self.abstractive.summarize(
                    enhanced_content, 
                    format, 
                    length, 
                    focus, 
                    metadata
                )
            
            if not summary:
                logger.info("[EXTRACTIVE] Using extraction-based summarization")
                summary = self.extractive.summarize(enhanced_content, format, length)
            
            # Cache the result
            self._cache.set(cache_key, summary)
            
            # Calculate and log quality metrics
            metrics = self._quality.calculate_all_metrics(content, summary)
            self._quality.log_metrics(metrics, context="Summary")
            
            return summary
            
        except Exception as e:
            return self._handle_error(e, "summarizing content")
    
    async def _arun(
        self,
        content: str,
        format: str = "paragraph",
        length: str = "medium",
        focus: Optional[str] = None,
        action: Optional[str] = None,
        source_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Async execution (currently delegates to sync version)
        
        Note: Future enhancement - Implement true async LLM calls for better performance.
        Current implementation is functional and delegates to synchronous _run() method.
        """
        return self._run(
            content=content,
            format=format,
            length=length,
            focus=focus,
            source_type=source_type,
            metadata=metadata
        )
    
    # === NLP ENHANCEMENT ===
    
    def _enhance_with_nlp(self, content: str) -> str:
        """
        Enhance content processing using NLP classification
        
        Args:
            content: Content to enhance
            
        Returns:
            Enhanced content (or original if enhancement fails)
        """
        if not self.classifier or len(content) < 200:
            return content
        
        try:
            # Use first 500 chars for classification
            sample = content[:500]
            classification = self.classifier.classify_query(sample)
            entities = classification.get('entities', {})
            
            # Log classification insights
            if entities:
                logger.info(f"[NLP] Classification detected: {list(entities.keys())}")
            
            return content
            
        except Exception as e:
            logger.warning(f"[NLP] Enhancement failed: {e}")
            return content
    
    # === SPECIALIZED SUMMARIZATION METHODS ===
    
    def summarize_email_thread(
        self,
        emails: List[Dict[str, Any]],
        format: str = "bullet_points",
        length: str = "medium"
    ) -> str:
        """
        Summarize email thread with context awareness
        
        Args:
            emails: List of email dictionaries (sender, date, subject, body)
            format: Output format
            length: Summary length
            
        Returns:
            Formatted thread summary
        """
        if not emails:
            return "[ERROR] No emails provided"
        
        try:
            return self.email_summarizer.summarize(emails, format, length)
        except Exception as e:
            return self._handle_error(e, "summarizing email thread")
    
    def summarize_calendar_events(
        self,
        events: List[Dict[str, Any]],
        format: str = "bullet_points",
        length: str = "medium"
    ) -> str:
        """
        Summarize calendar events/meetings
        
        Args:
            events: List of event dictionaries (title, start, duration, attendees)
            format: Output format
            length: Summary length
            
        Returns:
            Formatted events summary
        """
        if not events:
            return "[ERROR] No events provided"
        
        try:
            return self.calendar_summarizer.summarize(events, format, length)
        except Exception as e:
            return self._handle_error(e, "summarizing calendar events")
    
    def summarize_conversation(
        self,
        messages: List[Dict[str, Any]],
        format: str = "bullet_points",
        length: str = "medium"
    ) -> str:
        """
        Summarize conversation/chat thread
        
        Args:
            messages: List of message dictionaries (speaker, timestamp, content)
            format: Output format
            length: Summary length
            
        Returns:
            Formatted conversation summary
        """
        if not messages:
            return "[ERROR] No messages provided"
        
        try:
            return self.conversation_summarizer.summarize(messages, format, length)
        except Exception as e:
            return self._handle_error(e, "summarizing conversation")
    
    # === PARSER INTEGRATION ===
    # Note: SummarizeTool is a utility tool, not domain-specific, so it doesn't
    # integrate with parsers. However, we implement get_supported_tools() for consistency.
    
    def get_supported_tools(self) -> List[str]:
        """
        Return list of tool names this tool supports
        
        SummarizeTool is a utility tool that doesn't have a domain-specific parser.
        It can be used by other tools (email, task, calendar) for summarization.
        """
        return ['summarize']
    
    # === UTILITY METHODS ===
    
    def clear_cache(self):
        """Clear the summary cache"""
        self._cache.clear()
        logger.info("[CACHE] Cleared summary cache")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return {
            'size': self._cache.size(),
            'max_size': self._cache.max_size
        }
