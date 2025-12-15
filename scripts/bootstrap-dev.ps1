# Bootstrap developer environment for Windows (PowerShell)
# Usage: From the repository root run `./scripts/bootstrap-dev.ps1`

Write-Host "Bootstrapping dev environment..."

# Ensure venv exists
if (-Not (Test-Path -Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Virtualenv not found at ./.venv - create one first or run your preferred setup." -ForegroundColor Yellow
}

# Install dev dependencies (editable)
Write-Host "Installing dev dependencies into .venv..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip; \
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'

# Install pre-commit hooks
Write-Host "Installing pre-commit hooks..."
.\.venv\Scripts\pre-commit install --install-hooks

# Run pre-commit once across the repo
Write-Host "Running pre-commit on all files (this may autofix some issues)..."
.\.venv\Scripts\pre-commit run --all-files

Write-Host "Bootstrap complete."
