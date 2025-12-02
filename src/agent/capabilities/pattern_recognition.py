"""
ML-based Pattern Recognition Module

Provides machine learning-based pattern recognition and anomaly detection
for the MemoryRole to identify behavioral patterns and anomalies.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import math


class AnomalyType(str, Enum):
    """Types of anomalies detected"""
    BEHAVIOR_CHANGE = "behavior_change"
    UNUSUAL_TIMING = "unusual_timing"
    RESOURCE_SPIKE = "resource_spike"
    SUCCESS_RATE_DROP = "success_rate_drop"
    EXECUTION_SLOWDOWN = "execution_slowdown"


@dataclass
class PatternCluster:
    """A cluster of similar execution patterns"""
    cluster_id: str
    pattern_name: str  # Human-readable name
    member_count: int
    centroid: Dict[str, Any]  # Representative pattern
    confidence: float
    characteristics: Dict[str, Any] = field(default_factory=dict)
    related_users: List[int] = field(default_factory=list)


@dataclass
class DetectedAnomaly:
    """Detected anomaly in execution patterns"""
    anomaly_type: AnomalyType
    severity: str  # 'critical', 'warning', 'info'
    description: str
    affected_patterns: List[str]
    confidence: float
    suggested_action: str
    detected_at: datetime = field(default_factory=datetime.now)


class PatternRecognition:
    """
    ML-based pattern recognition and anomaly detection
    
    Provides:
    - Unsupervised clustering of execution patterns
    - Anomaly detection
    - Behavioral change detection
    - Pattern recommendations
    - Resource usage prediction
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize pattern recognition system"""
        self.config = config or {}
        
        # Pattern storage
        self.patterns: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.clusters: Dict[str, PatternCluster] = {}
        self.cluster_counter = 0
        
        # Anomaly detection
        self.anomalies: List[DetectedAnomaly] = []
        self.baseline_metrics: Dict[str, Dict[str, float]] = {}
        
        # User behavior profiles
        self.user_profiles: Dict[int, Dict[str, Any]] = {}
        self.user_history: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        
        self.stats = {
            'patterns_analyzed': 0,
            'clusters_created': 0,
            'anomalies_detected': 0,
            'predictions_made': 0,
        }
    
    async def analyze_pattern(
        self,
        pattern_signature: str,
        pattern_data: Dict[str, Any],
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Analyze a pattern and classify it
        
        Args:
            pattern_signature: Signature of the pattern
            pattern_data: Pattern data
            user_id: Optional user ID
            
        Returns:
            Analysis result with cluster assignment and insights
        """
        self.stats['patterns_analyzed'] += 1
        
        # Store pattern
        self.patterns[pattern_signature].append({
            **pattern_data,
            'timestamp': datetime.now(),
            'user_id': user_id
        })
        
        # Find or create cluster
        cluster = self._find_or_create_cluster(pattern_signature, pattern_data)
        
        # Detect anomalies
        anomalies = self._detect_anomalies_in_pattern(pattern_signature, pattern_data, user_id)
        
        # Update user profile
        if user_id:
            self._update_user_profile(user_id, pattern_signature, pattern_data)
        
        return {
            'cluster_id': cluster.cluster_id,
            'cluster_name': cluster.pattern_name,
            'cluster_confidence': cluster.confidence,
            'anomalies': [
                {
                    'type': a.anomaly_type.value,
                    'severity': a.severity,
                    'description': a.description
                }
                for a in anomalies
            ],
            'recommendations': self._generate_recommendations(pattern_signature, cluster, anomalies)
        }
    
    def _find_or_create_cluster(
        self,
        pattern_signature: str,
        pattern_data: Dict[str, Any]
    ) -> PatternCluster:
        """
        Find existing cluster or create new one using simple clustering
        
        Uses similarity-based clustering. First checks if this exact signature
        has been seen before, then falls back to similarity matching.
        """
        # Check if we've seen this exact signature before
        # If we have patterns with this signature, check if they belong to a cluster
        if pattern_signature in self.patterns and len(self.patterns[pattern_signature]) > 1:
            # Look for existing cluster that might contain this signature
            for cluster in self.clusters.values():
                # Check if this signature is already associated with this cluster
                if 'pattern_signatures' in cluster.characteristics:
                    if pattern_signature in cluster.characteristics['pattern_signatures']:
                        # Found existing cluster for this signature
                        cluster.member_count += 1
                        cluster.confidence = min(1.0, cluster.confidence + 0.05)
                        return cluster
        
        best_cluster = None
        best_similarity = 0.7  # Threshold for joining cluster
        
        # Compare with existing clusters
        for cluster in self.clusters.values():
            similarity = self._calculate_similarity(pattern_data, cluster.centroid)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_cluster = cluster
        
        if best_cluster:
            # Join existing cluster
            best_cluster.member_count += 1
            best_cluster.confidence = min(1.0, best_cluster.confidence + 0.05)
            # Track this signature in the cluster
            if 'pattern_signatures' not in best_cluster.characteristics:
                best_cluster.characteristics['pattern_signatures'] = []
            if pattern_signature not in best_cluster.characteristics['pattern_signatures']:
                best_cluster.characteristics['pattern_signatures'].append(pattern_signature)
            return best_cluster
        else:
            # Create new cluster
            self.cluster_counter += 1
            characteristics = self._extract_characteristics(pattern_data)
            # Store the pattern signature in cluster characteristics
            characteristics['pattern_signatures'] = [pattern_signature]
            cluster = PatternCluster(
                cluster_id=f"cluster_{self.cluster_counter}",
                pattern_name=self._generate_cluster_name(pattern_data),
                member_count=1,
                centroid=self._compute_centroid(pattern_data),
                confidence=0.7,
                characteristics=characteristics
            )
            
            self.clusters[cluster.cluster_id] = cluster
            self.stats['clusters_created'] += 1
            
            return cluster
    
    def _calculate_similarity(
        self,
        pattern1: Dict[str, Any],
        pattern2: Dict[str, Any]
    ) -> float:
        """
        Calculate similarity between two patterns
        
        Uses cosine similarity and feature matching
        """
        similarity = 0.0
        factors = 0
        
        # Intent similarity
        if pattern1.get('intent') == pattern2.get('intent'):
            similarity += 0.3
        factors += 0.3
        
        # Domain overlap
        domains1 = set(pattern1.get('domains', []))
        domains2 = set(pattern2.get('domains', []))
        if domains1 and domains2:
            domain_similarity = len(domains1 & domains2) / len(domains1 | domains2)
            similarity += domain_similarity * 0.3
        factors += 0.3
        
        # Execution characteristics
        duration1 = pattern1.get('execution_time_ms', 0)
        duration2 = pattern2.get('execution_time_ms', 0)
        if duration1 > 0 and duration2 > 0:
            # Calculate duration similarity (inverse of percent difference)
            percent_diff = abs(duration1 - duration2) / max(duration1, duration2)
            duration_sim = 1 - min(percent_diff, 1.0)
            similarity += duration_sim * 0.2
        factors += 0.2
        
        # Success rate
        success1 = pattern1.get('success', False)
        success2 = pattern2.get('success', False)
        if success1 == success2:
            similarity += 0.2
        factors += 0.2
        
        return min(1.0, similarity / factors) if factors > 0 else 0.0
    
    def _compute_centroid(self, pattern: Dict[str, Any]) -> Dict[str, Any]:
        """Compute cluster centroid from pattern"""
        return {
            'intent': pattern.get('intent'),
            'domains': pattern.get('domains', []),
            'avg_duration_ms': pattern.get('execution_time_ms', 0),
            'success_rate': 1.0 if pattern.get('success') else 0.0,
            'complexity': pattern.get('complexity', 0.5)
        }
    
    def _extract_characteristics(self, pattern: Dict[str, Any]) -> Dict[str, Any]:
        """Extract human-readable characteristics from pattern"""
        return {
            'is_multi_domain': len(pattern.get('domains', [])) > 1,
            'is_complex': pattern.get('complexity', 0.5) > 0.6,
            'is_time_sensitive': pattern.get('execution_time_ms', 1000) > 1000,
            'success_count': 1 if pattern.get('success') else 0
        }
    
    def _generate_cluster_name(self, pattern: Dict[str, Any]) -> str:
        """Generate human-readable name for cluster"""
        intent = pattern.get('intent', 'query')
        domains = pattern.get('domains', [])
        
        if len(domains) > 1:
            domain_str = 'multi-domain'
        elif domains:
            domain_str = domains[0]
        else:
            domain_str = 'general'
        
        return f"{intent.capitalize()} {domain_str}".strip()
    
    def _detect_anomalies_in_pattern(
        self,
        pattern_signature: str,
        pattern_data: Dict[str, Any],
        user_id: Optional[int] = None
    ) -> List[DetectedAnomaly]:
        """Detect anomalies in pattern"""
        anomalies: List[DetectedAnomaly] = []
        
        # Initialize baseline if needed
        if pattern_signature not in self.baseline_metrics:
            self.baseline_metrics[pattern_signature] = {
                'avg_duration': pattern_data.get('execution_time_ms', 0),
                'success_rate': 1.0 if pattern_data.get('success') else 0.0,
                'min_duration': pattern_data.get('execution_time_ms', 0),
                'max_duration': pattern_data.get('execution_time_ms', 0),
            }
        
        baseline = self.baseline_metrics[pattern_signature]
        current_duration = pattern_data.get('execution_time_ms', 0)
        current_success = pattern_data.get('success', False)
        
        # Detect execution slowdown
        if current_duration > baseline['avg_duration'] * 1.5:
            anomaly = DetectedAnomaly(
                anomaly_type=AnomalyType.EXECUTION_SLOWDOWN,
                severity='warning',
                description=f"Execution time {current_duration}ms is 50% slower than baseline {baseline['avg_duration']}ms",
                affected_patterns=[pattern_signature],
                confidence=0.8,
                suggested_action='Consider checking resource availability or API rate limits'
            )
            anomalies.append(anomaly)
        
        # Detect success rate drop
        if not current_success and baseline['success_rate'] > 0.8:
            anomaly = DetectedAnomaly(
                anomaly_type=AnomalyType.SUCCESS_RATE_DROP,
                severity='warning',
                description="Execution failed when historically successful",
                affected_patterns=[pattern_signature],
                confidence=0.75,
                suggested_action='Investigate failure reason and check dependencies'
            )
            anomalies.append(anomaly)
        
        # Update baseline with new data
        baseline['avg_duration'] = baseline['avg_duration'] * 0.8 + current_duration * 0.2
        baseline['success_rate'] = baseline['success_rate'] * 0.9 + (1.0 if current_success else 0.0) * 0.1
        baseline['min_duration'] = min(baseline['min_duration'], current_duration)
        baseline['max_duration'] = max(baseline['max_duration'], current_duration)
        
        # Detect user behavior changes
        if user_id:
            behavior_anomalies = self._detect_behavior_change(user_id, pattern_signature, pattern_data)
            anomalies.extend(behavior_anomalies)
        
        # Store anomalies
        self.anomalies.extend(anomalies)
        self.stats['anomalies_detected'] += len(anomalies)
        
        return anomalies
    
    def _detect_behavior_change(
        self,
        user_id: int,
        pattern_signature: str,
        pattern_data: Dict[str, Any]
    ) -> List[DetectedAnomaly]:
        """Detect changes in user behavior"""
        anomalies: List[DetectedAnomaly] = []
        
        # Store history
        self.user_history[user_id].append({
            'pattern': pattern_signature,
            'data': pattern_data,
            'timestamp': datetime.now()
        })
        
        # Keep only last 100 entries
        if len(self.user_history[user_id]) > 100:
            self.user_history[user_id] = self.user_history[user_id][-100:]
        
        # Detect timing anomalies
        if len(self.user_history[user_id]) > 10:
            recent_times = [
                h['timestamp'] for h in self.user_history[user_id][-10:]
            ]
            
            # Check for unusual activity time
            hour = datetime.now().hour
            typical_hours = set(h['timestamp'].hour for h in self.user_history[user_id][:-1])
            
            if len(typical_hours) > 0 and hour not in typical_hours:
                anomaly = DetectedAnomaly(
                    anomaly_type=AnomalyType.UNUSUAL_TIMING,
                    severity='info',
                    description=f"Unusual activity at hour {hour} for this user",
                    affected_patterns=[pattern_signature],
                    confidence=0.6,
                    suggested_action='Monitor for potential security concerns'
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _update_user_profile(
        self,
        user_id: int,
        pattern_signature: str,
        pattern_data: Dict[str, Any]
    ) -> None:
        """Update user profile based on pattern"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                'pattern_preferences': defaultdict(int),
                'total_patterns': 0,
                'success_rate': 0.0,
                'avg_execution_time': 0.0,
                'created_at': datetime.now(),
                'last_updated': datetime.now()
            }
        
        profile = self.user_profiles[user_id]
        profile['pattern_preferences'][pattern_signature] += 1
        profile['total_patterns'] += 1
        profile['success_rate'] = (
            profile['success_rate'] * 0.9 +
            (1.0 if pattern_data.get('success') else 0.0) * 0.1
        )
        profile['avg_execution_time'] = (
            profile['avg_execution_time'] * 0.9 +
            pattern_data.get('execution_time_ms', 0) * 0.1
        )
        profile['last_updated'] = datetime.now()
    
    def _generate_recommendations(
        self,
        pattern_signature: str,
        cluster: PatternCluster,
        anomalies: List[DetectedAnomaly]
    ) -> List[str]:
        """Generate recommendations based on pattern analysis"""
        recommendations = []
        
        # Pattern-specific recommendations based on frequency
        pattern_count = len(self.patterns.get(pattern_signature, []))
        if pattern_count > 5:
            recommendations.append(f"Pattern '{pattern_signature[:50]}...' has been observed {pattern_count} times - consider optimization")
        elif pattern_count == 1:
            recommendations.append(f"New pattern detected: '{pattern_signature[:50]}...' - monitoring for trends")
        
        # Cluster-based recommendations
        if cluster.member_count > 10:
            recommendations.append(f"This is a common pattern ({cluster.member_count} similar cases)")
        
        if cluster.confidence < 0.5:
            recommendations.append("Low confidence cluster - continue monitoring")
        
        # Anomaly-based recommendations
        for anomaly in anomalies:
            if anomaly.severity == 'critical':
                recommendations.append(f"CRITICAL: {anomaly.suggested_action}")
            elif anomaly.severity == 'warning':
                recommendations.append(anomaly.suggested_action)
        
        # Pattern characteristics
        if cluster.characteristics.get('is_multi_domain'):
            recommendations.append("Consider parallelizing multi-domain operations")
        
        if cluster.characteristics.get('is_time_sensitive'):
            recommendations.append("This is a time-sensitive pattern - prioritize accordingly")
        
        return recommendations
    
    async def predict_pattern_occurrence(
        self,
        user_id: int,
        lookback_hours: int = 24
    ) -> List[Tuple[str, float]]:
        """
        Predict likely patterns for a user in near future
        
        Args:
            user_id: User ID
            lookback_hours: Hours to look back for trend analysis
            
        Returns:
            List of (pattern_signature, probability) tuples
        """
        self.stats['predictions_made'] += 1
        
        if user_id not in self.user_profiles:
            return []
        
        # Calculate cutoff time based on lookback_hours
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
        
        # Count pattern frequencies from recent history within lookback window
        pattern_counts: Dict[str, int] = defaultdict(int)
        total_recent = 0
        
        # Filter user history by lookback_hours
        if user_id in self.user_history:
            for entry in self.user_history[user_id]:
                entry_time = entry.get('timestamp')
                if isinstance(entry_time, datetime) and entry_time >= cutoff_time:
                    pattern_sig = entry.get('pattern')
                    if pattern_sig:
                        pattern_counts[pattern_sig] += 1
                        total_recent += 1
        
        # Calculate probabilities
        pattern_probs = []
        
        # If no recent patterns found, fall back to user profile
        if total_recent == 0:
            profile = self.user_profiles[user_id]
            total = profile['total_patterns']
            
            for pattern_sig, count in profile['pattern_preferences'].items():
                probability = count / total if total > 0 else 0
                pattern_probs.append((pattern_sig, probability))
        else:
            # Calculate probabilities from recent patterns
            for pattern_sig, count in pattern_counts.items():
                probability = count / total_recent if total_recent > 0 else 0
                pattern_probs.append((pattern_sig, probability))
        
        # Sort by probability
        return sorted(pattern_probs, key=lambda x: x[1], reverse=True)[:5]
    
    def get_cluster_stats(self) -> Dict[str, Any]:
        """Get clustering statistics"""
        return {
            'total_clusters': len(self.clusters),
            'avg_cluster_size': sum(c.member_count for c in self.clusters.values()) / len(self.clusters) if self.clusters else 0,
            'highest_confidence_cluster': max(
                (c.confidence for c in self.clusters.values()),
                default=0
            )
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pattern recognition statistics"""
        return {
            'patterns_analyzed': self.stats['patterns_analyzed'],
            'clusters_created': self.stats['clusters_created'],
            'anomalies_detected': self.stats['anomalies_detected'],
            'predictions_made': self.stats['predictions_made'],
            'users_profiled': len(self.user_profiles),
            'cluster_stats': self.get_cluster_stats()
        }
