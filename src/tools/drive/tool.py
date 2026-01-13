"""
Drive Tool - Google Drive file access capabilities
"""
import asyncio
from typing import Optional, Any, Type
from langchain.tools import BaseTool
from pydantic import Field, BaseModel

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class DriveInput(BaseModel):
    """Input for DriveTool."""
    action: str = Field(description="Action to perform (list, search, read, starred, extract_tasks)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    days: Optional[int] = Field(default=7, description="Number of days for recent files")
    limit: Optional[int] = Field(default=20, description="Result limit")
    file_id: Optional[str] = Field(default=None, description="ID of the file to read or act upon")


class DriveTool(BaseTool):
    """Google Drive access tool for file operations"""
    name: str = "drive"
    description: str = "Access Google Drive files (list recent files, search, read content). Use for queries about files, documents, spreadsheets."
    args_schema: Type[BaseModel] = DriveInput
    
    config: Optional[Config] = Field(default=None)
    user_id: int = Field(default=1)
    credentials: Optional[Any] = Field(default=None)
    _service: Optional[Any] = None
    _rag_engine: Optional[Any] = None  # RAG for semantic file search
    
    def __init__(self, config: Optional[Config] = None, user_id: int = 1, 
                 credentials: Optional[Any] = None, **kwargs):
        super().__init__(
            config=config,
            user_id=user_id,
            credentials=credentials,
            **kwargs
        )
        if credentials:
            logger.info(f"[DriveTool] Initialized with credentials (valid={getattr(credentials, 'valid', 'unknown')})")
        else:
            logger.warning("[DriveTool] Initialized with NO credentials")
        self._service = None
        self._rag_engine = None
    
    def _initialize_service(self):
        """Lazy initialization of Drive service"""
        if self._service is None and self.config and self.credentials:
            try:
                from ...integrations.google_drive.service import GoogleDriveService
                self._service = GoogleDriveService(
                    config=self.config,
                    credentials=self.credentials
                )
                logger.info("[DriveTool] Drive service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize GoogleDriveService: {e}")
                self._service = None
    
    def _initialize_rag(self):
        """Lazy initialization of RAG engine for semantic file search"""
        if self._rag_engine is None and self.config:
            try:
                from ...ai.rag import RAGEngine
                self._rag_engine = RAGEngine(
                    config=self.config,
                    collection_name="drive-files"
                )
                logger.info("[DriveTool] RAG engine initialized for drive-files collection")
            except Exception as e:
                logger.warning(f"[DriveTool] RAG engine init failed (will use API fallback): {e}")
                self._rag_engine = None
    
    def _search_files_rag(self, query: str, k: int = 10) -> list:
        """
        Search for files using RAG semantic search.
        Returns list of file metadata dicts or empty list if no results.
        """
        if not self._rag_engine:
            self._initialize_rag()
        
        if not self._rag_engine:
            return []
        
        try:
            # Search with RAG - returns list of dicts with content, metadata, confidence
            results = self._rag_engine.search(
                query=query,
                k=k,
                min_confidence=0.3,
                use_multi_query=True,
                timeout=3.0
            )
            
            if not results:
                logger.info(f"[DriveTool] RAG search found 0 files for: '{query}'")
                return []
            
            # Extract file metadata from RAG results
            files = []
            for result in results:
                metadata = result.get('metadata', {})
                file_id = metadata.get('file_id') or metadata.get('id')
                file_name = metadata.get('file_name') or metadata.get('name') or metadata.get('title', 'Unknown')
                
                if file_id:
                    files.append({
                        'id': file_id,
                        'name': file_name,
                        'mimeType': metadata.get('mime_type', metadata.get('mimeType', '')),
                        'confidence': result.get('confidence', 0),
                        '_rag_source': True  # Mark as from RAG
                    })
            
            if files:
                logger.info(f"[DriveTool] RAG search found {len(files)} files for: '{query}'")
                logger.info(f"[DriveTool] Top RAG match: {files[0].get('name')} (confidence: {files[0].get('confidence', 0):.2f})")
            
            return files
            
        except Exception as e:
            logger.warning(f"[DriveTool] RAG search failed: {e}")
            return []

    def _run(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Execute drive tool action
        
        Actions:
        - list: List recent files (default 7 days)
        - search: Search for files by name/content
        - read: Read file content by file_id
        - starred: List starred files
        """
        self._initialize_service()
        
        if not self._service:
            return "[INTEGRATION_REQUIRED] Drive permission not granted. Please enable Google integration in Settings."
        
        try:
            if action == "list" or action == "recent":
                # List recent files
                days = kwargs.get('days', 7)
                limit = kwargs.get('limit', 20)
                
                try:
                    days = int(days) if isinstance(days, str) else days
                except ValueError:
                    days = 7
                
                files = self._service.list_recent_files(days=days, limit=limit)
                
                if not files:
                    return f"I couldn't find any files modified in the last {days} days."
                
                return self._format_file_list(files, f"Recent files (last {days} days)")
            
            elif action == "search":
                # Search files by query
                if not query:
                    return "I need a search query to find files. What are you looking for?"
                
                # Clean the query - extract key terms for better matching
                import re
                clean_query = query.strip()
                
                # Remove surrounding quotes first
                clean_query = clean_query.strip("'\"")
                
                # Remove action phrases
                for phrase in ['get the work items from', 'get work items from', 'work items from',
                               'get the', 'find the', 'open the', 'from the', 'please', 'find']:
                    clean_query = re.sub(r'\b' + re.escape(phrase) + r'\b', '', clean_query, flags=re.IGNORECASE).strip()
                
                # Remove trailing words like 'file', 'doc', 'and add them to my tasks'
                clean_query = re.sub(r'\s+(file|doc|document|and\s+.*)$', '', clean_query, flags=re.IGNORECASE).strip()
                
                # Strip quotes again after phrase removal
                clean_query = clean_query.strip("'\"")
                
                if not clean_query:
                    clean_query = query.strip("'\"")
                
                logger.info(f"[DriveTool] Search term cleaned: '{query}' -> '{clean_query}'")
                
                # Extract significant keywords (3+ chars, not common words)
                stop_words = {'the', 'and', 'for', 'from', 'with', 'this', 'that', 'file', 'document', 'doc'}
                keywords = [w for w in clean_query.split() if len(w) >= 3 and w.lower() not in stop_words]
                
                limit = kwargs.get('limit', 20)
                files = []
                
                # PRIORITY 1: Try RAG semantic search first (fast + fuzzy matching)
                rag_files = self._search_files_rag(clean_query, k=limit)
                if rag_files:
                    files = rag_files
                    logger.info(f"[DriveTool] Using RAG results: {len(files)} files")
                
                # PRIORITY 2: Fall back to Drive API if RAG returns nothing
                if not files:
                    logger.info(f"[DriveTool] No RAG results, falling back to Drive API")
                    try:
                        # PROGRESSIVE SEARCH: Try multi-keyword AND, then fewer keywords
                        if len(keywords) >= 2:
                            for num_keywords in [4, 3, 2]:
                                if num_keywords > len(keywords):
                                    continue
                                kw_subset = keywords[:num_keywords]
                                conditions = [f"name contains '{kw}'" for kw in kw_subset]
                                search_query = " and ".join(conditions) + " and trashed = false"
                                logger.info(f"[DriveTool] Multi-keyword search ({num_keywords} kw): {search_query}")
                                result = self._service.client.list_files(q=search_query, page_size=limit)
                                files = result.get('files', [])
                                if files:
                                    logger.info(f"[DriveTool] Found {len(files)} files")
                                    break
                        
                        # Fallback: simple name search
                        if not files:
                            escaped_query = clean_query.replace("'", "\\'")
                            search_query = f"name contains '{escaped_query}' and trashed = false"
                            logger.info(f"[DriveTool] Simple search: {search_query}")
                            result = self._service.client.list_files(q=search_query, page_size=limit)
                            files = result.get('files', [])
                        
                        # Fallback: single keyword searches
                        if not files and keywords:
                            for kw in keywords[:3]:
                                logger.info(f"[DriveTool] Single keyword search: '{kw}'")
                                result = self._service.client.list_files(
                                    q=f"name contains '{kw}' and trashed = false",
                                    page_size=limit
                                )
                                files = result.get('files', [])
                                if files:
                                    break
                        
                        # Fallback: fullText search
                        if not files:
                            logger.info(f"[DriveTool] No name match, trying fullText search")
                            escaped_query = clean_query.replace("'", "\\'")
                            result = self._service.client.list_files(
                                q=f"fullText contains '{escaped_query}' and trashed = false",
                                page_size=limit
                            )
                            files = result.get('files', [])
                        
                        # Rank results by keyword match score
                        if files and keywords:
                            def match_score(file_name):
                                name_lower = file_name.lower()
                                return sum(1 for kw in keywords if kw.lower() in name_lower)
                            files = sorted(files, key=lambda f: match_score(f.get('name', '')), reverse=True)
                            top_score = match_score(files[0].get('name', ''))
                            logger.info(f"[DriveTool] Top match: {files[0].get('name')} (score: {top_score}/{len(keywords)})")
                    
                    except Exception as e:
                        logger.error(f"[DriveTool] Drive API search failed: {e}")
                
                if not files:
                    return f"I couldn't find any files matching '{clean_query}'."
                
                return self._format_file_list(files, f"Files matching '{clean_query}'")
            
            elif action == "starred":
                # List starred files
                limit = kwargs.get('limit', 20)
                files = self._service.list_starred_files(limit=limit)
                
                if not files:
                    return "You don't have any starred files."
                
                return self._format_file_list(files, "Your starred files")
            
            elif action == "read":
                # Read file content
                file_id = kwargs.get('file_id') or query
                
                if not file_id:
                    return "I need a file ID to read. Which file would you like me to read?"
                
                try:
                    # Get file metadata first
                    meta = self._service.client.get_file(file_id, fields="name, mimeType")
                    name = meta.get('name', 'Unknown')
                    mime_type = meta.get('mimeType', '')
                    
                    content = self._service.get_file_content(file_id, mime_type)
                    
                    if not content:
                        return f"I couldn't read the content of '{name}'."
                    
                    # Decode and truncate
                    text = content.decode('utf-8', errors='ignore')
                    if len(text) > 3000:
                        text = text[:3000] + "\n\n...(content truncated)"
                    
                    return f"**Content of '{name}':**\n\n{text}"
                    
                except Exception as e:
                    logger.error(f"[DriveTool] Read failed: {e}")
                    return f"Failed to read file: {str(e)}"
            
            elif action == "extract_tasks":
                # Extract work items from a file and create tasks
                # Uses Docling for intelligent document parsing
                # Creates tasks in Google Tasks by default, or Asana/Notion if specified
                if not query:
                    return "I need a file name to extract tasks from. Which file should I look at?"
                
                import re
                import tempfile
                import os
                
                query_lower = query.lower()
                
                # Detect task destination
                task_destination = "google_tasks"  # Default
                if any(phrase in query_lower for phrase in ['asana', 'in asana', 'to asana']):
                    task_destination = "asana"
                elif any(phrase in query_lower for phrase in ['notion', 'in notion', 'to notion']):
                    task_destination = "notion"
                
                logger.info(f"[DriveTool] Task destination: {task_destination}")
                
                # Step 1: Extract the filename from the query
                # Priority 1: Look for quoted filename (most reliable)
                quoted_match = re.search(r"['\"]([^'\"]+)['\"]", query)
                if quoted_match:
                    clean_query = quoted_match.group(1).strip()
                    logger.info(f"[DriveTool] Extracted quoted text: '{clean_query}'")
                else:
                    # Priority 2: Extract from pattern "from X file"
                    clean_query = query.strip()
                    
                    # Remove leading phrases
                    clean_query = re.sub(r'^.*?(?:from\s+(?:the\s+)?(?:content\s+of\s+)?)', '', clean_query, flags=re.IGNORECASE).strip()
                    
                    # Remove any remaining action phrases
                    for phrase in ['extract work items', 'work items', 'get the', 'find the', 'identify work items']:
                        clean_query = re.sub(r'\b' + re.escape(phrase) + r'\b', '', clean_query, flags=re.IGNORECASE).strip()
                
                # ALWAYS strip trailing words like 'file', 'document', 'doc' and action phrases
                clean_query = re.sub(r'\s+(?:file|document|doc|and\s+.*)$', '', clean_query, flags=re.IGNORECASE).strip()
                
                # Strip quotes that might remain
                clean_query = clean_query.strip("'\"")
                
                if not clean_query:
                    return "I couldn't determine the file name from your request. Please specify the file name."
                
                logger.info(f"[DriveTool] Searching for file: '{clean_query}'")
                
                # Extract significant keywords for multi-keyword search
                # Exclude common noise words and 'file'
                stop_words = {'the', 'and', 'for', 'from', 'with', 'this', 'that', 'file', 'document', 'doc'}
                keywords = [w for w in clean_query.split() if len(w) >= 3 and w.lower() not in stop_words]
                
                files = []
                
                # PRIORITY 1: Try RAG semantic search first (fast + fuzzy matching)
                rag_files = self._search_files_rag(clean_query, k=10)
                if rag_files:
                    files = rag_files
                    logger.info(f"[DriveTool] Using RAG results for extract_tasks: {len(files)} files")
                
                # PRIORITY 2: Fall back to Drive API if RAG returns nothing
                if not files:
                    logger.info(f"[DriveTool] No RAG results, falling back to Drive API for extract_tasks")
                    try:
                        # PROGRESSIVE SEARCH: Try multi-keyword AND, then progressively fewer keywords
                        if len(keywords) >= 2:
                            for num_keywords in [4, 3, 2]:
                                if num_keywords > len(keywords):
                                    continue
                                kw_subset = keywords[:num_keywords]
                                conditions = [f"name contains '{kw}'" for kw in kw_subset]
                                search_query = " and ".join(conditions) + " and trashed = false"
                                logger.info(f"[DriveTool] Multi-keyword search ({num_keywords} keywords): {search_query}")
                                result = self._service.client.list_files(q=search_query, page_size=10)
                                files = result.get('files', [])
                                if files:
                                    logger.info(f"[DriveTool] Found {len(files)} files with {num_keywords} keywords")
                                    break
                        
                        # Fallback: try simple "name contains" with full query
                        if not files:
                            search_query = f"name contains '{clean_query}' and trashed = false"
                            logger.info(f"[DriveTool] Simple name search: {search_query}")
                            result = self._service.client.list_files(q=search_query, page_size=10)
                            files = result.get('files', [])
                        
                        # Fallback: try individual keywords one at a time
                        if not files and keywords:
                            for kw in keywords[:3]:
                                search_query = f"name contains '{kw}' and trashed = false"
                                logger.info(f"[DriveTool] Single keyword search: '{kw}'")
                                result = self._service.client.list_files(q=search_query, page_size=20)
                                files = result.get('files', [])
                                if files:
                                    break
                        
                        # Fallback: try fullText search (searches inside documents)
                        if not files:
                            logger.info(f"[DriveTool] Trying fullText search")
                            result = self._service.client.list_files(
                                q=f"fullText contains '{clean_query}' and trashed = false",
                                page_size=10
                            )
                            files = result.get('files', [])
                        
                        # Rank results by keyword match score
                        if files and keywords:
                            def match_score(file_name):
                                name_lower = file_name.lower()
                                return sum(1 for kw in keywords if kw.lower() in name_lower)
                            files = sorted(files, key=lambda f: match_score(f.get('name', '')), reverse=True)
                            top_file = files[0]
                            top_score = match_score(top_file.get('name', ''))
                            logger.info(f"[DriveTool] Top match: {top_file.get('name')} (score: {top_score}/{len(keywords)})")
                    
                    except Exception as e:
                        logger.error(f"[DriveTool] Drive API search failed: {e}")
                        return f"Failed to search for file: {str(e)}"
                
                if not files:
                    return f"I couldn't find any files matching '{clean_query}'. Please check the file name."
                
                target_file = files[0]
                file_id = target_file.get('id')
                file_name = target_file.get('name', 'Unknown')
                mime_type = target_file.get('mimeType', '')
                
                logger.info(f"[DriveTool] Found file: {file_name} ({file_id})")
                
                # Step 2: Get file content - for Google Docs, export as PDF for Docling
                try:
                    if mime_type.startswith('application/vnd.google-apps.document'):
                        # Export Google Docs as PDF for Docling layout analysis
                        content = self._service.client.export_file(file_id, 'application/pdf')
                        file_ext = '.pdf'
                    elif mime_type.startswith('application/vnd.google-apps.'):
                        # Other Google types - export as text
                        content = self._service.client.export_file(file_id, 'text/plain')
                        file_ext = '.txt'
                    else:
                        # Binary files - download directly  
                        content = self._service.client.get_file_content(file_id)
                        file_ext = os.path.splitext(file_name)[1] or '.bin'
                    
                    if not content:
                        return f"I found '{file_name}' but couldn't read its content."
                        
                except Exception as e:
                    logger.error(f"[DriveTool] Failed to read file: {e}")
                    return f"Failed to read '{file_name}': {str(e)}"
                
                # Step 3: Parse document with Docling for intelligent extraction
                text_content = ""
                try:
                    from docling.document_converter import DocumentConverter
                    DOCLING_AVAILABLE = True
                except ImportError:
                    DOCLING_AVAILABLE = False
                    logger.warning("[DriveTool] Docling not available, falling back to simple text extraction")
                
                if DOCLING_AVAILABLE and file_ext in ['.pdf', '.docx', '.pptx', '.xlsx']:
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                            temp_file.write(content)
                            temp_path = temp_file.name
                        
                        converter = DocumentConverter()
                        result = converter.convert(temp_path, raises_on_error=False)
                        text_content = result.document.export_to_markdown()
                        
                        logger.info(f"[DriveTool] Docling extracted {len(text_content)} chars from {file_name}")
                        
                        # Cleanup temp file
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                            
                    except Exception as e:
                        logger.warning(f"[DriveTool] Docling failed, falling back: {e}")
                        text_content = content.decode('utf-8', errors='ignore')
                else:
                    # Fallback to simple text decoding
                    text_content = content.decode('utf-8', errors='ignore')
                
                # Truncate for LLM context
                if len(text_content) > 15000:
                    text_content = text_content[:15000]
                
                # Step 4: Use LLM to extract work items
                try:
                    from src.ai.llm_factory import LLMFactory
                    from src.utils.config import load_config
                    from langchain_core.messages import SystemMessage, HumanMessage
                    import json
                    
                    config = load_config()
                    llm = LLMFactory.get_llm_for_provider(config)
                    
                    extraction_prompt = f"""You are a task extraction assistant. Analyze this document and extract ALL actionable work items, tasks, action items, to-dos, and things that need to be done.

Document: {file_name}

Content:
{text_content}

Extract EVERY actionable item as a task. Return a JSON array where each item has:
- "title": Clear, actionable task title (max 100 chars)
- "notes": Additional context, deadlines, or details
- "priority": "high" (urgent/deadline soon), "medium" (normal), or "low" (optional/someday)
- "due_date": Date in YYYY-MM-DD format if mentioned, otherwise null

Look for:
- Bullet points describing actions
- Items starting with action verbs (complete, send, create, schedule, etc.)
- Items with deadlines or time references
- Follow-up items or next steps

Return ONLY valid JSON array, no other text. Example:
[{{"title": "Send out email reminders", "notes": "During the break", "priority": "medium", "due_date": null}}]

If no actionable items found, return: []"""

                    messages = [
                        SystemMessage(content="You are a helpful assistant that extracts tasks from documents. Be thorough - extract every actionable item."),
                        HumanMessage(content=extraction_prompt)
                    ]
                    
                    response = llm.invoke(messages)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    # Parse JSON from response
                    json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                    if json_match:
                        extracted_tasks = json.loads(json_match.group(0))
                    else:
                        extracted_tasks = []
                        
                except Exception as e:
                    logger.error(f"[DriveTool] LLM extraction failed: {e}")
                    return f"Found '{file_name}' but failed to extract tasks: {str(e)}"
                
                if not extracted_tasks:
                    return f"I read '{file_name}' but didn't find any clear work items or tasks to extract."
                
                # Step 5: Create tasks in the appropriate destination
                created_tasks = []
                failed_tasks = []
                destination_name = "Google Tasks"
                
                try:
                    if task_destination == "google_tasks":
                        from src.integrations.google_tasks.service import TaskService
                        from src.core.tasks.google_client import GoogleTasksClient
                        
                        task_client = GoogleTasksClient(self.config, credentials=self.credentials)
                        task_service = TaskService(self.config, task_client=task_client, user_id=self.user_id)
                        
                        for task_data in extracted_tasks:
                            try:
                                title = task_data.get('title', 'Untitled Task')
                                notes = task_data.get('notes', f'Extracted from: {file_name}')
                                priority = task_data.get('priority', 'medium')
                                due_date = task_data.get('due_date')
                                
                                created = task_service.create_task(
                                    title=title,
                                    notes=notes,
                                    priority=priority,
                                    due_date=due_date
                                )
                                created_tasks.append(title)
                            except Exception as e:
                                logger.warning(f"[DriveTool] Failed to create task '{title}': {e}")
                                failed_tasks.append(title)
                                
                    elif task_destination == "asana":
                        destination_name = "Asana"
                        from src.integrations.asana.service import AsanaService
                        
                        asana_service = AsanaService(self.config, credentials=self.credentials)
                        
                        for task_data in extracted_tasks:
                            try:
                                title = task_data.get('title', 'Untitled Task')
                                notes = task_data.get('notes', f'Extracted from: {file_name}')
                                due_date = task_data.get('due_date')
                                
                                created = asana_service.create_task(
                                    title=title,
                                    notes=notes,
                                    due_date=due_date
                                )
                                created_tasks.append(title)
                            except Exception as e:
                                logger.warning(f"[DriveTool] Failed to create Asana task '{title}': {e}")
                                failed_tasks.append(title)
                                
                    elif task_destination == "notion":
                        destination_name = "Notion"
                        # For Notion, we'd need to create pages/database items
                        # Return extracted tasks with instructions for now
                        task_list = "\n".join([f"• {t.get('title', 'Task')}" for t in extracted_tasks])
                        return f"I extracted {len(extracted_tasks)} work items from '{file_name}':\n\n{task_list}\n\n⚠️ Notion task creation is not yet implemented. Please add these manually to Notion."
                            
                except Exception as e:
                    logger.error(f"[DriveTool] Task service initialization failed: {e}")
                    task_list = "\n".join([f"• {t.get('title', 'Task')}" for t in extracted_tasks])
                    return f"I extracted {len(extracted_tasks)} work items from '{file_name}':\n\n{task_list}\n\n⚠️ However, I couldn't add them to {destination_name} automatically: {str(e)}"
                
                # Build response
                if created_tasks:
                    task_list = "\n".join([f"✅ {t}" for t in created_tasks])
                    response = f"I found '{file_name}' and created {len(created_tasks)} tasks in **{destination_name}**:\n\n{task_list}"
                    
                    if failed_tasks:
                        failed_list = "\n".join([f"❌ {t}" for t in failed_tasks])
                        response += f"\n\nFailed to create:\n{failed_list}"
                    
                    # Create Document -> Task relationships in graph (non-blocking)
                    # Run async in thread since _run is sync
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(self._link_document_to_tasks(file_id, file_name, created_tasks))
                        loop.close()
                    except Exception as e:
                        logger.debug(f"[DriveTool] Graph linking failed (non-blocking): {e}")
                    
                    return response
                else:
                    return f"I extracted tasks from '{file_name}' but couldn't create them in {destination_name}. Please try again."
            
            else:
                return f"Unknown action '{action}'. I can: list, search, starred, read, or extract_tasks from files."
                
        except Exception as e:
            error_msg = str(e)
            if "[INTEGRATION_REQUIRED]" in error_msg:
                return error_msg
            logger.error(f"DriveTool error: {e}", exc_info=True)
            return f"Error: {error_msg}"
    
    def _format_file_list(self, files: list, title: str) -> str:
        """Format a list of files for display"""
        lines = [f"**{title}:** ({len(files)} files)\n"]
        
        for i, f in enumerate(files, 1):
            name = f.get('name', 'Unknown')
            mime_type = f.get('mimeType', '')
            modified = f.get('modifiedByMeTime') or f.get('modifiedTime', '')
            modified_label = "Modified by you" if f.get('modifiedByMeTime') else "Modified"
            
            # Icon based on type
            icon = "📄"
            if 'folder' in mime_type:
                icon = "📁"
            elif 'spreadsheet' in mime_type or 'excel' in mime_type:
                icon = "📊"
            elif 'document' in mime_type or 'word' in mime_type:
                icon = "📝"
            elif 'presentation' in mime_type or 'powerpoint' in mime_type:
                icon = "📽️"
            elif 'pdf' in mime_type:
                icon = "📕"
            elif 'image' in mime_type:
                icon = "🖼️"
            
            # Format date nicely
            date_str = ""
            if modified:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(modified.replace('Z', '+00:00'))
                    # Convert to local time
                    dt_local = dt.astimezone()
                    date_str = dt_local.strftime('%b %d, %I:%M %p')
                except Exception:
                    date_str = modified[:10] if len(modified) >= 10 else modified
            
            lines.append(f"{i}. {icon} **{name}**")
            if date_str:
                lines.append(f"   _{modified_label}: {date_str}_")
            lines.append("")
        
        return "\n".join(lines)
    
    async def _link_document_to_tasks(self, file_id: str, file_name: str, task_titles: list):
        """
        Create Document -> ActionItem relationships in the graph.
        
        This links the source document to the tasks that were extracted from it,
        enabling queries like "What tasks came from this document?" or 
        "Show me the source document for this task."
        """
        try:
            from src.services.indexing.graph import KnowledgeGraphManager
            from src.services.indexing.graph.schema import NodeType, RelationType
            
            graph_manager = KnowledgeGraphManager(self.config)
            
            document_node_id = f"drive_{file_id}"
            
            for task_title in task_titles:
                try:
                    # Create a stable task node ID from the title
                    # This is a simplification - in production you'd use the actual task ID
                    import hashlib
                    task_hash = hashlib.md5(f"{file_id}:{task_title}".encode()).hexdigest()[:12]
                    task_node_id = f"action_item_{task_hash}"
                    
                    # Check if ActionItem node exists; create if not
                    existing = graph_manager.get_node(task_node_id)
                    if not existing:
                        graph_manager.add_node(
                            node_id=task_node_id,
                            node_type=NodeType.ACTION_ITEM,
                            properties={
                                "description": task_title,
                                "status": "pending",
                                "source_file": file_name,
                                "source_file_id": file_id
                            }
                        )
                        logger.debug(f"[DriveTool] Created ActionItem node: {task_node_id}")
                    
                    # Create Document -> ActionItem relationship
                    # Using CONTAINS since the task was extracted FROM the document
                    graph_manager.add_relationship(
                        from_node=document_node_id,
                        to_node=task_node_id,
                        rel_type=RelationType.CONTAINS,
                        properties={"extraction_method": "llm_extract", "source": "drive_tool"}
                    )
                    logger.debug(f"[DriveTool] Created CONTAINS relationship: {document_node_id} -> {task_node_id}")
                    
                except Exception as task_error:
                    logger.debug(f"[DriveTool] Failed to link task '{task_title}': {task_error}")
                    
        except Exception as e:
            # Graph linking failure should not affect the main response
            logger.debug(f"[DriveTool] Failed to link document to tasks: {e}")
    
    async def _arun(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Async execution"""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)

