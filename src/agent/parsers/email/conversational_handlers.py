"""
Email Conversational Response Handlers

Handles all conversational response generation and email parsing:
- Conversational response generation for email queries
- Email parsing from formatted tool results
- Response validation and cleanup
- LLM regeneration for robotic responses

This module ensures all email responses sound natural and conversational,
not robotic or technical.
"""
import re
from typing import Dict, Any, Optional, List
from langchain_core.messages import HumanMessage

from ....utils.logger import setup_logger
from ....ai.prompts import EMAIL_GENERIC_PROMPT
from ....ai.prompts.utils import format_prompt
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for conversational handlers
MAX_EMAILS_FOR_CONTEXT = 40  # Increased from 10 to show more emails for "new emails" queries
MAX_SNIPPET_LENGTH = 200
RESPONSE_MIN_LENGTH = 10
RESPONSE_WARNING_LENGTH = 100
RESPONSE_PREVIEW_LENGTH = 50


class EmailConversationalHandlers:
    """
    Handles all conversational response generation for email operations.
    
    This includes:
    - Generating natural, conversational responses (generate_conversational_email_response)
    - Parsing emails from formatted results (parse_emails_from_formatted_result)
    - Validating responses are conversational (is_response_conversational)
    - Forcing LLM regeneration (force_llm_regeneration)
    - Final cleanup of responses (final_cleanup_conversational_response)
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
    
    def generate_conversational_email_response(self, formatted_result: str, query: str, user_first_name: Optional[str] = None) -> Optional[str]:
        """
        Generate natural, conversational response for email queries using LLM
        
        Args:
            formatted_result: Raw formatted result from email tool (e.g., "Gmail Search Results (5):\n\n[EMAIL]\n...")
            query: Original user query
            user_first_name: Optional user's first name for personalization
            
        Returns:
            Conversational response string, or None if LLM not available
        """
        if not self.llm_client:
            logger.warning("[EMAIL] LLM client not available for conversational response")
            return None
        
        logger.info(f"[EMAIL] Generating conversational response from formatted result ({len(formatted_result)} chars)")
        
        try:
            # CRITICAL: Check if this is a "no emails found" message BEFORE parsing
            formatted_result_lower = formatted_result.lower()
            is_no_results_message = (
                "couldn't find" in formatted_result_lower or
                "don't see" in formatted_result_lower or
                "no emails" in formatted_result_lower or
                "no matching" in formatted_result_lower or
                "couldn't find any emails" in formatted_result_lower
            )
            
            # Parse emails from formatted result
            emails = self.parse_emails_from_formatted_result(formatted_result)
            
            # CRITICAL: Validate that emails list is not empty or None
            # If emails is None, empty list, or contains invalid entries, treat as "no results"
            if not emails or not isinstance(emails, list) or len(emails) == 0:
                emails = []
                is_no_results_message = True
                logger.info(f"[EMAIL] No emails parsed from formatted result - treating as 'no results'")
            else:
                # Validate that emails actually contain valid data (not just empty dicts)
                valid_emails = []
                for email in emails:
                    if isinstance(email, dict) and (email.get('subject') or email.get('from') or email.get('sender')):
                        valid_emails.append(email)
                    else:
                        logger.warning(f"[EMAIL] Skipping invalid email entry: {email}")
                
                if len(valid_emails) == 0:
                    emails = []
                    is_no_results_message = True
                    logger.info(f"[EMAIL] No valid emails found after validation - treating as 'no results'")
                else:
                    emails = valid_emails
                    logger.info(f"[EMAIL] Found {len(emails)} valid emails after validation")
            
            # Determine query characteristics early (needed for LLM initialization)
            query_lower = query.lower()
            logger.info(f"[EMAIL] Conversational handler received query: '{query}' (lower: '{query_lower}'), emails count: {len(emails) if emails else 0}")
            
            # Check if user explicitly asked for a count
            count_query_patterns = [
                "how many", "how much", "count", "number of", "total", 
                "how many emails", "how many new emails", "how many unread",
                "what's the count", "what's the number", "tell me how many"
            ]
            is_count_query = any(pattern in query_lower for pattern in count_query_patterns)
            
            is_today_query = "today" in query_lower or "new emails" in query_lower
            
            # CRITICAL: Detect time-based queries (last hour, past hour, few hours, etc.)
            # This must match the detection logic in action_handlers.py
            time_based_phrases = [
                "last hour", "past hour", "few hours", "last hour or so",
                "last day", "past day", "last week", "past week",
                "last month", "past month", "last year", "past year",
                "in the last", "in the past", "from the last", "from the past",
                "over the last", "over the past"
            ]
            is_time_based_query = any(phrase in query_lower for phrase in time_based_phrases)
            
            # Also check for numeric patterns like "last 2 hours", "past 3 hours", etc.
            if not is_time_based_query:
                time_pattern = re.search(r'(last|past|few)\s+(\d+)?\s*(hour|hours|day|days|week|weeks|month|months)', query_lower)
                if time_pattern:
                    is_time_based_query = True
                    logger.info(f"[EMAIL] Detected time-based query via regex pattern: '{time_pattern.group(0)}'")
            
            # Log detection result for debugging
            logger.info(f"[EMAIL] Query detection - is_today_query: {is_today_query}, is_time_based_query: {is_time_based_query}, query: '{query}'")
            if is_time_based_query:
                matched_phrases = [phrase for phrase in time_based_phrases if phrase in query_lower]
                logger.info(f"[EMAIL] Matched time-based phrases: {matched_phrases}")
            
            # Initialize prompt variable
            prompt = None
            
            if not emails or is_no_results_message:
                # No emails found - use rich prompts from prompts/ directory
                from langchain_core.messages import HumanMessage
                
                is_priority_query = any(term in query_lower for term in ["priority", "urgent", "immediate attention", "important"])
                
                # Use rich prompts from prompts/conversational_prompts.py
                if is_priority_query:
                    from ....ai.prompts import EMAIL_PRIORITY_NO_RESULTS_PROMPT
                    escaped_query = str(query).replace('{', '{{').replace('}', '}}')
                    
                    # Add personalization to the rich prompt
                    personalization_note = ""
                    if user_first_name:
                        personalization_note = f"\n\nPERSONALIZATION: The user's name is {user_first_name}. Use their name sparingly - only once or twice in the entire response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
                    
                    # Use the rich prompt and add personalization
                    prompt_template = EMAIL_PRIORITY_NO_RESULTS_PROMPT
                    prompt = prompt_template.replace('{query}', escaped_query)
                    prompt = prompt.replace('{context}', "Checked: inbox, starred, important, primary, updates folders")
                    prompt = prompt + personalization_note
                else:
                    from ....ai.prompts import EMAIL_NO_RESULTS_GENERAL_PROMPT
                    escaped_query = str(query).replace('{', '{{').replace('}', '}}')
                    
                    # Add personalization to the rich prompt
                    personalization_note = ""
                    if user_first_name:
                        personalization_note = f"\n\nPERSONALIZATION: The user's name is {user_first_name}. Use their name sparingly - only once or twice in the entire response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
                    
                    # Use the rich prompt and add personalization
                    prompt_template = EMAIL_NO_RESULTS_GENERAL_PROMPT
                    prompt = prompt_template.replace('{query}', escaped_query)
                    prompt = prompt + personalization_note
                
                # Use enhanced LLM with full max_tokens even for "no results" responses
                from ....ai.llm_factory import LLMFactory
                try:
                    enhanced_llm = LLMFactory.get_llm_for_provider(
                        self.config, 
                        temperature=EmailParserConfig.LLM_TEMPERATURE, 
                        max_tokens=EmailParserConfig.LLM_MAX_TOKENS
                    )
                    response = enhanced_llm.invoke([HumanMessage(content=prompt)])
                except Exception as e:
                    logger.warning(f"[EMAIL] Failed to create enhanced LLM for no-results, using default: {e}")
                    response = self.llm_client.invoke([HumanMessage(content=prompt)])
                
                if hasattr(response, 'content'):
                    return response.content.strip()
            else:
                # Has emails - generate conversational summary
                is_priority_query = any(term in query_lower for term in ["priority", "urgent", "immediate attention", "important"])
                is_singular = " email " in query_lower or query_lower.endswith(" email") or query_lower.endswith(" email?")
                
                # is_time_based_query is already set above, no need to recalculate
                
                # Check if this is a "new emails" query (should include more emails)
                is_new_emails_query = any(phrase in query_lower for phrase in ["new emails", "new email", "new messages", "new message"])
                
                # Use all emails for today queries, time-based queries, or "new emails" queries, otherwise limit to MAX_EMAILS_FOR_CONTEXT
                max_emails_for_response = len(emails) if (is_today_query or is_time_based_query or is_new_emails_query) else MAX_EMAILS_FOR_CONTEXT
                logger.info(f"[EMAIL] Including {max_emails_for_response} emails in response (total: {len(emails)}, is_today_query: {is_today_query}, is_time_based_query: {is_time_based_query})")
                
                email_context = []
                for i, email in enumerate(emails[:max_emails_for_response], 1):
                    email_info = f"Email {i}:\n"
                    # CRITICAL: Use 'from' field first (Gmail API standard), then 'sender' as fallback
                    sender = email.get('from') or email.get('sender', 'Unknown')
                    if not sender or not sender.strip() or sender == 'Unknown':
                        # Try to extract from other fields
                        sender = email.get('recipient') or 'Unknown'
                    email_info += f"  From: {sender}\n"
                    # CRITICAL: Ensure subject is never empty
                    subject = email.get('subject', '')
                    if not subject or subject.strip() == '' or subject == 'No Subject':
                        subject = 'No Subject'
                    email_info += f"  Subject: {subject}\n"
                    if email.get('date'):
                        email_info += f"  Date: {email.get('date')}\n"
                    if email.get('snippet'):
                        email_info += f"  Preview: {email.get('snippet', '')[:150]}...\n"
                    email_context.append(email_info)
                
                # For priority queries, filter out promotional emails
                if is_priority_query:
                    filtered_emails = []
                    for email in emails:
                        subject = email.get('subject', '').lower()
                        sender = email.get('sender', '').lower()
                        
                        is_promotional = (
                            any(promo_term in subject for promo_term in ['offer', 'sale', 'discount', 'deal', 'flash', 'promo', 'promotion', 'special', 'limited time', 'save', '% off', 'coupon', 'code', 'extended', 'fall flash']) or
                            any(promo_term in sender for promo_term in ['noreply', 'no-reply', 'marketing', 'promo', 'offers', 'deals', 'newsletter'])
                        )
                        
                        if not is_promotional:
                            filtered_emails.append(email)
                        else:
                            logger.info(f"[EMAIL] Filtered out promotional email: {email.get('subject', 'No subject')}")
                    
                    if filtered_emails:
                        emails = filtered_emails
                        # Check if this is a "new emails" query (should include more emails)
                        is_new_emails_query = any(phrase in query_lower for phrase in ["new emails", "new email", "new messages", "new message"])
                        
                        # Use all filtered emails for today queries, time-based queries, or "new emails" queries
                        max_emails_for_response = len(emails) if (is_today_query or is_time_based_query or is_new_emails_query) else MAX_EMAILS_FOR_CONTEXT
                        logger.info(f"[EMAIL] After promotional filtering: {len(emails)} emails remaining (is_today_query: {is_today_query}, is_time_based_query: {is_time_based_query})")
                        email_context = []
                        for i, email in enumerate(emails[:max_emails_for_response], 1):
                            email_info = f"Email {i}:\n"
                            # CRITICAL: Use 'from' field first, then 'sender' as fallback
                            sender = email.get('from') or email.get('sender', 'Unknown')
                            if email.get('subject') and sender == email.get('subject'):
                                logger.warning(f"[EMAIL] WARNING: Sender matches subject - possible data issue. Sender: {sender}, Subject: {email.get('subject')}")
                            email_info += f"  From: {sender}\n"
                            email_info += f"  Subject: {email.get('subject', 'No Subject')}\n"
                            if email.get('date'):
                                email_info += f"  Date: {email.get('date')}\n"
                            if email.get('snippet'):
                                email_info += f"  Preview: {email.get('snippet', '')[:150]}...\n"
                            email_context.append(email_info)
                    else:
                        logger.info(f"[EMAIL] All emails were promotional, generating 'no results' response")
                        emails = []
                        email_context = []
                
                if is_singular and len(emails) == 1:
                    from ....ai.prompts import EMAIL_PRIORITY_FOUND_SINGLE
                    
                    email = emails[0]
                    priority_note = ""
                    if is_priority_query:
                        priority_note = "\n\nIMPORTANT CONTEXT: This is a priority email - it likely needs a response or requires some action. Based on the content, mention what action might be needed (like responding, making a payment, verifying something, etc.). Be natural and conversational about it."
                    
                    # CRITICAL: Use 'from' field first, then 'sender' as fallback for sender
                    # Never use subject as sender
                    sender = email.get('from') or email.get('sender', 'Unknown')
                    if email.get('subject') and sender == email.get('subject'):
                        logger.error(f"[EMAIL] CRITICAL ERROR: Sender matches subject! Sender: {sender}, Subject: {email.get('subject')}. This should never happen.")
                        # Try to get sender from a different field or use 'Unknown'
                        sender = 'Unknown'
                    
                    # Escape curly braces in email content to prevent format() errors
                    escaped_sender = str(sender).replace('{', '{{').replace('}', '}}')
                    escaped_subject = str(email.get('subject', 'No Subject')).replace('{', '{{').replace('}', '}}')
                    escaped_date = str(email.get('date', 'Unknown')).replace('{', '{{').replace('}', '}}')
                    escaped_preview = str(email.get('snippet', 'No preview available')[:MAX_SNIPPET_LENGTH]).replace('{', '{{').replace('}', '}}')
                    escaped_query = str(query).replace('{', '{{').replace('}', '}}')
                    escaped_priority_note = str(priority_note).replace('{', '{{').replace('}', '}}')
                    
                    # Add personalization to prompt if user_first_name is available
                    personalization_note = ""
                    if user_first_name:
                        personalization_note = f"\n\nPERSONALIZATION: The user's name is {user_first_name}. Use their name sparingly - only once or twice in the entire response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
                    
                    prompt = EMAIL_PRIORITY_FOUND_SINGLE.format(
                        priority_note=escaped_priority_note + personalization_note,
                        sender=escaped_sender,
                        subject=escaped_subject,
                        date=escaped_date,
                        preview=escaped_preview,
                        query=escaped_query
                    )
                else:
                    from ....ai.prompts import EMAIL_PRIORITY_FOUND_MULTIPLE
                    
                    priority_context = ""
                    if is_priority_query:
                        priority_context = "\n\nIMPORTANT CONTEXT: The user asked for priority emails that need immediate attention. Mention that these are emails requiring their attention or response. Be conversational and natural - don't sound robotic. Focus on what action might be needed for each email (reply, payment, etc.)."
                    
                    email_count = len(emails)
                    # CRITICAL: Tell LLM to include ALL emails, not just the ones in context
                    # If we're showing all emails (today query or time-based query), make sure LLM knows to mention all
                    include_all_note = ""
                    if (is_today_query or is_time_based_query) and email_count > max_emails_for_response:
                        time_context = "from the last hour or so" if is_time_based_query else "today"
                        include_all_note = f"\n\nCRITICAL: You are seeing {max_emails_for_response} emails out of {email_count} total. However, the user asked about 'new emails {time_context}', so you should mention that there are {email_count} total emails and provide a comprehensive summary of the key ones. If there are many emails, group them by sender or topic."
                    elif is_today_query or is_time_based_query:
                        time_context = "from the last hour or so" if is_time_based_query else "today"
                        include_all_note = f"\n\nCRITICAL: The user asked about 'new emails {time_context}'. Make sure to mention ALL {email_count} emails in your response. Don't skip any - provide a comprehensive summary."
                    
                    # Escape curly braces in email content to prevent format() errors
                    # Also handle the conditional expression in the template
                    email_list_str = chr(10).join(email_context) if email_context else 'None'
                    escaped_email_list = email_list_str.replace('{', '{{').replace('}', '}}')
                    escaped_query = str(query).replace('{', '{{').replace('}', '}}')
                    escaped_priority_context = (priority_context + include_all_note).replace('{', '{{').replace('}', '}}')
                    
                    # Handle the conditional plural in the template
                    # The template has: "you've found {email_count} email{'s' if email_count != 1 else ''}"
                    # We need to replace the entire conditional expression
                    email_plural = 's' if email_count != 1 else ''
                    
                    # Add personalization to prompt if user_first_name is available
                    personalization_note = ""
                    if user_first_name:
                        personalization_note = f"\n\nPERSONALIZATION: The user's name is {user_first_name}. Use their name sparingly - only once or twice in the entire response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
                        escaped_priority_context = escaped_priority_context + personalization_note.replace('{', '{{').replace('}', '}}')
                    
                    # Add count instruction based on whether user asked for a count
                    count_instruction = ""
                    if is_count_query:
                        count_instruction = f"\n\nCRITICAL: The user explicitly asked for a count. You MUST mention the exact number: {email_count} email{'s' if email_count != 1 else ''}. Be accurate and specific."
                    else:
                        count_instruction = "\n\nCRITICAL: The user did NOT ask for a count. DO NOT mention the number of emails in your response. Just present the emails naturally without stating how many there are."
                    escaped_count_instruction = count_instruction.replace('{', '{{').replace('}', '}}')
                    
                    # Use string replacement instead of format() to avoid issues with conditional expressions and curly braces
                    prompt = EMAIL_PRIORITY_FOUND_MULTIPLE.replace('{email_count}', str(email_count))
                    # Replace the conditional expression with the computed plural
                    prompt = prompt.replace("{'s' if email_count != 1 else ''}", email_plural)
                    prompt = prompt.replace('{priority_context}', escaped_priority_context)
                    prompt = prompt.replace('{count_instruction}', escaped_count_instruction)
                    prompt = prompt.replace('{email_list}', escaped_email_list)
                    prompt = prompt.replace('{query}', escaped_query)
            
            # Get response from LLM with sufficient max_tokens to avoid truncation
            # Always use full max_tokens for email list responses to prevent truncation
            if prompt is None:
                logger.error("[EMAIL] Prompt was not set - this should not happen")
                return None
            
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            # Use full max_tokens (4000) for email responses, especially for "today" queries with many emails
            # This prevents truncation from the start
            try:
                enhanced_llm = LLMFactory.get_llm_for_provider(
                    self.config, 
                    temperature=EmailParserConfig.LLM_TEMPERATURE, 
                    max_tokens=EmailParserConfig.LLM_MAX_TOKENS  # Use full max_tokens (4000) for email responses
                )
                response = enhanced_llm.invoke([HumanMessage(content=prompt)])
                email_count_for_log = len(emails) if emails else 0
                logger.info(f"[EMAIL] Using LLM with max_tokens={EmailParserConfig.LLM_MAX_TOKENS} for email response ({email_count_for_log} emails, is_today_query: {is_today_query})")
            except Exception as e:
                logger.warning(f"[EMAIL] Failed to create enhanced LLM, using default: {e}")
                response = self.llm_client.invoke([HumanMessage(content=prompt)])
            
            # Extract response text - ensure we get the FULL response (no truncation)
            response_text = None
            was_truncated = False
            
            if hasattr(response, 'content'):
                response_text = response.content
                # Check for truncation indicators
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
            
            # Clean up the response (but preserve full length)
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
            
            logger.info(f"[EMAIL] Generated conversational response: length={len(response_text)} chars, truncated={was_truncated}")
            return response_text
            
        except Exception as e:
            logger.error(f"Failed to generate conversational email response: {e}", exc_info=True)
            return None
    
    def parse_emails_from_formatted_result(self, formatted_result: str) -> List[Dict[str, Any]]:
        """
        Parse emails from formatted tool result
        
        Args:
            formatted_result: Raw formatted result from email tool
            
        Returns:
            List of email dictionaries with sender, subject, date, snippet
        """
        emails = []
        
        if not formatted_result:
            return emails
        
        # CRITICAL: Remove [OK] prefix if present
        formatted_result = re.sub(r'^\[OK\]\s+', '', formatted_result, flags=re.IGNORECASE)
        
        # Remove "Gmail Search Results (X):" header
        formatted_result = re.sub(r'^\[OK\]\s*Gmail\s+Search\s+Results\s*\([^)]+\):\s*\n*', '', formatted_result, flags=re.IGNORECASE)
        formatted_result = re.sub(r'^\[OK\]\s*I\s+found\s+\d+\s+email.*?:\s*\n*', '', formatted_result, flags=re.IGNORECASE)
        formatted_result = re.sub(r'^I\s+found\s+\d+\s+email.*?:\s*\n*', '', formatted_result, flags=re.IGNORECASE)
        
        # Try numbered list format first: "1. [UNREAD] **Subject**\n   From: ...\n   Time: ..."
        numbered_pattern = r'(\d+)\.\s+(\[UNREAD\]|\[READ\])?\s*\*\*?(.+?)\*\*?\s*\n'
        numbered_matches = list(re.finditer(numbered_pattern, formatted_result, re.MULTILINE | re.IGNORECASE))
        
        if numbered_matches:
            for i, match in enumerate(numbered_matches):
                email = {'subject': match.group(3).strip()}
                
                # Extract sender, time, and preview from the lines after the subject
                start_pos = match.end()
                end_pos = numbered_matches[i + 1].start() if i + 1 < len(numbered_matches) else len(formatted_result)
                
                email_block = formatted_result[start_pos:end_pos]
                
                # Extract sender - CRITICAL: Use "From:" field, not subject
                sender_match = re.search(r'From:\s*(.+?)(?:\n|$)', email_block, re.IGNORECASE)
                if sender_match:
                    sender_text = sender_match.group(1).strip()
                    # Ensure we're not accidentally extracting subject as sender
                    # If sender matches subject, something is wrong - log warning
                    if email.get('subject') and sender_text == email.get('subject'):
                        logger.warning(f"[EMAIL] WARNING: Sender matches subject - possible parsing error. Sender: {sender_text}, Subject: {email.get('subject')}")
                    email['sender'] = sender_text
                
                # Extract time/date
                time_match = re.search(r'Time:\s*(.+?)(?:\n|$)', email_block, re.IGNORECASE)
                if time_match:
                    email['date'] = time_match.group(1).strip()
                
                # Extract preview
                preview_match = re.search(r'Preview:\s*(.+?)(?:\n|$)', email_block, re.IGNORECASE)
                if preview_match:
                    email['snippet'] = preview_match.group(1).strip()[:MAX_SNIPPET_LENGTH]
                else:
                    # Try to extract from non-metadata lines
                    lines = email_block.split('\n')
                    preview_lines = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith(('From:', 'Time:', 'Subject:', 'Preview:', '**', '[UNREAD]', '[READ]')):
                            preview_lines.append(line)
                            if len(preview_lines) >= 2:
                                break
                    if preview_lines:
                        email['snippet'] = ' '.join(preview_lines)[:200]
                
                # CRITICAL: Only add email if it has valid sender AND subject (both required)
                if email.get('sender') and email.get('sender').strip() and email.get('subject') and email.get('subject').strip():
                    # Additional validation: ensure sender is not "Unknown" or empty
                    sender = email.get('sender', '').strip()
                    subject = email.get('subject', '').strip()
                    if sender and sender != 'Unknown' and subject and subject != 'No Subject':
                        emails.append(email)
                    else:
                        logger.warning(f"[EMAIL] Skipping email with invalid sender/subject: sender='{sender}', subject='{subject}'")
        
        # If no numbered matches found, try [EMAIL] marker format
        if not emails:
            email_blocks = re.split(r'\[EMAIL\]\s*\n?', formatted_result)
            
            for block in email_blocks:
                if not block.strip():
                    continue
                
                email = {}
                
                # Extract sender - CRITICAL: Use "From:" field, not subject
                sender_match = re.search(r'From:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
                if sender_match:
                    sender_text = sender_match.group(1).strip()
                    # Ensure we're not accidentally extracting subject as sender
                    if email.get('subject') and sender_text == email.get('subject'):
                        logger.warning(f"[EMAIL] WARNING: Sender matches subject - possible parsing error. Sender: {sender_text}, Subject: {email.get('subject')}")
                    email['sender'] = sender_text
                
                # Extract subject
                subject_match = re.search(r'Subject:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
                if subject_match:
                    email['subject'] = subject_match.group(1).strip()
                
                # Extract date
                date_match = re.search(r'(?:Date|Time):\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
                if date_match:
                    email['date'] = date_match.group(1).strip()
                
                # Extract snippet/preview (first few lines of content)
                lines = block.split('\n')
                snippet_lines = []
                for line in lines:
                    if not line.strip().startswith(('From:', 'Subject:', 'Date:', 'Time:', '[EMAIL]', '[OK]', '[UNREAD]', '[READ]')):
                        snippet_lines.append(line.strip())
                        if len(snippet_lines) >= 3:
                            break
                if snippet_lines:
                    email['snippet'] = ' '.join(snippet_lines)[:200]
                
                # CRITICAL: Only add email if it has valid sender AND subject (both required)
                sender = email.get('sender', '').strip() if email.get('sender') else ''
                subject = email.get('subject', '').strip() if email.get('subject') else ''
                if sender and sender != 'Unknown' and subject and subject != 'No Subject' and subject:
                    emails.append(email)
                else:
                    logger.warning(f"[EMAIL] Skipping email block with invalid sender/subject: sender='{sender}', subject='{subject}'")
        
        return emails
    
    def is_response_conversational(self, response: str) -> bool:
        """Check if a response is conversational (not robotic)"""
        if not response or not response.strip():
            return False
        
        response_lower = response.lower()
        
        # Robotic patterns
        robotic_patterns = [
            '[ok]', '[email]', '[error]', 'i found', 'emails matching your search',
            'gmail search results', 'no emails found'
        ]
        has_robotic = any(pattern in response_lower for pattern in robotic_patterns)
        
        # Conversational indicators
        conversational_indicators = [
            'hey', 'hi', 'looks like', 'it seems', 'you have', "you've got",
            'here are', 'there are', 'i see', 'i notice'
        ]
        has_conversational = any(indicator in response_lower for indicator in conversational_indicators)
        
        return has_conversational and not has_robotic
    
    def force_llm_regeneration(self, query: str, original_result: str, user_first_name: Optional[str] = None) -> str:
        """
        Force LLM regeneration of a response that still contains robotic patterns
        
        Args:
            query: Original user query
            original_result: Original robotic response
            user_first_name: Optional user's first name for personalization
            
        Returns:
            Conversational response generated by LLM
        """
        if not self.llm_client:
            return self.final_cleanup_conversational_response(original_result)
        
        try:
            # Use rich prompt from prompts/conversational_prompts.py
            from ....ai.prompts import EMAIL_GENERAL_RESPONSE_PROMPT
            
            # Add personalization to the rich prompt
            personalization_note = ""
            if user_first_name:
                personalization_note = f"\n\nPERSONALIZATION: The user's name is {user_first_name}. Use their name sparingly - only once or twice in the entire response, or only when it feels truly natural (e.g., at the very beginning like 'Hey {user_first_name}!' or at the end). Do NOT repeat their name in every paragraph - that sounds robotic. Most of the response should NOT include their name."
            
            escaped_query = str(query).replace('{', '{{').replace('}', '}}')
            prompt_template = EMAIL_GENERAL_RESPONSE_PROMPT
            prompt = prompt_template.replace('{query}', escaped_query)
            prompt = prompt + personalization_note
            
            # Add additional instruction to avoid robotic patterns
            prompt = prompt + """

