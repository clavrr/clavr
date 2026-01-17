"""
Evaluation Runner

Orchestrates and runs all evaluations, generating comprehensive reports.
"""
import asyncio
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from .base import EvaluationMetrics
from .intent_eval import IntentClassificationEvaluator
from .entity_eval import EntityExtractionEvaluator

from .response_eval import ResponseQualityEvaluator
from .preset_eval import PresetFunctionalityEvaluator
from .contact_eval import ContactResolutionEvaluator
from .memory_eval import ConversationMemoryEvaluator
from .e2e_eval import EndToEndEvaluator
from .multistep_eval import MultiStepEvaluator
from .autonomy_eval import AutonomyEvaluator
from .datasets import (
    INTENT_TEST_CASES,

    RESPONSE_QUALITY_TEST_CASES,
    PRESET_TEST_CASES,
    CONTACT_RESOLUTION_TEST_CASES,
    MEMORY_TEST_CASES,
    E2E_TEST_CASES,
    MULTISTEP_TEST_CASES,
    AUTONOMY_TEST_CASES
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class EvaluationRunner:
    """Runs comprehensive evaluation suite"""
    
    def __init__(self,
                 agent: Optional[Any] = None,
                 tools: Optional[Dict[str, Any]] = None,
                 db_session: Optional[Any] = None,
                 graph_manager: Optional[Any] = None,
                 rag_engine: Optional[Any] = None,
                 email_service: Optional[Any] = None,
                 user_id: int = 1,
                 output_dir: str = "eval_results"):
        """
        Initialize evaluation runner
        
        Args:
            agent: ClavrAgent instance for E2E and response evals
            tools: Dictionary of tools for tool selection eval
            db_session: Database session for memory and preset evals
            graph_manager: Neo4j graph manager for contact resolution
            rag_engine: RAG engine for contact resolution
            email_service: Email service for contact resolution
            user_id: User ID for evaluations
            output_dir: Directory to save evaluation results
        """
        self.agent = agent
        self.tools = tools
        self.db_session = db_session
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self.email_service = email_service
        self.user_id = user_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.results: Dict[str, EvaluationMetrics] = {}
        self._db_available = False
    
    def _check_database_connectivity(self) -> None:
        """Check if database is available and accessible"""
        # Check PostgreSQL is running
        import subprocess
        try:
            result = subprocess.run(
                ['pg_isready', '-h', 'localhost', '-p', '5432'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("PostgreSQL is running and accepting connections")
            else:
                logger.warning("PostgreSQL may not be running. Some evaluations may fail.")
                logger.warning("   Start PostgreSQL with: brew services start postgresql@17")
                self._db_available = False
                return
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.warning(f"Could not verify PostgreSQL status: {e}")
            logger.warning("   Make sure PostgreSQL is running: brew services start postgresql@17")
            self._db_available = False
            return
        
        # Try sync connection (for preset evals)
        try:
            from src.database import get_db_context
            with get_db_context() as db:
                from sqlalchemy import text
                db.execute(text("SELECT 1"))
            logger.info("Database connectivity verified (sync)")
            self._db_available = True
        except Exception as e:
            logger.warning(f"Database connectivity check failed (sync): {e}")
            logger.warning("   Preset functionality evaluation may fail")
            logger.warning("   Check your DATABASE_URL in .env file")
            self._db_available = False
    
    async def run_all(self) -> Dict[str, EvaluationMetrics]:
        """
        Run all evaluations
        
        Returns:
            Dictionary of evaluation name -> metrics
        """
        logger.info("="*60)
        logger.info("Starting Comprehensive Evaluation Suite (10 Evaluations)")
        logger.info("="*60)
        
        # Check database connectivity for evals that need it
        self._check_database_connectivity()
        
        # 1. Intent Classification
        logger.info("\n[1/8] Running Intent Classification Evaluation...")
        intent_eval = IntentClassificationEvaluator()
        self.results['intent_classification'] = await intent_eval.evaluate(INTENT_TEST_CASES)
        intent_eval.print_summary()
        
        # 2. Entity Extraction
        logger.info("\n[2/8] Running Entity Extraction Evaluation...")
        entity_eval = EntityExtractionEvaluator()
        self.results['entity_extraction'] = await entity_eval.evaluate(ENTITY_TEST_CASES)
        entity_eval.print_summary()
        
        # 3. Tool Selection needs to be removed as it is deprecated
        logger.info("\n[3/8] Skipping Tool Selection Evaluation (Deprecated)...")
        self.results['tool_selection'] = EvaluationMetrics()
        
        # 4. Response Quality
        if self.agent:
            logger.info("\n[4/8] Running Response Quality Evaluation...")
            response_eval = ResponseQualityEvaluator(agent=self.agent)
            self.results['response_quality'] = await response_eval.evaluate(RESPONSE_QUALITY_TEST_CASES)
            response_eval.print_summary()
        else:
            logger.warning("[4/8] Skipping Response Quality Evaluation (no agent provided)")
            self.results['response_quality'] = EvaluationMetrics()
        
        # 5. Preset Functionality
        # Preset storage uses sync sessions, so we can always run this
        logger.info("\n[5/8] Running Preset Functionality Evaluation...")
        preset_eval = PresetFunctionalityEvaluator(user_id=self.user_id)
        self.results['preset_functionality'] = await preset_eval.evaluate(PRESET_TEST_CASES)
        preset_eval.print_summary()
        
        # 6. Contact Resolution
        if self.graph_manager or self.rag_engine or self.email_service:
            logger.info("\n[6/8] Running Contact Resolution Evaluation...")
            contact_eval = ContactResolutionEvaluator(
                graph_manager=self.graph_manager,
                rag_engine=self.rag_engine,
                email_service=self.email_service,
                user_id=self.user_id
            )
            self.results['contact_resolution'] = await contact_eval.evaluate(CONTACT_RESOLUTION_TEST_CASES)
            contact_eval.print_summary()
        else:
            logger.warning("[6/8] Skipping Contact Resolution Evaluation (no services provided)")
            self.results['contact_resolution'] = EvaluationMetrics()
        
        # 7. Conversation Memory
        # Memory evaluator creates its own session, so always run it
        logger.info("\n[7/8] Running Conversation Memory Evaluation...")
        memory_eval = ConversationMemoryEvaluator(user_id=self.user_id)
        self.results['conversation_memory'] = await memory_eval.evaluate(MEMORY_TEST_CASES)
        memory_eval.print_summary()
        
        # 8. End-to-End
        if self.agent:
            logger.info("\n[8/10] Running End-to-End Evaluation...")
            e2e_eval = EndToEndEvaluator(agent=self.agent)
            self.results['end_to_end'] = await e2e_eval.evaluate(E2E_TEST_CASES)
            e2e_eval.print_summary()
        else:
            logger.warning("[8/10] Skipping End-to-End Evaluation (no agent provided)")
            self.results['end_to_end'] = EvaluationMetrics()
        
        # 9. Multi-Step Query Evaluation
        if self.agent:
            logger.info("\n[9/10] Running Multi-Step Query Evaluation...")
            multistep_eval = MultiStepEvaluator(agent=self.agent)
            self.results['multi_step'] = await multistep_eval.evaluate(MULTISTEP_TEST_CASES)
            multistep_eval.print_summary()
        else:
            logger.warning("[9/10] Skipping Multi-Step Evaluation (no agent provided)")
            self.results['multi_step'] = EvaluationMetrics()
        
        # 10. Autonomy Evaluation
        if self.agent:
            logger.info("\n[10/10] Running Autonomy Evaluation...")
            autonomy_eval = AutonomyEvaluator(agent=self.agent)
            self.results['autonomy'] = await autonomy_eval.evaluate(AUTONOMY_TEST_CASES)
            autonomy_eval.print_summary()
        else:
            logger.warning("[10/10] Skipping Autonomy Evaluation (no agent provided)")
            self.results['autonomy'] = EvaluationMetrics()
        
        # Generate summary report
        self._print_overall_summary()
        
        # Save results
        self._save_results()
        
        return self.results
    
    def _print_overall_summary(self) -> None:
        """Print overall evaluation summary"""
        print("\n" + "="*60)
        print("OVERALL EVALUATION SUMMARY")
        print("="*60)
        
        total_tests = sum(m.total_tests for m in self.results.values())
        total_passed = sum(m.passed_tests for m in self.results.values())
        overall_accuracy = total_passed / total_tests if total_tests > 0 else 0.0
        
        print(f"\nOverall Accuracy: {overall_accuracy:.2%}")
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {total_passed}")
        print(f"Failed: {total_tests - total_passed}")
        
        print("\nPer-Evaluation Breakdown:")
        for name, metrics in self.results.items():
            if metrics.total_tests > 0:
                print(f"  {name.replace('_', ' ').title()}:")
                print(f"    Accuracy: {metrics.accuracy:.2%}")
                print(f"    Tests: {metrics.passed_tests}/{metrics.total_tests}")
                print(f"    Avg Latency: {metrics.average_latency_ms:.2f}ms")
        
        print("="*60 + "\n")
    
    def _save_results(self) -> None:
        """Save all evaluation results to JSON"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"evaluation_results_{timestamp}.json"
        
        output = {
            'timestamp': datetime.utcnow().isoformat(),
            'overall_metrics': {
                'total_tests': sum(m.total_tests for m in self.results.values()),
                'total_passed': sum(m.passed_tests for m in self.results.values()),
                'overall_accuracy': sum(m.passed_tests for m in self.results.values()) / 
                                   sum(m.total_tests for m in self.results.values()) 
                                   if sum(m.total_tests for m in self.results.values()) > 0 else 0.0
            },
            'evaluations': {
                name: metrics.to_dict() for name, metrics in self.results.items()
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Saved evaluation results to {output_file}")


async def run_evaluations(
    agent: Optional[Any] = None,
    tools: Optional[Dict[str, Any]] = None,
    db_session: Optional[Any] = None,
    graph_manager: Optional[Any] = None,
    rag_engine: Optional[Any] = None,
    email_service: Optional[Any] = None,
    user_id: int = 1,
    output_dir: str = "eval_results"
) -> Dict[str, EvaluationMetrics]:
    """
    Convenience function to run all evaluations
    
    Args:
        agent: ClavrAgent instance
        tools: Dictionary of tools
        db_session: Database session
        graph_manager: Neo4j graph manager
        rag_engine: RAG engine
        email_service: Email service
        user_id: User ID
        output_dir: Output directory for results
        
    Returns:
        Dictionary of evaluation results
    """
    runner = EvaluationRunner(
        agent=agent,
        tools=tools,
        db_session=db_session,
        graph_manager=graph_manager,
        rag_engine=rag_engine,
        email_service=email_service,
        user_id=user_id,
        output_dir=output_dir
    )
    
    return await runner.run_all()

