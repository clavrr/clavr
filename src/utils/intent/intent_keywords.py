"""
Intent Keywords Loader
Loads keyword configurations from YAML files
"""
import os
from pathlib import Path
from typing import Dict, List, Set, Optional
import yaml

from ..logger import setup_logger

logger = setup_logger(__name__)


class IntentKeywords:
    """
    Container for intent detection keywords
    
    Loads keywords from YAML configuration and provides
    efficient lookup methods.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize keyword loader
        
        Args:
            config_path: Path to intent keywords YAML file
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Default to config/intent_keywords.yaml
            project_root = Path(__file__).parent.parent.parent
            self.config_path = project_root / 'config' / 'intent_keywords.yaml'
        
        self.email_actions: Set[str] = set()
        self.general_actions: Set[str] = set()
        self.calendar_keywords: Set[str] = set()
        self.task_keywords: Set[str] = set()
        self.recipient_keywords: Set[str] = set()
        self.time_keywords: Set[str] = set()
        self.priority_keywords: Set[str] = set()
        self.search_keywords: Set[str] = set()
        
        self._load_keywords()
    
    def _load_keywords(self):
        """Load keywords from YAML configuration"""
        try:
            if not self.config_path.exists():
                logger.warning(f"Keywords config not found: {self.config_path}")
                self._use_fallback_keywords()
                return
            
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            if not config:
                logger.warning("Empty keywords config, using fallback")
                self._use_fallback_keywords()
                return
            
            # Load each category
            self.email_actions = set(config.get('email_actions', []))
            self.general_actions = set(config.get('general_actions', []))
            self.calendar_keywords = set(config.get('calendar_keywords', []))
            self.task_keywords = set(config.get('task_keywords', []))
            self.recipient_keywords = set(config.get('recipient_keywords', []))
            self.time_keywords = set(config.get('time_keywords', []))
            self.priority_keywords = set(config.get('priority_keywords', []))
            self.search_keywords = set(config.get('search_keywords', []))
            
            logger.info(f"Loaded {self._total_keywords()} keywords from {self.config_path}")
            
        except Exception as e:
            logger.error(f"Failed to load keywords config: {e}")
            self._use_fallback_keywords()
    
    def _use_fallback_keywords(self):
        """Use minimal fallback keywords if config fails to load"""
        logger.info("Using fallback keywords")
        
        self.email_actions = {
            'send email', 'compose email', 'write email', 'draft email',
            'reply', 'forward', 'email', 'show emails', 'my emails'
        }
        
        self.general_actions = {
            'schedule', 'create', 'add', 'book', 'delete', 'update',
            'show', 'list', 'find', 'search'
        }
        
        self.calendar_keywords = {
            'calendar', 'meeting', 'event', 'appointment', 'schedule',
            'free time', 'available', 'conflict'
        }
        
        self.task_keywords = {
            'task', 'tasks', 'todo', 'reminder', 'deadline', 'due'
        }
    
    def _total_keywords(self) -> int:
        """Get total number of keywords loaded"""
        return (
            len(self.email_actions) +
            len(self.general_actions) +
            len(self.calendar_keywords) +
            len(self.task_keywords) +
            len(self.recipient_keywords) +
            len(self.time_keywords) +
            len(self.priority_keywords) +
            len(self.search_keywords)
        )
    
    def has_email_action_keyword(self, text: str) -> bool:
        """Check if text contains email action keywords"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.email_actions)
    
    def has_general_action_keyword(self, text: str) -> bool:
        """Check if text contains general action keywords"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.general_actions)
    
    def has_calendar_keyword(self, text: str) -> bool:
        """Check if text contains calendar keywords"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.calendar_keywords)
    
    def has_task_keyword(self, text: str) -> bool:
        """Check if text contains task keywords"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.task_keywords)
    
    def has_priority_keyword(self, text: str) -> bool:
        """Check if text contains priority keywords"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.priority_keywords)
    
    def get_matched_keywords(self, text: str, category: Optional[str] = None) -> List[str]:
        """
        Get all keywords that match in the text
        
        Args:
            text: Text to search
            category: Optional category to limit search (email_actions, general_actions, etc.)
            
        Returns:
            List of matched keywords
        """
        text_lower = text.lower()
        matched = []
        
        categories = {
            'email_actions': self.email_actions,
            'general_actions': self.general_actions,
            'calendar_keywords': self.calendar_keywords,
            'task_keywords': self.task_keywords,
            'recipient_keywords': self.recipient_keywords,
            'time_keywords': self.time_keywords,
            'priority_keywords': self.priority_keywords,
            'search_keywords': self.search_keywords,
        }
        
        if category:
            # Search only in specified category
            keyword_set = categories.get(category, set())
            matched = [kw for kw in keyword_set if kw in text_lower]
        else:
            # Search in all categories
            for keyword_set in categories.values():
                matched.extend([kw for kw in keyword_set if kw in text_lower])
        
        return matched
    
    def get_all_keywords(self, category: Optional[str] = None) -> List[str]:
        """
        Get all keywords (optionally filtered by category)
        
        Args:
            category: Optional category name
            
        Returns:
            List of keywords
        """
        if category == 'email_actions':
            return list(self.email_actions)
        elif category == 'general_actions':
            return list(self.general_actions)
        elif category == 'calendar_keywords':
            return list(self.calendar_keywords)
        elif category == 'task_keywords':
            return list(self.task_keywords)
        elif category == 'recipient_keywords':
            return list(self.recipient_keywords)
        elif category == 'time_keywords':
            return list(self.time_keywords)
        elif category == 'priority_keywords':
            return list(self.priority_keywords)
        elif category == 'search_keywords':
            return list(self.search_keywords)
        else:
            # Return all keywords
            all_kw = set()
            all_kw.update(self.email_actions)
            all_kw.update(self.general_actions)
            all_kw.update(self.calendar_keywords)
            all_kw.update(self.task_keywords)
            all_kw.update(self.recipient_keywords)
            all_kw.update(self.time_keywords)
            all_kw.update(self.priority_keywords)
            all_kw.update(self.search_keywords)
            return list(all_kw)


# Global instance (lazy-loaded)
_keywords_instance: Optional[IntentKeywords] = None


def get_intent_keywords() -> IntentKeywords:
    """
    Get the global IntentKeywords instance (singleton)
    
    Returns:
        IntentKeywords instance
    """
    global _keywords_instance
    
    if _keywords_instance is None:
        _keywords_instance = IntentKeywords()
    
    return _keywords_instance


def load_intent_keywords(config_path: Optional[str] = None) -> IntentKeywords:
    """
    Load intent keywords from configuration
    
    Args:
        config_path: Optional path to keywords config file
        
    Returns:
        IntentKeywords instance
    """
    global _keywords_instance
    
    _keywords_instance = IntentKeywords(config_path)
    return _keywords_instance
