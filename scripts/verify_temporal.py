
import asyncio
import os
from datetime import datetime
from src.ai.temporal_reasoner import TemporalReasoner
class MockConfig:
    pass

class MockGraphManager:
    async def execute_query(self, query, params):
        print(f"Executing query: {query}")
        print(f"Params: {params}")
        if "TimeBlock" in query: # timeline query or something
             return []
        
        # Return dummy activities for testing
        return [{'activities': [
            {'type': 'email', 'time': datetime.now(), 'subject': 'Test Email'},
            {'type': 'meeting', 'time': datetime.now(), 'title': 'Test Meeting'}
        ]}]

async def main():
    config = MockConfig()
    graph = MockGraphManager()
    reasoner = TemporalReasoner(config, graph)
    
    print("--- Testing reason_about_time ---")
    query = "What did I do yesterday?"
    context = await reasoner.reason_about_time(query, user_id=1)
    if context:
        print(f"Summary: {context.summary}")
        print(f"Activities: {len(context.activities)}")
    else:
        print("No context found")

    print("\n--- Testing get_relationship_timeline ---")
    events = await reasoner.get_relationship_timeline(user_id=1, person_id="test@example.com")
    print(f"Timeline events: {len(events)}")

if __name__ == "__main__":
    asyncio.run(main())
