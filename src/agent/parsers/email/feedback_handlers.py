"""
Email Feedback Handlers - Handle learning from user feedback and autonomous improvement
"""
import re
import json
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path

from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Constants for feedback handlers
QUERY_PREVIEW_LENGTH = 50
MIN_FEEDBACK_FOR_ANALYSIS = 10


class EmailFeedbackHandlers:
    """Handles feedback collection, analysis, and autonomous learning for email parsing"""
    
    def __init__(self, email_parser):
        self.email_parser = email_parser
        self.feedback_store = email_parser.feedback_store
        self.feedback_file = email_parser.feedback_file
        self.date_parser = email_parser.date_parser
    
    def learn_from_feedback(self, original_query: str, user_correction: str, result_was_correct: bool = False):
        """
        Learn from user feedback to improve future parsing
        
        Args:
            original_query: The original user query
            user_correction: What the user actually wanted (correction)
            result_was_correct: Whether the original result was correct
        """
        feedback_entry = {
            'original_query': original_query,
            'user_correction': user_correction,
            'result_was_correct': result_was_correct,
            'timestamp': datetime.now().isoformat(),
            'parser_version': 'enhanced_v1.0'
        }
        
        self.feedback_store.append(feedback_entry)
        
        # Save feedback to file for persistence
        self.save_feedback()
        
        logger.info(f"📚 Learned from feedback: original='{original_query[:QUERY_PREVIEW_LENGTH]}...', correction='{user_correction[:QUERY_PREVIEW_LENGTH]}...'")
        
        # Analyze feedback patterns if we have enough data
        if len(self.feedback_store) > MIN_FEEDBACK_FOR_ANALYSIS:
            self.analyze_feedback_patterns()
    
    def save_feedback(self):
        """Save feedback to persistent storage"""
        try:
            # Skip if feedback_file is None
            if not self.feedback_file:
                logger.debug("Feedback file path not set, skipping save")
                return
                
            # Ensure data directory exists
            feedback_path = Path(self.feedback_file)
            feedback_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Load existing feedback
            if feedback_path.exists():
                with open(self.feedback_file, 'r') as f:
                    existing = json.load(f)
            else:
                existing = []
            
            # Append new feedback
            existing.extend(self.feedback_store)
            
            # Save back to file
            with open(self.feedback_file, 'w') as f:
                json.dump(existing, f, indent=2)
            
            logger.debug(f"Saved feedback to {self.feedback_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save feedback: {e}")
    
    def load_feedback(self):
        """Load feedback from persistent storage"""
        try:
            # Skip if feedback_file is None
            if not self.feedback_file:
                logger.debug("Feedback file path not set, skipping load")
                self.feedback_store[:] = []
                return
                
            feedback_path = Path(self.feedback_file)
            if feedback_path.exists():
                with open(self.feedback_file, 'r') as f:
                    self.feedback_store[:] = json.load(f)
                logger.info(f"Loaded {len(self.feedback_store)} feedback entries")
            else:
                logger.debug(f"Feedback file does not exist: {self.feedback_file}")
                self.feedback_store[:] = []
        except Exception as e:
            logger.warning(f"Failed to load feedback: {e}")
            self.feedback_store[:] = []
    
    def analyze_feedback_patterns(self):
        """Analyze feedback patterns to identify common mistakes"""
        try:
            if not self.feedback_store:
                return
            
            # Count mistakes
            mistakes = [f for f in self.feedback_store if not f.get('result_was_correct', True)]
            
            if len(mistakes) < 5:
                return
            
            logger.info(f"Analyzing {len(mistakes)} feedback entries...")
            
            # Group by mistake type
            mistake_patterns = {
                'wrong_intent': [],
                'missing_entities': [],
                'wrong_date': [],
                'wrong_sender': []
            }
            
            for mistake in mistakes:
                original = mistake.get('original_query', '')
                correction = mistake.get('user_correction', '')
                
                # Analyze what went wrong
                if self.is_intent_mismatch(original, correction):
                    mistake_patterns['wrong_intent'].append(mistake)
                elif self.missing_entities(original, correction):
                    mistake_patterns['missing_entities'].append(mistake)
                elif self.date_related_mistake(original, correction):
                    mistake_patterns['wrong_date'].append(mistake)
                elif self.sender_related_mistake(original, correction):
                    mistake_patterns['wrong_sender'].append(mistake)
            
            # Log findings
            for pattern_type, occurrences in mistake_patterns.items():
                if occurrences:
                    logger.info(f"  - {pattern_type}: {len(occurrences)} occurrences")
            
            # Update parsing rules if needed
            self.update_parsing_rules_from_feedback(mistake_patterns)
            
        except Exception as e:
            logger.error(f"Feedback analysis failed: {e}")
    
    def is_intent_mismatch(self, original: str, correction: str) -> bool:
        """Check if intent was misclassified"""
        # Simple heuristic: check if correction mentions different action
        correction_lower = correction.lower()
        original_lower = original.lower()
        
        intent_keywords = {
            'search': ['search', 'find', 'look for'],
            'send': ['send', 'compose', 'write'],
            'list': ['list', 'show', 'display']
        }
        
        # Check if correction indicates different intent
        for intent, keywords in intent_keywords.items():
            if any(kw in correction_lower for kw in keywords) and not any(kw in original_lower for kw in keywords):
                return True
        
        return False
    
    def missing_entities(self, original: str, correction: str) -> bool:
        """Check if entities were missing"""
        # Check if correction adds entities not in original
        # Simple check for added information
        return len(correction) > len(original) * 1.2
    
    def date_related_mistake(self, original: str, correction: str) -> bool:
        """Check if date parsing was wrong"""
        date_keywords = ['date', 'time', 'when', 'yesterday', 'today', 'week', 'month']
        return any(kw in correction.lower() for kw in date_keywords)
    
    def sender_related_mistake(self, original: str, correction: str) -> bool:
        """Check if sender detection was wrong"""
        sender_keywords = ['from', 'sender', 'who', 'email from']
        return any(kw in correction.lower() for kw in sender_keywords)
    
    def update_parsing_rules_from_feedback(self, mistake_patterns: Dict[str, List[Dict]]):
        """
        Autonomous learning: Update parsing rules based on feedback patterns
        
        AUTONOMOUS LEARNING BEHAVIOR:
        - Automatically extracts patterns from user corrections
        - Updates intent classification rules without user intervention
        - Improves entity extraction based on feedback
        - Adapts date parsing rules autonomously
        - Stores learned patterns for future use
        
        This enables the agent to learn and improve autonomously over time.
        """
        try:
            updates_made = []
            
            # 1. Extract patterns for intent misclassification
            if mistake_patterns.get('wrong_intent'):
                logger.info("Learning from intent misclassification patterns...")
                intent_patterns = self.extract_intent_correction_patterns(mistake_patterns['wrong_intent'])
                updates_made.append(f"Intent patterns: {len(intent_patterns)}")
                # Store for future use in classification
                self.email_parser._learned_intent_patterns = getattr(self.email_parser, '_learned_intent_patterns', {})
                self.email_parser._learned_intent_patterns.update(intent_patterns)
            
            # 2. Extract new entity patterns
            if mistake_patterns.get('missing_entities'):
                logger.info("Learning entity extraction patterns...")
                entity_patterns = self.extract_entity_patterns(mistake_patterns['missing_entities'])
                updates_made.append(f"Entity patterns: {len(entity_patterns)}")
                # Store for enhanced entity extraction
                self.email_parser._learned_entity_patterns = getattr(self.email_parser, '_learned_entity_patterns', {})
                self.email_parser._learned_entity_patterns.update(entity_patterns)
            
            # 3. Learn date parsing improvements
            if mistake_patterns.get('wrong_date'):
                logger.info("Learning date parsing improvements...")
                date_expressions = self.extract_date_expressions(mistake_patterns['wrong_date'])
                updates_made.append(f"Date expressions: {len(date_expressions)}")
                # Pass to date parser if available
                if self.date_parser and hasattr(self.date_parser, 'learn_expression'):
                    for expr, date in date_expressions.items():
                        try:
                            self.date_parser.learn_expression(expr, date)
                        except:
                            pass
            
            # 4. Enhance keyword expansion
            if mistake_patterns.get('wrong_sender'):
                logger.info("Learning keyword variations...")
                keyword_map = self.extract_keyword_synonyms(mistake_patterns['wrong_sender'])
                updates_made.append(f"Keyword synonyms: {len(keyword_map)}")
                # Store for query expansion
                self.email_parser._learned_synonyms = getattr(self.email_parser, '_learned_synonyms', {})
                for keyword, synonyms in keyword_map.items():
                    if keyword in self.email_parser._learned_synonyms:
                        self.email_parser._learned_synonyms[keyword].extend(synonyms)
                    else:
                        self.email_parser._learned_synonyms[keyword] = synonyms
            
            if updates_made:
                logger.info(f"Active learning applied: {', '.join(updates_made)}")
                # Save learned patterns to persistent storage
                self.save_learned_patterns()
            else:
                logger.info("No significant patterns to learn from feedback")
            
        except Exception as e:
            logger.error(f"Failed to update parsing rules: {e}")
    
    def extract_intent_correction_patterns(self, mistakes: List[Dict]) -> Dict[str, str]:
        """Extract patterns from intent corrections"""
        patterns = {}
        for mistake in mistakes:
            original = mistake.get('original_query', '').lower()
            correction = mistake.get('user_correction', '').lower()
            
            # Look for word differences
            original_words = set(original.split())
            correction_words = set(correction.split())
            added_words = correction_words - original_words
            
            # If correction adds action words, learn the mapping
            action_intents = {
                'search': ['search', 'find', 'look', 'show'],
                'list': ['list', 'show', 'display', 'get'],
                'send': ['send', 'compose', 'write', 'draft']
            }
            
            for intent, keywords in action_intents.items():
                if any(kw in added_words for kw in keywords):
                    # Learn: original query pattern -> correct intent
                    if original:
                        patterns[original] = intent
        
        return patterns
    
    def extract_entity_patterns(self, mistakes: List[Dict]) -> Dict[str, List[str]]:
        """Extract entity extraction patterns from corrections"""
        patterns = {}
        for mistake in mistakes:
            correction = mistake.get('user_correction', '')
            
            # Look for email addresses in corrections
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails = re.findall(email_pattern, correction)
            
            # Look for names (capitalized words)
            name_pattern = r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b'
            names = re.findall(name_pattern, correction)
            
            # Learn that certain phrases in corrections indicate entities
            if emails or names:
                original = mistake.get('original_query', '').lower()
                for email in emails:
                    # Pattern: when user says "email to [person]", they mean [email]
                    person = email.split('@')[0]
                    patterns[f'person:{person}'] = [email]
        
        return patterns
    
    def extract_date_expressions(self, mistakes: List[Dict]) -> Dict[str, str]:
        """Extract date expression patterns"""
        expressions = {}
        for mistake in mistakes:
            correction = mistake.get('user_correction', '')
            
            # Look for date expressions in corrections
            date_keywords = ['yesterday', 'today', 'tomorrow', 'week', 'month', 'ago']
            if any(kw in correction.lower() for kw in date_keywords):
                # Extract the date expression
                for kw in date_keywords:
                    if kw in correction.lower():
                        expressions[kw] = correction  # Store association
        
        return expressions
    
    def extract_keyword_synonyms(self, mistakes: List[Dict]) -> Dict[str, List[str]]:
        """Extract keyword synonym mappings"""
        synonym_map = {}
        for mistake in mistakes:
            original = mistake.get('original_query', '').lower()
            correction = mistake.get('user_correction', '').lower()
            
            # Find which words were changed/added in correction
            original_words = set(original.split())
            correction_words = set(correction.split())
            added_words = correction_words - original_words
            
            # Learn synonym relationships
            # If correction adds "urgent" when original had "important", learn the link
            if 'urgent' in added_words and 'important' in original_words:
                synonym_map['important'] = ['urgent']
            if 'meeting' in added_words and 'appointment' in original_words:
                synonym_map['appointment'] = ['meeting']
        
        return synonym_map
    
    def save_learned_patterns(self):
        """Save learned patterns to persistent storage"""
        try:
            patterns_file = Path("./data/learned_patterns.json")
            patterns_file.parent.mkdir(parents=True, exist_ok=True)
            
            patterns = {
                'intent_patterns': getattr(self.email_parser, '_learned_intent_patterns', {}),
                'entity_patterns': getattr(self.email_parser, '_learned_entity_patterns', {}),
                'synonyms': getattr(self.email_parser, '_learned_synonyms', {}),
                'timestamp': datetime.now().isoformat()
            }
            
            with open(patterns_file, 'w') as f:
                json.dump(patterns, f, indent=2)
            
            logger.info("Saved learned patterns to ./data/learned_patterns.json")
        except Exception as e:
            logger.warning(f"Failed to save learned patterns: {e}")
    
    def load_learned_patterns(self):
        """Load learned patterns from persistent storage"""
        try:
            patterns_file = Path("./data/learned_patterns.json")
            if patterns_file.exists():
                with open(patterns_file, 'r') as f:
                    patterns = json.load(f)
                
                self.email_parser._learned_intent_patterns = patterns.get('intent_patterns', {})
                self.email_parser._learned_entity_patterns = patterns.get('entity_patterns', {})
                self.email_parser._learned_synonyms = patterns.get('synonyms', {})
                
                logger.info("Loaded learned patterns from feedback")
        except Exception as e:
            logger.debug(f"Could not load learned patterns: {e}")
            self.email_parser._learned_intent_patterns = {}
            self.email_parser._learned_entity_patterns = {}
            self.email_parser._learned_synonyms = {}
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """Get feedback statistics"""
        if not self.feedback_store:
            return {"total_feedback": 0, "message": "No feedback collected yet"}
        
        total = len(self.feedback_store)
        correct = sum(1 for f in self.feedback_store if f.get('result_was_correct', True))
        mistakes = total - correct
        
        return {
            "total_feedback": total,
            "correct_results": correct,
            "mistakes": mistakes,
            "accuracy": round(correct / total * 100, 2) if total > 0 else 0,
            "last_feedback": self.feedback_store[-1]['timestamp'] if self.feedback_store else None
        }
    
    def clear_feedback(self):
        """Clear all feedback (for testing/reset)"""
        self.feedback_store[:] = []
        try:
            feedback_path = Path(self.feedback_file)
            if feedback_path.exists():
                feedback_path.unlink()
                logger.info("Cleared all feedback")
        except Exception as e:
            logger.warning(f"Failed to clear feedback: {e}")
