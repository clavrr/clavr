"""
Domain Validator - Validates routing decisions to prevent misrouting

This module provides a validation layer to ensure queries are routed to the
correct domain (email, task, calendar, notion) before execution. It prevents the
critical issue where task queries were being routed to calendar tools and
vice versa.

Key Features:
- Domain detection with confidence scoring (supports EMAIL, TASK, CALENDAR, NOTION)
- Cross-domain query detection
- Routing validation before tool execution
- Misrouting prevention with clear error messages
- Integration with parser confidence scores
- Enhanced detection via AnalyzerRole integration
- Pattern-based fallback when AnalyzerRole unavailable

Architecture:
    Orchestrator → DomainValidator → ExecutionPlanner → Tool
    CrossDomainHandler → DomainValidator → Domain Detection
    AnalyzerRole → DomainValidator (optional enhancement)

Usage:
    validator = DomainValidator(analyzer_role=analyzer_role)
    validation = validator.validate_routing(query, tool_name, parsed_result)
    if not validation.valid:
        logger.error(f"Invalid routing: {validation.reason}")
"""

import re
from typing import Dict, Any, List, Optional, Tuple

from ....utils.logger import setup_logger
from ..config.domain_validation_config import DomainValidationConfig
from .tool_domain_config import Domain, get_tool_domain_config

# Import keyword lists from intent module and cross_domain_config
from ...intent import TASK_KEYWORDS, CALENDAR_KEYWORDS, EMAIL_KEYWORDS
from ...intent import (
    TASK_QUESTION_PATTERNS,
    TASK_CREATE_PATTERNS,
    TASK_LIST_PATTERNS,
    TASK_ANALYSIS_PATTERNS,
    CALENDAR_QUESTION_PATTERNS,
    CALENDAR_PATTERNS,
    EMAIL_MANAGEMENT_PATTERNS
)
from ..config.cross_domain_config import CrossDomainConfig

logger = setup_logger(__name__)


