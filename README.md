# TideWatch

**Intelligent Docker Container Update Management**

TideWatch is a comprehensive Docker container update manager that provides real-time monitoring, intelligent scheduling, automated restarts, and seamless integration with multiple notification services. Keep your Docker containers up-to-date while maintaining security and stability across your homelab.

[![Docker Build](https://github.com/homelabforge/tidewatch/actions/workflows/docker-build.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/docker-build.yml)
[![CodeQL](https://github.com/homelabforge/tidewatch/actions/workflows/codeql.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-3.4.0-green.svg)](https://github.com/homelabforge/tidewatch/releases)
[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/tidewatch/pkgs/container/tidewatch)
[![Python 3.14+](https://img.shields.io/badge/Python-3.14+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)

🌐 **[Website](https://homelabforge.io/builds/tidewatch/)** | 📖 **[Documentation](https://github.com/homelabforge/tidewatch/wiki)** | 💬 **[Discussions](https://github.com/homelabforge/tidewatch/discussions)**

---

## Features

### Core Functionality
- **Real-time Container Monitoring** - Track all running containers with live status updates (SSE)
- **Intelligent Update Management** - Schedule updates with dependency ordering and retry logic
- **Auto-Restart with Backoff** - Automatically restart failed containers with exponential backoff
- **My Projects Auto-Discovery** - Detect and track development containers
- **HTTP Server Detection** - Automatically discover web interfaces
- **Update History** - Complete audit trail of all container updates and events
- **Rollback Capabilities** - Safely revert to previous versions when needed
- **Update Windows** - Schedule updates during maintenance windows

### Dependency Tracking
- **Application Dependencies** - Track npm, PyPI, Composer, Cargo, and Go module versions
- **Dockerfile Base Images** - Monitor base image updates for custom containers
- **Dependency Ordering** - Intelligent update sequencing based on container dependencies
- **Vulnerability Awareness** - Track outdated dependencies and security issues

### Notifications (7 Services)
- **Gotify** - Self-hosted push notifications
- **Pushover** - Mobile push notifications
- **Slack** - Team chat integration
- **Discord** - Community platform notifications
- **Telegram** - Instant messaging alerts
- **Email (SMTP)** - Traditional email notifications
- **ntfy** - Simple HTTP-based push notifications

### Authentication & Security
- **Local JWT Authentication** - Argon2id password hashing with secure sessions
- **OIDC/SSO Support** - Enterprise authentication (Authentik, Authelia, Keycloak, Google, Microsoft)
- **Database Encryption** - AES-128 encryption for 14 sensitive fields (v3.4.0)
- **Path Injection Protection** - Comprehensive input sanitization
- **SSRF Protection** - Webhook URL validation
- **Log Injection Prevention** - Secure logging with data masking
- **CSRF Protection** - Session-based double-submit pattern
- **Rate Limiting** - 60 requests/minute per IP

### User Experience
- **Light/Dark Theme** - Automatic system preference detection
- **Responsive Design** - Mobile-first interface with Tailwind CSS v4
- **Real-time Updates** - Server-Sent Events (SSE) for live dashboard
- **Export & Backup** - Configuration and history exports with CSV support
- **Comprehensive API** - RESTful API with OpenAPI/Swagger documentation

---

## Technology Stack

### Backend
- **Python 3.14+** - Modern Python with latest async features
- **FastAPI 0.121.2** - High-performance async web framework
- **Granian 2.5.7** - Rust-based ASGI server for optimal performance
- **SQLAlchemy 2.0.44** - Advanced async ORM with SQLite (WAL mode)
- **APScheduler 3.11.1** - Robust task scheduling and orchestration
- **Docker SDK 7.1.0** - Official Docker API client
- **Authlib 1.4.0** - OIDC/OAuth2 authentication
- **Cryptography 44.0.0** - Field-level database encryption
- **Pydantic 2.12.0** - Data validation and settings management

### Frontend
- **React 19.2** - Latest React with concurrent features
- **TypeScript 5.9.3** - Type-safe JavaScript
- **Vite 7.2.2** - Lightning-fast build tool
- **Tailwind CSS 4.1.17** - Utility-first CSS framework with automatic theming
- **React Router 7.10.1** - Modern routing solution
- **Recharts 3.5.1** - Composable charting library
- **Lucide React 0.556.0** - Beautiful icon library (1,647 icons)

---

## Quick Start

### Docker Compose (Recommended)

```yaml
services:
  tidewatch:
    image: ghcr.io/homelabforge/tidewatch:latest
    container_name: tidewatch
    ports:
      - "8788:8788"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - tidewatch-data:/data
    restart: unless-stopped

volumes:
  tidewatch-data:
```

**That's it!** TideWatch auto-generates all secrets on first startup and stores them in `/data/` for persistence.

### Docker Run

```bash
docker run -d \
  --name tidewatch \
  -p 8788:8788 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v tidewatch-data:/data \
  ghcr.io/homelabforge/tidewatch:latest
```

### Access the Application

Once running, access TideWatch at: **`http://localhost:8788`**

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `DATABASE_URL` | `sqlite+aiosqlite:////data/tidewatch.db` | Database connection string |
| `TIDEWATCH_ENCRYPTION_KEY` | *Optional* | Fernet key for database encryption. If not set, sensitive settings stored in plain text with warning. Auto-generated secrets in `/data/` are always used. |
| `TIDEWATCH_DEBUG` | `false` | Enable debug mode (shows stack traces in API responses) |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker socket connection |
| `CORS_ORIGINS` | Localhost ports | Allowed CORS origins (comma-separated). Default: localhost development ports. Set to production domain(s) when deploying. |
| `CSRF_SECURE_COOKIE` | `false` | Require HTTPS for cookies (enable in production) |

### Authentication Configuration

TideWatch supports three authentication modes:

#### 1. No Authentication (Default)
⚠️ **Not recommended for production**. Suitable for local testing only.

#### 2. Local JWT Authentication
Configure via Settings → System in the web UI:
1. Change Authentication Mode to "Local"
2. Set admin password
3. Log in with credentials

#### 3. OIDC/SSO Authentication (v3.2.0+)
Enterprise SSO with popular providers:

**Supported Providers:**
- Authentik
- Authelia
- Keycloak
- Google Workspace
- Microsoft Entra ID (Azure AD)
- GitHub

**Setup Example (Authentik):**
```yaml
environment:
  - OIDC_PROVIDER_URL=https://authentik.example.com/application/o/tidewatch/
  - OIDC_CLIENT_ID=your-client-id
  - OIDC_CLIENT_SECRET=your-client-secret
  - OIDC_REDIRECT_URI=https://tidewatch.example.com/api/auth/oidc/callback
```

See [Authentication Wiki](https://github.com/homelabforge/tidewatch/wiki/Authentication) for detailed provider setup guides.

### Notification Services

Configure up to 7 notification services simultaneously via Settings → Notifications:

| Service | Configuration Required |
|---------|----------------------|
| **Gotify** | Server URL, App Token |
| **Pushover** | User Key, App Token |
| **Slack** | Webhook URL |
| **Discord** | Webhook URL |
| **Telegram** | Bot Token, Chat ID |
| **Email** | SMTP Server, Port, Username, Password |
| **ntfy** | Topic URL |

Notifications are sent for:
- Container updates (success/failure)
- Auto-restart events
- Dependency update detection
- System errors and warnings

---

## Database

### SQLite (Default)
Zero-configuration database with Write-Ahead Logging (WAL) for optimal performance.

**Backup:**
```bash
docker exec tidewatch sqlite3 /data/tidewatch.db ".backup /data/tidewatch-backup.db"
```

### PostgreSQL (Optional)
For advanced deployments:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: tidewatch
      POSTGRES_USER: tidewatch
      POSTGRES_PASSWORD: secure-password
    volumes:
      - postgres-data:/var/lib/postgresql/data

  tidewatch:
    image: ghcr.io/homelabforge/tidewatch:latest
    environment:
      - DATABASE_URL=postgresql+asyncpg://tidewatch:secure-password@postgres:5432/tidewatch
```

**Backup:**
```bash
docker exec postgres pg_dump -U tidewatch tidewatch > tidewatch-backup.sql
```

---

## Reverse Proxy Setup

### Traefik

```yaml
services:
  tidewatch:
    image: ghcr.io/homelabforge/tidewatch:latest
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.tidewatch.rule=Host(`tidewatch.example.com`)"
      - "traefik.http.routers.tidewatch.entrypoints=websecure"
      - "traefik.http.routers.tidewatch.tls.certresolver=letsencrypt"
      - "traefik.http.services.tidewatch.loadbalancer.server.port=8788"
```

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name tidewatch.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8788;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support for real-time updates
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

---

## API Documentation

TideWatch provides a comprehensive REST API with automatic OpenAPI documentation.

- **API Docs (Swagger)**: `http://localhost:8788/docs`
- **API Redoc**: `http://localhost:8788/redoc`
- **OpenAPI Schema**: `http://localhost:8788/openapi.json`

### Key Endpoints

**Health & System:**
- `GET /health` - Health check endpoint
- `GET /api/system/version` - System version info
- `GET /api/events` - Server-Sent Events stream

**Containers:**
- `GET /api/containers` - List all containers
- `GET /api/containers/{id}` - Container details
- `GET /api/containers/{id}/history` - Update history
- `GET /api/containers/{id}/logs` - Container logs
- `POST /api/containers/{id}/restart` - Restart container

**Updates:**
- `POST /api/updates/trigger` - Trigger container update
- `GET /api/updates/check` - Check for available updates
- `GET /api/history` - Update history

**Dependencies:**
- `GET /api/dependencies` - List all tracked dependencies
- `GET /api/dependencies/check` - Check for dependency updates

**Settings:**
- `GET /api/settings` - Get all settings
- `PUT /api/settings` - Update settings

**Authentication:**
- `POST /api/auth/login` - Local authentication
- `GET /api/auth/oidc/login` - OIDC flow initiation
- `GET /api/auth/oidc/callback` - OIDC callback
- `POST /api/auth/logout` - Logout

---

## Security

### v3.4.0 Security Enhancements

TideWatch v3.4.0 addresses 9 critical security vulnerabilities with comprehensive protections:

1. **Database Encryption** - 14 sensitive fields encrypted with Fernet (AES-128)
   - Notification tokens, webhook URLs, SMTP passwords, OIDC secrets
   - Optional: Set `TIDEWATCH_ENCRYPTION_KEY` to enable (gracefully falls back to plain text with warning)

2. **Path Injection Protection** - `sanitize_path()` utility validates all file paths
   - Prevents directory traversal attacks
   - Blocks absolute paths and parent directory references

3. **SSRF Protection** - Webhook URL validation
   - Blocks private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
   - Prevents metadata service access (169.254.169.254)
   - Validates URL schemes (http/https only)

4. **Log Injection Prevention** - `sanitize_log_message()` removes control characters
   - Prevents log forgery and injection attacks

5. **Sensitive Data Masking** - Automatic masking in logs
   - Shows only last 4 characters of tokens/keys
   - Protects credentials in error messages

6. **Stack Trace Control** - Production vs debug mode
   - Set `TIDEWATCH_DEBUG=false` in production to hide stack traces

### Additional Security Features

- **🔐 Argon2id Hashing** - Industry-standard password hashing
- **🛡️ CSRF Protection** - Session-based double-submit pattern
- **⏱️ Rate Limiting** - 60 requests/minute per IP
- **✅ Input Validation** - Pydantic schema validation
- **📋 Security Headers** - HSTS, CSP, X-Frame-Options, X-Content-Type-Options

### Production Security Checklist

```bash
# Enable production mode
export TIDEWATCH_DEBUG=false
export CSRF_SECURE_COOKIE=true
export CORS_ORIGINS="https://tidewatch.yourdomain.com"

# Optional: Enable database encryption for sensitive fields
# export TIDEWATCH_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Use HTTPS with reverse proxy
# Enable authentication (Local or OIDC)
# Regular backups of database
```

---

## Troubleshooting

### Common Issues

| Issue | Quick Fix |
|-------|-----------|
| **Container won't start** | Check Docker socket permissions: `sudo chmod 666 /var/run/docker.sock` |
| **Updates not detected** | Verify Docker socket mount: `-v /var/run/docker.sock:/var/run/docker.sock:ro` |
| **OIDC login fails** | Verify redirect URI matches provider configuration exactly |
| **Notifications not sending** | Test notification in Settings → Notifications → Test button |
| **Database locked errors** | Ensure only one TideWatch instance is running |

See [Troubleshooting Wiki](https://github.com/homelabforge/tidewatch/wiki/Troubleshooting) for detailed diagnostics and solutions.

---

## Upgrading

### Upgrading to v3.4.0 (Security Enhancements)

**✅ Simple Upgrade**: No configuration changes required! TideWatch auto-generates all secrets.

```bash
# 1. Backup database (recommended)
docker cp tidewatch:/data/tidewatch.db ./tidewatch-backup.db

# 2. Pull latest image and restart
docker compose pull
docker compose up -d

# 3. Verify logs for successful migration
docker logs tidewatch
```

**Optional**: To enable database encryption for sensitive settings (notification tokens, passwords), set `TIDEWATCH_ENCRYPTION_KEY`. Without it, sensitive settings are stored in plain text (logged as warning).

See [Upgrading Wiki](https://github.com/homelabforge/tidewatch/wiki/Upgrading) for version-specific migration guides.

---

## Development

### Prerequisites
- Python 3.14+
- Node.js 20+
- Docker

### Backend Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Run development server
granian --interface asgi --host 0.0.0.0 --port 8788 --reload app.main:app
```

### Frontend Setup

```bash
# Install dependencies
cd frontend
npm install

# Run development server
npm run dev
```

Frontend will run on `http://localhost:5173` and proxy API requests to backend.

### Testing

TideWatch includes comprehensive test coverage for security-critical modules and core business logic.

#### Test Results (Current)
- **Total**: 801 tests
- **Passing**: 531 (66%)
- **Failing**: 166 (service mocking required)
- **Skipped**: 104 (documented)
- **Errors**: 0 ✓
- **Coverage**: ~20% (focused on security modules: 95%+)

#### Running Backend Tests

```bash
cd backend

# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test module
pytest tests/test_auth.py -v

# Run only security tests
pytest tests/test_*.py -k security -v
```

**Test Environment Variables**:
- `TIDEWATCH_TESTING=true` - Disables rate limiting middleware during tests (prevents false failures)
- `TIDEWATCH_ENCRYPTION_KEY` - Required for encryption tests (auto-generated if not set)

#### Test Infrastructure

**Key Fixtures** (see `backend/tests/conftest.py`):
- `db` - Async test database session with automatic rollback
- `client` - Unauthenticated HTTP client (auth_mode='none')
- `authenticated_client` - Client with admin JWT token
- `admin_user` - Pre-created test user account
- `mock_docker_client` - Mock Docker API responses
- `mock_event_bus` - Mock SSE event system

#### Running Frontend Tests

```bash
cd frontend

# Run tests
npm test

# Run with coverage
npm run test:coverage

# Run in watch mode
npm run test:ui
```

#### Test Coverage by Module

| Module | Coverage | Status |
|--------|----------|--------|
| Security (auth, encryption, validation) | 95%+ | ✅ Excellent |
| Core Business Logic | 85%+ | ✅ Good |
| API Endpoints | 52% | ⚠️ In Progress |
| Services (notifications, schedulers) | 0-20% | 🔄 Planned |

**Note**: Current focus is on security-critical paths. Service module coverage is planned for future phases.

---

## Architecture

### System Components

```
┌─────────────────┐
│   React SPA     │  Frontend (Vite + React 19)
│  (Tailwind v4)  │  Light/Dark Theme + SSE
└────────┬────────┘
         │ HTTP/REST + SSE
┌────────▼────────┐
│ FastAPI+Granian │  Backend (Python 3.14)
│   OIDC/JWT Auth │  Argon2id + Encryption
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
┌───▼──┐  ┌──▼───────┐
│SQLite│  │Docker API│
│ WAL  │  │  Events  │
└──────┘  └──────────┘
```

### Key Design Decisions

- **Single Worker** - APScheduler requires single-worker for state consistency
- **Async-First** - All I/O operations use async/await for maximum concurrency
- **WAL Mode SQLite** - Write-Ahead Logging for better read/write performance
- **Granian ASGI** - Rust-based server for 15-20% memory reduction vs uvicorn
- **Field Encryption** - Fernet encryption for sensitive database fields
- **SSE for Real-time** - Server-Sent Events for live dashboard updates

---

## Performance

### Metrics (v3.4.0)

- **Startup Time**: ~1.2 seconds
- **Memory Usage**: ~150-170 MiB (with Granian)
- **API Response Time**: <100ms average (67 containers)
- **Health Check Latency**: <5ms
- **Frontend Bundle**: ~500KB (gzipped)
- **Database**: ~15MB (100 containers, 30 days history)

### Optimizations

- Route-based code splitting for faster initial load
- Efficient async database queries with connection pooling
- Memoized component rendering to reduce re-renders
- Vendor chunk splitting for better browser caching
- WAL mode for concurrent read/write performance

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

### Recent Major Releases

**v3.4.0** (2025-12-06) - **Security Release**
- 🔒 9 critical security fixes (path injection, SSRF, log injection)
- 🔐 Database field encryption for 14 sensitive fields
- 🛡️ Comprehensive input sanitization and validation
- 📋 Sensitive data masking in logs

**v3.2.0** (2025-11-20)
- 🔑 OIDC/SSO authentication support
- 🌐 Multi-provider SSO (Authentik, Authelia, Keycloak, Google, Microsoft)

**v3.1.0** (2025-11-15)
- 🔔 Multi-service notifications (7 services)
- 📧 Email, Telegram, Discord, Slack, Gotify, Pushover, ntfy

**v2.9.0** (2025-11-10)
- 🎨 Light/Dark theme support with automatic detection

**v2.8.0** (2025-11-05)
- 📦 Dockerfile base image tracking
- 🌐 HTTP server auto-detection

**v2.6.0** (2025-10-28)
- 📊 Application dependency tracking (npm, PyPI, Composer, Cargo, Go)

**v2.3.0** (2025-10-15)
- 🔄 Auto-restart with exponential backoff
- ⏰ Update window scheduling
- 🔗 Container dependency management

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Contribution Steps

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes following code style guidelines
4. Test your changes: `pytest` (backend) and `npm test` (frontend)
5. Commit: `git commit -m 'feat: Add amazing feature'`
6. Push: `git push origin feature/amazing-feature`
7. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- Built for homelabbers and self-hosted enthusiasts
- AI-assisted development with Claude and Codex
- Part of the [HomelabForge](https://homelabforge.io) ecosystem
- Inspired by modern container orchestration needs

---

## Support & Community

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/homelabforge/tidewatch/issues)
- 📖 **Documentation**: [Wiki](https://github.com/homelabforge/tidewatch/wiki)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/homelabforge/tidewatch/discussions)
- 🌐 **Website**: [homelabforge.io/builds/tidewatch](https://homelabforge.io/builds/tidewatch/)
- 🔒 **Security**: [SECURITY.md](SECURITY.md)

---

**TideWatch** - Stay ahead of the update tide 🌊
