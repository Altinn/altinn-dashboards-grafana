# Unified Grafana OCI artifact — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish all Grafana dashboards (self-contained `configMapRef` CRs) + all product alerts from `altinn-dashboards-grafana` as one Flux OCI artifact, consumed by `gitops-manifests` through a single `OCIRepository` + `Kustomization` syncroot.

**Architecture:** `altinn-dashboards-grafana` becomes the single content source: a repo-root kustomization aggregates `dashboards/` (3 platform folders + 9 dashboards wrapped from raw JSON via `configMapGenerator`) and `products/*/alerting`. CI pushes the repo root as one Flux OCI artifact to `altinncr.azurecr.io`. `gitops-manifests` `oci/grafana-operator/grafana-manifests/` drops its in-repo dashboard CRs + folders and instead references the artifact via an `OCIRepository` + `flux-kustomize.yaml` (the established `dis-apim` pattern), keeping the operator HelmRelease + `external-grafana` instance.

**Tech Stack:** Kustomize (`configMapGenerator`, `disableNameSuffixHash`), grafana-operator v5.23.0 CRDs (`GrafanaDashboard`/`GrafanaFolder`/`GrafanaContactPoint`/`GrafanaAlertRuleGroup`), Flux OCI (`OCIRepository`, `Kustomization`, `flux push artifact`), kubeconform, GitHub Actions (Azure OIDC), shellcheck/actionlint.

**Two repos / worktrees:**
- **A = altinn-dashboards-grafana**: `/Users/arealmaas/conductor/workspaces/altinn-dashboards-grafana/pangyo-v1` (branch `arealmaas/slack-alerts-multi-product`).
- **B = gitops-manifests**: `/Users/arealmaas/conductor/workspaces/gitops-manifests/amsterdam` (branch `arealmaas/amsterdam`).

**Reference spec:** `docs/superpowers/specs/2026-06-11-unified-grafana-oci-artifact-design.md` (in repo A).

**Decision baked into this plan (override before executing if you disagree):** artifact path = `oci://altinncr.azurecr.io/monitoring/grafana`, consumer `OCIRepository`/`Kustomization` name = `grafana-content`, pinned `ref.tag: release`.

**The 9 dashboards (folder / basename / JSON path → ConfigMap name → GrafanaDashboard name):**

| folder | basename | JSON (under `dashboards/`) | ConfigMap | GrafanaDashboard |
|---|---|---|---|---|
| altinn | blackbox-exporter | altinn/blackbox-exporter.json | dashboard-altinn-blackbox-exporter | external-grafana-altinn-blackbox-exporter |
| altinn | pod-console-error-logs | altinn/pod-console-error-logs.json | dashboard-altinn-pod-console-error-logs | external-grafana-altinn-pod-console-error-logs |
| altinn | publicip | altinn/publicip.json | dashboard-altinn-publicip | external-grafana-altinn-publicip |
| altinn | traefik-official | altinn/traefik-official.json | dashboard-altinn-traefik-official | external-grafana-altinn-traefik-official |
| fluxcd | flux-cluster-stats | fluxcd/flux-cluster-stats.json | dashboard-fluxcd-flux-cluster-stats | external-grafana-fluxcd-flux-cluster-stats |
| fluxcd | flux-control-plane | fluxcd/flux-control-plane.json | dashboard-fluxcd-flux-control-plane | external-grafana-fluxcd-flux-control-plane |
| fluxcd | gitops-flux-application-deployments-dashboard | fluxcd/gitops-flux-application-deployments-dashboard.json | dashboard-fluxcd-gitops-flux-application-deployments-dashboard | external-grafana-fluxcd-gitops-flux-application-deployments-dashboard |
| linkerd | daemonset | linkerd/daemonset.json | dashboard-linkerd-daemonset | external-grafana-linkerd-daemonset |
| linkerd | deployment | linkerd/deployment.json | dashboard-linkerd-deployment | external-grafana-linkerd-deployment |

---

## Repo A — altinn-dashboards-grafana (content source)

### Task 1: Vendor the `GrafanaDashboard` CRD schema for CI

**Files:**
- Modify: `schemas/regenerate.py` (the `KINDS` dict)
- Create (generated): `schemas/grafanadashboard_v1beta1.json`

- [ ] **Step 1: Confirm the gap (test first)**

Run: `ls schemas/ | grep dashboard || echo "MISSING"`
Expected: `MISSING` (no dashboard schema vendored yet).

