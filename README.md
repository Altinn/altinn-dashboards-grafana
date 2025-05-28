# Altinn Grafana Dashboards

A collection of Grafana dashboard configurations for monitoring Altinn infrastructure and services. This repository contains JSON dashboard definitions that can be imported into Grafana for comprehensive observability across different components of the Altinn platform.

## Repository Structure

```
dashboards/
├── altinn/           # Altinn-specific monitoring dashboards
├── fluxcd/           # FluxCD GitOps monitoring dashboards
└── linkerd/          # Linkerd service mesh monitoring dashboards
```

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