class ValidationResult:
    """Result of domain validation"""
    
    def __init__(self, valid: bool, confidence: float, reason: str = "",
                 detected_domain: Optional[Domain] = None,
                 target_domain: Optional[Domain] = None,
                 suggestions: Optional[List[str]] = None):
        self.valid = valid
        self.confidence = confidence
        self.reason = reason
        self.detected_domain = detected_domain
        self.target_domain = target_domain
        self.suggestions = suggestions or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/debugging"""
        return {
            'valid': self.valid,
            'confidence': self.confidence,
            'reason': self.reason,
            'detected_domain': self.detected_domain.value if self.detected_domain else None,
            'target_domain': self.target_domain.value if self.target_domain else None,
            'suggestions': self.suggestions
        }


class DomainValidator:
    """
    Validates routing decisions to prevent cross-domain misrouting
    
    Examples of what it prevents:
    - "What tasks do I have today?" → calendar tool (WRONG)
    - "Show my meetings tomorrow" → task tool (WRONG)
    - "Send email to John" → calendar tool (WRONG)
    - "Create a Notion page" → task tool (WRONG)
    
    Examples of what it allows:
    - "What tasks do I have today?" → task tool (CORRECT)
    - "Show my meetings tomorrow" → calendar tool (CORRECT)
    - "Send email to John" → email tool (CORRECT)
    - "Create a Notion page" → Notion tool (CORRECT)
    
    Integration:
    - Can use AnalyzerRole for enhanced domain detection
    - Used by ExecutionPlanner to validate execution steps
    - Used by Orchestrator for routing validation
    - Used by CrossDomainHandler for domain detection
    """
    
    def __init__(
        self,
        strict_mode: bool = True,
        tool_to_domain: Optional[Dict[str, Domain]] = None,
        analyzer_role: Optional[Any] = None
    ):
        """
        Initialize domain validator
        
        Args:
            strict_mode: If True, reject any cross-domain routing.
                        If False, allow with warnings for low confidence.
            tool_to_domain: Optional tool-to-domain mapping. If None, uses ToolDomainConfig.
            analyzer_role: Optional AnalyzerRole instance for enhanced domain detection.
        """
        self.strict_mode = strict_mode
        self.analyzer_role = analyzer_role
        
        # Domain-specific patterns for detection
        self.domain_patterns = self._build_domain_patterns()
        
        # Tool to domain mapping - use provided or get from centralized config
        if tool_to_domain is not None:
            self.tool_to_domain = tool_to_domain
        else:
            # Get mapping from centralized config
            config = get_tool_domain_config()
            self.tool_to_domain = config.get_all_tools()
        
        logger.info(f"[VALIDATOR] DomainValidator initialized (strict_mode={strict_mode}, analyzer_role={'enabled' if analyzer_role else 'disabled'})")
    
    def _build_domain_patterns(self) -> Dict[Domain, Dict[str, Any]]:
        """Build domain-specific pattern matching rules using config values"""
        patterns = {
            Domain.TASK: {
                'keywords': TASK_KEYWORDS,
                'strong_indicators': [
                    r'\btask\b', r'\btasks\b', r'\btodo\b', r'\btodos\b',
                    r'\breminder\b', r'\bdeadline\b',
                    r'due\s+(?:today|tomorrow|this week|next week)',
                    r'overdue', r'pending', r'completed'
                ],
                'question_patterns': TASK_QUESTION_PATTERNS,
                'action_patterns': TASK_CREATE_PATTERNS
            },
            Domain.CALENDAR: {
                'keywords': CALENDAR_KEYWORDS,
                'strong_indicators': [
                    r'\bmeeting\b', r'\bmeetings\b', r'\bevent\b', r'\bevents\b',
                    r'\bappointment\b', r'\bcalendar\b',
                    r'schedule\s+(?:a|an|the)\s+meeting',
                    r'book\s+(?:a|an|the)\s+meeting',
                    r'what.*(?:on my calendar|calendar events)',
                    r'(?:time|when)\s+(?:is|are)\s+(?:my|the)\s+meeting'
                ],
                'question_patterns': CALENDAR_QUESTION_PATTERNS,
                'action_patterns': CALENDAR_PATTERNS
            },
            Domain.EMAIL: {
                'keywords': EMAIL_KEYWORDS,
                'strong_indicators': [
                    r'\bemail\b', r'\bemails\b', r'\bmessage\b', r'\bmessages\b',
                    r'\binbox\b', r'\bunread\b', r'\bsender\b',
                    r'send\s+(?:an?\s+)?email',
                    r'search\s+(?:for\s+)?emails?',
                    r'from\s+\w+@',  # Email address
                    r'urgent\s+(?:emails?|messages?)'
                ],
                'question_patterns': EMAIL_MANAGEMENT_PATTERNS,
                'action_patterns': []
            },
            Domain.NOTION: {
                'keywords': CrossDomainConfig.NOTION_KEYWORDS,
                'strong_indicators': [
                    r'\bnotion\b', r'\bpage\b', r'\bpages\b', r'\bdatabase\b',
                    r'\bdocument\b', r'\bwiki\b',
                    r'create\s+(?:a|an|the)?\s+(?:notion\s+)?(?:page|database)',
                    r'update\s+(?:a|an|the)?\s+(?:notion\s+)?(?:page|database)',
                    r'search\s+(?:in\s+)?notion',
                    r'query\s+(?:notion\s+)?(?:page|database)',
                    r'notion\s+(?:page|database|document)'
                ],
                'question_patterns': [
                    'what notion', 'notion pages', 'notion database',
                    'search notion', 'find in notion', 'notion document'
                ],
                'action_patterns': [
                    'create notion', 'update notion', 'add to notion',
                    'notion page', 'notion database'
                ]
            }
        }
        
        return patterns
    
    async def detect_domain(self, query: str) -> Tuple[Domain, float, Dict[str, Any]]:
        """
        Detect the primary domain of a query with confidence scoring
        
        Uses AnalyzerRole if available for enhanced detection, otherwise falls back
        to pattern-based detection.
        
        Args:
            query: User's natural language query
            
        Returns:
            Tuple of (detected_domain, confidence, details)
            - detected_domain: The detected Domain enum
            - confidence: Float 0.0-1.0 indicating detection confidence
            - details: Dict with detection details (matched_patterns, scores, etc.)
        """
        # Try AnalyzerRole first if available for enhanced detection
        if self.analyzer_role:
            try:
                analysis_result = await self.analyzer_role.analyze(query)
                if analysis_result and analysis_result.domains:
                    # Map analyzer domains to Domain enum
                    detected_domains = []
                    for domain_str in analysis_result.domains:
                        domain_str_lower = domain_str.lower()
                        if domain_str_lower in ['email', 'emails']:
                            detected_domains.append(Domain.EMAIL)
                        elif domain_str_lower in ['task', 'tasks', 'todo', 'todos']:
                            detected_domains.append(Domain.TASK)
                        elif domain_str_lower in ['calendar', 'meeting', 'meetings', 'event', 'events']:
                            detected_domains.append(Domain.CALENDAR)
                        elif domain_str_lower in ['notion', 'page', 'pages', 'database']:
                            detected_domains.append(Domain.NOTION)
                    
                    if detected_domains:
                        # Use primary domain (first one)
                        primary_domain = detected_domains[0]
                        # Use analyzer's confidence if available, otherwise use pattern-based
                        confidence = getattr(analysis_result, 'confidence', 0.8) if hasattr(analysis_result, 'confidence') else 0.8
                        
                        logger.info(f"[VALIDATOR] AnalyzerRole detected domain: {primary_domain.value} (confidence: {confidence:.2f})")
                        
                        return primary_domain, confidence, {
                            'method': 'analyzer_role',
                            'domains': [d.value for d in detected_domains],
                            'intent': getattr(analysis_result, 'intent', None),
                            'entities': getattr(analysis_result, 'entities', {})
                        }
            except Exception as e:
                logger.debug(f"[VALIDATOR] AnalyzerRole detection failed, falling back to patterns: {e}")
        
        # Fallback to pattern-based detection
        query_lower = query.lower()
        
        # Score each domain
        domain_scores = {}
        matched_patterns = {}
        
        for domain, patterns in self.domain_patterns.items():
            score = 0.0
            matches = []
            
            # Check strong indicators (weighted using config)
            for indicator_pattern in patterns['strong_indicators']:
                if re.search(indicator_pattern, query_lower):
                    score += DomainValidationConfig.STRONG_INDICATOR_WEIGHT
                    matches.append(('strong_indicator', indicator_pattern))
            
            # Check keywords (weighted using config)
            for keyword in patterns['keywords']:
                if keyword in query_lower:
                    score += DomainValidationConfig.KEYWORD_WEIGHT
                    matches.append(('keyword', keyword))
            
            # Check question patterns (weighted using config)
            for pattern in patterns.get('question_patterns', []):
                if pattern in query_lower:
                    score += DomainValidationConfig.QUESTION_PATTERN_WEIGHT
                    matches.append(('question_pattern', pattern))
            
            # Check action patterns (weighted using config)
            for pattern in patterns.get('action_patterns', []):
                if pattern in query_lower:
                    score += DomainValidationConfig.ACTION_PATTERN_WEIGHT
                    matches.append(('action_pattern', pattern))
            
            domain_scores[domain] = min(1.0, score)  # Cap at 1.0
            matched_patterns[domain] = matches
        
        # Find domain with highest score
        if not domain_scores:
            return Domain.GENERAL, 0.0, {}
        
        best_domain = max(domain_scores.keys(), key=lambda d: domain_scores[d])
        best_score = domain_scores[best_domain]
        
        # Check if multiple domains have high scores (mixed query)
        high_scoring_domains = [d for d, s in domain_scores.items() if s > DomainValidationConfig.MIXED_DOMAIN_THRESHOLD]
        if len(high_scoring_domains) > 1:
            logger.info(f"[VALIDATOR] Mixed domain query detected: {high_scoring_domains}")
            return Domain.MIXED, DomainValidationConfig.MIXED_DOMAIN_CONFIDENCE, {
                'scores': domain_scores,
                'matched_patterns': matched_patterns,
                'domains': high_scoring_domains
            }
        
        # Return best domain
        details = {
            'method': 'pattern_matching',
            'scores': domain_scores,
            'matched_patterns': matched_patterns[best_domain],
            'all_matches': matched_patterns
        }
        
        logger.info(f"[VALIDATOR] Pattern-based detection: {best_domain.value} (confidence: {best_score:.2f})")
        
        return best_domain, best_score, details
    
    async def validate_routing(
        self,
        query: str,
        tool_name: str,
        parsed_result: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate that a query is being routed to the correct tool domain
        
        Args:
            query: User's natural language query
            tool_name: Name of the tool being routed to
            parsed_result: Optional parser result with action, entities, confidence
            
        Returns:
            ValidationResult with validation status and details
        """
        logger.info(f"[VALIDATOR] Validating routing: '{query}' → {tool_name}")
        
        # Detect query domain
        detected_domain, detection_confidence, detection_details = await self.detect_domain(query)
        
        # Get target domain from tool name
        target_domain = self.tool_to_domain.get(tool_name.lower(), Domain.GENERAL)
        
        # Handle mixed domain queries
        if detected_domain == Domain.MIXED:
            domains = detection_details.get('domains', [])
            if target_domain in domains:
                return ValidationResult(
                    valid=True,
                    confidence=DomainValidationConfig.MIXED_QUERY_MATCH_CONFIDENCE,
                    reason=f"Mixed query, but {target_domain.value} is one of the detected domains",
                    detected_domain=detected_domain,
                    target_domain=target_domain,
                    suggestions=["Consider breaking this into separate queries for better accuracy"]
                )
            else:
                if self.strict_mode:
                    return ValidationResult(
                        valid=False,
                        confidence=DomainValidationConfig.MIXED_QUERY_MISMATCH_CONFIDENCE,
                        reason=f"Mixed query detected domains {[d.value for d in domains]}, but routing to {target_domain.value}",
                        detected_domain=detected_domain,
                        target_domain=target_domain,
                        suggestions=[f"Try routing to one of: {', '.join([d.value for d in domains])}"]
                    )
        
        # Check for exact domain match
        if detected_domain == target_domain:
            # Perfect match - add bonus confidence
            confidence = min(1.0, detection_confidence + DomainValidationConfig.EXACT_MATCH_BONUS)
            
            # If parser result available, incorporate parser confidence
            if parsed_result:
                parser_confidence = parsed_result.get('confidence', 0.0)
                # Weighted average: use config weights
                confidence = (
                    (confidence * DomainValidationConfig.DOMAIN_DETECTION_WEIGHT) + 
                    (parser_confidence * DomainValidationConfig.PARSER_CONFIDENCE_WEIGHT)
                )
            
            return ValidationResult(
                valid=True,
                confidence=confidence,
                reason=f"Query domain ({detected_domain.value}) matches target ({target_domain.value})",
                detected_domain=detected_domain,
                target_domain=target_domain
            )
        
        # Domain mismatch detected
        if detected_domain == Domain.GENERAL:
            # Low confidence domain detection, allow routing
            return ValidationResult(
                valid=True,
                confidence=DomainValidationConfig.GENERAL_DOMAIN_CONFIDENCE,
                reason=f"Could not confidently detect domain, allowing {target_domain.value} routing",
                detected_domain=detected_domain,
                target_domain=target_domain,
                suggestions=["Query may be too vague - consider being more specific"]
            )
        
        # CRITICAL: Strong domain mismatch (e.g., task query → calendar tool)
        # Use centralized mismatch messages from config
        from ..config.domain_validation_config import get_mismatch_message_for_domains
        
        reason = get_mismatch_message_for_domains(detected_domain, target_domain)
        
        # In strict mode, reject mismatches
        if self.strict_mode and detection_confidence > DomainValidationConfig.STRICT_MODE_THRESHOLD:
            logger.error(f"[VALIDATOR] ROUTING ERROR: {reason}")
            return ValidationResult(
                valid=False,
                confidence=DomainValidationConfig.MISMATCH_REJECT_CONFIDENCE,
                reason=reason,
                detected_domain=detected_domain,
                target_domain=target_domain,
                suggestions=[
                    f"Route to {detected_domain.value} tool instead",
                    "Check query classification logic",
                    f"Detected domain with {detection_confidence:.1%} confidence"
                ]
            )
        
        # Non-strict mode: allow with warning
        logger.warning(f"[VALIDATOR] Routing warning: {reason}")
        return ValidationResult(
            valid=True,
            confidence=DomainValidationConfig.MISMATCH_WARNING_CONFIDENCE,
            reason=f"[WARNING] {reason}",
            detected_domain=detected_domain,
            target_domain=target_domain,
            suggestions=[
                f"Consider routing to {detected_domain.value} tool",
                "Result may not match user expectations"
            ]
        )
    
    async def validate_execution_plan(
        self,
        query: str,
        execution_steps: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate an entire execution plan before running
        
        Args:
            query: Original user query
            execution_steps: List of execution steps with tool assignments
            
        Returns:
            Dictionary with validation results for each step
        """
        results = {
            'overall_valid': True,
            'confidence': 1.0,
            'step_validations': [],
            'warnings': [],
            'errors': []
        }
        
        for i, step in enumerate(execution_steps):
            tool_name = step.get('tool_name', '')
            step_query = step.get('query', query)
            
            validation = await self.validate_routing(step_query, tool_name)
            
            results['step_validations'].append({
                'step_id': step.get('id', f'step_{i}'),
                'validation': validation.to_dict()
            })
            
            if not validation.valid:
                results['overall_valid'] = False
                results['errors'].append(f"Step {i}: {validation.reason}")
            elif validation.confidence < DomainValidationConfig.MIN_VALIDATION_CONFIDENCE:
                results['warnings'].append(f"Step {i}: Low confidence ({validation.confidence:.2f})")
            
            # Update overall confidence (minimum of all steps)
            results['confidence'] = min(results['confidence'], validation.confidence)
        
        logger.info(
            f"[VALIDATOR] Execution plan validation: "
            f"valid={results['overall_valid']}, "
            f"confidence={results['confidence']:.2f}, "
            f"warnings={len(results['warnings'])}, "
            f"errors={len(results['errors'])}"
        )
        
        return results
