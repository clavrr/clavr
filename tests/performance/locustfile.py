"""
Performance and Load Testing with Locust
Tests API endpoints under various load conditions
"""
import json
import random
from locust import HttpUser, task, between, events
from locust.contrib.fasthttp import FastHttpUser

# Test data
TEST_USERS = ["test1@example.com", "test2@example.com", "test3@example.com"]
TEST_QUERIES = [
    "Show me my unread emails",
    "List my meetings for tomorrow",
    "Search for emails from john@example.com",
    "What's on my calendar this week?",
    "Find emails about project updates",
    "Show me recent emails",
    "List all my tasks",
    "Search calendar for client meetings"
]

class EmailAgentUser(FastHttpUser):
    """
    Simulated user for email agent API
    Uses FastHttpUser for better performance
    """
    # Wait between 1-3 seconds between tasks
    wait_time = between(1, 3)
    
    # Test credentials
    auth_token = None
    user_email = None
    
    def on_start(self):
        """Called when a simulated user starts"""
        self.user_email = random.choice(TEST_USERS)
        # Login and get token (if authentication is required)
        # self.login()
    
    def login(self):
        """Authenticate user and get token"""
        response = self.client.post("/auth/login", json={
            "email": self.user_email,
            "password": "testpassword"
        })
        if response.status_code == 200:
            data = response.json()
            self.auth_token = data.get("access_token")
    
    def get_headers(self):
        """Get headers with auth token"""
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers
    
    @task(3)
    def health_check(self):
        """Test health endpoint (high frequency)"""
        self.client.get("/health")
    
    @task(5)
    def chat_query(self):
        """Test chat endpoint with various queries"""
        query = random.choice(TEST_QUERIES)
        self.client.post(
            "/chat",
            json={"message": query},
            headers=self.get_headers(),
            name="/chat [query]"
        )
    
    @task(2)
    def list_emails_page1(self):
        """Test email listing with pagination - page 1"""
        self.client.get(
            "/emails?page=1&page_size=20",
            headers=self.get_headers(),
            name="/emails [page 1]"
        )
    
    @task(1)
    def list_emails_page2(self):
        """Test email listing with pagination - page 2"""
        self.client.get(
            "/emails?page=2&page_size=20",
            headers=self.get_headers(),
            name="/emails [page 2]"
        )
    
    @task(2)
    def search_emails(self):
        """Test email search"""
        self.client.get(
            "/emails/search?q=meeting&page=1&page_size=10",
            headers=self.get_headers(),
            name="/emails/search"
        )
    
    @task(2)
    def list_calendar(self):
        """Test calendar listing"""
        self.client.get(
            "/calendar/events?page=1&page_size=20",
            headers=self.get_headers(),
            name="/calendar/events"
        )
    
    @task(1)
    def get_user_profile(self):
        """Test user profile endpoint"""
        self.client.get(
            "/users/me",
            headers=self.get_headers()
        )


class AdminUser(FastHttpUser):
    """Admin user for testing admin endpoints"""
    wait_time = between(2, 5)
    
    @task
    def admin_stats(self):
        """Test admin statistics endpoint"""
        self.client.get("/admin/statistics")


class StressTestUser(HttpUser):
    """
    User for stress testing with higher load
    Uses standard HttpUser for connection reuse
    """
    wait_time = between(0.5, 1.5)
    
    @task(10)
    def rapid_health_checks(self):
        """Rapid health check requests"""
        self.client.get("/health")
    
    @task(3)
    def rapid_chat(self):
        """Rapid chat requests"""
        query = random.choice(TEST_QUERIES)
        self.client.post("/chat", json={"message": query})


# Event handlers for custom metrics
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts"""
    print("🚀 Starting performance tests...")
    print(f"Target host: {environment.host}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops"""
    print("\n📊 Performance test completed!")
    print(f"Total requests: {environment.stats.num_requests}")
    print(f"Failed requests: {environment.stats.num_failures}")
    
    if environment.stats.total.fail_ratio > 0.1:
        print("⚠️  Warning: Failure rate > 10%")


# Custom metrics
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Track custom metrics for each request"""
    if response_time > 2000:  # 2 seconds
        print(f"⚠️  Slow request: {name} took {response_time}ms")
