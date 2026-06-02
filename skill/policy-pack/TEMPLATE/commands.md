# Build & Development Commands

## [TEMPLATE] Command Reference

> Replace with your project's actual commands.

---

## Build Commands

```yaml
build:
  description: "Compile/build the project"
  command: "[TEMPLATE: your build command]"
  directory: "[TEMPLATE: build output directory]"

install:
  description: "Install dependencies"
  command: "[TEMPLATE: install command]"
```

---

## Test Commands

```yaml
test:
  unit:
    description: "Run unit tests"
    command: "[TEMPLATE: unit test command]"
    coverage: true
    threshold: 80

  integration:
    description: "Run integration tests"
    command: "[TEMPLATE: integration test command]"
    requires: "database service"

  e2e:
    description: "Run end-to-end tests"
    command: "[TEMPLATE: e2e command]"
    requires: "full stack running"

  all:
    description: "Run all test suites"
    command: "[TEMPLATE: run all tests]"
```

---

## Debug Commands

```yaml
debug:
  dev_server:
    description: "Start development server with debug"
    command: "[TEMPLATE: debug server command]"

  test_watch:
    description: "Run tests in watch mode"
    command: "[TEMPLATE: watch command]"

  attach:
    description: "Attach to running process"
    command: "[TEMPLATE: attach command]"
```

---

## Lint & Format Commands

```yaml
lint:
  description: "Run linter"
  command: "[TEMPLATE: lint command]"

  format:
    description: "Format code"
    command: "[TEMPLATE: format command]"

  typecheck:
    description: "Run type checker"
    command: "[TEMPLATE: typecheck command]"

  security:
    description: "Security audit"
    command: "[TEMPLATE: security command]"
```

---

## Development Workflow

```yaml
dev:
  start:
    description: "Start development server"
    command: "[TEMPLATE: dev start command]"

  reset:
    description: "Reset database/state"
    command: "[TEMPLATE: reset command]"
```

---

## CI/CD Commands

```yaml
ci:
  pre_commit:
    command: "[TEMPLATE: pre-commit hook command]"

  ci_build:
    command: "[TEMPLATE: CI build command]"

  ci_test:
    command: "[TEMPLATE: CI test command]"
```