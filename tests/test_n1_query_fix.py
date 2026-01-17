"""
Test N+1 Query Fix for Gmail list_messages

This test verifies that the batch API is used instead of making N+1 individual requests
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from src.core.email.google_client import GoogleGmailClient
from src.utils.config import Config


class TestN1QueryFix:
    """Test that list_messages uses batch API to avoid N+1 queries"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.config = Mock(spec=Config)
        self.credentials = Mock()
        self.credentials.scopes = ['https://www.googleapis.com/auth/gmail.readonly']
        
    def test_list_messages_uses_batch_api(self):
        """Test that list_messages uses batch API instead of N individual calls"""
        with patch('src.core.email.google_client.build') as mock_build:
            # Setup mock service
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            
            # Mock the list response with 10 message IDs
            mock_list_response = {
                'messages': [
                    {'id': f'msg_{i}', 'threadId': f'thread_{i}'}
                    for i in range(10)
                ]
            }
            
            mock_service.users().messages().list().execute.return_value = mock_list_response
            
            # Mock batch execution
            mock_batch_messages = []
            for i in range(10):
                mock_batch_messages.append({
                    'id': f'msg_{i}',
                    'threadId': f'thread_{i}',
                    'payload': {
                        'headers': [
                            {'name': 'From', 'value': f'sender{i}@example.com'},
                            {'name': 'To', 'value': 'recipient@example.com'},
                            {'name': 'Subject', 'value': f'Test Subject {i}'},
                            {'name': 'Date', 'value': 'Mon, 1 Jan 2024 12:00:00 +0000'}
                        ],
                        'body': {'data': 'VGVzdCBib2R5'}
                    },
                    'snippet': f'Test snippet {i}',
                    'internalDate': '1704110400000'
                })
            
            # Track batch execution
            batch_executed = []
            
            def mock_batch_execute(self):
                """Mock batch execute that calls callbacks"""
                # Simulate batch execution by calling the callback for each request
                for i, (request_id, request) in enumerate(self._requests.items()):
                    batch_executed.append(request_id)
                    # Call the callback with the response
                    self._callback(request_id, mock_batch_messages[i], None)
            
            with patch('googleapiclient.http.BatchHttpRequest') as mock_batch_class:
                mock_batch_instance = MagicMock()
                mock_batch_class.return_value = mock_batch_instance
                
                # Setup batch mock
                mock_batch_instance._requests = {}
                mock_batch_instance._callback = None
                
                def mock_add(request, callback=None, request_id=None):
                    req_id = request_id or f"req_{len(mock_batch_instance._requests)}"
                    mock_batch_instance._requests[req_id] = request
                    if callback:
                        mock_batch_instance._callback = callback
                
                mock_batch_instance.add = mock_add
                mock_batch_instance.execute = lambda: mock_batch_execute(mock_batch_instance)
                
                # Create client and list messages
                client = GoogleGmailClient(self.config, credentials=self.credentials)
                messages = client.list_messages(query="", max_results=10)
                
                # Verify results
                assert len(messages) == 10, f"Expected 10 messages, got {len(messages)}"
                
                # Verify batch was created and executed
                mock_batch_class.assert_called_once()
                mock_batch_instance.execute.assert_called_once()
                
                # Verify that 10 requests were added to the batch
                assert len(mock_batch_instance._requests) == 10, \
                    f"Expected 10 batch requests, got {len(mock_batch_instance._requests)}"
                
                print("✅ Batch API used successfully")
                print(f"✅ Single batch request with {len(mock_batch_instance._requests)} messages")
                print(f"✅ Avoided {len(mock_batch_instance._requests)} individual API calls")
    
    def test_list_messages_single_api_call_vs_n_plus_one(self):
        """Test that we make 2 total API calls (1 list + 1 batch) instead of N+1"""
        with patch('src.core.email.google_client.build') as mock_build:
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            
            # Track all API calls
            api_calls = []
            
            def track_list(*args, **kwargs):
                api_calls.append(('list', args, kwargs))
                result = MagicMock()
                result.execute.return_value = {
                    'messages': [{'id': f'msg_{i}'} for i in range(10)]
                }
                return result
            
            def track_get(*args, **kwargs):
                api_calls.append(('get', args, kwargs))
                result = MagicMock()
                result.execute.return_value = {
                    'id': kwargs.get('id', 'msg_0'),
                    'payload': {
                        'headers': [
                            {'name': 'From', 'value': 'sender@example.com'},
                            {'name': 'Subject', 'value': 'Test'}
                        ],
                        'body': {'data': 'VGVzdA=='}
                    }
                }
                return result
            
            mock_service.users().messages().list = track_list
            mock_service.users().messages().get = track_get
            
            # Mock batch to succeed
            with patch('googleapiclient.http.BatchHttpRequest') as mock_batch_class:
                mock_batch = MagicMock()
                mock_batch_class.return_value = mock_batch
                
                responses = []
                for i in range(10):
                    responses.append({
                        'id': f'msg_{i}',
                        'payload': {
                            'headers': [
                                {'name': 'From', 'value': 'sender@example.com'},
                                {'name': 'Subject', 'value': f'Test {i}'}
                            ],
                            'body': {'data': 'VGVzdA=='}
                        }
                    })
                
                def execute_batch():
                    api_calls.append(('batch', len(responses), None))
                    # Call the callback for each response
                    callback = mock_batch.add.call_args_list[0][1].get('callback')
                    if callback:
                        for i, resp in enumerate(responses):
                            callback(f'req_{i}', resp, None)
                
                mock_batch.execute = execute_batch
                
                # Create client and list messages
                client = GoogleGmailClient(self.config, credentials=self.credentials)
                messages = client.list_messages(max_results=10)
                
                # Count API calls
                list_calls = [c for c in api_calls if c[0] == 'list']
                get_calls = [c for c in api_calls if c[0] == 'get']
                batch_calls = [c for c in api_calls if c[0] == 'batch']
                
                print(f"\n📊 API Call Statistics:")
                print(f"   List calls: {len(list_calls)}")
                print(f"   Individual get calls: {len(get_calls)}")
                print(f"   Batch calls: {len(batch_calls)}")
                print(f"   Total API calls: {len(list_calls) + len(get_calls) + len(batch_calls)}")
                
                # Verify we use batch instead of individual gets
                assert len(list_calls) == 1, "Should make exactly 1 list call"
                assert len(batch_calls) == 1, "Should make exactly 1 batch call"
                assert len(get_calls) == 0, "Should make 0 individual get calls (use batch instead)"
                
                total_calls = len(list_calls) + len(batch_calls)
                assert total_calls == 2, f"Expected 2 total API calls (1 list + 1 batch), got {total_calls}"
                
                print(f"\n✅ N+1 Query Problem FIXED!")
                print(f"✅ Old approach: 1 list + 10 gets = 11 API calls")
                print(f"✅ New approach: 1 list + 1 batch = 2 API calls")
                print(f"✅ Performance improvement: 5.5x fewer API calls!")
    
    def test_batch_handles_errors_gracefully(self):
        """Test that batch API handles individual message errors gracefully"""
        with patch('src.core.email.google_client.build') as mock_build:
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            
            mock_service.users().messages().list().execute.return_value = {
                'messages': [{'id': f'msg_{i}'} for i in range(5)]
            }
            
            with patch('googleapiclient.http.BatchHttpRequest') as mock_batch_class:
                mock_batch = MagicMock()
                mock_batch_class.return_value = mock_batch
                
                def execute_with_errors():
                    # Simulate: 3 successes, 2 errors
                    callback = None
                    for call in mock_batch.add.call_args_list:
                        if 'callback' in call[1]:
                            callback = call[1]['callback']
                            break
                    
                    if callback:
                        # Success responses
                        for i in [0, 1, 2]:
                            callback(f'req_{i}', {
                                'id': f'msg_{i}',
                                'payload': {
                                    'headers': [{'name': 'Subject', 'value': f'Test {i}'}],
                                    'body': {'data': 'VGVzdA=='}
                                }
                            }, None)
                        
                        # Error responses
                        for i in [3, 4]:
                            callback(f'req_{i}', None, Exception(f"Error fetching msg_{i}"))
                
                mock_batch.execute = execute_with_errors
                
                client = GoogleGmailClient(self.config, credentials=self.credentials)
                messages = client.list_messages(max_results=5)
                
                # Should still return the successful messages
                assert len(messages) == 3, f"Expected 3 successful messages, got {len(messages)}"
                
                print("\n✅ Batch API handles partial errors gracefully")
                print(f"✅ 5 messages requested, 2 failed, 3 succeeded")
                print(f"✅ Returned {len(messages)} valid messages")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
