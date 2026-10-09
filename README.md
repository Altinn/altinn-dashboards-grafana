# Altinn Grafana Dashboards, Alerts & Datasources

Your product's Grafana dashboards, alerts and datasources, as code. Everything here is a
[grafana-operator](https://github.com/grafana/grafana-operator) custom resource; when it is merged
to `main` it is deployed to the central Grafana (`dis-grafana-prod`) within about five minutes.

- **Edit in Git, not in the Grafana UI.** The UI is for building and trying things out; anything
  you want to keep goes through a pull request. UI edits to a dashboard or rule managed from
  this repository are overwritten on the next sync.
- **Merging is the release.** There is no promotion step and no environment branch.
- **This repository is public.** Never commit secrets, tokens or webhook URLs; they live in Azure
  Key Vault (see [Alerts](#alerts) and [Datasources](#datasources)).

## Your product's directory

Each product owns one directory, and gets one Grafana folder that its dashboards and alert rules
share:

```
products/<product>/
├── dashboards/              # optional
│   ├── kustomization.yaml   #   wraps each JSON into a ConfigMap
│   ├── <name>.yaml          #   GrafanaDashboard → folderRef external-grafana-<product>
│   └── <name>.json          #   the dashboard JSON
├── alerting/
│   ├── kustomization.yaml
│   ├── folder.yaml          #   GrafanaFolder external-grafana-<product>
│   ├── contact-points.yaml  #   GrafanaContactPoint (Slack)
│   └── rules-*.yaml         #   GrafanaAlertRuleGroup(s)
└── datasources/             # optional, reviewed by the platform team
```

**Start by copying [`products/infoportal/`](products/infoportal/)**: it is small and covers
dashboards and alerts. [`products/dialogporten/`](products/dialogporten/) is a larger example
with rules exported from the Grafana UI.

## Onboard a product

1. **Create the folder and alerting overlay.** Copy `products/infoportal/alerting/` to
   `products/<product>/alerting/` and replace the product name, App Insights resource ID and
   query. `folder.yaml` creates the `external-grafana-<product>` folder.
2. **Register it** by adding `products/<product>/alerting` to the `resources:` list in the
   repo-root [`kustomization.yaml`](kustomization.yaml). Do the same for `dashboards` and
   `datasources` when you add them.
3. **Add ownership** to [`CODEOWNERS`](CODEOWNERS):
   `/products/<product>/    @Altinn/team-<product>` (keep the trailing slash).
4. **Ask the platform team for a Slack webhook secret** if you want alert notifications (see
   [Alerts](#alerts)).
5. **Validate locally, open a PR, merge.** CI runs the same checks.

## Dashboards

1. Build the dashboard in Grafana, then **Export → Export as JSON**, with *Export the dashboard
   to use in another instance* switched off.
2. Save it as `products/<product>/dashboards/<name>.json`. Add a `configMapGenerator` entry for it
   in that directory's `kustomization.yaml`, and a `<name>.yaml` `GrafanaDashboard` that points at
   the ConfigMap with `folderRef: external-grafana-<product>`. Copy both from
   [`products/infoportal/dashboards/`](products/infoportal/dashboards/).
3. Keep the dashboard's `uid` stable; links to the dashboard use it.

Tips:

- **Pin datasource UIDs** (for example `azure-monitor-oob`) instead of a `${datasource}` variable.
  A variable often saves the value `default`, and the panels then silently query the wrong
  datasource. Add the dashboard's title to `products/<product>/dashboards/.lint` under
  `panel-datasource-rule` and `template-datasource-rule`, as infoportal does, or the linter fails.
- **Show all environments at once** instead of behind an environment variable: give an Azure
  Monitor query all your App Insights resources and derive the environment from `_ResourceId`.
  [`all-environments.json`](products/infoportal/dashboards/all-environments.json) does this.
- CI fails if a dashboard JSON is not wired into a ConfigMap and a `GrafanaDashboard`, if its
  `folderRef` does not exist, or if the overlay is not registered at the repo root.

## Alerts

A `GrafanaAlertRuleGroup` holds your rules. Each rule is a query (`refId: A`) and a threshold on it
(`refId: C`, `condition: C`). Write the rule by hand
([infoportal](products/infoportal/alerting/rules-exceptions.yaml)), or build it in the Grafana UI,
**Export** it, and paste `data[].model` verbatim ([dialogporten](products/dialogporten/alerting/)).

| Concern | Convention |
|---|---|
| Namespace and instance | `namespace: grafana`, `instanceSelector: { matchLabels: { dashboards: external-grafana } }` |
| Folder | `folderRef: external-grafana-<product>` |
| `uid` | stable and explicit per rule; **reuse it on every edit**. A new `uid` creates a duplicate rule |
| `for` | **required** on every rule; UI exports omit it, so add `for: 0s` |
| Labels | `Product`, `Env`, plus `AlertType` / `Severity` as needed. Use your platform's environment names: `AT22`/`AT23`/`TT02`/`Prod` in dis-core |
| Routing | `notificationSettings.receiver: "<contact point spec.name>"` on each rule |

**Slack notifications.** The webhook URL is never in Git. The platform team stores it in the
`grafana-alerting` Key Vault as `slack-webhook-<product>` and maps it to the key `<product>` in
the `grafana-slack-webhooks` Secret. Your `contact-points.yaml` reads that key through
`valuesFrom`; copy it from infoportal and change the key.

A firing alert re-posts to Slack every 4 hours by default. For state alerts (up / down), set
`notificationSettings.repeat_interval` (snake_case, at most `120h`).

## Datasources

Most products only need the shared Azure Monitor datasource (`azure-monitor-oob`) and the
existing Prometheus workspaces, so check the Grafana datasource list first. To add your own
Prometheus or Tempo connection:

1. Copy [`examples/datasources/`](examples/datasources/) to `products/<product>/datasources/`
   and keep only the datasources you need.
2. Set a unique, stable `spec.uid` (for example `studio-prometheus-experimental`) and reuse it in
   dashboards and alerts. Keep `isDefault: false` and `editable: false`.
3. Store the complete `Authorization` header value (including `Bearer `) in Key Vault
   `grafana-grafana-b607eb82` and point `remoteRef.key` at it. Leave `${authorization}` in Git.
4. Make sure the endpoint is reachable from Azure Managed Grafana. Everyone with access to the
   shared Grafana can query a datasource; product folders do not restrict it.
5. Register the overlay at the repo root. The platform team reviews datasource changes.

Plugins beyond the built-in ones (for example VictoriaLogs) must be enabled in Azure first; ask the
platform team.

## Validate locally

CI runs the same checks. You need [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/)
5.x, [kubeconform](https://github.com/yannh/kubeconform) and Python 3 with PyYAML.

```bash
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

kustomize build . \
  | kubeconform -strict -skip ExternalSecret,SecretStore,Vault,ApplicationIdentity -summary \
      -schema-location default -schema-location "$SCHEMA_LOC" -

python3 scripts/validate-dashboards.py   # dashboard JSON ↔ ConfigMap ↔ GrafanaDashboard wiring
```

## Questions

Ask the platform team (`@Altinn/team-platform`). Shared platform dashboards (`dashboards/`), the
public dashboards ([`public/`](public/README.md)) and the delivery pipeline
([`docs/platform.md`](docs/platform.md)) are maintained by them.

## License

MIT — see [LICENSE](LICENSE).
