
import asyncio
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.getcwd())

from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.topic_extractor import TopicExtractor
from src.services.indexing.cross_app_correlator import CrossAppCorrelator, Correlation
from src.services.indexing.temporal_indexer import TemporalIndexer
from src.services.insights.insight_service import InsightService

async def test_topic_extractor():
    print("\n--- Testing TopicExtractor Clustering ---")
    mock_graph = MagicMock(spec=KnowledgeGraphManager)
    config = MagicMock(spec=Config)
    
    extractor = TopicExtractor(config, mock_graph)
    # Mock LLM
    extractor.llm = MagicMock()
    extractor.llm.invoke.return_value = "YES" # Assume LLM says yes they are same
    
    # Mock existing topics in graph
    mock_graph.query.return_value = [
        {"id": "topic:existing", "name": "Q4 Launch Strategy", "keywords": ["launch", "q4", "strategy"]}
    ]
    
    # Test _find_similar_topic
    print("Testing _find_similar_topic with semantic match...")
    result = await extractor._find_similar_topic(
        name="Q4 Product Release",
        user_id=1,
        keywords=["release", "q4", "product"]
    )
    
    if result and result["id"] == "topic:existing":
        print("✅ Success: Found semantically similar topic via keyword overlap + LLM")
    else:
        print(f"❌ Failed: Did not find similar topic. Result: {result}")

async def test_cross_app_correlator():
    print("\n--- Testing CrossAppCorrelator Linking ---")
    mock_graph = MagicMock(spec=KnowledgeGraphManager)
    mock_rag = MagicMock()
    config = MagicMock(spec=Config)
    
    correlator = CrossAppCorrelator(config, mock_rag, mock_graph)
    
    # Test relationship determination
    print("Testing relationship type determination...")
    
    correlation = Correlation(
        source_node_id="email:1",
        target_node_id="task:1",
        target_source="asana",
        similarity_score=0.9,
        target_content_preview="This is a follow up to our meeting...",
        discovered_at=datetime.utcnow()
    )
    
    mock_graph.get_node.return_value = {"id": "exists"}
    
    await correlator._create_correlation_relationship(correlation)
    
    # Verify graph call args
    args = mock_graph.add_relationship.call_args
    if args:
        kwargs = args[1]
        rel_type = kwargs.get("rel_type")
        context = kwargs.get("properties", {}).get("context")
        
        if rel_type == "FOLLOWS" and context == "follow_up":
            print("✅ Success: Correctly identified FOLLOWS relationship from content")
        else:
            print(f"❌ Failed: Wrong relationship type. Got {rel_type}, context {context}")
    else:
        print("❌ Failed: add_relationship not called")

async def test_temporal_indexer_episodes():
    print("\n--- Testing TemporalIndexer Episode Detection ---")
    mock_graph = MagicMock(spec=KnowledgeGraphManager)
    config = MagicMock(spec=Config)
    
    indexer = TemporalIndexer(config, mock_graph)
    
    # Mock timeline data (high activity for 3 days)
    mock_timeline = [
        {"start_time": "2024-12-01T00:00:00", "event_count": 10},
        {"start_time": "2024-12-02T00:00:00", "event_count": 10},
        {"start_time": "2024-12-03T00:00:00", "event_count": 100}, # Spike
        {"start_time": "2024-12-04T00:00:00", "event_count": 120}, # Spike
        {"start_time": "2024-12-05T00:00:00", "event_count": 110}, # Spike
        {"start_time": "2024-12-06T00:00:00", "event_count": 10}
    ]
    
    indexer.get_timeline = AsyncMock(return_value=mock_timeline)
    indexer._create_episode = AsyncMock(return_value={"id": "episode:1"})
    
    episodes = await indexer.detect_episodes(1, datetime.now(), datetime.now())
    
    if len(episodes) == 1:
        print("✅ Success: Detected 1 high-activity episode")
    else:
        print(f"❌ Failed: Expected 1 episode, got {len(episodes)}")

async def run_tests():
    await test_topic_extractor()
    await test_cross_app_correlator()
    await test_temporal_indexer_episodes()
    print("\nTests Complete.")

if __name__ == "__main__":
    asyncio.run(run_tests())
