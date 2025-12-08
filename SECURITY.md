# Security Features

TideWatch implements comprehensive security measures to protect your container infrastructure.

## Table of Contents

1. [Authentication & Authorization](#authentication--authorization)
2. [CSRF Protection](#csrf-protection)
3. [Rate Limiting](#rate-limiting)
4. [Input Validation](#input-validation)
5. [Encryption](#encryption)
6. [Security Headers](#security-headers)
7. [Security Best Practices](#security-best-practices)
8. [Reporting Security Issues](#reporting-security-issues)

## Authentication & Authorization

### Password-Based Authentication

TideWatch uses Argon2id for password hashing, providing strong protection against brute-force attacks.

**Configuration:**
- Passwords are hashed using Argon2id with time cost=3, memory cost=64MB, parallelism=4
- Minimum password length: 8 characters
- Passwords are salted automatically

**Setup:**
```bash
# Create first user (admin)
curl -X POST http://localhost:8788/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "email": "admin@example.com", "password": "YourSecurePassword123!"}'
```

### Session Management

- Sessions use secure, HTTP-only cookies
- Session timeout: 24 hours
- Sessions are invalidated on logout

## CSRF Protection

Cross-Site Request Forgery (CSRF) protection is enabled by default.

### How it Works

1. **Token Generation**: Server generates a unique CSRF token per session
2. **Token Storage**: Token stored in:
   - Server-side session (secure)
   - HTTP-only cookie (XSS protection)
   - Response header `X-CSRF-Token` (for client storage)
3. **Token Validation**: All state-changing requests (POST, PUT, DELETE, PATCH) must include:
   - CSRF token in `X-CSRF-Token` header
   - Valid session cookie

### Client Implementation

```javascript
// Fetch CSRF token on app load
const response = await fetch('/api/v1/containers');
const csrfToken = response.headers.get('X-CSRF-Token');

// Include in subsequent requests
await fetch('/api/v1/containers/1', {
  method: 'PUT',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrfToken
  },
  body: JSON.stringify({policy: 'auto'})
});
```

### Configuration

```bash
# Environment variables
CSRF_SECURE_COOKIE=true  # Set to true in production with HTTPS
```

**Note**: Session secrets are auto-generated on first startup and saved to `/data/session_secret.key`.

## Rate Limiting

Rate limiting prevents API abuse and DoS attacks.

**Default Limits:**
- 60 requests per minute per IP address
- Applies to all API endpoints
- Returns 429 (Too Many Requests) when exceeded

**Response Headers:**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
```

**Exempted Endpoints:**
- `/health` - Health check
- `/metrics` - Prometheus metrics

## Input Validation

All user inputs are validated to prevent injection attacks.

### Container Name Validation

- Maximum length: 255 characters
- Allowed characters: `a-z A-Z 0-9 _ - .`
- Blocked patterns: `;`, `&&`, `|`, `` ` ``, `$()`, `../`

### Compose File Path Validation

- Must be within `/compose` directory
- Path traversal attempts blocked (`../`, symlinks outside base)
- Absolute paths validated

### Docker Command Validation

- Only allows `docker compose` or `docker-compose`
- Command injection patterns blocked
- Arguments validated

### Example: Blocked Attacks

```bash
# Command injection attempts (BLOCKED)
container_name="test; rm -rf /"
container_name="test && whoami"
container_name="test | cat /etc/passwd"

# Path traversal attempts (BLOCKED)
compose_file="/compose/../../etc/passwd"
compose_file="/compose/../../../root/.ssh/id_rsa"
```

## Encryption

### Database Field Encryption (v3.4.0+)

**Optional Feature**: Sensitive data (API keys, passwords, tokens, webhooks) can be encrypted at rest using Fernet (AES-128 in CBC mode with HMAC authentication).

**How It Works:**
- **With encryption key**: Sensitive fields are encrypted in the database
- **Without encryption key**: Sensitive fields stored in plain text (warning logged)
- **Auto-generated secrets**: JWT and session secrets are always auto-generated and stored in `/data/` (never in environment)

**Enable Encryption (Optional):**
```bash
# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Set in environment or .env file
export TIDEWATCH_ENCRYPTION_KEY=<generated-key>
```

**Fields That Can Be Encrypted (14 total):**
- Registry tokens: `dockerhub_token`, `ghcr_token`
- VulnForge: `vulnforge_api_key`, `vulnforge_password`
- Notifications: `ntfy_token`, `gotify_token`, `pushover_user_key`, `pushover_api_token`, `telegram_bot_token`
- Webhooks: `slack_webhook_url`, `discord_webhook_url` (may contain embedded secrets)
- Email: `email_smtp_password`
- OIDC: `oidc_client_secret`
- Admin: `admin_password_hash` (already Argon2id hashed)

**Important Notes:**
- Encryption happens automatically when you update settings through the UI or API
- Existing plain-text values must be re-saved to encrypt them (migration only marks fields)
- Without `TIDEWATCH_ENCRYPTION_KEY`, sensitive fields are stored in plain text (warning logged)
- Losing the encryption key makes encrypted data **irrecoverable** - backup your key securely

## SSRF Protection (v3.4.0+)

Server-Side Request Forgery (SSRF) protection prevents malicious actors from using webhook/notification URLs to access internal network resources.

**Protected Services:**
- Slack webhook URLs
- Discord webhook URLs
- ntfy server URLs
- Gotify server URLs
- OIDC provider URLs

**Protection Mechanisms:**
- Blocks private IP ranges (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Blocks loopback addresses (127.0.0.0/8, ::1)
- Blocks link-local addresses (169.254.0.0/16)
- Blocks cloud metadata services (169.254.169.254)
- Validates DNS to prevent DNS rebinding attacks
- Checks IDN (Internationalized Domain Names) for homograph attacks

**Configuration by Service:**
```python
# Public webhooks (Slack, Discord) - Strict validation
- Requires HTTPS
- Blocks private IPs

# Self-hosted services (ntfy, Gotify) - Flexible validation
- Allows HTTP and HTTPS
- Allows private IPs (for self-hosted instances)
- Allows localhost/IP addresses
```

## Path Traversal Protection (v3.4.0+)

All file operations are validated to prevent path traversal attacks.

**Protected Paths:**
- Database path (`DATABASE_URL`)
- JWT secret key file (`/data/secret.key`)
- Session secret file (`/data/session_secret.key`)
- Compose directory (`compose_directory` setting)
- Projects directory (`projects_directory` setting)
- Dockerfile locations

**Validation:**
- Paths resolved to absolute form
- Symlinks optionally rejected
- Paths must be within allowed base directories:
  - `/data` - Database and secrets
  - `/compose` - Docker Compose files
  - `/projects` - Project source code
  - `/tmp` - Testing (development only)

## Log Injection Prevention (v3.4.0+)

User-controlled data is sanitized before logging to prevent log injection attacks.

**Sanitized Inputs:**
- Container names
- Image names and tags
- File paths
- Error messages
- API request parameters

**Protection:**
- Removes newline characters (`\n`, `\r`)
- Removes tab characters (`\t`)
- Removes control characters (0x00-0x1f, 0x7f-0x9f)

## Stack Trace Protection (v3.4.0+)

Detailed error information is hidden from API responses in production to prevent information leakage.

**Configuration:**
```bash
# Development mode - shows detailed errors
export TIDEWATCH_DEBUG=true

# Production mode - shows generic errors (DEFAULT)
export TIDEWATCH_DEBUG=false
```

**Behavior:**
- **Production** (`TIDEWATCH_DEBUG=false`): Returns generic "Internal error occurred" message
- **Development** (`TIDEWATCH_DEBUG=true`): Returns full error details and stack traces
- **Internal Logging**: Full details always logged internally regardless of mode

## Security Headers

TideWatch automatically adds security headers to all responses:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains (HTTPS only)
Content-Security-Policy: default-src 'self'; ...
```

## Security Best Practices

### Production Deployment

1. **Enable HTTPS**
   ```yaml
   # docker-compose.yml
   environment:
     CSRF_SECURE_COOKIE: "true"
   labels:
     - "traefik.http.routers.tidewatch.tls=true"
   ```

2. **Set Strong Session Secret**
   ```bash
   export SESSION_SECRET_KEY=$(openssl rand -base64 64)
   ```

3. **Configure CORS**
   ```bash
   # Restrict to your domain
   export CORS_ORIGINS="https://tidewatch.yourdomain.com"
   ```

4. **Use Encryption Key**
   ```bash
   export ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
   ```

5. **Limit Docker Socket Access**
   ```yaml
   # Use socket proxy (recommended)
   environment:
     DOCKER_HOST: tcp://socket-proxy-rw:2375
   ```

### Network Security

- **Never expose port directly to internet**
- **Use reverse proxy (Traefik, Nginx)**
- **Enable TLS/SSL**
- **Consider VPN or Tailscale for remote access**

### Docker Security

```yaml
services:
  tidewatch:
    security_opt:
      - no-new-privileges:true
    read_only: false  # Needs write for /data
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - SETGID
      - SETUID
```

### Monitoring

- Review security logs in `/data/security.log`
- Monitor failed authentication attempts
- Set up alerts for rate limit violations

## Reporting Security Issues

If you discover a security vulnerability, please report it via:
- **GitHub Security Advisories:** https://github.com/homelabforge/tidewatch/security/advisories/new
- **Response Time:** Within 48 hours
- **Disclosure:** Coordinated disclosure preferred

**Please do NOT:**
- Open public GitHub issues for security vulnerabilities
- Exploit vulnerabilities on production systems

## Security Checklist

Before deploying to production:

- [ ] HTTPS enabled with valid certificate
- [ ] `CSRF_SECURE_COOKIE=true` set
- [ ] Strong `SESSION_SECRET_KEY` configured
- [ ] `ENCRYPTION_KEY` generated and set
- [ ] CORS restricted to your domain
- [ ] Rate limiting enabled
- [ ] Docker socket access restricted (socket proxy)
- [ ] Security headers verified
- [ ] Authentication enabled
- [ ] Regular backups configured
- [ ] Security logging enabled
- [ ] Monitoring and alerting set up

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
