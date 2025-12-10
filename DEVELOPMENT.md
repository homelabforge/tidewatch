# Development Guide

## Prerequisites

### Bun Installation

TideWatch uses [Bun](https://bun.sh) as the JavaScript runtime for the frontend.

**Install Bun:**
```bash
curl -fsSL https://bun.sh/install | bash
```

**Verify installation:**
```bash
bun --version  # Should be 1.3.4 or higher
```

### Other Requirements
- **Python:** 3.14+
- **Docker:** 24.0+ with Compose plugin

## Frontend Development

### Setup
```bash
cd frontend
bun install
```

### Development Server
```bash
bun dev  # Starts on http://localhost:5173
```

### Building
```bash
bun run build  # Production build
```

### Testing
```bash
bun test          # Run tests in watch mode
bun test --run    # Run tests once
bun test --ui     # Open test UI
bun run test:coverage  # Generate coverage report
```

### Code Quality
```bash
bun run lint       # Run ESLint
bun run type-check # TypeScript type checking
```

## Backend Development

### Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### Running
```bash
python -m granian app.main:app --port 8788 --reload
```

### Testing
```bash
pytest --cov=app --cov-report=term-missing
```

## Docker Development

### Build
```bash
docker compose build
```

### Run
```bash
docker compose up -d
```

### Logs
```bash
docker compose logs -f
```

## Troubleshooting

### Bun Issues

#### "Command not found: bun"
**Solution:**
```bash
# Install Bun
curl -fsSL https://bun.sh/install | bash

# Reload shell
source ~/.bashrc  # or ~/.zshrc

# Verify
bun --version
```

#### "lockfile out of sync"
**Solution:**
```bash
# Regenerate lockfile
rm bun.lock
bun install

# Or force install
bun install --force
```

#### "Module not found" errors
**Solution:**
```bash
# Clean install
cd frontend
rm -rf node_modules bun.lock
bun install
```

#### HMR not working
**Solution:**
1. Check Vite dev server is running on port 5173
2. Check browser console for errors
3. Try hard refresh: Ctrl+Shift+R (Cmd+Shift+R on Mac)
4. Restart dev server: Ctrl+C then `bun dev`
5. Clear Vite cache: `rm -rf node_modules/.vite && bun dev`

### TypeScript Errors

If you see type errors, ensure TypeScript is up to date:
```bash
cd frontend
bun run type-check
```

### Port Already in Use

If port 8788 or 5173 is already in use:
```bash
# Find process using the port
lsof -i :8788
lsof -i :5173

# Kill the process
kill -9 <PID>
```

## Performance Tips

- Bun is 10-25x faster than npm for package installation
- Use `bun install` instead of `bun install --frozen-lockfile` during development
- HMR with Vite is instant - no need to restart dev server
- Run tests in watch mode (`bun test`) for faster feedback
