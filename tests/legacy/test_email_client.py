"""
Tests for email client
"""
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.email.email_client import EmailClient
from src.models.email_message import EmailMessage


class TestEmailClient:
    """Test email client functionality"""
    
    def test_init(self, test_config):
        """Test client initialization"""
        client = EmailClient(test_config)
        assert client.email_address == test_config.email.address
        assert client.email_password == test_config.email.password
    
    @patch('src.email.email_client.MailBox')
    def test_fetch_new_emails(self, mock_mailbox, test_config):
        """Test fetching new emails"""
        # Setup mock
        mock_msg = Mock()
        mock_msg.uid = "123"
        mock_msg.from_ = "sender@example.com"
        mock_msg.to = ["recipient@example.com"]
        mock_msg.subject = "Test"
        mock_msg.text = "Body"
        mock_msg.html = None
        mock_msg.date = Mock()
        mock_msg.cc = []
        mock_msg.bcc = []
        
        mock_mailbox_instance = MagicMock()
        mock_mailbox_instance.__enter__.return_value.fetch.return_value = [mock_msg]
        mock_mailbox.return_value = mock_mailbox_instance
        
        client = EmailClient(test_config)
        emails = client.fetch_new_emails()
        
        assert len(emails) > 0
    
    def test_mark_as_processed(self, test_config, sample_email):
        """Test marking email as processed"""
        client = EmailClient(test_config)
        
        with patch('src.email.email_client.MailBox') as mock_mailbox:
            mock_mailbox_instance = MagicMock()
            mock_mailbox.return_value = mock_mailbox_instance
            
            # Should not raise exception
            client.mark_as_processed(sample_email)

