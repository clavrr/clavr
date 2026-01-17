
import sys
import os

sys.path.append(os.getcwd())

def check_imports():
    print("Checking agent imports...")
    try:
        from src.agents.base import BaseAgent
        print("✅ BaseAgent imported")
    except Exception as e:
        print(f"❌ BaseAgent import failed: {e}")

    try:
        from src.agents.research.agent import ResearchAgent
        print("✅ ResearchAgent imported")
    except Exception as e:
        print(f"❌ ResearchAgent import failed: {e}")

    try:
        from src.agents.tasks.agent import TaskAgent
        print("✅ TaskAgent imported")
    except Exception as e:
        print(f"❌ TaskAgent import failed: {e}")

    try:
        from src.agents.calendar.agent import CalendarAgent
        print("✅ CalendarAgent imported")
    except Exception as e:
        print(f"❌ CalendarAgent import failed: {e}")

if __name__ == "__main__":
    check_imports()
