# Environment Variables

TideWatch uses environment variables for configuration. All variables are optional unless marked as **REQUIRED**.

## Core Configuration

### `TIDEWATCH_ENCRYPTION_KEY`
- **Type**: String (Fernet key)
- **Default**: Auto-generated on first run
- **Description**: Encryption key for sensitive database fields (API keys, tokens, passwords)
- **Security**: Store securely, do not commit to version control
- **Generation**: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### `DATABASE_URL`
- **Type**: String (SQLAlchemy URL)
- **Default**: `sqlite:////data/tidewatch.db`
- **Description**: Database connection string
- **Examples**:
  - SQLite: `sqlite:////data/tidewatch.db`
  - PostgreSQL: `postgresql+asyncpg://user:pass@localhost/tidewatch`

### `TIDEWATCH_DEBUG`
- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Description**: Enable debug mode (full stack traces in API responses)
- **Production**: Should always be `false` in production

## Testing

### `TIDEWATCH_TESTING`
- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Description**: Disable rate limiting middleware during tests
- **Usage**: Set to `true` when running pytest test suite
- **Effect**: Prevents rate limiting from blocking test execution

## Authentication

### `JWT_SECRET_KEY`
- **Type**: String
- **Default**: Auto-generated from `/data/secret.key`
- **Description**: Secret key for JWT token signing
- **Security**: Auto-generated on first run, persisted to file

### `JWT_EXPIRATION_HOURS`
- **Type**: Integer
- **Default**: `24`
- **Description**: JWT token expiration time in hours

## Docker Configuration

### `DOCKER_HOST`
- **Type**: String
- **Default**: `unix:///var/run/docker.sock`
- **Description**: Docker daemon socket URL
- **Examples**:
  - Unix socket: `unix:///var/run/docker.sock`
  - TCP socket (via socket-proxy): `tcp://socket-proxy:2375`

## Paths

### `COMPOSE_DIR`
- **Type**: String
- **Default**: `/compose`
- **Description**: Base directory for docker-compose files
- **Security**: Path traversal protection enforced

### `PROJECTS_DIR`
- **Type**: String
- **Default**: `/projects`
- **Description**: Base directory for project scanning
- **Security**: Path traversal protection enforced

## Security

### `CSRF_SECURE_COOKIE`
- **Type**: Boolean (`true`/`false`)
- **Default**: `false` (development), `true` (production HTTPS)
- **Description**: Require secure CSRF cookies (HTTPS only)

### `RATE_LIMIT_PER_MINUTE`
- **Type**: Integer
- **Default**: `60`
- **Description**: API rate limit (requests per minute per IP)
- **Effect**: Disabled when `TIDEWATCH_TESTING=true`

## Example .env File

```env
# Encryption (REQUIRED for production)
TIDEWATCH_ENCRYPTION_KEY=your-fernet-key-here

# Database
DATABASE_URL=sqlite:////data/tidewatch.db

# Debug (disable in production)
TIDEWATCH_DEBUG=false

# Docker
DOCKER_HOST=tcp://socket-proxy:2375

# Paths
COMPOSE_DIR=/compose
PROJECTS_DIR=/projects

# Authentication
JWT_EXPIRATION_HOURS=24

# Security
RATE_LIMIT_PER_MINUTE=60
```

## Docker Compose Example

```yaml
services:
  tidewatch:
    image: ghcr.io/homelabforge/tidewatch:latest
    env_file:
      - .env
    environment:
      DOCKER_HOST: tcp://socket-proxy:2375
      TIDEWATCH_DEBUG: "false"
    volumes:
      - tidewatch-data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
```
