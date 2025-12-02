"""
Response Personalization Module

Provides response personalization and adaptive formatting for the SynthesizerRole
based on user preferences and interaction patterns.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class ResponseFormat(str, Enum):
    """Response format preferences"""
    CONCISE = "concise"          # Short, to-the-point responses
    DETAILED = "detailed"        # Comprehensive responses with context
    STRUCTURED = "structured"    # Formatted with clear sections
    CONVERSATIONAL = "conversational"  # Natural, friendly tone
    TECHNICAL = "technical"      # Include technical details


class DetailLevel(str, Enum):
    """Detail level for responses"""
    MINIMAL = "minimal"          # Only essential information
    STANDARD = "standard"        # Default level of detail
    COMPREHENSIVE = "comprehensive"  # All available details


@dataclass
class UserPreferences:
    """User's response preferences"""
    user_id: int
    preferred_format: ResponseFormat = ResponseFormat.CONVERSATIONAL  # Default to conversational
    preferred_detail_level: DetailLevel = DetailLevel.STANDARD
    include_timestamps: bool = False
    include_statistics: bool = False
    use_emojis: bool = False
    use_markdown: bool = True
    preferred_language: str = "en"
    max_items_shown: int = 10
    group_by_domain: bool = True
    show_alternatives: bool = True
    include_actions: bool = True
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class PersonalizedResponse:
    """Personalized response for user"""
    user_id: int
    original_query: str
    formatted_response: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    personalization_applied: List[str] = field(default_factory=list)
    engagement_score: float = 0.0


