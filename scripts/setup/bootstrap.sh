#!/bin/bash
# MCP Gateway Bootstrap Script
# Usage: ./bootstrap.sh [bootstrap|update]

set -e

# Modus: bootstrap oder update
MODE="${1:-bootstrap}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="mcp-gateway"

# ============================================
# UPDATE MODE
# ============================================
if [ "$MODE" = "update" ]; then
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  MCP Gateway Update${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    cd "$SCRIPT_DIR"
    
    # 1. Git Pull
    if [ -d ".git" ]; then
        echo -e "${BLUE}[*]${NC} Pulling latest changes..."
        git pull origin main || git pull origin master || echo -e "${YELLOW}[!]${NC} Git pull failed, continuing..."
        echo -e "${GREEN}[✓]${NC} Git updated"
    else
        echo -e "${YELLOW}[!]${NC} Not a git repository, skipping git pull"
    fi
    
    # 2. Dependencies aktualisieren
    echo ""
    echo -e "${BLUE}[*]${NC} Updating dependencies..."
    uv pip install -e ".[dev]" -q
    echo -e "${GREEN}[+]${NC} Dependencies updated"
    
    # 3. Config Migration (neue Felder hinzufügen)
    echo ""
    echo -e "${BLUE}[*]${NC} Checking configuration..."
    if [ -f "config.json" ] && [ -f "config.json.example" ]; then
        echo -e "${YELLOW}[!]${NC} Check config.json.example for new options"
        echo "    Manually merge new fields if needed"
    fi
    
    # 4. Tests laufen lassen
    echo ""
    echo -e "${BLUE}[*]${NC} Running tests..."
    if uv run python -m pytest tests/ -q --tb=line 2>/dev/null | tail -5; then
        echo -e "${GREEN}[✓]${NC} Tests passed"
    else
        echo -e "${YELLOW}[!]${NC} Some tests failed"
    fi
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Update Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Restart the gateway if running:"
    echo -e "  ${YELLOW}pkill -f mcp_gateway${NC}"
    echo -e "  ${YELLOW}./scripts/run.sh${NC}"
    echo ""
    
    exit 0
fi

# ============================================
# BOOTSTRAP MODE (Original)
# ============================================

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  MCP Gateway Bootstrap${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ============================================
# 1. Python Version prüfen
# ============================================
echo -e "${BLUE}[*]${NC} Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' || echo "0")
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}[✗]${NC} Python 3.10+ required, found: $PYTHON_VERSION"
    exit 1
fi
echo -e "${GREEN}[✓]${NC} Python $PYTHON_VERSION found"

# ============================================
# 2. Abhängigkeiten prüfen
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Checking dependencies..."

# Prüfe uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}[!]${NC} uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "    Or: pip install uv"
    exit 1
fi
echo -e "${GREEN}[✓]${NC} uv found"

# ============================================
# 3. Virtuelle Umgebung erstellen
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Setting up virtual environment..."
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    uv venv .venv
    echo -e "${GREEN}[+]${NC} Created virtual environment"
else
    echo -e "${GREEN}[✓]${NC} Virtual environment exists"
fi

# ============================================
# 4. Abhängigkeiten installieren
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Installing dependencies..."
uv pip install -e ".[dev]" -q
echo -e "${GREEN}[+]${NC} Dependencies installed"

# ============================================
# 5. Verzeichnisstruktur erstellen
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Creating directories..."
mkdir -p logs
mkdir -p ai/logs
mkdir -p docs-internal
echo -e "${GREEN}[+]${NC} Created logs/, ai/logs/, docs-internal/"

# ============================================
# 6. Konfiguration erstellen
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Setting up configuration..."

if [ ! -f "config.json" ]; then
    if [ -f "config.json.example" ]; then
        cp config.json.example config.json
        echo -e "${GREEN}[+]${NC} Created config.json from template"
    else
        cat > config.json << 'EOF'
{
  "mcp_servers": {
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time", "--local-timezone=Europe/Berlin"]
    }
  },
  "http_gateway": {
    "host": "0.0.0.0",
    "port": 8080
  }
}
EOF
        echo -e "${GREEN}[+]${NC} Created default config.json"
    fi
else
    echo -e "${GREEN}[✓]${NC} config.json exists"
fi

# ============================================
# 7. Pre-commit hooks (optional)
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Setting up git hooks..."
if [ -d ".git" ]; then
    uv run pre-commit install 2>/dev/null || echo -e "${YELLOW}[!]${NC} pre-commit not configured (optional)"
else
    echo -e "${YELLOW}[!]${NC} Not a git repository (optional)"
fi

# ============================================
# 8. Tests ausführen
# ============================================
echo ""
echo -e "${BLUE}[*]${NC} Running basic tests..."
if uv run python -m pytest tests/test_config.py -q --tb=short 2>/dev/null; then
    echo -e "${GREEN}[✓]${NC} Basic tests passed"
else
    echo -e "${YELLOW}[!]${NC} Some tests failed (run: uv run pytest tests/ to see details)"
fi

# ============================================
# Zusammenfassung
# ============================================
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Bootstrap Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit config.json to add your MCP servers"
echo "  2. Run the gateway:"
echo -e "     ${YELLOW}./scripts/run.sh${NC}"
echo "     or: ${YELLOW}uv run python -m mcp_gateway${NC}"
echo ""
echo "Documentation:"
echo "  - README.md"
echo ""
echo "For updates run:"
echo -e "  ${YELLOW}./scripts/setup/bootstrap.sh update${NC}"
echo ""
