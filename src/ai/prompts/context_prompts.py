"""
Context extraction and synthesis prompts
"""

CONTEXT_EXTRACTION_PROMPT = """Extract structured context from this step result:

Result: {result}

Extract:
- search_topic: Main topic being searched for
- key_findings: Important points or details found (brief)
- relevant_count: Number of items found
- subjects: List of email subjects or item titles
- important_entities: People, dates, projects mentioned
- emails: Email addresses found
- dates: Date/time expressions found

Return as ContextExtractionSchema."""

