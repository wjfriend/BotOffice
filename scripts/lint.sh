#!/usr/bin/env bash
# Syntax gate for every deliverable. Exit code 0 means the tree is
# syntactically valid; anything else blocks delivery (constraint 3).
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FAILED=0

echo "== python =="
if command -v python >/dev/null 2>&1; then
  while IFS= read -r file; do
    if ! python -m py_compile "$file"; then
      echo "FAIL: $file"
      FAILED=1
    fi
  done < <(find botoffice scripts -name "*.py" 2>/dev/null; echo "server.py")
elif command -v python3 >/dev/null 2>&1; then
  while IFS= read -r file; do
    if ! python3 -m py_compile "$file"; then
      echo "FAIL: $file"
      FAILED=1
    fi
  done < <(find botoffice scripts -name "*.py" 2>/dev/null; echo "server.py")
else
  echo "SKIP: no python interpreter found"
fi

echo "== javascript =="
if command -v node >/dev/null 2>&1; then
  while IFS= read -r file; do
    if ! node --check "$file"; then
      echo "FAIL: $file"
      FAILED=1
    fi
  done < <(find public -name "*.js" 2>/dev/null)
else
  echo "SKIP: node not found"
fi

echo "== json =="
if command -v python >/dev/null 2>&1; then
  while IFS= read -r file; do
    if ! python -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" "$file"; then
      echo "FAIL: $file"
      FAILED=1
    fi
  done < <(find config data -name "*.json" 2>/dev/null)
fi

if [ "$FAILED" -ne 0 ]; then
  echo "LINT FAILED"
  exit 1
fi
echo "LINT OK"
exit 0
