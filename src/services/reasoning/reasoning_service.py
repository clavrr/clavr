"""
Graph Reasoning Service

Orchestrates the "Living" aspect of the memory graph by running specialized
reasoning agents to find patterns, connections, and insights that simple
indexing misses.
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.reasoning.interfaces import ReasoningAgent, ReasoningResult
from src.ai.rag import RAGEngine

logger = setup_logger(__name__)

class GraphReasoningService:
    """
    Orchestrates specialized reasoning agents to enhance the knowledge graph.
    
    Responsibilities:
    1. Manage lifecycle of reasoning agents
    2. Run periodic "Deep Reasoning" cycles
    3. Process agent findings into GraphPattern, Hypothesis, and Insight nodes
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager, rag_engine: Optional[RAGEngine] = None):
        self.config = config
        self.graph = graph_manager
        self.rag_engine = rag_engine
        self.agents: List[ReasoningAgent] = []
        self.is_running = False
        self._cycle_task: Optional[asyncio.Task] = None
        
    def register_agent(self, agent: ReasoningAgent):
        """Register a reasoning agent."""
        self.agents.append(agent)
        logger.info(f"[ReasoningService] Registered agent: {agent.name}")
        
    async def start(self):
        """Start the background reasoning service."""
        if self.is_running:
            return
            
        self.is_running = True
        logger.info("[ReasoningService] Started")
        
        # Start background cycle if configured
        # For now, we'll rely on external triggers or Scheduler
        
    async def stop(self):
        """Stop the service."""
        self.is_running = False
        if self._cycle_task:
            self._cycle_task.cancel()
            
    async def run_reasoning_cycle(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        """
        Run a full reasoning cycle for a user across all agents.
        
        Returns:
            Stats on generated findings
        """
        logger.info(f"[ReasoningService] Starting reasoning cycle for user {user_id}")
        stats = {"patterns": 0, "hypotheses": 0, "insights": 0}
        
        results: List[ReasoningResult] = []
        
        # Run agents concurrently
        tasks = [agent.analyze(user_id, context) for agent in self.agents]
        agent_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, res in enumerate(agent_results):
            if isinstance(res, Exception):
                logger.error(f"[ReasoningService] Agent {self.agents[i].name} failed: {res}")
            elif res:
                results.extend(res)
                
        # Process results
        for result in results:
            success = await self._process_finding(user_id, result)
            if success:
                if result.type == 'pattern':
                    stats["patterns"] += 1
                elif result.type == 'hypothesis':
                    stats["hypotheses"] += 1
                elif result.type == 'insight':
                    stats["insights"] += 1
                    
        logger.info(f"[ReasoningService] Cycle complete. Generated: {stats}")
        return stats
        
    async def _process_finding(self, user_id: int, result: ReasoningResult) -> bool:
        """Store a finding in the graph."""
        try:
            if result.type == 'pattern':
                return await self._store_pattern(user_id, result)
            elif result.type == 'hypothesis':
                return await self._store_hypothesis(user_id, result)
            elif result.type == 'insight':
                return await self._store_insight(user_id, result)
            return False
        except Exception as e:
            logger.error(f"[ReasoningService] Failed to process finding from {result.source_agent}: {e}")
            return False
            
    async def _store_pattern(self, user_id: int, result: ReasoningResult) -> bool:
        """Create a GraphPattern node."""
        content = result.content
        properties = {
            "description": content.get("description", "Unknown pattern"),
            "pattern_type": content.get("pattern_type", "general"),
            "trigger": content.get("trigger"),
            "action": content.get("action"),
            "confidence": result.confidence,
            "frequency": content.get("frequency", 0.0),
            "observation_count": content.get("count", 1),
            "last_observed": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "source": result.source_agent,
            "created_at": datetime.utcnow().isoformat()
        }
        
        node_id = await self.graph.create_node(NodeType.GRAPH_PATTERN, properties)
        
        # Create relationships to related nodes if provided
        related_nodes = content.get('related_nodes', [])
        for related_item in related_nodes:
            try:
                related_id = related_item if isinstance(related_item, str) else related_item.get('id')
                rel_type = RelationType.ABOUT
                if isinstance(related_item, dict):
                    rel_type_str = related_item.get('relation_type', 'ABOUT')
                    rel_type = getattr(RelationType, rel_type_str.upper(), RelationType.ABOUT)
                
                if related_id:
                    await self.graph.create_relationship(
                        from_id=node_id,
                        to_id=related_id,
                        relation_type=rel_type,
                        properties={"confidence": result.confidence}
                    )
            except Exception as rel_err:
                logger.debug(f"[ReasoningService] Failed to create pattern relationship: {rel_err}")
        
        return bool(node_id)
        
    async def _store_hypothesis(self, user_id: int, result: ReasoningResult) -> bool:
        """Create a Hypothesis node."""
        content = result.content
        properties = {
            "statement": content.get("statement", ""),
            "reasoning": content.get("reasoning", ""),
            "confidence": result.confidence,
            "status": "pending",
            "user_id": user_id,
            "source_agent": result.source_agent,
            "created_at": datetime.utcnow().isoformat()
        }
        
        node_id = await self.graph.create_node(NodeType.HYPOTHESIS, properties)
        
        # Link evidence (SUPPORTED_BY)
        evidence_ids = content.get("evidence_ids", [])
        for evidence_id in evidence_ids:
            await self.graph.create_relationship(
                from_id=node_id,
                to_id=evidence_id,
                relation_type=RelationType.SUPPORTED_BY,
                properties={"confidence": result.confidence}
            )
            
        return bool(node_id)
        
    async def _store_insight(self, user_id: int, result: ReasoningResult) -> bool:
        """Create an Insight node (via InsightService logic)."""
        # We manually create it here to ensure it links to the reasoning chain
        content = result.content
        properties = {
            "content": content.get("content", ""),
            "type": content.get("type", "analysis"),
            "confidence": result.confidence,
            "actionable": content.get("actionable", False),
            "reasoning_chain": content.get("reasoning_chain", ""),
            "user_id": user_id,
            "source": result.source_agent,
            "created_at": datetime.utcnow().isoformat()
        }
        
        node_id = await self.graph.create_node(NodeType.INSIGHT, properties)
        
        # Link to related nodes (ABOUT)
        related_ids = content.get("related_ids", [])
        for related_id in related_ids:
            await self.graph.create_relationship(
                from_id=node_id,
                to_id=related_id,
                relation_type=RelationType.ABOUT,
                properties={}
            )
            
        return bool(node_id)

# Global instance management
_reasoning_service: Optional[GraphReasoningService] = None

def get_reasoning_service() -> Optional[GraphReasoningService]:
    return _reasoning_service

def init_reasoning_service(config: Config, graph_manager: KnowledgeGraphManager, rag_engine: Optional[RAGEngine] = None) -> GraphReasoningService:
    global _reasoning_service
    _reasoning_service = GraphReasoningService(config, graph_manager, rag_engine)
    
    # Initialize agents here
    from src.services.reasoning.agents.connection_spotter import ConnectionSpotterAgent
    if rag_engine:
        _reasoning_service.register_agent(ConnectionSpotterAgent(config, graph_manager, rag_engine))
    
    # Register "Living Memory" agents
    from src.services.reasoning.agents.pattern_learning import PatternLearningAgent
    from src.services.reasoning.agents.gap_analysis import GapAnalysisAgent
    from src.services.reasoning.agents.conflict_detector import ConflictDetectorAgent
    from src.services.reasoning.agents.temporal_pattern_agent import TemporalPatternAgent
    
    _reasoning_service.register_agent(PatternLearningAgent(config, graph_manager))
    _reasoning_service.register_agent(GapAnalysisAgent(config, graph_manager))
    _reasoning_service.register_agent(ConflictDetectorAgent(config, graph_manager))
    _reasoning_service.register_agent(TemporalPatternAgent(config, graph_manager))
    
    logger.info("[ReasoningService] Initialized with 5 agents")
    return _reasoning_service

