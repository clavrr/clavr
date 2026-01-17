#!/usr/bin/env python3
"""
Clavr CLI

Command-line interface for developers who live in the terminal.

The "Invisible UI" - Clavr meets you where you work.

Usage:
    clavr brief          # Get morning briefing
    clavr todo           # List todos/action items
    clavr ask "query"    # Ask Clavr anything
    clavr search "term"  # Semantic search across all sources
    clavr inserts        # View proactive insights
"""
import os
import sys
import argparse
import asyncio
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich import print as rprint

console = Console()


def setup_environment():
    """Setup environment for CLI usage."""
    # Load env if available
    from dotenv import load_dotenv
    load_dotenv()


async def cmd_brief(args):
    """Get morning briefing."""
    console.print(Panel.fit(
        "[bold blue]Clavr Morning Brief[/]",
        subtitle=datetime.now().strftime("%A, %B %d, %Y")
    ))
    
    try:
        from src.utils.config import load_config
        from api.dependencies import AppState
        
        config = load_config()
        brief_service = AppState.get_brief_service(user_id=1)
        
        with console.status("[bold blue]Fetching briefing...", spinner="dots"):
            # Ensure we use the user_id from args
            user_id = getattr(args, 'user_id', 1)
            briefs = await brief_service.get_dashboard_briefs(user_id=user_id)
        
        # Show calendar summary
        console.print("\n[bold]Today's Schedule[/]")
        meetings = briefs.get("meetings", [])
        if meetings:
            for m in meetings[:5]:
                start = m.get("start_time", "")
                time_str = start.split("T")[1][:5] if "T" in start else "All Day"
                console.print(f"  [cyan]{time_str}[/] - {m.get('title')}")
        else:
            console.print("  [dim]No meetings scheduled for today.[/]")
        
        # Show todo summary
        console.print("\n[bold]Action Items[/]")
        todos = briefs.get("todos", [])
        if todos:
            for t in todos[:5]:
                console.print(f"  • {t.get('title')} ([dim]{t.get('source')}[/])")
        else:
            console.print("  [dim]No urgent items. Looking good![/]")
        
        # Show insights
        console.print("\n[bold]Insights[/]")
        reminders = briefs.get("reminders", {})
        summary = reminders.get("summary")
        if summary:
            console.print(f"  {summary}")
        else:
            console.print("  [dim]No new insights. All clear![/]")
        
    except Exception as e:
        console.print(f"[red]Failed to get brief: {e}[/]")


async def cmd_todo(args):
    """List todos and action items."""
    console.print(Panel.fit("[bold green]Your Action Items[/]"))
    
    try:
        from api.dependencies import AppState
        brief_service = AppState.get_brief_service(user_id=1)
        
        with console.status("[bold green]Fetching todos...", spinner="dots"):
            # Ensure we use the user_id from args
            user_id = getattr(args, 'user_id', 1)
            # Internal _get_todos is async
            todos = await brief_service._get_todos(user_id=user_id)

        if not todos:
            console.print("[dim]No action items found.[/]")
            return

        table = Table(show_header=True, header_style="bold green")
        table.add_column("Source", style="dim")
        table.add_column("Title")
        table.add_column("Due Date")
        table.add_column("Urgency")

        for t in todos:
            urgency_color = "red" if t.get("urgency") == "high" else "yellow" if t.get("urgency") == "medium" else "dim"
            table.add_row(
                t.get("source", "unknown"),
                t.get("title", "Untitled"),
                t.get("due_date", "No date")[:10] if t.get("due_date") else "No date",
                f"[{urgency_color}]{t.get('urgency', 'medium')}[/]"
            )
        
        console.print(table)
    except Exception as e:
        console.print(f"[red]Failed to list todos: {e}[/]")


async def cmd_ask(args):
    """Ask Clavr a question."""
    query = " ".join(args.query)
    
    if not query:
        console.print("[red]Please provide a question[/]")
        return
    
    console.print(f"\n[dim]Asking Clavr: {query}[/]\n")
    
    try:
        from api.dependencies import AppState
        user_id = getattr(args, 'user_id', 1)
        agent = AppState.get_supervisor_agent(user_id=user_id)
        
        if not agent:
            console.print("[red]Supervisor agent not available.[/]")
            return

        with console.status("[bold blue]Thinking...", spinner="dots"):
            # SupervisorAgent.route_and_execute is the main entry point
            response = await agent.route_and_execute(query, user_id=user_id) 
        
        console.print(Panel(
            response,
            title="Clavr",
            border_style="blue"
        ))
    except Exception as e:
        console.print(f"[red]Error asking Clavr: {e}[/]")
        # Fallback to placeholder if agent fails
        console.print(Panel(
            f"I would help you with: '{query}', but I hit an error: {e}",
            title="Clavr (Offline Mode)",
            border_style="yellow"
        ))


