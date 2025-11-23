"""
Document processing prompt templates
"""

# Document Summarization Prompts
DOCUMENT_SUMMARY_SYSTEM = """You are an expert at analyzing and summarizing documents. Create clear, comprehensive summaries that capture key information."""

DOCUMENT_SUMMARY_PROMPT = """Analyze and summarize this document comprehensively.

Title: {title}
Document Type: {doc_type}
Content:
{content}

Provide:
1. **Executive Summary** (2-3 sentences)
2. **Key Points** (bullet points)
3. **Important Details**: Dates, numbers, decisions
4. **Action Items**: If any
5. **Recommendations**: If applicable

Be thorough but concise. Focus on actionable information."""

DOCUMENT_KEY_POINTS = """Extract the key points from this document:

{content}

Provide a bullet-point list of the most important information."""


# Meeting Notes Prompts
MEETING_PREP_SYSTEM = """You are an expert meeting facilitator. Create comprehensive meeting preparation materials."""

MEETING_PREP_PROMPT = """Generate a comprehensive pre-meeting brief for this upcoming meeting.

Meeting Details:
- Title: {title}
- Date & Time: {datetime}
- Attendees: {attendees}
- Duration: {duration}

{context}

Provide:
1. **Meeting Overview** (2-3 sentences)
2. **Key Objectives**: What should be accomplished
3. **Agenda Items**: Suggested topics to cover
4. **Preparation Checklist**: What participants should prepare
5. **Discussion Points**: Key questions to address
6. **Expected Outcomes**: What success looks like
7. **Follow-up Items**: Post-meeting actions

Be practical and actionable."""

MEETING_SUMMARY_SYSTEM = """You are an expert at creating structured meeting summaries. Capture key decisions and action items clearly."""

MEETING_SUMMARY_PROMPT = """Analyze these meeting notes and create a structured summary.

Meeting: {title}
Date: {date}
Attendees: {attendees}

Notes:
{notes}

Provide:
1. **Meeting Overview** (2-3 sentences)
2. **Key Discussion Points** (bullet points)
3. **Decisions Made**: Clear list of decisions
4. **Action Items**: Who, what, when
5. **Open Questions**: Unresolved issues
6. **Next Steps**: Clear path forward
7. **Key Takeaways**: Most important points

Be clear and actionable. Make it easy to follow up."""

