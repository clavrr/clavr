"""
Notion Parser - Handles Notion-specific query parsing and execution

This parser understands natural language Notion queries and converts them into
structured Notion operations. It provides:

- Intent classification (search, create_page, update_page, query_database, etc.)
- Entity extraction (titles, database IDs, page IDs, properties, content)
- Advanced query understanding with LLM support
- Conversational response generation
- Semantic pattern matching

The parser uses LLM-powered classification when available, falling back to
pattern-based parsing for reliability.

Enhanced with Superior NLU Approach:
- Semantic pattern matching with embeddings
- Confidence-based routing
- Learning system for continuous improvement
- Few-shot learning and chain-of-thought reasoning
"""
import re
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from langchain.tools import BaseTool

from .base_parser import BaseParser
from ...utils.logger import setup_logger
from .notion.semantic_matcher import NotionSemanticPatternMatcher
from .notion.learning_system import NotionLearningSystem

# Import handler modules
from .notion.classification_handlers import NotionClassificationHandlers
from .notion.action_handlers import NotionActionHandlers
from .notion.creation_handlers import NotionCreationHandlers
from .notion.management_handlers import NotionManagementHandlers
from .notion.query_processing_handlers import NotionQueryProcessingHandlers
from .notion.utility_handlers import NotionUtilityHandlers
from .notion.constants import NotionParserConfig, NotionActionTypes

logger = setup_logger(__name__)


