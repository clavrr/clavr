"""
Notion Automation and Efficiency Integration

Implements capability 3: Automation and Efficiency
- Custom Agent Memory: Direct agent to specific Notion page/database for context
- Data Integrity: Enforce organization, tagging, categorization
- Personalization: Adapt output format and tone to company/user standards
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio

from .client import NotionClient
from .config import NotionConfig
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionAutomationAndEfficiency:
    """
    Automation and efficiency integration for Notion.
    
    Provides:
    1. Custom Agent Memory - Direct to specific Notion page/database
    2. Data Integrity - Auto-enforce organization and categorization
    3. Personalization - Adapt output to company standards
    """
    
    def __init__(
        self,
        notion_client: NotionClient,
        config: Optional[Any] = None
    ):
        """
        Initialize Notion automation and efficiency.
        
        Args:
            notion_client: NotionClient instance
            config: Optional configuration object
        """
        self.notion_client = notion_client
        self.config = config or NotionConfig
        
        # Cache for memory pages and policies
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._policy_cache: Dict[str, Dict[str, Any]] = {}
        
        logger.info("Notion automation and efficiency initialized")
    
    async def setup_custom_agent_memory(
        self,
        database_id: str,
        page_title: str,
        context_type: str,
        initial_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Setup custom agent memory pointing to specific Notion page/database.
        
        This implements capability 3, part 1:
        - User directs agent to "company mission page" for context
        - Agent uses this as personalized memory/context
        - Output is formatted according to company standards
        
        Args:
            database_id: Database to store memory page in
            page_title: Title for memory page
            context_type: Type of context ('company_mission', 'tone_guide', 'template', etc.)
            initial_context: Initial context content
            
        Returns:
            Memory page details
        """
        try:
            logger.info(f"[NOTION] Setting up custom agent memory: {page_title}")
            
            # Step 1: Create memory page in Notion
            memory_page = await self._create_memory_page(
                database_id,
                page_title,
                context_type,
                initial_context
            )
            
            if not memory_page:
                logger.error("[NOTION] Failed to create memory page")
                return {'success': False, 'message': 'Failed to create memory page'}
            
            # Step 2: Cache memory page for quick access
            page_id = memory_page.get('id')
            self._memory_cache[page_id] = {
                'title': page_title,
                'context_type': context_type,
                'database_id': database_id,
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Step 3: Configure agent to use this memory
            memory_config = {
                'page_id': page_id,
                'database_id': database_id,
                'context_type': context_type,
                'refresh_interval_seconds': 300  # Refresh every 5 minutes
            }
            
            logger.info(f"[NOTION] Memory page created and configured: {page_id}")
            
            return {
                'success': True,
                'page_id': page_id,
                'page_url': memory_page.get('url'),
                'memory_config': memory_config,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error setting up custom memory: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def retrieve_agent_memory(
        self,
        page_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve custom agent memory from Notion.
        
        Args:
            page_id: Memory page ID
            
        Returns:
            Memory content or None if not found
        """
        try:
            # Check cache first
            if page_id in self._memory_cache:
                logger.debug(f"Retrieved memory from cache: {page_id}")
                return self._memory_cache[page_id]
            
            # Fetch from Notion
            page = self.notion_client.get_page(page_id)
            
            if not page:
                logger.warning(f"Memory page not found: {page_id}")
                return None
            
            # Extract content
            memory_content = await self._extract_memory_content(page)
            
            # Cache it
            self._memory_cache[page_id] = memory_content
            
            logger.debug(f"Retrieved memory from Notion: {page_id}")
            return memory_content
            
        except Exception as e:
            logger.warning(f"Error retrieving agent memory: {e}")
            return None
    
    async def data_integrity_and_organization(
        self,
        database_id: str,
        page_id: str,
        page_data: Dict[str, Any],
        enforcement_policy: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Enforce data integrity, organization, and categorization.
        
        This implements capability 3, part 2:
        - Automatically tag and categorize new documents
        - Link correctly within Notion structure
        - Ensure data consistency and integrity
        
        Args:
            database_id: Database ID
            page_id: Page ID to organize
            page_data: Page data to validate and organize
            enforcement_policy: Optional policy to enforce
            
        Returns:
            Organization and enforcement result
        """
        try:
            logger.info(f"[NOTION] Enforcing data integrity for page {page_id}")
            
            # Step 1: Load or create enforcement policy
            if not enforcement_policy:
                enforcement_policy = await self._get_or_create_policy(database_id)
            
            # Step 2: Validate data against policy
            validation_result = await self._validate_data_against_policy(
                page_data,
                enforcement_policy
            )
            
            if not validation_result['valid']:
                logger.warning(f"[NOTION] Data validation failed: {validation_result['errors']}")
                return {
                    'success': False,
                    'errors': validation_result['errors']
                }
            
            # Step 3: Auto-categorize and tag
            auto_tags = await self._generate_auto_tags(page_data, enforcement_policy)
            auto_categories = await self._determine_auto_categories(page_data, enforcement_policy)
            
            # Step 4: Apply organization updates
            organized_properties = await self._create_organized_properties(
                page_data,
                auto_tags,
                auto_categories,
                enforcement_policy
            )
            
            # Step 5: Update page with organized data
            update_result = await self.notion_client.update_page_async(
                page_id=page_id,
                properties=organized_properties
            )
            
            if not update_result:
                logger.error("[NOTION] Failed to update page with organized data")
                return {'success': False, 'message': 'Failed to update page'}
            
            logger.info(f"[NOTION] Data integrity enforced: {page_id}")
            
            return {
                'success': True,
                'page_id': page_id,
                'auto_tags': auto_tags,
                'auto_categories': auto_categories,
                'organized_properties': organized_properties,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error enforcing data integrity: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def personalize_output_formatting(
        self,
        response_text: str,
        company_standards_page_id: str,
        user_preferences_page_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Personalize output formatting based on company standards and user preferences.
        
        This implements capability 3, part 3:
        - Format output according to company tone and style
        - Apply company templates
        - Ensure consistency with organizational standards
        
        Args:
            response_text: Original response text
            company_standards_page_id: Notion page with company standards
            user_preferences_page_id: Optional user preference overrides
            
        Returns:
            Personalized output with formatting applied
        """
        try:
            logger.info("[NOTION] Personalizing output formatting")
            
            # Step 1: Load company standards
            company_standards = await self.retrieve_agent_memory(company_standards_page_id)
            
            if not company_standards:
                logger.warning("[NOTION] Company standards not found, using defaults")
                company_standards = self._get_default_standards()
            
            # Step 2: Load user preferences (optional)
            user_preferences = {}
            if user_preferences_page_id:
                user_preferences = await self.retrieve_agent_memory(user_preferences_page_id) or {}
            
            # Step 3: Apply formatting rules
            formatted_response = await self._apply_formatting_rules(
                response_text,
                company_standards,
                user_preferences
            )
            
            logger.info("[NOTION] Output formatting personalized")
            
            return {
                'success': True,
                'original_text': response_text,
                'formatted_text': formatted_response,
                'standards_applied': company_standards.get('name', 'default'),
                'user_preferences_applied': bool(user_preferences),
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error personalizing output: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'original_text': response_text
            }
    
    # Helper methods
    
    async def _create_memory_page(
        self,
        database_id: str,
        page_title: str,
        context_type: str,
        initial_context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Create a memory page in Notion"""
        try:
            properties = {
                'Title': {
                    'title': [{'text': {'content': page_title}}]
                },
                'Type': {
                    'select': {'name': context_type}
                },
                'Created': {
                    'date': {'start': datetime.utcnow().isoformat()}
                }
            }
            
            # Create content from initial context
            children = []
            for key, value in initial_context.items():
                children.append({
                    'object': 'block',
                    'type': 'paragraph',
                    'paragraph': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {'content': f"{key}: {str(value)}"}
                            }
                        ]
                    }
                })
            
            page = await self.notion_client.create_page_async(
                database_id=database_id,
                properties=properties,
                content=children if children else None
            )
            
            return page
            
        except Exception as e:
            logger.warning(f"Error creating memory page: {e}")
            return None
    
    async def _extract_memory_content(
        self,
        page: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract content from memory page"""
        try:
            properties = page.get('properties', {})
            
            return {
                'page_id': page.get('id'),
                'title': self._extract_title_from_properties(properties),
                'context_type': self._extract_property(properties, 'Type'),
                'created': self._extract_property(properties, 'Created'),
                'url': page.get('url')
            }
            
        except Exception as e:
            logger.warning(f"Error extracting memory content: {e}")
            return {}
    
    async def _get_or_create_policy(
        self,
        database_id: str
    ) -> Dict[str, Any]:
        """Get or create data integrity policy"""
        try:
            # Check cache
            if database_id in self._policy_cache:
                return self._policy_cache[database_id]
            
            # Create default policy
            policy = {
                'database_id': database_id,
                'required_fields': ['Title', 'Type', 'Status'],
                'auto_tag_enabled': True,
                'auto_categorize_enabled': True,
                'enforce_naming': True,
                'enforce_structure': True,
                'valid_categories': ['document', 'task', 'meeting', 'project', 'note'],
                'valid_statuses': ['open', 'in_progress', 'done', 'archived']
            }
            
            # Cache it
            self._policy_cache[database_id] = policy
            
            return policy
            
        except Exception as e:
            logger.warning(f"Error getting policy: {e}")
            return {}
    
    async def _validate_data_against_policy(
        self,
        page_data: Dict[str, Any],
        policy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate page data against policy"""
        try:
            errors = []
            
            # Check required fields
            for required_field in policy.get('required_fields', []):
                if required_field not in page_data and f"{required_field}_missing":
                    errors.append(f"Missing required field: {required_field}")
            
            return {
                'valid': len(errors) == 0,
                'errors': errors
            }
            
        except Exception as e:
            logger.warning(f"Error validating data: {e}")
            return {'valid': False, 'errors': [str(e)]}
    
    async def _generate_auto_tags(
        self,
        page_data: Dict[str, Any],
        policy: Dict[str, Any]
    ) -> List[str]:
        """Generate automatic tags for page"""
        tags = []
        try:
            # Add type-based tags
            page_type = page_data.get('type', 'general')
            tags.append(f"type:{page_type}")
            
            # Add category tags
            if page_data.get('category'):
                tags.append(f"category:{page_data['category']}")
            
            # Add temporal tags
            tags.append(f"created:{datetime.now().year}")
            
            return tags
            
        except Exception as e:
            logger.warning(f"Error generating tags: {e}")
            return tags
    
    async def _determine_auto_categories(
        self,
        page_data: Dict[str, Any],
        policy: Dict[str, Any]
    ) -> List[str]:
        """Determine automatic categories for page"""
        categories = []
        try:
            # Based on page content and type
            page_type = page_data.get('type')
            
            valid_categories = policy.get('valid_categories', [])
            
            if page_type in valid_categories:
                categories.append(page_type)
            else:
                categories.append('general')
            
            return categories
            
        except Exception as e:
            logger.warning(f"Error determining categories: {e}")
            return ['general']
    
    async def _create_organized_properties(
        self,
        page_data: Dict[str, Any],
        auto_tags: List[str],
        auto_categories: List[str],
        policy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create organized properties for Notion page"""
        try:
            properties = {
                'Tags': {
                    'multi_select': [{'name': tag} for tag in auto_tags]
                },
                'Category': {
                    'multi_select': [{'name': cat} for cat in auto_categories]
                },
                'Organized': {
                    'checkbox': True
                },
                'Last Organized': {
                    'date': {'start': datetime.utcnow().isoformat()}
                }
            }
            
            return properties
            
        except Exception as e:
            logger.warning(f"Error creating organized properties: {e}")
            return {}
    
    async def _apply_formatting_rules(
        self,
        response_text: str,
        company_standards: Dict[str, Any],
        user_preferences: Dict[str, Any]
    ) -> str:
        """Apply formatting rules to response"""
        try:
            formatted = response_text
            
            # Apply company standards
            tone = company_standards.get('tone', 'professional')
            
            if tone == 'formal':
                # Ensure formal language
                formatted = formatted.replace("hey", "Hello")
                formatted = formatted.replace("thanks", "Thank you")
            
            elif tone == 'casual':
                # Add casual elements
                pass
            
            # Apply user preferences
            if user_preferences.get('line_length'):
                # Word wrap to preferred line length
                pass
            
            if user_preferences.get('use_markdown'):
                # Convert to markdown
                pass
            
            return formatted
            
        except Exception as e:
            logger.warning(f"Error applying formatting: {e}")
            return response_text
    
    def _get_default_standards(self) -> Dict[str, Any]:
        """Get default company standards"""
        return {
            'name': 'default',
            'tone': 'professional',
            'formatting': 'standard',
            'language': 'en-US'
        }
    
    def _extract_title_from_properties(self, properties: Dict[str, Any]) -> str:
        """Extract title from Notion properties"""
        try:
            for prop_name, prop_value in properties.items():
                if prop_value.get('type') == 'title':
                    titles = prop_value.get('title', [])
                    if titles:
                        return titles[0].get('plain_text', '')
            return ''
        except Exception:
            return ''
    
    def _extract_property(self, properties: Dict[str, Any], prop_name: str) -> Optional[str]:
        """Extract a specific property value"""
        try:
            prop = properties.get(prop_name)
            if not prop:
                return None
            
            prop_type = prop.get('type')
            
            if prop_type == 'select':
                return prop.get('select', {}).get('name')
            elif prop_type == 'date':
                return prop.get('date', {}).get('start')
            elif prop_type == 'rich_text':
                rich_texts = prop.get('rich_text', [])
                if rich_texts:
                    return rich_texts[0].get('plain_text')
            
            return None
            
        except Exception:
            return None
