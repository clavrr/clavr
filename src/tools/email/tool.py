"""
Email Tool - Email management capabilities
"""
import asyncio
from typing import Optional, Any, Type
from langchain.tools import BaseTool
from pydantic import Field, BaseModel

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class EmailInput(BaseModel):
    """Input for EmailTool."""
    action: str = Field(description="Action to perform (search, send, reply, summarize, organize, delete, briefing, etc.)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    to: Optional[str] = Field(default=None, description="Recipient email address")
    subject: Optional[str] = Field(default=None, description="Email subject")
    body: Optional[str] = Field(default=None, description="Email body content")
    email_id: Optional[str] = Field(default=None, description="ID of the email to act upon")
    thread_id: Optional[str] = Field(default=None, description="Thread ID")
    limit: Optional[int] = Field(default=10, description="Result limit")
    sender: Optional[str] = Field(default=None, description="Sender name or email filter (e.g. 'Eleven Labs', 'john@example.com')")
    after_date: Optional[str] = Field(default=None, description="Filter: After this date (YYYY/MM/DD)")
    before_date: Optional[str] = Field(default=None, description="Filter: Before this date (YYYY/MM/DD)")
    # Python keyword 'from' workaround usually handled by alias, but keeping it simple for now

from ..base import WorkflowEventMixin


class EmailTool(WorkflowEventMixin, BaseTool):
    """Email management tool wrapping EmailParser"""
    name: str = "email"
    description: str = "Email management (search, send, reply, organize). Use this for any email-related queries."
    args_schema: Type[BaseModel] = EmailInput
    
    config: Optional[Config] = Field(default=None)
    rag_engine: Optional[Any] = Field(default=None)
    hybrid_coordinator: Optional[Any] = Field(default=None)
    user_id: int = Field(description="User ID - required for multi-tenancy")
    credentials: Optional[Any] = Field(default=None)
    user_first_name: Optional[str] = Field(default=None)
    _service: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, rag_engine: Optional[Any] = None, 
                 user_id: int = None, credentials: Optional[Any] = None, user_first_name: Optional[str] = None,
                 hybrid_coordinator: Optional[Any] = None, **kwargs):
        if user_id is None:
            raise ValueError("user_id is required for EmailTool - cannot default to 1 for multi-tenancy")
        super().__init__(
            config=config,
            rag_engine=rag_engine,
            hybrid_coordinator=hybrid_coordinator,
            user_id=user_id,
            credentials=credentials,
            user_first_name=user_first_name,
            **kwargs
        )
        if credentials:
            logger.info(f"[EmailTool] Initialized with credentials (valid={getattr(credentials, 'valid', 'unknown')})")
        else:
            logger.warning("[EmailTool] Initialized with NO credentials")
        if hybrid_coordinator:
            logger.info("[EmailTool] Initialized with HybridIndexCoordinator for Graph+Vector search")
        self._service = None
    
    def _initialize_service(self):
        """Lazy initialization of email service"""
        if self._service is None and self.config and self.credentials:
            try:
                from ...integrations.gmail.service import EmailService
                from ...services.rag_service import RAGService
                
                # Create RAG engine wrapper if needed, or use passed one
                # EmailService accepts rag_engine and hybrid_coordinator for Graph+Vector search
                
                self._service = EmailService(
                    config=self.config,
                    credentials=self.credentials,
                    rag_engine=self.rag_engine,
                    hybrid_coordinator=self.hybrid_coordinator,
                    user_id=self.user_id  # CRITICAL: Pass user_id for data isolation
                )
            except Exception as e:
                logger.error(f"Failed to initialize EmailService: {e}")
                # Don't raise, just log - allows tool to partially function or fail gracefully later
                self._service = None

    def _run(self, action: str = "search", query: str = "", **kwargs) -> str:
        """Execute email tool action"""
        workflow_emitter = kwargs.get('workflow_emitter')
        
        self._initialize_service()
        
        if not self._service and action not in ["create_template", "list_templates", "delete_template"]:
            # Templates might work without service if they leverage DB directly, 
            # but use_template needs service.
            if action == "use_template":
                 return "I'm having trouble connecting to your email service right now. Could you double-check your credentials?"
        
        try:
            # Emit action executing event
            if workflow_emitter:
                self.emit_action_event(workflow_emitter, 'executing', f"Processing email {action}", action=action)
            
            # Handle preset/template actions
            if action == "create_template":
                # Create an email preset
                template_name = kwargs.get('template_name') or kwargs.get('name')
                subject = kwargs.get('subject', '')
                body = kwargs.get('body', '') or query
                
                if not template_name:
                    return "[ERROR] Could not identify preset name. Please specify a name for the preset."
                
                try:
                    from ...database import get_db_context
                    from ...core.email.presets import EmailTemplateStorage
                    
                    with get_db_context() as db:
                        storage = EmailTemplateStorage(db, self.user_id)
                        
                        # Extract email details from kwargs
                        to_recipients = kwargs.get('to_recipients') or kwargs.get('to', [])
                        cc_recipients = kwargs.get('cc_recipients') or kwargs.get('cc', [])
                        bcc_recipients = kwargs.get('bcc_recipients') or kwargs.get('bcc', [])
                        tone = kwargs.get('tone', 'professional')
                        category = kwargs.get('category')
                        
                        # Fallback for subject if not provided (Agent should usually extract it)
                        if not subject and query:
                             # Simple heuristic fallback
                             if "subject" in query.lower():
                                 try:
                                     subject = query.split("subject", 1)[1].strip(": ").split("\n")[0]
                                 except Exception as e:
                                     logger.debug(f"[EmailTool] Failed to extract subject from query: {e}")
                        
                        storage.create_template(
                            name=template_name,
                            subject=subject,
                            body=body,
                            to_recipients=to_recipients if isinstance(to_recipients, list) else [to_recipients] if to_recipients else [],
                            cc_recipients=cc_recipients if isinstance(cc_recipients, list) else [cc_recipients] if cc_recipients else [],
                            bcc_recipients=bcc_recipients if isinstance(bcc_recipients, list) else [bcc_recipients] if bcc_recipients else [],
                            tone=tone,
                            category=category
                        )
                        
                        return f"You got it! I've created the '{template_name}' email preset for you."
                except Exception as e:
                    logger.error(f"Failed to create email preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to create email preset: {str(e)}"
            
            elif action == "use_template":
                # Use an existing email preset to send an email
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify preset name. Please specify which preset to use."
                
                try:
                    from ...database import get_db_context
                    from ...core.email.presets import EmailTemplateStorage
                    
                    with get_db_context() as db:
                        storage = EmailTemplateStorage(db, self.user_id)
                        
                        # Get preset
                        template = storage.get_template(template_name)
                        if not template:
                            return f"[ERROR] Email preset '{template_name}' not found."
                        
                        # Extract variables from query if provided
                        variables = kwargs.get('variables', {})
                        
                        # Expand template with variables
                        expanded = storage.expand_template(template_name, variables)
                        
                        # Merge with provided parameters (provided params override preset)
                        to = kwargs.get('to') or expanded.get('to_recipients', [])
                        cc = kwargs.get('cc') or expanded.get('cc_recipients', [])
                        bcc = kwargs.get('bcc') or expanded.get('bcc_recipients', [])
                        subject = kwargs.get('subject') or expanded.get('subject', '')
                        body = kwargs.get('body') or expanded.get('body', '')
                        
                        if not self._service:
                            return "[ERROR] Email service not available. Cannot send email from preset."
                        
                        # Normalize recipients
                        to_str = to[0] if isinstance(to, list) and to else (to if isinstance(to, str) else "")
                        cc_list = cc if isinstance(cc, list) else ([cc] if cc else [])
                        bcc_list = bcc if isinstance(bcc, list) else ([bcc] if bcc else [])

                        if not to_str:
                             return "[ERROR] No recipient specified in preset or request."

                        self._service.send_email(
                            to=to_str,
                            subject=subject,
                            body=body,
                            cc=cc_list,
                            bcc=bcc_list
                        )
                        
                        return f"Sent email using preset '{template_name}' to {to_str}"
                except Exception as e:
                    logger.error(f"Failed to use email preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to use email preset: {str(e)}"
            
            elif action == "list_templates":
                # List all email presets
                try:
                    from ...database import get_db_context
                    from ...core.email.presets import EmailTemplateStorage
                    
                    with get_db_context() as db:
                        storage = EmailTemplateStorage(db, self.user_id)
                        templates = storage.list_templates()
                        
                        if not templates:
                            return "You don't have any email presets yet."
                        
                        template_lines = []
                        for i, template in enumerate(templates, 1):
                            name = template.get('name', 'Unnamed')
                            subject = template.get('subject', '')[:50]
                            template_lines.append(f"{i}. {name}" + (f" - {subject}" if subject else ""))
                        
                        return f"Your email presets ({len(templates)} total):\n" + "\n".join(template_lines)
                except Exception as e:
                    logger.error(f"Failed to list email presets: {e}", exc_info=True)
                    return f"[ERROR] Failed to list email presets: {str(e)}"
            
            elif action == "delete_template":
                 # Delete an email preset
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify preset name."
                
                try:
                    from ...database import get_db_context
                    from ...core.email.presets import EmailTemplateStorage
                    
                    with get_db_context() as db:
                        storage = EmailTemplateStorage(db, self.user_id)
                        storage.delete_template(template_name)
                        return f"Deleted email preset '{template_name}' successfully."
                except Exception as e:
                    return f"[ERROR] Failed to delete email preset: {str(e)}"

            # --- Core Actions using EmailService ---

            if not self._service:
                 # If we reached here, we needed the service but failed
                 return "[INTEGRATION_REQUIRED] Gmail permission not granted. Please enable Google integration in Settings."

            if action == "send":
                to = kwargs.get('to') or kwargs.get('recipient')
                subject = kwargs.get('subject', 'No Subject')
                body = kwargs.get('body', query) # fallback to query as body
                cc = kwargs.get('cc', [])
                bcc = kwargs.get('bcc', [])
                
                if not to:
                    return "Oops! I need to know who to send this to. Could you specify a recipient?"

                if isinstance(to, list):
                    to = to[0] # send_email expects str currently for 'to'

                result = self._service.send_email(
                    to=to,
                    subject=subject,
                    body=body,
                    cc=cc if isinstance(cc, list) else [cc] if cc else [],
                    bcc=bcc if isinstance(bcc, list) else [bcc] if bcc else []
                )
                return f"Sent! Your email to {to} is on its way."

            elif action == "reply":
                message_id = kwargs.get('message_id') or kwargs.get('thread_id')
                body = kwargs.get('body', query)
                cc = kwargs.get('cc', [])
                
                if not message_id:
                    return "Error: No message_id specified for reply."
                
                self._service.reply_to_email(
                    message_id=message_id,
                    body=body,
                    cc=cc if isinstance(cc, list) else [cc] if cc else []
                )
                return "Reply sent!"

            elif action == "count":
                # Handle async call
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        count = executor.submit(lambda: asyncio.run(self._service.get_unread_count())).result(timeout=5.0)
                else:
                    count = loop.run_until_complete(self._service.get_unread_count())
                    
                return f"You have {count} unread emails."

            elif action in ["search", "list", "unread", "briefing", "list_priority", "priority", "check"]:
                # OPTIMIZATION: Voice mode needs SPEED (<2s). 
                # For "unread" or "what's new", use aggressive limits and skip complex filtering.
                
                default_folder = "inbox"
                if action == "search":
                    default_folder = "all"
                
                folder = default_folder
                is_unread = None
                
                if action in ["unread", "list_priority", "priority"]:
                    is_unread = True
                
                # Check for direct Gmail queries in 'query'
                if query and ("is:" in query or "from:" in query or "in:" in query):
                    pass
                elif query and ("new" in query.lower() or "unread" in query.lower()):
                    is_unread = True
                    # Comprehensive cleanup: strip ALL conversational wrapper words
                    # Old regex only stripped 4 words, leaving "do have" in queries like
                    # "What new emails do I have?" → Gmail searched "is:unread do have"
                    import re as _re
                    noise_words = r'\b(what|whats|do|does|did|i|my|me|have|has|any|are|is|there|check|list|show|get|give|tell|the|all|for|new|unread|latest|recent|emails|email|inbox|messages|please|can|you|could|would)\b'
                    clean_q = _re.sub(noise_words, '', query.lower(), flags=_re.IGNORECASE).strip()
                    clean_q = _re.sub(r'[?.,!]', '', clean_q).strip()
                    clean_q = _re.sub(r'\s+', ' ', clean_q).strip()  # collapse whitespace
                    if not clean_q:
                        query = "" # Clear query so we just list unread

                # VOICE OPTIMIZATION: If just checking unread/new, limit to 3 items for speed
                limit = kwargs.get('limit', 5)
                if is_unread and not query:
                    limit = 5  # Show all recent unread
                
                # Extract specific filters from kwargs if the Agent provided them
                from_email = kwargs.get('from') or kwargs.get('sender')
                to_email = kwargs.get('to') or kwargs.get('recipient')
                subject = kwargs.get('subject') or kwargs.get('subject_contains')
                after_date = kwargs.get('after') or kwargs.get('after_date')
                before_date = kwargs.get('before') or kwargs.get('before_date')
                content_contains = kwargs.get('content') or kwargs.get('content_contains') or kwargs.get('body_contains')
                has_attachment = kwargs.get('has_attachment', None)
                folder_override = kwargs.get('folder')
                
                if folder_override:
                    folder = folder_override
                
                # Build enhanced query with content keywords
                search_query = query
                if content_contains and content_contains not in (query or ''):
                    search_query = f"{query} {content_contains}".strip() if query else content_contains
                
                # execute search
                # NOTE: service.search_emails internally decides whether to use RAG or Gmail API.
                # VOICE OPTIMIZATION: Bypassing RAG (allow_rag=False) for speed if it's just a general list.
                # However, for specific/complex searches (financial, entity lookup), we MUST use RAG/Graph for accuracy.
                use_rag = True
                
                # Keywords that suggest we NEED RAG (precise lookup, financial, entities)
                rag_triggers = ["receipt", "invoice", "bill", "subscription", "charged", "payment", "find", "search"]
                is_complex_search = any(w in (search_query or "").lower() for w in rag_triggers) or from_email or subject
                
                if limit <= 5 and not is_complex_search:
                    use_rag = False
                    logger.info(f"[EmailTool] VOICE FAST PATH: Bypassing RAG for speed (limit={limit}, simple_query)")

                results = self._service.search_emails(
                    query=search_query,
                    folder=folder,
                    limit=limit,
                    from_email=from_email,
                    to_email=to_email,
                    subject=subject,
                    has_attachment=has_attachment,
                    is_unread=is_unread,
                    after_date=after_date,
                    before_date=before_date,
                    allow_rag=use_rag
                )
                
                if not results:
                    return "I couldn't find any emails matching that."
                
                # Format results conversationally
                lines = []
                if len(results) == 1:
                    # Single result — show FULL email content (user likely wants to read it)
                    email = results[0]
                    sender = email.get('sender', 'Unknown')
                    if '<' in sender:
                        sender = sender.split('<')[0].strip().strip('"')
                    subj = email.get('subject', '(No Subject)')
                    body = email.get('body', '') or email.get('snippet', '')
                    
                    lines.append(f"I've pulled up the email from {sender}. Here is the text:\n")
                    lines.append(f"**{subj}**\n")
                    lines.append(body.strip() if body.strip() else "(No content available)")
                else:
                    lines.append(f"I found {len(results)} emails:\n")

                    for i, email in enumerate(results, 1):
                        sender = email.get('sender', 'Unknown')
                        if '<' in sender:
                            sender = sender.split('<')[0].strip().strip('"')
                            
                        subj = email.get('subject', '(No Subject)')
                        date = email.get('date', '')
                        snippet = email.get('snippet', '').strip()[:150] 
                        
                        lines.append(f"**{i}. {subj}**")
                        
                        # Simplify date logic for speed
                        date_str = date
                        try:
                            from datetime import datetime
                            if date and 'T' in date:
                                 dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                                 date_str = dt.strftime('%I:%M %p') # Just time for today hopefully
                        except Exception as e:
                            logger.debug(f"[EmailTool] Date parse failed for '{date}': {e}")
                            
                        lines.append(f"   from _{sender}_")
                        if snippet:
                            lines.append(f"   \"{snippet}...\"")
                        lines.append("") # Spacer
                
                return "\n".join(lines)
            
            else:
                return f"Error: Unknown action '{action}'"
            
        except Exception as e:
            logger.error(f"EmailTool error: {e}", exc_info=True)
            if workflow_emitter:
                self.emit_action_event(workflow_emitter, 'error', f"Email {action} failed: {str(e)}", action=action, error=str(e))
            return f"Error: {str(e)}"
            
    async def _arun(self, action: str = "search", query: str = "", **kwargs) -> str:
        """Async execution"""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)
