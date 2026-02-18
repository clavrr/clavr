#!/usr/bin/env python3
"""
Clavr - Intelligent Email AI Agent - Main Entry Point
"""
import sys
import signal
import click
from rich.console import Console
from src.utils.process_manager import ProcessManager

console = Console()


from src.utils.system import check_port_available, kill_process_on_port
from dotenv import load_dotenv

# Load environment variables (CRITICAL for encryption keys)
load_dotenv()


@click.command()
@click.option('--port', default=8000, help='Port to run server on')
@click.option('--host', default='0.0.0.0', help='Host to bind to (use 0.0.0.0 for network access)')
@click.option('--reload', is_flag=True, help='Enable auto-reload')
@click.option('--no-celery', is_flag=True, help='Skip starting Celery worker')
@click.option('--no-beat', is_flag=True, help='Skip starting Celery Beat scheduler')
@click.option('--kill-existing', is_flag=True, help='Kill existing process on port if in use')
def main(port: int, host: str, reload: bool, no_celery: bool, no_beat: bool, kill_existing: bool):
    """
    Email AI Agent
    
    Start the FastAPI application with all AI features
    Automatically starts Celery worker and Beat for background email indexing
    """
    import uvicorn
    import os
    
    # Set Google Cloud credentials if not already set
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        project_dir = os.path.dirname(os.path.abspath(__file__))
        creds_dir = os.path.join(project_dir, "credentials")
        
        # Look for service account JSON files
        if os.path.exists(creds_dir):
            # Prioritize service account files over others (heuristic: often start with 'gen-' or 'service-')
            json_files = [f for f in os.listdir(creds_dir) if f.endswith('.json') and not f.startswith('token') and not f.startswith('client_secret')]
            
            if json_files:
                # Pick the first service account type file found
                creds_path = os.path.join(creds_dir, json_files[0])
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
                console.print(f"[dim]Set GOOGLE_APPLICATION_CREDENTIALS to: {creds_path}[/dim]")
            else:
                 console.print("[dim]No service account credentials found in credentials/ dir[/dim]")
    
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
    
    # Start Celery worker unless explicitly disabled
    celery_started = False
    
    if not no_celery:
        celery_started = ProcessManager.start_celery_worker()
        if not celery_started:
            console.print("[yellow]WARNING: API will start but background tasks won't process[/yellow]")
        console.print()
        
        # Start Celery Beat unless explicitly disabled
        if not no_beat and celery_started:
            if not ProcessManager.start_celery_beat():
                console.print("[yellow]WARNING: Periodic tasks (email sync) won't run automatically[/yellow]")
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
        console.print("\n[yellow]Server stopped by user[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Server error: {e}[/bold red]")
    finally:
        # Cleanup ALL background processes
        ProcessManager.stop_all()




if __name__ == "__main__":
    main()