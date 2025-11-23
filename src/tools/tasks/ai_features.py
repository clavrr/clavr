"""
AI Features Module for Task Tool

Handles all AI-powered task operations including:
- Extracting tasks from arbitrary text
- Auto-enhancing task suggestions
- Task prioritization and categorization
"""
from typing import Dict, Any, Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from .constants import (
    DEFAULT_PRIORITY,
    AI_TEXT_EXTRACTION_PROMPT,
    AI_ENHANCEMENT_PROMPT,
    DEFAULT_ESTIMATED_HOURS,
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class AIFeatures:
    """Handles AI-powered task operations"""
    
    def __init__(self, task_tool):
        """
        Initialize AI features
        
        Args:
            task_tool: Reference to parent TaskTool instance
        """
        self.task_tool = task_tool
    
    def extract_tasks_from_text(
        self,
        text: str,
        source_type: str = "text",
        auto_create: bool = False,
        default_priority: str = DEFAULT_PRIORITY
    ) -> str:
        """
        Extract action items from arbitrary text using AI
        
        Args:
            text: Text to analyze
            source_type: "text", "email", "meeting_notes", "document"
            auto_create: Automatically create extracted tasks
            default_priority: Default priority for created tasks
            
        Returns:
            List of extracted tasks (and creation results if auto_create=True)
        """
        try:
            if not self.task_tool.llm_client:
                return "[ERROR] AI features require LLM client"
            
            user_msg = f"""Extract actionable tasks from this {source_type}:

{text}

Identify all clear action items that need to be done."""
            
            messages = [
                SystemMessage(content=AI_TEXT_EXTRACTION_PROMPT),
                HumanMessage(content=user_msg)
            ]
            
            response = self.task_tool.llm_client.invoke(messages)
            ai_output = response.content
            
            # Parse extracted tasks
            extracted = self._parse_task_blocks(ai_output, default_priority)
            
            if not extracted:
                return "[INFO] No actionable tasks found in text"
            
            # Format output
            output = self._format_extracted_tasks(extracted, source_type)
            
            # Auto-create if requested
            if auto_create:
                created_count = self._create_extracted_tasks(extracted, source_type)
                output += f"\nCreated {created_count} tasks automatically"
            else:
                output += "\nAdd auto_create=True to create these tasks automatically"
            
            logger.info(f"[AI] Extracted {len(extracted)} tasks from {source_type}")
            return self.task_tool._format_success(output)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "extracting tasks from text")
    
    def auto_enhance_task(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Use AI to suggest task enhancements
        
        Args:
            task_description: Task description
            context: Additional context (user preferences, related tasks, etc.)
            
        Returns:
            Dictionary with suggestions (category, priority, tags, etc.)
        """
        try:
            if not self.task_tool.llm_client:
                return self._get_default_suggestions()
            
            context_str = ""
            if context:
                context_str = f"\nContext: {context}"
            
            user_msg = f"""Analyze this task and provide suggestions:
Task: {task_description}{context_str}"""
            
            messages = [
                SystemMessage(content=AI_ENHANCEMENT_PROMPT),
                HumanMessage(content=user_msg)
            ]
            
            response = self.task_tool.llm_client.invoke(messages)
            ai_output = response.content
            
            # Parse suggestions
            suggestions = self._parse_enhancement_suggestions(ai_output)
            
            logger.info(f"[AI] Generated enhancement suggestions for task: {task_description}")
            return suggestions
            
        except Exception as e:
            logger.error(f"Task enhancement failed: {e}")
            return self._get_default_suggestions()
    
    def _parse_task_blocks(
        self,
        ai_output: str,
        default_priority: str
    ) -> List[Dict[str, Any]]:
        """Parse task blocks from AI output"""
        extracted = []
        task_blocks = ai_output.split('---')
        
        for block in task_blocks:
            if 'TASK:' not in block:
                continue
            
            lines = block.strip().split('\n')
            task_info = {
                'description': None,
                'priority': default_priority,
                'due_date': None,
                'category': None
            }
            
            for line in lines:
                if line.startswith('TASK:'):
                    task_info['description'] = line.replace('TASK:', '').strip()
                elif line.startswith('PRIORITY:'):
                    task_info['priority'] = line.replace('PRIORITY:', '').strip().lower()
                elif line.startswith('DUE:'):
                    due_str = line.replace('DUE:', '').strip()
                    if due_str.lower() != 'none':
                        task_info['due_date'] = due_str
                elif line.startswith('CATEGORY:'):
                    task_info['category'] = line.replace('CATEGORY:', '').strip()
            
            if task_info['description']:
                extracted.append(task_info)
        
        return extracted
    
    def _format_extracted_tasks(
        self,
        extracted: List[Dict[str, Any]],
        source_type: str
    ) -> str:
        """Format extracted tasks for display"""
        output = f"**Extracted {len(extracted)} tasks from {source_type}:**\n\n"
        
        for i, task in enumerate(extracted, 1):
            output += f"{i}. **{task['description']}**\n"
            output += f"   Priority: {task['priority']}\n"
            if task['due_date']:
                output += f"   Due: {task['due_date']}\n"
            if task['category']:
                output += f"   Category: {task['category']}\n"
            output += "\n"
        
        return output
    
    def _create_extracted_tasks(
        self,
        extracted: List[Dict[str, Any]],
        source_type: str
    ) -> int:
        """Create tasks from extracted data"""
        created_count = 0
        
        for task in extracted:
            try:
                self.task_tool._create_task(
                    description=task['description'],
                    due_date=task['due_date'],
                    priority=task['priority'],
                    category=task['category'],
                    tags=[source_type, 'ai-extracted']
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Failed to create task: {e}")
        
        return created_count
    
    def _parse_enhancement_suggestions(self, ai_output: str) -> Dict[str, Any]:
        """Parse enhancement suggestions from AI output"""
        suggestions = {
            'suggested_category': 'general',
            'suggested_priority': DEFAULT_PRIORITY,
            'suggested_tags': [],
            'estimated_hours': DEFAULT_ESTIMATED_HOURS,
            'suggested_subtasks': [],
            'suggested_notes': ''
        }
        
        for line in ai_output.split('\n'):
            if line.startswith('CATEGORY:'):
                suggestions['suggested_category'] = line.replace('CATEGORY:', '').strip()
            elif line.startswith('PRIORITY:'):
                suggestions['suggested_priority'] = line.replace('PRIORITY:', '').strip().lower()
            elif line.startswith('TAGS:'):
                tags_str = line.replace('TAGS:', '').strip()
                suggestions['suggested_tags'] = [t.strip() for t in tags_str.split(',')]
            elif line.startswith('ESTIMATED_HOURS:'):
                try:
                    hours_str = line.replace('ESTIMATED_HOURS:', '').strip()
                    suggestions['estimated_hours'] = float(hours_str)
                except:
                    pass
            elif line.startswith('SUBTASKS:'):
                subtasks_str = line.replace('SUBTASKS:', '').strip()
                suggestions['suggested_subtasks'] = [s.strip() for s in subtasks_str.split('|')]
            elif line.startswith('NOTES:'):
                suggestions['suggested_notes'] = line.replace('NOTES:', '').strip()
        
        return suggestions
    
    def _get_default_suggestions(self) -> Dict[str, Any]:
        """Get default suggestions when AI is not available"""
        return {
            'suggested_category': 'general',
            'suggested_priority': DEFAULT_PRIORITY,
            'suggested_tags': [],
            'estimated_hours': DEFAULT_ESTIMATED_HOURS
        }
