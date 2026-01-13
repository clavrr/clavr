import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.services.indexing.graph.manager import KnowledgeGraphManager, GraphBackend
from src.services.indexing.graph.schema import NodeType, RelationType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

async def main():
    logger.info("Starting ArangoDB Verification...")
    
    # Initialize Manager
    try:
        graph = KnowledgeGraphManager(backend="arangodb")
        logger.info("Successfully initialized KnowledgeGraphManager with ArangoDB backend")
    except Exception as e:
        logger.error(f"Failed to initialize manager: {e}")
        return

    # 1. Add Nodes
    node1_id = "test_user_123"
    node1_props = {"name": "Test User", "email": "test@example.com"}
    
    node2_id = "test_action_456"
    node2_props = {"description": "Buy groceries", "status": "pending"}
    
    logger.info(f"Adding node {node1_id}...")
    try:
        await graph.add_node(node1_id, NodeType.CONTACT, node1_props)
        logger.info("Node 1 added.")
    except Exception as e:
        logger.error(f"Failed to add node 1: {e}")

    logger.info(f"Adding node {node2_id}...")
    try:
        await graph.add_node(node2_id, NodeType.ACTION_ITEM, node2_props)
        logger.info("Node 2 added.")
    except Exception as e:
        logger.error(f"Failed to add node 2: {e}")

    # 2. Add Relationship
    logger.info("Adding relationship...")
    
    # Verify Node 2 exists first
    n2 = await graph.get_node(node2_id)
    if not n2:
        logger.error(f"Node 2 ({node2_id}) NOT FOUND before adding relationship!")
    else:
        logger.info(f"Node 2 found: {n2}")

    try:
        # ActionItem (node2) CREATED_BY Contact (node1)
        await graph.add_relationship(node2_id, node1_id, RelationType.CREATED_BY, {"timestamp": 123456})
        logger.info("Relationship added.")
    except Exception as e:
        logger.error(f"Failed to add relationship: {e}")

    # 3. Retrieve Node
    logger.info("Retrieving node 1...")
    node = await graph.get_node(node1_id)
    if node:
        logger.info(f"Node retrieved: {node}")
    else:
        logger.error("Node not found!")

    # 4. Neighbors
    logger.info("Getting neighbors of node 1...")
    neighbors = await graph.get_neighbors(node1_id)
    logger.info(f"Neighbors: {neighbors}")
    
    # 5. AQL Query
    logger.info("Executing custom AQL...")
    query = "FOR n IN Contact RETURN n"
    results = await graph.query(query)
    logger.info(f"Query results: {len(results)} nodes found")

    # 6. Cleanup
    logger.info("Deleting nodes...")
    await graph.delete_node(node1_id)
    await graph.delete_node(node2_id)
    logger.info("Verification Complete.")

if __name__ == "__main__":
    asyncio.run(main())
