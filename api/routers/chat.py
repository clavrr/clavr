"""
Chat and Query Endpoints
Handles natural language queries, email search, and intelligent routing
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re
import json
import asyncio

from src.database import get_async_db
from src.utils.config import load_config
from src.ai.llm_factory import LLMFactory
from src.ai.prompts import get_agent_system_prompt
from src.utils.logger import setup_logger
from ..dependencies import get_config, get_rag_engine
from ..auth import get_current_user_required, get_current_user_optional
from ..exceptions import create_error_response, create_success_response
from src.database.models import User

logger = setup_logger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])



class ChatRequest(BaseModel):
    """Request model for chat endpoint with validation"""
    question: Optional[str] = Field(None, max_length=10000, description="User question")
    query: Optional[str] = Field(None, max_length=10000, description="Alternative query field")
    max_results: int = Field(5, ge=1, le=100, description="Maximum number of results")
    
    @validator('question', 'query')
    def sanitize_query(cls, v):
        """Sanitize and validate query input"""
        if v is None:
            return None
        # Remove excessive whitespace
        v = re.sub(r'\s+', ' ', v.strip())
        # Limit length
        if len(v) > 10000:
            raise ValueError("Query too long (max 10000 characters)")
        # Basic injection prevention (remove SQL-like patterns)
        v = re.sub(r'[;\'"]', '', v)
        return v
    
    @property
    def get_query(self) -> str:
        """Get query from either question or query field"""
        return self.question or self.query or ""


class ChatResponse(BaseModel):
    """Response model for chat endpoint"""
    answer: str
    sources: List[Dict[str, Any]] = []
    found_results: bool = True


class UnifiedQueryRequest(BaseModel):
    """Request model for unified query endpoint with validation"""
    query: str = Field(..., min_length=1, max_length=10000, description="User query")
    max_results: Optional[int] = Field(5, ge=1, le=100, description="Maximum results")
    
    @validator('query')
    def sanitize_and_validate_query(cls, v):
        """Sanitize and validate query"""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        # Remove excessive whitespace
        v = re.sub(r'\s+', ' ', v.strip())
        # Limit length
        if len(v) > 10000:
            raise ValueError("Query too long (max 10000 characters)")
        # Basic sanitization
        v = re.sub(r'[;\'"]', '', v)
        return v


class UnifiedQueryResponse(BaseModel):
    """Response model for unified query endpoint"""
    query_type: str  # 'calendar', 'email', 'action', 'clarification'
    answer: str
    data: Optional[Dict[str, Any]] = None
    success: bool = True




async def _save_assistant_response(
    memory,
    user_id: int,
    session_id: str,
    content: str,
    intent: str
) -> bool:
    """
    Helper to save assistant response to conversation memory (async)
    
    Args:
        memory: ConversationMemory instance
        user_id: User ID
        session_id: Session ID
        content: Response content
        intent: Intent type (clarification, email, action, etc.)
        
    Returns:
        True if saved successfully
    """
    try:
        logger.info(f"Saving {intent} response (user={user_id}, session={session_id[:8]}...)")
        await memory.add_message(
            user_id=user_id,
            session_id=session_id,
            role='assistant',
            content=content,
            intent=intent
        )
        logger.info(f"[OK] Saved {intent} response to conversation history")
        return True
    except Exception as e:
        logger.error(f"[ERROR] Failed to save {intent} response: {e}", exc_info=True)
        return False




@router.post("/chat", response_model=ChatResponse)
async def chat_with_emails(
    request: ChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_async_db)
) -> ChatResponse:
    """
    Smart chat endpoint with email search using RAG
    
    Routes to appropriate handler:
    - Actions (schedule, create, etc.) → unified query endpoint
    - Questions about emails → email search with RAG
    
    Args:
        request: ChatRequest with question and optional max_results
        
    Returns:
        AI-generated answer with email sources
    """
    try:
        query_text = request.get_query
        logger.info(f"Processing chat query: {query_text[:100]}...")
        
        # Use LLM-based intent detection FIRST (not keyword matching)
        # This makes the agent truly intelligent, not just pattern matching
        from ..utils.intent_detection import detect_query_intent
        from src.utils import get_intent_keywords
        
        config = get_config()
        detected_intent = detect_query_intent(query_text, config)
        
        # Load intent keywords from configuration
        keywords = get_intent_keywords()
        
        # Intelligent routing based on LLM intent detection
        query_lower = query_text.lower()
        
        # Initialize query_type with a default value
        query_type = 'search'  # Default to search for general queries
        
        # Route based on LLM-detected intent (primary method)
        if detected_intent == 'calendar':
            query_type = 'calendar_action'
            logger.info("LLM routed to calendar (intelligent routing)")
        elif detected_intent == 'task':
            query_type = 'task_action'
            logger.info("LLM routed to task (intelligent routing)")
        elif detected_intent == 'email':
            query_type = 'email_action'
            logger.info("LLM routed to email (intelligent routing)")
        elif detected_intent == 'general':
            # General queries should use the agent for conversational responses
            query_type = 'general_action'
            logger.info("LLM routed to general (intelligent routing)")
        elif detected_intent is None:
            # LLM detection failed or returned invalid response, use fallback
            # Fallback to keyword-based detection using config-loaded keywords
            is_email_action = keywords.has_email_action_keyword(query_text)
            is_calendar = keywords.has_calendar_keyword(query_text) and not is_email_action
            is_task = keywords.has_task_keyword(query_text) and not keywords.has_email_action_keyword(query_text)
            
            if is_email_action:
                query_type = 'email_action'
                logger.info("Routing to email (fallback keyword detection)")
            elif is_calendar:
                query_type = 'calendar_action'
                logger.info("Routing to calendar (fallback keyword detection)")
            elif is_task:
                query_type = 'task_action'
                logger.info("Routing to task (fallback keyword detection)")
            else:
                query_type = 'search'
                logger.info("Email search query, using RAG...")
        else:
            # Handle any other unexpected intent values
            query_type = 'general_action'
            logger.info(f"Unknown intent '{detected_intent}', routing to general action")
        
        # Route to unified endpoint for all action types
        if query_type in ['email_action', 'task_action', 'calendar_action', 'general_action']:
            unified_request = UnifiedQueryRequest(
                query=query_text,
                max_results=request.max_results
            )
            # Call the unified_query logic inline since it's a separate endpoint
            # We'll duplicate the logic here for proper internal calls
            try:
                from src.agent import ClavrAgent
                from src.ai.conversation_memory import ConversationMemory
                from api.dependencies import (
                    AppState, get_calendar_tool, 
                    get_task_tool, get_summarize_tool
                )
                
                config = load_config()
                # Initialize ConversationMemory with RAG for semantic search
                rag_engine = AppState.get_rag_engine()
                memory = ConversationMemory(db, rag_engine=rag_engine)
                
                # Get authenticated user from middleware (already set in request.state)
                if not hasattr(http_request.state, 'user') or not http_request.state.user:
                    raise HTTPException(status_code=401, detail="Authentication required. Please log in and include your session token in the request.")
                
                authenticated_user = http_request.state.user
                user_id = authenticated_user.id
                
                # Extract user's first name for personalization
                from src.utils import extract_first_name
                user_first_name = extract_first_name(authenticated_user.name, authenticated_user.email)
                
                logger.info(f"[CHAT] Processing query for authenticated user_id={user_id}, first_name={user_first_name}")
                
                # Get session ID from http_request state (set by middleware)
                session_id = getattr(http_request.state, 'session_id', None) or f"session_{user_id}"
                
                # Use cached singleton tools (no re-initialization on each request)
                # Pass http_request to get_email_tool and get_task_tool so they can access user credentials from session
                # CRITICAL: Pass user_first_name to EmailTool and TaskTool for personalization
                tools = [
                    AppState.get_task_tool(user_id=user_id, request=http_request, user_first_name=user_first_name),
                    AppState.get_calendar_tool(user_id=user_id, request=http_request),
                    AppState.get_email_tool(user_id=user_id, request=http_request, user_first_name=user_first_name),
                    get_summarize_tool(config=config)
                ]
                
                agent = ClavrAgent(tools=tools, config=config, memory=memory, user_first_name=user_first_name)
                
                answer = await agent.execute(query=query_text, user_id=user_id, session_id=session_id)
                
                return ChatResponse(
                    answer=answer,
                    sources=[],
                    found_results=True
                )
            except Exception as e:
                logger.error(f"Error in unified query: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")
        
        logger.info("Email search query, trying RAG first, then falling back to Gmail API...")
        
        # Get RAG tool and config
        rag = get_rag_engine()
        cfg = get_config()
        
        # Try RAG search first (will automatically fall back to sentence-transformers if Gemini quota exceeded)
        try:
            results = rag.search(query_text, k=request.max_results, rerank=True)
        except Exception as rag_error:
            logger.warning(f"RAG search failed: {rag_error}, falling back to Gmail API")
            results = []
        
        # If RAG doesn't find results, fall back to Gmail API search via EmailTool
        if not results or len(results) == 0:
            logger.info("RAG search returned no results, falling back to Gmail API search...")
            
            # Get authenticated user for Gmail API fallback (from middleware)
            user_id = None
            if hasattr(http_request.state, 'user') and http_request.state.user:
                user_id = http_request.state.user.id
                logger.info(f"Using Gmail API fallback for user {user_id}")
                
                # Use EmailTool to search Gmail directly
                from api.dependencies import AppState
                email_tool = AppState.get_email_tool(user_id=user_id, request=http_request)
                
                try:
                    if email_tool and email_tool.google_client and email_tool.google_client.is_available():
                        # Extract sender from query if present
                        query_lower = query_text.lower()
                        sender = None
                        
                        # Try to extract sender name (Monique, Rodney, etc.)
                        import re
                        sender_patterns = [
                            r'from\s+([a-zA-Z][a-zA-Z0-9@._-]+)',
                            r'email+\s+from\s+([a-zA-Z][a-zA-Z0-9@._-]+)',
                            r'([a-zA-Z][a-zA-Z0-9@._-]*?)\s+(?:respond|responded|reply|replied)',
                        ]
                        
                        for pattern in sender_patterns:
                            match = re.search(pattern, query_lower)
                            if match:
                                potential_sender = match.group(1).strip()
                                skip_words = ['did', 'does', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'about', 'all']
                                if potential_sender.lower() not in skip_words:
                                    sender = potential_sender
                                    break
                        
                        # Search Gmail API with multiple variations to find the sender
                        if sender:
                            # Try multiple search variations since Gmail might need exact name or email
                            search_queries = [
                                f'from:"{sender}"',  # Quoted name (exact match)
                                f"from:{sender}",  # Unquoted name
                                sender,  # Just the name as keyword search
                            ]
                            
                            gmail_result = None
                            for search_query in search_queries:
                                logger.info(f"Searching Gmail API with query: '{search_query}'")
                                result = email_tool._run(action="search", query=search_query, limit=request.max_results * 2)  # Get more results to filter
                                
                                # Check if results actually contain the sender name
                                if result and "Gmail Search Results" in result and "No emails found" not in result:
                                    # Filter results to ensure they actually match the sender
                                    email_matches = re.findall(r'\[EMAIL\]\s*(.*?)(?=\[EMAIL\]|$)', result, re.DOTALL)
                                    matching_emails = []
                                    sender_lower = sender.lower()
                                    
                                    for email_text in email_matches:
                                        # Check if sender name appears in the email (From field or content)
                                        from_match = re.search(r'From:\s*(.+?)(?:\n|$)', email_text, re.IGNORECASE)
                                        if from_match:
                                            from_field = from_match.group(1).lower()
                                            # Check if sender name is in the From field
                                            if sender_lower in from_field:
                                                matching_emails.append(email_text)
                                    
                                    if matching_emails:
                                        # Reconstruct result with only matching emails
                                        gmail_result = "[OK] Gmail Search Results (" + str(len(matching_emails)) + "):\n\n"
                                        for i, email_text in enumerate(matching_emails[:request.max_results], 1):
                                            gmail_result += f"[EMAIL]\n{email_text}\n\n"
                                        logger.info(f"Found {len(matching_emails)} emails matching sender '{sender}'")
                                        break
                            
                            if not gmail_result:
                                logger.warning(f"No emails found matching sender '{sender}'")
                    else:
                        # Use the original query as Gmail search
                        search_query = query_text
                        logger.info(f"Searching Gmail API with query: {search_query}")
                        gmail_result = email_tool._run(action="search", query=search_query, limit=request.max_results)
                    
                    # Check if Gmail search found results
                    if gmail_result and "Gmail Search Results" in gmail_result and "No emails found" not in gmail_result:
                        logger.info("Gmail API search found results, using them")
                        # Parse Gmail results and format as RAG-style results
                        # Extract email info from Gmail result string
                        from datetime import datetime
                        
                        # Try to parse email details from Gmail result
                        email_matches = re.findall(r'\[EMAIL\]\s*(.*?)(?=\[EMAIL\]|$)', gmail_result, re.DOTALL)
                        
                        if email_matches:
                            formatted_results = []
                            for i, email_text in enumerate(email_matches[:request.max_results], 1):
                                # Extract subject, sender, date from email text
                                subject_match = re.search(r'Subject:\s*(.+?)(?:\n|$)', email_text)
                                sender_match = re.search(r'From:\s*(.+?)(?:\n|$)', email_text)
                                date_match = re.search(r'Date:\s*(.+?)(?:\n|$)', email_text)
                                
                                formatted_results.append({
                                    'content': email_text[:500],
                                    'metadata': {
                                        'subject': subject_match.group(1) if subject_match else 'No subject',
                                        'sender': sender_match.group(1) if sender_match else 'Unknown',
                                        'date': date_match.group(1) if date_match else 'Unknown date'
                                    },
                                    'distance': 0.0
                                })
                            
                            if formatted_results:
                                results = formatted_results
                                logger.info(f"Parsed {len(results)} emails from Gmail API results")
                except Exception as e:
                    logger.warning(f"Gmail API fallback failed: {e}", exc_info=True)
        
        # If still no results after fallback, return helpful message
        if not results or len(results) == 0:
            return ChatResponse(
                answer="I couldn't find any relevant emails to answer your question. "
                      "Your email database might be empty or the question might not relate to your emails. "
                      "If you just authenticated, emails are being indexed in the background. Please try again in a few minutes.",
                sources=[],
                found_results=False
            )
        
        # Format context from email results
        context_parts = []
        sources = []
        
        for i, result in enumerate(results[:request.max_results], 1):
            content = result.get('content', '')[:500]
            metadata = result.get('metadata', {})
            
            context_parts.append(f"Email {i}:\n{content}\n")
            sources.append({
                "index": i,
                "subject": metadata.get('subject', 'No subject'),
                "sender": metadata.get('sender', 'Unknown'),
                "date": metadata.get('date', 'Unknown date'),
                "snippet": content[:200] + "..." if len(content) > 200 else content
            })
        
        context = "\n---\n".join(context_parts)
        
        # Use LLM to generate answer
        cfg = get_config()
        llm = LLMFactory.get_google_llm(cfg, temperature=0.0)
        
        system_prompt = f"""{get_agent_system_prompt()}

