"""
Email LLM Generation Handlers

Handles all LLM-based generation tasks for email operations:
- Email body composition with context-aware generation
- Email summarization (single and multiple emails)
- Conversational response generation
- Content summarization with format/length preferences

This module centralizes all LLM generation logic that was previously scattered
throughout the main EmailParser class.
"""
import re
from typing import Dict, Any, Optional, List
from langchain_core.messages import HumanMessage

from ....utils.logger import setup_logger
from ....ai.prompts import EMAIL_GENERIC_PROMPT
from ....ai.prompts.utils import format_prompt
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for LLM generation
LONG_THREAD_THRESHOLD = 10
MEDIUM_THREAD_THRESHOLD = 5
SUMMARY_LENGTH_CHECK = 100
SUMMARY_PREVIEW_LENGTH = 100
SUMMARY_WARNING_LENGTH = 50
MAX_CONTEXT_EMAILS = 20
MAX_SNIPPET_PREVIEW_LENGTH = 200
RESPONSE_MIN_LENGTH = 10
RESPONSE_WARNING_LENGTH = 100
RESPONSE_PREVIEW_LENGTH = 50


class EmailLLMGenerationHandlers:
    """
    Handles all LLM-based generation tasks for email operations.
    
    This includes:
    - Email body composition (_generate_email_with_llm)
    - Single email summarization (_generate_email_summary_with_llm)
    - Multiple emails summarization (_generate_email_summary_with_llm_for_multiple_emails)
    - Conversational response generation (_generate_conversational_email_response)
    - Generic content summarization (_generate_summary_with_llm)
    """
    
    def __init__(self, email_parser):
        """
        Initialize LLM generation handlers.
        
        Args:
            email_parser: Parent EmailParser instance for accessing llm_client, config, etc.
        """
        self.email_parser = email_parser
        self.llm_client = email_parser.llm_client
        self.config = email_parser.config
    
    def generate_email_with_llm(self, query: str, recipient: str, entities: Dict[str, Any]) -> str:
        """
        Generate email body using LLM - context-aware generation
        
        Args:
            query: User's email composition request
            recipient: Email recipient
            entities: Extracted entities (sender, subject, keywords, etc.)
            
        Returns:
            Generated email body content
        """
        if not self.llm_client:
            return self.email_parser._generate_simple_email(query, recipient)
        
        try:
            # Build context from entities
            context_parts = []
            if entities.get('sender'):
                context_parts.append(f"Sender: {entities.get('sender')}")
            if entities.get('subject'):
                context_parts.append(f"Subject: {entities.get('subject')}")
            if entities.get('keywords'):
                context_parts.append(f"Key topics: {', '.join(entities.get('keywords', []))}")
            
            context = "\n".join(context_parts) if context_parts else "No additional context"
            
            # Use prompt template from ai/prompts
            prompt = format_prompt(
                EMAIL_GENERIC_PROMPT,
                tone="professional yet friendly",
                purpose=f"Respond to user request: {query}",
                context=f"Recipient: {recipient}\n\nAdditional Context:\n{context}\n\nRequirements:\n- Do NOT include email headers (To:, From:, Subject:) - just the body content\n- Sign off appropriately (e.g., 'Best regards,' followed by the sender's name)\n- Natural flow and readability",
                length="appropriate"
            )
            
            response = self.llm_client.invoke(prompt)
            generated_body = response.content.strip()
            
            logger.info(f"LLM generated email body ({len(generated_body)} chars)")
            return generated_body
            
        except Exception as e:
            logger.warning(f"LLM email generation failed: {e}")
            return self.email_parser._generate_simple_email(query, recipient)
    
    def generate_email_summary_with_llm(self, sender: str, subject: str, body: str, 
                                       thread_context: Optional[str] = None) -> str:
        """
        Generate a rich, conversational summary of what an email was about
        
        Args:
            sender: Email sender name/address
            subject: Email subject line
            body: Email body content
            thread_context: Optional thread context (other emails in the thread)
            
        Returns:
            Natural, conversational summary of the email content
        """
        if not self.llm_client:
            return None
        
        try:
            # Build context for the LLM
            context_parts = []
            if subject:
                context_parts.append(f"Subject: {subject}")
            if sender:
                context_parts.append(f"From: {sender}")
            if thread_context:
                context_parts.append(f"\nThread Context:\n{thread_context}")
            
            context_info = "\n".join(context_parts) if context_parts else "No additional context"
            
            # Clean body for better processing - don't truncate, let LLM handle it
            # Remove excessive whitespace
            clean_body = re.sub(r'\s+', ' ', body).strip()
            
            # Determine summary length guidance based on thread complexity
            thread_length_guidance = ""
            if thread_context:
                # Count approximate number of messages in thread context
                thread_message_count = thread_context.count("From:")
                if thread_message_count > LONG_THREAD_THRESHOLD:
                    thread_length_guidance = "This is a long thread with many messages. Provide a comprehensive summary that covers the key phases and developments in the conversation. Be thorough but concise - aim for 5-8 sentences."
                elif thread_message_count > MEDIUM_THREAD_THRESHOLD:
                    thread_length_guidance = "This is a medium-length thread. Provide a detailed summary covering the main points and progression - aim for 4-6 sentences."
                else:
                    thread_length_guidance = "This is a shorter thread. Provide a clear summary - aim for 3-5 sentences."
            else:
                thread_length_guidance = "This appears to be a single email or short thread. Provide a concise summary - aim for 2-4 sentences."
            
            # Import and use EMAIL_SUMMARY_SINGLE prompt
            from ....ai.prompts import EMAIL_SUMMARY_SINGLE
            
            prompt = EMAIL_SUMMARY_SINGLE.format(
                sender=sender,
                subject=subject,
                date="N/A",  # Date would be passed if available
                body=clean_body,
                length_guidance=thread_length_guidance
            )

            response = self.llm_client.invoke(prompt)
            # Get full response content - handle both string and object responses
            if hasattr(response, 'content'):
                summary = response.content.strip()
                # Check if response has additional content (for streaming responses)
                if hasattr(response, 'response_metadata') and response.response_metadata:
                    # Some LLMs return metadata that might indicate if response was truncated
                    metadata = response.response_metadata
                    if 'finish_reason' in metadata:
                        finish_reason = metadata['finish_reason']
                        if finish_reason == 'length':
                            logger.warning(f"[EMAIL] LLM response was truncated due to length limit (finish_reason: {finish_reason})")
            elif isinstance(response, str):
                summary = response.strip()
            else:
                summary = str(response).strip()
            
            # Log the actual summary length and last chars to verify completeness
            logger.info(f"[EMAIL] Generated email summary ({len(summary)} chars)")
            if len(summary) > SUMMARY_LENGTH_CHECK:
                logger.debug(f"[EMAIL] Summary ends with: ...{summary[-SUMMARY_PREVIEW_LENGTH:]}")
            else:
                logger.debug(f"[EMAIL] Full summary: {summary}")
            
            # Verify summary is not truncated mid-sentence
            if summary and not summary[-1] in '.!?':
                # If summary doesn't end with punctuation, it might be truncated
                logger.warning(f"[EMAIL] Summary may be incomplete - doesn't end with punctuation. Last {SUMMARY_WARNING_LENGTH} chars: ...{summary[-SUMMARY_WARNING_LENGTH:]}")
            
            return summary
            
        except Exception as e:
            logger.warning(f"LLM email summary generation failed: {e}", exc_info=True)
            return None
    
    def generate_email_summary_with_llm_for_multiple_emails(self, emails_result: str, query: str) -> Optional[str]:
        """
        Generate a conversational summary of multiple emails using LLM
        
        Args:
            emails_result: Formatted result from email tool containing multiple emails
            query: Original user query
            
        Returns:
            Conversational summary of the emails, or None if LLM not available
        """
        if not self.llm_client:
            return None
        
        try:
            # Parse emails from the result
            emails = self.email_parser._parse_emails_from_formatted_result(emails_result)
            
            if not emails:
                return None
            
            # Build email context for the LLM
            email_context_parts = []
            for i, email in enumerate(emails[:MAX_CONTEXT_EMAILS], 1):  # Limit to MAX_CONTEXT_EMAILS for context
                email_info = f"Email {i}:\n"
                email_info += f"  From: {email.get('sender', 'Unknown')}\n"
                email_info += f"  Subject: {email.get('subject', 'No Subject')}\n"
                if email.get('date'):
                    email_info += f"  Date: {email.get('date')}\n"
                if email.get('snippet'):
                    email_info += f"  Preview: {email.get('snippet', '')[:MAX_SNIPPET_PREVIEW_LENGTH]}\n"
                email_context_parts.append(email_info)
            
            email_context = "\n".join(email_context_parts)
            
            # Import and use EMAIL_SUMMARY_MULTIPLE prompt
            from ....ai.prompts import EMAIL_SUMMARY_MULTIPLE
            
            # Escape curly braces in email content to prevent format() errors
            escaped_email_list = str(email_context).replace('{', '{{').replace('}', '}}')
            escaped_query = str(query).replace('{', '{{').replace('}', '}}')
            
            prompt = EMAIL_SUMMARY_MULTIPLE.format(
                email_count=len(emails),
                email_list=escaped_email_list,
                query=escaped_query
            )
            
            # Get response from LLM
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            
            # Extract response text
            response_text = None
            was_truncated = False
            
            if hasattr(response, 'content'):
                response_text = response.content
                # Check for truncation
                if hasattr(response, 'response_metadata') and response.response_metadata:
                    metadata = response.response_metadata
                    if 'finish_reason' in metadata:
                        finish_reason = metadata['finish_reason']
                        if finish_reason == 'length':
                            was_truncated = True
                            logger.error(f"[EMAIL] LLM response was TRUNCATED (finish_reason: {finish_reason})")
                            # Retry with higher max_tokens
                            try:
                                logger.info("[EMAIL] Attempting to regenerate with higher max_tokens...")
                                from ....ai.llm_factory import LLMFactory
                                retry_llm = LLMFactory.get_llm_for_provider(self.config, temperature=EmailParserConfig.LLM_TEMPERATURE, max_tokens=EmailParserConfig.LLM_MAX_TOKENS)
                                retry_response = retry_llm.invoke([HumanMessage(content=prompt)])
                                if hasattr(retry_response, 'content'):
                                    response_text = retry_response.content
                                    logger.info(f"[EMAIL] Retry successful - got {len(response_text)} chars")
                                    was_truncated = False
                            except Exception as retry_error:
                                logger.warning(f"[EMAIL] Retry with higher max_tokens failed: {retry_error}")
            elif isinstance(response, str):
                response_text = response
            else:
                response_text = str(response)
            
            if not response_text:
                logger.error("[EMAIL] No response text extracted from LLM")
                return None
            
            # Clean up the response
            response_text = response_text.strip()
            
            # Remove any leading/trailing quotes if present
            if len(response_text) > 2 and response_text.startswith('"') and response_text.endswith('"'):
                response_text = response_text[1:-1].strip()
            if len(response_text) > 2 and response_text.startswith("'") and response_text.endswith("'"):
                response_text = response_text[1:-1].strip()
            
            # Verify response is complete
            if response_text and len(response_text) > RESPONSE_MIN_LENGTH:
                if not response_text[-1] in '.!?':
                    if was_truncated or len(response_text) > RESPONSE_WARNING_LENGTH:
                        logger.warning(f"[EMAIL] Response may be incomplete - doesn't end with punctuation. Last {RESPONSE_PREVIEW_LENGTH} chars: ...{response_text[-RESPONSE_PREVIEW_LENGTH:]}")
                        if was_truncated:
                            response_text += " [Response may be truncated]"
                        else:
                            response_text += "."
            
            logger.info(f"[EMAIL] Generated email summary: length={len(response_text)} chars, truncated={was_truncated}")
            return response_text
            
        except Exception as e:
            logger.error(f"Failed to generate email summary for multiple emails: {e}", exc_info=True)
            return None
    
    def generate_summary_with_llm(self, content: str, format_type: str, length: str, 
                                 focus: Optional[str] = None) -> str:
        """
        Generate summary using LLM with format, length, and focus preferences
        
        Args:
            content: Content to summarize
            format_type: Output format (bullet_points/key_points/paragraph)
            length: Desired length (short/medium/long)
            focus: Optional focus area
            
        Returns:
            Generated summary
        """
        if not self.llm_client:
            return "[ERROR] LLM not available for summarization"
        
        # Build format instructions
        format_instructions = {
            'bullet_points': 'Format as a bulleted list',
            'key_points': 'Format as key points or takeaways',
            'paragraph': 'Format as a narrative paragraph'
        }.get(format_type, 'paragraph')
        
        # Build length instructions
        length_instructions = {
            'short': 'in 1-2 sentences',
            'medium': 'in 2-3 paragraphs',
            'long': 'comprehensively with full details'
        }.get(length, 'medium')
        
        # Build focus instructions
        focus_instruction = f"\n\nFocus particularly on: {focus}" if focus else ""
        
        prompt = f"""Please summarize the following content {length_instructions}.

Format: {format_instructions}{focus_instruction}

Content to summarize:
{content}

Summary:"""
        
        response = self.llm_client.invoke(prompt)
        return response.content.strip()
