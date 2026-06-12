# Flux repo wiring (goes in the *consumer* repo, not here)

This repo is the single content source for the central Grafana: all platform dashboards
(self-contained `GrafanaDashboard` CRs that reference a wrapped-JSON `ConfigMap` via
`spec.configMapRef`), the 3 platform `GrafanaFolder`s (`external-grafana-altinn/fluxcd/linkerd`),
and every product's alert CRs (`GrafanaAlertRuleGroup`, `GrafanaContactPoint`,
`GrafanaNotificationPolicy*`). CI packages the repo-root kustomize aggregate as **one Flux OCI
artifact** (`oci://altinncr.azurecr.io/monitoring/grafana`) and pushes it to ACR. The consumer
repo (`gitops-manifests`) pulls that single artifact with one `OCIRepository` + one
`Kustomization` and supplies the Slack webhook `Secret`.

Everything below is copy-paste ready for the **consumer repo** (`gitops-manifests`). Adjust
namespaces/refs to match that repo's conventions.

## 1. Source + Kustomization (in gitops-manifests `oci/grafana-operator/grafana-manifests/base/`)

The consumer adds these two files; together they replace the in-repo dashboard CRs + folders
that previously lived in `gitops-manifests`. Azure workload identity in-cluster
(`provider: azure`) authenticates the pull — no registry pull secret is needed when the Flux
source-controller runs with a federated identity that has `AcrPull` on the registry.

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

Notes:
- `path: ./` builds this repo's root `kustomization.yaml`, which aggregates the `dashboards/`
  kustomization (folders + dashboard CRs + the wrapped-JSON ConfigMaps) and each
  `products/<name>/alerting` overlay. Everything the cluster needs ships inside the artifact —
  nothing is fetched by URL.
- `targetNamespace: grafana` is belt-and-suspenders: the CRs also declare
  `metadata.namespace: grafana`.
- **How the artifact is produced:** `.github/workflows/publish-grafana-artifact.yml` runs
  `flux push artifact` (via `Altinn/altinn-platform/actions/flux/build-push-image`) on every
  push to `main`/`release`. Each run pushes an immutable `:<short-commit-sha>` tag and also
  moves the branch tag (`:main` / `:release`), so the `ref.tag: release` above tracks the tip
  of `release` — or pin `ref.tag: <short-sha>` (or use `ref.digest:`) to freeze an exact
  revision. The same push can be done by hand with
  `scripts/publish-grafana-artifact-manual.sh` (e.g.
  `./scripts/publish-grafana-artifact-manual.sh --acr-login --tag release`).

> **Provisioning prerequisites (one-time).** Two values must be agreed with the platform team
> and kept identical on both sides (publisher ↔ consumer):
> - **Registry + repository:** `oci://altinncr.azurecr.io/monitoring/grafana` — set in
>   `.github/workflows/publish-grafana-artifact.yml` (`ARTIFACT_NAME`) and in the
>   `OCIRepository` above.
> - **Push credentials:** the workflow authenticates to ACR via Azure workload-identity
>   federation and needs repo secrets `AZURE_SUBSCRIPTION_ID`, `AZURE_CLIENT_ID`,
>   `AZURE_TENANT_ID` for an app registration that (a) has a federated credential trusting
>   this repo's `main`/`release` refs and (b) holds the `AcrPush` role on the registry.

## 2. Slack webhook Secret

The `GrafanaContactPoint` reads the webhook from a Secret named `grafana-slack-webhooks` in
the `grafana` namespace, one key per product. **Never commit the webhook** (this repo is
public). Recommended source on Azure: External Secrets Operator → Azure Key Vault.

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: grafana-slack-webhooks
  namespace: grafana
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-kv
    kind: ClusterSecretStore
  target:
    name: grafana-slack-webhooks     # <- the Secret the contact point reads
  data:
    - secretKey: dialogporten         # <- matches valuesFrom.secretKeyRef.key
      remoteRef:
        key: grafana-slack-dialogporten-webhook
    # - secretKey: <next-product>
    #   remoteRef: { key: grafana-slack-<next-product>-webhook }
```

SealedSecrets is the simpler fallback if ESO isn't available:

```yaml
# kubeseal < raw-secret.yaml > sealed-secret.yaml ; commit only the sealed output.
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: grafana-slack-webhooks
  namespace: grafana
spec:
  encryptedData:
    dialogporten: AgB...<sealed>...
```

## 3. Pre-flight checks before promoting

1. The `Grafana` CR carries `labels.dashboards: external-grafana` (matches every CR's
   `instanceSelector` in this repo).
2. **The 3 platform folders (`external-grafana-altinn`, `external-grafana-fluxcd`,
   `external-grafana-linkerd`) and all 9 platform dashboards now ship from this artifact** —
   they are no longer defined in `gitops-manifests`. Before promoting, confirm the consumer
   repo has dropped its in-repo dashboard CRs + `folders.yaml` so the operator never sees two
   definitions of the same object.
3. **No pre-existing root `GrafanaNotificationPolicy`** for `external-grafana` unless you
   intend to adopt routing Option B — there can be only one per instance. With the default
   per-rule routing (Option A) you don't need one. See the README "Routing" section.
4. The `external-grafana-dialogporten` `GrafanaFolder` is defined exactly once. This repo
   ships one in `products/dialogporten/alerting/folder.yaml`; if the consumer repo already
   defines it, delete this repo's copy and keep the consumer repo's.
5. grafana-operator ≥ **v5.21.0** (for `GrafanaContactPoint.spec.receivers[]`) and, only if
   adopting Option B, ≥ **v5.16.0** (for `GrafanaNotificationPolicyRoute`). These are the
   feature-introduction floors; this repo's CI schemas are pinned to **v5.23.0** (see
   `schemas/regenerate.py`) and should track whatever version the cluster actually runs.

## 4. Verify after apply

```bash
# Source + sync reconciled
flux get kustomization grafana-content -n flux-system

# CRs reconciled (4 folders, 9 dashboards, 1 contactpoint, 1 alertrulegroup)
kubectl -n grafana get grafanafolder,grafanadashboard,grafanacontactpoint,grafanaalertrulegroup

kubectl -n grafana get grafanaalertrulegroup dialogporten-exceptions -o jsonpath='{.status}'
kubectl -n grafana get grafanacontactpoint dialogporten-slack-exceptions

# In Grafana UI: the Altinn/Fluxcd/Linkerd folders show their dashboards; folder
# "Dialogporten" shows the rules; Alerting → Contact points shows "Dialogporten Slack
# Exceptions" (provisioned, read-only) → Test delivers to Slack.
```
