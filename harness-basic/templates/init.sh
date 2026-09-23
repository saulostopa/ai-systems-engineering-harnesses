#!/bin/bash
# init.sh — initializes the basic harness in a project (model of the webmotors-harness-factory)
# Usage: copy the templates/ package to the project root and run: ./init.sh
set -e

echo "=== Basic harness — initialization ==="

# 1. Working directory
echo "[1/4] Checking working directory..."
[ -f "AGENTS.md" ] || { echo "  ERROR: AGENTS.md missing. Copy the package to the project root."; exit 1; }
echo "  OK: AGENTS.md present"

# 2. Tools
echo "[2/4] Checking tools..."
command -v node >/dev/null 2>&1 && echo "  OK: node $(node --version)" || echo "  WARNING: node not found (adjust as needed for the project)"
command -v npm  >/dev/null 2>&1 && echo "  OK: npm $(npm --version)" || echo "  WARNING: npm not found"

# 3. Hooks (optional — copy from the factory's .githooks/ if you have one)
echo "[3/4] Checking hooks..."
if git rev-parse --git-dir >/dev/null 2>&1; then
  HOOKS=$(git config core.hooksPath || echo "not configured")
  echo "  hooksPath: $HOOKS"
else
  echo "  WARNING: not a git repository"
fi

# 4. Baseline
echo "[4/4] Project baseline..."
if [ -f "package.json" ]; then
  npm run build >/dev/null 2>&1 && echo "  OK: build passed" || echo "  WARNING: build failed — run 'npm run build' and investigate before working"
else
  echo "  WARNING: no package.json (project of a different nature — adjust this section)"
fi

echo
echo "=== Next steps ==="
echo "  1. Read AGENTS.md"
echo "  2. Choose ONE feature in feature_list.json (status: in_progress)"
echo "  3. Declare the scope in policies/scope-control.md"
echo "  4. Implement and verify (build + tests + evidence)"