[ALERT] ANTI-HALLUCINATION RULES FOR EMAIL SEARCH:
1. ONLY use information explicitly stated in the provided emails
2. DO NOT make assumptions or inferences
3. DO NOT add information from outside sources
4. If info is missing, say "I don't see that in these emails"
5. Cite which email contains each fact (e.g., "Email 1 mentions...")

Format:
- Friendly, conversational language
- Use text tags ([EMAIL] for emails, [CAL] for events, [TIME] for times)
- No markdown bold/italic (no **, *, _)
- Plain text structure"""
        
        prompt = f"""User Question: {query_text}

Relevant Emails:
{context}

Answer using ONLY the information above. Be honest about what you DON'T know.

Answer:"""
        
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]
        
        response = llm.invoke(messages)
        answer = response.content.strip()
        
        logger.info(f"Generated answer: {len(answer)} characters")
        
        return ChatResponse(
            answer=answer,
            sources=sources,
            found_results=True
        )
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@router.post("/query", response_model=UnifiedQueryResponse)
async def unified_query(
    http_req: Request,
    req_data: UnifiedQueryRequest,
    db_session: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user_required)
) -> UnifiedQueryResponse:
    """
    Unified smart query endpoint with intelligent routing
    
    Uses LangGraph for context-aware routing to:
    - Calendar queries (view/list events)
    - Email searches (RAG-powered)
    - Actions (schedule, create, update, delete)
    
    Args:
        request: UnifiedQueryRequest with query text
        db: Database session
        
    Returns:
        UnifiedQueryResponse with routed answer
    """
    try:
        from src.agent import ClavrAgent
        from src.tools import TaskTool, CalendarTool, EmailTool, SummarizeTool
        from src.ai.conversation_memory import ConversationMemory
        from api.middleware import require_session
        
        # Get the query text from the req_data parameter (which is UnifiedQueryRequest)
        query_text = getattr(req_data, 'query', None) if hasattr(req_data, 'query') else str(req_data)
        logger.info(f"Processing unified query with ClavrAgent: {query_text[:100] if query_text else 'unknown'}...")
        
        # Initialize memory and config
        config = load_config()
        memory = ConversationMemory(db_session)
        
        # Get user and session from request state (set by middleware)
        user_id = current_user.id
        
        # Extract user's first name for personalization
        from src.utils import extract_first_name
        user_first_name = extract_first_name(current_user.name, current_user.email)
        
        # Get session ID from request state (set by middleware)
        session_id = getattr(http_req.state, 'session_id', None) or getattr(http_req.state, 'session', {}).get('session_token', f"session_{user_id}")
        
        logger.info(f"Processing query for user={user_id}, session={session_id[:8] if session_id else 'none'}, first_name={user_first_name}")
        
        # Initialize RAG tool for semantic search
        from api.dependencies import (
            get_email_tool, get_calendar_tool, 
            get_task_tool, get_summarize_tool
        )
        
        # Use cached singleton tools (no re-initialization on each request)
        # Pass http_req to get_email_tool and get_task_tool so they can access user credentials from session
        # CRITICAL: Pass user_first_name to EmailTool and TaskTool for personalization
        from api.dependencies import AppState
        tools = [
            AppState.get_task_tool(user_id=user_id, request=http_req, user_first_name=user_first_name),
            AppState.get_calendar_tool(user_id=user_id, request=http_req),
            AppState.get_email_tool(user_id=user_id, request=http_req, user_first_name=user_first_name),
            get_summarize_tool(config=config)
        ]
        
        agent = ClavrAgent(tools=tools, config=config, memory=memory, user_first_name=user_first_name)
        logger.info("[OK] Initialized ClavrAgent with tools and conversation memory")
        
        # Get conversation history
        conversation_history = await memory.get_recent_messages(
            user_id=user_id,
            session_id=session_id,
            limit=10
        )
        logger.info(f"Retrieved {len(conversation_history)} messages from history")
        
        # Process query through ClavrAgent with conversation memory
        answer = await agent.execute(
            query=query_text,
            user_id=user_id,
            session_id=session_id
        )
        
        # Create routing_result format for compatibility
        routing_result = {
            'answer': answer,
            'intent': 'general',
            'entities': {},
            'confidence': 0.9,
            'needs_clarification': False,
            'suggestions': [],
            'metadata': {}
        }
        
        # Save user message
        try:
            await memory.add_message(
                user_id=user_id,
                session_id=session_id,
                role='user',
                content=query_text,
                entities=routing_result['entities'],
                confidence=routing_result['confidence']
            )
            logger.info("[OK] Saved user message to conversation history")
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
        
        # Check if clarification is needed
        if routing_result['needs_clarification']:
            answer = routing_result.get(
                'clarification_question',
                "I need more information. Can you provide more details?"
            )
            
            await _save_assistant_response(memory, user_id, session_id, answer, 'clarification')
            
            return UnifiedQueryResponse(
                query_type="clarification",
                answer=answer,
                data={"suggestions": routing_result['suggestions']}
            )
        
        # Get intent and route
        query_type = routing_result['intent']
        entities = routing_result['entities']
        
        logger.info(f"Agent routed to: {query_type} (confidence: {routing_result['confidence']:.2f})")
        
        # Use the agent's actual response instead of placeholder
        # The agent already processed the query and returned the result
        
        await _save_assistant_response(memory, user_id, session_id, answer, query_type)
        
        return UnifiedQueryResponse(
            query_type=query_type,
            answer=answer,
            data={
                "entities": entities,
                "confidence": routing_result['confidence'],
                "suggestions": routing_result['suggestions']
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in unified query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@router.post("/query/stream")
async def unified_query_stream(
    http_req: Request,
    req_data: UnifiedQueryRequest,
    db_session: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Streaming version of unified query endpoint using Server-Sent Events (SSE)
    
    Returns:
        StreamingResponse with text chunks as they become available
    """
    async def generate_stream():
        try:
            from src.agent import ClavrAgent
            from src.ai.conversation_memory import ConversationMemory
            from api.dependencies import (
                get_email_tool, get_calendar_tool, 
                get_task_tool, get_summarize_tool, AppState
            )
            
            query_text = getattr(req_data, 'query', None) if hasattr(req_data, 'query') else str(req_data)
            logger.info(f"Processing streaming query: {query_text[:100] if query_text else 'unknown'}...")
            
            # Initialize memory and config
            config = load_config()
            memory = ConversationMemory(db_session)
            
            # Get user and session from request state
            user_id = current_user.id
            
            # Extract user's first name for personalization
            from src.utils import extract_first_name
            user_first_name = extract_first_name(current_user.name, current_user.email)
            
            session_id = getattr(http_req.state, 'session_id', None) or getattr(http_req.state, 'session', {}).get('session_token', f"session_{user_id}")
            
            logger.info(f"Processing streaming query for user={user_id}, session={session_id[:8] if session_id else 'none'}, first_name={user_first_name}")
            
            # Initialize tools
            # CRITICAL: Pass user_first_name to EmailTool and TaskTool for personalization
            tools = [
                AppState.get_task_tool(user_id=user_id, request=http_req, user_first_name=user_first_name),
                AppState.get_calendar_tool(user_id=user_id, request=http_req),
                AppState.get_email_tool(user_id=user_id, request=http_req, user_first_name=user_first_name),
                get_summarize_tool(config=config)
            ]
            
            agent = ClavrAgent(tools=tools, config=config, memory=memory, user_first_name=user_first_name)
            logger.info("[OK] Initialized ClavrAgent for streaming")
            
            # Save user message
            try:
                await memory.add_message(
                    user_id=user_id,
                    session_id=session_id,
                    role='user',
                    content=query_text,
                    entities={},
                    confidence=0.9
                )
                logger.info("[OK] Saved user message to conversation history")
            except Exception as e:
                logger.error(f"Failed to save user message: {e}")
            
            # Stream the response
            full_response = ""
            workflow_complete_received = False
            chunk_size = 5  # Characters per chunk for text streaming (increased from 3 for faster streaming)
            
            async for chunk in agent.stream_execute(
                query=query_text,
                user_id=user_id,
                session_id=session_id,
                chunk_size=chunk_size,
                stream_workflow=True  # Explicitly enable workflow streaming
            ):
                # Check if chunk is a WorkflowEvent (workflow streaming enabled)
                from src.agent.events.workflow_events import WorkflowEvent
                if isinstance(chunk, WorkflowEvent):
                    # For workflow events, send the event data
                    event_data = {
                        'type': 'workflow_event',
                        'event_type': chunk.type.value,
                        'message': chunk.message,
                        'data': chunk.data,
                        'timestamp': chunk.timestamp.isoformat() if chunk.timestamp else None,
                        'done': False
                    }
                    
                    # Handle workflow_complete event
                    if chunk.type.value == 'workflow_complete':
                        workflow_complete_received = True
                        event_data['done'] = False  # Keep done=False, text chunks will follow
                        # CRITICAL: Don't extract or send the full response here
                        # The response will be streamed as text chunks, so including it causes duplication
                        # Remove response from event data to prevent frontend from displaying it immediately
                        if 'data' in event_data and 'response' in event_data['data']:
                            # Remove response from event data - chunks will provide it instead
                            event_data['data'] = {k: v for k, v in event_data['data'].items() if k != 'response'}
                            event_data['data']['streaming'] = True  # Signal that chunks will follow
                        # DO NOT extract full_response here - it will be built from streamed chunks
                        # This prevents the frontend from displaying the response twice
                    
                    yield f"data: {json.dumps(event_data)}\n\n"
                else:
                    # For text chunks (streamed after workflow events)
                    # These are the actual response text chunks being streamed character by character
                    if isinstance(chunk, str):
                        full_response += chunk
                        # Send chunk as SSE event for text streaming
                        # CRITICAL: Send immediately without buffering
                        chunk_data = json.dumps({'chunk': chunk, 'done': False})
                        yield f"data: {chunk_data}\n\n"
                        # Delay for natural text streaming effect (0.02s = 20ms)
                        # This provides smooth, readable streaming without being too fast or too slow
                        await asyncio.sleep(0.02)
                    else:
                        # Unexpected chunk type, log it
                        logger.warning(f"Unexpected chunk type in stream: {type(chunk)}")
                        if hasattr(chunk, '__str__'):
                            full_response += str(chunk)
                            yield f"data: {json.dumps({'chunk': str(chunk), 'done': False})}\n\n"
            
            # If no workflow_complete was received but we have a response, extract it
            if not workflow_complete_received and not full_response:
                # Fallback: try to get response from agent's last execution
                try:
                    # Execute again to get the response (non-streaming)
                    full_response = await agent.execute(query=query_text, user_id=user_id, session_id=session_id)
                    # Stream the fallback response character by character
                    if full_response:
                        for i in range(0, len(full_response), chunk_size):
                            chunk = full_response[i:i + chunk_size]
                            yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                            await asyncio.sleep(0.02)
                except Exception as e:
                    logger.error(f"Failed to get final response: {e}")
                    full_response = "I encountered an error processing your request."
                    # Stream error message
                    for i in range(0, len(full_response), chunk_size):
                        chunk = full_response[i:i + chunk_size]
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                        await asyncio.sleep(0.02)
            
            # Save assistant response
            try:
                await memory.add_message(
                    user_id=user_id,
                    session_id=session_id,
                    role='assistant',
                    content=full_response,
                    intent='general'
                )
                logger.info("[OK] Saved assistant streaming response to conversation history")
            except Exception as e:
                logger.error(f"Failed to save assistant response: {e}")
            
            # Send final event
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'full_response': full_response})}\n\n"
            
        except Exception as e:
            logger.error(f"Error in streaming query: {e}", exc_info=True)
            error_msg = json.dumps({'error': str(e), 'done': True})
            yield f"data: {error_msg}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx
            "X-Content-Type-Options": "nosniff",
            "Transfer-Encoding": "chunked"  # Ensure chunked transfer encoding
        }
    )

