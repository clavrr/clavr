"""
ChatService - Centralizes chat logic, intent detection, and agent orchestration.
"""
import logging
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from src.ai.llm_factory import LLMFactory
from src.ai.prompts import get_agent_system_prompt
from src.ai.conversation_memory import ConversationMemory
from src.agents.supervisor import SupervisorAgent
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.utils import extract_first_name

logger = setup_logger(__name__)

class ChatService:
    def __init__(self, db: AsyncSession, config: Config):
        self.db = db
        self.config = config

    async def process_chat_query(self, user: Any, query_text: str, max_results: int, request: Any) -> Dict[str, Any]:
        """
        Process a smart chat query: detect intent, route to RAG or Action Agent.
        """
        from src.ai.intent.intent_patterns import has_email_keywords, has_calendar_keywords, has_task_keywords
        
        # Intelligent routing based on keywords
        query_type = self._determine_query_type(query_text, has_email_keywords, has_calendar_keywords, has_task_keywords)
        
        if query_type in ['email_action', 'task_action', 'calendar_action', 'general_action']:
            answer = await self.execute_unified_query(user, query_text, request)
            return {"answer": answer, "sources": [], "found_results": True}
        
        # Fallback to RAG search
        return await self._process_rag_query(user, query_text, max_results, request)

    def _determine_query_type(self, query_text: str, has_email_keywords_fn, has_calendar_keywords_fn, has_task_keywords_fn) -> str:
        """Determine routing query type based on keywords."""
        if has_email_keywords_fn(query_text): return 'email_action'
        if has_calendar_keywords_fn(query_text): return 'calendar_action'
        if has_task_keywords_fn(query_text): return 'task_action'
        return 'search'

    async def execute_unified_query(self, user: Any, query_text: str, request: Any, stream: bool = False) -> Any:
        """Execute query using SupervisorAgent."""
        from api.dependencies import AppState
        
        user_id = user.id
        user_first_name = extract_first_name(user.name, user.email)
        session_id = getattr(request.state, 'session_id', None) or f"session_{user_id}"
        
        # === INCREMENTAL LEARNING HOOK ===
        # Extract and learn facts from user message (fire-and-forget)
        asyncio.create_task(self._observe_message_for_learning(user_id, query_text))
        
        rag_engine = AppState.get_rag_engine()
        memory = ConversationMemory(self.db, rag_engine=rag_engine)
        
        tools = AppState.get_all_tools(user_id=user_id, request=request, user_first_name=user_first_name)

        # PERSISTENCE: Save User Message
        try:
            await memory.add_message(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=query_text,
                intent="unified_query"
            )
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
        
        # Add non-singleton tools
        from api.dependencies import get_summarize_tool
        tools.append(get_summarize_tool(config=self.config))
        
        # Use SupervisorAgent
        agent = SupervisorAgent(
            config=self.config, 
            tools=tools, 
            memory=memory, 
            db=self.db,
            user_id=user_id
        )
        
        if stream:
            return self._stream_response(agent, query_text, user_id, user_first_name, session_id)
        
        response = await agent.route_and_execute(
            query=query_text, 
            user_id=user_id, 
            user_name=user_first_name, 
            session_id=session_id
        )

        # PERSISTENCE: Save Assistant Response
        try:
            await memory.add_message(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=response
            )
        except Exception as e:
            logger.error(f"Failed to save assistant response: {e}")
            
        return response

    async def _observe_message_for_learning(self, user_id: int, message: str) -> None:
        """
        Background task to extract facts from user message.
        
        This is a fire-and-forget operation that doesn't block the main response.
        """
        try:
            from src.ai.memory import get_incremental_learner
            
            learner = get_incremental_learner()
            if learner:
                result = await learner.observe_message(
                    user_id=user_id,
                    message=message,
                    context={"source": "chat"}
                )
                if result and result.facts_learned > 0:
                    logger.debug(f"[ChatService] Learned {result.facts_learned} facts from message")
        except Exception as e:
            # Non-critical - don't break chat if learning fails
            logger.debug(f"[ChatService] Message learning failed: {e}")

    async def _stream_response(self, agent: SupervisorAgent, query: str, user_id: int, user_name: str, session_id: str):
        """Generator to stream agent response."""
        response = await agent.route_and_execute(
            query=query, 
            user_id=user_id, 
            user_name=user_name, 
            session_id=session_id
        )
        
        # For now, we simulate streaming by yielding the full response in chunks
        # Ideally, SupervisorAgent should support streaming natively.
        chunk_size = 50
        for i in range(0, len(response), chunk_size):
            yield response[i:i + chunk_size]
            await asyncio.sleep(0.01) # Small delay for realism

    async def execute_unified_query_stream(self, user: Any, query_text: str, request: Any):
        """Execute query and stream the response in chunks with real-time events."""
        from api.dependencies import AppState
        from src.events import WorkflowEventEmitter
        import json
        import asyncio
        
        # FAST PATH: Check if query requires an unconnected integration
        fast_response = await self._check_and_respond_if_not_connected(query_text, request)
        if fast_response:
            yield json.dumps({"type": "content", "content": fast_response, "done": False})
            yield json.dumps({"type": "done", "content": "", "done": True})
            return
        
        user_id = user.id
        user_first_name = extract_first_name(user.name, user.email)
        session_id = getattr(request.state, 'session_id', None) or f"session_{user_id}"
        
        rag_engine = AppState.get_rag_engine()
        memory = ConversationMemory(self.db, rag_engine=rag_engine)
        
        tools = AppState.get_all_tools(user_id=user_id, request=request, user_first_name=user_first_name)

        # PERSISTENCE: Save User Message
        try:
            await memory.add_message(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=query_text,
                intent="unified_stream"
            )
        except Exception as e:
            logger.error(f"Failed to save user message (stream): {e}")
        
        # Add non-singleton tools
        from api.dependencies import get_summarize_tool
        tools.append(get_summarize_tool(config=self.config))
        
        # Create event queue for streaming
        event_queue = asyncio.Queue()
        
        # Create event emitter with SSE callback
        async def on_event(event):
            await event_queue.put({
                "type": "event",
                "event_type": event.type.value if hasattr(event.type, 'value') else str(event.type),
                "message": event.message,
                "done": False
            })
        
        event_emitter = WorkflowEventEmitter()
        event_emitter.on_event(on_event)
        
        # Use SupervisorAgent with event emitter
        agent = SupervisorAgent(
            config=self.config, 
            tools=tools, 
            memory=memory, 
            db=self.db,
            user_id=user_id,
            event_emitter=event_emitter
        )
        
        # Run agent in background task
        response_holder = {"response": None, "error": None}
        
        async def run_agent():
            try:
                response_holder["response"] = await agent.route_and_execute(
                    query=query_text, 
                    user_id=user_id, 
                    user_name=user_first_name, 
                    session_id=session_id
                )
            except Exception as e:
                response_holder["error"] = str(e)
                logger.error(f"Agent execution failed: {e}")
            finally:
                # Signal completion
                await event_queue.put({"type": "agent_complete", "done": True})
        
        # Start agent task
        agent_task = asyncio.create_task(run_agent())
        
        # Yield immediate thinking status
        yield json.dumps({"type": "status", "status": "thinking", "message": "Processing your request...", "done": False})
        
        content_emitted = False
        
        # Stream events as they come in
        try:
            while True:
                try:
                    # Wait for events with timeout
                    event_data = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                    
                    if event_data.get("type") == "agent_complete":
                        break
                    
                    # If it's a content chunk from the agent, format it as "content" for the frontend
                    if event_data.get("type") == "event" and event_data.get("event_type") == "content_chunk":
                        content_emitted = True
                        chunk_content = str(event_data.get("message", ""))
                        
                        # Sub-chunking for ultra-smooth typewriter effect 
                        # especially if LLM sends large fragments
                        if len(chunk_content) > 15:
                            logger.info(f"[SSE] Sub-chunking large fragment ({len(chunk_content)} chars)")
                            words = chunk_content.split(' ')
                            for i, word in enumerate(words):
                                # Add space back except for the last word
                                text = word + (' ' if i < len(words) - 1 else '')
                                yield json.dumps({
                                    "type": "content",
                                    "content": text,
                                    "done": False
                                })
                                # Random-ish tiny delay for human-like feel
                                await asyncio.sleep(0.02)
                        else:
                            logger.info(f"[SSE] Yielding small chunk: {len(chunk_content)} chars")
                            yield json.dumps({
                                "type": "content",
                                "content": chunk_content,
                                "done": False
                            })
                            await asyncio.sleep(0.01)
                    else:
                        # Forward other events as they are
                        yield json.dumps(event_data)
                    
                except asyncio.TimeoutError:
                    # No events, check if agent is still running
                    if agent_task.done():
                        break
                    continue
        except Exception as e:
            logger.error(f"Event streaming error: {e}")
        
        # Wait for agent to finish
        await agent_task
        
        # Handle response errors
        if response_holder["error"]:
            yield json.dumps({"type": "error", "content": f"Error: {response_holder['error']}", "done": True})
            return
        
        # NOTE: Real-time streaming is now handled via CONTENT_CHUNK events above.
        # Fallback: if no chunks were emitted, simulate streaming for better UX
        if not content_emitted and response_holder["response"]:
            full_text = str(response_holder["response"])
            chunk_size = 20 # Small chunks for smooth animation
            
            for i in range(0, len(full_text), chunk_size):
                chunk = full_text[i:i + chunk_size]
                yield json.dumps({
                    "type": "content", 
                    "content": chunk, 
                    "done": False
                })
                # Tiny delay to allow frontend to render
                await asyncio.sleep(0.02)
        
        # Send final done signal
        yield json.dumps({"type": "done", "content": "", "done": True})

        # PERSISTENCE: Save Assistant Response (Full)
        try:
            full_response = response_holder["response"]
            if full_response:
                await memory.add_message(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=str(full_response)
                )
        except Exception as e:
            logger.error(f"Failed to save assistant response (stream): {e}")

    async def _process_rag_query(self, user: Any, query_text: str, max_results: int, request: Any) -> Dict[str, Any]:
        """Perform RAG search with Gmail fallback."""
        from api.dependencies import AppState
        rag = AppState.get_rag_engine()
        
        try:
            results = await rag.asearch(query_text, k=max_results, rerank=True)
        except Exception as e:
            logger.warning(f"RAG search failed: {e}, falling back to Gmail API")
            results = []
            
        if not results:
            results = await self._gmail_fallback(user, query_text, max_results, request)
            
        if not results:
            return {
                "answer": "I couldn't find any relevant emails to answer your question.",
                "sources": [],
                "found_results": False
            }
            
        return await self._generate_answer_from_results(query_text, results, max_results)

    async def _gmail_fallback(self, user: Any, query_text: str, max_results: int, request: Any) -> List[Dict[str, Any]]:
        """Fallback to Gmail API search."""
        from api.dependencies import AppState
        from src.utils.parsing import parse_gmail_tool_output
        
        email_tool = AppState.get_email_tool(user_id=user.id, request=request)
        
        try:
            if not email_tool or not email_tool.google_client or not email_tool.google_client.is_available():
                return []
                
            # Basic search implementation
            gmail_result = email_tool._run(action="search", query=query_text, limit=max_results)
            return parse_gmail_tool_output(gmail_result, limit=max_results)
            
        except Exception as e:
            logger.warning(f"Gmail API fallback failed: {e}")
            return []

    async def _generate_answer_from_results(self, query_text: str, results: List[Dict[str, Any]], max_results: int) -> Dict[str, Any]:
        """Generate AI answer based on retrieved results."""
        context_parts = []
        sources = []
        
        for i, result in enumerate(results[:max_results], 1):
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
        llm = LLMFactory.get_google_llm(self.config, temperature=0.0)
        
        system_prompt = f"""{get_agent_system_prompt()}
[ALERT] ANTI-HALLUCINATION RULES:
1. ONLY use info from provided emails.
2. If info is missing, say "I don't see that in these emails".
3. Cite emails (e.g., "Email 1 mentions...")."""

        prompt = f"User Question: {query_text}\n\nRelevant Emails:\n{context}\n\nAnswer using ONLY the information above:"
        
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        
        response = llm.invoke(messages)
        return {
            "answer": response.content.strip(),
            "sources": sources,
            "found_results": True
        }

    async def _check_and_respond_if_not_connected(self, query_text: str, request: Any) -> Optional[str]:
        """
        Fast-path check: If query requires an integration that's not connected,
        return an immediate helpful response instead of going through the full agent pipeline.
        
        Uses the granted_scopes stored in the session to precisely detect which
        Google integrations the user has connected.
        
        Returns None if all required integrations are connected (or query doesn't require any).
        Returns a response string if an integration is needed but not connected.
        """
        from src.ai.intent.intent_patterns import has_email_keywords, has_calendar_keywords, has_task_keywords
        from sqlalchemy import select
        from src.database.models import UserIntegration
        
        session = getattr(request.state, 'session', None)
        user = getattr(request.state, 'user', None)
        
        # Determine current user ID robustly
        uid = getattr(session, 'user_id', None)
        if not uid and user:
            uid = user.id
        if not uid and hasattr(request.state, 'user_id'):
            uid = request.state.user_id
        
        # Fast keyword detection to determine what services the query needs
        needs_email = has_email_keywords(query_text)
        needs_calendar = has_calendar_keywords(query_text)
        needs_tasks = has_task_keywords(query_text)
        
        # If no integrations needed, proceed normally
        if not (needs_email or needs_calendar or needs_tasks):
            return None
        
        # Parse granted scopes from session (comma-separated string)
        granted_scopes_str = getattr(session, 'granted_scopes', None) if session else None
        granted_scopes = set(granted_scopes_str.split(',')) if granted_scopes_str else set()
        
        # Define which scopes are needed for each service
        GMAIL_SCOPES = {
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/gmail.modify'
        }
        CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar'
        TASKS_SCOPE = 'https://www.googleapis.com/auth/tasks'
        
        # Check which services are missing
        missing_services = []
        
        if needs_email and not granted_scopes.intersection(GMAIL_SCOPES):
            # FALLBACK 1: Check if session already has gmail_access_token (from main login)
            is_connected_session = bool(getattr(session, 'gmail_access_token', None)) if session else False
            
            # FALLBACK 2: Check DB if session scope is missing (session scopes can be stale)
            is_connected_db = False
            if not is_connected_session:
                try:
                    if self.db and uid:
                        # Check if active gmail integration exists
                        stmt = select(UserIntegration).where(
                            UserIntegration.user_id == uid,
                            UserIntegration.provider == 'gmail',
                            UserIntegration.is_active == True
                        )
                        result = await self.db.execute(stmt)
                        if result.scalar_one_or_none():
                            is_connected_db = True
                except Exception as e:
                    logger.warning(f"Failed to check Gmail UserIntegration fallback: {e}")
            
            if not is_connected_session and not is_connected_db:
                missing_services.append("Gmail")
        
        if needs_calendar and CALENDAR_SCOPE not in granted_scopes:
            # FALLBACK: Check DB if session scope is missing (session scopes can be stale)
            is_connected_db = False
            try:
                    if uid:
                         # Check if active integration exists
                         stmt = select(UserIntegration).where(
                             UserIntegration.user_id == uid,
                             UserIntegration.provider == 'google_calendar',
                             UserIntegration.is_active == True
                         )
                         result = await self.db.execute(stmt)
                         if result.scalar_one_or_none():
                             is_connected_db = True
            except Exception as e:
                logger.warning(f"Failed to check UserIntegration fallback: {e}")

            if not is_connected_db:
                missing_services.append("Calendar")
        
        if needs_tasks and TASKS_SCOPE not in granted_scopes:
            # FALLBACK: Check DB if session scope is missing (session scopes can be stale)
            is_connected_db = False
            try:
                if uid:
                    # Check if active tasks integration exists
                    stmt = select(UserIntegration).where(
                        UserIntegration.user_id == uid,
                        UserIntegration.provider == 'google_tasks',
                        UserIntegration.is_active == True
                    )
                    result = await self.db.execute(stmt)
                    if result.scalar_one_or_none():
                        is_connected_db = True
            except Exception as e:
                logger.warning(f"Failed to check Tasks UserIntegration fallback: {e}")
            
            if not is_connected_db:
                missing_services.append("Tasks")
        
        # If no services are missing, proceed normally
        if not missing_services:
            return None
        
        # Build user-friendly response
        service_list = " and ".join(missing_services)
        
        return (
            f"I'd love to help with that, but your {service_list} isn't connected yet. "
            f"You can connect it from Settings → Integrations to get started!"
        )
