#!/usr/bin/env bash
set -e

# Target directory where your project files currently live
CURRENT_DIR="$(pwd)"
PROJECT_NAME="fight-me"

echo "===== CREATING GITHUB REPO & PUSHING: $PROJECT_NAME ====="

cd "$CURRENT_DIR" || exit 1

# Ensure git is initialized in the current directory if it isn't already
if [ ! -d ".git" ]; then
    git init
fi

# Ensure we are on a main branch (or create it if needed)
if git show-ref --verify --quiet refs/heads/main; then
    git switch main
else
    git checkout -b main
fi

# Create a robust .gitignore if one doesn't exist
if [ ! -f ".gitignore" ]; then
    cat << 'EOF' > .gitignore
# Local secrets
.env
.env.*
!.env.example
*.pem
*.key
*.crt
credentials/
secrets/

# Python environments
venv/
.venv/
env/
__pycache__/
*.py[cod]

# Local databases
*.db
*.sqlite
*.sqlite3

# Logs
*.log
logs/

# macOS / editors
.DS_Store
.vscode/
.idea/

# Temporary files
*.tmp
*.temp
*.swp
*.swo
EOF
fi

# Stage all files in the current directory (respecting .gitignore)
git add .

# Commit changes if there's anything staged
if ! git diff --cached --quiet; then
    git commit -m "Initial commit: add project files"
else
    echo "No changes to commit."
fi

# Create the public GitHub repository using GitHub CLI, link remote, and push
# Change `--public` to `--private` if desired
gh repo create "$PROJECT_NAME" --public --source=. --remote=origin --push

echo
echo "========================================"
echo " REPO CREATED AND FILES PUSHED"
echo "========================================"
git remote -v
git branch --show-current
git status
