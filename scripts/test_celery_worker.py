#!/usr/bin/env python3
"""
Comprehensive Celery Worker Test Script

This script:
1. Starts a Celery worker in the background
2. Verifies all tasks are registered
3. Tests task execution
4. Checks queues and periodic tasks
5. Cleans up

Usage:
    python scripts/test_celery_worker.py
"""

import sys
import time
import signal
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class Colors:
    HEADER = '\033[95m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(80)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")


def print_success(text):
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")


def print_error(text):
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")


def print_info(text):
    print(f"  {text}")


class CeleryTester:
    def __init__(self):
        self.worker_process = None
        self.app = None
        
    def load_app(self):
        """Load Celery app"""
        print_header("Loading Celery Application")
        try:
            from src.workers.celery_app import celery_app
            self.app = celery_app
            print_success(f"App loaded: {self.app.main}")
            print_info(f"Broker: {self.app.conf.broker_url}")
            print_info(f"Backend: {self.app.conf.result_backend}")
            return True
        except Exception as e:
            print_error(f"Failed to load app: {e}")
            return False
    
    def start_worker(self):
        """Start worker process"""
        print_header("Starting Celery Worker")
        
        try:
            # Kill existing workers
            subprocess.run(['pkill', '-f', 'celery.*worker'], 
                          stderr=subprocess.DEVNULL, check=False)
            time.sleep(2)
            
            # Start new worker
            print_info("Starting worker process...")
            self.worker_process = subprocess.Popen(
                ['celery', '-A', 'src.workers.celery_app', 'worker', 
                 '--loglevel=info', '--concurrency=2'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(project_root)
            )
            
            # Wait for startup
            print_info("Waiting for worker to start (10 seconds)...")
            time.sleep(10)
            
            # Check if still running
            if self.worker_process.poll() is not None:
                print_error("Worker terminated unexpectedly")
                return False
            
            print_success("Worker started successfully")
            return True
            
        except Exception as e:
            print_error(f"Failed to start worker: {e}")
            return False
    
    def verify_tasks(self):
        """Verify tasks are registered"""
        print_header("Verifying Registered Tasks")
        
        expected = {
            'email_tasks': 6,
            'calendar_tasks': 4,
            'indexing_tasks': 5,
            'notification_tasks': 5,
            'maintenance_tasks': 7,
        }
        
        try:
            # Try multiple times
            for attempt in range(3):
                try:
                    print_info(f"Inspecting tasks (attempt {attempt + 1}/3)...")
                    inspect = self.app.control.inspect(timeout=15)
                    registered = inspect.registered()
                    
                    if registered:
                        break
                        
                    if attempt < 2:
                        print(f"{Colors.WARNING}No response, waiting...{Colors.ENDC}")
                        time.sleep(5)
                except Exception as e:
                    if attempt < 2:
                        print(f"{Colors.WARNING}Retry {attempt + 1}: {e}{Colors.ENDC}")
                        time.sleep(5)
                    else:
                        raise
            
            if not registered:
                print_error("No workers responded")
                return False
            
            # Count tasks
            worker_name = list(registered.keys())[0]
            tasks = registered[worker_name]
            
            print_success(f"Worker: {worker_name}")
            print_success(f"Total tasks: {len(tasks)}\n")
            
            # Group by module
            by_module = {}
            for task in tasks:
                if 'src.workers.tasks.' in task:
                    module = task.split('.')[3]
                    if module not in by_module:
                        by_module[module] = []
                    by_module[module].append(task)
            
            # Check each module
            all_ok = True
            for module, expected_count in expected.items():
                actual_count = len(by_module.get(module, []))
                status = "✓" if actual_count == expected_count else "✗"
                color = Colors.OKGREEN if actual_count == expected_count else Colors.FAIL
                
                print(f"{color}{status} {module}: {actual_count}/{expected_count}{Colors.ENDC}")
                
                if actual_count != expected_count:
                    all_ok = False
                    
            return all_ok
            
        except Exception as e:
            print_error(f"Failed to verify tasks: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_execution(self):
        """Test task execution"""
        print_header("Testing Task Execution")
        
        try:
            print_info("Queueing debug_task...")
            result = self.app.send_task('src.workers.celery_app.debug_task')
            
            print_info(f"Task ID: {result.id}")
            print_info("Waiting for result...")
            
            output = result.get(timeout=15)
            print_success("Task completed!")
            print_info(f"Result: {output}")
            return True
            
        except Exception as e:
            print_error(f"Task failed: {e}")
            return False
    
    def verify_queues(self):
        """Verify queue configuration"""
        print_header("Verifying Queues")
        
        expected_queues = ['default', 'email', 'calendar', 'indexing', 'notifications', 'priority']
        
        try:
            inspect = self.app.control.inspect(timeout=10)
            active = inspect.active_queues()
            
            if not active:
                print_error("No active queues")
                return False
            
            worker = list(active.keys())[0]
            queues = [q['name'] for q in active[worker]]
            
            all_found = True
            for queue in expected_queues:
                if queue in queues:
                    print_success(queue)
                else:
                    print_error(f"{queue} - MISSING")
                    all_found = False
            
            return all_found
            
        except Exception as e:
            print_error(f"Failed to verify queues: {e}")
            return False
    
    def cleanup(self):
        """Stop worker"""
        print_header("Cleanup")
        
        try:
            if self.worker_process:
                print_info("Stopping worker...")
                self.worker_process.send_signal(signal.SIGTERM)
                
                try:
                    self.worker_process.wait(timeout=10)
                    print_success("Worker stopped")
                except subprocess.TimeoutExpired:
                    self.worker_process.kill()
                    self.worker_process.wait()
                    print_success("Worker killed")
            
            subprocess.run(['pkill', '-f', 'celery.*worker'],
                          stderr=subprocess.DEVNULL, check=False)
                          
        except Exception as e:
            print_error(f"Cleanup failed: {e}")
    
    def run(self):
        """Run all tests"""
        print_header("CELERY WORKER TEST SUITE")
        
        try:
            # Load app
            if not self.load_app():
                return False
            
            # Start worker
            if not self.start_worker():
                return False
            
            # Run tests
            tasks_ok = self.verify_tasks()
            queues_ok = self.verify_queues()
            exec_ok = self.test_execution()
            
            # Final result
            print_header("TEST RESULTS")
            
            if tasks_ok and queues_ok and exec_ok:
                print_success("ALL TESTS PASSED!")
                print()
                print_info("Your Celery setup is working correctly.")
                print_info("")
                print_info("Next steps:")
                print_info("  1. Start worker: ./scripts/start_celery_worker.sh")
                print_info("  2. Start scheduler: ./scripts/start_celery_beat.sh")
                print_info("  3. Start Flower UI: ./scripts/start_flower.sh")
                print_info("  4. Visit: http://localhost:5555")
                return True
            else:
                print_error("SOME TESTS FAILED")
                if not tasks_ok:
                    print_error("- Task registration failed")
                if not queues_ok:
                    print_error("- Queue configuration failed")
                if not exec_ok:
                    print_error("- Task execution failed")
                return False
                
        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}Interrupted by user{Colors.ENDC}")
            return False
        except Exception as e:
            print_error(f"Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.cleanup()


def main():
    tester = CeleryTester()
    success = tester.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
