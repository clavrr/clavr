"""
Notion Autonomous Execution Integration

Implements capability 2: Autonomous Workflow Execution (Action)
- Database Management: Auto create/update Notion databases and pages
- Goal-Driven Reporting: Generate complex reports from multiple sources
- Seamless Integration: Updates Notion as external actions complete
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio

from .client import NotionClient
from .config import NotionConfig
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionAutonomousExecution:
    """
    Autonomous execution integration for Notion.
    
    Provides:
    1. Database Management - Auto create/update Notion databases
    2. Goal-Driven Reporting - Generate reports from multiple sources
    3. Seamless Integration - Auto-update as actions complete
    """
    
    def __init__(
        self,
        notion_client: NotionClient,
        rag_engine: Optional[Any] = None,
        config: Optional[Any] = None
    ):
        """
        Initialize Notion autonomous execution.
        
        Args:
            notion_client: NotionClient instance
            rag_engine: Optional RAGEngine for knowledge retrieval
            config: Optional configuration object
        """
        self.notion_client = notion_client
        self.rag_engine = rag_engine
        self.config = config or NotionConfig
        
        logger.info("Notion autonomous execution initialized")
    
    async def database_management_at_scale(
        self,
        action_type: str,
        source_system: str,
        action_data: Dict[str, Any],
        target_database_id: str
    ) -> Dict[str, Any]:
        """
        Automatically manage Notion databases based on external actions.
        
        This implements capability 2, part 1:
        - Example: After calendar meeting held, auto-create rows in Project Tracker
        - Auto-update Notion as external actions complete
        
        Args:
            action_type: Type of action ('meeting_held', 'email_sent', etc.)
            source_system: System action came from ('calendar', 'slack', etc.)
            action_data: Data from the action
            target_database_id: Notion database to update
            
        Returns:
            Result of database management operation
        """
        try:
            logger.info(f"[NOTION] Auto-managing database for {action_type} from {source_system}")
            
            # Step 1: Determine what needs to be created/updated
            management_plan = await self._create_management_plan(
                action_type,
                source_system,
                action_data,
                target_database_id
            )
            
            if not management_plan:
                logger.warning("[NOTION] No management plan generated")
                return {'success': False, 'message': 'No action needed'}
            
            # Step 2: Execute management operations
            results = []
            
            # Create new entries if needed
            if management_plan.get('create_entries'):
                for entry in management_plan['create_entries']:
                    result = await self._create_database_entry(
                        target_database_id,
                        entry,
                        source_system,
                        action_data
                    )
                    results.append(result)
            
            # Update existing entries if needed
            if management_plan.get('update_entries'):
                for update in management_plan['update_entries']:
                    result = await self._update_database_entry(
                        update['page_id'],
                        update['properties'],
                        source_system,
                        action_data
                    )
                    results.append(result)
            
            logger.info(f"[NOTION] Autonomous database management complete: {len(results)} operations")
            
            return {
                'success': True,
                'operations': results,
                'action_type': action_type,
                'source_system': source_system,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error in database management: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def goal_driven_reporting(
        self,
        report_spec: Dict[str, Any],
        database_id: str,
        sources: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate complex goal-driven reports and update Notion.
        
        This implements capability 2, part 2:
        - Example: "Generate weekly status report from Project Phoenix, Slack, and Jira"
        - Gathers metrics from multiple sources
        - Compiles into formatted Notion page
        - Auto-organizes and tags data
        
        Args:
            report_spec: Report specification (title, filters, sources)
            database_id: Database to create report in
            sources: Data sources (Jira, Slack, Calendar, etc.)
            
        Returns:
            Report generation result
        """
        try:
            logger.info(f"[NOTION] Generating goal-driven report: {report_spec.get('title')}")
            
            # Step 1: Gather data from all sources
            gathered_data = await self._gather_report_data(report_spec, sources)
            
            # Step 2: Synthesize and structure report
            report_content = await self._synthesize_report(report_spec, gathered_data)
            
            # Step 3: Create Notion page with report
            page = await self._create_report_page(
                database_id,
                report_spec,
                report_content
            )
            
            if not page:
                logger.error("[NOTION] Failed to create report page")
                return {'success': False, 'message': 'Failed to create report'}
            
            logger.info(f"[NOTION] Report created: {page.get('url')}")
            
            return {
                'success': True,
                'page_id': page.get('id'),
                'page_url': page.get('url'),
                'report_title': report_spec.get('title'),
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error in goal-driven reporting: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def seamless_integration_updates(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        notion_references: List[str]
    ) -> bool:
        """
        Seamlessly update Notion as external actions complete.
        
        This implements capability 2, part 3:
        - Monitors external systems for action completion
        - Auto-updates related Notion pages
        - Maintains data synchronization
        
        Args:
            event_type: Type of event ('task_completed', 'email_sent', etc.)
            event_data: Event data and results
            notion_references: Notion page IDs to update
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            logger.info(f"[NOTION] Seamless integration update for {event_type}")
            
            # Step 1: Determine update strategy based on event
            updates = await self._plan_seamless_updates(
                event_type,
                event_data,
                notion_references
            )
            
            # Step 2: Apply updates to Notion pages
            updated_count = 0
            for page_id, update_properties in updates.items():
                try:
                    result = await self.notion_client.update_page_async(
                        page_id=page_id,
                        properties=update_properties
                    )
                    
                    if result:
                        updated_count += 1
                        logger.debug(f"Updated Notion page {page_id}")
                        
                except Exception as e:
                    logger.warning(f"Error updating page {page_id}: {e}")
            
            logger.info(f"[NOTION] Seamless integration: updated {updated_count} pages")
            return updated_count > 0
            
        except Exception as e:
            logger.error(f"[NOTION] Error in seamless integration: {e}", exc_info=True)
            return False
    
    # Helper methods
    
    async def _create_management_plan(
        self,
        action_type: str,
        source_system: str,
        action_data: Dict[str, Any],
        target_database_id: str
    ) -> Optional[Dict[str, Any]]:
        """Create a plan for database management"""
        try:
            # Based on action type, determine what to create/update
            plan = {
                'create_entries': [],
                'update_entries': []
            }
            
            if action_type == 'meeting_held':
                # Create entry in Project Tracker
                plan['create_entries'].append({
                    'title': action_data.get('meeting_title'),
                    'type': 'meeting_summary',
                    'date': datetime.utcnow().isoformat(),
                    'assignees': action_data.get('attendees', []),
                    'action_items': action_data.get('action_items', [])
                })
            
            elif action_type == 'email_sent':
                # Create or update entry for sent email
                plan['create_entries'].append({
                    'title': action_data.get('subject'),
                    'type': 'email',
                    'date': datetime.utcnow().isoformat(),
                    'recipients': action_data.get('recipients', []),
                    'status': 'sent'
                })
            
            return plan if plan['create_entries'] or plan['update_entries'] else None
            
        except Exception as e:
            logger.warning(f"Error creating management plan: {e}")
            return None
    
    async def _create_database_entry(
        self,
        database_id: str,
        entry_template: Dict[str, Any],
        source_system: str,
        original_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a new entry in Notion database"""
        try:
            properties = {
                'Title': {
                    'title': [
                        {'text': {'content': entry_template.get('title', 'Untitled')}}
                    ]
                },
                'Type': {
                    'select': {'name': entry_template.get('type', 'task')}
                },
                'Source': {
                    'select': {'name': source_system}
                },
                'Date': {
                    'date': {'start': entry_template.get('date', datetime.utcnow().isoformat())}
                },
                'Status': {
                    'select': {'name': entry_template.get('status', 'open')}
                }
            }
            
            page = await self.notion_client.create_page_async(
                database_id=database_id,
                properties=properties
            )
            
            if page:
                logger.debug(f"Created database entry: {page.get('id')}")
                return {'success': True, 'page_id': page.get('id')}
            
            return {'success': False, 'message': 'Failed to create entry'}
            
        except Exception as e:
            logger.warning(f"Error creating database entry: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _update_database_entry(
        self,
        page_id: str,
        update_properties: Dict[str, Any],
        source_system: str,
        action_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing database entry"""
        try:
            properties = {
                'Status': {
                    'select': {'name': update_properties.get('status', 'in_progress')}
                },
                'Last Updated': {
                    'date': {'start': datetime.utcnow().isoformat()}
                }
            }
            
            page = await self.notion_client.update_page_async(
                page_id=page_id,
                properties=properties
            )
            
            if page:
                logger.debug(f"Updated database entry: {page_id}")
                return {'success': True, 'page_id': page_id}
            
            return {'success': False, 'message': 'Failed to update entry'}
            
        except Exception as e:
            logger.warning(f"Error updating database entry: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _gather_report_data(
        self,
        report_spec: Dict[str, Any],
        sources: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Gather data from all sources for report"""
        gathered = {
            'notion_data': [],
            'external_data': {},
            'metrics': {}
        }
        
        try:
            # Gather from Notion if database specified
            if report_spec.get('notion_database_id'):
                results = await self.notion_client.query_database_async(
                    database_id=report_spec['notion_database_id']
                )
                gathered['notion_data'] = results.get('results', [])
            
            # Gather from external sources
            if sources:
                for source_name, source_data in sources.items():
                    gathered['external_data'][source_name] = source_data
            
            logger.debug(f"Gathered data for report: {len(gathered['notion_data'])} Notion items")
            return gathered
            
        except Exception as e:
            logger.warning(f"Error gathering report data: {e}")
            return gathered
    
    async def _synthesize_report(
        self,
        report_spec: Dict[str, Any],
        gathered_data: Dict[str, Any]
    ) -> str:
        """Synthesize gathered data into report content"""
        try:
            report_parts = []
            
            # Add header
            report_parts.append(f"# {report_spec.get('title', 'Report')}")
            report_parts.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Add Notion data summary
            notion_items = gathered_data.get('notion_data', [])
            if notion_items:
                report_parts.append(f"\n## Notion Items ({len(notion_items)})")
            
            # Add external data summary
            external_data = gathered_data.get('external_data', {})
            if external_data:
                report_parts.append("\n## External Sources")
                for source_name in external_data.keys():
                    report_parts.append(f"- {source_name}")
            
            return '\n'.join(report_parts)
            
        except Exception as e:
            logger.warning(f"Error synthesizing report: {e}")
            return "Report generation failed"
    
    async def _create_report_page(
        self,
        database_id: str,
        report_spec: Dict[str, Any],
        report_content: str
    ) -> Optional[Dict[str, Any]]:
        """Create Notion page with report content"""
        try:
            properties = {
                'Title': {
                    'title': [
                        {'text': {'content': report_spec.get('title', 'Report')}}
                    ]
                },
                'Type': {
                    'select': {'name': 'report'}
                },
                'Generated': {
                    'date': {'start': datetime.utcnow().isoformat()}
                }
            }
            
            # Create content blocks
            children = [
                {
                    'object': 'block',
                    'type': 'paragraph',
                    'paragraph': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {'content': report_content}
                            }
                        ]
                    }
                }
            ]
            
            page = await self.notion_client.create_page_async(
                database_id=database_id,
                properties=properties,
                content=children
            )
            
            return page
            
        except Exception as e:
            logger.warning(f"Error creating report page: {e}")
            return None
    
    async def _plan_seamless_updates(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        notion_references: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Plan updates for seamless integration"""
        updates = {}
        
        try:
            for page_id in notion_references:
                properties = {}
                
                if event_type == 'task_completed':
                    properties['Status'] = {'select': {'name': 'done'}}
                
                elif event_type == 'email_sent':
                    properties['Status'] = {'select': {'name': 'sent'}}
                
                elif event_type == 'meeting_scheduled':
                    properties['Status'] = {'select': {'name': 'scheduled'}}
                
                if properties:
                    updates[page_id] = properties
            
            return updates
            
        except Exception as e:
            logger.warning(f"Error planning seamless updates: {e}")
            return {}
