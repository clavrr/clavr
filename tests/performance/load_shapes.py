"""
Advanced Performance Test Scenarios
Different load patterns and test scenarios
"""
from locust import HttpUser, task, between, LoadTestShape
import math


class CacheWarmupUser(HttpUser):
    """
    User for cache warmup testing
    Tests cache hit/miss performance
    """
    wait_time = between(1, 2)
    
    # Repeat same queries to test cache hits
    fixed_queries = [
        "Show me unread emails",
        "List meetings for today",
        "Search emails from boss@company.com"
    ]
    
    @task
    def cached_query(self):
        """Repeat same query to test cache performance"""
        query = self.fixed_queries[0]  # Always use first query
        self.client.post("/chat", json={"message": query})
    
    @task
    def paginated_list_cached(self):
        """Test cached pagination"""
        self.client.get("/emails?page=1&page_size=20")


class SpikeyLoadUser(HttpUser):
    """User for spike testing"""
    wait_time = between(0.1, 0.5)
    
    @task
    def health_check(self):
        self.client.get("/health")
    
    @task
    def chat_spike(self):
        self.client.post("/chat", json={"message": "Quick test"})


class StepLoadShape(LoadTestShape):
    """
    Step load pattern: gradually increase load
    Good for finding breaking points
    """
    step_time = 30  # Seconds per step
    step_load = 10  # Users to add per step
    spawn_rate = 5
    time_limit = 300  # 5 minutes total
    
    def tick(self):
        run_time = self.get_run_time()
        
        if run_time > self.time_limit:
            return None
        
        current_step = run_time // self.step_time
        user_count = int((current_step + 1) * self.step_load)
        
        return (user_count, self.spawn_rate)


class WaveLoadShape(LoadTestShape):
    """
    Wave pattern: simulate natural traffic patterns
    Users come in waves throughout the day
    """
    time_limit = 600  # 10 minutes
    min_users = 5
    max_users = 50
    wave_period = 120  # 2 minute waves
    
    def tick(self):
        run_time = self.get_run_time()
        
        if run_time > self.time_limit:
            return None
        
        # Sine wave for natural traffic
        wave = math.sin((run_time / self.wave_period) * 2 * math.pi)
        user_count = int(self.min_users + (wave + 1) * (self.max_users - self.min_users) / 2)
        
        return (user_count, 10)


class DoubleWaveLoadShape(LoadTestShape):
    """
    Double wave: morning and afternoon traffic peaks
    Simulates real-world usage patterns
    """
    time_limit = 600
    
    def tick(self):
        run_time = self.get_run_time()
        
        if run_time > self.time_limit:
            return None
        
        # Two peaks: one early, one late
        normalized_time = (run_time % 300) / 300  # Normalize to 0-1
        
        if normalized_time < 0.25:
            # Morning ramp up
            user_count = int(10 + (normalized_time / 0.25) * 40)
        elif normalized_time < 0.5:
            # Morning peak
            user_count = 50
        elif normalized_time < 0.75:
            # Afternoon dip
            user_count = int(50 - ((normalized_time - 0.5) / 0.25) * 30)
        else:
            # Afternoon peak
            user_count = int(20 + ((normalized_time - 0.75) / 0.25) * 30)
        
        return (user_count, 10)


class SpikeLoadShape(LoadTestShape):
    """
    Spike test: sudden traffic spikes
    Tests system resilience
    """
    def tick(self):
        run_time = self.get_run_time()
        
        if run_time > 300:  # 5 minutes
            return None
        
        # Spike every 60 seconds
        if (run_time // 60) % 2 == 0:
            # Spike
            return (100, 50)
        else:
            # Normal load
            return (10, 10)
