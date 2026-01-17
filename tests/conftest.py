"""
Pytest configuration and fixtures
"""
import pytest
from datetime import datetime

# from src.models.email_message import EmailMessage
from src.utils.config import (
    Config,
    AgentConfig,
    EmailConfig,
    IMAPConfig,
    SMTPConfig,
    AIConfig,
    EmailFolders
)


# @pytest.fixture
# def sample_email():
#     """Sample email message for testing"""
#     # return EmailMessage(
#     #     id="test123",
#     #     sender="sender@example.com",
#     #     recipient="recipient@example.com",
#     #     subject="Test Subject",
#     #     body="This is a test email body.",
#     #     date=datetime.now().isoformat(),
#     #     timestamp=datetime.now()
#     # )


@pytest.fixture
def test_config():
    """Test configuration"""
    return Config(
        agent=AgentConfig(
            name="Test Agent",
            email="test@example.com",
            check_interval=60,
            dry_run=True
        ),
        email=EmailConfig(
            address="test@example.com",
            password="test_password",
            imap=IMAPConfig(
                server="imap.test.com",
                port=993
            ),
            smtp=SMTPConfig(
                server="smtp.test.com",
                port=587
            ),
            folders=EmailFolders()
        ),
        ai=AIConfig(
            provider="openai",
            model="gpt-4",
            api_key="test_key",
            temperature=0.7,
            max_tokens=1000
        )
    )

