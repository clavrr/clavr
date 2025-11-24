#!/usr/bin/env python3
"""
Clavr - Intelligent Email AI Agent - Main Entry Point
"""
import sys
import subprocess
import signal
import time
import click
from rich.console import Console

console = Console()

# Global variable to track Celery worker process
celery_process = None


def start_celery_worker():
    """Start Celery worker in background"""
    global celery_process
    
    console.print("[bold green]Starting Celery worker...[/bold green]")
    
    try:
        import os
        import sys
        
        # Determine virtual environment path
        # If running from venv, use sys.executable's directory
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            # Running in virtual environment
            venv_bin = os.path.dirname(sys.executable)
            celery_cmd = os.path.join(venv_bin, 'celery')
        else:
            # Try to find venv in project directory
            project_dir = os.path.dirname(os.path.abspath(__file__))
            venv_celery = os.path.join(project_dir, 'email_agent', 'bin', 'celery')
            if os.path.exists(venv_celery):
                celery_cmd = venv_celery
            else:
                # Fallback to system celery
                celery_cmd = 'celery'
        
        # Use Python from venv to ensure correct environment
        if celery_cmd != 'celery':
            # Use python -m celery to ensure we're using the right Python
            python_cmd = os.path.join(os.path.dirname(celery_cmd), 'python3')
            celery_args = [
                python_cmd,
                '-m', 'celery',
                '-A', 'src.workers.celery_app',
                'worker',
                '--loglevel=info',
                '--pool=solo'  # Use solo pool for better compatibility
            ]
        else:
            celery_args = [
                celery_cmd,
                '-A', 'src.workers.celery_app',
                'worker',
                '--loglevel=info',
                '--pool=solo'
            ]
        
        # Start Celery worker as subprocess with log file
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'celery_worker.log')
        
        # Open log file for appending
        log_fd = open(log_file, 'a')
        
        celery_process = subprocess.Popen(
            celery_args,
            stdout=log_fd,
            stderr=subprocess.STDOUT,  # Merge stderr to stdout
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))  # Set working directory
        )
        
        console.print(f"[dim]Worker logs: {log_file}[/dim]")
        
        # Give it a moment to start and check for Redis connection
        import redis
        redis_available = False
        for i in range(5):  # Try for up to 5 seconds
            try:
                r = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
                r.ping()
                redis_available = True
                break
            except Exception:
                time.sleep(1)
        
        if not redis_available:
            console.print("[bold yellow]WARNING: Redis not available. Celery may fail to connect.[/bold yellow]")
            console.print("[dim]Start Redis with: redis-server or brew services start redis[/dim]")
        
        time.sleep(2)  # Give Celery time to initialize
        
        # Check if it's still running
        if celery_process.poll() is None:
            console.print("[bold green]Celery worker started successfully[/bold green]")
            console.print("[dim]Email indexing tasks will be processed automatically[/dim]")
            return True
        else:
            # Get error output
            stdout, stderr = celery_process.communicate()
            error_msg = stderr if stderr else stdout
            console.print(f"[bold red]Celery worker failed to start[/bold red]")
            if error_msg:
                # Show last few lines of error
                error_lines = error_msg.strip().split('\n')
                console.print(f"[dim]Error (last 5 lines):[/dim]")
                for line in error_lines[-5:]:
                    if line.strip():
                        console.print(f"[dim]  {line[:150]}[/dim]")
            return False
            
    except FileNotFoundError:
        console.print("[bold red]Celery not found. Install with: pip install celery[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]Failed to start Celery: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


def stop_celery_worker():
    """Stop Celery worker gracefully"""
    global celery_process
    
    if celery_process:
        console.print("[yellow]Stopping Celery worker...[/yellow]")
        try:
            celery_process.terminate()
            celery_process.wait(timeout=5)
            console.print("[green]Celery worker stopped[/green]")
        except subprocess.TimeoutExpired:
            console.print("[yellow]Force killing Celery worker...[/yellow]")
            celery_process.kill()
        except Exception as e:
            console.print(f"[red]Error stopping Celery: {e}[/red]")


def check_port_available(port: int, host: str = '0.0.0.0'):
    """
    Check if a port is available. Returns (is_available, pid_using_port).
    If port is in use, returns (False, pid). Otherwise returns (True, 0).
    """
    import socket
    
    try:
        # Try to bind to the port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        result = sock.bind((host, port))
        sock.close()
        return (True, 0)
    except OSError:
        # Port is in use, try to find the PID
        try:
            import subprocess
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                pid = int(result.stdout.strip().split('\n')[0])
                return (False, pid)
        except Exception:
            pass
        return (False, 0)


def kill_process_on_port(port: int) -> bool:
    """Kill the process using the specified port. Returns True if successful."""
    try:
        import subprocess
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split('\n')[0]
            subprocess.run(['kill', '-9', pid], timeout=2)
            import time
            time.sleep(0.5)  # Give it a moment to die
            return True
    except Exception:
        pass
    return False


@click.command()
@click.option('--port', default=8000, help='Port to run server on')
@click.option('--host', default='0.0.0.0', help='Host to bind to')
@click.option('--reload', is_flag=True, help='Enable auto-reload')
@click.option('--no-celery', is_flag=True, help='Skip starting Celery worker')
@click.option('--kill-existing', is_flag=True, help='Kill existing process on port if in use')
def main(port: int, host: str, reload: bool, no_celery: bool, kill_existing: bool):
    """
    Email AI Agent
    
    Start the FastAPI application with all AI features
    Automatically starts Celery worker for background email indexing
    """
    import uvicorn
    
    # Check if port is available
    is_available, pid = check_port_available(port, host)
    if not is_available:
        if kill_existing:
            console.print(f"[yellow]Port {port} is in use by process {pid}. Killing it...[/yellow]")
            if kill_process_on_port(port):
                console.print(f"[green]Killed process {pid}. Starting server...[/green]")
                import time
                time.sleep(1)  # Wait a moment for port to be released
            else:
                console.print(f"[bold red]Failed to kill process {pid} on port {port}[/bold red]")
                sys.exit(1)
        else:
            console.print(f"[bold red]Port {port} is already in use by process {pid}[/bold red]")
            console.print(f"[yellow]Options:[/yellow]")
            console.print(f"  1. Kill existing process: [bold]python main.py --kill-existing[/bold]")
            console.print(f"  2. Use different port: [bold]python main.py --port 8001[/bold]")
            console.print(f"  3. Kill manually: [bold]kill -9 {pid}[/bold]")
            sys.exit(1)
    
    console.print("[bold blue]Starting Email AI Agent API[/bold blue]")
    console.print(f"Server: http://{host}:{port}")
    console.print(f"Docs: http://{host}:{port}/docs")
    console.print()
    
    # Don't override signal handlers - let uvicorn handle SIGINT/SIGTERM gracefully
    # Celery cleanup will happen in exception handlers and finally block
    # Overriding signal handlers causes issues with async cleanup in lifespan context managers
    
    # Start Celery worker unless explicitly disabled
    celery_started = False
    if not no_celery:
        celery_started = start_celery_worker()
        if not celery_started:
            console.print("[yellow]WARNING: API will start but background tasks won't process[/yellow]")
        console.print()
    else:
        console.print("[yellow]WARNING: Celery worker disabled (--no-celery flag)[/yellow]")
        console.print()
    
    console.print("[bold]Press Ctrl+C to stop[/bold]\n")
    
    try:
        # uvicorn.run() blocks until the server is stopped
        uvicorn.run(
            "api.main:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
    except KeyboardInterrupt:
        # User pressed Ctrl+C - stop Celery and exit gracefully
        console.print("\n[yellow]Server stopped by user[/yellow]")
        stop_celery_worker()
    except OSError as e:
        # Port binding error - provide helpful message
        if "address already in use" in str(e).lower() or e.errno == 48:
            console.print(f"\n[bold red]Port {port} is already in use[/bold red]")
            console.print(f"[yellow]Options:[/yellow]")
            console.print(f"  1. Kill existing process: [bold]python main.py --kill-existing[/bold]")
            console.print(f"  2. Use different port: [bold]python main.py --port 8001[/bold]")
            stop_celery_worker()
            sys.exit(1)
        else:
            raise
    except Exception as e:
        # Unexpected error - log it and cleanup
        console.print(f"\n[bold red]Server error: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        stop_celery_worker()
        sys.exit(1)
    finally:
        # Ensure Celery is stopped on any exit
        if celery_process and celery_process.poll() is None:
            stop_celery_worker()


if __name__ == "__main__":
    main()