class NotionParser(BaseParser):
    """
    Enhanced Notion Parser with Superior NLU
    
    Modular architecture with specialized handlers:
    - Classification: Intent detection and confidence-based routing
    - Action: Notion-specific action handling
    - Creation: Page and database entry creation
    - Management: Page and database management operations
    - QueryProcessing: Query execution and response generation
    - Utility: Common helper functions
    """
    
    def __init__(self, rag_service=None, memory=None, config=None):
        super().__init__(rag_service, memory, config)
        self.name = "notion"
        self.config = config
        
        # Add NLP utilities if config provided (following TaskParser pattern)
        if config:
            try:
                from ...ai.query_classifier import QueryClassifier
                from ...ai.llm_factory import LLMFactory
                
                self.classifier = QueryClassifier(config)
                try:
                    # Initialize LLM client with higher max_tokens to prevent truncation
                    self.llm_client = LLMFactory.get_llm_for_provider(
                        config, 
                        temperature=NotionParserConfig.LLM_TEMPERATURE, 
                        max_tokens=NotionParserConfig.LLM_MAX_TOKENS
                    )
                    logger.info(f"[NOTION] LLM client initialized (max_tokens={NotionParserConfig.LLM_MAX_TOKENS})")
                except Exception as e:
                    self.llm_client = None
                    logger.warning(f"[NOTION] LLM not available: {e}, using pattern-based parsing")
            except Exception as e:
                logger.warning(f"[NOTION] Failed to initialize NLP utilities: {e}")
                self.classifier = None
                self.llm_client = None
        else:
            self.classifier = None
            self.llm_client = None
            logger.info("[NOTION] Notion parser initialized without config - using pattern-based parsing")
        
        # Initialize enhanced NLU components
        self.semantic_matcher = NotionSemanticPatternMatcher(config=config)
        self.learning_system = NotionLearningSystem(memory=memory)
        
        # Initialize handler modules
        self.classification_handlers = NotionClassificationHandlers(self)
        self.action_handlers = NotionActionHandlers(self)
        self.creation_handlers = NotionCreationHandlers(self)
        self.management_handlers = NotionManagementHandlers(self)
        self.query_processing_handlers = NotionQueryProcessingHandlers(self)
        self.utility_handlers = NotionUtilityHandlers(self)
        
        logger.info("[NOTION] All Notion handler modules initialized successfully")
    
    def get_supported_tools(self) -> List[str]:
        """Return list of tool names this parser supports"""
        return ['notion', 'notion_tool']
    
    def parse_query_to_params(self, query: str, user_id: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse Notion query into structured parameters WITHOUT executing the tool
        
        Args:
            query: User query
            user_id: Optional user ID for context
            session_id: Optional session ID for context
            
        Returns:
            Dictionary with:
                - action: str (e.g., 'search', 'create_page', 'update_page', 'query_database')
                - entities: Dict[str, Any] (e.g., title, database_id, page_id, query, properties)
                - confidence: float (0.0-1.0)
                - metadata: Dict[str, Any] (suggestions, detected patterns, etc.)
        """
        try:
            logger.info(f"[NOTION] NotionParser.parse_query_to_params called with query: '{query}'")
            
            # Extract actual query from conversation context
            actual_query = self.query_processing_handlers.extract_actual_query(query)
            
            # Detect Notion action using classification handlers
            action = self.classification_handlers.detect_notion_action(actual_query)
            logger.info(f"[NOTION] Detected action: {action}")
            
            # Extract entities based on action
            entities = self._extract_entities_for_action(actual_query, action)
            
            # Calculate confidence
            confidence = self._calculate_confidence(actual_query, action, entities)
            
            # Generate metadata
            metadata = self._generate_metadata(actual_query, action, entities)
            
            return {
                "action": action,
                "entities": entities,
                "confidence": confidence,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error in parse_query_to_params: {e}", exc_info=True)
            return {
                "action": "error",
                "entities": {},
                "confidence": 0.0,
                "metadata": {"error": str(e)}
            }
    
    def _extract_entities_for_action(self, query: str, action: str) -> Dict[str, Any]:
        """Extract entities relevant to the detected action"""
        entities = {}
        
        if action == NotionActionTypes.SEARCH:
            entities['query'] = self.utility_handlers.extract_search_query(query)
            entities['database_id'] = self.utility_handlers.extract_database_id_from_query(query)
            entities['num_results'] = NotionParserConfig.DEFAULT_SEARCH_LIMIT
            
        elif action == NotionActionTypes.CREATE_PAGE:
            entities['title'] = self.utility_handlers.extract_title_from_query(query)
            entities['database_id'] = self.utility_handlers.extract_database_id_from_query(query)
            entities['content'] = self.creation_handlers._extract_content_from_query(query)
            
        elif action == NotionActionTypes.UPDATE_PAGE:
            entities['page_id'] = self.utility_handlers.extract_page_id_from_query(query)
            entities['title'] = self.utility_handlers.extract_title_from_query(query)
            
        elif action == NotionActionTypes.GET_PAGE:
            entities['page_id'] = self.utility_handlers.extract_page_id_from_query(query)
            
        elif action == NotionActionTypes.QUERY_DATABASE:
            entities['database_id'] = self.utility_handlers.extract_database_id_from_query(query)
            entities['query'] = self.utility_handlers.extract_search_query(query)
            
        elif action == NotionActionTypes.CREATE_DATABASE_ENTRY:
            entities['database_id'] = self.utility_handlers.extract_database_id_from_query(query)
            entities['properties'] = self.creation_handlers._extract_properties_from_query(query)
            
        elif action == NotionActionTypes.CROSS_PLATFORM_SYNTHESIS:
            entities['query'] = self.utility_handlers.extract_search_query(query)
            entities['databases'] = []  # Would be extracted from query
        
        return entities
    
    def _calculate_confidence(self, query: str, action: str, entities: Dict[str, Any]) -> float:
        """Calculate confidence score for the parsing result"""
        confidence = 0.5  # Base confidence
        
        # Increase confidence if action is explicit
        explicit_actions = ['create_page', 'update_page', 'search', 'query_database']
        if action in explicit_actions:
            confidence += 0.2
        
        # Increase confidence if entities were extracted
        if entities:
            confidence += 0.2
        
        # Increase confidence if query contains Notion keywords
        query_lower = query.lower()
        notion_keywords = ['notion', 'page', 'database', 'notion page', 'notion database']
        if any(keyword in query_lower for keyword in notion_keywords):
            confidence += 0.1
        
        return min(1.0, confidence)
    
    def _generate_metadata(self, query: str, action: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Generate metadata for the parsing result"""
        return {
            'action': action,
            'entities': entities,
            'query': query,
            'parser': 'notion_parser'
        }
    
    def parse_query(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """
        Parse Notion-related query with enhanced NLU approach
        
        Uses multiple approaches for robust intent detection:
        1. LLM-powered classification (primary)
        2. Semantic pattern matching (secondary)
        3. Pattern-based fallback (tertiary)
        
        Args:
            query: User query
            tool: Notion tool
            user_id: User ID (optional)
            session_id: Session ID (optional)
            
        Returns:
            Conversational Notion response
        """
        logger.info(f"[NOTION] Processing query: {query}")
        
        try:
            # Store session info for potential feedback learning
            self.current_session = {
                "user_id": user_id,
                "session_id": session_id,
                "query": query,
                "timestamp": datetime.now()
            }
            
            # Step 1: Detect action
            action = self.classification_handlers.detect_notion_action(query)
            logger.info(f"[NOTION] Detected action: {action}")
            
            # Step 2: Try LLM Classification (Primary approach)
            classification = self.classification_handlers.classify_notion_query(query)
            
            if classification:
                validated_classification = self._validate_classification(query, action, classification)
                
                if validated_classification:
                    logger.info(f"[NOTION] Using LLM classification: {validated_classification}")
                    result = self.query_processing_handlers.execute_notion_with_classification(
                        tool, query, validated_classification, action
                    )
                    
                    # Learn from this interaction
                    self.learning_system.record_classification_result(
                        query=query,
                        predicted_action=action,
                        llm_classification=validated_classification,
                        success=not result.startswith("Error")
                    )
                    
                    return result
            
            # Step 3: Fallback to pattern-based execution
            logger.info("[NOTION] Using pattern-based execution")
            return self._execute_action_by_pattern(tool, query, action)
            
        except Exception as e:
            logger.error(f"[NOTION] Notion query parsing failed: {e}", exc_info=True)
            return f"[ERROR] Failed to process Notion query: {str(e)}"
    
    def _validate_classification(self, query: str, action: str, classification: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate LLM classification result"""
        classified_action = classification.get('action')
        
        # Validate action matches detected action
        if classified_action and classified_action == action:
            return classification
        
        # If actions don't match, prefer the detected action but use entities from classification
        if classified_action:
            classification['action'] = action
            logger.warning(f"[NOTION] Action mismatch: detected={action}, classified={classified_action}, using detected")
        
        return classification
    
    def _execute_action_by_pattern(self, tool: BaseTool, query: str, action: str) -> str:
        """
        Execute Notion action using pattern-based routing
        
        Routes to appropriate handler based on action type.
        """
        try:
            if action == NotionActionTypes.CREATE_PAGE:
                return self.creation_handlers.parse_and_create_page(tool, query)
            elif action == NotionActionTypes.UPDATE_PAGE:
                return self.management_handlers.parse_and_update_page(tool, query)
            elif action == NotionActionTypes.SEARCH:
                return self.management_handlers.handle_search_action(tool, query)
            elif action == NotionActionTypes.GET_PAGE:
                return self.action_handlers.handle_get_page_action(tool, query)
            elif action == NotionActionTypes.QUERY_DATABASE:
                return self.management_handlers.handle_query_database_action(tool, query)
            elif action == NotionActionTypes.CREATE_DATABASE_ENTRY:
                return self.creation_handlers.parse_and_create_database_entry(tool, query)
            elif action == NotionActionTypes.CROSS_PLATFORM_SYNTHESIS:
                return self.action_handlers.handle_cross_platform_synthesis_action(tool, query)
            elif action == NotionActionTypes.AUTO_MANAGE_DATABASE:
                return self.action_handlers.handle_auto_manage_database_action(tool, query)
            else:
                logger.warning(f"[NOTION] Unknown action: {action}, defaulting to search")
                return self.management_handlers.handle_search_action(tool, query)
        except Exception as e:
            logger.error(f"[NOTION] Error executing action '{action}': {e}", exc_info=True)
            return f"[ERROR] Failed to execute Notion action: {str(e)}"

