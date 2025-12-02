"""
Routing Analytics - Track and analyze routing decisions

This module provides analytics and tracking for routing decisions to enable
continuous improvement of the agent's routing accuracy. It:

1. Tracks routing decisions with metadata
2. Measures routing accuracy and confidence
3. Identifies patterns in routing errors
4. Provides insights for optimization
5. Enables A/B testing of routing strategies

Key Metrics:
- Routing accuracy (correct vs incorrect)
- Average confidence scores
- Most common misrouting patterns
- Domain-specific accuracy rates (EMAIL, TASK, CALENDAR, NOTION)
- Parser utilization rates
- Query complexity distribution

Architecture:
    Tool/Orchestrator → RoutingAnalytics → Storage → Analytics Dashboard

Use Cases:
- Monitor routing accuracy over time
- Identify problematic query patterns
- Validate parser improvements
- Optimize confidence thresholds
- Track A/B test results

Integration:
- Orchestrator: Calls record_routing() after each routing decision
- ExecutionPlanner: Calls record_correction() when domain validator corrects routing
- DomainValidator: Provides confidence scores and domain detection
- CrossDomainHandler: Records cross-domain query metrics
- ToolDomainConfig: Normalizes domain names for consistent tracking
- ExecutionStep: Uses step.domain for domain tracking
- RoutingAnalyticsConfig: Centralized configuration and thresholds
"""

import json
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from enum import Enum

from ....utils.logger import setup_logger
from .tool_domain_config import get_tool_domain_config, Domain

logger = setup_logger(__name__)


class RoutingAnalyticsConfig:
    """Centralized configuration for routing analytics"""
    
    # Database settings
    DEFAULT_DB_PATH = "data/routing_analytics.db"
    ENABLE_TRACKING = True
    
    # Metrics thresholds
    MIN_PATTERN_OCCURRENCES = 2
    MAX_PATTERNS_IN_REPORT = 10
    
    # Time windows (days)
    DEFAULT_METRICS_PERIOD = 7
    LONG_TERM_PERIOD = 30
    
    # Confidence thresholds
    MIN_CONFIDENCE_FOR_REPORTING = 0.5
    
    # Query analysis
    MAX_QUERY_LENGTH_STORED = 500
    PATTERN_HASH_SEPARATOR = "|"
    
    # Report settings
    REPORT_WIDTH = 60
    CONFIDENCE_BINS = 10
    
    @classmethod
    def get_db_path(cls) -> str:
        """Get database path with fallback"""
        return cls.DEFAULT_DB_PATH
    
    @classmethod
    def is_tracking_enabled(cls) -> bool:
        """Check if tracking is enabled"""
        return cls.ENABLE_TRACKING


class RoutingOutcome(Enum):
    """Outcome of a routing decision"""
    SUCCESS = "success"
    FAILURE = "failure"
    CORRECTION = "correction"  # Auto-corrected by validator
    UNCERTAIN = "uncertain"  # Low confidence
    MIXED = "mixed"  # Cross-domain query


