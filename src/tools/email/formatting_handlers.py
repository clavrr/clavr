"""
Email Formatting Handlers

Handles formatting of email lists and conversational responses.
This module centralizes formatting logic to keep the main EmailTool class clean.
"""
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from ...utils.logger import setup_logger
from ...ai.prompts import EMAIL_CONVERSATIONAL_LIST, EMAIL_CONVERSATIONAL_EMPTY
from ...ai.prompts import get_agent_system_prompt
from ...utils.config import Config
from .constants import (
    LIMITS,
    LLM_TEMPERATURE,
    LLM_TEMPERATURE_LOW,
    LLM_MAX_TOKENS
)

logger = setup_logger(__name__)


class EmailFormattingHandlers:
    """
    Handles email formatting operations.
    
    This class centralizes formatting logic to improve maintainability
    and keep the main EmailTool class focused on orchestration.
    """
    
    def __init__(self, email_tool):
        """
        Initialize formatting handlers.
        
        Args:
            email_tool: Parent EmailTool instance for accessing services, config, etc.
        """
        self.email_tool = email_tool
        self.config = email_tool.config if hasattr(email_tool, 'config') else None
        self.email_service = email_tool.email_service if hasattr(email_tool, 'email_service') else None
    
    def format_email_list(
        self,
        emails: List[Dict[str, Any]],
        title: str,
        query: str = ""
    ) -> str:
        """
        Format email list for display with conversational response.
        
        Args:
            emails: List of email dictionaries
            title: Title for the email list
            query: Original query for conversational context
            
        Returns:
            Formatted email list string
        """
        if not emails:
            # Even for no emails, make it conversational
            if query:
                try:
                    from ...ai.llm_factory import LLMFactory
                    from langchain_core.messages import HumanMessage, SystemMessage
                    
                    # Use self.config if available, otherwise fall back to Config.from_env()
                    config = self.config if self.config else Config.from_env()
                    llm = LLMFactory.get_llm_for_provider(config, temperature=LLM_TEMPERATURE)
                    
                    if llm:
                        # Use centralized prompt with AGENT_SYSTEM_PROMPT
                        prompt = EMAIL_CONVERSATIONAL_EMPTY.format(query=query)
                        
                        messages = [
                            SystemMessage(content=get_agent_system_prompt()),
                            HumanMessage(content=prompt)
                        ]
                        response = llm.invoke(messages)
                        response_text = response.content if hasattr(response, 'content') else str(response)
                        
                        if not isinstance(response_text, str):
                            response_text = str(response_text) if response_text else ""
                        
                        if response_text and len(response_text.strip()) > 0:
                            return response_text.strip()
                except Exception as e:
                    logger.debug(f"[EMAIL] Failed to generate conversational 'no emails' response: {e}")
            
            return f"No emails found. Your inbox is clear!"
        
        # CRITICAL: Check if query is asking about email CONTENT (not just listing)
        # Use intelligent LLM-based detection from the existing architecture
        # IMPORTANT: Check for content queries even with multiple emails (user might ask about a specific email)
        should_generate_summary = False
        if query:
            should_generate_summary = self._detect_content_query(query)
            logger.info(f"[EMAIL] Content query detection result: should_generate_summary={should_generate_summary}, query='{query}'")
            
            # If asking about content, try to find the specific email mentioned in the query
            if should_generate_summary:
                logger.info(f"[EMAIL] Content query detected, searching for matching email among {len(emails)} results")
                
                # If we have exactly one email, use it directly
                if len(emails) == 1:
                    summary = self._generate_email_summary(emails[0])
                    if summary:
                        logger.info(f"[EMAIL] Generated summary for single email: {emails[0].get('subject', '')}")
                        return summary
                    else:
                        # Summary generation failed - return error message instead of falling through
                        logger.warning(f"[EMAIL] Failed to generate summary for single email, returning error message")
                        return f"I found the email '{emails[0].get('subject', 'No Subject')}' but couldn't retrieve its content. Please try again."
                else:
                    # Multiple emails - try to find the one matching the query
                    # Extract key terms from query to match against email subjects AND senders
                    query_lower = query.lower()
                    matching_email = None
                    best_match_score = 0
                    
                    # CRITICAL: Extract sender name AND subject from query if mentioned
                    # Example: "What is the email from 'The Core' with the subject 'X' all about?"
                    # Also handles: "What is the Core's email all about?"
                    sender_name = None
                    subject_text = None
                    
                    # Pattern 1: Possessive pattern - "What is the Core's email all about?" → "Core" or "The Core"
                    if "'s email" in query_lower or "s email" in query_lower:
                        # Extract text before "'s email" or "s email"
                        match_idx = query_lower.find("'s email")
                        if match_idx == -1:
                            match_idx = query_lower.find("s email")
                        if match_idx > 0:
                            # Get words before the match (preserve original case)
                            before_match = query[:match_idx].strip()
                            # Extract the last meaningful word/phrase (likely the sender name)
                            # CRITICAL: Include "The" if it's part of the sender name (e.g., "The Core")
                            words = before_match.split()
                            # Skip common words at the end, but keep "The" if it's followed by a capitalized word
                            skip_words = ['a', 'an', 'what', 'is', 'was', 'does', 'did', 'tell', 'me', 'about', 'all', 'the']
                            sender_parts = []
                            reversed_words = list(reversed(words))
                            for i, word in enumerate(reversed_words):
                                word_lower = word.lower()
                                # Keep "The" if it's followed by a capitalized word (likely part of sender name)
                                # When iterating in reverse, the previous word (i-1) is the next word in original order
                                if word_lower == 'the' and i > 0:
                                    next_word_original = reversed_words[i-1]  # Previous in reversed = next in original
                                    if next_word_original and next_word_original[0].isupper():
                                        sender_parts.insert(0, word)
                                elif word_lower not in skip_words:
                                    sender_parts.insert(0, word)
                                elif sender_parts:  # If we already found sender parts, stop
                                    break
                            if sender_parts:
                                sender_name = " ".join(sender_parts)
                                logger.info(f"[EMAIL] Extracted sender from possessive pattern: '{sender_name}'")
                    
                    # Pattern 2: "from" keyword - "What is the email from 'The Core' with the subject 'X' all about?"
                    if "from" in query_lower and not sender_name:
                        # Extract text after "from" until next preposition or end of query
                        from_idx = query_lower.find("from")
                        after_from = query_lower[from_idx + 4:].strip()
                        
                        # Check if subject is mentioned after "from" (e.g., "from X with the subject Y")
                        subject_patterns = [
                            "with the subject",
                            "with subject",
                            "subject",
                            "titled",
                            "titled as"
                        ]
                        
                        subject_idx = None
                        for pattern in subject_patterns:
                            if pattern in after_from:
                                subject_idx = after_from.find(pattern)
                                break
                        
                        if subject_idx is not None:
                            # Extract sender name (stop at subject pattern)
                            sender_text = after_from[:subject_idx].strip()
                            stop_words = ['yesterday', 'today', 'about', 'all', 'the', 'email', 'emails', 'message', 'messages', 'what', 'was', 'is', 'did', 'say', 'with']
                            sender_parts = []
                            for word in sender_text.split():
                                if word in stop_words:
                                    break
                                sender_parts.append(word)
                            if sender_parts:
                                sender_name = " ".join(sender_parts).strip()
                                logger.info(f"[EMAIL] Extracted sender name from query (with subject): '{sender_name}'")
                            
                            # Extract subject (after subject pattern)
                            after_subject_pattern = after_from[subject_idx + len(pattern):].strip()
                            # Extract subject text (handle quotes and stop words)
                            # Try to extract quoted subject first
                            quoted_match = re.search(r'["\']([^"\']+)["\']', after_subject_pattern)
                            if quoted_match:
                                subject_text = quoted_match.group(1)
                                logger.info(f"[EMAIL] Extracted quoted subject from query: '{subject_text}'")
                            else:
                                # Extract subject words until stop words
                                subject_stop_words = ['all', 'about', 'yesterday', 'today', 'what', 'was', 'is', 'did', 'say']
                                subject_parts = []
                                for word in after_subject_pattern.split():
                                    if word in subject_stop_words:
                                        break
                                    subject_parts.append(word)
                                if subject_parts:
                                    subject_text = " ".join(subject_parts)
                                    logger.info(f"[EMAIL] Extracted subject from query: '{subject_text}'")
                        else:
                            # No subject mentioned - just extract sender
                            # CRITICAL: Check for "all about" phrase first, then stop at individual stop words
                            after_from_lower = after_from.lower()
                            if "all about" in after_from_lower:
                                # Stop at "all about" phrase
                                all_about_idx = after_from_lower.find("all about")
                                sender_text = after_from[:all_about_idx].strip()
                            else:
                                sender_text = after_from
                            
                            stop_words = ['yesterday', 'today', 'about', 'all', 'the', 'email', 'emails', 'message', 'messages', 'what', 'was', 'is', 'did', 'say']
                            sender_parts = []
                            for word in sender_text.split():
                                if word.lower() in stop_words:
                                    break
                                sender_parts.append(word)
                            if sender_parts:
                                sender_name = " ".join(sender_parts).strip()
                                logger.info(f"[EMAIL] Extracted sender name from query: '{sender_name}'")
                    
                    # Extract meaningful words from query (skip common words)
                    # Keep words that are 3+ characters and not common stop words
                    query_words = [w for w in query_lower.split() if len(w) >= 3 and w not in [
                        'tell', 'me', 'about', 'the', 'what', 'is', 'was', 'does', 'did', 
                        'from', 'email', 'message', 'more', 'please', 'can', 'you', 'show',
                        'this', 'that', 'these', 'those', 'with', 'for', 'and', 'or', 'but',
                        'yesterday', 'today', 'received', 'all', 'subject', 'titled'
                    ]]
                    
                    logger.info(f"[EMAIL] Extracted query words for matching: {query_words}, sender_name: {sender_name}, subject_text: {subject_text}")
                    
                    # CRITICAL: Clean up sender_name - remove quotes and extra words
                    if sender_name:
                        # Remove quotes if present
                        sender_name = sender_name.strip("'\"")
                        # Remove trailing words like "with", "subject", etc.
                        sender_name = re.sub(r'\s+(with|subject|titled|about|all|the|email|emails).*$', '', sender_name, flags=re.IGNORECASE).strip()
                        logger.info(f"[EMAIL] Cleaned sender name: '{sender_name}'")
                    
                    # CRITICAL: If sender is mentioned, filter to only emails from that sender FIRST
                    # This ensures we prioritize the correct email when user asks "What is the email from X all about?"
                    emails_to_match = emails
                    if sender_name:
                        sender_name_lower = sender_name.lower().strip()
                        emails_from_sender = []
                        logger.info(f"[EMAIL] Filtering emails by sender '{sender_name}' (normalized: '{sender_name_lower}') from {len(emails)} total emails")
                        
                        for email in emails:
                            sender = email.get('from', email.get('sender', ''))
                            sender_lower = sender.lower() if sender else ""
                            # Extract display name from sender if it's in format "Name <email>"
                            display_name = sender.split('<')[0].strip().strip('"\'') if sender else ""
                            display_name_lower = display_name.lower() if display_name else ""
                            
                            # Log first few emails for debugging
                            if len(emails_from_sender) < 3:
                                logger.debug(f"[EMAIL] Checking email from '{display_name}' (normalized: '{display_name_lower}') against sender '{sender_name_lower}'")
                            
                            # Check if sender matches (case-insensitive, flexible matching)
                            # Match if:
                            # 1. Exact match in display name
                            # 2. Sender name contained in display name or vice versa
                            # 3. Individual words from sender name match display name
                            # 4. Sender name matches core words (e.g., "the core" matches "The Core")
                            sender_words = [w for w in sender_name_lower.split() if len(w) >= 2]
                            core_words = [w for w in sender_name_lower.split() if w not in ['the', 'a', 'an']]  # Remove articles
                            
                            matches = (
                                sender_name_lower == display_name_lower or
                                sender_name_lower in display_name_lower or
                                display_name_lower in sender_name_lower or
                                sender_name_lower in sender_lower or
                                sender_lower in sender_name_lower or
                                (len(sender_words) > 0 and all(word in display_name_lower for word in sender_words)) or
                                (len(core_words) > 0 and all(word in display_name_lower for word in core_words))  # Match core words even if "the" is missing
                            )
                            
                            if matches:
                                emails_from_sender.append(email)
                                logger.debug(f"[EMAIL] ✓ Matched email '{email.get('subject', 'No Subject')[:50]}...' from '{display_name}'")
                        
                        if emails_from_sender:
                            emails_to_match = emails_from_sender
                            logger.info(f"[EMAIL] ✓ Filtered to {len(emails_from_sender)} emails from sender '{sender_name}' (out of {len(emails)} total)")
                            # Log the subjects of filtered emails
                            for i, email in enumerate(emails_from_sender[:3]):
                                logger.debug(f"[EMAIL]   [{i+1}] {email.get('subject', 'No Subject')[:60]}...")
                        else:
                            logger.warning(f"[EMAIL] ✗ No emails found from sender '{sender_name}', matching against all {len(emails)} emails")
                            # Log first few email senders for debugging
                            for i, email in enumerate(emails[:5]):
                                sender = email.get('from', email.get('sender', 'Unknown'))
                                display_name = sender.split('<')[0].strip().strip('"\'') if sender else "Unknown"
                                logger.debug(f"[EMAIL]   Sample email [{i+1}] from: '{display_name}'")
                    
                    # CRITICAL: Filter out "No Subject" emails if subject is explicitly mentioned in query
                    # This prevents matching "No Subject" emails when user asks about a specific subject
                    if subject_text:
                        # Filter to only emails with actual subjects (not "No Subject" or empty)
                        emails_with_subjects = [e for e in emails_to_match if e.get('subject', '').strip() and e.get('subject', '').lower() not in ['no subject', '(no subject)', '']]
                        if emails_with_subjects:
                            emails_to_match = emails_with_subjects
                            logger.info(f"[EMAIL] Filtered out {len(emails_to_match) - len(emails_with_subjects)} 'No Subject' emails, matching against {len(emails_with_subjects)} emails with subjects")
                    
                    # Try to find email by subject AND sender match with scoring
                    for email in emails_to_match:
                        subject = email.get('subject', '').lower()
                        sender = email.get('from', email.get('sender', '')).lower()
                        
                        match_score = 0
                        
                        # CRITICAL: If subject is explicitly mentioned, prioritize exact subject match
                        if subject_text:
                            subject_text_lower = subject_text.lower()
                            # Exact subject match (highest priority)
                            if subject_text_lower == subject:
                                match_score += 50  # Very strong boost for exact subject match
                                logger.debug(f"[EMAIL] Exact subject match: '{subject_text}' == '{subject}'")
                            # Subject contains query subject or vice versa
                            elif subject_text_lower in subject or subject in subject_text_lower:
                                match_score += 30  # Strong boost for partial subject match
                                logger.debug(f"[EMAIL] Partial subject match: '{subject_text}' in '{subject}'")
                            # Check individual words from subject
                            subject_text_words = subject_text_lower.split()
                            for word in subject_text_words:
                                if len(word) >= 3 and word in subject:
                                    match_score += 5  # Boost for individual subject word matches
                        
                        # CRITICAL: If query mentions sender, HEAVILY prioritize sender match
                        # This ensures emails from the correct sender ALWAYS rank higher than emails from wrong senders
                        if sender_name:
                            sender_lower = sender.lower()
                            sender_name_lower = sender_name.lower()
                            
                            # Extract display name from sender if it's in format "Name <email>"
                            display_name = sender.split('<')[0].strip().strip('"\'')
                            display_name_lower = display_name.lower() if display_name else ""
                            
                            # Remove articles for core word matching
                            sender_words = sender_name_lower.split()
                            core_words = [w for w in sender_words if w not in ['the', 'a', 'an'] and len(w) >= 2]
                            
                            sender_matched = False
                            
                            # Check multiple matching strategies (in order of priority)
                            # 1. Exact match in display name (highest priority)
                            if sender_name_lower == display_name_lower:
                                match_score += 100  # CRITICAL: Very high score to ensure this email is selected
                                sender_matched = True
                                logger.debug(f"[EMAIL] ✓ Exact sender display name match: '{sender_name}' == '{display_name}' (+100 points)")
                            # 2. Sender name contained in display name or vice versa
                            elif sender_name_lower in display_name_lower or display_name_lower in sender_name_lower:
                                match_score += 80  # CRITICAL: Very high score for partial match
                                sender_matched = True
                                logger.debug(f"[EMAIL] ✓ Partial sender display name match: '{sender_name}' in '{display_name}' (+80 points)")
                            # 3. Core words match (e.g., "the core" matches "The Core" or "Core")
                            elif len(core_words) > 0 and all(word in display_name_lower for word in core_words):
                                match_score += 75  # CRITICAL: High score for core word match
                                sender_matched = True
                                logger.debug(f"[EMAIL] ✓ Core word match: '{core_words}' in '{display_name}' (+75 points)")
                            # 4. Sender name in full sender string (includes email)
                            elif sender_name_lower in sender_lower or sender_lower in sender_name_lower:
                                match_score += 70  # CRITICAL: High score for sender match in full string
                                sender_matched = True
                                logger.debug(f"[EMAIL] ✓ Sender match in full string: '{sender_name}' matches '{sender}' (+70 points)")
                            # 5. Individual words from sender name match
                            elif len(sender_words) > 0 and all(word in display_name_lower for word in sender_words):
                                match_score += 60  # High score for word-by-word match
                                sender_matched = True
                                logger.debug(f"[EMAIL] ✓ Word-by-word sender match: '{sender_words}' in '{display_name}' (+60 points)")
                            
                            # If sender didn't match, heavily penalize this email
                            if not sender_matched:
                                match_score -= 50  # Heavy penalty for wrong sender
                                logger.debug(f"[EMAIL] ✗ Sender mismatch: '{sender_name}' != '{display_name}' (-50 points)")
                            
                            # Additional boost for individual sender words (even if already matched)
                            sender_name_words = sender_name_lower.split()
                            for word in sender_name_words:
                                if len(word) >= 3:
                                    if word in display_name_lower:
                                        match_score += 2  # Small additional boost
                                    elif word in sender_lower:
                                        match_score += 1  # Small additional boost
                        
                        # Count how many query words match the subject (only if subject not explicitly mentioned)
                        if not subject_text:
                            subject_word_matches = sum(1 for word in query_words if word in subject)
                            match_score += subject_word_matches
                            
                            # Boost score if multiple consecutive words match (phrase match)
                            if len(query_words) >= 2:
                                # Check for 2-word phrases
                                for i in range(len(query_words) - 1):
                                    phrase = f"{query_words[i]} {query_words[i+1]}"
                                    if phrase in subject:
                                        match_score += 3  # Strong boost for phrase matches
                            
                            # Also check if subject contains key phrases from query
                            if any(word in subject for word in query_words):
                                match_score += 1  # Small boost for individual word matches
                        
                        # CRITICAL: Penalize "No Subject" emails heavily when subject is mentioned
                        if subject_text and (not subject or subject in ['no subject', '(no subject)', '']):
                            match_score -= 100  # Heavy penalty for "No Subject" when subject is explicitly mentioned
                            logger.debug(f"[EMAIL] Penalized 'No Subject' email (subject was mentioned in query)")
                        
                        logger.debug(f"[EMAIL] Email '{subject[:50]}...' from '{sender[:30]}...' match score: {match_score}")
                        
                        if match_score > best_match_score:
                            best_match_score = match_score
                            matching_email = email
                            logger.debug(f"[EMAIL] New best match: '{matching_email.get('subject', 'No Subject')[:50]}...' (score: {best_match_score})")
                    
                    # Log the best match found
                    if matching_email:
                        logger.info(f"[EMAIL] Best matching email: '{matching_email.get('subject', 'No Subject')}' from '{matching_email.get('from', 'Unknown')}' (score: {best_match_score})")
                    else:
                        logger.warning(f"[EMAIL] No matching email found after scoring {len(emails_to_match)} emails")
                    
                    # CRITICAL: When subject is explicitly mentioned, require higher match score
                    # This prevents "No Subject" emails from being selected
                    min_match_score = 20 if subject_text else 1  # Require at least 20 points if subject mentioned
                    
                    # CRITICAL: If sender is mentioned and we successfully filtered emails, use the first email from that sender
                    # This handles queries like "What is the email from The Core all about?"
                    # IMPORTANT: Only use filtered emails if filtering actually worked (reduced count)
                    if sender_name and emails_to_match and len(emails_to_match) < len(emails):
                        # We successfully filtered to emails from the sender - use the first one (most recent)
                        logger.info(f"[EMAIL] ✓ Sender '{sender_name}' mentioned, using first email from filtered list ({len(emails_to_match)} emails): {emails_to_match[0].get('subject', '')}")
                        summary = self._generate_email_summary(emails_to_match[0])
                        if summary:
                            logger.info(f"[EMAIL] ✓ Generated summary for email from sender '{sender_name}': {emails_to_match[0].get('subject', '')}")
                            return summary
                        else:
                            logger.warning(f"[EMAIL] ✗ Failed to generate summary for email from sender '{sender_name}'")
                            return f"I found the email '{emails_to_match[0].get('subject', 'No Subject')}' from {sender_name} but couldn't retrieve its content. Please try again."
                    
                    # If found matching email with good score, generate summary for it
                    if matching_email and best_match_score >= min_match_score:
                        summary = self._generate_email_summary(matching_email)
                        if summary:
                            logger.info(f"[EMAIL] Generated summary for matching email (score: {best_match_score}, min_required: {min_match_score}): {matching_email.get('subject', '')}")
                            return summary
                        else:
                            # Summary generation failed - return error message
                            logger.warning(f"[EMAIL] Failed to generate summary for matching email: {matching_email.get('subject', '')}")
                            return f"I found the email '{matching_email.get('subject', 'No Subject')}' but couldn't retrieve its content. Please try again."
                    elif matching_email and best_match_score < min_match_score:
                        # Match found but score too low (likely "No Subject" email when subject was mentioned)
                        logger.warning(f"[EMAIL] Match found but score too low ({best_match_score} < {min_match_score}), likely 'No Subject' email. Subject was explicitly mentioned: '{subject_text}'")
                        # Return helpful error message asking user to be more specific
                        return f"I found emails from '{sender_name if sender_name else 'the sender'}' but couldn't find one with the subject '{subject_text}'. Could you check if the subject is correct, or try asking about a different email?"
                    else:
                        # No exact match - use first email if query explicitly asks about "the email" or "this email"
                        if any(phrase in query_lower for phrase in ['the email', 'this email', 'that email', 'it', 'the one']):
                            summary = self._generate_email_summary(emails_to_match[0] if emails_to_match else emails[0])
                            if summary:
                                logger.info(f"[EMAIL] Generated summary for first email (explicit reference): {(emails_to_match[0] if emails_to_match else emails[0]).get('subject', '')}")
                                return summary
                            else:
                                logger.warning(f"[EMAIL] Failed to generate summary for first email (explicit reference)")
                                return f"I found the email '{(emails_to_match[0] if emails_to_match else emails[0]).get('subject', 'No Subject')}' but couldn't retrieve its content. Please try again."
                        else:
                            # CRITICAL: If sender is mentioned but no exact match, still try to summarize first email from that sender
                            if sender_name and emails_to_match:
                                logger.info(f"[EMAIL] Sender '{sender_name}' mentioned, summarizing first email from filtered list")
                                summary = self._generate_email_summary(emails_to_match[0])
                                if summary:
                                    logger.info(f"[EMAIL] Generated summary for first email from sender: {emails_to_match[0].get('subject', '')}")
                                    return summary
                            
                            # Try first email anyway if content query detected
                            logger.info(f"[EMAIL] No exact match found, trying first email for content query")
                            summary = self._generate_email_summary(emails_to_match[0] if emails_to_match else emails[0])
                            if summary:
                                logger.info(f"[EMAIL] Generated summary for first email: {(emails_to_match[0] if emails_to_match else emails[0]).get('subject', '')}")
                                return summary
                            else:
                                # Summary generation failed - return helpful error
                                logger.warning(f"[EMAIL] Failed to generate summary for first email")
                                return f"I found {len(emails)} email(s) but couldn't determine which one you're asking about. Could you be more specific about which email you'd like me to summarize?"
                
                # CRITICAL: If we're in a content query block but haven't returned yet,
                # we should still try to generate a summary for the first email
                # This handles edge cases where matching logic didn't find a match
                logger.warning(f"[EMAIL] Content query detected but no summary generated yet. Attempting summary for first email as fallback.")
                if emails:
                    summary = self._generate_email_summary(emails[0])
                    if summary:
                        logger.info(f"[EMAIL] Generated summary for first email (fallback): {emails[0].get('subject', '')}")
                        return summary
                    else:
                        logger.warning(f"[EMAIL] Failed to generate summary for first email (fallback)")
                        return f"I found {len(emails)} email(s) but couldn't retrieve the content. Please try again or be more specific about which email you'd like me to summarize."
                else:
                    return "I couldn't find any emails to summarize. Please check your query and try again."
        
        # Try conversational response (but only if not a content query)
        if query and not should_generate_summary:
            conversational = self._generate_conversational_email_list_response(emails, query, title)
            if conversational:
                return conversational
        
        # Fallback to natural sentence format (NOT robotic, with bold subjects)
        # Create a natural sentence instead of bullet points
        # For "today" queries, include ALL emails (not just 10) to avoid truncation
        query_lower = query.lower() if query else ""
        is_today_query = "today" in query_lower or "new emails" in query_lower
        max_emails_for_fallback = len(emails) if is_today_query else min(LIMITS.MAX_EMAILS_FOR_DISPLAY, len(emails))
        
        email_descriptions = []
        for email in emails[:max_emails_for_fallback]:
            subject = email.get('subject', 'No Subject')
            sender = email.get('from', email.get('sender', 'Unknown'))
            
            # Format email subject in bold
            email_desc = f"**{subject}**"
            
            # Add sender information
            if sender and sender != 'Unknown':
                # Extract name from email if it's in format "Name <email>"
                sender_name = sender.split('<')[0].strip().strip('"\'')
                if sender_name:
                    email_desc += f" from {sender_name}"
                else:
                    # Use email address if no name
                    email_addr = sender.split('<')[-1].strip('>').strip()
                    email_desc += f" from {email_addr}"
            
            email_descriptions.append(email_desc)
        
        # Create natural sentence format
        if len(email_descriptions) == 1:
            return f"You've got {email_descriptions[0]} in your inbox."
        elif len(email_descriptions) == 2:
            return f"You've got {email_descriptions[0]} and {email_descriptions[1]} in your inbox."
        else:
            first_few = ", ".join(email_descriptions[:-1])
            last_one = email_descriptions[-1]
            if len(emails) > LIMITS.MAX_EMAILS_FOR_DISPLAY:
                return f"You've got {first_few}, and {last_one} in your inbox. That's {len(emails)} emails total."
            else:
                return f"You've got {first_few}, and {last_one} in your inbox."
    
    def _generate_conversational_email_list_response(
        self,
        emails: List[Dict[str, Any]],
        query: str,
        context_title: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a natural, conversational response for email lists using LLM.
        
        Returns None if LLM generation fails (caller should use fallback).
        """
        try:
            from ...ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage, SystemMessage
            import json
            
            # Use self.config if available, otherwise fall back to Config.from_env()
            config = self.config if self.config else Config.from_env()
            llm = LLMFactory.get_llm_for_provider(config, temperature=LLM_TEMPERATURE)
            if not llm:
                return None
            
            # Prepare email data for LLM
            # CRITICAL: Check if query asks for "the last email" or "last email" (singular)
            query_lower = query.lower() if query else ""
            is_last_email_query = (
                "the last email" in query_lower or
                "last email" in query_lower or
                "most recent email" in query_lower or
                "latest email" in query_lower
            ) and "emails" not in query_lower
            
            # If asking for "the last email", limit to ONLY the first email (most recent)
            if is_last_email_query and len(emails) > 1:
                logger.info(f"[EMAIL] Query asks for 'the last email' but got {len(emails)} results - limiting to first email only")
                emails = emails[:1]
            
            # For "today" queries, include ALL emails (not just 10) to avoid truncation
            is_today_query = "today" in query_lower or "new emails" in query_lower
            # Use all emails for today queries, otherwise limit to reasonable number for context
            max_emails_for_llm = len(emails) if is_today_query else min(LIMITS.MAX_EMAILS_FOR_LLM_CONTEXT, len(emails))
            logger.info(f"[EMAIL] Including {max_emails_for_llm} emails in LLM context (total: {len(emails)}, is_today_query: {is_today_query}, is_last_email_query: {is_last_email_query})")
            
            email_summaries = []
            for email in emails[:max_emails_for_llm]:
                subject = email.get('subject', 'No Subject')
                sender = email.get('from', email.get('sender', 'Unknown'))
                date = email.get('date', 'Unknown date')
                # CRITICAL: Use full body content from index, not just snippet
                body_content = email.get('body', '') or email.get('snippet', '')
                
                email_summaries.append({
                    'subject': subject,
                    'from': sender,
                    'date': date,
                    'preview': body_content[:LIMITS.PREVIEW_LENGTH_FOR_EMAIL] if body_content else '',
                    'full_content': body_content  # Include full body for content queries
                })
            
            # Get current time for context
            from ...core.calendar.utils import get_user_timezone
            import pytz
            user_tz_name = get_user_timezone(self.config if hasattr(self, 'config') else None)
            user_tz = pytz.timezone(user_tz_name)
            now = datetime.now(user_tz)
            current_time = now.strftime('%I:%M %p').lstrip('0')
            current_date = now.strftime('%A, %B %d, %Y')
            
            # Count unread emails
            unread_count = sum(1 for e in emails if e.get('is_unread', False))
            
            # CRITICAL: Tell LLM about total email count and ensure it mentions ALL emails
            # BUT: If asking for "the last email", focus ONLY on the first email
            include_all_note = ""
            if is_last_email_query:
                include_all_note = f"\n\nCRITICAL: The user asked about 'the last email' (singular). Focus ONLY on the FIRST email in the list below. Do NOT mention any other emails - the user specifically asked for 'the last email' only."
            elif is_today_query and len(emails) > max_emails_for_llm:
                include_all_note = f"\n\nCRITICAL: The user asked about 'new emails today'. You are seeing {max_emails_for_llm} emails in the list below, but there are {len(emails)} total emails. Make sure to mention ALL {len(emails)} emails in your response. Group them by sender or topic if helpful, but don't skip any."
            elif is_today_query:
                include_all_note = f"\n\nCRITICAL: The user asked about 'new emails today'. Make sure to mention ALL {len(emails)} emails in your response. Don't skip any - provide a comprehensive summary."
            
            # Use centralized prompt with get_agent_system_prompt() for consistency
            prompt = EMAIL_CONVERSATIONAL_LIST.format(
                query=query,
                current_time=current_time,
                current_date=current_date,
                email_count=len(emails),
                unread_count=unread_count,
                emails_json=json.dumps(email_summaries, indent=2)
            )
            
            # Add note about including all emails if needed
            if include_all_note:
                prompt += include_all_note

            # Use SystemMessage with get_agent_system_prompt() for better conversational responses
            messages = [
                SystemMessage(content=get_agent_system_prompt()),
                HumanMessage(content=prompt)
            ]
            
            # Use LLM with sufficient max_tokens to prevent truncation
            try:
                # Use enhanced LLM with full max_tokens for email list responses
                enhanced_llm = LLMFactory.get_llm_for_provider(
                    config,
                    temperature=LLM_TEMPERATURE,
                    max_tokens=LLM_MAX_TOKENS
                )
                response = enhanced_llm.invoke(messages)
                logger.info(f"[EMAIL] Using enhanced LLM with max_tokens={LLM_MAX_TOKENS} for email list ({len(emails)} emails)")
            except Exception as e:
                logger.warning(f"[EMAIL] Failed to create enhanced LLM, using default: {e}")
                response = llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text and len(response_text.strip()) > 0:
                # Check if response is too robotic (contains patterns we want to avoid)
                robotic_patterns = [
                    r'You have \d+ emails?:',
                    r'^\*\*.*\*\*\s*\(\d+ emails?\)',
                    r'^\d+\.\s',  # Numbered list at start
                    r'^\s*[\*\-]\s',  # Bullet points at start
                ]
                
                # CRITICAL: Check if email subjects are in quotes instead of bold
                # Pattern to detect quoted email subjects: "subject" or 'subject'
                quoted_subject_patterns = [
                    r'"[^"]*"',  # Double quotes
                    r"'[^']*'",  # Single quotes
                ]
                
                # Check if response contains quoted subjects (but allow quotes in other contexts)
                # We're looking for patterns like "project update" or 'meeting reminder'
                has_quoted_subjects = False
                for pattern in quoted_subject_patterns:
                    matches = re.findall(pattern, response_text)
                    # If we find quoted strings that look like email subjects (not just punctuation)
                    for match in matches:
                        # Remove quotes to check content
                        content = match.strip('"\'')
                        # If it's a reasonable length and doesn't look like punctuation, it might be an email subject
                        if len(content) > 3 and not content.startswith(('(', '[', '{')):
                            # Check if this quoted string appears near email-related words
                            context = response_text[max(0, response_text.find(match) - 50):min(len(response_text), response_text.find(match) + len(match) + 50)]
                            if any(word in context.lower() for word in ['email', 'from', 'about', 'subject', 'inbox', 'got', 'have', 'you', 'your']):
                                has_quoted_subjects = True
                                break
                    if has_quoted_subjects:
                        break
                
                is_robotic = any(re.search(pattern, response_text, re.MULTILINE) for pattern in robotic_patterns)
                
                if not is_robotic and not has_quoted_subjects:
                    logger.info(f"[EMAIL] Generated conversational email list response")
                    return response_text.strip()
                else:
                    if has_quoted_subjects:
                        # LLM used quotes instead of bold formatting - fallback to formatted list
                        # This is expected behavior, not an error - just using fallback formatting
                        logger.debug(f"[EMAIL] LLM response contains quoted email subjects instead of bold, using fallback formatting")
                    else:
                        logger.debug(f"[EMAIL] LLM response was too robotic, using fallback formatting")
                    return None
            
        except Exception as e:
            logger.warning(f"[EMAIL] Failed to generate conversational email list response: {e}")
            return None
    
    def _generate_email_summary(self, email: Dict[str, Any]) -> Optional[str]:
        """
        Generate summary for a single email when user asks about content.
        
        Args:
            email: Email dictionary
            
        Returns:
            Summary string or None if generation fails
        """
        try:
            message_id = email.get('id')
            sender = email.get('from', email.get('sender', 'Unknown'))
            subject = email.get('subject', '')
            
            if not message_id or not self.email_service:
                return None
            
            # CRITICAL: Prioritize index content - emails from index already have full body
            email_source = email.get('_source', 'unknown')
            body_content = email.get('body', '') or email.get('snippet', '')
            
            logger.info(f"[EMAIL] Initial body content check: source={email_source}, has_body={bool(email.get('body'))}, body_len={len(body_content)}, snippet_len={len(email.get('snippet', ''))}")
            
            # CRITICAL: If email is from index, trust the index content (it already has full body)
            # Only fetch from Gmail API if:
            # 1. Email is NOT from index (from Gmail API directly)
            # 2. AND we don't have body content or it's too short
            # 3. AND we have a message_id to fetch
            is_from_index = email_source in ['index', 'hybrid_graphrag', 'neo4j_direct']
            
            if is_from_index:
                # Trust index content - it already has the full body
                logger.info(f"[EMAIL] Email is from index (source: {email_source}), using index body content (len: {len(body_content)})")
                if not body_content or len(body_content.strip()) == 0:
                    logger.warning(f"[EMAIL] Index email has empty body content, but still from index - may be a data issue")
            elif not body_content or len(body_content) < LIMITS.MIN_BODY_LENGTH_THRESHOLD:
                # Email is from Gmail API and doesn't have full body - fetch it
                logger.info(f"[EMAIL] Email is from Gmail API (source: {email_source}), fetching full body (current_len: {len(body_content)})")
                try:
                    full_email = self.email_service.get_email(message_id)
                    if full_email:
                        # Prefer full body over snippet
                        body_content = full_email.get('body', '') or full_email.get('snippet', '')
                        logger.info(f"[EMAIL] Fetched full body from Gmail API: len={len(body_content)}")
                    else:
                        logger.warning(f"[EMAIL] Could not fetch email {message_id} from Gmail API")
                except Exception as e:
                    logger.warning(f"[EMAIL] Error fetching email body from Gmail API: {e}")
                    # Continue with existing body_content if available
            
            # CRITICAL: Generate summary if we have ANY body content (even if short)
            # The LLM can still summarize short content, and we want to provide what we have
            if not body_content or len(body_content.strip()) == 0:
                return None
            
            logger.info(f"[EMAIL] Generating summary for email content query (body length: {len(body_content)}, source: {'index' if email.get('body') else 'gmail_api'})")
            
            # Use LLM to generate summary
            from ...ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage, SystemMessage
            from ...ai.prompts import EMAIL_SUMMARY_SINGLE
            
            config = self.config if self.config else Config.from_env()
            llm_client = LLMFactory.get_llm_for_provider(config, temperature=LLM_TEMPERATURE_LOW)
            
            if not llm_client:
                return None
            
            summary_prompt = EMAIL_SUMMARY_SINGLE.format(
                sender=sender,
                subject=subject,
                body=body_content[:LIMITS.MAX_BODY_LENGTH_FOR_PROMPT],
                length_guidance="comprehensive"
            )
            
            messages = [
                SystemMessage(content="You are a helpful personal assistant."),
                HumanMessage(content=summary_prompt)
            ]
            
            response = llm_client.invoke(messages)
            summary_text = response.content if hasattr(response, 'content') else str(response)
            
            if summary_text and len(summary_text.strip()) > 0:
                logger.info(f"[EMAIL] Generated email content summary ({len(summary_text)} chars)")
                return summary_text.strip()
            
            return None
        except Exception as e:
            logger.warning(f"[EMAIL] Failed to generate email content summary: {e}", exc_info=True)
            return None
    
    def _detect_content_query(self, query: str) -> bool:
        """
        Detect if query is asking about email content (not just listing).
        
        Args:
            query: User query string
            
        Returns:
            True if query is asking about content, False otherwise
        """
        try:
            # Use the intelligent classification handler from the existing architecture
            from ...agent.parsers.email.classification_handlers import EmailClassificationHandlers
            from ...ai.llm_factory import LLMFactory
            
            config = self.config if self.config else Config.from_env()
            llm_client = LLMFactory.get_llm_for_provider(config, temperature=LLM_TEMPERATURE_LOW)
            
            if not llm_client:
                return False
            
            try:
                # Create minimal parser wrapper for classification handler
                class ParserWrapper:
                    def __init__(self, llm_client):
                        self.llm_client = llm_client
                        self.learning_system = None  # Not needed for detection
                
                temp_parser = ParserWrapper(llm_client)
                classification_handler = EmailClassificationHandlers(temp_parser)
                
                # Use intelligent LLM-based detection (no hardcoded patterns)
                what_about_detection = classification_handler.detect_what_about_query(query)
                asks_what_about = what_about_detection.get("asks_what_about", False)
                asks_summary = what_about_detection.get("asks_summary", False)
                confidence = what_about_detection.get("confidence", 0.0)
                reasoning = what_about_detection.get("reasoning", "No reasoning provided")
                
                # Use LLM detection result - trust the intelligent architecture
                should_generate_summary = asks_what_about or asks_summary
                
                logger.info(f"[EMAIL] Intelligent content query detection: asks_what_about={asks_what_about}, asks_summary={asks_summary}, confidence={confidence}, should_summarize={should_generate_summary}, reasoning={reasoning}")
                return should_generate_summary
            except Exception as e:
                logger.debug(f"[EMAIL] LLM-based detection failed: {e}")
                return False
        except Exception as e:
            logger.debug(f"[EMAIL] Content query detection failed: {e}")
            return False