async def cmd_search(args):
    """Semantic search across all sources."""
    query = " ".join(args.query)
    
    if not query:
        console.print("[red]Please provide a search term[/]")
        return
    
    console.print(f"\n[bold]Searching for: {query}[/]\n")
    
    try:
        from src.utils.config import load_config
        from api.dependencies import AppState
        
        config = load_config()
        rag_engine = AppState.get_rag_engine() if hasattr(AppState, 'get_rag_engine') else None
        
        if rag_engine:
            results = await rag_engine.search(query, top_k=10)
            
            if results:
                table = Table(show_header=True)
                table.add_column("Source", style="dim")
                table.add_column("Title")
                table.add_column("Snippet")
                
                for r in results[:10]:
                    table.add_row(
                        r.get("source", "unknown"),
                        r.get("title", "Untitled")[:30],
                        r.get("text", "")[:50] + "..."
                    )
                
                console.print(table)
            else:
                console.print("[dim]No results found[/]")
        else:
            console.print("[yellow]Search not available. Connect to Clavr API.[/]")
            
    except Exception as e:
        console.print(f"[red]Search failed: {e}[/]")


async def cmd_insights(args):
    """View proactive insights."""
    console.print(Panel.fit("[bold yellow]Proactive Insights[/]"))
    
    try:
        from api.dependencies import AppState
        insight_service = AppState.get_insight_service()
        
        if not insight_service:
            console.print("[yellow]Insight service not available.[/]")
            return

        with console.status("[bold yellow]Fetching insights...", spinner="dots"):
            user_id = getattr(args, 'user_id', 1)
            insights = await insight_service.get_contextual_insights(user_id=user_id, current_context="CLI")
            
        if not insights:
            # Fallback to general insights if no contextual ones
            insights = await insight_service.get_urgent_insights(user_id=user_id)

        if not insights:
            console.print("[dim]No new insights found.[/]")
            return

        for i, insight in enumerate(insights, 1):
            icon = {"conflict": "!", "decay": "+", "deadline": "-", "context": "?"}.get(insight.get("type"), "?")
            console.print(f"\n{icon} [bold]{insight.get('type', 'insight').title()}[/]")
            console.print(f"   {insight.get('content')}")
            if insight.get('related_entities'):
                console.print(f"   [dim]Related: {', '.join(insight['related_entities'])}[/]")

    except Exception as e:
        console.print(f"[red]Failed to fetch insights: {e}[/]")


def main():
    """Main CLI entry point."""
    setup_environment()
    
    parser = argparse.ArgumentParser(
        prog="clavr",
        description="Clavr CLI - Your intelligent work assistant"
    )
    
    parser.add_argument("--user-id", type=int, default=1, help="User ID to act as")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # brief command
    brief_parser = subparsers.add_parser("brief", help="Get morning briefing")
    brief_parser.set_defaults(func=cmd_brief)
    
    # todo command
    todo_parser = subparsers.add_parser("todo", help="List action items")
    todo_parser.set_defaults(func=cmd_todo)
    
    # ask command
    ask_parser = subparsers.add_parser("ask", help="Ask Clavr a question")
    ask_parser.add_argument("query", nargs="*", help="Your question")
    ask_parser.set_defaults(func=cmd_ask)
    
    # search command
    search_parser = subparsers.add_parser("search", help="Semantic search")
    search_parser.add_argument("query", nargs="*", help="Search term")
    search_parser.set_defaults(func=cmd_search)
    
    # insights command
    insights_parser = subparsers.add_parser("insights", help="View insights")
    insights_parser.set_defaults(func=cmd_insights)
    
    args = parser.parse_args()
    
    if args.command is None:
        # Default to brief
        console.print(Panel.fit(
            "[bold blue]Welcome to Clavr CLI![/]\n\n"
            "Commands:\n"
            "  [green]clavr brief[/]    - Morning briefing\n"
            "  [green]clavr todo[/]     - Action items\n"
            "  [green]clavr ask[/]      - Ask anything\n"
            "  [green]clavr search[/]   - Semantic search\n"
            "  [green]clavr insights[/] - View insights",
            title="clavr"
        ))
        return
    
    # Run the async command
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
