# Public dashboards

Azure Managed Grafana cannot share dashboards publicly, so customer-facing dashboards are
served from a separate self-hosted Grafana OSS instance, `grafana-public`
(`dashboards.altinn.cloud`, gitops-manifests `oci/grafana-public`). It runs in the
`grafana-public` namespace with the label `dashboards: public-grafana`. Its one datasource,
`azure-managed-prometheus`, reads `admin-prod-obs-amw` through a workload identity scoped to
that workspace.

| Dashboard | Public link |
|-----------|-------------|
| SLA - Altinn Products | https://dashboards.altinn.cloud/public-dashboards/f78639a049244c32aa7592110334e28c |
| SLA - Service Owners | https://dashboards.altinn.cloud/public-dashboards/05040001fe4c4b2d8b225597f15be856 |

Public dashboards cannot use template variables, so the JSON in `public/dashboards/` is
generated from the platform dashboards by `scripts/build-public-dashboards.py`: it drops the
variables, substitutes each one's "All" value, and points the datasource at the public
instance. It also makes the copies refresh manually only (no refresh intervals to pick) and
leaves out per-dashboard time picker presets, so the instance-wide presets apply: those stop at
one calendar month, because Azure Monitor Prometheus rejects ranges over 32 days. Both limits
are set on the instance (gitops-manifests `oci/grafana-public`, "Time picker and refresh").

Edit the source in the repo-root `dashboards/`, then run the script and commit both. CI fails when the
generated copy is out of date.

To publish another dashboard:

1. Add it to `SOURCES` in `scripts/build-public-dashboards.py` (and its datasource UID to
   `DATASOURCES`, if the public instance has a matching datasource) and run the script.
2. Add a `configMapGenerator` entry in `public/kustomization.yaml` and a `GrafanaDashboard` in
   `public/dashboards.yaml` with `allowCrossNamespaceImport: true`, `resyncPeriod: 1m`, the
   `public-grafana` selector, a `public-grafana-*` folder and a new random
   `publicSharing.accessToken`
   (`python3 -c "import uuid; print(uuid.uuid4())"`).
3. Add its title to `public/dashboards/<group>/.lint`.

Grafana stores the token without dashes, so the link is `/public-dashboards/<accessToken without
dashes>`; the operator also reports it in the CR's `status.publicSharingPath`. The `accessToken`
is the public link and is immutable: never change it once customers have
it. `scripts/validate-dashboards.py` fails if a public dashboard has no token, or if any CR
outside `public/` targets the public instance. Everything under `public/` is visible on the
internet, so check panel titles, text and queries for anything internal before merging.
