# Altinn Grafana Dashboards & Alerts

Grafana dashboards **and alerting-as-code** for monitoring Altinn infrastructure and
services. Dashboards are raw JSON consumed by the central Grafana over a `GrafanaDashboard`
URL; alerts are [grafana-operator](https://github.com/grafana/grafana-operator) custom
resources applied from this repo by Flux. See **[Alerting-as-Code](#alerting-as-code-operator-crs)**.

## Repository Structure

```
dashboards/                     # platform/infra dashboard JSON (fetched by URL from the Flux repo)
├── altinn/                     #   Altinn-specific monitoring dashboards
├── fluxcd/                     #   FluxCD GitOps monitoring dashboards
└── linkerd/                    #   Linkerd service mesh monitoring dashboards
products/                       # one folder per product, owning its dashboards + alerts
└── dialogporten/
    ├── dashboards/             #   product dashboard JSON (consumed by URL, like dashboards/ above)
    └── alerting/               #   operator CRs, APPLIED from this repo by Flux
        ├── kustomization.yaml
        ├── folder.yaml             # GrafanaFolder
        ├── contact-points.yaml     # GrafanaContactPoint (Slack, webhook from a Secret)
        └── rules-exceptions.yaml   # GrafanaAlertRuleGroup (Test/YT01/Staging/Prod + more)
schemas/                        # vendored, version-pinned CRD JSON schemas for CI (regenerate.py)
kustomization.yaml              # repo-root aggregator: lists each products/*/alerting overlay
docs/flux-repo-wiring.md        # copy-paste GitRepository + Kustomization + Secret for the Flux repo
.github/workflows/validate-alerting.yml
```

> **Layout note:** `dashboards/{altinn,fluxcd,linkerd}/` is the platform/infra area and is left
> in place. Relocating it under `platform/dashboards/` is a deferred, coordinated follow-up —
> it would break the Flux repo's `GrafanaDashboard.spec.url` paths, so it must be sequenced
> (add new-path copies → update the Flux repo's URLs → remove old paths) and is intentionally
> out of scope here.

## Dashboard Categories

### Altinn Dashboards (`dashboards/altinn/`)

Core monitoring dashboards for Altinn platform components:

- **`blackbox-exporter.json`** - Prometheus Blackbox Exporter dashboard for endpoint monitoring
  - HTTP status codes and response times
  - DNS lookup performance
  - SSL certificate expiry monitoring
  - TLS version tracking
  - Network connectivity health checks

- **`pod-console-error-logs.json`** - Pod Console Error Logs dashboard
  - Kubernetes pod error log aggregation
  - Console error tracking and analysis

- **`publicip.json`** - Public IP monitoring dashboard
  - Inbound and outbound IP address tracking
  - Network connectivity monitoring

- **`traefik-official.json`** - Traefik reverse proxy monitoring
  - Instance health and status
  - Request routing metrics
  - Load balancer performance

### FluxCD Dashboards (`dashboards/fluxcd/`)

GitOps monitoring dashboards for FluxCD operations:

- **`flux-cluster-stats.json`** - Cluster-wide FluxCD statistics
- **`flux-control-plane.json`** - FluxCD control plane monitoring
- **`gitops-flux-application-deployments-dashboard.json`** - Application deployment tracking

### Linkerd Dashboards (`dashboards/linkerd/`)

Service mesh monitoring for Linkerd:

- **`daemonset.json`** - DaemonSet monitoring and metrics
- **`deployment.json`** - Deployment health and performance tracking

## Usage

### Importing Dashboards

1. **Via Grafana UI:**
   - Navigate to Grafana → Dashboards → Import
   - Upload the JSON file or paste the JSON content
   - Configure data sources as needed

2. **Via API:**
   ```bash
   curl -X POST \
     http://your-grafana-instance/api/dashboards/db \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d @path/to/dashboard.json
   ```

3. **Via Provisioning:**
   - Place JSON files in Grafana's provisioning directory
   - Configure `dashboards.yaml` provisioning file

### Data Source Requirements

These dashboards require the following data sources to be configured in Grafana:

- **Prometheus** - For metrics collection and monitoring
- **Loki** (for log dashboards) - For log aggregation and analysis

### Configuration

Before importing, ensure your Grafana instance has:

1. Prometheus data source configured and accessible
2. Appropriate permissions for dashboard management
3. Required Grafana version (8.1.0 or higher recommended)

## Dashboard Customization

Each dashboard JSON file can be customized by:

1. Modifying panel queries and visualizations
2. Adjusting time ranges and refresh intervals
3. Updating variable definitions and filters
4. Customizing alert thresholds and notifications

## Alerting-as-Code (operator CRs)

Alerts live next to each product's dashboards under `products/<name>/alerting/` as
[grafana-operator](https://github.com/grafana/grafana-operator) custom resources
(`grafana.integreatly.org/v1beta1`). **Dialogporten** is the first product.

**Why these are real manifests (not URLs):** `GrafanaDashboard` is fetched by `spec.url`,
but alert CRs (`GrafanaAlertRuleGroup`, `GrafanaContactPoint`, `GrafanaNotificationPolicy*`)
have **no `spec.url`** — they must be *applied* by Flux. So they live here and the Flux repo
points at this repo with a `GitRepository` + `Kustomization`
(see **[docs/flux-repo-wiring.md](docs/flux-repo-wiring.md)**).

The central Grafana (`instanceSelector dashboards=external-grafana`, namespace `grafana`,
Azure Monitor datasource `azure-monitor-oob`) monitors all environments via Azure Monitor.
**Environments are modelled as separate rules in one group** (Test / YT01 / Staging / Prod),
not separate clusters.

### Building blocks (per product)

| File | Kind | Purpose |
|---|---|---|
| `folder.yaml` | `GrafanaFolder` | The product's folder (`external-grafana-<product>`). Define **once** — omit if the Flux repo already ships it. |
| `contact-points.yaml` | `GrafanaContactPoint` | Slack receiver; webhook injected from a Secret via `valuesFrom` (never committed). |
| `rules-exceptions.yaml` | `GrafanaAlertRuleGroup` | The rules; `data[].model` pasted verbatim from a Grafana UI export. |
| `routes.yaml` *(optional)* | `GrafanaNotificationPolicyRoute` | Only for routing Option B (see below). |

### Conventions

| Concern | Convention |
|---|---|
| Namespace | `grafana` (same as the `Grafana` CR → no cross-namespace import) |
| Instance binding | `instanceSelector: { matchLabels: { dashboards: external-grafana } }` |
| Folder | `folderRef: external-grafana-<product>` (rules + dashboards share it) |
| Labels on every rule | `Product`, `Env` (`Test`/`YT01`/`Staging`/`Prod`), plus `Severity`/`AlertType` where relevant |
| Contact point | human name in `spec.name` (rules reference this); DNS-safe `metadata.name` |
| Rule `model` | author in the Grafana UI → **Export JSON** → paste `data[].model` verbatim |
| UIDs | stable, explicit `uid` per rule — reuse on edit, **never regenerate** |
| `for` | **required** by the CRD on every rule (the UI export omits it → add `for: 0s`) |

### Routing — how alerts reach Slack

**Option A (default, used here): per-rule `notificationSettings.receiver`.** Every rule names
its product's contact point directly. Full per-product ownership, zero shared state, no
singleton to coordinate. This repo uses Option A — all five Dialogporten rules route to
`Dialogporten Slack Exceptions`.

**Option B (optional scale-up): central root policy + per-product routes.** When you later
want centralized grouping / mute-timings / inheritance, the platform team owns one
`GrafanaNotificationPolicy` (root) with a `routeSelector`, and each product ships a
`GrafanaNotificationPolicyRoute` matched by label. Because every rule is already labelled
`Product=<name>`, it's a drop-in later with no rule changes.

> ⚠️ **Singleton risk:** there can be only **one** root notification policy per Grafana
> instance. Do **not** add `platform/alerting/root-notification-policy.yaml` if the Flux repo
> already defines a root policy for `external-grafana` — extend the existing one's
> `routeSelector` instead. Confirm before adding `platform/alerting/`.

### Secrets (Slack)

`GrafanaContactPoint.valuesFrom` reads the webhook from the `grafana-slack-webhooks` Secret
in the `grafana` namespace — **one key per product**. The Secret is created in-cluster from
the Flux repo (External Secrets → Azure Key Vault, or SealedSecrets). It is **never committed
here** (public repo). See [docs/flux-repo-wiring.md](docs/flux-repo-wiring.md).

### Add a new product

1. `mkdir -p products/<name>/{dashboards,alerting}`.
2. In `alerting/`, add:
   - `contact-points.yaml` — `GrafanaContactPoint` (Slack), `valuesFrom` → a **new key** in
     the `grafana-slack-webhooks` Secret.
   - `folder.yaml` — `GrafanaFolder external-grafana-<name>` (skip if one already exists).
   - `rules-*.yaml` — `GrafanaAlertRuleGroup`(s) with `Product: <name>` + `Env` labels,
     `for: 0s`, and `notificationSettings.receiver` pointing at the contact point's `spec.name`.
   - `kustomization.yaml` listing those files.
3. Add `products/<name>/alerting` to the repo-root `kustomization.yaml`.
4. Add the product's Slack webhook key to the Flux repo's `ExternalSecret`.
5. Dashboards: drop JSON in `products/<name>/dashboards/`; add the `GrafanaDashboard` URL-CR
   in the Flux repo (as today).
6. Open a PR → CI validates → merge → promote `main → release`.

### Validate locally

CI (`.github/workflows/validate-alerting.yml`) runs offline: `kustomize build` +
`kubeconform -strict` against the vendored CRD schemas in `schemas/` (pinned to
grafana-operator **v5.23.0**), plus `dashboard-linter` on changed dashboard JSON. To run the
same check locally:

```bash
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
kustomize build products/dialogporten/alerting \
  | kubeconform -strict -summary \
      -schema-location default -schema-location "$SCHEMA_LOC" -
```

When the cluster's grafana-operator is upgraded, bump `OPERATOR_VERSION` in
`schemas/regenerate.py` and re-run it to refresh the vendored schemas.

> `kubeconform` checks shape/types/required/enums only. It does **not** verify that
> `folderRef` resolves, that `condition` points at a real `refId`, or that the Azure `model`
> query is valid. A `kubectl apply --dry-run=server` against a cluster with the CRDs can be
> added later as a deeper pre-deploy gate.

## Contributing

When contributing new dashboards or modifications:

1. Ensure dashboards are exported from Grafana in JSON format
2. Remove any environment-specific data source UIDs
3. Test dashboard imports on a clean Grafana instance
4. Document any special requirements or dependencies

## Requirements

- **Grafana:** 8.1.0 or higher
- **Prometheus:** Compatible version for data source
- **Kubernetes:** For pod and service monitoring dashboards
- **FluxCD:** For GitOps monitoring dashboards
- **Linkerd:** For service mesh monitoring dashboards

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues related to:
- Dashboard functionality: Check Grafana documentation and panel configurations
- Data source connectivity: Verify Prometheus and other data source configurations
- Platform-specific metrics: Consult respective component documentation (FluxCD, Linkerd, etc.)

---

**Note:** These dashboards are designed for the Altinn platform infrastructure. You may need to adjust queries and panel configurations based on your specific environment and metric naming conventions.