# Contributing to MCP Gateway

Thank you for your interest in contributing to MCP Gateway! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Node.js 18+ (for admin dashboard development)

### Setup Steps

1. Fork and clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/mcp-gateway.git
cd mcp-gateway
```

2. Install dependencies:
```bash
uv venv
uv pip install -e ".[dev]"
```

3. Run tests to verify setup:
```bash
uv run pytest tests/ -v
```

## Git Workflow

### Branch Naming Convention

Use the following prefixes for branch names:

- `feature/` - New features (e.g., `feature/add-oauth-auth`)
- `fix/` - Bug fixes (e.g., `fix/hot-reload-race-condition`)
- `docs/` - Documentation updates (e.g., `docs/api-examples`)
- `refactor/` - Code refactoring (e.g., `refactor/simplify-backends`)
- `test/` - Test improvements (e.g., `test/add-integration-tests`)
- `chore/` - Maintenance tasks (e.g., `chore/update-dependencies`)

### Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `style:` Code style (formatting, missing semi colons, etc)
- `refactor:` Code refactoring
- `perf:` Performance improvements
- `test:` Adding or correcting tests
- `chore:` Build process or auxiliary tool changes

Examples:
```
feat(backends): add circuit breaker pattern for failed backends

fix(admin): prevent args loss when saving filesystem server config

docs(readme): add docker deployment instructions
```

### Pull Request Process

1. **Create a branch** from `main`:
```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes** following our coding standards

3. **Run quality checks** before committing:
```bash
# Format code
uv run ruff format src tests

# Run linter
uv run ruff check src tests

# Run type checker
uv run mypy src

# Run tests
uv run pytest tests/ -v
```

4. **Commit your changes**:
```bash
git add .
git commit -m "feat(scope): description"
```

5. **Push and create PR**:
```bash
git push origin feature/your-feature-name
```

Then open a Pull Request on GitHub.

### PR Requirements

- All CI checks must pass
- At least one review approval required
- Tests added/updated for new features
- Documentation updated if needed
- No merge conflicts

## Coding Standards

### Python
- Follow PEP 8
- Use type hints
- Maximum line length: 100 characters
- Use `ruff` for linting and formatting

### JavaScript (Admin Dashboard)
- Use ES6+ features
- Follow existing code style
- Comment complex logic

### Testing

Write tests for:
- New features
- Bug fixes (reproduce the bug first)
- Edge cases

Test structure:
```python
# tests/unit/test_module.py
def test_feature_description():
    """Test what the feature does."""
    # Arrange
    input_data = ...
    
    # Act
    result = function_under_test(input_data)
    
    # Assert
    assert result == expected_output
```

## Release Process

1. Update version in `pyproject.toml`
2. Update `RELEASE_NOTES.md`
3. Create a git tag:
```bash
git tag -a v0.3.0 -m "Release version 0.3.0"
git push origin v0.3.0
```
4. GitHub Actions will automatically:
   - Run tests
   - Build package
   - Publish to PyPI
   - Create GitHub Release
   - Build and push Docker image

## Getting Help

- Open an issue for bugs or feature requests
- Join discussions in GitHub Discussions
- Check existing issues before creating new ones

## Code of Conduct

Be respectful and constructive in all interactions.
