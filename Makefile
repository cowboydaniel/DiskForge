# DiskForge Makefile
# Build, test, and lint commands

.PHONY: all install install-dev lint format test test-unit test-integration test-gui test-coverage clean build gui cli help

# Default Python interpreter
PYTHON ?= python3
POETRY ?= poetry

# Colors for output
GREEN := \033[0;32m
NC := \033[0m

all: install lint test

help:
	@echo "DiskForge Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install       Install production dependencies"
	@echo "  install-dev   Install development dependencies"
	@echo "  lint          Run linters (ruff, mypy)"
	@echo "  format        Format code with ruff"
	@echo "  test          Run all tests"
	@echo "  test-unit     Run unit tests only"
	@echo "  test-integration  Run integration tests"
	@echo "  test-gui      Run GUI tests"
	@echo "  test-coverage Run tests with coverage report"
	@echo "  clean         Clean build artifacts"
	@echo "  build         Build distribution packages"
	@echo "  gui           Launch the GUI application"
	@echo "  cli           Show CLI help"

# Installation
install:
	@echo "$(GREEN)Installing dependencies...$(NC)"
	$(POETRY) install --only main

install-dev:
	@echo "$(GREEN)Installing development dependencies...$(NC)"
	$(POETRY) install

# Alternative: Install with pip if Poetry is not available
pip-install:
	@echo "$(GREEN)Installing with pip...$(NC)"
	$(PYTHON) -m pip install -e .

pip-install-dev:
	@echo "$(GREEN)Installing dev dependencies with pip...$(NC)"
	$(PYTHON) -m pip install -e ".[dev]"

# Linting
lint: lint-ruff lint-mypy

lint-ruff:
	@echo "$(GREEN)Running ruff...$(NC)"
	$(POETRY) run ruff check src tests

lint-mypy:
	@echo "$(GREEN)Running mypy...$(NC)"
	$(POETRY) run mypy src/diskforge || true

# Formatting
format:
	@echo "$(GREEN)Formatting code...$(NC)"
	$(POETRY) run ruff format src tests
	$(POETRY) run ruff check --fix src tests

# Testing
test:
	@echo "$(GREEN)Running all tests...$(NC)"
	$(POETRY) run pytest -v

test-unit:
	@echo "$(GREEN)Running unit tests...$(NC)"
	$(POETRY) run pytest tests/unit -v -m unit

test-integration:
	@echo "$(GREEN)Running integration tests...$(NC)"
	$(POETRY) run pytest tests/integration -v -m integration

test-gui:
	@echo "$(GREEN)Running GUI tests...$(NC)"
	$(POETRY) run pytest tests/gui -v -m gui

test-coverage:
	@echo "$(GREEN)Running tests with coverage...$(NC)"
	$(POETRY) run pytest --cov=src/diskforge --cov-report=html --cov-report=term

# Cleaning
clean:
	@echo "$(GREEN)Cleaning build artifacts...$(NC)"
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Building
build: clean
	@echo "$(GREEN)Building distribution packages...$(NC)"
	$(POETRY) build

# Running the application
gui:
	@echo "$(GREEN)Launching DiskForge GUI...$(NC)"
	$(POETRY) run diskforge-gui

cli:
	@echo "$(GREEN)DiskForge CLI Help...$(NC)"
	$(POETRY) run diskforge --help

# Development helpers
shell:
	@echo "$(GREEN)Starting Poetry shell...$(NC)"
	$(POETRY) shell

update:
	@echo "$(GREEN)Updating dependencies...$(NC)"
	$(POETRY) update

check: lint test
	@echo "$(GREEN)All checks passed!$(NC)"

# Pre-commit hooks
pre-commit-install:
	@echo "$(GREEN)Installing pre-commit hooks...$(NC)"
	$(POETRY) run pre-commit install

pre-commit-run:
	@echo "$(GREEN)Running pre-commit on all files...$(NC)"
	$(POETRY) run pre-commit run --all-files

# Docker support (optional)
docker-build:
	@echo "$(GREEN)Building Docker image...$(NC)"
	docker build -t diskforge:latest .

docker-run:
	@echo "$(GREEN)Running DiskForge in Docker...$(NC)"
	docker run -it --privileged diskforge:latest
