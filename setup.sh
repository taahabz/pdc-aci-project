#!/bin/bash
# setup.sh - Initialize project environment and directories
# Usage: bash setup.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📦 Setting up Adaptive Cache Invalidation Project..."
echo "   Project root: $PROJECT_ROOT"

# 1. Create virtual environment if it doesn't exist
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo "✓ Creating Python virtual environment..."
    cd "$PROJECT_ROOT"
    python3 -m venv venv
else
    echo "✓ Virtual environment already exists"
fi

# 2. Activate venv and install dependencies
echo "✓ Installing dependencies..."
source "$PROJECT_ROOT/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$PROJECT_ROOT/requirements.txt" -q

# 3. Create necessary directories
echo "✓ Creating project directories..."
mkdir -p "$PROJECT_ROOT/shared_db"
mkdir -p "$PROJECT_ROOT/results"
mkdir -p "$PROJECT_ROOT/plots"
mkdir -p "$PROJECT_ROOT/logs"
mkdir -p "$PROJECT_ROOT/app/strategies"
mkdir -p "$PROJECT_ROOT/load_gen"

# 4. Create .gitkeep files
touch "$PROJECT_ROOT/shared_db/.gitkeep"
touch "$PROJECT_ROOT/results/.gitkeep"
touch "$PROJECT_ROOT/plots/.gitkeep"
touch "$PROJECT_ROOT/logs/.gitkeep"

# 5. Copy .env if it doesn't exist
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "✓ Creating .env from template..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo "   ⚠️  Edit .env to customize configuration for your environment"
else
    echo "✓ .env already exists"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Activate venv: source venv/bin/activate"
echo "  2. Review and adjust: .env"
echo "  3. Start Docker: docker compose up -d"
echo "  4. Run tests: python3 -m pytest tests/"
echo ""
