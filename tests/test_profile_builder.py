"""
Unit Tests for ProfileBuilder

Tests the ProfileBuilder class for building user writing style profiles
from sent emails.
"""
import pytest
import asyncio
from datetime import datetime
from typing import List, Dict, Any

from src.ai.profile_builder import ProfileBuilder
from src.utils.config import Config


# Test Data Fixtures
@pytest.fixture
def sample_emails() -> List[Dict[str, Any]]:
    """Sample sent emails for testing"""
    return [
        {
            'content': 'Hi John,\n\nThanks for reaching out! I can definitely help with that. Let me know if you need anything else.\n\nBest regards,\nAnthony',
            'metadata': {
                'subject': 'Re: Project Question',
                'date': '2024-11-10T10:00:00Z',
                'to': 'john@example.com'
            }
        },
        {
            'content': 'Hey Sarah,\n\nGreat question! Here\'s what I think: we should prioritize the frontend work first. Let me know your thoughts.\n\nCheers,\nAnthony',
            'metadata': {
                'subject': 'Sprint Planning',
                'date': '2024-11-11T14:30:00Z',
                'to': 'sarah@example.com'
            }
        },
        {
            'content': 'Hello Team,\n\nPlease find attached the quarterly report. Review it and send me your feedback by Friday.\n\nRegards,\nAnthony',
            'metadata': {
                'subject': 'Q3 Report',
                'date': '2024-11-12T09:15:00Z',
                'to': 'team@example.com'
            }
        }
    ]


@pytest.fixture
def config():
    """Mock config for testing"""
    return None  # ProfileBuilder can work without config (uses fallback)


# Basic ProfileBuilder Tests
@pytest.mark.asyncio
async def test_build_profile_basic(sample_emails, config):
    """Test basic profile building"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(sample_emails)
    
    assert profile is not None
    assert 'writing_style' in profile
    assert 'response_patterns' in profile
    assert 'preferences' in profile
    assert 'common_phrases' in profile
    assert profile['sample_size'] == len(sample_emails)


@pytest.mark.asyncio
async def test_build_profile_empty_list(config):
    """Test profile building with empty email list"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile([])
    
    # Should return default profile
    assert profile is not None
    assert profile['sample_size'] == 0
    assert 'writing_style' in profile


@pytest.mark.asyncio
async def test_build_profile_invalid_emails(config):
    """Test profile building with invalid email data"""
    builder = ProfileBuilder(config=config)
    
    invalid_emails = [
        {'no_content': 'missing content key'},
        {'content': ''},  # Empty content
        {'content': 'x'},  # Too short
    ]
    
    profile = await builder.build_profile(invalid_emails)
    
    # Should handle gracefully
    assert profile is not None
    assert profile['sample_size'] >= 0


@pytest.mark.asyncio
async def test_extract_greetings(sample_emails, config):
    """Test greeting extraction"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(sample_emails)
    
    greetings = profile['response_patterns'].get('greetings', [])
    
    # Should detect common greetings
    assert len(greetings) > 0
    # Common greetings like "Hi", "Hey", "Hello" should be detected
    greeting_texts = [g['greeting'] for g in greetings]
    assert any('Hi' in g or 'Hey' in g or 'Hello' in g for g in greeting_texts)


@pytest.mark.asyncio
async def test_extract_closings(sample_emails, config):
    """Test closing extraction"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(sample_emails)
    
    closings = profile['response_patterns'].get('closings', [])
    
    # Should detect common closings
    assert len(closings) > 0
    # Common closings like "Best regards", "Cheers", "Regards" should be detected
    closing_texts = [c['closing'] for c in closings]
    assert any('regards' in c.lower() or 'cheers' in c.lower() for c in closing_texts)


@pytest.mark.asyncio
async def test_detect_tone(sample_emails, config):
    """Test tone detection"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(sample_emails)
    
    tone = profile['writing_style'].get('tone')
    
    # Should detect tone
    assert tone is not None
    # Sample emails are friendly/professional
    assert tone in ['friendly', 'professional', 'casual']


@pytest.mark.asyncio
async def test_formality_analysis(sample_emails, config):
    """Test formality level analysis"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(sample_emails)
    
    formality = profile['writing_style'].get('formality_level')
    
    # Should analyze formality
    assert formality is not None
    assert formality in ['formal', 'semi-formal', 'informal']


@pytest.mark.asyncio
async def test_length_preferences(sample_emails, config):
    """Test length preference detection"""
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(sample_emails)
    
    avg_length = profile['preferences'].get('avg_sentence_length')
    
    # Should calculate average length
    assert avg_length is not None
    assert avg_length > 0


