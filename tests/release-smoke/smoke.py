"""End-to-end smoke test for TideWatch.

Run against a fresh TideWatch instance to verify the high-value paths
that unit tests can't catch:

- All migrations apply on a fresh DB (verified externally by run.sh
  via schema_migrations row count).
- Auth setup flow: POST /auth/setup creates first admin.
- Login flow: POST /auth/login returns a token.
- Settings endpoint reachable as authenticated user (validates the
  whole stack is wired — DB, auth, JSON serialization).

Usage:
    python smoke.py http://app-pg:8788
    python smoke.py http://app-sqlite:8788
"""

from __future__ import annotations

import sys

import httpx


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def main(base: str) -> int:
    fails = 0
    with httpx.Client(base_url=base, timeout=20.0, follow_redirects=True) as c:
        banner("Health check")
        r = c.get("/health")
        print(f"  GET /health -> {r.status_code}")
        if r.status_code != 200:
            print("  body:", r.text[:200])
            return 1

        banner("Setup admin (first-time)")
        r = c.post(
            "/api/v1/auth/setup",
            json={
                "username": "smoke",
                "email": "smoke@example.com",
                "password": "SmokePass123!",
                "full_name": "Smoke Test",
            },
        )
        print(f"  POST /api/v1/auth/setup -> {r.status_code}")
        if r.status_code != 201:
            print("  body:", r.text[:300])
            return 1

        banner("Login")
        r = c.post(
            "/api/v1/auth/login",
            json={"username": "smoke", "password": "SmokePass123!"},
        )
        print(f"  POST /api/v1/auth/login -> {r.status_code}")
        if r.status_code != 200:
            print("  body:", r.text[:200])
            return 1
        token = r.json().get("access_token")
        if not token:
            print("  ✗ no access_token in response")
            return 1
        print(f"  ✓ token len: {len(token)}")
        c.headers["Authorization"] = f"Bearer {token}"

        banner("Authenticated GET /api/v1/settings")
        r = c.get("/api/v1/settings")
        print(f"  GET /api/v1/settings -> {r.status_code}")
        if r.status_code != 200:
            print("  body:", r.text[:200])
            fails += 1
        else:
            data = r.json()
            print(
                f"  ✓ settings returned ({len(data) if isinstance(data, (list, dict)) else 'scalar'} entries)"
            )

    banner("RESULT")
    if fails:
        print(f"  ✗ {fails} check(s) failed")
        return 1
    print("  ✓ all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8788"))
