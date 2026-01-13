
import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add project root
sys.path.insert(0, os.getcwd())

# MOCK DEPENDENCIES
mock_sqlalchemy = MagicMock()
mock_ext = MagicMock()
mock_asyncio = MagicMock()
mock_ext.asyncio = mock_asyncio
mock_sqlalchemy.ext = mock_ext
sys.modules['sqlalchemy'] = mock_sqlalchemy
sys.modules['sqlalchemy.ext'] = mock_ext
sys.modules['sqlalchemy.ext.asyncio'] = mock_asyncio
sys.modules['sqlalchemy.orm'] = MagicMock()
sys.modules['sqlalchemy.future'] = MagicMock()
sys.modules['sqlalchemy.exc'] = MagicMock() # FIX: Add exc module
sys.modules['celery'] = MagicMock()
sys.modules['src.database'] = MagicMock()
sys.modules['src.database.models'] = MagicMock()

# Import
from src.services.ingestion.asana import AsanaIngestor
from src.services.indexing.graph import NodeType, RelationType

async def verify_ingestion():
    print("=== Verifying Ingestion Pipeline (Asana) ===\n")
    
    # Mock Graph
    mock_graph = AsyncMock()
    mock_graph.find_node_by_property.return_value = None # Assume no person exists initially
    
    ingestor = AsanaIngestor(graph_manager=mock_graph, config={})
    
    # Run Sync
    # This uses the hardcoded 'mock_tasks' inside asana.py
    stats = await ingestor.run_sync()
    print(f"Stats: {stats}")
    
    # Assertions
    # 1. Check Task Node Creation
    task_calls = [c for c in mock_graph.add_node.call_args_list if c.kwargs['node_type'] == NodeType.ACTION_ITEM]
    print(f"\n[Test 1] Task Nodes Created: {len(task_calls)}")
    if len(task_calls) >= 2:
        print("  ✅ Tasks created successfully")
        task_1 = task_calls[0].kwargs['properties']
        print(f"  - Task 1: {task_1['name']} (Status: {task_1['status']})")
    else:
         print("  ❌ Failed to create tasks")
         
    # 2. Check Person Node Creation
    person_calls = [c for c in mock_graph.add_node.call_args_list if c.kwargs['node_type'] == NodeType.PERSON]
    print(f"\n[Test 2] Person Nodes Created: {len(person_calls)}")
    if len(person_calls) >= 2:
         print("  ✅ People created successfully")
    else:
         print("  ❌ Failed to create people")
         
    # 3. Check Relationships
    rel_calls = mock_graph.add_relationship.call_args_list
    print(f"\n[Test 3] Relationships Created: {len(rel_calls)}")
    
    assigned_rels = [c for c in rel_calls if c.kwargs['rel_type'] == RelationType.ASSIGNED_TO]
    works_on_rels = [c for c in rel_calls if c.kwargs['rel_type'] == RelationType.WORKS_ON]
    
    if len(assigned_rels) >= 2:
        print(f"  ✅ ASSIGNED_TO relationships: {len(assigned_rels)}")
    else:
        print(f"  ❌ Missing assignment relationships")
        
    if len(works_on_rels) >= 2:
         print(f"  ✅ WORKS_ON relationships: {len(works_on_rels)}")
    else:
         print(f"  ⚠️ Missing WORKS_ON relationships (Optional)")

if __name__ == "__main__":
    try:
        asyncio.run(verify_ingestion())
    except Exception as e:
        print(f"ERROR: {e}")