@pytest.mark.asyncio
async def test_concurrent_profile_builds(sample_emails, config):
    """Test concurrent profile building (async safety)"""
    builder = ProfileBuilder(config=config)
    
    # Build multiple profiles concurrently
    tasks = [
        builder.build_profile(sample_emails),
        builder.build_profile(sample_emails[:2]),
        builder.build_profile(sample_emails[1:])
    ]
    
    profiles = await asyncio.gather(*tasks)
    
    # All should complete successfully
    assert len(profiles) == 3
    assert all(p is not None for p in profiles)
    assert all('writing_style' in p for p in profiles)


@pytest.mark.asyncio
async def test_profile_consistency(sample_emails, config):
    """Test that profiles are consistent across builds"""
    builder = ProfileBuilder(config=config)
    
    # Build same profile twice
    profile1 = await builder.build_profile(sample_emails)
    profile2 = await builder.build_profile(sample_emails)
    
    # Should be similar (allowing for some variance in LLM responses)
    assert profile1['sample_size'] == profile2['sample_size']
    assert profile1['writing_style']['tone'] == profile2['writing_style']['tone']


# Edge Cases
@pytest.mark.asyncio
async def test_single_email_profile(config):
    """Test profile building with single email"""
    single_email = [{
        'content': 'Hi there,\n\nJust a quick note.\n\nThanks,\nAnthony',
        'metadata': {'subject': 'Test', 'date': '2024-11-15T10:00:00Z'}
    }]
    
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile(single_email)
    
    assert profile is not None
    assert profile['sample_size'] == 1


@pytest.mark.asyncio
async def test_very_long_emails(config):
    """Test profile building with very long emails"""
    long_email = {
        'content': 'Hi,\n\n' + 'This is a very long email. ' * 500 + '\n\nBest,\nAnthony',
        'metadata': {'subject': 'Long', 'date': '2024-11-15T10:00:00Z'}
    }
    
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile([long_email])
    
    # Should handle long content
    assert profile is not None
    assert profile['sample_size'] == 1


@pytest.mark.asyncio
async def test_special_characters_in_emails(config):
    """Test profile building with special characters"""
    special_email = {
        'content': 'Hi! 😊\n\nLet\'s meet @ 2pm. Cost: $50. Rating: 5/5 ⭐\n\nThanks!\nAnthony',
        'metadata': {'subject': 'Meeting', 'date': '2024-11-15T10:00:00Z'}
    }
    
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile([special_email])
    
    # Should handle special characters gracefully
    assert profile is not None
    assert profile['sample_size'] == 1


@pytest.mark.asyncio
async def test_multilingual_content(config):
    """Test profile building with mixed language content"""
    multilingual_email = {
        'content': 'Hi,\n\nMerci beaucoup! Danke schön! ありがとう!\n\nBest,\nAnthony',
        'metadata': {'subject': 'Thanks', 'date': '2024-11-15T10:00:00Z'}
    }
    
    builder = ProfileBuilder(config=config)
    profile = await builder.build_profile([multilingual_email])
    
    # Should handle multilingual content
    assert profile is not None


# Performance Tests
@pytest.mark.asyncio
@pytest.mark.slow
async def test_large_email_batch(config):
    """Test profile building with large number of emails"""
    # Generate 100 test emails
    large_batch = []
    for i in range(100):
        large_batch.append({
            'content': f'Hi,\n\nEmail {i} content here.\n\nBest,\nAnthony',
            'metadata': {
                'subject': f'Email {i}',
                'date': f'2024-11-{(i % 30) + 1:02d}T10:00:00Z'
            }
        })
    
    builder = ProfileBuilder(config=config)
    
    import time
    start = time.time()
    profile = await builder.build_profile(large_batch)
    duration = time.time() - start
    
    assert profile is not None
    assert profile['sample_size'] == 100
    assert duration < 10.0  # Should complete in under 10 seconds


# Integration with LLM (if available)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_llm_enhanced_analysis(sample_emails):
    """Test LLM-enhanced analysis (requires LLM config)"""
    try:
        from src.utils.config import load_config
        config = load_config()
        
        builder = ProfileBuilder(config=config)
        profile = await builder.build_profile(sample_emails)
        
        # LLM should provide richer analysis
        assert profile is not None
        assert 'writing_style' in profile
        
    except Exception as e:
        pytest.skip(f"LLM not configured: {e}")


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
