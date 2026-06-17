# Altinn Grafana Dashboards & Alerts

Grafana dashboards **and alerting-as-code** for Altinn infrastructure and services. Everything
here is [grafana-operator](https://github.com/grafana/grafana-operator) custom resources
(`grafana.integreatly.org/v1beta1`) — platform dashboards as self-contained `GrafanaDashboard`
CRs (`spec.configMapRef` → a wrapped-JSON `ConfigMap`) plus the alert CRs. The whole repo-root
kustomize aggregate is published as **one Flux OCI artifact**
(`oci://altinncr.azurecr.io/monitoring/grafana`) and consumed by `gitops-manifests` — nothing is
imported by hand.

## Repository Structure

```
dashboards/                     # platform dashboards (self-contained configMapRef CRs)
├── kustomization.yaml          #   wraps each JSON into a ConfigMap + lists the CRs
├── folders.yaml                #   3 GrafanaFolder CRs (Altinn/Fluxcd/Linkerd)
├── dashboards.yaml             #   9 GrafanaDashboard CRs
├── altinn/                     #   Altinn dashboard JSON
├── fluxcd/                     #   FluxCD dashboard JSON
└── linkerd/                    #   Linkerd dashboard JSON
products/                       # one folder per product, owning its dashboards + alerts
└── dialogporten/
    ├── dashboards/             #   product dashboard JSON
    └── alerting/               #   operator CRs
        ├── kustomization.yaml
        ├── folder.yaml             # GrafanaFolder
        ├── contact-points.yaml     # GrafanaContactPoint (Slack)
        └── rules-exceptions.yaml   # GrafanaAlertRuleGroup
platform/                       # platform-team infrastructure CRs
└── secrets/                    #   Slack-webhook Key Vault wiring
    ├── application-identity.yaml  # ApplicationIdentity (DIS identity operator)
    ├── vault.yaml                 # Vault (DIS vault operator) + managed SecretStore
    └── external-secret.yaml       # ExternalSecret → grafana-slack-webhooks Secret
schemas/                        # vendored, version-pinned CRD JSON schemas for CI (regenerate.py)
kustomization.yaml              # repo-root aggregator: dashboards/ + each products/*/alerting
scripts/publish-grafana-artifact-manual.sh    # manual `flux push artifact` (mirrors CI)
.github/workflows/              # offline validation CI + OCI publish
```

## Dashboards

**Altinn** (`dashboards/altinn/`)
- `blackbox-exporter.json` — Blackbox Exporter endpoint, TLS and DNS monitoring
- `pod-console-error-logs.json` — Kubernetes pod console error log aggregation
- `publicip.json` — inbound/outbound public IP tracking
- `traefik-official.json` — Traefik reverse proxy health and routing metrics

**FluxCD** (`dashboards/fluxcd/`)
- `flux-cluster-stats.json` — cluster-wide FluxCD statistics
- `flux-control-plane.json` — FluxCD control plane monitoring
- `gitops-flux-application-deployments-dashboard.json` — application deployment tracking

**Linkerd** (`dashboards/linkerd/`)
- `daemonset.json` — DaemonSet monitoring and metrics
- `deployment.json` — Deployment health and performance

## Alerting-as-Code (operator CRs)

Alerts live next to each product's dashboards under `products/<name>/alerting/` as
grafana-operator CRs. **Dialogporten** is the first product. The central Grafana
(`instanceSelector dashboards=external-grafana`, namespace `grafana`) monitors all
environments via Azure Monitor; environments are modelled as separate rules in one group
(Test / YT01 / Staging / Prod).

### Conventions

| Concern | Convention |
|---|---|
| Namespace | `grafana` |
| Instance binding | `instanceSelector: { matchLabels: { dashboards: external-grafana } }` |
| Folder | `folderRef: external-grafana-<product>` (rules + dashboards share it) |
| Labels on every rule | `Product`, `Env` (`Test`/`YT01`/`Staging`/`Prod`), plus `Severity`/`AlertType` |
| Contact point | human name in `spec.name` (rules reference this); DNS-safe `metadata.name` |
| Rule `model` | authored in the Grafana UI → **Export JSON** → paste `data[].model` verbatim |
| UIDs | stable, explicit `uid` per rule — reuse on edit, **never regenerate** |
| `for` | **required** by the CRD on every rule (UI export omits it → add `for: 0s`) |

### Routing

**Option A (default, used here): per-rule `notificationSettings.receiver`.** Every rule names
its product's contact point directly — full per-product ownership, no shared state. All five
Dialogporten rules route to `Dialogporten Slack Exceptions`. **Option B (optional):** a central
`GrafanaNotificationPolicy` (root) plus per-product `GrafanaNotificationPolicyRoute`s for
centralized grouping/inheritance. Because every rule is already labelled `Product=<name>`, it's a
drop-in later. There can be only one root policy per instance, so confirm before adding
`platform/alerting/`.

### Secrets

`GrafanaContactPoint.valuesFrom` reads the Slack webhook from the `grafana-slack-webhooks` Secret
in the `grafana` namespace (one key per product). The webhook value is stored in the
`grafana-alerting` Azure Key Vault — provisioned in-repo by the DIS Vault operator via
`platform/secrets/vault.yaml` — and synced into the `grafana-slack-webhooks` Secret by the
ExternalSecret (ESO) in `platform/secrets/external-secret.yaml`. The value is **never in git or
the artifact** (public repo).

### Add a new product

1. `mkdir -p products/<name>/{dashboards,alerting}`.
2. In `alerting/`, add `contact-points.yaml` (`GrafanaContactPoint`, `valuesFrom` → a **new key**
   in `grafana-slack-webhooks`), `folder.yaml` (`GrafanaFolder external-grafana-<name>`, skip if
   one exists), `rules-*.yaml` (`GrafanaAlertRuleGroup`(s) with `Product`/`Env` labels, `for: 0s`,
   and `notificationSettings.receiver`), and a `kustomization.yaml` listing them.
3. Add `products/<name>/alerting` to the repo-root `kustomization.yaml`.
4. The platform team adds the product's webhook to the `grafana-alerting` Key Vault as
   `slack-webhook-<product>` and adds a matching `data` entry (secretKey `<product>`) to
   `platform/secrets/external-secret.yaml`.
5. Dashboards: drop JSON in `products/<name>/dashboards/`, wrap it into a `ConfigMap`, and add a
   self-contained `GrafanaDashboard` CR. `scripts/validate-dashboards.py` fails if a JSON is added
   without its `configMapGenerator` entry + CR.
6. Add the ownership line to `CODEOWNERS` — `/products/<name>/    @Altinn/team-<name>`.
7. Open a PR → CI validates → merge → promote `main → release`.

### Validate locally

```bash
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
kustomize build products/dialogporten/alerting \
  | kubeconform -strict -summary \
      -schema-location default -schema-location "$SCHEMA_LOC" -
```

## Delivery (OCI artifact)

The whole repo-root aggregate is published as one Flux OCI artifact to
`oci://altinncr.azurecr.io/monitoring/grafana` by
`.github/workflows/publish-grafana-artifact.yml` (on push to `main`/`release`; manual via
`scripts/publish-grafana-artifact-manual.sh`). `gitops-manifests` consumes it through one
`OCIRepository` + `Kustomization` (named `grafana-content`) and applies all CRs into the
`grafana` namespace. Provisioning prerequisite: Azure OIDC secrets
(`DIS_SYNCROOT_AZURE_SUBSCRIPTION_ID`, `DIS_SYNCROOT_AZURE_CLIENT_ID`,
`DIS_SYNCROOT_AZURE_TENANT_ID`) for an identity with the `AcrPush` role, and the artifact path
(`ARTIFACT_NAME` = `monitoring/grafana`).

## Requirements

- **kustomize** 5.x and **kubeconform** (offline validation against the vendored `schemas/`)
- **flux** CLI (manual publish)
- A central Grafana provisioned by grafana-operator with `instanceSelector dashboards=external-grafana`

## License

MIT — see [LICENSE](LICENSE).
