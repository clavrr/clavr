import sys
import os
import asyncio
import time
from unittest.mock import MagicMock

# Ensure src is in path
sys.path.append(os.getcwd())

# Mock RAGEngine to distinguish from logic latency
import sys
from unittest.mock import MagicMock

# Mock module
mock_rag_module = MagicMock()
sys.modules["src.ai.rag.core.rag_engine"] = mock_rag_module

class MockRAGEngine:
    def __init__(self, config, rag_config=None):
        self.vector_store = MagicMock()
        async def mock_asearch(*args, **kwargs): return [{"content": "Mock result"}]
        self.vector_store.asearch = mock_asearch
        
    def get_scoped_view(self, collection, user_id):
            view = MagicMock()
            async def mock_scoped_asearch(*args, **kwargs): return [{"content": "Mock scoped result"}]
            view.asearch = mock_scoped_asearch
            return view

mock_rag_module.RAGEngine = MockRAGEngine

# Mock InteractionsClient
class MockInteractionsClient:
    def __init__(self, *args, **kwargs):
        self.is_available = True
    async def create_interaction(self, input, model=None, **kwargs):
        await asyncio.sleep(0.05)
        res = MagicMock()
        # Mock a planning response if it looks like a planning request
        if "[PLANNING]" in input:
             res.text = '[{"step": 1, "domain": "email", "query": "Search emails"}, {"step": 2, "domain": "calendar", "query": "Check calendar"}]'
        else:
             res.text = '{"category": "email"}'
        res.id = "mock_id"
        return res
    async def get_interaction(self, id):
        return MagicMock(text='{"category": "email"}')

import src.ai.interactions_client as interactions_mod
interactions_mod.InteractionsClient = MockInteractionsClient

# Mock LLM Logic
class MockLLM:
    def invoke(self, messages):
        time.sleep(0.05) # Simulate 50ms network
        res = MagicMock()
        # Return something that looks like JSON if requested
        res.content = '{"category": "email", "action": "search", "query": "emails"}'
        return res
        
    async def ainvoke(self, messages):
         await asyncio.sleep(0.05)
         res = MagicMock()
         res.content = '{"category": "email"}'
         return res

# Mock Config
class MockConfig:
    def __init__(self):
        # RAG Config class to support copy()
        class RAGConfigMock:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
            def copy(self, update=None):
                new_obj = RAGConfigMock(**self.__dict__)
                if update: new_obj.__dict__.update(update)
                return new_obj
            def __getattr__(self, name): return self.__dict__.get(name)

        self.rag = RAGConfigMock(
            enabled=True, 
            embedding_model="text-embedding-3-small", 
            embedding_provider="openai", 
            vector_db_type="qdrant", 
            collection_name="test", 
            api_key="mock", 
            url="mock",
            max_retries=3,
            retry_base_delay=1.0,
            embedding_cache_size=1000,
            embedding_cache_ttl_hours=24
        )
        self.llm = type('obj', (object,), {'fast_model': "gemini-flash", 'smart_model': "gemini-pro"})
        self.database = type('obj', (object,), {'url': None})
        self.ai = type('obj', (object,), {'api_key': 'mock'})
        self._data = {"rag": {}, "llm": {}, "ai": {}}
        
    def dict(self): return self._data
    def __getitem__(self, item): return self._data[item]
    def get(self, item, default=None): return self._data.get(item, default)

async def profile_latency():
    print("--- Latency Profiling Started ---")
    
    from src.agents.supervisor import SupervisorAgent
    from src.utils.latency import LatencyMonitor
    from src.ai.llm_factory import LLMFactory
    
    # Patch LLM Factory to return MockLLM
    LLMFactory.get_llm_for_provider = MagicMock(return_value=MockLLM())
    LLMFactory.get_google_llm = MagicMock(return_value=MockLLM())

    config = MockConfig()
    tools = []
    
    # Initialize
    with LatencyMonitor("Initialization"):
        supervisor = SupervisorAgent(config=config, tools=tools, user_id=123)
    
    # Warmup
    print("\n[Warmup Run]")
    await supervisor.route_and_execute("Hello", user_id=123)
    
    # Profile Run 1: Simple Routing
    print("\n[Profile Run 1: Simple Routing]")
    with LatencyMonitor("Total Request Latency"):
        await supervisor.route_and_execute("Check my emails", user_id=123)

    # Profile Run 2: "Complex" Plan (Mocked to be single step by MockLLM but exercises logic)
    print("\n[Profile Run 2: Complex Query]")
    with LatencyMonitor("Total Request Latency"):
        await supervisor.route_and_execute("Plan my week and check emails", user_id=123)

if __name__ == "__main__":
    asyncio.run(profile_latency())
