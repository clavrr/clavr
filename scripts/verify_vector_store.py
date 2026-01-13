import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.getcwd())

from src.utils.config import load_config
from src.ai.rag.core.vector_store import create_vector_store
from src.ai.rag.core.embedding_provider import EmbeddingProvider

# Mock embedding provider for test
class MockProvider(EmbeddingProvider):
    def encode(self, text):
        return [0.1] * 768
    def encode_batch(self, texts):
        return [[0.1] * 768 for _ in texts]
    def encode_query(self, text):
        return [0.1] * 768
    def get_dimension(self):
        return 768

def main():
    print("Loading config...")
    config = load_config()
    
    print("Creating vector store...")
    try:
        store = create_vector_store(
            config=config,
            rag_config=config.rag,
            embedding_provider=MockProvider()
        )
        print(f"Vector Store created successfully.")
        print(f"Backend type: {type(store).__name__}")
        
        # Test basic stats
        stats = store.get_stats()
        print(f"Stats: {stats}")
        
    except Exception as e:
        print(f"FAILED to create vector store: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
