#!/usr/bin/env bash
# Import a google-agents-cli wheel from PyPI into this repository.
#
# Usage: scripts/import-wheel.sh <version>
# Example: scripts/import-wheel.sh 0.1.1
#
# Steps:
#   1. Fetch wheel URL and expected SHA256 from PyPI JSON API.
#   2. Download the wheel into a temp dir.
#   3. Verify the SHA256 matches what PyPI published.
#   4. Extract the wheel.
#   5. Replace `google/` and the flattened dist-info files at repo root.
#   6. Print a suggested git commit + tag command.

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>" >&2
  exit 2
fi

VERSION="$1"
PKG="google-agents-cli"
DIST_NAME="google_agents_cli"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Fetching PyPI metadata for ${PKG}==${VERSION}"
read -r URL EXPECTED_SHA FILENAME < <(
  curl -fsSL "https://pypi.org/pypi/${PKG}/${VERSION}/json" \
    | python3 -c '
import json, sys
data = json.load(sys.stdin)
for f in data["urls"]:
    if f["filename"].endswith(".whl"):
        print(f["url"], f["digests"]["sha256"], f["filename"])
        break
else:
    sys.exit("no wheel found on PyPI")
'
)

echo "    wheel:  ${FILENAME}"
echo "    sha256: ${EXPECTED_SHA}"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "==> Downloading wheel"
curl -fsSL -o "${WORK}/${FILENAME}" "${URL}"

echo "==> Verifying SHA256"
ACTUAL_SHA="$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "${WORK}/${FILENAME}")"
if [ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]; then
  echo "SHA256 mismatch!" >&2
  echo "  expected: ${EXPECTED_SHA}" >&2
  echo "  actual:   ${ACTUAL_SHA}"   >&2
  exit 1
fi
echo "    ok"

echo "==> Extracting"
unzip -q "${WORK}/${FILENAME}" -d "${WORK}/extracted"

DIST_INFO="${WORK}/extracted/${DIST_NAME}-${VERSION}.dist-info"
if [ ! -d "${DIST_INFO}" ]; then
  echo "expected dist-info dir not found: ${DIST_INFO}" >&2
  exit 1
fi

echo "==> Replacing files in repo root"
rm -rf "${REPO_ROOT}/google"
cp -R "${WORK}/extracted/google" "${REPO_ROOT}/google"

for f in METADATA RECORD WHEEL entry_points.txt; do
  if [ -f "${DIST_INFO}/${f}" ]; then
    cp "${DIST_INFO}/${f}" "${REPO_ROOT}/${f}"
  else
    echo "    warn: ${f} not present in this wheel" >&2
  fi
done

if [ -f "${DIST_INFO}/licenses/LICENSE" ]; then
  cp "${DIST_INFO}/licenses/LICENSE" "${REPO_ROOT}/LICENSE"
fi
if [ -f "${DIST_INFO}/licenses/NOTICE" ]; then
  cp "${DIST_INFO}/licenses/NOTICE" "${REPO_ROOT}/NOTICE"
elif [ -f "${REPO_ROOT}/NOTICE" ]; then
  echo "    note: NOTICE present in repo but not in this wheel; leaving previous file in place" >&2
fi

cat <<EOF

==> Done. Suggested next steps:

    cd "${REPO_ROOT}"
    git add -A
    git status
    git commit -m "Import google-agents-cli ${VERSION} wheel contents

Source: ${URL}
SHA256: ${EXPECTED_SHA}
"
    git tag v${VERSION}
EOF
