<div align="center">
  
Intelligent Docker Container Update Management

[![Docker Build](https://github.com/homelabforge/tidewatch/actions/workflows/docker-build.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/docker-build.yml)
[![CodeQL](https://github.com/homelabforge/tidewatch/actions/workflows/codeql.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/codeql.yml)
[![CI](https://github.com/homelabforge/tidewatch/actions/workflows/ci.yml/badge.svg)](https://github.com/homelabforge/tidewatch/actions/workflows/ci.yml)

[![Docker](https://img.shields.io/badge/Docker-Available-2496ED?logo=docker&logoColor=white)](https://github.com/homelabforge/tidewatch/pkgs/container/tidewatch)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Bun 1.3.4](https://img.shields.io/badge/Bun-1.3.4-000000?logo=bun&logoColor=white)](https://bun.sh)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

![TideWatch Dashboard](docs/screenshots/dashboard.png)

</div>

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


**Default Mode**: Runs with no authentication for easy setup. Configure authentication in Settings before exposing to the internet.

📖 **[Complete Installation Guide](https://github.com/homelabforge/tidewatch/wiki/Installation)**

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
