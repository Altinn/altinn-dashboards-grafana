# Studio datasources

Studio's four connections in `products/studio/datasources` share the Key Vault secret
`datasource-altinn-studio-authorization` in Azure Key Vault `grafana-grafana-b607eb82`
(managed by the `grafana-alerting` Vault resource). Store the complete `Bearer <token>` value
there; each connection syncs it into its own Kubernetes Secret.
The datasource SecretStore reuses the `grafana-alerting` service account and its Azure permissions;
Slack keeps the operator-managed `grafana-alerting-secret-store`. If the vault URL changes,
update `platform/secrets/datasource-secret-store.yaml`.
Before deploying the overlay, populate the secret and enable `victoriametrics-logs-datasource`
in Azure Managed Grafana. Prometheus and Tempo use built-in plugins.

`altinn-studio-traces-logsql` uses the VictoriaLogs plugin on VictoriaTraces' LogsQL API, through
the proxy's `traces-logsql` prefix, so it queries the same spans as `altinn-studio-traces` with
LogsQL instead of TraceQL. Besides a row per span, VictoriaTraces stores trace index rows (the
`trace_id_idx_stream` stream), whose `duration` is the whole trace's. Filter on a span field, such
as `name:*` or a `{resource_attr:service.name="..."}` stream filter, before `stats count()` or
`quantile(0.95, duration)`, or the index rows are counted too.
