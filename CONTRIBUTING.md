# Contributing to Clavr

Thank you for your interest in contributing! This guide outlines the workflow and standards for contributing to the Clavr project.

> [!TIP]
> If you are new to the project, please start by reading the [Onboarding Guide](file:///Users/maniko/.gemini/antigravity/brain/69300d59-15f1-4e1c-9e57-d6d248028320/onboarding.md) for a deep dive into the architecture.

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone <your-fork-url>
   cd clavr
   ```
3. **Set up the environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Configure Infrastructure**:
   - Ensure **PostgreSQL** and **Redis** are running.
   - Copy `.env.example` to `.env` and fill in necessary API keys.
5. **Initialize Database**:
   ```bash
   alembic upgrade head
   ```

## Development Workflow

### Running the Application
To start the API and all background workers (Celery) simultaneously:
```bash
python main.py
```

### Coding Standards
- **Python Version**: 3.13+
- **Style**: PEP 8 compliance. We use **Black** for formatting and **isort** for import sorting.
- **Type Hints**: Required for all new functions and class methods.
- **Docstrings**: Use Google-style docstrings for all public modules, classes, and functions.

### Import Hierarchy (Crucial)
To prevent circular dependencies, we follow a strict bottom-up import hierarchy:
1. `utils/`: Low-level utilities. No dependencies on other `src/` modules.
2. `ai/`: AI logic, RAG, and prompts. Depends on `utils/`.
3. `core/`: Core business logic and models. Depends on `ai/`, `utils/`.
4. `services/`: External service integrations and complex business logic. Depends on `core/`, `ai/`, `utils/`.
5. `agents/`: High-level orchestration and agents. Depends on all layers below.

Run the circular import check before committing:
```bash
make check-imports
```

## Testing & Quality Assurance

- **Unit Tests**: `pytest`
- **Linting**: `make lint` (runs Pylint/Flake8)
- **Formatting**: `make format`
- **Circular Imports**: `make check-imports`

> [!IMPORTANT]
> All Pull Requests must pass linting and `check-imports` before they will be reviewed.

## Pull Request Process

1. Create a new branch for your feature or bugfix: `git checkout -b feature/your-feature-name`.
2. Implement your changes and add corresponding tests.
3. Ensure documentation in `docs/` or the README is updated to reflect your changes.
4. Run `make format` and `make lint`.
5. Submit the PR and request a review from maintainers.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.

