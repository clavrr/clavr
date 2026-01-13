"""
Email Presets - PostgreSQL-backed storage

Stores email presets in PostgreSQL with user-specific isolation,
ACID transactions, and full database integration. Supports variable
substitution in preset subject and body.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ...utils.logger import setup_logger
from ...database.models import EmailTemplate

logger = setup_logger(__name__)


class EmailTemplateStorage:
    """
    PostgreSQL-backed storage for email presets
    
    Presets support variables like {recipient_name}, {date}, {project_name}
    and are stored in PostgreSQL with user-specific isolation
    """
    
    def __init__(self, db_session: Session, user_id: int):
        """
        Initialize email template storage
        
        Args:
            db_session: SQLAlchemy database session
            user_id: User ID for template isolation
        """
        self.db = db_session
        self.user_id = user_id
        logger.debug(f"Initialized EmailTemplateStorage for user {user_id}")
    
    def create_template(
        self,
        name: str,
        subject: str,
        body: str,
        to_recipients: Optional[List[str]] = None,
        cc_recipients: Optional[List[str]] = None,
        bcc_recipients: Optional[List[str]] = None,
        tone: str = "professional",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new email template
        
        Args:
            name: Template name (must be unique per user)
            subject: Email subject (supports {variables})
            body: Email body (supports {variables})
            to_recipients: Default TO recipients (list of email addresses)
            cc_recipients: Default CC recipients
            bcc_recipients: Default BCC recipients
            tone: Email tone ('professional', 'casual', 'friendly', 'formal')
            category: Template category (e.g., 'followup', 'thankyou', 'meeting_request')
            
        Returns:
            Created template dictionary
            
        Raises:
            ValueError: If template name already exists for this user
        """
        try:
            template = EmailTemplate(
                user_id=self.user_id,
                name=name,
                subject=subject or '',
                body=body,
                to_recipients=to_recipients or [],
                cc_recipients=cc_recipients or [],
                bcc_recipients=bcc_recipients or [],
                tone=tone,
                category=category,
                is_active=True
            )
            
            self.db.add(template)
            self.db.commit()
            
            logger.info(f"Created email template '{name}' for user {self.user_id}")
            return template.to_dict()
            
        except IntegrityError as e:
            self.db.rollback()
            logger.warning(f"Email template '{name}' already exists for user {self.user_id}")
            raise ValueError(f"Email template '{name}' already exists") from e
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create email template '{name}': {e}")
            raise
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get template by name
        
        Args:
            name: Template name
            
        Returns:
            Template dictionary or None if not found
        """
        template = self.db.query(EmailTemplate).filter(
            EmailTemplate.user_id == self.user_id,
            EmailTemplate.name == name,
            EmailTemplate.is_active == True
        ).first()
        
        if template:
            return template.to_dict()
        return None
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all templates for the user
        
        Returns:
            List of template dictionaries
        """
        templates = self.db.query(EmailTemplate).filter(
            EmailTemplate.user_id == self.user_id,
            EmailTemplate.is_active == True
        ).all()
        
        return [t.to_dict() for t in templates]
    
    def update_template(self, name: str, **updates) -> Dict[str, Any]:
        """
        Update template fields
        
        Args:
            name: Template name
            **updates: Fields to update (subject, body, tone, etc.)
            
        Returns:
            Updated template dictionary
            
        Raises:
            ValueError: If template not found
        """
        template = self.db.query(EmailTemplate).filter(
            EmailTemplate.user_id == self.user_id,
            EmailTemplate.name == name,
            EmailTemplate.is_active == True
        ).first()
        
        if not template:
            raise ValueError(f"Email template '{name}' not found")
        
        # Update provided fields
        for key, value in updates.items():
            if hasattr(template, key):
                setattr(template, key, value)
        
        self.db.commit()
        logger.info(f"Updated email template '{name}' for user {self.user_id}")
        return template.to_dict()
    
    def delete_template(self, name: str) -> bool:
        """
        Soft delete a template
        
        Args:
            name: Template name
            
        Returns:
            True if deleted successfully
            
        Raises:
            ValueError: If template not found
        """
        template = self.db.query(EmailTemplate).filter(
            EmailTemplate.user_id == self.user_id,
            EmailTemplate.name == name,
            EmailTemplate.is_active == True
        ).first()
        
        if not template:
            raise ValueError(f"Email template '{name}' not found")
        
        template.is_active = False
        self.db.commit()
        
        logger.info(f"Deleted email template '{name}' for user {self.user_id}")
        return True
    
    def expand_template(
        self,
        template_name: str,
        variables: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Expand a template with variables
        
        Args:
            template_name: Template name
            variables: Dictionary of variable values (e.g., {'recipient_name': 'John', 'date': 'Monday'})
            
        Returns:
            Expanded email dictionary ready for sending
            
        Raises:
            ValueError: If template not found
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Email template '{template_name}' not found")
        
        variables = variables or {}
        
        # Expand subject and body with variables
        subject = template.get('subject', '')
        body = template.get('body', '')
        
        for key, value in variables.items():
            subject = subject.replace(f'{{{key}}}', value)
            body = body.replace(f'{{{key}}}', value)
        
        result = {
            'subject': subject,
            'body': body,
            'to_recipients': template.get('to_recipients', []).copy(),
            'cc_recipients': template.get('cc_recipients', []).copy(),
            'bcc_recipients': template.get('bcc_recipients', []).copy(),
            'tone': template.get('tone', 'professional'),
            'category': template.get('category')
        }
        
        return result

