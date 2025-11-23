"""
Blog-related prompt templates
"""

# Blog Completion Prompts
BLOG_COMPLETION_SYSTEM = """You are a helpful writing assistant for blog posts."""

BLOG_COMPLETION_PROMPT = """Your task is to complete the given text in a natural, engaging way.

IMPORTANT:
- The text may be incomplete (user is typing in real-time)
- Continue the thought naturally from where it left off
- Maintain the writing style and tone
- Keep completions concise (especially for short prompts)
- Only provide the completion text, do NOT repeat the prompt
- If the text ends mid-sentence, complete the sentence
- If the text ends mid-word, complete the word and continue
- Be contextually appropriate for a blog post

{context}

Current text (user is typing):
{prompt_text}"""
