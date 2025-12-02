"""
Context Synthesizer - Cross-domain context enrichment

Integrates with:
- schemas.schemas: ContextExtractionSchema for structured context extraction
- LLM: Structured output for reliable context parsing
- SynthesisConfig: Configuration for enrichment thresholds and limits
- ExecutionStep: Domain-aware execution steps for transition detection
- ToolDomainConfig: Centralized domain mapping
- Config files: Enrichment rules loaded from YAML

Handles context synthesis between different domains (email, calendar, tasks, notion).

Features:
- Cross-domain context enrichment (email->calendar, calendar->task, notion integrations)
- Structured context extraction from step results
- Pattern-based and LLM-based extraction methods
- Domain transition detection and enrichment
- Integration with orchestration execution flow

Usage:
    synthesizer = ContextSynthesizer(llm_client=llm_client)
    
    # Synthesize context across execution steps
    enriched_context = await synthesizer.synthesize_context(
        execution_steps=steps,
        current_context={'query': query, 'entities': entities}
    )
    
    # Extract structured context from result
    context = await synthesizer.extract_context_from_result(
        result="Found 5 emails about budget",
        use_llm=True
    )
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import re

from ..core.base import ExecutionStep, ContextEnrichment
from ..config.synthesis_config import SynthesisConfig
from ..domain.tool_domain_config import get_tool_domain_config, Domain

# Schema imports for type-safe context extraction
try:
    from ...schemas.schemas import ContextExtractionSchema
    HAS_SCHEMAS = True
except ImportError:
    HAS_SCHEMAS = False
    ContextExtractionSchema = Any

# Prompt imports
try:
    from ....ai.prompts.context_prompts import CONTEXT_EXTRACTION_PROMPT
except ImportError:
    CONTEXT_EXTRACTION_PROMPT = None

from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Regex patterns for pattern-based extraction (constants)
EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
DATE_PATTERNS = [
    r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
    r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
    r'(today|tomorrow|yesterday)',  # Relative dates
]
COUNT_PATTERN = r'(\d+)\s+(email|message|event|task|item)'
SUBJECT_PATTERN = r'Subject:\s*(.+?)(?:\n|$)'


class ContextSynthesizer:
    """Advanced context synthesis across domains with schema integration"""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.enrichment_rules = self._load_enrichment_rules()
        self.tool_domain_config = get_tool_domain_config()
    
    def _load_enrichment_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load cross-domain context enrichment rules from config file"""
        try:
            import yaml
            config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "enrichment_rules.yaml"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    rules = config.get('enrichment_rules', {})
                    if rules:
                        logger.debug(f"Loaded {len(rules)} enrichment rules from config")
                        return rules
        except Exception as e:
            logger.warning(f"Failed to load enrichment rules from config: {e}, using empty rules")
        
        return {}
    
    async def synthesize_context(self, 
                                execution_steps: List[ExecutionStep],
                                current_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synthesize enriched context across domains
        
        Args:
            execution_steps: List of execution steps to analyze for domain transitions
            current_context: Current context dictionary to enrich
            
        Returns:
            Enriched context dictionary with cross-domain enrichments applied
        """
        enriched_context = current_context.copy()
        
        # Analyze domain transitions
        domain_transitions = self._identify_domain_transitions(execution_steps)
        
        if domain_transitions:
            logger.debug(f"[CONTEXT-SYNTHESIS] Found {len(domain_transitions)} domain transitions")
        
        for transition in domain_transitions:
            enrichment = await self._apply_enrichment_rules(
                transition['from_domain'],
                transition['to_domain'],
                transition['context']
            )
            
            if enrichment:
                enrichment_key = f"enrichment_{enrichment.enrichment_type}"
                enriched_context[enrichment_key] = enrichment.enriched_context
                logger.debug(
                    f"[CONTEXT-SYNTHESIS] Applied {enrichment.enrichment_type} enrichment "
                    f"({enrichment.source_domain} -> {enrichment.target_domain})"
                )
        
        return enriched_context
    
    def _identify_domain_transitions(self, steps: List[ExecutionStep]) -> List[Dict[str, Any]]:
        """Identify domain transitions for enrichment"""
        transitions = []
        
        for i in range(len(steps) - 1):
            # Extract domain from step's domain attribute or intent
            current_domain = self._extract_domain(
                getattr(steps[i], 'domain', None) or 
                getattr(steps[i], 'intent', None) or 
                (steps[i].get_domain() if hasattr(steps[i], 'get_domain') else None) or
                ''
            )
            next_domain = self._extract_domain(
                getattr(steps[i + 1], 'domain', None) or 
                getattr(steps[i + 1], 'intent', None) or 
                (steps[i + 1].get_domain() if hasattr(steps[i + 1], 'get_domain') else None) or
                ''
            )
            
            if current_domain != next_domain and current_domain != 'general' and next_domain != 'general':
                # Get result from step, handling both string and dict results
                step_result = getattr(steps[i], 'result', None)
                if isinstance(step_result, dict):
                    context = step_result.get('result', step_result.get('data', ''))
                else:
                    context = str(step_result) if step_result else ''
                
                transitions.append({
                    'from_domain': current_domain,
                    'to_domain': next_domain,
                    'context': context
                })
        
        return transitions
    
    def _extract_domain(self, intent: str) -> str:
        """Extract domain from intent string using ToolDomainConfig"""
        if not intent:
            return 'general'
        
        # Use ToolDomainConfig for domain normalization
        domain_enum = self.tool_domain_config.normalize_domain_string(intent)
        if domain_enum:
            return domain_enum.value
        
        # Fallback for 'summary' domain
        if intent.lower() == 'summary':
            return 'summary'
        
        return 'general'
    
    async def _apply_enrichment_rules(self,
                                     from_domain: str,
                                     to_domain: str,
                                     context: str) -> Optional[ContextEnrichment]:
        """
        Apply domain-specific enrichment rules
        
        Args:
            from_domain: Source domain (e.g., 'email', 'calendar', 'notion')
            to_domain: Target domain (e.g., 'task', 'notion', 'calendar')
            context: Context string from the source domain step result
            
        Returns:
            ContextEnrichment object if enrichment rules match, None otherwise
        """
        rule_key = f"{from_domain}_to_{to_domain}"
        rules = self.enrichment_rules.get(rule_key)
        
        if not rules:
            logger.debug(f"[CONTEXT-SYNTHESIS] No enrichment rules found for {rule_key}")
            return None
        
        # Extract relevant information based on patterns
        context_lower = context.lower() if context else ''
        extracted = {}
        for pattern in rules['extract_patterns']:
            if pattern.lower() in context_lower:
                extracted[pattern] = True
        
        if not extracted:
            logger.debug(f"[CONTEXT-SYNTHESIS] No patterns matched for {rule_key}")
            return None
        
        # Apply context mappings - extract actual values from context
        enriched_context = {}
        for source_key, target_key in rules['context_mappings'].items():
            # Try to extract actual values from context using simple heuristics
            # This could be enhanced with LLM extraction if needed
            if source_key in context_lower or any(pattern in context_lower for pattern in extracted.keys()):
                # For now, use pattern presence as indicator
                # In production, could use LLM to extract actual values
                enriched_context[target_key] = True  # Indicates presence
        
        if not enriched_context:
            return None
        
        confidence = SynthesisConfig.ENRICHMENT_CONFIDENCE_THRESHOLD
        
        return ContextEnrichment(
            source_domain=from_domain,
            target_domain=to_domain,
            enrichment_type=rule_key,
            enriched_context=enriched_context,
            confidence=confidence
        )
    
    async def extract_context_from_result(self, result: str, use_llm: bool = True) -> Optional[Dict[str, Any]]:
        """
        Extract structured context from step execution result.
        
        Uses ContextExtractionSchema with LLM structured output when available,
        falls back to pattern-based extraction.
        
        Args:
            result: The raw result text from a step execution
            use_llm: Whether to use LLM for extraction (requires llm_client)
            
        Returns:
            Extracted context as dict, or None if extraction fails
        """
        if not result:
            return None
        
        # Try LLM-based extraction with schema if available
        if use_llm and self.llm_client:
            try:
                # Use prompt from prompts module
                if CONTEXT_EXTRACTION_PROMPT:
                    prompt = CONTEXT_EXTRACTION_PROMPT.format(result=result)
                else:
                    # Fallback if prompt not available
                    prompt = f"Extract structured context from this step result:\n\nResult: {result}\n\nReturn as ContextExtractionSchema."
                
                # Use structured output if LLM supports it
                if hasattr(self.llm_client, 'with_structured_output'):
                    structured_llm = self.llm_client.with_structured_output(ContextExtractionSchema)
                    context = structured_llm.invoke(prompt)
                    logger.debug("Context extraction with structured output succeeded")
                    
                    # Convert to dict
                    return context.model_dump(exclude_none=True)
                    
            except Exception as e:
                logger.warning(f"Structured context extraction failed: {e}, falling back to pattern-based")
        
        # Fallback to pattern-based extraction
        return self._pattern_based_context_extraction(result)
    
    def _pattern_based_context_extraction(self, result: str) -> Dict[str, Any]:
        """Extract context using patterns (fallback method)"""
        context = {}
        
        # Extract email addresses
        emails = re.findall(EMAIL_PATTERN, result)
        if emails:
            context['emails'] = list(set(emails))
        
        # Extract dates
        dates = []
        for pattern in DATE_PATTERNS:
            dates.extend(re.findall(pattern, result, re.IGNORECASE))
        if dates:
            context['dates'] = list(set(dates))
        
        # Extract counts
        count_matches = re.findall(COUNT_PATTERN, result, re.IGNORECASE)
        if count_matches:
            context['relevant_count'] = int(count_matches[0][0])
        
        # Extract subject lines
        subjects = re.findall(SUBJECT_PATTERN, result, re.IGNORECASE)
        if subjects:
            context['subjects'] = subjects[:SynthesisConfig.MAX_SUBJECTS_TO_EXTRACT]
        
        return context
