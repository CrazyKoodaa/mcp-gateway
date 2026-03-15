# MCP Gateway Git Workflow

This document summarizes the Git workflow, CI/CD pipelines, and development practices.

## 📁 Repository Structure

```
.github/
├── workflows/
│   ├── ci.yml          # Main CI pipeline
│   └── release.yml     # Release automation
└── pull_request_template.md

.githooks/
├── pre-commit          # Code quality checks
├── pre-push            # Test runner
├── commit-msg          # Commit message validation
└── README.md           # Setup instructions
```

## 🔄 CI/CD Pipeline

### Continuous Integration (ci.yml)

Runs on every push and PR to `main`/`develop`:

1. **Lint & Type Check**
   - Ruff linter
   - Ruff formatter check
   - MyPy type checker

2. **Test Matrix**
   - Python 3.10, 3.11, 3.12, 3.13
   - Unit tests (excluding manual tests)
   - Coverage reporting to Codecov

3. **Integration Tests**
   - Full integration test suite
   - Timeout: 10 minutes

4. **Build & Package**
   - Build wheel and sdist
   - Twine package validation
   - Artifact upload

5. **Docker Build**
   - Build Docker image
   - Layer caching with BuildKit

### Release Automation (release.yml)

Triggered on version tags (`v*`):

1. Run full test suite
2. Build and publish to PyPI
3. Create GitHub Release with artifacts
4. Build and push Docker image to GHCR

## 🎣 Git Hooks

### Setup
```bash
git config core.hooksPath .githooks
```

### pre-commit
- Runs on: `git commit`
- Checks:
  - Ruff linter with auto-fix
  - Ruff format validation
- Fails commit if checks don't pass

### pre-push
- Runs on: `git push`
- Checks:
  - Full test suite (excluding manual tests)
- Prevents push if tests fail

### commit-msg
- Runs on: `git commit`
- Validates [Conventional Commits](https://www.conventionalcommits.org/)
- Format: `<type>(<scope>): <description>`

## 🌿 Branch Strategy

### Main Branches
- `main` - Production-ready code
- `develop` - Integration branch for features

### Feature Branches
Use prefixes:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation
- `refactor/` - Code refactoring
- `test/` - Test improvements
- `chore/` - Maintenance

Example: `feature/add-oauth-auth`

## ✍️ Commit Convention

Follow Conventional Commits:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `style:` Code style (formatting)
- `refactor:` Code refactoring
- `perf:` Performance improvement
- `test:` Adding/updating tests
- `chore:` Build/dependency changes
- `ci:` CI/CD changes
- `build:` Build system changes
- `revert:` Revert previous commit

### Examples
```
feat(backends): add circuit breaker pattern for failed backends

fix(admin): prevent args loss when saving filesystem server config

docs(readme): add docker deployment instructions

test(integration): add hot reload integration tests
```

## 🔀 Pull Request Process

1. **Create Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**
   - Write code
   - Add/update tests
   - Update documentation

3. **Quality Checks**
   ```bash
   # Format
   uv run ruff format src tests
   
   # Lint
   uv run ruff check src tests
   
   # Type check
   uv run mypy src
   
   # Test
   uv run pytest tests/ -v
   ```

4. **Commit**
   ```bash
   git add .
   git commit -m "feat(scope): description"
   ```

5. **Push & PR**
   ```bash
   git push origin feature/your-feature-name
   ```

### PR Requirements
- [ ] All CI checks pass
- [ ] At least 1 review approval
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No merge conflicts

## 🏷️ Release Process

1. **Update Version**
   ```toml
   # pyproject.toml
   version = "0.3.0"
   ```

2. **Update Release Notes**
   - Add entry to `RELEASE_NOTES.md`

3. **Create Tag**
   ```bash
   git tag -a v0.3.0 -m "Release version 0.3.0"
   git push origin v0.3.0
   ```

4. **Automation Handles**
   - Running tests
   - Building package
   - Publishing to PyPI
   - Creating GitHub Release
   - Building/pushing Docker image

## 🧪 Testing Strategy

### Unit Tests
- Fast, isolated tests
- Run on every commit
- Location: `tests/unit/`

### Integration Tests
- Test component interactions
- Run in CI before merge
- Location: `tests/integration/`

### Manual Tests
- Require external services
- Run manually when needed
- Location: `tests/manual/`

## 🚨 Emergency Procedures

### Skip Hooks (Not Recommended)
```bash
# Skip pre-commit
git commit --no-verify -m "message"

# Skip pre-push
git push --no-verify
```

### Hotfix Process
1. Branch from `main`: `git checkout -b fix/critical-bug main`
2. Fix and test
3. PR to `main` with "hotfix" label
4. Fast-track review
5. After merge, tag and release immediately

## 📊 CI Status Badges

Add to README:
```markdown
![CI](https://github.com/OWNER/REPO/workflows/CI/badge.svg)
![Release](https://github.com/OWNER/REPO/workflows/Release/badge.svg)
```
