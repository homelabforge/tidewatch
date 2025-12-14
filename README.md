# TideWatch

Intelligent Docker Container Update Management

<div align="center">

[![Docker Build](https://github.com/homelabforge/tidewatch/actions/workflows/docker-build.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/docker-build.yml)
[![CodeQL](https://github.com/homelabforge/tidewatch/actions/workflows/codeql.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/codeql.yml)

[![Version](https://img.shields.io/badge/Version-3.5.4-green.svg)](https://github.com/homelabforge/tidewatch/releases)
[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/tidewatch/pkgs/container/tidewatch)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Bun 1.3.4](https://img.shields.io/badge/Bun-1.3.4-000000?logo=bun&logoColor=white)](https://bun.sh)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

![TideWatch Dashboard](docs/screenshots/dashboard.png)

</div>

**📚 [Full Documentation (Wiki)](https://github.com/homelabforge/tidewatch/wiki)** | **🌐 [Website](https://homelabforge.io/builds/tidewatch/)** | **⭐ [Star on GitHub](https://github.com/homelabforge/tidewatch)**

---

## Quick Start

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

```bash
docker compose up -d
```

Open http://localhost:8788 and start managing container updates.

**Auto-Configuration**: TideWatch auto-generates all secrets on first startup.

📖 **[Complete Installation Guide](https://github.com/homelabforge/tidewatch/wiki/Installation)**

---

## Key Features

- **Real-time Container Monitoring** - Live status updates with Server-Sent Events
- **Intelligent Update Management** - Schedule updates with dependency ordering
- **Auto-Restart with Backoff** - Exponential backoff for failed containers
- **Dependency Tracking** - Monitor npm, PyPI, Composer, Cargo, and Go modules
- **7 Notification Services** - Gotify, Pushover, Slack, Discord, Telegram, Email, ntfy
- **OIDC/SSO Support** - Enterprise authentication (Authentik, Keycloak, Google, Microsoft)
- **Database Encryption** - AES-128 encryption for sensitive fields
- **Light/Dark Theme** - Automatic system preference detection
- **Self-Hosted** - Your data stays on your infrastructure

---

## Documentation

### Getting Started
- **[Installation](https://github.com/homelabforge/tidewatch/wiki/Installation)** - Docker setup and configuration
- **[Quick Start Guide](https://github.com/homelabforge/tidewatch/wiki/Quick-Start)** - Get running in 5 minutes
- **[First Time Setup](https://github.com/homelabforge/tidewatch/wiki/First-Time-Setup)** - Initial configuration

### Features
- **[Container Monitoring](https://github.com/homelabforge/tidewatch/wiki/Container-Monitoring)** - Real-time tracking and updates
- **[Updates](https://github.com/homelabforge/tidewatch/wiki/Updates)** - Update scheduling and management
- **[Dependencies](https://github.com/homelabforge/tidewatch/wiki/Dependencies)** - Application dependency tracking
- **[Notifications](https://github.com/homelabforge/tidewatch/wiki/Notifications)** - Multi-service notification setup
- **[Dashboard](https://github.com/homelabforge/tidewatch/wiki/Dashboard)** - Overview and analytics

### Configuration
- **[Authentication](https://github.com/homelabforge/tidewatch/wiki/Authentication)** - Local, OIDC, and SSO setup
- **[Database Configuration](https://github.com/homelabforge/tidewatch/wiki/Database-Configuration)** - SQLite vs PostgreSQL
- **[Advanced Configuration](https://github.com/homelabforge/tidewatch/wiki/Advanced-Configuration)** - Environment variables and tuning

### Help
- **[FAQ](https://github.com/homelabforge/tidewatch/wiki/FAQ)** - Common questions
- **[Troubleshooting](https://github.com/homelabforge/tidewatch/wiki/Troubleshooting)** - Fix common issues
- **[Upgrading](https://github.com/homelabforge/tidewatch/wiki/Upgrading)** - Version migration guides

---

## Technology Stack

**Backend:** FastAPI (Python 3.14), Granian ASGI, SQLAlchemy 2.0, Docker SDK, Authlib
**Frontend:** React 19, TypeScript, Tailwind CSS 4, Bun 1.3.4, Vite 7.2.6

---

## Development

```bash
# Clone repository
git clone https://github.com/homelabforge/tidewatch.git
cd tidewatch

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
granian --interface asgi --host 0.0.0.0 --port 8788 --reload app.main:app

# Frontend (new terminal)
cd frontend
bun install
bun dev
```

API docs at http://localhost:8788/docs

---

## Support

- **📚 Documentation**: [GitHub Wiki](https://github.com/homelabforge/tidewatch/wiki)
- **🌐 Website**: [homelabforge.io/builds/tidewatch](https://homelabforge.io/builds/tidewatch/)
- **🐛 Bug Reports**: [GitHub Issues](https://github.com/homelabforge/tidewatch/issues)
- **💬 Discussions**: [GitHub Discussions](https://github.com/homelabforge/tidewatch/discussions)

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Acknowledgments

Built for homelabbers who want intelligent container update management without relying on third-party services.

Part of the [HomelabForge](https://homelabforge.io) ecosystem.

### Development Assistance

TideWatch was developed through AI-assisted pair programming with **Claude** and **Codex**, combining human vision with AI capabilities for architecture, security patterns, and implementation.