class ResponsePersonalizer:
    """
    Response personalization and adaptive formatting
    
    Provides:
    - User preference learning
    - Adaptive response formatting
    - Context-aware content selection
    - Engagement optimization
    - Multi-language support
    - Accessibility considerations
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize response personalizer"""
        self.config = config or {}
        
        # User preferences storage
        self.user_preferences: Dict[int, UserPreferences] = {}
        self.interaction_history: Dict[int, List[Dict[str, Any]]] = {}
        
        # Format templates
        self.format_templates = self._initialize_templates()
        
        self.stats = {
            'responses_personalized': 0,
            'users_profiled': 0,
            'avg_engagement_score': 0.0,
        }
    
    async def personalize_response(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        user_id: int,
        query: str,
        sources: Optional[List[str]] = None
    ) -> PersonalizedResponse:
        """
        Personalize a response for a specific user
        
        Args:
            response_text: Original response text
            response_data: Response data
            user_id: User ID
            query: Original query
            sources: Data sources used
            
        Returns:
            PersonalizedResponse with formatted response
        """
        self.stats['responses_personalized'] += 1
        
        # Get or create user preferences
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = UserPreferences(user_id=user_id)
            self.stats['users_profiled'] += 1
        
        preferences = self.user_preferences[user_id]
        
        # Apply personalizations
        personalization_applied = []
        
        # Format adaptation
        formatted_response = self._apply_format(
            response_text, response_data, preferences
        )
        personalization_applied.append(f"format:{preferences.preferred_format.value}")
        
        # Detail level adaptation
        formatted_response = self._adjust_detail_level(
            formatted_response, response_data, preferences
        )
        personalization_applied.append(f"detail:{preferences.preferred_detail_level.value}")
        
        # Domain grouping
        if preferences.group_by_domain and response_data:
            formatted_response = self._group_by_domain(
                formatted_response, response_data
            )
            personalization_applied.append("grouped_by_domain")
        
        # Add enhancements
        if preferences.include_actions:
            formatted_response = self._add_suggested_actions(
                formatted_response, response_data, query
            )
            personalization_applied.append("suggested_actions_added")
        
        # Calculate engagement score
        engagement_score = self._calculate_engagement_score(
            formatted_response, preferences, response_data
        )
        
        # Store interaction
        self._store_interaction(user_id, query, formatted_response, response_data)
        
        return PersonalizedResponse(
            user_id=user_id,
            original_query=query,
            formatted_response=formatted_response,
            metadata={
                'sources': sources or [],
                'preferences_applied': preferences.preferred_format.value,
                'detail_level': preferences.preferred_detail_level.value
            },
            personalization_applied=personalization_applied,
            engagement_score=engagement_score
        )
    
    async def learn_preferences(
        self,
        user_id: int,
        interaction_data: Dict[str, Any]
    ) -> None:
        """
        Learn user preferences from interactions
        
        Args:
            user_id: User ID
            interaction_data: Interaction data including feedback
        """
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = UserPreferences(user_id=user_id)
        
        preferences = self.user_preferences[user_id]
        
        # Update based on feedback
        if 'feedback' in interaction_data:
            feedback = interaction_data['feedback']
            
            if 'too_long' in feedback:
                preferences.preferred_detail_level = DetailLevel.MINIMAL
            elif 'too_short' in feedback:
                preferences.preferred_detail_level = DetailLevel.COMPREHENSIVE
            
            if 'needs_structure' in feedback:
                preferences.preferred_format = ResponseFormat.STRUCTURED
            elif 'too_formal' in feedback:
                preferences.preferred_format = ResponseFormat.CONVERSATIONAL
        
        # Update based on response time
        if 'response_time_ms' in interaction_data:
            resp_time = interaction_data['response_time_ms']
            if resp_time > 2000:  # >2 seconds
                preferences.preferred_detail_level = DetailLevel.MINIMAL
        
        preferences.updated_at = datetime.now()
    
    def _apply_format(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Apply format preference"""
        template = self.format_templates.get(preferences.preferred_format.value)
        
        if not template:
            return response_text
        
        # Apply template
        formatted = template(response_text, response_data, preferences)
        return formatted
    
    def _format_concise(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Format as concise response"""
        lines = response_text.strip().split('\n')
        
        # Take only first few lines
        concise_lines = []
        for line in lines[:3]:
            if line.strip():
                concise_lines.append(line)
        
        return '\n'.join(concise_lines)
    
    def _format_detailed(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Format as detailed response"""
        lines = [response_text]
        
        # Add metadata
        if preferences.include_timestamps:
            lines.append(f"\n_Timestamp: {datetime.now().isoformat()}_")
        
        if preferences.include_statistics and response_data:
            lines.append("\n**Statistics:**")
            for key, value in response_data.items():
                if key not in ['email', 'calendar', 'tasks', 'combined_insights']:
                    lines.append(f"- {key}: {value}")
        
        return '\n'.join(lines)
    
    def _format_structured(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Format as structured response with sections"""
        sections = []
        
        sections.append("## Response\n")
        sections.append(response_text)
        
        if response_data:
            sections.append("\n## Data Summary\n")
            
            for domain, data in response_data.items():
                if data and isinstance(data, dict):
                    sections.append(f"**{domain.capitalize()}:**")
                    if 'count' in data:
                        sections.append(f"- Found: {data['count']}")
                    if 'items' in data:
                        sections.append(f"- Items: {len(data['items'])}")
        
        return '\n'.join(sections)
    
    def _format_conversational(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Format as conversational response"""
        # Add friendly opening/closing
        formatted = f"Here's what I found:\n\n{response_text}"
        
        # Add brief summary if response_data is available
        if response_data:
            summary_parts = []
            if response_data.get('email') and response_data['email'].get('count', 0) > 0:
                summary_parts.append(f"{response_data['email']['count']} email(s)")
            if response_data.get('calendar') and response_data['calendar'].get('count', 0) > 0:
                summary_parts.append(f"{response_data['calendar']['count']} event(s)")
            if response_data.get('tasks') and response_data['tasks'].get('count', 0) > 0:
                summary_parts.append(f"{response_data['tasks']['count']} task(s)")
            
            if summary_parts:
                formatted += f"\n\nFound: {', '.join(summary_parts)}"
        
        # Apply emojis if user prefers them
        if preferences.use_emojis:
            formatted = self._add_emojis(formatted)
        
        # Add timestamp if requested
        if preferences.include_timestamps:
            formatted += f"\n\n_Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
        
        return formatted
    
    def _format_technical(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Format as technical response"""
        lines = [response_text]
        
        if response_data:
            lines.append("\n**Technical Details:**")
            lines.append("```")
            
            import json
            # Adjust detail level based on preferences
            if preferences.preferred_detail_level == DetailLevel.MINIMAL:
                # Only include essential fields
                minimal_data = {}
                for key, value in response_data.items():
                    if isinstance(value, dict):
                        minimal_data[key] = {k: v for k, v in value.items() if k in ['count', 'id', 'status']}
                    else:
                        minimal_data[key] = value
                lines.append(json.dumps(minimal_data, indent=2, default=str))
            else:
                lines.append(json.dumps(response_data, indent=2, default=str))
            
            lines.append("```")
        
        # Add statistics if requested
        if preferences.include_statistics and response_data:
            lines.append("\n**Statistics:**")
            stats = []
            if response_data.get('email') and response_data['email'].get('count', 0) > 0:
                stats.append(f"Emails: {response_data['email']['count']}")
            if response_data.get('calendar') and response_data['calendar'].get('count', 0) > 0:
                stats.append(f"Events: {response_data['calendar']['count']}")
            if response_data.get('tasks') and response_data['tasks'].get('count', 0) > 0:
                stats.append(f"Tasks: {response_data['tasks']['count']}")
            if stats:
                lines.append(" | ".join(stats))
        
        # Add timestamp if requested
        if preferences.include_timestamps:
            lines.append(f"\n_Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
        
        return '\n'.join(lines)
    
    def _adjust_detail_level(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        preferences: UserPreferences
    ) -> str:
        """Adjust detail level in response"""
        if preferences.preferred_detail_level == DetailLevel.MINIMAL:
            # Remove explanations, keep only results
            lines = response_text.split('\n')
            filtered = [l for l in lines if not any(
                word in l.lower() for word in ['found', 'based on', 'due to', 'because']
            )]
            return '\n'.join(filtered) if filtered else response_text
        
        elif preferences.preferred_detail_level == DetailLevel.COMPREHENSIVE:
            # Add more context and explanations
            return self._expand_with_context(response_text, response_data)
        
        else:  # STANDARD
            return response_text
    
    def _group_by_domain(
        self,
        response_text: str,
        response_data: Dict[str, Any]
    ) -> str:
        """Group results by domain"""
        if not response_data:
            return response_text
        
        sections = []
        
        for domain in ['email', 'calendar', 'tasks']:
            if response_data.get(domain):
                sections.append(f"\n**{domain.upper()}**")
                # Add domain-specific content
                domain_data = response_data[domain]
                if isinstance(domain_data, dict):
                    if domain_data.get('count'):
                        sections.append(f"Found {domain_data['count']} items")
                    if domain_data.get('items'):
                        for item in domain_data['items'][:5]:
                            sections.append(f"- {item}")
        
        return '\n'.join(sections) if sections else response_text
    
    def _add_suggested_actions(
        self,
        response_text: str,
        response_data: Dict[str, Any],
        query: str
    ) -> str:
        """Add suggested follow-up actions"""
        actions = []
        
        if response_data.get('email') and response_data['email'].get('count', 0) > 0:
            actions.append("📧 Reply to emails")
            actions.append("📧 Archive emails")
        
        if response_data.get('calendar') and response_data['calendar'].get('count', 0) > 0:
            actions.append("📅 Update calendar")
            actions.append("📅 Add reminder")
        
        if response_data.get('tasks') and response_data['tasks'].get('count', 0) > 0:
            actions.append("✓ Mark tasks complete")
            actions.append("✓ Reschedule tasks")
        
        if actions:
            response_text += "\n\n**Quick actions:**\n"
            for action in actions[:3]:
                response_text += f"- {action}\n"
        
        return response_text
    
    def _expand_with_context(
        self,
        response_text: str,
        response_data: Dict[str, Any]
    ) -> str:
        """Expand response with additional context"""
        lines = [response_text]
        
        lines.append("\n**Context & Insights:**")
        
        if response_data.get('email'):
            lines.append(f"- {response_data['email'].get('count', 0)} emails found in your mailbox")
        
        if response_data.get('calendar'):
            lines.append(f"- {response_data['calendar'].get('count', 0)} events in your calendar")
        
        if response_data.get('tasks'):
            lines.append(f"- {response_data['tasks'].get('count', 0)} tasks to manage")
        
        return '\n'.join(lines)
    
    def _add_emojis(self, text: str) -> str:
        """Add emojis to text"""
        replacements = {
            'email': '📧',
            'calendar': '📅',
            'task': '✓',
            'meeting': '👥',
            'reminder': '🔔',
            'urgent': '⚠️',
            'important': '⭐',
            'error': '❌',
            'success': '✅',
        }
        
        for word, emoji in replacements.items():
            if word in text.lower():
                # Case-insensitive replacement
                import re
                text = re.sub(f'(?i)\\b{word}\\b', f'{emoji} {word}', text)
        
        return text
    
    def _calculate_engagement_score(
        self,
        response_text: str,
        preferences: UserPreferences,
        response_data: Dict[str, Any]
    ) -> float:
        """Calculate engagement score for response"""
        score = 0.5  # Base score
        
        # Length appropriateness
        text_length = len(response_text)
        if preferences.preferred_detail_level == DetailLevel.MINIMAL and text_length < 100:
            score += 0.2
        elif preferences.preferred_detail_level == DetailLevel.COMPREHENSIVE and text_length > 300:
            score += 0.15
        elif preferences.preferred_detail_level == DetailLevel.STANDARD and 100 <= text_length <= 300:
            score += 0.15
        
        # Format appropriateness
        if preferences.preferred_format == ResponseFormat.STRUCTURED and '**' in response_text:
            score += 0.1
        elif preferences.preferred_format == ResponseFormat.CONVERSATIONAL:
            score += 0.05
        
        # Data richness
        if response_data:
            source_count = sum(1 for v in response_data.values() if v)
            score += min(source_count * 0.1, 0.2)
        
        return min(score, 1.0)
    
    def _store_interaction(
        self,
        user_id: int,
        query: str,
        response: str,
        response_data: Dict[str, Any]
    ) -> None:
        """Store interaction for learning"""
        if user_id not in self.interaction_history:
            self.interaction_history[user_id] = []
        
        self.interaction_history[user_id].append({
            'query': query,
            'response': response,
            'response_data': response_data,
            'timestamp': datetime.now()
        })
        
        # Keep only last 100 interactions
        if len(self.interaction_history[user_id]) > 100:
            self.interaction_history[user_id] = self.interaction_history[user_id][-100:]
    
    def _initialize_templates(self) -> Dict[str, Any]:
        """Initialize format templates"""
        return {
            'concise': self._format_concise,
            'detailed': self._format_detailed,
            'structured': self._format_structured,
            'conversational': self._format_conversational,
            'technical': self._format_technical,
        }
    
    def set_user_preferences(
        self,
        user_id: int,
        preferences: Dict[str, Any]
    ) -> None:
        """Set explicit user preferences"""
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = UserPreferences(user_id=user_id)
        
        prefs = self.user_preferences[user_id]
        
        if 'format' in preferences:
            try:
                prefs.preferred_format = ResponseFormat(preferences['format'])
            except ValueError:
                pass
        
        if 'detail_level' in preferences:
            try:
                prefs.preferred_detail_level = DetailLevel(preferences['detail_level'])
            except ValueError:
                pass
        
        if 'include_timestamps' in preferences:
            prefs.include_timestamps = preferences['include_timestamps']
        
        if 'include_statistics' in preferences:
            prefs.include_statistics = preferences['include_statistics']
        
        if 'use_emojis' in preferences:
            prefs.use_emojis = preferences['use_emojis']
        
        if 'max_items_shown' in preferences:
            prefs.max_items_shown = preferences['max_items_shown']
        
        if 'group_by_domain' in preferences:
            prefs.group_by_domain = preferences['group_by_domain']
        
        prefs.updated_at = datetime.now()
    
    def get_user_preferences(self, user_id: int) -> Optional[UserPreferences]:
        """Get user preferences"""
        return self.user_preferences.get(user_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get personalization statistics"""
        return {
            'responses_personalized': self.stats['responses_personalized'],
            'users_profiled': self.stats['users_profiled'],
            'avg_engagement_score': f"{self.stats['avg_engagement_score']:.2f}",
            'total_interactions_tracked': sum(
                len(h) for h in self.interaction_history.values()
            )
        }