- [ ] **Step 2: Add `GrafanaDashboard` to the `KINDS` dict**

In `schemas/regenerate.py`, change the `KINDS` dict to (new line first, keeping alpha-ish order with the others):

```python
KINDS = {
    "GrafanaAlertRuleGroup": "grafanaalertrulegroups",
    "GrafanaContactPoint": "grafanacontactpoints",
    "GrafanaDashboard": "grafanadashboards",
    "GrafanaFolder": "grafanafolders",
    "GrafanaNotificationPolicy": "grafananotificationpolicies",
    "GrafanaNotificationPolicyRoute": "grafananotificationpolicyroutes",
}
```

- [ ] **Step 3: Regenerate the schemas**

Run: `python3 schemas/regenerate.py`
Expected: prints `wrote schemas/grafanadashboard_v1beta1.json` among the others, ending `Pinned to grafana-operator v5.23.0`.

- [ ] **Step 4: Verify the new schema knows `configMapRef`**

Run: `python3 -c "import json; s=json.load(open('schemas/grafanadashboard_v1beta1.json')); print('configMapRef' in s['properties']['spec']['properties'])"`
Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add schemas/regenerate.py schemas/grafanadashboard_v1beta1.json
git commit -m "ci: vendor GrafanaDashboard CRD schema (v5.23.0) for kubeconform"
```

---

### Task 2: Platform Grafana folders

**Files:**
- Create: `dashboards/folders.yaml`

- [ ] **Step 1: Create `dashboards/folders.yaml`** (copied verbatim from the CRs currently in gitops-manifests so they reconcile in place)

```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaFolder
metadata:
  name: external-grafana-altinn
  namespace: grafana
spec:
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  title: Altinn
  permissions: |
    {
      "items": [
        { "role": "Admin",  "permission": 4 },
        { "role": "Editor", "permission": 1 },
        { "role": "Viewer", "permission": 1 }
      ]
    }
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaFolder
metadata:
  name: external-grafana-fluxcd
  namespace: grafana
spec:
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  title: Fluxcd
  permissions: |
    {
      "items": [
        { "role": "Admin",  "permission": 4 },
        { "role": "Editor", "permission": 1 },
        { "role": "Viewer", "permission": 1 }
      ]
    }
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaFolder
metadata:
  name: external-grafana-linkerd
  namespace: grafana
spec:
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  title: Linkerd
  permissions: |
    {
      "items": [
        { "role": "Admin",  "permission": 4 },
        { "role": "Editor", "permission": 1 },
        { "role": "Viewer", "permission": 1 }
      ]
    }
```

- [ ] **Step 2: Commit** (validated together with the kustomization in Task 4)

```bash
git add dashboards/folders.yaml
git commit -m "feat(dashboards): add platform Grafana folders (Altinn/Fluxcd/Linkerd)"
```

---

### Task 3: Platform dashboard CRs (`configMapRef`, self-contained)

**Files:**
- Create: `dashboards/dashboards.yaml`

- [ ] **Step 1: Create `dashboards/dashboards.yaml`** (9 CRs — identical `name`/`folderRef`/`instanceSelector` to the gitops-manifests CRs; only the source field is `spec.configMapRef` instead of `spec.url`)

```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-altinn-blackbox-exporter
  namespace: grafana
spec:
  folderRef: external-grafana-altinn
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-altinn-blackbox-exporter
    key: blackbox-exporter.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-altinn-pod-console-error-logs
  namespace: grafana
spec:
  folderRef: external-grafana-altinn
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-altinn-pod-console-error-logs
    key: pod-console-error-logs.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-altinn-publicip
  namespace: grafana
spec:
  folderRef: external-grafana-altinn
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-altinn-publicip
    key: publicip.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-altinn-traefik-official
  namespace: grafana
spec:
  folderRef: external-grafana-altinn
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-altinn-traefik-official
    key: traefik-official.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-fluxcd-flux-cluster-stats
  namespace: grafana
spec:
  folderRef: external-grafana-fluxcd
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-fluxcd-flux-cluster-stats
    key: flux-cluster-stats.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-fluxcd-flux-control-plane
  namespace: grafana
spec:
  folderRef: external-grafana-fluxcd
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-fluxcd-flux-control-plane
    key: flux-control-plane.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-fluxcd-gitops-flux-application-deployments-dashboard
  namespace: grafana
