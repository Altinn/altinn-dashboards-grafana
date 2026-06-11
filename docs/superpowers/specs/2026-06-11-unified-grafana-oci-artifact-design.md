# Unified Grafana OCI artifact — design

**Date:** 2026-06-11
**Status:** Approved (design); pending spec review → implementation plan
**Repos involved:** `Altinn/altinn-dashboards-grafana` (content source), `dis-way/gitops-manifests` (cluster GitOps hub), plus a separate cluster-bootstrap repo (top-level Flux Kustomizations; not in our workspaces).

## 1. Background & problem

`altinn-dashboards-grafana` holds Grafana **dashboard JSON** (`dashboards/{altinn,fluxcd,linkerd}/*.json`) and, since PR #9, **alerting-as-code** operator CRs (`products/dialogporten/alerting/`). Today:

- Dashboards are delivered by `GrafanaDashboard` CRs that live in **`gitops-manifests`** (`oci/grafana-operator/grafana-manifests/`), each fetching JSON by `spec.url` → `raw.githubusercontent.com/Altinn/altinn-dashboards-grafana/${RELEASE_BRANCH:=release}/dashboards/...`.
- Alert CRs have **no `spec.url`** — they must be *applied* as manifests, so they currently have no delivery path to the cluster.

**Goal:** publish **everything** (all dashboards + all alerts, for platform + all products) as **one Flux OCI artifact**, pulled by **one syncroot**, with `altinn-dashboards-grafana` as the single content source of truth. (Brainstorming decisions: full unification = "this repo is the single applied source"; dashboards become self-contained via `configMapRef`; consumed by gitops-manifests via an `OCIRepository` reference — "Approach 1".)

### Non-goals
- No change to the Grafana operator install or the `external-grafana` `Grafana` instance (both stay in gitops-manifests).
- No relocation of dashboard JSON files (zero moves — verified feasible).
- No change to the ring/release-please promotion machinery (external artifacts sit outside it by house convention).

## 2. End-state architecture

```
Altinn/altinn-dashboards-grafana  ──(CI: flux push artifact)──▶  oci://altinncr.azurecr.io/<PATH>:release
   (single content source)                                              │
   • 3 platform GrafanaFolders                                          │  (one artifact)
   • 9 platform GrafanaDashboards (configMapRef, self-contained)        │
   • products/<p>/alerting CRs (+ product folders)                      ▼
dis-way/gitops-manifests  oci/grafana-operator/
   • operator HelmRelease + external-grafana instance      (unchanged)
   • grafana-manifests/base/oci-repository.yaml  (OCIRepository → the artifact)   ◀── ONE syncroot
   • grafana-manifests/base/flux-kustomize.yaml  (Kustomization → ns: grafana)
        └─ applies folders + dashboards + alerts, all products, in one reconcile
```

**Registry (confirmed):** `altinncr.azurecr.io`. gitops-manifests internal artifacts use `…/manifests/infra/<name>`; **external** artifacts (e.g. `dis-apim`) are referenced directly via `OCIRepository` + a `flux-kustomize.yaml` `Kustomization` with `postBuild.substitute`, and sit **outside** release-please (Renovate pins the version). Our artifact is external → follows that pattern.