IMPORTANT: Generate a COMPLETELY natural, conversational response that sounds like a real person talking to a friend. Do NOT use any of these robotic patterns:
- "I found X emails" or "I have found X emails"
- "No emails found" or "I found no emails"
- "I searched" or "I have searched"
- "I checked" or "I have checked"
- Technical tags like [OK], [EMAIL], [ERROR], etc.
- Formal phrases like "I have located" or "I have identified"

Instead, use natural, conversational language like:
- "Hey! I see you have..." or "Looks like you've got..."
- "I don't see any..." or "I couldn't find any..."
- "You've got..." or "There are..."
- "I checked..." (not "I have checked")

Make it sound like you're helping a friend, not a robot reporting data. Use contractions when appropriate ("don't", "can't", "it's", "you've"). Vary your sentence structure. Be warm and personable.

Generate a COMPLETE, natural, conversational response. Do NOT truncate. Always end with proper punctuation (. ! or ?)."""
            
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content') and response.content:
                return self.final_cleanup_conversational_response(response.content.strip())
        except Exception as e:
            logger.error(f"[EMAIL] Failed to force LLM regeneration: {e}")
        
        return self.final_cleanup_conversational_response(original_result)
    
    def final_cleanup_conversational_response(self, response: str) -> str:
        """
        Final cleanup pass to remove ALL robotic patterns from conversational responses
        
        This is a comprehensive cleanup that removes:
        - [OK], [EMAIL], [ERROR], [WARNING], [INFO], [SEARCH] prefixes
        - Robotic phrases like "I found X emails matching your search"
        - Numbered lists and excessive formatting
        - Any remaining technical tags
        
        Args:
            response: Response string to clean
            
        Returns:
            Fully cleaned, conversational response
        """
        if not response:
            return response
        
        # CRITICAL: Remove ALL technical tags (case-insensitive, anywhere in text)
        response = re.sub(r'\[OK\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[EMAIL\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[ERROR\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[WARNING\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[INFO\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[SEARCH\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[TIME\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[FROM\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[UNREAD\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[READ\]\s*', '', response, flags=re.IGNORECASE)
        
        # Remove robotic phrases
        response = re.sub(r'I\s+found\s+\d+\s+email.*?matching\s+your\s+search[\.:]?\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'I\s+found\s+1\s+email.*?matching\s+your\s+search[\.:]?\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'Gmail\s+Search\s+Results[\.:]?\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'Email\s+Search\s+Results[\.:]?\s*', '', response, flags=re.IGNORECASE)
        
        # Remove "I'll list your emails" type phrases
        response = re.sub(r"I'll\s+list\s+(your\s+)?emails[\.:]?\s*", '', response, flags=re.IGNORECASE)
        
        # Remove excessive markdown formatting
        response = re.sub(r'\*\*([^*]+)\*\*', r'\1', response)
        response = re.sub(r'\*([^*]+)\*', r'\1', response)
        response = re.sub(r'`([^`]+)`', r'\1', response)
        response = re.sub(r'#+\s*', '', response)  # Remove headers
        
        # Clean up excessive whitespace
        response = re.sub(r'\n{3,}', '\n\n', response)
        response = re.sub(r' {2,}', ' ', response)
        
        # Ensure response doesn't start with technical terms
        response = re.sub(r'^(Error|Warning|Failed|Success|OK|EMAIL):\s*', '', response, flags=re.IGNORECASE)
        
        return response.strip()
