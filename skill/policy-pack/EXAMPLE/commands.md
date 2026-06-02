# Build & Development Commands

## FastAPI Project Command Reference

---

## Build Commands

```yaml
build:
  description: "Compile Python files (noop for Python)"
  command: "python -m py_compile src/**/*.py"
  directory: "src"

install:
  description: "Install dependencies"
  command: "pip install -r requirements.txt"

requirements:
  description: "Generate requirements.txt"
  command: "pip freeze > requirements.txt"

setup:
  description: "Initial project setup"
  command: "bash scripts/setup.sh"
```

---

## Test Commands

```yaml
test:
  unit:
    description: "Run unit tests"
    command: "pytest tests/unit -v --cov=src --cov-report=term-missing --cov-fail-under=80"
    coverage: true
    threshold: 80
    markers:
      - "unit"

  integration:
    description: "Run integration tests"
    command: "pytest tests/integration -v --cov=src --cov-report=term-missing -m integration"
    requires: "database service"
    markers:
      - "integration"

  e2e:
    description: "Run e2e tests"
    command: "pytest tests/e2e -v -m e2e"
    requires: "full stack running"
    markers:
      - "e2e"

  all:
    description: "Run all test suites"
    command: "pytest tests/ -v --cov=src --cov-report=term-missing --cov-fail-under=80 -m 'not e2e'"
    parallel: true
    workers: 4

  watch:
    description: "Run tests in watch mode"
    command: "ptw tests/ --cov=src"
```

---

## Debug Commands

```yaml
debug:
  dev_server:
    description: "Start development server with reload"
    command: "uvicorn src.main:app --reload --log-level debug"

  prod_server:
    description: "Start production server"
    command: "uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4"

  test_watch:
    description: "Run tests in watch mode"
    command: "ptw tests/unit -v"

  shell:
    description: "Start REPL with app context"
    command: "python -m IPython -c 'from src.main import app; import asyncio; asyncio.run(app.router startup())'"

  db_shell:
    description: "Connect to database"
    command: "psql $DATABASE_URL"
```

---

## Lint & Format Commands

```yaml
lint:
  description: "Run Ruff linter"
  command: "ruff check src/ tests/"

  format:
    description: "Format code with Black"
    command: "black src/ tests/"

  format_check:
    description: "Check formatting without applying"
    command: "black --check src/ tests/"

  import_sort:
    description: "Sort imports with isort"
    command: "isort src/ tests/"

  typecheck:
    description: "Run mypy type checker"
    command: "mypy src/ --ignore-missing-imports"

  security:
    description: "Security audit with Bandit"
    command: "bandit -r src/"

  all:
    description: "Run all lint checks"
    command: "make lint"
```

---

## Database Commands

```yaml
db:
  migrate:
    description: "Run Alembic migrations"
    command: "alembic upgrade head"

  migrate_create:
    description: "Create new migration"
    command: "alembic revision --autogenerate -m '{description}'"

  migrate_downgrade:
    description: "Rollback last migration"
    command: "alembic downgrade -1"

  reset:
    description: "Reset database"
    command: "alembic downgrade base && alembic upgrade head"

  seed:
    description: "Seed database with test data"
    command: "python -m scripts.seed"
```

---

## Development Workflow

```yaml
dev:
  start:
    description: "Start development server"
    command: "make dev"

  setup:
    description: "Setup development environment"
    command: "make setup"

  clean:
    description: "Clean cache files"
    command: "find . -type d -name __pycache__ -exec rm -rf {} + && find . -name '*.pyc' -delete"

  docker_up:
    description: "Start Docker services"
    command: "docker-compose up -d"

  docker_down:
    description: "Stop Docker services"
    command: "docker-compose down"
```

---

## CI/CD Commands

```yaml
ci:
  pre_commit:
    command: "ruff check && black --check && mypy src/"

  ci_build:
    command: "pip install -r requirements.txt && python -m py_compile src/**/*.py"

  ci_test:
    command: "pytest tests/ -v --cov=src --cov-fail-under=80 -m 'not e2e'"

  ci_lint:
    command: "ruff check src/ tests/ && black --check src/ tests/"
```