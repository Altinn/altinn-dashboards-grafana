# CLAUDE.md

Guidance for Claude instances working in this repo. Keep it accurate — if you change a
convention, update this file in the same PR. The human-facing narrative lives in
[`README.md`](README.md); this file is the agent-facing, copy-paste playbook.

## What this repo is

Grafana **dashboards and alerting-as-code**, entirely as
[grafana-operator](https://github.com/grafana/grafana-operator) custom resources
(`grafana.integreatly.org/v1beta1`). There is **no live Grafana API access from here** — you
edit YAML, CI validates it offline, and the whole repo-root kustomize aggregate is published as
**one Flux OCI artifact** (`oci://altinncr.azurecr.io/monitoring/grafana`) that `gitops-manifests`
applies into the `grafana` namespace. Nothing is imported by hand.

A single **central Grafana** instance renders everything. Every CR binds to it with the same
instance selector and lives in the same namespace:

```yaml
namespace: grafana
instanceSelector:
  matchLabels:
    dashboards: external-grafana
```

Alerts query **Azure Monitor / Application Insights** (datasource `azure-monitor-oob`), not
Prometheus. Environments are modelled as **separate rules**, not separate instances.

## Repo map

```
dashboards/                       # platform dashboards (shared, not product-owned)
products/<product>/
├── dashboards/                   # product dashboards (optional) — own kustomize overlay
│   ├── kustomization.yaml        # configMapGenerator + disableNameSuffixHash: true
│   ├── dashboard.yaml            # GrafanaDashboard CR (folderRef = the product folder)
│   └── <name>.json
└── alerting/
    ├── kustomization.yaml        # lists the files below
    ├── folder.yaml               # GrafanaFolder  external-grafana-<product>
    ├── contact-points.yaml       # GrafanaContactPoint (Slack)
    └── rules-*.yaml              # GrafanaAlertRuleGroup(s)
platform/secrets/                 # Slack-webhook Key Vault → ExternalSecret → Secret wiring
schemas/                          # vendored CRD JSON schemas for offline kubeconform
kustomization.yaml                # repo-root aggregator (dashboards/ + each products/*/alerting)
CODEOWNERS                        # per-product ownership
```

`products/dialogporten/` (full, multi-env, heavily noise-filtered) and `products/infoportal/`
(minimal, prod-only, hand-authored) are the two reference implementations. **Copy
`infoportal/` for a simple new product; copy `dialogporten/` only if you genuinely need its
machinery.**

## Conventions (do not deviate without reason)

| Concern | Convention |
|---|---|
| Namespace | `grafana` |
| Instance binding | `instanceSelector: { matchLabels: { dashboards: external-grafana } }` |
| Folder | `folderRef: external-grafana-<product>` (rules + dashboards share it) |
| Labels on every rule | `Product`, `Env` (`Test`/`YT01`/`Staging`/`Prod`), plus `AlertType`/`Severity` as needed |
| Contact point | human name in `spec.name` (rules reference this string); DNS-safe `metadata.name` |
| Routing | per-rule `notificationSettings.receiver: "<human contact-point name>"` (Option A) |
| Rule `for` | **required by the CRD** on every rule. UI export omits it → add `for: 0s` |
| Rule `uid` | stable + explicit per rule. **Reuse on edit, never regenerate** (regenerating duplicates the rule in Grafana) |

## The Slack-webhook secret flow

The webhook value is **never in git** (public repo). The chain:

1. Platform/product team adds the webhook to the `grafana-alerting` Azure Key Vault as a secret
   named `slack-webhook-<product>` (some are environment-suffixed, e.g.
   `slack-webhook-infoportal-prod` — use the exact name that exists in the vault).
2. `platform/secrets/external-secret.yaml` syncs it into the `grafana-slack-webhooks` k8s Secret.
   Each product gets one `data` entry: `secretKey` is the **short product key**, `remoteRef.key`
   is the **vault secret name**:
   ```yaml
   - secretKey: <product>
     remoteRef:
       key: slack-webhook-<product>[-<env>]
   ```
3. The product's `contact-points.yaml` reads that key via `valuesFrom`:
   ```yaml
   valuesFrom:
     - targetPath: url
       valueFrom:
         secretKeyRef:
           name: grafana-slack-webhooks
           key: <product>          # == secretKey above
   ```

## Alert rule anatomy

A `GrafanaAlertRuleGroup` holds `spec.rules[]`. Each rule is a query (`refId: A`) plus a
threshold expression (`refId: C`) and is wired with `condition: C`.

- **`A`** — `queryType: Azure Log Analytics`, `datasourceUid: azure-monitor-oob`, with the KQL in
  `model.azureLogAnalytics.query`. `dashboardTime: true` + `relativeTimeRange.from` (seconds) sets
  the lookback window with **no `ago()` in the KQL**. `resources: [<App Insights resource ID>]`.
- **`C`** — `datasourceUid: __expr__`, `type: threshold`, `expression: A`, evaluator e.g. `gt 0`.
- If the query `summarize`s into multiple rows, **each row becomes its own alert instance** and
  its non-numeric columns ride along as labels into the Slack message — so `project` a numeric
  count column plus whatever you want shown (e.g. `Type`, `Details`).

**Two ways to author the `model`:**
- **Hand-authored** (see `products/infoportal/`): fine for simple rules. Pick a stable readable
  `uid` like `<product>-exceptions-prod`. Tradeoff: if someone later builds it in the Grafana UI
  and re-exports, the UID won't match unless they preserve it.
- **UI export** (see `products/dialogporten/`): author in the Grafana UI → **Export JSON** →
  paste `data[].model` **verbatim**, then add `for: 0s`. Do not hand-edit exported `model` blocks
  or regenerate their UIDs.

## How to add a new product

Worked example: this is exactly how `products/infoportal/` was added.

1. **Create the overlay** `products/<product>/alerting/` with four files. Copy them from
   `products/infoportal/alerting/` and substitute `<product>` / `Infoportal` / the App Insights
   resource ID / the KQL filter:
   - `folder.yaml` — `GrafanaFolder` `external-grafana-<product>`, `spec.title: <Product>`.
   - `contact-points.yaml` — `GrafanaContactPoint`, DNS-safe `metadata.name`, human
     `spec.name: "<Product> Slack Exceptions"`, `valuesFrom` → `grafana-slack-webhooks` key
     `<product>`.
   - `rules-exceptions.yaml` — `GrafanaAlertRuleGroup` with `folderRef: external-grafana-<product>`,
     one rule per environment (`Exceptions Prod`, …), each with `for: 0s`, labels
     `Product`/`Env`/`AlertType`, `notificationSettings.receiver: "<Product> Slack Exceptions"`,
     and the `A`+`C` query/threshold pair.
   - `kustomization.yaml` — lists the three files above.
2. **Register the overlay** in the repo-root `kustomization.yaml` (`resources:` list).
3. **Wire the secret** — add a `data` entry to `platform/secrets/external-secret.yaml` (see the
   secret-flow section). Confirm the vault secret name with the team; it may be env-suffixed.
4. **Add ownership** to `CODEOWNERS`: `/products/<product>/    @Altinn/team-<product>`.
5. **Validate locally** (see below), open a PR, let CI pass, merge, then promote `main → release`.

Minimal-product KQL pattern (severity-3 traces grouped into actionable instances):

```kql
traces
| where cloud_RoleName == "<role>"
| where severityLevel >= 3
| extend ExType = tostring(customDimensions.['exception.type'])
| extend ExMsg = tostring(customDimensions.['exception.message'])
| extend Details = iff(isnotempty(ExMsg), ExMsg, message)
| summarize Count = count() by Type = ExType, Details = substring(Details, 0, 200)
| project Type, Details, Count
```

## How to expand an existing product

- **Add an environment** (e.g. Staging): add another entry to `spec.rules[]` in the product's
  `rules-*.yaml` — new stable `uid`, `Env: Staging` label, the staging App Insights resource ID,
  and (if it's a separate webhook) wire a new secret key + contact point. If one webhook serves
  all envs, reuse the existing contact point.
- **Add another alert type** (e.g. latency, a specific exception): add a new rule to the group, or
  a new `rules-<topic>.yaml` file listed in the product's `kustomization.yaml`. Give it
  `Severity`/`AlertType` labels so routing/grouping stays meaningful.
- **Add a dashboard**: drop JSON in `products/<product>/dashboards/` and give that directory its
  own overlay — `kustomization.yaml` (`configMapGenerator` + `generatorOptions.
  disableNameSuffixHash: true`, so the CR can reference the ConfigMap by a stable name) and a
  self-contained `GrafanaDashboard` CR pointing at it via `spec.configMapRef`, with
  `folderRef: external-grafana-<product>` so it lands beside the product's alerts. Then register
  `products/<product>/dashboards` in the repo-root `kustomization.yaml`.
  **Copy `products/infoportal/dashboards/`** — it is the reference implementation.
  `scripts/validate-dashboards.py` (a CI gate) covers both `dashboards/*/*.json` and
  `products/*/dashboards/*.json`, and **fails if a dashboard JSON is not wired into both a
  ConfigMap and a CR**, if a `folderRef` doesn't resolve, or if a product overlay is missing from
  the root kustomization.
- **Pin datasource UIDs in dashboard JSON** (`azure-monitor-oob`, `admin-prod-obs-amw`) rather
  than using a `${datasource}` template variable. The variable saves the value `default`, the
  default datasource is Azure Monitor rather than Prometheus, and Grafana then silently falls
  back to the *first* Prometheus datasource — which in `dis-grafana-prod` is a `dis-core` AMW
  holding no probe data. Panels render empty with no error.
- **Edit an existing rule**: keep the `uid`. Changing it orphans the old rule and creates a
  duplicate in Grafana.

## Validate locally (matches CI)

```bash
SCHEMA_LOC='schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

# 1. kustomize must build the new overlay AND the root aggregate
kustomize build products/<product>/alerting
kustomize build .

# 2. kubeconform -strict against the vendored schemas (CI pins v0.6.7)
kustomize build products/<product>/alerting \
  | kubeconform -strict -ignore-missing-schemas -summary -verbose \
      -schema-location default -schema-location "$SCHEMA_LOC" -
kustomize build . \
  | kubeconform -strict -ignore-missing-schemas -summary -verbose \
      -schema-location default -schema-location "$SCHEMA_LOC" -

# 3. relaxed yamllint (long-line warnings are OK; errors are not)
yamllint -d relaxed products platform dashboards kustomization.yaml
```

`ExternalSecret`, `Vault`, and `ApplicationIdentity` show as **skipped** in kubeconform — they
have no vendored schema, which is expected (`-ignore-missing-schemas`).

Also run `python3 scripts/validate-dashboards.py` if you touched any dashboard wiring.

## Gotchas

- **`severityLevel` is numeric.** Use `severityLevel >= 3`, not `== "3"` — a string compare can
  silently match nothing.
- **`for: 0s` is mandatory.** The CRD rejects a rule without it; Grafana UI exports omit it.
- **A firing alert re-notifies every 4h by default.** Nothing here defines a
  `GrafanaNotificationPolicy`, so every rule inherits the central Grafana root policy
  (`group_wait 30s`, `group_interval 5m`, **`repeat_interval 4h`**). A long incident re-posts the
  *same* firing message every 4h, which reads like repeated independent failures. For state-style
  alerts (availability/probe) where one firing + one resolve is the whole story, set
  `notificationSettings.repeat_interval` explicitly — the CRD field is **snake_case**
  (`repeat_interval`, not `repeatInterval`; `additionalProperties: false` rejects the camelCase
  spelling). Grafana caps it at **120h** and coerces it to a multiple of `group_interval`.
- **Never regenerate a rule `uid`.** Reuse it on every edit.
- **Azure resource IDs are case-insensitive but use canonical casing** (`resourceGroups`,
  `Microsoft.Insights`) for consistency with existing rules — Azure Portal exports often
  lowercase them.
- **The webhook secret name may be environment-suffixed** in the vault
  (`slack-webhook-<product>-prod`). Match the actual vault name in `remoteRef.key`; the
  `secretKey`/contact-point `key` stays the short `<product>`.
- **Anchor PromQL label regexes explicitly.** In Azure Managed Prometheus,
  `job=~"blackbox-http-ipv[46]"` also matched `blackbox-http-ipv4-health-check` — do not rely on
  `=~` being fully anchored. Write `job=~"blackbox-http-ipv[46]$"` when you mean the shallow
  probes only. Verified 2026-08-26; the deep and shallow probes report very different numbers, so
  getting this wrong silently mixes them.
- **Collapse prober pods before averaging over time.** Blackbox runs on two replicas and pods
  churn, so `avg_over_time(probe_success[...])` then `max` lets a short-lived replica mask an
  outage. Use a subquery instead:
  `avg_over_time((max by (instance) (probe_success{...}))[$__range:1m])`.
- **One OCI artifact, no partial apply.** A broken CR can block the whole artifact — keep
  `kustomize build .` green.
