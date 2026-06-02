# Flux repo wiring (goes in the *other* repo, not here)

Dashboards in this repo are pulled by `GrafanaDashboard.spec.url`. Alert CRs
(`GrafanaAlertRuleGroup`, `GrafanaContactPoint`, `GrafanaNotificationPolicy*`) have **no
`spec.url`** — they cannot be fetched by URL, so they must be *applied* by Flux as real
manifests. This repo holds those manifests; the Flux repo points at it with a
`GitRepository` + `Kustomization` and supplies the Slack webhook `Secret`.

Everything below is copy-paste ready for the **Flux repo**. Adjust namespaces/refs to match
that repo's conventions.

## 1. Source + Kustomization

```yaml
# Source: this repo, tracking the same branch the dashboards already use.
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: altinn-dashboards-grafana
  namespace: flux-system
spec:
  interval: 5m
  url: https://github.com/Altinn/altinn-dashboards-grafana.git
  ref:
    branch: release        # same branch GrafanaDashboard.spec.url pins to
---
# Apply the alert CRs into the `grafana` namespace.
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: grafana-alerting
  namespace: flux-system
spec:
  interval: 10m
  prune: true
  sourceRef:
    kind: GitRepository
    name: altinn-dashboards-grafana
  path: "./"               # repo-root kustomization.yaml aggregates products/*/alerting
  targetNamespace: grafana
  dependsOn:
    - name: grafana-operator   # ensure the CRDs exist before applying CRs
  # postBuild:
  #   substitute: {}           # only if any value here is parameterised with ${VAR}
```

Notes:
- `path: "./"` builds this repo's root `kustomization.yaml`, which lists each
  `products/<name>/alerting` overlay. The non-manifest files in this repo (raw dashboard
  JSON, README, workflows) are ignored because the root kustomization only references the
  alerting overlays.
- `targetNamespace: grafana` is belt-and-suspenders: the CRs also declare
  `metadata.namespace: grafana`.

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
2. **No pre-existing root `GrafanaNotificationPolicy`** for `external-grafana` unless you
   intend to adopt routing Option B — there can be only one per instance. With the default
   per-rule routing (Option A) you don't need one. See the README "Routing" section.
3. The `external-grafana-dialogporten` `GrafanaFolder` is defined exactly once. This repo
   ships one in `products/dialogporten/alerting/folder.yaml`; if the Flux repo already
   defines it, delete this repo's copy and keep the Flux repo's.
4. grafana-operator ≥ **v5.21.0** (for `GrafanaContactPoint.spec.receivers[]`) and, only if
   adopting Option B, ≥ **v5.16.0** (for `GrafanaNotificationPolicyRoute`). These are the
   feature-introduction floors; this repo's CI schemas are pinned to **v5.23.0** (see
   `schemas/regenerate.py`) and should track whatever version the cluster actually runs.

## 4. Verify after apply

```bash
# CRs reconciled
kubectl -n grafana get grafanaalertrulegroup dialogporten-exceptions -o jsonpath='{.status}'
kubectl -n grafana get grafanacontactpoint dialogporten-slack-exceptions

# In Grafana UI: folder "Dialogporten" shows the rules; Alerting → Contact points shows
# "Dialogporten Slack Exceptions" (provisioned, read-only) → Test delivers to Slack.
```
