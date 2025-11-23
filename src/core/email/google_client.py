"""
Google Gmail API Client
Provides methods to interact with Gmail API with automatic retry logic
"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ...utils.logger import setup_logger
from ...utils.config import Config
from ...utils.api import get_api_url_with_fallback
from ...utils import retry_gmail_api
from ...utils import (
    with_gmail_circuit_breaker,
    gmail_list_fallback,
    ServiceUnavailableError
)
from ..base import BaseGoogleAPIClient
from .utils import (
    extract_headers,
    extract_message_body,
    format_message_from_gmail,
    create_gmail_message
)
from .gmail_constants import GMAIL_FOLDERS

# Constants for Gmail client operations
DEFAULT_MAX_RESULTS = 10
DEFAULT_SENT_EMAILS_LIMIT = 100
MIN_BODY_LENGTH_FOR_PROFILE = 50
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_FORBIDDEN = 403
HTTP_STATUS_UNAUTHORIZED = 401

logger = setup_logger(__name__)


class GoogleGmailClient(BaseGoogleAPIClient):
    """
    Google Gmail API client
    
    Provides methods to interact with Gmail:
    - List messages
    - Read messages
    - Send messages
    - Search messages
    - Manage labels
    """
    
    def _build_service(self) -> Any:
        """Build Gmail API service"""
        return build('gmail', 'v1', credentials=self.credentials)
    
    def _get_required_scopes(self) -> List[str]:
        """Get required Gmail scopes"""
        return [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/gmail.modify'
        ]
    
    def _get_service_name(self) -> str:
        """Get service name"""
        return "Gmail"
    
    # ========== Retry-Protected API Methods ==========
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _list_messages_with_retry(
        self,
        query: str,
        max_results: int,
        label_ids: List[str]
    ) -> Dict[str, Any]:
        """
        List messages with automatic retry on transient errors and circuit breaker protection
        
        Args:
            query: Search query
            max_results: Maximum results
            label_ids: Label IDs to search
            
        Returns:
            API response with message list
        """
        return self.service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results,
            labelIds=label_ids
        ).execute()
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _get_message_with_retry(self, message_id: str, format: str = 'full') -> Dict[str, Any]:
        """
        Get a message with automatic retry on transient errors and circuit breaker protection
        
        Args:
            message_id: Message ID
            format: Message format (full, metadata, minimal, raw)
            
        Returns:
            Message details
        """
        return self.service.users().messages().get(
            userId='me',
            id=message_id,
            format=format
        ).execute()
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _send_message_with_retry(self, message: Dict[str, str]) -> Dict[str, Any]:
        """
        Send a message with automatic retry on transient errors and circuit breaker protection
        
        Args:
            message: Gmail message object
            
        Returns:
            Sent message details
        """
        return self.service.users().messages().send(
            userId='me',
            body=message
        ).execute()
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _create_draft_with_retry(self, message: Dict[str, str]) -> Dict[str, Any]:
        """
        Create a draft with automatic retry on transient errors and circuit breaker protection
        
        Args:
            message: Gmail message object
            
        Returns:
            Draft details
        """
        return self.service.users().drafts().create(
            userId='me',
            body={'message': message}
        ).execute()
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _get_thread_with_retry(self, thread_id: str) -> Dict[str, Any]:
        """
        Get a thread with automatic retry on transient errors and circuit breaker protection
        
        Args:
            thread_id: Thread ID
            
        Returns:
            Thread details with all messages
        """
        return self.service.users().threads().get(
            userId='me',
            id=thread_id,
            format='full'
        ).execute()
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _modify_message_with_retry(
        self,
        message_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Modify message labels with automatic retry on transient errors and circuit breaker protection
        
        Args:
            message_id: Message ID
            add_labels: Label IDs to add
            remove_labels: Label IDs to remove
            
        Returns:
            Modified message details
        """
        body = {}
        if add_labels:
            body['addLabelIds'] = add_labels
        if remove_labels:
            body['removeLabelIds'] = remove_labels
        
        return self.service.users().messages().modify(
            userId='me',
            id=message_id,
            body=body
        ).execute()
    
    @with_gmail_circuit_breaker()
    @retry_gmail_api()
    def _batch_get_messages_with_retry(
        self,
        message_ids: List[str],
        format: str = 'full'
    ) -> List[Dict[str, Any]]:
        """
        Batch get multiple messages with automatic retry and circuit breaker protection
        
        This uses the Gmail API's batch request capability to fetch multiple messages
        in a single HTTP request, significantly reducing latency and avoiding N+1 queries.
        
        Falls back to individual requests if batch API returns 404 errors.
        
        Args:
            message_ids: List of message IDs to fetch
            format: Message format (full, metadata, minimal, raw)
            
        Returns:
            List of message details
        """
        from googleapiclient.http import BatchHttpRequest
        from googleapiclient.errors import HttpError
        
        messages = []
        errors = []
        
        def callback(request_id, response, exception):
            """Callback for batch request"""
            if exception is not None:
                errors.append({
                    'request_id': request_id,
                    'error': str(exception)
                })
                logger.warning(f"Error fetching message {request_id}: {exception}")
            else:
                messages.append(response)
        
        try:
            # Create batch request
            batch = BatchHttpRequest(callback=callback)
            
            # Add all message requests to the batch
            for msg_id in message_ids:
                batch.add(
                    self.service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format=format
                    )
                )
            
            # Execute batch request (single HTTP call for all messages)
            batch.execute()
            
            if errors:
                logger.warning(f"Batch request had {len(errors)} errors out of {len(message_ids)} messages")
            
            return messages
            
        except HttpError as e:
            # Gmail batch API sometimes returns 404 - fall back to individual requests
            # This is expected behavior, not an error - Gmail API has limitations
            if e.resp.status == HTTP_STATUS_NOT_FOUND:
                logger.debug(f"Gmail batch API returned 404 (expected), falling back to individual requests for {len(message_ids)} messages")
                return self._fetch_messages_individually(message_ids, format)
            raise
        except Exception as e:
            # For any other batch error, fall back to individual requests
            # This is a fallback mechanism, not necessarily an error
            logger.debug(f"Batch request failed ({type(e).__name__}), falling back to individual requests: {e}")
            return self._fetch_messages_individually(message_ids, format)
    
    def _fetch_messages_individually(
        self,
        message_ids: List[str],
        format: str = 'full'
    ) -> List[Dict[str, Any]]:
        """
        Fetch messages one by one (fallback for batch API failures)
        
        Args:
            message_ids: List of message IDs to fetch
            format: Message format (full, metadata, minimal, raw)
            
        Returns:
            List of message details
        """
        messages = []
        for msg_id in message_ids:
            try:
                message = self.service.users().messages().get(
                    userId='me',
                    id=msg_id,
                    format=format
                ).execute()
                messages.append(message)
            except Exception as e:
                logger.warning(f"Failed to fetch message {msg_id}: {e}")
                # Continue with other messages
                continue
        
        logger.info(f"Fetched {len(messages)}/{len(message_ids)} messages individually")
        return messages
    
    # ========== Public API Methods ==========
    
    def list_messages(
        self,
        query: str = "",
        max_results: int = DEFAULT_MAX_RESULTS,
        label_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        List messages from Gmail with automatic retry on transient errors
        
        Args:
            query: Search query (Gmail search syntax)
            max_results: Maximum number of messages to return
            label_ids: List of label IDs to search (default: INBOX)
            
        Returns:
            List of message dictionaries
        """
        if not self.is_available():
            logger.warning("Gmail service not available")
            return []
        
        try:
            if label_ids is None:
                label_ids = [GMAIL_FOLDERS['inbox']]
            
            # For empty query, ensure we're using labelIds properly
            # Empty query + labelIds should return all messages with that label
            if not query or query.strip() == "":
                logger.debug(f"[GMAIL] Empty query detected - using labelIds only: {label_ids}")
            
            # List messages with retry logic
            results = self._list_messages_with_retry(
                query=query if query else "",
                max_results=max_results,
                label_ids=label_ids
            )
            
            messages = results.get('messages', [])
            
            if not messages:
                logger.info("No messages found")
                return []
            
            # Extract message IDs
            message_ids = [msg['id'] for msg in messages]
            
            # Batch get all message details in a SINGLE API call (fixes N+1 query problem)
            logger.debug(f"[GMAIL] Batch fetching {len(message_ids)} messages in single API call")
            detailed_msgs = self._batch_get_messages_with_retry(
                message_ids=message_ids,
                format='full'
            )
            
            # Format messages using utility function
            detailed_messages = []
            for msg_detail in detailed_msgs:
                try:
                    formatted_message = format_message_from_gmail(msg_detail, include_internal_date=True)
                    detailed_messages.append(formatted_message)
                except Exception as e:
                    logger.warning(f"Failed to format message: {e}")
                    continue
            
            logger.info(f"Retrieved {len(detailed_messages)} messages from Gmail using batch API (1 request instead of {len(message_ids)+1})")
            return detailed_messages
            
        except HttpError as e:
            error_str = str(e)
            error_details = getattr(e, 'error_details', {})
            
            # Check for Account Restricted error (Google Workspace admin restriction)
            # Only log this if we have credentials (user is authenticated)
            # If no credentials, this is expected and we shouldn't log a warning
            if 'Account Restricted' in error_str or 'access_denied' in error_str.lower():
                if 'Account Restricted' in error_str:
                    # Only log restriction warning if we have credentials (user authenticated)
                    # If no credentials, this is expected behavior
                    if self.credentials:
                        if not hasattr(self, '_account_restricted_logged'):
                            logger.error(
                                "🚫 Gmail API access is RESTRICTED by your Google Workspace admin."
                            )
                            logger.error(
                                "   This prevents fetching emails directly from Gmail API."
                            )
                            logger.info(
                                "   To resolve: Contact your Google Workspace admin to allow access to: "
                                "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
                            )
                            logger.info(
                                "   Alternative: Use RAG semantic search if emails are already indexed."
                            )
                            self._account_restricted_logged = True
                    # Return empty list silently to avoid log spam
                    return []
            
            if e.resp.status == HTTP_STATUS_FORBIDDEN:
                if 'invalid_scope' in error_str.lower():
                    logger.error("Gmail API error: OAuth token missing required Gmail scopes")
                    api_url = get_api_url_with_fallback(self)
                    logger.info(f"Please re-authenticate with Gmail permissions at: {api_url}/auth/google/login")
                elif 'disabled' in error_str.lower() or 'not enabled' in error_str.lower():
                    logger.error("Gmail API is not enabled")
                    logger.info("Enable it at: https://console.cloud.google.com/apis/library/gmail.googleapis.com")
                else:
                    logger.error(f"Gmail API access denied ({HTTP_STATUS_FORBIDDEN}): {error_str}")
            elif e.resp.status == HTTP_STATUS_UNAUTHORIZED:
                logger.error("Gmail API authentication failed (401)")
                api_url = get_api_url_with_fallback(self)
                logger.info(f"Please re-authenticate at: {api_url}/auth/google/login")
            else:
                logger.error(f"Gmail API error ({e.resp.status}): {error_str}")
            return []
        except Exception as e:
            error_str = str(e)
            # Check for Account Restricted in exception message
            # Only log this if we have credentials (user is authenticated)
            if 'Account Restricted' in error_str or 'access_denied' in error_str.lower():
                if self.credentials:  # Only log if user is authenticated
                    if not hasattr(self, '_account_restricted_logged'):
                        logger.warning(
                            "⚠️  Gmail API access is restricted by your Google Workspace admin. "
                            "Email indexing will be skipped."
                        )
                        logger.info(
                            "To resolve this, contact your Google Workspace admin to allow access to: "
                            "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
                        )
                        self._account_restricted_logged = True
                return []
            logger.error(f"Failed to list Gmail messages: {e}")
            return []
    
    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        schedule_time: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Send a message via Gmail (with optional scheduling)
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body
            cc: CC recipients (optional)
            bcc: BCC recipients (optional)
            schedule_time: Optional datetime to schedule email send (creates draft if provided)
            
        Returns:
            Sent message details or None if failed
        """
        if not self.is_available():
            logger.warning("Gmail service not available")
            return None
        
        try:
            # Create message using utility function
            message = create_gmail_message(to, subject, body, cc, bcc)
            
            # If scheduling, create draft instead of sending immediately
            if schedule_time:
                return self._schedule_message(message, schedule_time, to, subject)
            
            # Send message immediately
            sent_message = self._send_message_with_retry(message)
            
            logger.info(f"[OK] Sent Gmail message to {to}")
            return sent_message
            
        except HttpError as e:
            logger.error(f"Error sending Gmail message: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to send Gmail message: {e}")
            return None
    
    def _schedule_message(
        self,
        message: Dict[str, str],
        schedule_time: datetime,
        to: str,
        subject: str
    ) -> Optional[Dict[str, Any]]:
        """
        Schedule an email by creating a draft with send date
        
        Note: Gmail doesn't natively support scheduled send via API.
        This creates a draft that can be scheduled using Gmail's "Schedule Send" feature
        or external scheduling tools.
        
        Args:
            message: Gmail message object
            schedule_time: When to send the email
            to: Recipient (for logging)
            subject: Subject (for logging)
            
        Returns:
            Draft message details
        """
        try:
            # Create draft
            draft = self._create_draft_with_retry(message)
            
            logger.info(f"[OK] Created scheduled draft for {to} (subject: {subject}) to send at {schedule_time}")
            logger.info(f"[INFO] Draft ID: {draft.get('id')}")
            logger.info(f"[INFO] Note: Gmail doesn't support native scheduled send via API.")
            logger.info(f"[INFO] You can use Gmail's 'Schedule Send' feature manually or set up external scheduling.")
            
            # Return draft with scheduling info
            draft['scheduled_send_time'] = schedule_time.isoformat()
            draft['scheduled_for'] = schedule_time.strftime('%Y-%m-%d %H:%M:%S')
            
            return draft
            
        except HttpError as e:
            logger.error(f"Error creating scheduled draft: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create scheduled draft: {e}")
            return None
    
    
    def search_messages(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        label_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search messages using Gmail search syntax
        
        Args:
            query: Gmail search query
            max_results: Maximum results
            label_ids: Label IDs to search
            
        Returns:
            List of matching messages
        """
        return self.list_messages(query=query, max_results=max_results, label_ids=label_ids)
    
    def search_emails(
        self,
        query: Optional[str] = None,
        folder: str = "inbox",
        limit: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Search emails - alias for search_messages with folder support
        
        Args:
            query: Gmail search query
            folder: Folder/label to search (inbox, sent, etc.)
            limit: Maximum results
            
        Returns:
            List of matching emails
        """
        # Map folder names to label IDs using constants
        folder_to_label = {
            'inbox': [GMAIL_FOLDERS['inbox']],
            'sent': [GMAIL_FOLDERS['sent']],
            'drafts': [GMAIL_FOLDERS['drafts']],
            'trash': [GMAIL_FOLDERS['trash']],
            'spam': [GMAIL_FOLDERS['spam']],
            'important': [GMAIL_FOLDERS['important']]
        }
        
        label_ids = folder_to_label.get(folder.lower(), [GMAIL_FOLDERS['inbox']])
        
        return self.search_messages(
            query=query or "",
            max_results=limit,
            label_ids=label_ids
        )
    
    def fetch_sent_emails(
        self,
        max_results: int = DEFAULT_SENT_EMAILS_LIMIT,
        include_drafts: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Fetch sent emails for building user writing style profile
        
        This method retrieves emails from the user's "Sent" folder to analyze
        their writing patterns, tone, and style for personalizing AI responses.
        
        Args:
            max_results: Maximum number of sent emails to retrieve (default: 100)
            include_drafts: Whether to include draft emails (default: False)
            
        Returns:
            List of sent email dictionaries with the following structure:
            [
                {
                    'id': 'message_id',
                    'thread_id': 'thread_id',
                    'subject': 'Email subject',
                    'from': 'sender@example.com',
                    'to': ['recipient@example.com'],
                    'cc': ['cc@example.com'],  # optional
                    'bcc': ['bcc@example.com'],  # optional
                    'date': '2024-01-01T12:00:00Z',
                    'body': 'Email body content',
                    'snippet': 'Email preview snippet',
                    'labels': ['SENT', 'IMPORTANT']
                },
                ...
            ]
            
        Example:
            >>> client = GoogleGmailClient(credentials)
            >>> sent_emails = client.fetch_sent_emails(max_results=50)
            >>> print(f"Retrieved {len(sent_emails)} sent emails")
        """
        if not self.is_available():
            logger.warning("Gmail service not available - cannot fetch sent emails")
            return []
        
        try:
            # Build query for sent emails
            query = "in:sent"
            label_ids = [GMAIL_FOLDERS['sent']]
            
            # Optionally include drafts for analysis
            if include_drafts:
                query = "(in:sent OR in:drafts)"
                label_ids = [GMAIL_FOLDERS['sent'], GMAIL_FOLDERS['drafts']]
                logger.debug("Including draft emails in sent email fetch")
            
            logger.info(f"Fetching up to {max_results} sent emails for profile building")
            
            # Use existing list_messages with SENT label
            sent_emails = self.list_messages(
                query=query,
                max_results=max_results,
                label_ids=label_ids
            )
            
            if not sent_emails:
                logger.warning("No sent emails found - user may not have sent any emails yet")
                return []
            
            # Filter and enrich data for profile building
            processed_emails = []
            for email in sent_emails:
                try:
                    # Validate email has required fields
                    if not email.get('body') or not email.get('subject'):
                        logger.debug(f"Skipping email {email.get('id')} - missing body or subject")
                        continue
                    
                    # Skip very short emails (likely not useful for style analysis)
                    body = email.get('body', '')
                    if len(body.strip()) < MIN_BODY_LENGTH_FOR_PROFILE:
                        logger.debug(f"Skipping email {email.get('id')} - body too short (<{MIN_BODY_LENGTH_FOR_PROFILE} chars)")
                        continue
                    
                    # Add metadata useful for profile building
                    email['word_count'] = len(body.split())
                    email['char_count'] = len(body)
                    
                    processed_emails.append(email)
                    
                except Exception as e:
                    logger.warning(f"Error processing sent email {email.get('id', 'unknown')}: {e}")
                    continue
            
            logger.info(
                f"Successfully fetched {len(processed_emails)} sent emails "
                f"(filtered from {len(sent_emails)} total)"
            )
            
            return processed_emails
            
        except HttpError as e:
            error_str = str(e)
            
            # Handle common errors
            if 'Account Restricted' in error_str or 'access_denied' in error_str.lower():
                if self.credentials and not hasattr(self, '_sent_emails_restricted_logged'):
                    logger.error(
                        "🚫 Gmail API access is RESTRICTED - cannot fetch sent emails for profile building"
                    )
                    logger.info(
                        "   Contact your Google Workspace admin to allow Gmail API access"
                    )
                    self._sent_emails_restricted_logged = True
                return []
            
            if e.resp.status == HTTP_STATUS_FORBIDDEN:
                logger.error(f"Gmail API access denied when fetching sent emails: {error_str}")
            elif e.resp.status == HTTP_STATUS_UNAUTHORIZED:
                logger.error("Gmail API authentication failed - please re-authenticate")
            else:
                logger.error(f"Gmail API error when fetching sent emails ({e.resp.status}): {error_str}")
            
            return []
            
        except Exception as e:
            logger.error(f"Unexpected error fetching sent emails: {e}")
            return []
    
    def get_thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get all messages in a thread
        
        Args:
            thread_id: Thread ID
            
        Returns:
            List of message dictionaries in chronological order
        """
        if not self.is_available():
            logger.warning("Gmail service not available")
            return []
        
        try:
            # Get thread details
            thread = self._get_thread_with_retry(thread_id)
            
            messages = thread.get('messages', [])
            thread_messages = []
            
            for message in messages:
                # Format message using utility function
                formatted_message = format_message_from_gmail(message, include_internal_date=True)
                formatted_message['thread_id'] = thread_id  # Ensure thread_id is set
                thread_messages.append(formatted_message)
            
            # Sort by internal date (chronological order)
            thread_messages.sort(key=lambda x: int(x.get('internal_date', 0)))
            
            logger.info(f"Retrieved {len(thread_messages)} messages from thread {thread_id}")
            return thread_messages
            
        except HttpError as e:
            logger.error(f"Error getting Gmail thread {thread_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to get Gmail thread: {e}")
            return []
    
    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific message by ID
        
        Args:
            message_id: Message ID
            
        Returns:
            Message details or None if not found
        """
        if not self.is_available():
            logger.warning("Gmail service not available")
            return None
        
        try:
            message = self._get_message_with_retry(message_id)
            
            # Format message using utility function
            return format_message_from_gmail(message)
            
        except HttpError as e:
            logger.error(f"Error getting Gmail message {message_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get Gmail message: {e}")
            return None
    
    def mark_as_read(self, message_id: str) -> bool:
        """
        Mark a message as read
        
        Args:
            message_id: Message ID
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.warning("Gmail service not available")
            return False
        
        try:
            self._modify_message_with_retry(
                message_id=message_id,
                remove_labels=['UNREAD']
            )
            
            logger.info(f"[OK] Marked Gmail message {message_id} as read")
            return True
            
        except Exception as e:
            logger.error(f"Failed to mark Gmail message as read: {e}")
            return False
    
    def add_label(self, message_id: str, label_ids: List[str]) -> bool:
        """
        Add labels to a message
        
        Args:
            message_id: Message ID
            label_ids: List of label IDs to add
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.warning("Gmail service not available")
            return False
        
        try:
            self._modify_message_with_retry(
                message_id=message_id,
                add_labels=label_ids
            )
            
            logger.info(f"[OK] Added labels to Gmail message {message_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add labels to Gmail message: {e}")
            return False
