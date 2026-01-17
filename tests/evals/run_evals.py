"""
Run Comprehensive Evaluations

This script runs all evaluations for the Clavr agent.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path BEFORE any imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Now import with absolute paths
from tests.evals.runner import run_evaluations
from src.agents.supervisor import SupervisorAgent
from src.database import get_async_db
from api.dependencies import get_config, get_rag_engine


async def main():
    """Run all evaluations"""
    print("="*60)
    print("Clavr Agent Evaluation Suite")
    print("="*60)
    print("\nInitializing components...")
    
    # Initialize components (optional - evals will skip if not available)
    agent = None
    tools_dict = None
    db_session = None
    graph_manager = None
    rag_engine = None
    email_service = None
    
    # Database session will be created per-evaluation as needed
    # This avoids session management issues across async boundaries
    db_session = None  # Will be created when needed by evaluators
    
    try:
        # Try to get config and RAG engine
        config = get_config()
        rag_engine = get_rag_engine()
        
        # Initialize tools for agent
        from src.tools import EmailTool, CalendarTool, TaskTool
        email_tool = EmailTool(config=config, rag_engine=rag_engine, user_id=1)
        calendar_tool = CalendarTool(config=config, user_id=1, rag_engine=rag_engine)
        task_tool = TaskTool(config=config, user_id=1)
        
        # Tools as list for agent
        tools_list = [email_tool, calendar_tool, task_tool]
        
        # Tools as dict for tool selection evaluator (recommend_tools expects dict)
        tools_dict = {
            'email': email_tool,
            'calendar': calendar_tool,
            'tasks': task_tool
        }
        
        # Initialize conversation memory (will use its own session when needed)
        memory = None  # Agent will create memory if needed
        
        # Initialize agent with tools and config
        # Agent will create its own memory and db sessions as needed
        agent = SupervisorAgent(
            config=config,
            tools=tools_list,
            memory=memory
        )
        print("Agent initialized successfully")
    except Exception as e:
        print(f"Warning: Could not initialize agent: {e}")
        import traceback
        traceback.print_exc()
        agent = None
        tools_dict = None
        rag_engine = None
    
    # Run evaluations
    print("\nRunning evaluations...")
    results = await run_evaluations(
        agent=agent,
        tools=tools_dict,  # Pass dict for tool selection eval (recommend_tools expects dict)
        db_session=db_session,
        graph_manager=graph_manager,
        rag_engine=rag_engine,
        email_service=email_service,
        user_id=1,
        output_dir="eval_results"
    )
    
    print("\n" + "="*60)
    print("Evaluation Complete!")
    print("="*60)
    print(f"\nResults saved to: eval_results/")
    print(f"Total evaluations run: {len(results)}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())

