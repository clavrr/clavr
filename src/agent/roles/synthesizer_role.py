"""
Synthesizer Role: Combine results and format responses

Responsible for:
- Combining results from multiple specialists
- Formatting results for user consumption
- Generating natural language responses
- Handling cross-domain context
- Personalizing responses based on user preferences
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Import enhanced personalization
try:
    from ..capabilities.response_personalizer import ResponsePersonalizer
    HAS_PERSONALIZATION = True
except ImportError:
    HAS_PERSONALIZATION = False


@dataclass
class SynthesizedResponse:
    """Final synthesized response to user"""
    query: str
    response_text: str
    data: Dict[str, Any] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)  # Domains/specialists used
    generation_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class SynthesizerRole:
    """
    Synthesizer Role: Combines results and generates responses
    
    The Synthesizer takes results from Domain Specialists and combines them
    into coherent, natural language responses for the user.
    
    Responsibilities:
    - Merge results from multiple domains
    - Enrich results with context
    - Generate natural language responses
    - Format data for presentation
    - Handle edge cases (empty results, errors, etc.)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize SynthesizerRole
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Initialize response personalizer
        self.personalizer = ResponsePersonalizer(config)
        
        self.stats = {
            'responses_generated': 0,
            'avg_generation_time_ms': 0.0,
            'multi_domain_responses': 0,
            'single_domain_responses': 0,
            'error_responses': 0,
        }
    
    async def synthesize(
        self,
        query: str,
        specialist_results: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None
    ) -> SynthesizedResponse:
        """
        Synthesize a response from specialist results
        
        Args:
            query: Original user query
            specialist_results: Results from domain specialists
                                Format: {domain: SpecialistResult, ...}
            context: Optional additional context
            user_id: Optional user ID for personalization
            
        Returns:
            SynthesizedResponse with formatted response text
        """
        start_time = datetime.now()
        self.stats['responses_generated'] += 1
        
        # Track sources
        sources = [domain for domain, result in specialist_results.items() if result and result.success]
        
        if len(sources) > 1:
            self.stats['multi_domain_responses'] += 1
        elif len(sources) == 1:
            self.stats['single_domain_responses'] += 1
        
        # Check for errors
        error_domains = [domain for domain, result in specialist_results.items() if result and not result.success]
        if error_domains:
            self.stats['error_responses'] += 1
        
        # Combine results
        combined_data = self._combine_results(specialist_results)
        
        # Generate response text
        response_text = self._generate_response_text(
            query=query,
            combined_data=combined_data,
            error_domains=error_domains,
            context=context
        )
        
        # Apply personalization if available
        if self.personalizer and user_id:
            personalized = await self.personalizer.personalize_response(
                response_text=response_text,
                response_data=combined_data,
                user_id=user_id,
                query=query,
                sources=sources
            )
            response_text = personalized.formatted_response
        
        generation_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return SynthesizedResponse(
            query=query,
            response_text=response_text,
            data=combined_data,
            sources=sources,
            generation_time_ms=generation_time
        )
    
    def _combine_results(self, specialist_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Combine results from multiple specialists
        
        Args:
            specialist_results: Results from each specialist
            
        Returns:
            Combined data dictionary
        """
        combined = {
            'email': None,
            'calendar': None,
            'tasks': None,
            'combined_insights': []
        }
        
        for domain, result in specialist_results.items():
            if result and result.success:
                combined[domain] = result.data
                
                # Extract insights
                if domain == 'email' and 'count' in result.data:
                    combined['combined_insights'].append(
                        f"Found {result.data['count']} emails"
                    )
                elif domain == 'calendar' and 'count' in result.data:
                    combined['combined_insights'].append(
                        f"Found {result.data['count']} events"
                    )
                elif domain == 'tasks' and 'count' in result.data:
                    combined['combined_insights'].append(
                        f"Found {result.data['count']} tasks"
                    )
        
        return combined
    
    def _generate_response_text(
        self,
        query: str,
        combined_data: Dict[str, Any],
        error_domains: List[str],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate natural language response
        
        Args:
            query: Original query
            combined_data: Combined data from specialists
            error_domains: Domains that had errors
            context: Optional context
            
        Returns:
            Natural language response
        """
        lines = []
        
        # CRITICAL: Check if query is explicitly about a specific domain
        # If so, only include results from that domain (don't mix domains)
        query_lower = query.lower()
        
        # Check for email-only queries
        is_email_only_query = any(
            keyword in query_lower for keyword in [
                'email', 'emails', 'message', 'messages', 'inbox', 'mail',
                'tell me about', 'what is', 'what was', 'what does', 'summarize',
                'when was', 'how much', 'last email', 'last message',
                'amazon', 'vercel', 'spotify', 'purchase', 'receipt', 'invoice', 'payment'
            ]
        ) and not any(
            keyword in query_lower for keyword in ['calendar', 'task', 'meeting', 'event', 'schedule']
        )
        
        # Check for calendar-only queries
        is_calendar_only_query = any(
            keyword in query_lower for keyword in [
                'calendar', 'meeting', 'meetings', 'event', 'events', 'appointment', 'schedule'
            ]
        ) and not any(
            keyword in query_lower for keyword in ['email', 'task', 'message']
        )
        
        # Check for task-only queries
        is_task_only_query = any(
            keyword in query_lower for keyword in [
                'task', 'tasks', 'todo', 'todos', 'reminder', 'deadline'
            ]
        ) and not any(
            keyword in query_lower for keyword in ['email', 'calendar', 'meeting', 'event']
        )
        
        # Handle errors first
        if error_domains:
            lines.append(f"I encountered issues with: {', '.join(error_domains)}")
            lines.append("")
        
        # Add context information if provided
        if context:
            # Add contextual insights if available
            if context.get('previous_query'):
                lines.append(f"Following up on: {context['previous_query'][:50]}...")
                lines.append("")
            if context.get('user_preferences'):
                # Context about user preferences can inform response style
                pass  # Preferences are handled by personalizer
            if context.get('related_items'):
                related_count = len(context.get('related_items', []))
                if related_count > 0:
                    lines.append(f"Found {related_count} related item(s) in context.")
                    lines.append("")
        
        # Check if any domain has a string result (formatted response from tool)
        # If so, use it directly instead of trying to extract structured data
        string_results = []
        domains_to_check = []
        
        # CRITICAL: Only check domains relevant to the query
        if is_email_only_query:
            domains_to_check = ['email']
        elif is_calendar_only_query:
            domains_to_check = ['calendar']
        elif is_task_only_query:
            domains_to_check = ['tasks']
        else:
            # Multi-domain query - check all domains
            domains_to_check = ['email', 'calendar', 'tasks']
        
        for domain in domains_to_check:
            result = combined_data.get(domain)
            if result and isinstance(result, str) and result.strip():
                string_results.append(result.strip())
        
        # If we have string results, use them directly (tools already formatted them)
        if string_results:
            # For single-domain queries, return only that domain's result
            if len(string_results) == 1 and (is_email_only_query or is_calendar_only_query or is_task_only_query):
                return string_results[0]
            # For multi-domain queries, join with newlines
            return "\n\n".join(string_results)
        
        # CRITICAL: Only add insights and results for domains relevant to the query
        # For email-only queries, don't include calendar/tasks insights
        if not is_email_only_query and not is_calendar_only_query and not is_task_only_query:
            # Add insights only for multi-domain queries
            if combined_data['combined_insights']:
                lines.extend(combined_data['combined_insights'])
                lines.append("")
        
        # Email-specific responses (structured data)
        # CRITICAL: Only include email results if query is about emails OR it's a multi-domain query
        if (is_email_only_query or not (is_calendar_only_query or is_task_only_query)):
            if combined_data['email'] and isinstance(combined_data['email'], dict):
                if combined_data['email'].get('count', 0) > 0:
                    emails = combined_data['email'].get('emails', [])
                    if emails:
                        lines.append("Emails:")
                        for i, email in enumerate(emails[:5], 1):  # Show top 5
                            lines.append(f"  {i}. {email.get('subject', 'No subject')}")
                        if len(emails) > 5:
                            lines.append(f"  ... and {len(emails) - 5} more")
                        lines.append("")
        
        # Calendar-specific responses (structured data)
        # CRITICAL: Only include calendar results if query is about calendar OR it's a multi-domain query
        if (is_calendar_only_query or not (is_email_only_query or is_task_only_query)):
            if combined_data['calendar'] and isinstance(combined_data['calendar'], dict):
                if combined_data['calendar'].get('count', 0) > 0:
                    events = combined_data['calendar'].get('events', [])
                    if events:
                        lines.append("Calendar Events:")
                        for i, event in enumerate(events[:5], 1):  # Show top 5
                            lines.append(f"  {i}. {event.get('summary', 'No title')}")
                        if len(events) > 5:
                            lines.append(f"  ... and {len(events) - 5} more")
                        lines.append("")
        
        # Tasks-specific responses (structured data)
        # CRITICAL: Only include task results if query is about tasks OR it's a multi-domain query
        if (is_task_only_query or not (is_email_only_query or is_calendar_only_query)):
            if combined_data['tasks'] and isinstance(combined_data['tasks'], dict):
                if combined_data['tasks'].get('count', 0) > 0:
                    tasks = combined_data['tasks'].get('tasks', [])
                    if tasks:
                        lines.append("Tasks:")
                        for i, task in enumerate(tasks[:5], 1):  # Show top 5
                            lines.append(f"  {i}. {task.get('title', 'No title')}")
                        if len(tasks) > 5:
                            lines.append(f"  ... and {len(tasks) - 5} more")
                        lines.append("")
        
        # Handle case where no data was found
        if not lines:
            lines.append("No results found for your query.")
        
        return "\n".join(lines).strip()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get synthesizer statistics"""
        total_responses = self.stats['responses_generated']
        
        if total_responses > 0:
            multi_pct = (self.stats['multi_domain_responses'] / total_responses) * 100
            error_pct = (self.stats['error_responses'] / total_responses) * 100
        else:
            multi_pct = 0
            error_pct = 0
        
        return {
            'total_responses': total_responses,
            'multi_domain_responses': self.stats['multi_domain_responses'],
            'single_domain_responses': self.stats['single_domain_responses'],
            'multi_domain_percentage': f"{multi_pct:.1f}%",
            'error_responses': self.stats['error_responses'],
            'error_percentage': f"{error_pct:.1f}%",
            'avg_generation_time_ms': f"{self.stats['avg_generation_time_ms']:.0f}ms"
        }
