.PHONY: check-imports test-imports lint format help

help:
	@echo "Available commands:"
	@echo "  make check-imports  - Check for circular imports"
	@echo "  make test-imports   - Test critical imports"
	@echo "  make lint           - Run linters"
	@echo "  make format         - Format code"

check-imports:
	@echo "Checking for circular imports..."
	@python scripts/check_circular_imports.py

test-imports:
	@echo "Testing critical imports..."
	@python -c "from src.utils import QueryClassifier; from src.ai.rag import RAGEngine; from src.services import RAGService; from src.models import EmailMessage; print('✓ All imports work successfully')"

lint:
	@echo "Running linters..."
	@pylint --disable=all --enable=import-error,cyclic-import src/ || true
	@python scripts/check_circular_imports.py

format:
	@echo "Formatting code..."
	@black src/ api/ scripts/
	@isort src/ api/ scripts/
