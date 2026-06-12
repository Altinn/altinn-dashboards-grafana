# Cutover Runbook — Unified Grafana OCI Artifact

This runbook covers the operator steps required to cut over from in-repo `spec.url` dashboard CRs in `gitops-manifests` to the unified Grafana OCI artifact published by `altinn-dashboards-grafana`. Read the design spec and implementation plan before proceeding:

- Design spec: [`docs/superpowers/specs/2026-06-11-unified-grafana-oci-artifact-design.md`](superpowers/specs/2026-06-11-unified-grafana-oci-artifact-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-06-11-unified-grafana-oci-artifact.md`](superpowers/plans/2026-06-11-unified-grafana-oci-artifact.md)

---

## 1. Provision Azure Push Credentials for `Altinn/altinn-dashboards-grafana`

The `gitops-manifests` repo uses `*_ADMINSERVICES_PROD` credentials that are scoped to that repo's workload identity and are **not reusable** here. A dedicated app registration (or managed identity) is required for `Altinn/altinn-dashboards-grafana`.

### 1a. Create the app registration / managed identity

```bash
# Create an app registration (or use a managed identity if preferred)
az ad app create --display-name "altinn-dashboards-grafana-ci"

# Note the appId (client ID) and the object ID
APP_ID=$(az ad app list --display-name "altinn-dashboards-grafana-ci" --query "[0].appId" -o tsv)
OBJECT_ID=$(az ad app list --display-name "altinn-dashboards-grafana-ci" --query "[0].id" -o tsv)

# Create a service principal for the app
az ad sp create --id "$APP_ID"
```

### 1b. Add federated credentials for GitHub Actions OIDC

Add two federated credentials — one for the `main` branch (CI pushes `:main` tag) and one for the `release` tag/branch (CI pushes `:release` tag).

```bash
# Federated credential for the main branch
az ad app federated-credential create \
  --id "$OBJECT_ID" \
  --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:Altinn/altinn-dashboards-grafana:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# Federated credential for the release branch/tag
az ad app federated-credential create \
  --id "$OBJECT_ID" \
  --parameters '{
    "name": "github-release",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:Altinn/altinn-dashboards-grafana:ref:refs/heads/release",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

> **Note:** If the `:release` artifact is promoted from a tag rather than a branch, add a third credential with `subject: "repo:Altinn/altinn-dashboards-grafana:ref:refs/tags/release"`. Check the workflow trigger in `.github/workflows/publish-grafana-artifact.yml` to confirm.

### 1c. Grant `AcrPush` on `altinncr.azurecr.io`

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
REGISTRY_RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/altinncr"
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

az role assignment create \
  --assignee "$SP_OBJECT_ID" \
  --role "AcrPush" \
  --scope "$REGISTRY_RESOURCE_ID"
```

Replace `<rg>` with the resource group that owns `altinncr`.

### 1d. Add GitHub repository secrets

In `https://github.com/Altinn/altinn-dashboards-grafana` → **Settings → Secrets and variables → Actions**, add:

| Secret name              | Value                                      |
|--------------------------|--------------------------------------------|
| `AZURE_SUBSCRIPTION_ID`  | The Azure subscription ID                 |
| `AZURE_CLIENT_ID`        | The `appId` from step 1a                  |
| `AZURE_TENANT_ID`        | The Azure tenant ID                       |

These three secrets are consumed by the `azure/login` action step in `.github/workflows/publish-grafana-artifact.yml` via the `client-id` / `tenant-id` / `subscription-id` inputs (OIDC, no client secret required).

---

## 2. Confirm the Artifact Path in `altinncr.azurecr.io`

The workflow and the consumer `OCIRepository` both reference the path `monitoring/grafana`. Verify this path is acceptable in the registry (no naming conflicts, no policy restrictions on the `monitoring/` namespace).

```bash
# List existing repositories in the registry
az acr repository list --name altinncr --output table | grep monitoring || echo "monitoring/* namespace is free"
```

**If the path needs to change:**

1. Update `ARTIFACT_NAME` in `.github/workflows/publish-grafana-artifact.yml`:
   ```yaml
   env:
     ARTIFACT_NAME: <new-path>   # e.g. grafana/content
   ```

2. Update the `url:` field in both repos' `OCIRepository`:
   - `altinn-dashboards-grafana`: `docs/flux-repo-wiring.md` (documentation reference)
   - `gitops-manifests`: `oci/grafana-operator/grafana-manifests/base/oci-repository.yaml`
   ```yaml
   url: oci://altinncr.azurecr.io/<new-path>
   ```

3. Re-run local builds in both repos to confirm the change is consistent:
   ```bash
   # repo A
   kustomize build . >/dev/null && echo "repo A OK"
   # repo B
   kustomize build oci/grafana-operator/grafana-manifests/base && echo "repo B OK"
   ```

---

## 3. Confirm the Cluster-Bootstrap Repo and `AcrPull` Identity

The cluster-bootstrap repo holds the top-level Flux `Kustomization` that points at `oci/grafana-operator/grafana-manifests/base` (or `/apps`) in `gitops-manifests`. After the repo-B merge, that path renders two new Flux objects — `OCIRepository/grafana-content` and `Kustomization/grafana-content` — rather than inline dashboard CRs.

### 3a. Verify the bootstrap Kustomization target still renders

```bash
# In gitops-manifests, after the Task 10+11 commit:
kustomize build oci/grafana-operator/grafana-manifests/base | \
  grep -E '^(kind|  name):' | paste - -
# Expected lines include:
#   kind: OCIRepository    name: grafana-content
#   kind: Kustomization    name: grafana-content
```

No change to the cluster-bootstrap repo is needed as long as its Kustomization target path (`base` or `apps`) renders non-empty output — which it does (the two `grafana-content` Flux objects).

### 3b. Confirm `AcrPull` for the source-controller identity

The Flux `source-controller` running in the cluster uses `provider: azure` in the `OCIRepository`, which means it authenticates to ACR using its workload identity (managed identity bound to the `source-controller` service account). Verify this identity has `AcrPull` on `altinncr.azurecr.io`:

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
REGISTRY_RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/altinncr"

# Find the managed identity / service principal used by source-controller
# (check the cluster's workload-identity annotations on the source-controller SA)
kubectl get sa -n flux-system source-controller -o jsonpath='{.metadata.annotations}'

# Verify the role assignment
az role assignment list --scope "$REGISTRY_RESOURCE_ID" --query "[?roleDefinitionName=='AcrPull'].{principal:principalName,role:roleDefinitionName}" -o table
```

If `AcrPull` is missing, grant it:

```bash
SOURCE_CONTROLLER_MI_OBJECT_ID="<object-id-of-source-controller-managed-identity>"
az role assignment create \
  --assignee "$SOURCE_CONTROLLER_MI_OBJECT_ID" \
  --role "AcrPull" \
  --scope "$REGISTRY_RESOURCE_ID"
```

---

## 4. Cutover Order

Perform the steps in this exact order to avoid a window where the consumer in `gitops-manifests` references an artifact that does not yet exist.

### Step 1 — Merge the `altinn-dashboards-grafana` PR first

Merge the repo-A PR (branch `arealmaas/slack-alerts-multi-product`). This triggers the `publish-grafana-artifact` CI workflow, which builds the repo-root kustomization and pushes the OCI artifact to:

```
oci://altinncr.azurecr.io/monitoring/grafana:release
```

### Step 2 — Confirm the artifact is published

Wait for the CI workflow to complete (check the Actions tab), then verify the artifact is available:

```bash
# Option A: pull via flux CLI
flux pull artifact oci://altinncr.azurecr.io/monitoring/grafana:release \
  --output /tmp/grafana-artifact

# Option B: check the ACR directly
az acr repository show-tags --name altinncr --repository monitoring/grafana --output table
# Expected: 'release' tag present, timestamp matches the CI run
```

Do **not** proceed to Step 3 until the `:release` tag is confirmed.

### Step 3 — Merge the `gitops-manifests` PR

Merge the repo-B PR (branch `arealmaas/amsterdam`). This removes the in-repo dashboard and folder CRs and deploys the `OCIRepository/grafana-content` + `Kustomization/grafana-content` objects.

### Step 4 — Trigger reconciliation

Force a reconcile if you do not want to wait for the 5-minute interval:

```bash
flux reconcile kustomization <bootstrap-kustomization-name> -n flux-system --with-source
# Then reconcile the grafana-content kustomization once it appears:
flux reconcile kustomization grafana-content -n flux-system --with-source
```

---

## 5. Verification

### 5a. Flux kustomization is Ready

```bash
flux get kustomization grafana-content -n flux-system
# Expected:
#   NAME             REVISION   SUSPENDED   READY   MESSAGE
#   grafana-content  ...        False       True    Applied revision: ...
```

### 5b. Grafana operator resources are applied

```bash
kubectl -n grafana get grafanafolder,grafanadashboard,grafanacontactpoint,grafanaalertrulegroup
```

Expected counts and status:

| Kind                    | Count | Status field |
|-------------------------|-------|--------------|
| `GrafanaFolder`         | 4     | `True`       |
| `GrafanaDashboard`      | 9     | `True`       |
| `GrafanaContactPoint`   | 1     | `True`       |
| `GrafanaAlertRuleGroup` | 1     | `True`       |

The 4 folders are: `external-grafana-altinn`, `external-grafana-fluxcd`, `external-grafana-linkerd` (platform, from `dashboards/folders.yaml`) and the Dialogporten folder (from `products/dialogporten/alerting`).

### 5c. Grafana UI

Log into the Grafana instance and confirm:

- Dashboards are visible under the **Altinn**, **Fluxcd**, and **Linkerd** folders (9 dashboards total).
- Alerting contact point and alert rule group for Dialogporten are present under **Alerting**.

### 5d. No orphaned in-repo CRs

Confirm that no `GrafanaDashboard` or `GrafanaFolder` CRs remain in `gitops-manifests` that could conflict:

```bash
# In gitops-manifests repo:
grep -r 'kind: GrafanaDashboard\|kind: GrafanaFolder' \
  oci/grafana-operator/grafana-manifests/ && echo "FOUND — investigate" || echo "clean"
# Expected: clean
```

---

## 6. Rollback

If the cutover causes issues, revert **only the repo-B commit** (the `gitops-manifests` merge). This restores the original in-repo dashboard and folder CRs with `spec.url` references, and removes the `OCIRepository`/`Kustomization` grafana-content objects.

```bash
# In gitops-manifests, identify the merge commit SHA
git log --oneline oci/grafana-operator/grafana-manifests/ | head -5

# Revert it (creates a new revert commit, no force-push required)
git revert <merge-commit-sha> --no-edit
git push
```

After the revert lands, Flux will reconcile and re-apply the original in-repo CRs. The OCI artifact at `oci://altinncr.azurecr.io/monitoring/grafana:release` remains in the registry but is unreferenced — it can be left as-is or cleaned up later.

> **Note:** Do not revert the repo-A merge. The `altinn-dashboards-grafana` changes (dashboard CRs using `configMapRef`, the publish workflow, folder definitions) are self-contained and harmless without a consumer.
