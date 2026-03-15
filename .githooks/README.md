# Git Hooks

This directory contains git hooks for MCP Gateway development.

## Setup

To use these hooks, run:

```bash
git config core.hooksPath .githooks
```

## Available Hooks

### pre-commit
- Runs `ruff check` on staged Python files
- Runs `ruff format --check` on staged Python files
- Auto-fixes issues where possible

### pre-push
- Runs the test suite (excluding manual tests)
- Prevents pushing if tests fail

### commit-msg
- Validates commit message format
- Enforces [Conventional Commits](https://www.conventionalcommits.org/)

## Skipping Hooks

In case you need to bypass hooks (not recommended):

```bash
# Skip pre-commit checks
git commit --no-verify -m "your message"

# Skip pre-push checks
git push --no-verify
```

## Troubleshooting

If hooks aren't running:
1. Make sure hooks are executable: `chmod +x .githooks/*`
2. Verify hookPath is set: `git config core.hooksPath` should output `.githooks`
3. Check that `uv` is installed and in your PATH
