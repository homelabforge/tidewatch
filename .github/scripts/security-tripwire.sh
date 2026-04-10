#!/usr/bin/env bash
# Security tripwire: catches raw Docker SDK calls that bypass
# get_container_or_404() dependency injection in route handlers.
# Services are exempt (internal use with validated inputs).
# containers.py is allowed: its single .containers.get() uses
# container.runtime_name from the DB model after get_container_or_404.
set -euo pipefail

FOUND=0
if grep -rPn '\.containers\.(get|list|run)\(' backend/app/routes/ | grep -v 'containers.py'; then
  echo "ERROR: Found raw Docker container queries in route files."
  echo "Use get_container_or_404() instead. See: backend/app/dependencies.py"
  FOUND=1
fi
exit $FOUND
