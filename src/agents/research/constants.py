
"""
Constants for Research Agent
"""

FALLBACK_SYSTEM_PROMPT = """You are a research assistant helping to analyze and synthesize information.
Provide comprehensive, well-organized findings with clear sections and key takeaways.
If you don't have enough information to answer fully, acknowledge the limitations."""

# Routing Patterns
RESEARCH_ROUTING_PATTERNS = [
    'research all',
    'deep research',
    'analyze all discussions',
    'analyze patterns in',
    'comprehensive summary of',
    'what have we discussed about',
    'find everything about'
]

# Exclusion Keywords (Finance)
FINANCE_EXCLUSION_KEYWORDS = ['how much', 'spend', 'cost', 'purchase', 'receipt', 'amazon', 'payment']
