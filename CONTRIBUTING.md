# Contributing to Tidewatch

Thanks for your interest in contributing to Tidewatch!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/tidewatch.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test locally
6. Commit: `git commit -m "Add your feature"`
7. Push: `git push origin feature/your-feature-name`
8. Open a Pull Request

## Development Setup

See the [Development section](README.md#development) in the README for setup instructions.

## Code Style

### Backend (Python)
- Follow PEP 8 guidelines
- Use `black` for code formatting
- Use type hints where appropriate
- Keep functions focused and under 50 lines when possible
- Use async/await for database operations

**Example:**
```python
async def get_container_or_404(
    container_id: int,
    db: AsyncSession
) -> Container:
    """Get container or raise 404 if not found."""
    container = await db.get(Container, container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    return container
```

### Frontend (React/TypeScript)
- Use TypeScript for all new components
- Use Prettier with default settings
- Follow React hooks best practices
- Use functional components (no class components)
- Keep components under 300 lines (split if larger)

**Component naming:**
```typescript
// PascalCase for components
export default function ContainerCard() { ... }

// camelCase for functions and variables
const handleUpdate = () => { ... }
```

## Testing

All contributions should include appropriate tests:

### Backend Testing

**Running Tests**:
```bash
cd backend
pytest --cov=app --cov-report=term
```

**Test Types**:
- **Unit Tests**: Test individual functions and classes
- **Integration Tests**: Test API endpoints and database operations
- **Security Tests**: Test authentication, encryption, input validation

**Test Naming Convention**:
- `test_<action>_<expected_outcome>`
- Example: `test_password_hashing_produces_different_hashes_each_time`

**Adding New Tests**:
1. Create test file in `backend/tests/` matching module name (`test_<module>.py`)
2. Use AAA pattern (Arrange, Act, Assert)
3. Use existing fixtures from `conftest.py` (db, client, authenticated_client)
4. Add skip decorators with clear reasons if infrastructure needed

**Coverage Requirements**:
- Security modules (auth, encryption, validation): >90%
- Core business logic (update engine, dependency manager): >85%
- API endpoints: >80%
- Services (notifications, schedulers): >60%

### Frontend Testing

**Running Tests**:
```bash
cd frontend
npm test              # Run all tests
npm run test:coverage # Generate coverage report
npm run test:ui       # Run with UI
```

**Test Libraries**:
- Vitest for test runner
- React Testing Library for component tests
- jsdom for DOM environment

**Coverage Requirements**:
- Components: >80%
- Utilities: >90%
- API clients: >75%

### Before Submitting PR

1. Run full test suite: `pytest` (backend) and `npm test` (frontend)
2. Check coverage hasn't decreased
3. Add tests for new features
4. Update test documentation if new patterns introduced

---

### Styling (Tailwind CSS 4.x)

Tidewatch uses **Tailwind CSS 4.x with `@theme`** for automatic light/dark mode theming based on system preference.

**Important conventions:**

#### 1. Use Semantic Theme Variables (Not Raw Colors)

```jsx
/* ✅ Correct - uses theme variables */
<div className="bg-tide-surface text-tide-text border-tide-border">

/* ❌ Wrong - hardcoded colors break dark mode */
<div className="bg-gray-800 text-white border-gray-700">
```

#### 2. Theme Variable Reference

**Background Colors:**
- `bg-tide-bg` - Main background
- `bg-tide-surface` - Card/panel background
- `bg-tide-surface-light` - Elevated surface
- `bg-tide-muted` - Muted/disabled background

**Text Colors:**
- `text-tide-text` - Primary text
- `text-tide-text-muted` - Secondary/muted text

**Border Colors:**
- `border-tide-border` - Standard borders

**Accent Colors:**
- `bg-primary-*` / `text-primary-*` - Primary actions (blue scale, 50-900)
- `bg-success-*` / `text-success-*` - Success states (green, 500-700)
- `bg-warning-*` / `text-warning-*` - Warning states (amber, 500-700)
- `bg-danger-*` / `text-danger-*` - Error/danger states (red, 500-700)

**Pre-built Component Classes:**
- `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`
- `.input`, `.card`
- `.badge`, `.badge-success`, `.badge-warning`, `.badge-danger`, `.badge-neutral`

#### 3. Dark Mode is Automatic

Theme variables automatically adapt based on system preference. **Never use `dark:` modifier** unless you need behavior different from the theme.

System preference detection happens automatically - no manual toggle needed.

#### 4. Adding New Theme Variables

If you need to add new colors:

1. Add to `@theme` block in `src/index.css`
2. Add light mode override in `html.light` block
3. Use semantic naming (describe purpose, not color)

#### 5. Responsive Design

- Mobile-first approach (base styles for mobile, scale up)
- Use Tailwind breakpoints: `sm:` (640px), `md:` (768px), `lg:` (1024px), `xl:` (1280px)
- Custom breakpoint: `xs:` (475px)
- Test on mobile, tablet, and desktop viewports

### Commits

Use conventional commit format:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, no logic change)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

**Examples:**
```bash
git commit -m "feat: add container auto-restart configuration"
git commit -m "fix: correct resource usage tracking for stopped containers"
git commit -m "docs: update OIDC authentication examples"
git commit -m "style: apply theme variables to settings page"
```

## Testing

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## Bug Reports

Use [GitHub Issues](https://github.com/homelabforge/tidewatch/issues) with:
- Clear description of the issue
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Docker version, browser, light/dark mode)
- Screenshots (if UI-related)

## Feature Requests

Open a [GitHub Discussion](https://github.com/homelabforge/tidewatch/discussions) to propose new features before implementing them.

## Questions?

Ask in [GitHub Discussions](https://github.com/homelabforge/tidewatch/discussions).
