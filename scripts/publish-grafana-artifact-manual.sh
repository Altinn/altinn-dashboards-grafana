#!/usr/bin/env bash
set -euo pipefail

# Manually publish all grafana CRs as a Flux OCI artifact to ACR (break-glass; mirrors
# .github/workflows/publish-grafana-artifact.yml).

usage() {
  cat <<'EOF'
Usage: scripts/publish-grafana-artifact-manual.sh [options]

Publishes the repo-root kustomize aggregate (dashboards + products/*/alerting) as a
Flux OCI artifact: oci://<registry>/<repo>:<tag>. Flux pulls it via an OCIRepository
and applies the CRs into the `grafana` namespace.

Options:
  --acr-login        Run `az acr login` before pushing
  --skip-validate    Skip the local `kustomize build .` gate
  --registry <host>  OCI registry host (default: altinncr.azurecr.io)
  --repo <path>      ACR repository (default: monitoring/grafana)
  --tag <tag>        OCI tag (default: current git branch)
  --provider <name>  Flux provider (default: azure)
  --source <url>     Override OCI source annotation (default: git remote.origin.url)
  --revision <rev>   Override OCI revision annotation (default: <branch>@sha1:<commit>)
  --dry-run          Print the command without executing
  -h, --help         Show this help text

Environment overrides:
  REGISTRY           (default: altinncr.azurecr.io)
  ARTIFACT_REPO      (default: monitoring/grafana)
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: Required command '$1' not found in PATH." >&2
    exit 1
  fi
}

build_kustomize() {
  local path="$1"
  if command -v kustomize >/dev/null 2>&1; then
    kustomize build "$path" >/dev/null
    return
  fi
  if command -v kubectl >/dev/null 2>&1; then
    kubectl kustomize "$path" >/dev/null
    return
  fi
  echo "Error: Neither 'kustomize' nor 'kubectl' found in PATH." >&2
  exit 1
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

ACR_LOGIN=false
SKIP_VALIDATE=false
DRY_RUN=false

REGISTRY="${REGISTRY:-altinncr.azurecr.io}"
ARTIFACT_REPO="${ARTIFACT_REPO:-monitoring/grafana}"
TAG=""
PROVIDER="azure"
SOURCE=""
REVISION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --acr-login) ACR_LOGIN=true ;;
    --skip-validate) SKIP_VALIDATE=true ;;
    --registry) shift; REGISTRY="${1:-}" ;;
    --repo) shift; ARTIFACT_REPO="${1:-}" ;;
    --tag) shift; TAG="${1:-}" ;;
    --provider) shift; PROVIDER="${1:-}" ;;
    --source) shift; SOURCE="${1:-}" ;;
    --revision) shift; REVISION="${1:-}" ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Error: Unknown argument '$1'" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

require_cmd flux
require_cmd git

if [[ -z "${TAG}" ]]; then
  # Default to the current branch; OCI tags forbid '/', so sanitize it.
  TAG="$(git rev-parse --abbrev-ref HEAD)"
  TAG="${TAG//\//-}"
fi

if [[ ! "${TAG}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Error: '${TAG}' is not a valid OCI tag (allowed: A-Za-z0-9_.- , max 128 chars, no leading '.' or '-'). Pass --tag <tag>." >&2
  exit 1
fi

if [[ -z "${SOURCE}" ]]; then
  SOURCE="$(git config --get remote.origin.url || true)"
fi
if [[ -z "${SOURCE}" ]]; then
  echo "Error: Could not determine git remote.origin.url; pass --source explicitly." >&2
  exit 1
fi

if [[ -z "${REVISION}" ]]; then
  REVISION="$(git rev-parse --abbrev-ref HEAD)@sha1:$(git rev-parse HEAD)"
fi

if [[ "${ACR_LOGIN}" == "true" ]]; then
  require_cmd az
  ACR_NAME="${REGISTRY%%.*}"
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "DRY RUN: az acr login --name ${ACR_NAME}"
  else
    az acr login --name "${ACR_NAME}"
  fi
fi

if [[ "${SKIP_VALIDATE}" == "false" ]]; then
  echo "Validating root aggregate builds..."
  build_kustomize "."
fi

TARGET="oci://${REGISTRY}/${ARTIFACT_REPO}:${TAG}"
cmd=(
  flux push artifact "${TARGET}"
  --path="."
  --source="${SOURCE}"
  --revision="${REVISION}"
  --provider="${PROVIDER}"
)

echo "Publishing ${TARGET} from repo root"
if [[ "${DRY_RUN}" == "true" ]]; then
  printf 'DRY RUN:'
  printf ' %q' "${cmd[@]}"
  printf '\n'
else
  "${cmd[@]}"
fi

echo "Done."