spec:
  folderRef: external-grafana-fluxcd
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-fluxcd-gitops-flux-application-deployments-dashboard
    key: gitops-flux-application-deployments-dashboard.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-linkerd-daemonset
  namespace: grafana
spec:
  folderRef: external-grafana-linkerd
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-linkerd-daemonset
    key: daemonset.json
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: external-grafana-linkerd-deployment
  namespace: grafana
spec:
  folderRef: external-grafana-linkerd
  instanceSelector:
    matchLabels:
      dashboards: "external-grafana"
  configMapRef:
    name: dashboard-linkerd-deployment
    key: deployment.json
```

- [ ] **Step 2: Commit** (validated in Task 4)

```bash
git add dashboards/dashboards.yaml
git commit -m "feat(dashboards): add platform GrafanaDashboard CRs (configMapRef)"
```

---

### Task 4: `dashboards/` kustomization (wrap JSON → ConfigMaps)

**Files:**
- Create: `dashboards/kustomization.yaml`

- [ ] **Step 1: Create `dashboards/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
# Self-contained platform dashboards: each raw JSON (kept in altinn/, fluxcd/, linkerd/
# below this kustomization so kustomize's load-restrictor is satisfied) is wrapped into a
# ConfigMap, and the matching GrafanaDashboard CR references it by spec.configMapRef.
# disableNameSuffixHash keeps the ConfigMap name stable so the CR reference is valid.
namespace: grafana
generatorOptions:
  disableNameSuffixHash: true
resources:
  - folders.yaml
  - dashboards.yaml
configMapGenerator:
  - name: dashboard-altinn-blackbox-exporter
    files:
      - altinn/blackbox-exporter.json
  - name: dashboard-altinn-pod-console-error-logs
    files:
      - altinn/pod-console-error-logs.json
  - name: dashboard-altinn-publicip
    files:
      - altinn/publicip.json
  - name: dashboard-altinn-traefik-official
    files:
      - altinn/traefik-official.json
  - name: dashboard-fluxcd-flux-cluster-stats
    files:
      - fluxcd/flux-cluster-stats.json
  - name: dashboard-fluxcd-flux-control-plane
    files:
      - fluxcd/flux-control-plane.json
  - name: dashboard-fluxcd-gitops-flux-application-deployments-dashboard
    files:
      - fluxcd/gitops-flux-application-deployments-dashboard.json
  - name: dashboard-linkerd-daemonset
    files:
      - linkerd/daemonset.json
  - name: dashboard-linkerd-deployment
    files:
      - linkerd/deployment.json
```

- [ ] **Step 2: Build and verify counts**

Run:
```bash
kustomize build dashboards | grep -c '^kind: GrafanaFolder'
kustomize build dashboards | grep -c '^kind: GrafanaDashboard'
kustomize build dashboards | grep -c '^kind: ConfigMap'
```
Expected: `3`, `9`, `9`.

- [ ] **Step 3: Verify every `configMapRef.name` resolves to a generated ConfigMap (no orphans)**

Run:
```bash
kustomize build dashboards > /tmp/dash.yaml
diff <(grep -oE 'dashboard-[a-z0-9-]+' /tmp/dash.yaml | sort -u) \
     <(awk '/^kind: ConfigMap/{f=1} f&&/^  name:/{print $2; f=0}' /tmp/dash.yaml | sort -u) \
  && echo "1:1 MATCH"
```
Expected: `1:1 MATCH` (no diff output).

- [ ] **Step 4: Commit**

```bash
git add dashboards/kustomization.yaml
git commit -m "feat(dashboards): wrap dashboard JSON into ConfigMaps via configMapGenerator"
```

---

### Task 5: Aggregate `dashboards/` into the repo-root kustomization

**Files:**
- Modify: `kustomization.yaml` (repo root)

- [ ] **Step 1: Verify root build currently excludes dashboards (test first)**

Run: `kustomize build . | grep -c '^kind: GrafanaDashboard'`
Expected: `0`.

- [ ] **Step 2: Add `dashboards` to the root `resources`**

In `kustomization.yaml`, change the `resources:` list so it reads:

```yaml
resources:
  - dashboards
  - products/dialogporten/alerting
  # - products/<next-product>/alerting
  # - products/<next-product>/dashboards
  # - platform/alerting                  # Option B only: central root policy + routes