**Artifact path — DECISION TO CONFIRM:** recommended `oci://altinncr.azurecr.io/monitoring/grafana` (parameterized as `ARTIFACT_NAME` in the publish workflow so it's a one-line change). Must match on both sides (publisher workflow ↔ consumer `OCIRepository`).

## 3. `altinn-dashboards-grafana` changes (the content source)

### 3.1 Dashboards become self-contained CRs (`configMapRef`)

Verified with kustomize v5.7.1: keep the 9 JSON where they are; a single kustomization at `dashboards/` wraps them (the JSON lives in subdirs *below* the kustomization, satisfying kustomize's load-restrictor — no `LoadRestrictionsNone` needed, which Flux does not enable).

```
dashboards/
  altinn/*.json  fluxcd/*.json  linkerd/*.json   # UNCHANGED — source of truth
  kustomization.yaml   # NEW
  folders.yaml         # NEW — 3 GrafanaFolder (moved out of gitops-manifests)
  dashboards.yaml      # NEW — 9 GrafanaDashboard CRs (configMapRef)
```

- `dashboards/kustomization.yaml`: `namespace: grafana`; `generatorOptions.disableNameSuffixHash: true`; `resources: [folders.yaml, dashboards.yaml]`; one `configMapGenerator` entry per dashboard, e.g.
  ```yaml
  configMapGenerator:
    - name: dashboard-altinn-traefik-official
      files: [altinn/traefik-official.json]
  ```
- `dashboards/folders.yaml`: 3 `GrafanaFolder` — `external-grafana-altinn` / `-fluxcd` / `-linkerd` (titles Altinn/Fluxcd/Linkerd, `instanceSelector matchLabels dashboards=external-grafana`, permissions block) — **copied verbatim** from gitops-manifests' current `grafana-manifests/base/folders.yaml`.
- `dashboards/dashboards.yaml`: 9 `GrafanaDashboard` — names `external-grafana-<folder>-<basename>`, `folderRef: external-grafana-<folder>`, `instanceSelector matchLabels dashboards=external-grafana`, and **`spec.configMapRef`** (replacing `spec.url`):
  ```yaml
  spec:
    configMapRef:
      name: dashboard-altinn-traefik-official
      key: traefik-official.json
  ```
  The CR `name`/`folderRef`/`instanceSelector` are **byte-identical** to the current gitops-manifests CRs so the operator reconciles them in place during cutover (only the source field changes, `url` → `configMapRef`).

Verified full repo-root build: 4 GrafanaFolder + 9 GrafanaDashboard + 9 ConfigMap + 1 GrafanaContactPoint + 1 GrafanaAlertRuleGroup, exit 0, no flags, 1:1 ConfigMap↔configMapRef match (no orphans).

### 3.2 Root kustomization
`kustomization.yaml` (currently only `products/dialogporten/alerting`) gains a `dashboards` resource:
```yaml
resources:
  - dashboards
  - products/dialogporten/alerting
  # - products/<next>/alerting
  # - products/<next>/dashboards
```
Future products: `products/<name>/{dashboards,alerting}/`, one root line each.

### 3.3 Vendored CRD schema
`GrafanaDashboard` is **not** yet in `schemas/`. Add `GrafanaDashboard → grafanadashboards` to the `KINDS` dict in `schemas/regenerate.py` (pinned grafana-operator v5.23.0) and re-run it to vendor `grafanadashboard_v1beta1.json`. The CRD's `spec.configMapRef` has `{key (required), name, optional}`.

### 3.4 Publish workflow + script (rescope, don't duplicate)
The artifact now contains dashboards **and** alerts → rescope the PR-#9 additions:
- `.github/workflows/publish-alerting-artifact.yml` → **`publish-grafana-artifact.yml`**; `ARTIFACT_NAME` default → the confirmed path; behaviour otherwise unchanged (validate `kustomize build .` gate, then push the whole repo root as one artifact via the same Azure-OIDC `build-push-image` action, tag = branch).
- `scripts/publish-alerting-artifact-manual.sh` → **`publish-grafana-artifact-manual.sh`** (same rescope; keep the OCI-tag sanitize/validate fix).
- `validate-alerting.yml`: the existing find-driven loop already builds `.` (root) + every `products/*/alerting`; it will now also validate `dashboards` via the root build. Add the new `GrafanaDashboard` schema so kubeconform `-strict` passes; lint the new YAML.

### 3.5 Docs
- `docs/flux-repo-wiring.md`: replace the generic OCIRepository/GitRepository copy-paste with the **actual gitops-manifests wiring** (the `dis-apim`-style `oci-repository.yaml` + `flux-kustomize.yaml`, `targetNamespace: grafana`), plus the cutover note.
- `README.md`: update "Delivery" + structure to reflect dashboards-as-CRs and the unified artifact; the "deferred platform/ reorg" caveat is resolved (we no longer depend on `spec.url` paths).

## 4. `gitops-manifests` changes (the consumer), `oci/grafana-operator/`

**Remove** (these now live in altinn-dashboards-grafana):
- `grafana-manifests/base/dashboards/*` (8 CRs) + its `kustomization.yaml`
- `grafana-manifests/apps/dashboards/*` (1 CR) + its `kustomization.yaml`
- `grafana-manifests/base/folders.yaml`

**Add** (mirroring `oci/dis-apim/base/`):
- `grafana-manifests/base/oci-repository.yaml` — `OCIRepository` (`provider: azure`, `url: oci://altinncr.azurecr.io/<PATH>`, `ref.tag: release`, `interval`).
- `grafana-manifests/base/flux-kustomize.yaml` — `Kustomization` (`sourceRef` → that OCIRepository, `path: ./`, `prune: true`, `targetNamespace: grafana`, `dependsOn` the operator; `postBuild.substitute` only if any value is parameterized).
- `grafana-manifests/base/kustomization.yaml` now references just these two (plus keep `apps/` thin or collapse it — TBD in plan).

**Keep unchanged:** operator HelmRelease, namespace, `grafana-admin-apikey`, `post-deploy/external-grafana.yaml` (the instance), `grafana-redirect/`, `fqdn-to-azure-grafana/`.

**Out of scope here / runbook:** the **top-level Flux Kustomization** that points the cluster at `grafana-manifests` lives in a **separate cluster-bootstrap repo**. Confirm it targets `grafana-manifests/base` (or `/apps`) so the new wiring is picked up; spec the exact change as a runbook (that repo is not in our workspaces).

## 5. Cutover sequence (no double-apply)

1. **altinn-dashboards-grafana PR** merges → CI publishes artifact `:release` (and `:main`/`:sha`). The dashboard CRs in the artifact have **identical** names/selectors to the ones still in gitops-manifests, so nothing conflicts yet (the artifact isn't referenced until step 2).
2. **gitops-manifests PR** (single commit): delete the 9 in-repo dashboard CRs + `folders.yaml` **and** add `oci-repository.yaml` + `flux-kustomize.yaml`. Because old CRs are removed and the new source applies CRs with the same names in the same commit, the operator never sees duplicates; dashboards reconcile in place (source field flips `url` → `configMapRef`).
3. **Cluster-bootstrap** confirm/adjust the top-level Kustomization target (runbook).
4. **Verify:** `kubectl -n grafana get grafanafolder,grafanadashboard,grafanacontactpoint,grafanaalertrulegroup`; folders/dashboards/alerts all present and `Applied`; Grafana UI shows the dashboards in their folders.

## 6. Decisions to confirm before first publish

1. **Artifact path** under `altinncr.azurecr.io` (recommended `monitoring/grafana`).
2. **Azure federated identity** with `AcrPush` trusting `Altinn/altinn-dashboards-grafana` + repo secrets (`AZURE_SUBSCRIPTION_ID`/`AZURE_CLIENT_ID`/`AZURE_TENANT_ID`). gitops-manifests' creds (`*_ADMINSERVICES_PROD`) are dis-way-scoped and not reusable as-is.
3. **`grafana-manifests/apps`** fate — collapse into `base` or keep as a thin overlay (resolve in the implementation plan).
4. **Cluster-bootstrap repo** name + the Kustomization that targets `grafana-manifests` (for the runbook).

## 7. Verification plan
- Local: `kustomize build .` (root) green; `kubeconform -strict` against vendored schemas incl. new `grafanadashboard`; `shellcheck`/`actionlint` on workflow+script; manual publish `--dry-run`.
- gitops-manifests: `kustomize build oci/grafana-operator/grafana-manifests/base` green after the swap.
- Adversarial multi-agent review (CR fidelity vs the CRs being removed; CI/Linux correctness; cutover safety) before opening PRs.
