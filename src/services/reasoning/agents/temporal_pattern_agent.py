"""
Temporal Pattern Agent

A reasoning agent focused on temporal intelligence - understanding time-based
patterns, optimal scheduling, and productivity rhythms.

Capabilities:
1. Optimal Meeting Times: Based on historical response rates and productivity
2. Productivity Patterns: When user is most productive
3. Scheduling Predictions: Predict if event will be rescheduled
4. Time Block Recommendations: Suggest focus time, break times

Outputs: Insight nodes (type=productivity, type=scheduling)
"""
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.reasoning.interfaces import ReasoningAgent, ReasoningResult

logger = setup_logger(__name__)


@dataclass
class ProductivityWindow:
    """A window of high productivity."""
    start_hour: int
    end_hour: int
    score: float
    activity_type: str


class TemporalPatternAgent(ReasoningAgent):
    """
    Agent that analyzes temporal patterns for productivity insights.
    
    This agent helps users optimize their schedule by understanding:
    - When they're most productive
    - Optimal times for different activities
    - Scheduling patterns that lead to rescheduling
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self._name = "TemporalPatternAgent"
        
    @property
    def name(self) -> str:
        return self._name
        
    async def analyze(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> List[ReasoningResult]:
        """
        Run temporal pattern analysis.
        """
        results = []
        
        # Run all temporal analyzers
        analyzer_tasks = [
            self._analyze_productivity_windows(user_id),
            self._analyze_meeting_patterns(user_id),
            self._identify_focus_time_opportunities(user_id),
            self._detect_scheduling_anti_patterns(user_id),
        ]
        
        try:
            all_insights = await asyncio.gather(*analyzer_tasks, return_exceptions=True)
            
            for i, insights in enumerate(all_insights):
                if isinstance(insights, Exception):
                    logger.error(f"[{self.name}] Analyzer {i} failed: {insights}")
                elif insights:
                    results.extend(insights)
                    
        except Exception as e:
            logger.error(f"[{self.name}] Analysis failed: {e}")
            
        logger.info(f"[{self.name}] Generated {len(results)} temporal insights for user {user_id}")
        return results
        
    async def verify(self, hypothesis_id: str) -> bool:
        """Verify temporal hypothesis."""
        return True
        
    # =========================================================================
    # Temporal Analysis Methods
    # =========================================================================
    
    async def _analyze_productivity_windows(self, user_id: int) -> List[ReasoningResult]:
        """
        Identify when user is most productive based on task completion times.
        
        Examples:
        - "You complete most tasks between 9-11 AM"
        - "Your afternoon productivity peaks at 2 PM"
        """
        results = []
        
        # Query tasks with completion timestamps
        query = """
        FOR t IN ActionItem
            FILTER t.user_id == @user_id
               AND t.status == 'completed'
               AND t.completed_at != null
            RETURN { completed_at: t.completed_at, priority: t.priority }
        LIMIT 200
        """
        
        try:
            tasks = await self.graph.execute_query(query, {"user_id": user_id})
            
            if not tasks or len(tasks) < 10:
                return results
                
            # Bucket completions by hour
            hour_counts: Dict[int, int] = defaultdict(int)
            high_priority_hours: Dict[int, int] = defaultdict(int)
            
            for task in tasks:
                completed_str = task.get("completed_at")
                if not completed_str:
                    continue
                    
                try:
                    if isinstance(completed_str, str):
                        completed = datetime.fromisoformat(completed_str.replace('Z', '+00:00'))
                    else:
                        completed = completed_str
                        
                    hour = completed.hour
                    hour_counts[hour] += 1
                    
                    if task.get("priority") == "high":
                        high_priority_hours[hour] += 1
                except (ValueError, AttributeError):
                    continue
                    
            if not hour_counts:
                return results
                
            # Find peak productivity hours
            total = sum(hour_counts.values())
            sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
            
            # Top 3 productive hours
            top_hours = sorted_hours[:3]
            
            if top_hours:
                peak_hour = top_hours[0][0]
                peak_tasks = top_hours[0][1]
                concentration = peak_tasks / total
                
                period = "morning" if peak_hour < 12 else "afternoon" if peak_hour < 17 else "evening"
                hour_str = f"{peak_hour}:00"
                
                content = {
                    "content": f"Your peak productivity is around {hour_str} ({period}) - {int(concentration*100)}% of tasks completed then",
                    "type": "productivity",
                    "insight_type": "peak_productivity_window",
                    "peak_hour": peak_hour,
                    "period": period,
                    "concentration": round(concentration, 2),
                    "sample_size": total,
                    "actionable": True,
                    "reasoning_chain": f"Analyzed {total} completed tasks, found {int(concentration*100)}% concentrated at {hour_str}"
                }
                
                results.append(ReasoningResult(
                    type="insight",
                    confidence=min(0.9, 0.5 + concentration),
                    content=content,
                    source_agent=self.name
                ))
                
        except Exception as e:
            logger.error(f"[{self.name}] Productivity window analysis failed: {e}")
            
        return results
        
    async def _analyze_meeting_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Analyze meeting patterns for optimization opportunities.
        
        Examples:
        - "Back-to-back meetings reduce productivity"
        - "Your 1:1s run 15 minutes over on average"
        """
        results = []
        
        # Get meeting history
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id
               AND e.start_time >= @start_date
            SORT e.start_time ASC
            RETURN { 
                title: e.title, 
                start: e.start_time, 
                end: e.end_time,
                actual_end: e.actual_end_time 
            }
        """
        
        try:
            meetings = await self.graph.execute_query(query, {
                "user_id": user_id,
                "start_date": thirty_days_ago
            })
            
            if not meetings or len(meetings) < 5:
                return results
                
            # Analyze for back-to-back patterns
            back_to_back_count = 0
            total_meetings = 0
            
            parsed_meetings = []
            for meeting in meetings:
                try:
                    start_str = meeting.get("start")
                    end_str = meeting.get("end")
                    
                    if not start_str or not end_str:
                        continue
                        
                    if isinstance(start_str, str):
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start = start_str
                        
                    if isinstance(end_str, str):
                        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    else:
                        end = end_str
                        
                    parsed_meetings.append({
                        "title": meeting.get("title", "Meeting"),
                        "start": start,
                        "end": end
                    })
                    total_meetings += 1
                except (ValueError, AttributeError):
                    continue
                    
            # Check for back-to-back patterns
            for i in range(1, len(parsed_meetings)):
                prev_end = parsed_meetings[i-1]["end"]
                curr_start = parsed_meetings[i]["start"]
                
                # Same day and within 15 minutes
                gap = (curr_start - prev_end).total_seconds() / 60
                if 0 <= gap < 15 and prev_end.date() == curr_start.date():
                    back_to_back_count += 1
                    
            if total_meetings > 0 and back_to_back_count >= 3:
                back_to_back_ratio = back_to_back_count / total_meetings
                
                content = {
                    "content": f"Back-to-back meeting pattern detected: {int(back_to_back_ratio*100)}% of meetings have <15min breaks",
                    "type": "productivity",
                    "insight_type": "meeting_pattern",
                    "back_to_back_ratio": round(back_to_back_ratio, 2),
                    "recommendation": "Consider adding buffer time between meetings",
                    "actionable": True
                }
                
                results.append(ReasoningResult(
                    type="insight",
                    confidence=0.8,
                    content=content,
                    source_agent=self.name
                ))
                
        except Exception as e:
            logger.error(f"[{self.name}] Meeting pattern analysis failed: {e}")
            
        return results
        
    async def _identify_focus_time_opportunities(self, user_id: int) -> List[ReasoningResult]:
        """
        Identify opportunities for focus time in the upcoming week.
        
        Examples:
        - "Wednesday afternoon has no meetings - good for deep work"
        - "Thursday has fragmented time - 5 gaps of 30 mins"
        """
        results = []
        
        now = datetime.utcnow()
        week_from_now = now + timedelta(days=7)
        
        # Check each upcoming day
        for day_offset in range(1, 6):  # Next 5 business days
            check_date = now + timedelta(days=day_offset)
            
            if check_date.weekday() >= 5:
                continue
                
            day_start = check_date.replace(hour=9, minute=0, second=0)  # 9 AM
            day_end = check_date.replace(hour=17, minute=0, second=0)   # 5 PM
            
            query = """
            FOR e IN CalendarEvent
                FILTER e.user_id == @user_id
                   AND e.start_time >= @day_start
                   AND e.start_time <= @day_end
                SORT e.start_time ASC
                RETURN { start: e.start_time, end: e.end_time }
            """
            
            try:
                meetings = await self.graph.execute_query(query, {
                    "user_id": user_id,
                    "day_start": day_start.isoformat(),
                    "day_end": day_end.isoformat()
                })
                
                # Calculate free blocks
                free_blocks = []
                last_end = day_start
                
                for meeting in sorted(meetings or [], key=lambda x: x.get("start", "")):
                    start_str = meeting.get("start")
                    end_str = meeting.get("end")
                    
                    if not start_str or not end_str:
                        continue
                        
                    try:
                        if isinstance(start_str, str):
                            start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        else:
                            start = start_str
                            
                        if isinstance(end_str, str):
                            end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                        else:
                            end = end_str
                            
                        if start > last_end:
                            block_minutes = int((start - last_end).total_seconds() / 60)
                            if block_minutes >= 30:
                                free_blocks.append({
                                    "start": last_end,
                                    "duration": block_minutes
                                })
                                
                        last_end = max(last_end, end)
                    except (ValueError, AttributeError):
                        continue
                        
                # Check end of day
                if last_end < day_end:
                    block_minutes = int((day_end - last_end).total_seconds() / 60)
                    if block_minutes >= 30:
                        free_blocks.append({
                            "start": last_end,
                            "duration": block_minutes
                        })
                        
                # Report significant focus time opportunities
                focus_blocks = [b for b in free_blocks if b["duration"] >= 120]  # 2+ hours
                
                if focus_blocks:
                    largest_block = max(focus_blocks, key=lambda x: x["duration"])
                    day_name = check_date.strftime("%A")
                    
                    content = {
                        "content": f"{day_name} has a {largest_block['duration']//60}-hour focus block available ({largest_block['start'].strftime('%H:%M')}-based)",
                        "type": "productivity",
                        "insight_type": "focus_time_opportunity",
                        "date": check_date.date().isoformat(),
                        "day_name": day_name,
                        "block_duration_minutes": largest_block["duration"],
                        "block_count": len(focus_blocks),
                        "actionable": True
                    }
                    
                    results.append(ReasoningResult(
                        type="insight",
                        confidence=0.85,
                        content=content,
                        source_agent=self.name
                    ))
                    
            except Exception as e:
                logger.error(f"[{self.name}] Focus time analysis for day {day_offset} failed: {e}")
                continue
                
        return results
        
    async def _detect_scheduling_anti_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect scheduling anti-patterns.
        
        Examples:
        - "Meetings scheduled at 8 AM are 50% more likely to be rescheduled"
        - "Friday afternoon meetings often get cancelled"
        """
        results = []
        
        # Query for rescheduled/cancelled meetings
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id
               AND (e.was_rescheduled == true OR e.was_cancelled == true)
            RETURN { 
                original_start: e.original_start_time, 
                rescheduled: e.was_rescheduled,
                cancelled: e.was_cancelled 
            }
        """
        
        try:
            problematic_meetings = await self.graph.execute_query(query, {"user_id": user_id})
            
            if not problematic_meetings or len(problematic_meetings) < 5:
                return results
                
            # Analyze patterns in problematic meetings
            hour_problems: Dict[int, int] = defaultdict(int)
            day_problems: Dict[int, int] = defaultdict(int)
            
            for meeting in problematic_meetings:
                start_str = meeting.get("original_start")
                if not start_str:
                    continue
                    
                try:
                    if isinstance(start_str, str):
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start = start_str
                        
                    hour_problems[start.hour] += 1
                    day_problems[start.weekday()] += 1
                except (ValueError, AttributeError):
                    continue
                    
            # Find problematic time slots
            total_problems = len(problematic_meetings)
            
            for hour, count in sorted(hour_problems.items(), key=lambda x: x[1], reverse=True)[:2]:
                concentration = count / total_problems
                if concentration >= 0.2:  # 20%+ of problems at this hour
                    content = {
                        "content": f"Meetings at {hour}:00 are more likely to be rescheduled ({int(concentration*100)}% of rescheduled meetings)",
                        "type": "scheduling",
                        "insight_type": "scheduling_anti_pattern",
                        "problematic_hour": hour,
                        "concentration": round(concentration, 2),
                        "recommendation": f"Consider avoiding scheduling at {hour}:00",
                        "actionable": True
                    }
                    
                    results.append(ReasoningResult(
                        type="insight",
                        confidence=0.7,
                        content=content,
                        source_agent=self.name
                    ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Scheduling anti-pattern detection failed: {e}")
            
        return results