```

- [ ] **Step 3: Build the whole artifact root**

Run: `kustomize build . | grep -cE '^kind: (GrafanaFolder|GrafanaDashboard|ConfigMap|GrafanaContactPoint|GrafanaAlertRuleGroup)'`
Expected: `24` (4 folders [3 platform + 1 dialogporten] + 9 dashboards + 9 configmaps + 1 contactpoint + 1 alertrulegroup).

- [ ] **Step 4: kubeconform-strict the whole root against the vendored schemas (incl. the new dashboard schema)**

Run:
```bash
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
kustomize build . | kubeconform -strict -summary \
  -schema-location default -schema-location "$SCHEMA_LOC" -
```
Expected: summary with `Errors: 0` and `Invalid: 0` (every GrafanaDashboard validates against the schema vendored in Task 1).

- [ ] **Step 5: Commit**

```bash
git add kustomization.yaml
git commit -m "feat: aggregate dashboards into the repo-root grafana artifact"
```

---

### Task 6: Rescope the publish workflow (alerts-only → whole grafana artifact)

**Files:**
- Rename: `.github/workflows/publish-alerting-artifact.yml` → `.github/workflows/publish-grafana-artifact.yml`
- Modify: the renamed file (`name`, `ARTIFACT_NAME`, path filters, header comment)

> The current file is untracked (created earlier this session). "Rename" = `mv` then `git add` the new path.

- [ ] **Step 1: Rename the file**

Run: `mv .github/workflows/publish-alerting-artifact.yml .github/workflows/publish-grafana-artifact.yml`

- [ ] **Step 2: Set `name`, `ARTIFACT_NAME`, and path filters**

In `.github/workflows/publish-grafana-artifact.yml`:
- Change the top `name:` line to: `name: Publish grafana artifact`
- Change the `env:` block to:
```yaml
env:
  ARTIFACT_NAME: monitoring/grafana
```
- Change the `concurrency.group` to: `publish-grafana-artifact-${{ github.ref_name }}`
- Change the `on.push.paths` list to include the dashboards + schemas + the new filename:
```yaml
    paths:
      - "dashboards/**"
      - "products/**"
      - "platform/**"
      - "schemas/**"
      - "kustomization.yaml"
      - ".github/workflows/publish-grafana-artifact.yml"
```
- Update the top comment block to say it packages "the repo-root kustomize aggregate (dashboards + all product alerts)" instead of "alerting CRs". Leave the validate step (`kustomize build .`) and the `build-push-image` action step unchanged.

- [ ] **Step 3: Lint**

Run: `actionlint .github/workflows/publish-grafana-artifact.yml && echo OK`
Expected: `OK` (no output from actionlint, then `OK`).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish-grafana-artifact.yml
git commit -m "ci: publish unified grafana artifact (dashboards + alerts) to monitoring/grafana"
```

---

### Task 7: Rescope the manual publish script

**Files:**
- Rename: `scripts/publish-alerting-artifact-manual.sh` → `scripts/publish-grafana-artifact-manual.sh`
- Modify: the renamed file (default `ARTIFACT_REPO`, help/usage wording)

- [ ] **Step 1: Rename**

Run: `mv scripts/publish-alerting-artifact-manual.sh scripts/publish-grafana-artifact-manual.sh`

- [ ] **Step 2: Change the default artifact repo**

In `scripts/publish-grafana-artifact-manual.sh`, change the default:
```bash
ARTIFACT_REPO="${ARTIFACT_REPO:-monitoring/grafana}"
```
and in the `usage()` heredoc change the `--repo` default text and the `ARTIFACT_REPO (default: …)` line to `monitoring/grafana`, and reword the one-line description from "alerting CRs" to "all grafana CRs (dashboards + alerts)". Leave the OCI-tag sanitize/validate logic and the `flux push artifact` assembly unchanged.

- [ ] **Step 3: shellcheck + dry-run**

Run:
```bash
shellcheck scripts/publish-grafana-artifact-manual.sh && echo "shellcheck OK"
./scripts/publish-grafana-artifact-manual.sh --dry-run --skip-validate --tag release 2>&1 | grep Publishing
```
Expected: `shellcheck OK`, then `Publishing oci://altinncr.azurecr.io/monitoring/grafana:release from repo root`.

- [ ] **Step 4: Commit**

```bash
git add scripts/publish-grafana-artifact-manual.sh
git commit -m "ci: rescope manual publish script to the unified grafana artifact"
```

---

