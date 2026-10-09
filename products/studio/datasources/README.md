# Studio datasources

Studio's three connections in `products/studio/datasources` share the Key Vault secret
`datasource-altinn-studio-authorization` in Azure Key Vault `grafana-grafana-b607eb82`
(managed by the `grafana-alerting` Vault resource). Store the complete `Bearer <token>` value
there; each connection syncs it into its own Kubernetes Secret.
The datasource SecretStore reuses the `grafana-alerting` service account and its Azure permissions;
Slack keeps the operator-managed `grafana-alerting-secret-store`. If the vault URL changes,
update `platform/secrets/datasource-secret-store.yaml`.
Before deploying the overlay, populate the secret and enable `victoriametrics-logs-datasource`
in Azure Managed Grafana. Prometheus and Tempo use built-in plugins.
