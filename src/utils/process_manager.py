"""
Process Manager
Helper class to manage background processes like Celery Workers and Beat.
"""
import subprocess
import time
import os
import sys
from typing import Optional, Tuple
from rich.console import Console
from src.utils.urls import URLs

console = Console()

class ProcessManager:
    """Manages Celery and other background processes."""
    
    _celery_process: Optional[subprocess.Popen] = None
    _beat_process: Optional[subprocess.Popen] = None
    
    @classmethod
    def get_celery_command(cls) -> Tuple[str, list]:
        """Determine correct celery command and arguments."""
        # Determine virtual environment path
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            # Running in virtual environment
            venv_bin = os.path.dirname(sys.executable)
            celery_cmd = os.path.join(venv_bin, 'celery')
        else:
            # Try to find venv in project directory
            project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            venv_celery = os.path.join(project_dir, 'email_agent', 'bin', 'celery')
            if os.path.exists(venv_celery):
                celery_cmd = venv_celery
            else:
                # Fallback to system celery
                celery_cmd = 'celery'
                
        return celery_cmd

    @classmethod
    def start_celery_worker(cls) -> bool:
        """Start Celery worker in background"""
        console.print("[bold green]Starting Celery worker...[/bold green]")
        
        try:
            celery_cmd = cls.get_celery_command()
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            # Use Python from venv to ensure correct environment
            if celery_cmd != 'celery':
                python_cmd = os.path.join(os.path.dirname(celery_cmd), 'python3')
                celery_args = [
                    python_cmd, '-m', 'celery',
                    '-A', 'src.workers.celery_app',
                    'worker', '--loglevel=info', '--pool=solo'
                ]
            else:
                celery_args = [
                    celery_cmd, '-A', 'src.workers.celery_app',
                    'worker', '--loglevel=info', '--pool=solo'
                ]
            
            # Start Celery worker as subprocess with log file
            log_dir = os.path.join(project_root, 'logs')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, 'celery_worker.log')
            log_fd = open(log_file, 'a')
            
            cls._celery_process = subprocess.Popen(
                celery_args,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=project_root
            )
            
            console.print(f"[dim]Worker logs: {log_file}[/dim]")
            
            # Check Redis
            if not cls._check_redis():
                console.print("[bold yellow]WARNING: Redis not available. Celery may fail to connect.[/bold yellow]")
            
            time.sleep(2)
            
            if cls._celery_process.poll() is None:
                console.print("[bold green]Celery worker started successfully[/bold green]")
                return True
            else:
                _, stderr = cls._celery_process.communicate()
                console.print(f"[bold red]Celery worker failed to start: {stderr}[/bold red]")
                return False
                
        except Exception as e:
            console.print(f"[bold red]Failed to start Celery: {e}[/bold red]")
            return False

    @classmethod
    def start_celery_beat(cls) -> bool:
        """Start Celery Beat scheduler"""
        console.print("[bold green]Starting Celery Beat scheduler...[/bold green]")
        
        try:
            celery_cmd = cls.get_celery_command()
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            if celery_cmd != 'celery':
                python_cmd = os.path.join(os.path.dirname(celery_cmd), 'python3')
                beat_args = [
                    python_cmd, '-m', 'celery',
                    '-A', 'src.workers.celery_app',
                    'beat', '--loglevel=info', 
                    '--scheduler=celery.beat:PersistentScheduler'
                ]
            else:
                beat_args = [
                    celery_cmd, '-A', 'src.workers.celery_app',
                    'beat', '--loglevel=info',
                    '--scheduler=celery.beat:PersistentScheduler'
                ]
            
            log_file = os.path.join(project_root, 'logs', 'celery_beat.log')
            log_fd = open(log_file, 'a')
            
            cls._beat_process = subprocess.Popen(
                beat_args,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=project_root
            )
            
            console.print(f"[dim]Beat logs: {log_file}[/dim]")
            time.sleep(2)
            
            if cls._beat_process.poll() is None:
                console.print("[bold green]Celery Beat started successfully[/bold green]")
                return True
            else:
                console.print("[bold red]Celery Beat failed to start[/bold red]")
                return False
                
        except Exception as e:
            console.print(f"[bold red]Failed to start Celery Beat: {e}[/bold red]")
            return False

    @classmethod
    def stop_all(cls):
        """Stop all managed processes."""
        if cls._beat_process:
            console.print("[yellow]Stopping Celery Beat...[/yellow]")
            cls._beat_process.terminate()
            cls._beat_process = None
            
        if cls._celery_process:
            console.print("[yellow]Stopping Celery worker...[/yellow]")
            cls._celery_process.terminate()
            cls._celery_process = None

    @staticmethod
    def _check_redis() -> bool:
        """Check if Redis is available."""
        import redis
        for _ in range(5):
            try:
                r = redis.Redis(
                    host=URLs.get_redis_host(), 
                    port=URLs.get_redis_port(), 
                    db=0, socket_connect_timeout=1
                )
                r.ping()
                return True
            except Exception:
                time.sleep(1)
        return False