### Task 8: Extend offline validation CI to dashboards

**Files:**
- Modify: `.github/workflows/validate-alerting.yml`

> The existing kubeconform job already builds `.` (root) — which now includes dashboards — and every `products/*/alerting`. Only two gaps: the path triggers don't include `dashboards/`, and yamllint only targets `products`/`platform`.

- [ ] **Step 1: Add `dashboards/` to both `paths:` trigger lists**

In `.github/workflows/validate-alerting.yml`, add `- "dashboards/**"` to the `on.pull_request.paths` list and the `on.push.paths` list (next to the existing `- "products/**"`).

- [ ] **Step 2: Add `dashboards` to the yamllint targets**

In the `yaml` job, change the targets line to:
```bash
          targets="dashboards products"
```
(keep the existing `if [ -d platform ]` append).

- [ ] **Step 3: Verify locally (the kubeconform job's exact command)**

Run:
```bash
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
kustomize build . | kubeconform -strict -summary \
  -schema-location default -schema-location "$SCHEMA_LOC" -
```
Expected: `Errors: 0`.

- [ ] **Step 4: actionlint + commit**

```bash
actionlint .github/workflows/validate-alerting.yml && echo OK
git add .github/workflows/validate-alerting.yml
git commit -m "ci: validate dashboards in the offline kustomize/kubeconform/yamllint job"
```

---

### Task 9: Update repo-A docs

**Files:**
- Modify: `docs/flux-repo-wiring.md`
- Modify: `README.md`

- [ ] **Step 1: Rewrite `docs/flux-repo-wiring.md` "Source + Kustomization" to the real consumer wiring**

Replace the Option A/B copy-paste block with the actual `gitops-manifests` pattern (the consumer adds these two files in `oci/grafana-operator/grafana-manifests/base/`):

````markdown
## 1. Source + Kustomization (in gitops-manifests `oci/grafana-operator/grafana-manifests/base/`)

```yaml
# oci-repository.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: grafana-content
  namespace: flux-system
spec:
  interval: 5m0s
  provider: azure
  ref:
    tag: release            # promote main -> release; CI tags the artifact per branch
  timeout: 5m0s
  url: oci://altinncr.azurecr.io/monitoring/grafana
---
# flux-kustomize.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: grafana-content
  namespace: flux-system
spec:
  interval: 5m0s
  retryInterval: 1m0s
  path: ./                  # repo-root kustomization aggregates dashboards + products/*/alerting
  prune: true
  sourceRef:
    kind: OCIRepository
    name: grafana-content
    namespace: flux-system
  targetNamespace: grafana
  timeout: 5m0s
  wait: true
```
````

Keep the existing "Slack webhook Secret" and "Pre-flight checks" sections; update the pre-flight note to say the 3 platform folders (`external-grafana-altinn/fluxcd/linkerd`) and all dashboards now ship from this artifact (no longer defined in gitops-manifests).

- [ ] **Step 2: Update `README.md` Delivery section + structure block**

In `README.md`: update the "Delivery (OCI artifact)" subsection so it states the artifact contains dashboards (as `configMapRef` CRs) + alerts and is consumed by `gitops-manifests` via an `OCIRepository`; update the Repository Structure block to show `dashboards/{kustomization.yaml,folders.yaml,dashboards.yaml}` and the renamed `publish-grafana-artifact.yml` / `scripts/publish-grafana-artifact-manual.sh`. Remove the "deferred platform/ reorg breaks spec.url" caveat (dashboards no longer use `spec.url`).

- [ ] **Step 3: Commit**

```bash
git add docs/flux-repo-wiring.md README.md
git commit -m "docs: document the unified grafana artifact + OCIRepository consumer wiring"
```

---

## Repo B — gitops-manifests (consumer cutover)

> All paths below are under `/Users/arealmaas/conductor/workspaces/gitops-manifests/amsterdam`. Do these on branch `arealmaas/amsterdam`. **One commit** for Task 10+11 so the operator never sees both the old CRs and the new source.

### Task 10: Remove the in-repo dashboards + folders

**Files:**
- Delete: `oci/grafana-operator/grafana-manifests/base/dashboards/` (8 CRs + its kustomization.yaml)
- Delete: `oci/grafana-operator/grafana-manifests/apps/dashboards/` (1 CR + its kustomization.yaml)
- Delete: `oci/grafana-operator/grafana-manifests/base/folders.yaml`

- [ ] **Step 1: Delete the files** (do not commit yet — combined with Task 11)

```bash
git rm -r oci/grafana-operator/grafana-manifests/base/dashboards
git rm -r oci/grafana-operator/grafana-manifests/apps/dashboards
git rm oci/grafana-operator/grafana-manifests/base/folders.yaml
```

---

### Task 11: Add the OCIRepository + Kustomization syncroot

**Files:**
- Create: `oci/grafana-operator/grafana-manifests/base/oci-repository.yaml`
- Create: `oci/grafana-operator/grafana-manifests/base/flux-kustomize.yaml`
- Modify: `oci/grafana-operator/grafana-manifests/base/kustomization.yaml`
- Modify: `oci/grafana-operator/grafana-manifests/apps/kustomization.yaml`

- [ ] **Step 1: Create `base/oci-repository.yaml`**

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: grafana-content
  namespace: flux-system
spec:
  interval: 5m0s
  provider: azure
  ref:
    tag: release
  timeout: 5m0s
  url: oci://altinncr.azurecr.io/monitoring/grafana
```

- [ ] **Step 2: Create `base/flux-kustomize.yaml`**

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: grafana-content
  namespace: flux-system
spec:
  interval: 5m0s
  retryInterval: 1m0s
  path: ./
  prune: true
  sourceRef:
    kind: OCIRepository
    name: grafana-content
    namespace: flux-system
  targetNamespace: grafana
  timeout: 5m0s
  wait: true
```

- [ ] **Step 3: Replace `base/kustomization.yaml` resources**

Set `oci/grafana-operator/grafana-manifests/base/kustomization.yaml` to:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - oci-repository.yaml
  - flux-kustomize.yaml
```

- [ ] **Step 4: Make `apps/kustomization.yaml` a thin passthrough**

Set `oci/grafana-operator/grafana-manifests/apps/kustomization.yaml` to (keeps the existing `grafana-manifests/apps` bootstrap target valid):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../base
```

- [ ] **Step 5: Build both targets**

Run:
```bash
kustomize build oci/grafana-operator/grafana-manifests/base
kustomize build oci/grafana-operator/grafana-manifests/apps
```
Expected (both): exactly one `OCIRepository` (`name: grafana-content`) and one `Kustomization` (`name: grafana-content`); no GrafanaDashboard/GrafanaFolder remain.

- [ ] **Step 6: Commit (Task 10 + 11 together)**

```bash
git add oci/grafana-operator/grafana-manifests
git commit -m "feat(grafana): pull dashboards+folders+alerts from the altinn-dashboards-grafana OCI artifact

Replace the in-repo GrafanaDashboard CRs + folders with an OCIRepository +
Kustomization referencing oci://altinncr.azurecr.io/monitoring/grafana:release.
Operator HelmRelease and external-grafana instance unchanged."
```

---

### Task 12: Update gitops-manifests grafana docs

**Files:**
- Modify: `oci/grafana-operator/grafana-manifests/README.md`

- [ ] **Step 1: Rewrite the "Manifest Sources" + structure sections**

Update `oci/grafana-operator/grafana-manifests/README.md` to state that dashboards, folders, and product alerts are now delivered by the external `altinn-dashboards-grafana` Flux OCI artifact (`oci://altinncr.azurecr.io/monitoring/grafana`, pinned `tag: release`) via `base/oci-repository.yaml` + `base/flux-kustomize.yaml`; remove the `${RELEASE_BRANCH}`/`spec.url` description and the "Add New Base/App Dashboard" steps (dashboards are now added in the altinn-dashboards-grafana repo). Keep the base/apps deploy-target note.

- [ ] **Step 2: Commit**

```bash
git add oci/grafana-operator/grafana-manifests/README.md
git commit -m "docs(grafana): document external OCI artifact as the manifest source"
```

---

## Cross-cutting

### Task 13: Cluster-bootstrap runbook + provisioning checklist

**Files:**
- Create (repo A): `docs/cutover-runbook.md`

- [ ] **Step 1: Write `docs/cutover-runbook.md`** covering, in order:
  1. **Provision Azure push creds** for `Altinn/altinn-dashboards-grafana`: an app registration / managed identity with a **federated credential** trusting this repo's `main` + `release` refs and the `AcrPush` role on `altinncr.azurecr.io`; add repo secrets `AZURE_SUBSCRIPTION_ID`, `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`. (gitops-manifests' `*_ADMINSERVICES_PROD` creds are dis-way-scoped and not reusable.)
  2. **Confirm the artifact path** `monitoring/grafana` is acceptable in `altinncr.azurecr.io` (else change `ARTIFACT_NAME` in `publish-grafana-artifact.yml` and the `url:` in both repos).
  3. **Confirm the cluster-bootstrap repo** (the one holding the top-level Flux `Kustomization` that points at `oci/grafana-operator/grafana-manifests/base` or `/apps`) — the new `grafana-content` `OCIRepository`/`Kustomization` are applied by that bootstrap. If it targets a path that no longer renders content directly, no change is needed (it now renders the two Flux objects); confirm `provider: azure` ACR pull works (the source-controller identity needs `AcrPull` on `altinncr.azurecr.io`).
  4. **Cutover order:** merge repo-A PR → confirm CI published `:release` (`flux pull artifact oci://altinncr.azurecr.io/monitoring/grafana:release` or check the ACR) → merge repo-B PR → reconcile.
  5. **Verification:** `kubectl -n grafana get grafanafolder,grafanadashboard,grafanacontactpoint,grafanaalertrulegroup` shows 4 folders / 9 dashboards / 1 contactpoint / 1 alertrulegroup, all `True`/applied; Grafana UI shows dashboards under the Altinn/Fluxcd/Linkerd folders; `flux get kustomization grafana-content -n flux-system` is Ready.
  6. **Rollback:** revert the repo-B commit (restores the in-repo URL CRs); the artifact remains but is unreferenced.

