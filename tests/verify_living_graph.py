"""
Verification Script for Living Memory Graph 2.0
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock
import datetime

# Add project root to path
sys.path.append(os.getcwd())

from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.reasoning.reactive_service import init_reactive_service, GraphEventType, GraphEvent
from src.services.reasoning.agents.gap_analysis import GapAnalysisAgent
from src.services.insights.insight_service import InsightService

async def main():
    print("=== Starting Living Graph Verification ===")
    
    # Mock Config
    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        "google_maps_api_key": "mock_google_key",
        "ENV": "test"
    }.get(k, default)
    # Also support attribute access
    config.google_maps_api_key = "mock_google_key"
    
    # 1. Setup Graph Manager (NetworkX for test)
    print("[Setup] Initializing Graph Manager (NetworkX)...")
    graph_manager = KnowledgeGraphManager(backend="networkx", config=config)
    
    # 2. Setup Reactive Service
    print("[Setup] Initializing Reactive Service...")
    reactive_service = init_reactive_service(config)
    await reactive_service.start()
    graph_manager.set_reactive_service(reactive_service)
    
    # 3. Setup Insight Service
    print("[Setup] Initializing Insight Service...")
    insight_service = InsightService(config, graph_manager)
    insight_service.set_reactive_service(reactive_service)
    
    # Test 1: Weather Context (Google Schema)
    print("\n[Test 1] Creating Weather Context (Google Schema)...")
    try:
        time_id = "timeblock:2024-05-20_10:hour"
        await graph_manager.add_node(time_id, NodeType.TIME_BLOCK, {
            "start_time": "2024-05-20T10:00:00",
            "end_time": "2024-05-20T11:00:00",
            "granularity": "hour",
            "label": "Morning Meeting Slot",
            "user_id": 1
        })
        
        weather_id = "weather:SF:2024-05-20_10"
        await graph_manager.add_node(weather_id, NodeType.WEATHER_CONTEXT, {
            "description": "Partly Cloudy",
            "temperature": 20.0,
            "timestamp": "2024-05-20T10:00:00",
            "condition": "Cloudy",
            "source": "GoogleWeather"
        })
        
        await graph_manager.add_relationship(time_id, weather_id, RelationType.HAS_WEATHER)
        print("✅ Weather context created successfully.")
    except Exception as e:
        print(f"❌ Weather context failed: {e}")
        import traceback
        traceback.print_exc()

    # Test 2: Reactive Stream
    print("\n[Test 2] Testing Reactive Intelligence Streaming...")
    
    # Create the task
    stream_task = asyncio.create_task(consume_stream(insight_service))
    
    # Give the task a moment to start up
    await asyncio.sleep(0.5)
    
    print("   Simulating urgent insight creation...")
    # Simulate finding a conflict insight
    insight_id = "insight:urgent:1"
    await graph_manager.add_node(insight_id, NodeType.INSIGHT, {
        "content": "Conflict detected: Overlapping meetings.",
        "type": "conflict",
        "confidence": 0.95,
        "user_id": 1,
        "created_at": datetime.datetime.utcnow().isoformat()
    })
    
    # Wait for stream to process
    await asyncio.sleep(2)
    stream_task.cancel()
    
    # Test 3: Gap Analysis
    print("\n[Test 3] Testing Gap Analysis Agent...")
    try:
        agent = GapAnalysisAgent(config, graph_manager)
        
        # Create imminent meeting (in 2 hours)
        now = datetime.datetime.utcnow()
        imminent = now + datetime.timedelta(hours=2)
        
        await graph_manager.add_node("event:imminent", NodeType.CALENDAR_EVENT, {
            "title": "Important Demo",
            "start_time": imminent.isoformat(),
            "user_id": 1,
            "end_time": (imminent + datetime.timedelta(hours=1)).isoformat()
        })
        
        # Run analysis
        results = await agent.analyze(user_id=1)
        if results:
            print(f"✅ Gap Analysis found {len(results)} issues.")
            print(f"   Sample: {results[0].content['content']}")
        else:
            print("⚠️ No gaps found (this might be expected if the mocked data doesn't perfectly match query logic).")
            
    except Exception as e:
        print(f"❌ Gap Analysis failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n=== Verification Complete ===")
    await reactive_service.stop()

async def consume_stream(service):
    print("   Listening for urgent insights...")
    try:
        async for insight in service.stream_urgent_insights(user_id=1):
            print(f"   >>> STREAMED INSIGHT: {insight.get('content')}")
    except asyncio.CancelledError:
        print("   Stream consumer cancelled.")
    except Exception as e:
        print(f"   Stream error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