class RoutingAnalytics:
    """
    Track and analyze routing decisions for continuous improvement
    
    Features:
    - Real-time tracking of routing decisions
    - Historical analysis and trends
    - Misrouting pattern detection
    - Confidence score analysis
    - Domain-specific metrics
    - Export capabilities for dashboards
    
    Example:
        >>> analytics = RoutingAnalytics(db_path="analytics.db")
        >>> analytics.record_routing(
        ...     query="Show my tasks",
        ...     detected_domain="task",
        ...     routed_tool="task",
        ...     confidence=0.95,
        ...     outcome=RoutingOutcome.SUCCESS
        ... )
        >>> metrics = analytics.get_metrics(days=7)
        >>> print(f"Accuracy: {metrics['accuracy']:.1%}")
    """
    
    def __init__(self, db_path: Optional[str] = None, enable_tracking: Optional[bool] = None):
        """
        Initialize routing analytics
        
        Args:
            db_path: Path to SQLite database for persistent storage.
                    If None, uses RoutingAnalyticsConfig.DEFAULT_DB_PATH.
            enable_tracking: If False, tracking is disabled (no-op mode).
                           If None, uses RoutingAnalyticsConfig.ENABLE_TRACKING.
        """
        # Use config defaults if not explicitly provided
        if enable_tracking is None:
            enable_tracking = RoutingAnalyticsConfig.ENABLE_TRACKING
        
        self.enable_tracking = enable_tracking
        
        # Initialize ToolDomainConfig for domain normalization
        self.tool_domain_config = get_tool_domain_config()
        
        if not enable_tracking:
            logger.info("[ANALYTICS] Tracking disabled")
            self.db_path = None
            self.conn = None
            return
        
        # Use config database path if not provided
        if db_path is None:
            db_path = RoutingAnalyticsConfig.DEFAULT_DB_PATH
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        logger.info(f"[ANALYTICS] Initialized with database: {self.db_path}")
    
    def _init_database(self):
        """Initialize SQLite database schema"""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        cursor = self.conn.cursor()
        
        # Routing decisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routing_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                query_length INTEGER,
                detected_domain TEXT,
                routed_tool TEXT NOT NULL,
                confidence REAL,
                parser_used BOOLEAN,
                validator_used BOOLEAN,
                cross_domain BOOLEAN,
                outcome TEXT NOT NULL,
                execution_time_ms REAL,
                error_message TEXT,
                metadata TEXT,
                user_id INTEGER,
                session_id TEXT
            )
        """)
        
        # Corrections table (for auto-corrected routing)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routing_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                routing_decision_id INTEGER,
                timestamp TEXT NOT NULL,
                original_tool TEXT NOT NULL,
                corrected_tool TEXT NOT NULL,
                correction_reason TEXT,
                validator_confidence REAL,
                FOREIGN KEY (routing_decision_id) REFERENCES routing_decisions(id)
            )
        """)
        
        # Misrouting patterns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS misrouting_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_hash TEXT UNIQUE NOT NULL,
                query_pattern TEXT NOT NULL,
                wrong_tool TEXT NOT NULL,
                correct_tool TEXT NOT NULL,
                occurrences INTEGER DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                avg_confidence REAL,
                resolved BOOLEAN DEFAULT 0
            )
        """)
        
        # Performance metrics table (aggregated)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                date TEXT PRIMARY KEY,
                total_routings INTEGER,
                successful_routings INTEGER,
                failed_routings INTEGER,
                corrected_routings INTEGER,
                avg_confidence REAL,
                avg_execution_time_ms REAL,
                parser_usage_rate REAL,
                validator_usage_rate REAL,
                cross_domain_rate REAL
            )
        """)
        
        # Create indices for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON routing_decisions(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcome ON routing_decisions(outcome)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_domain ON routing_decisions(detected_domain)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool ON routing_decisions(routed_tool)")
        
        self.conn.commit()
        logger.info("[ANALYTICS] Database schema initialized")
    
    def _normalize_domain(self, domain: Optional[str]) -> Optional[str]:
        """
        Normalize domain string using ToolDomainConfig.
        
        Args:
            domain: Domain string (e.g., 'email', 'task', 'notion')
            
        Returns:
            Normalized domain string or None
        """
        if not domain:
            return None
        
        # Try to normalize using ToolDomainConfig
        domain_enum = self.tool_domain_config.normalize_domain_string(domain)
        if domain_enum:
            return domain_enum.value
        
        # Fallback: lowercase and return
        return domain.lower()
    
    def record_routing(
        self,
        query: str,
        routed_tool: str,
        detected_domain: Optional[str] = None,
        confidence: Optional[float] = None,
        outcome: RoutingOutcome = RoutingOutcome.SUCCESS,
        parser_used: bool = False,
        validator_used: bool = False,
        cross_domain: bool = False,
        execution_time_ms: Optional[float] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        execution_step: Optional[Any] = None  # ExecutionStep object for domain extraction
    ) -> int:
        """
        Record a routing decision
        
        Args:
            query: User's query
            routed_tool: Tool that was selected
            detected_domain: Domain detected by parser/validator (will be normalized)
            confidence: Confidence score (0.0-1.0)
            outcome: Outcome of routing (success, failure, etc.)
            parser_used: Whether parser was used
            validator_used: Whether domain validator was used
            cross_domain: Whether this was a cross-domain query
            execution_time_ms: Execution time in milliseconds
            error_message: Error message if outcome is failure
            metadata: Additional metadata (JSON-serializable dict)
            user_id: Optional user ID
            session_id: Optional session ID
            execution_step: Optional ExecutionStep object (will extract domain if detected_domain not provided)
            
        Returns:
            ID of the recorded decision
        """
        if not self.enable_tracking:
            return -1
        
        # Extract domain from ExecutionStep if available and not provided
        if execution_step and not detected_domain:
            if hasattr(execution_step, 'get_domain'):
                detected_domain = execution_step.get_domain()
            elif hasattr(execution_step, 'domain') and execution_step.domain:
                detected_domain = execution_step.domain
        
        # Normalize domain using ToolDomainConfig
        normalized_domain = self._normalize_domain(detected_domain)
        
        # Normalize routed_tool name
        normalized_tool = self.tool_domain_config.normalize_tool_name(routed_tool)
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO routing_decisions (
                timestamp, query, query_length, detected_domain, routed_tool,
                confidence, parser_used, validator_used, cross_domain, outcome,
                execution_time_ms, error_message, metadata, user_id, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            query[:RoutingAnalyticsConfig.MAX_QUERY_LENGTH_STORED],  # Truncate if needed
            len(query),
            normalized_domain,
            normalized_tool,
            confidence,
            parser_used,
            validator_used,
            cross_domain,
            outcome.value,
            execution_time_ms,
            error_message,
            json.dumps(metadata) if metadata else None,
            user_id,
            session_id
        ))
        
        self.conn.commit()
        decision_id = cursor.lastrowid
        
        confidence_str = f"{confidence:.2f}" if confidence else "N/A"
        domain_str = f", domain={normalized_domain}" if normalized_domain else ""
        logger.debug(
            f"[ANALYTICS] Recorded routing: '{query[:50]}...' → {normalized_tool}{domain_str} "
            f"({outcome.value}, confidence={confidence_str})"
        )
        
        return decision_id
    
    def record_correction(
        self,
        decision_id: int,
        original_tool: str,
        corrected_tool: str,
        reason: str,
        validator_confidence: Optional[float] = None
    ):
        """
        Record an auto-correction by the domain validator
        
        Args:
            decision_id: ID of the routing decision that was corrected
            original_tool: Original (incorrect) tool (will be normalized)
            corrected_tool: Corrected tool (will be normalized)
            reason: Reason for correction
            validator_confidence: Validator's confidence in correction
        """
        if not self.enable_tracking:
            return
        
        # Normalize tool names
        normalized_original = self.tool_domain_config.normalize_tool_name(original_tool)
        normalized_corrected = self.tool_domain_config.normalize_tool_name(corrected_tool)
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO routing_corrections (
                routing_decision_id, timestamp, original_tool, corrected_tool,
                correction_reason, validator_confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            decision_id,
            datetime.now().isoformat(),
            normalized_original,
            normalized_corrected,
            reason,
            validator_confidence
        ))
        
        self.conn.commit()
        
        logger.info(
            f"[ANALYTICS] Recorded correction: {normalized_original} → {normalized_corrected} "
            f"(reason: {reason})"
        )
    
    def record_domain_validation(
        self,
        query: str,
        detected_domain: str,
        target_tool: str,
        validation_valid: bool,
        validation_confidence: float,
        detected_confidence: float,
        decision_id: Optional[int] = None
    ):
        """
        Record results from domain validation for analytics
        
        Args:
            query: Original query
            detected_domain: Domain detected by validator (will be normalized)
            target_tool: Tool being routed to (will be normalized)
            validation_valid: Whether validation passed
            validation_confidence: Confidence of validation result
            detected_confidence: Confidence of domain detection
            decision_id: Optional decision ID to link with routing record
        """
        if not self.enable_tracking:
            return
        
        # Normalize domain and tool
        normalized_domain = self._normalize_domain(detected_domain)
        normalized_tool = self.tool_domain_config.normalize_tool_name(target_tool)
        
        outcome = RoutingOutcome.SUCCESS if validation_valid else RoutingOutcome.FAILURE
        
        self.record_routing(
            query=query,
            routed_tool=normalized_tool,
            detected_domain=normalized_domain,
            confidence=validation_confidence,
            outcome=outcome,
            parser_used=False,
            validator_used=True,
            cross_domain=False,
            metadata={
                'detected_confidence': detected_confidence,
                'validation_confidence': validation_confidence,
                'linked_decision_id': decision_id
            }
        )
    
    def record_misrouting_pattern(
        self,
        query_pattern: str,
        wrong_tool: str,
        correct_tool: str,
        confidence: Optional[float] = None
    ):
        """
        Record or update a misrouting pattern
        
        Args:
            query_pattern: Pattern that was misrouted (e.g., "What tasks...")
            wrong_tool: Tool that was incorrectly selected
            correct_tool: Tool that should have been selected
            confidence: Confidence score when misrouting occurred
        """
        if not self.enable_tracking:
            return
        
        # Create pattern hash
        pattern_hash = f"{query_pattern}{RoutingAnalyticsConfig.PATTERN_HASH_SEPARATOR}{wrong_tool}{RoutingAnalyticsConfig.PATTERN_HASH_SEPARATOR}{correct_tool}"
        
        cursor = self.conn.cursor()
        
        # Check if pattern exists
        cursor.execute(
            "SELECT id, occurrences, avg_confidence FROM misrouting_patterns WHERE pattern_hash = ?",
            (pattern_hash,)
        )
        result = cursor.fetchone()
        
        if result:
            # Update existing pattern
            pattern_id, occurrences, avg_conf = result
            new_occurrences = occurrences + 1
            
            # Update average confidence
            if confidence is not None and avg_conf is not None:
                new_avg_conf = (avg_conf * occurrences + confidence) / new_occurrences
            elif confidence is not None:
                new_avg_conf = confidence
            else:
                new_avg_conf = avg_conf
            
            cursor.execute("""
                UPDATE misrouting_patterns
                SET occurrences = ?, last_seen = ?, avg_confidence = ?
                WHERE id = ?
            """, (new_occurrences, datetime.now().isoformat(), new_avg_conf, pattern_id))
            
        else:
            # Insert new pattern
            cursor.execute("""
                INSERT INTO misrouting_patterns (
                    pattern_hash, query_pattern, wrong_tool, correct_tool,
                    first_seen, last_seen, avg_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                pattern_hash,
                query_pattern[:RoutingAnalyticsConfig.MAX_QUERY_LENGTH_STORED],
                wrong_tool,
                correct_tool,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                confidence
            ))
        
        self.conn.commit()
        
        logger.warning(
            f"[ANALYTICS] Misrouting pattern: '{query_pattern[:50]}...' "
            f"routed to {wrong_tool} (should be {correct_tool})"
        )
    
    def get_metrics(
        self,
        days: int = None,
        domain: Optional[str] = None,
        tool: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get routing metrics for a time period
        
        Args:
            days: Number of days to look back. If None, uses RoutingAnalyticsConfig.DEFAULT_METRICS_PERIOD
            domain: Optional domain filter
            tool: Optional tool filter
            
        Returns:
            Dictionary with metrics
        """
        if not self.enable_tracking:
            return {'error': 'Tracking disabled'}
        
        if days is None:
            days = RoutingAnalyticsConfig.DEFAULT_METRICS_PERIOD
        
        cursor = self.conn.cursor()
        
        # Build query with filters
        where_clauses = ["timestamp >= ?"]
        params = [
            (datetime.now() - timedelta(days=days)).isoformat()
        ]
        
        if domain:
            where_clauses.append("detected_domain = ?")
            params.append(domain)
        
        if tool:
            where_clauses.append("routed_tool = ?")
            params.append(tool)
        
        where_clause = " AND ".join(where_clauses)
        
        # Total routings
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause}",
            params
        )
        total_routings = cursor.fetchone()[0]
        
        if total_routings == 0:
            return {
                'total_routings': 0,
                'accuracy': 0.0,
                'message': 'No routing data for specified period'
            }
        
        # Successful routings
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause} AND outcome = ?",
            params + ['success']
        )
        successful_routings = cursor.fetchone()[0]
        
        # Failed routings
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause} AND outcome = ?",
            params + ['failure']
        )
        failed_routings = cursor.fetchone()[0]
        
        # Corrected routings
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause} AND outcome = ?",
            params + ['correction']
        )
        corrected_routings = cursor.fetchone()[0]
        
        # Average confidence
        cursor.execute(
            f"SELECT AVG(confidence) FROM routing_decisions WHERE {where_clause} AND confidence IS NOT NULL",
            params
        )
        avg_confidence = cursor.fetchone()[0] or 0.0
        
        # Average execution time
        cursor.execute(
            f"SELECT AVG(execution_time_ms) FROM routing_decisions WHERE {where_clause} AND execution_time_ms IS NOT NULL",
            params
        )
        avg_execution_time = cursor.fetchone()[0] or 0.0
        
        # Parser usage rate
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause} AND parser_used = 1",
            params
        )
        parser_used_count = cursor.fetchone()[0]
        
        # Validator usage rate
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause} AND validator_used = 1",
            params
        )
        validator_used_count = cursor.fetchone()[0]
        
        # Cross-domain rate
        cursor.execute(
            f"SELECT COUNT(*) FROM routing_decisions WHERE {where_clause} AND cross_domain = 1",
            params
        )
        cross_domain_count = cursor.fetchone()[0]
        
        # Calculate accuracy
        accuracy = successful_routings / total_routings if total_routings > 0 else 0.0
        
        # Calculate rates
        parser_usage_rate = parser_used_count / total_routings if total_routings > 0 else 0.0
        validator_usage_rate = validator_used_count / total_routings if total_routings > 0 else 0.0
        cross_domain_rate = cross_domain_count / total_routings if total_routings > 0 else 0.0
        
        return {
            'period_days': days,
            'total_routings': total_routings,
            'successful_routings': successful_routings,
            'failed_routings': failed_routings,
            'corrected_routings': corrected_routings,
            'accuracy': accuracy,
            'avg_confidence': avg_confidence,
            'avg_execution_time_ms': avg_execution_time,
            'parser_usage_rate': parser_usage_rate,
            'validator_usage_rate': validator_usage_rate,
            'cross_domain_rate': cross_domain_rate,
            'domain_filter': domain,
            'tool_filter': tool
        }
    
    def get_misrouting_patterns(
        self,
        min_occurrences: int = None,
        unresolved_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get common misrouting patterns
        
        Args:
            min_occurrences: Minimum number of occurrences to include.
                           If None, uses RoutingAnalyticsConfig.MIN_PATTERN_OCCURRENCES
            unresolved_only: Only show unresolved patterns
            
        Returns:
            List of misrouting patterns sorted by occurrences
        """
        if not self.enable_tracking:
            return []
        
        if min_occurrences is None:
            min_occurrences = RoutingAnalyticsConfig.MIN_PATTERN_OCCURRENCES
        
        cursor = self.conn.cursor()
        
        query = """
            SELECT query_pattern, wrong_tool, correct_tool, occurrences,
                   first_seen, last_seen, avg_confidence, resolved
            FROM misrouting_patterns
            WHERE occurrences >= ?
        """
        params = [min_occurrences]
        
        if unresolved_only:
            query += " AND resolved = 0"
        
        query += " ORDER BY occurrences DESC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        patterns = []
        for row in results:
            patterns.append({
                'query_pattern': row[0],
                'wrong_tool': row[1],
                'correct_tool': row[2],
                'occurrences': row[3],
                'first_seen': row[4],
                'last_seen': row[5],
                'avg_confidence': row[6],
                'resolved': bool(row[7])
            })
        
        return patterns
    
    def get_domain_accuracy(self, days: int = 7) -> Dict[str, float]:
        """
        Get accuracy by domain
        
        Args:
            days: Number of days to look back
            
        Returns:
            Dictionary mapping domain to accuracy
        """
        if not self.enable_tracking:
            return {}
        
        cursor = self.conn.cursor()
        
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute("""
            SELECT detected_domain,
                   COUNT(*) as total,
                   SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successful
            FROM routing_decisions
            WHERE timestamp >= ? AND detected_domain IS NOT NULL
            GROUP BY detected_domain
        """, (since,))
        
        results = cursor.fetchall()
        
        accuracy_by_domain = {}
        for domain, total, successful in results:
            accuracy_by_domain[domain] = successful / total if total > 0 else 0.0
        
        return accuracy_by_domain
    
    def get_tool_usage(self, days: int = 7) -> Dict[str, int]:
        """
        Get tool usage counts
        
        Args:
            days: Number of days to look back
            
        Returns:
            Dictionary mapping tool name to usage count
        """
        if not self.enable_tracking:
            return {}
        
        cursor = self.conn.cursor()
        
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute("""
            SELECT routed_tool, COUNT(*) as count
            FROM routing_decisions
            WHERE timestamp >= ?
            GROUP BY routed_tool
            ORDER BY count DESC
        """, (since,))
        
        results = cursor.fetchall()
        
        return {tool: count for tool, count in results}
    
    def get_confidence_distribution(self, days: int = 7, bins: Optional[int] = None) -> Dict[str, int]:
        """
        Get distribution of confidence scores
        
        Args:
            days: Number of days to look back
            bins: Number of bins for histogram. If None, uses RoutingAnalyticsConfig.CONFIDENCE_BINS
            
        Returns:
            Dictionary mapping confidence range to count
        """
        if not self.enable_tracking:
            return {}
        
        if bins is None:
            bins = RoutingAnalyticsConfig.CONFIDENCE_BINS
        
        cursor = self.conn.cursor()
        
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute("""
            SELECT confidence
            FROM routing_decisions
            WHERE timestamp >= ? AND confidence IS NOT NULL
        """, (since,))
        
        confidences = [row[0] for row in cursor.fetchall()]
        
        if not confidences:
            return {}
        
        # Create histogram
        bin_size = 1.0 / bins
        distribution = defaultdict(int)
        
        for conf in confidences:
            bin_index = min(int(conf / bin_size), bins - 1)
            bin_range = f"{bin_index * bin_size:.1f}-{(bin_index + 1) * bin_size:.1f}"
            distribution[bin_range] += 1
        
        return dict(distribution)
    
    def export_metrics(self, output_path: str, days: int = 30):
        """
        Export metrics to JSON file for dashboards
        
        Args:
            output_path: Path to output JSON file
            days: Number of days of data to export
        """
        if not self.enable_tracking:
            logger.warning("[ANALYTICS] Cannot export - tracking disabled")
            return
        
        metrics = {
            'generated_at': datetime.now().isoformat(),
            'period_days': days,
            'overall_metrics': self.get_metrics(days=days),
            'domain_accuracy': self.get_domain_accuracy(days=days),
            'tool_usage': self.get_tool_usage(days=days),
            'confidence_distribution': self.get_confidence_distribution(days=days),
            'misrouting_patterns': self.get_misrouting_patterns(min_occurrences=2),
        }
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(metrics, f, indent=2)
        
        logger.info(f"[ANALYTICS] Exported metrics to {output_path}")
    
    def generate_report(self, days: int = 7) -> str:
        """
        Generate a text report of routing analytics
        
        Args:
            days: Number of days to include in report
            
        Returns:
            Formatted text report
        """
        if not self.enable_tracking:
            return "Analytics tracking is disabled"
        
        metrics = self.get_metrics(days=days)
        domain_accuracy = self.get_domain_accuracy(days=days)
        tool_usage = self.get_tool_usage(days=days)
        misrouting = self.get_misrouting_patterns(min_occurrences=2)
        
        report = []
        report.append("=" * 60)
        report.append(f"ROUTING ANALYTICS REPORT - Last {days} Days")
        report.append("=" * 60)
        report.append("")
        
        # Overall metrics
        report.append("OVERALL METRICS:")
        report.append(f"  Total Routings: {metrics['total_routings']}")
        report.append(f"  Accuracy: {metrics['accuracy']:.1%}")
        report.append(f"  Avg Confidence: {metrics['avg_confidence']:.2f}")
        report.append(f"  Avg Execution Time: {metrics['avg_execution_time_ms']:.1f}ms")
        report.append(f"  Parser Usage: {metrics['parser_usage_rate']:.1%}")
        report.append(f"  Validator Usage: {metrics['validator_usage_rate']:.1%}")
        report.append(f"  Cross-Domain Queries: {metrics['cross_domain_rate']:.1%}")
        report.append("")
        
        # Domain accuracy
        if domain_accuracy:
            report.append("ACCURACY BY DOMAIN:")
            for domain, accuracy in sorted(domain_accuracy.items(), key=lambda x: x[1], reverse=True):
                report.append(f"  {domain}: {accuracy:.1%}")
            report.append("")
        
        # Tool usage
        if tool_usage:
            report.append("TOOL USAGE:")
            for tool, count in sorted(tool_usage.items(), key=lambda x: x[1], reverse=True):
                percentage = count / metrics['total_routings'] * 100 if metrics['total_routings'] > 0 else 0
                report.append(f"  {tool}: {count} ({percentage:.1f}%)")
            report.append("")
        
        # Misrouting patterns
        if misrouting:
            report.append("COMMON MISROUTING PATTERNS:")
            for pattern in misrouting[:10]:  # Top 10
                report.append(f"  Pattern: '{pattern['query_pattern'][:50]}...'")
                report.append(f"    Wrong: {pattern['wrong_tool']} → Correct: {pattern['correct_tool']}")
                report.append(f"    Occurrences: {pattern['occurrences']}")
                report.append(f"    Avg Confidence: {pattern['avg_confidence']:.2f}")
                report.append("")
        
        report.append("=" * 60)
        
        return "\n".join(report)
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("[ANALYTICS] Database connection closed")
    
    def __del__(self):
        """Cleanup on deletion"""
        self.close()


# Global singleton instance with thread-safe initialization
_global_routing_analytics: Optional[RoutingAnalytics] = None
_analytics_lock = None

def _get_analytics_lock():
    """Lazy initialization of lock"""
    global _analytics_lock
    if _analytics_lock is None:
        from threading import Lock
        _analytics_lock = Lock()
    return _analytics_lock


def get_routing_analytics(db_path: Optional[str] = None) -> RoutingAnalytics:
    """
    Factory function to get or create global RoutingAnalytics instance (thread-safe singleton).
    
    This ensures a single analytics instance is shared across the orchestrator.
    
    Args:
        db_path: Optional path to analytics database
        
    Returns:
        RoutingAnalytics instance
        
    Usage:
        >>> analytics = get_routing_analytics()
        >>> analytics.record_routing(...)
    """
    global _global_routing_analytics
    
    if _global_routing_analytics is None:
        with _get_analytics_lock():
            # Double-check pattern for thread safety
            if _global_routing_analytics is None:
                _global_routing_analytics = RoutingAnalytics(db_path=db_path)
                logger.info("[ANALYTICS] Global RoutingAnalytics instance created")
    
    return _global_routing_analytics


def reset_routing_analytics() -> None:
    """
    Reset the global analytics instance (mainly for testing).
    
    WARNING: This should only be used in tests. Resetting the analytics
    in production can cause inconsistent behavior.
    """
    global _global_routing_analytics
    
    with _get_analytics_lock():
        if _global_routing_analytics:
            _global_routing_analytics.close()
        _global_routing_analytics = None
        logger.debug("[ANALYTICS] Global RoutingAnalytics instance reset")