- [ ] **Step 2: Commit**

```bash
git add docs/cutover-runbook.md
git commit -m "docs: cluster-bootstrap cutover runbook + Azure push-cred checklist"
```

---

### Task 14: Final verification + adversarial review

- [ ] **Step 1: Repo A full local gate**

Run (in repo A):
```bash
kustomize build . >/dev/null && echo "root build OK"
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
kustomize build . | kubeconform -strict -summary -schema-location default -schema-location "$SCHEMA_LOC" -
shellcheck scripts/publish-grafana-artifact-manual.sh && echo "shellcheck OK"
actionlint .github/workflows/publish-grafana-artifact.yml .github/workflows/validate-alerting.yml && echo "actionlint OK"
```
Expected: `root build OK`, kubeconform `Errors: 0`, `shellcheck OK`, `actionlint OK`.

- [ ] **Step 2: Repo B build gate**

Run (in repo B): `kustomize build oci/grafana-operator/grafana-manifests/base && kustomize build oci/grafana-operator/grafana-manifests/apps`
Expected: both render the two `grafana-content` Flux objects, exit 0.

- [ ] **Step 3: CR-fidelity check (the cutover's safety property)**

Confirm the GrafanaDashboard CR names + folderRefs produced by repo A exactly match the set removed from repo B:
```bash
kustomize build . | awk '/^kind: GrafanaDashboard/{d=1} d&&/^  name:/{print $2; d=0}' | sort
```
Expected: the 9 `external-grafana-*` names from the plan's table — identical to the names deleted in Task 10.

- [ ] **Step 4: Dispatch an adversarial multi-agent review** (CR fidelity vs the removed CRs, CI/Linux correctness, OCIRepository/Kustomization correctness, cutover double-apply safety). Fix any confirmed findings, re-run Steps 1–3.

- [ ] **Step 5: Open the two PRs** (repo A first), linking both and the runbook; do not merge until the Task 13 provisioning items are confirmed.

---

## Self-review notes (author)

- **Spec coverage:** §3.1 dashboards→Tasks 2–4; §3.2 root→Task 5; §3.3 schema→Task 1; §3.4 workflow/script/CI→Tasks 6–8; §3.5 docs→Task 9; §4 consumer→Tasks 10–12; §5 cutover→Task 13; §7 verification→Task 14. All covered.
- **Placeholders:** none — every manifest is shown in full; the only parameterized value (`monitoring/grafana`) is declared as a baked decision up front and appears identically in Tasks 6, 7, 9, 11, 13.
- **Name consistency:** ConfigMap names (`dashboard-<folder>-<basename>`), CR names (`external-grafana-<folder>-<basename>`), and `configMapRef.key` (the JSON basename) are consistent across Tasks 3, 4, and the table; `grafana-content` is the OCIRepository/Kustomization name in Tasks 9 and 11.
