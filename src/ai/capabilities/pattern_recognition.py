"""
Pattern Recognition Capability

Detects recurring user patterns and habits to enable proactive assistance.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import Counter

# Use shared logger
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class PatternRecognition:
    """
    Analyzes historical data to find patterns in user behavior.
    """
    
    def __init__(self):
        self.user_patterns = {}
        # Simple in-memory storage for now
        self.history = [] 
        
    def analyze_behavior(self, user_id: int, action_type: str, context: Dict[str, Any]):
        """Record and analyze a user action"""
        entry = {
            'user_id': user_id,
            'type': action_type,
            'context': context,
            'timestamp': datetime.now(),
            'hour': datetime.now().hour,
            'weekday': datetime.now().weekday()
        }
        self.history.append(entry)
        
        # Trigger update if enough data
        if len(self.history) % 10 == 0:
            self._update_patterns(user_id)
            
    def _update_patterns(self, user_id: int):
        """Update learned patterns for user"""
        user_history = [h for h in self.history if h['user_id'] == user_id]
        if not user_history:
            return
            
        patterns = {}
        
        # 1. Preferred times for checking email
        email_checks = [h['hour'] for h in user_history if h['type'] == 'check_email']
        if email_checks:
            common_hour = Counter(email_checks).most_common(1)[0][0]
            patterns['preferred_email_hour'] = common_hour
            
        # 2. Frequent collaborators
        collaborators = []
        for h in user_history:
            if h.get('context', {}).get('person'):
                collaborators.append(h['context']['person'])
        
        if collaborators:
            top_person = Counter(collaborators).most_common(1)[0][0]
            patterns['top_collaborator'] = top_person
            
        self.user_patterns[user_id] = patterns
        logger.info(f"Updated patterns for user {user_id}: {patterns}")
        
    def get_active_patterns(self, user_id: int) -> Dict[str, Any]:
        """Get currently detected patterns"""
        return self.user_patterns.get(user_id, {})
    
    def suggest_proactive_actions(self, user_id: int) -> List[str]:
        """Suggest actions based on context and patterns"""
        patterns = self.get_active_patterns(user_id)
        suggestions = []
        
        current_hour = datetime.now().hour
        
        if 'preferred_email_hour' in patterns:
            pref = patterns['preferred_email_hour']
            if current_hour == pref:
                suggestions.append("Would you like to check your emails now? (It's your usual time)")
                
        if 'top_collaborator' in patterns:
            pass # functional placeholder for future logic
            
        return suggestions
