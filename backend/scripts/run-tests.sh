#!/usr/bin/env bash
# Run the TideWatch backend test suite in a Python 3.14 container.
#
# The host runs 3.13; tests target 3.14. The production image has no
# pytest. This script bridges that gap with a dedicated test image
# (Dockerfile.test).
#
# Usage:
#   bin/run-tests.sh                    # full suite
#   bin/run-tests.sh tests/test_foo.py  # subset
#   bin/run-tests.sh -k self_managed    # filter
#   bin/run-tests.sh --build            # force rebuild test image first
#
# The docker socket is mounted so tests that exercise `docker inspect`
# / `docker ps` (e.g. _check_container_runtime) work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="tidewatch-test:local"

build=0
args=()
for arg in "$@"; do
  case "$arg" in
    --build) build=1 ;;
    *) args+=("$arg") ;;
  esac
done

# Build if explicitly requested or image doesn't exist
if [[ "$build" -eq 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE..."
  docker build -t "$IMAGE" -f "$BACKEND_DIR/Dockerfile.test" "$BACKEND_DIR"
fi

cmd=(pytest --no-cov)
if [[ "${#args[@]}" -gt 0 ]]; then
  cmd+=("${args[@]}")
fi

docker run --rm \
  -v "$BACKEND_DIR:/app" \
  -w /app \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e PYTHONPATH=/app \
  "$IMAGE" "${cmd[@]}"
