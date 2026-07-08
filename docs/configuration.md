# Configuration Reference

All configurable values for the agentlog Helm chart.

## ClickHouse

| Value | Default | Description |
|-------|---------|-------------|
| `clickhouse.image` | `clickhouse/clickhouse-server:24.8` | ClickHouse Docker image |
| `clickhouse.storage` | `10Gi` | Persistent disk size for span data |
| `clickhouse.retention` | `30` | Days before spans are auto-deleted (TTL) |
| `clickhouse.resources.requests.cpu` | `250m` | Minimum CPU guaranteed |
| `clickhouse.resources.requests.memory` | `512Mi` | Minimum memory guaranteed |
| `clickhouse.resources.limits.cpu` | `1` | Maximum CPU allowed |
| `clickhouse.resources.limits.memory` | `2Gi` | Maximum memory (OOMKilled if exceeded) |

### Sizing guidance

- **Small** (dev/testing, <100 traces/day): `storage=5Gi`, default resources
- **Medium** (team use, <10k traces/day): `storage=50Gi`, `limits.memory=4Gi`
- **Large** (production, >10k traces/day): `storage=200Gi`, `limits.memory=8Gi`, consider dedicated node

## Collector

| Value | Default | Description |
|-------|---------|-------------|
| `collector.image` | `otel/opentelemetry-collector-contrib:0.110.0` | Collector Docker image |
| `collector.replicas` | `1` | Starting replica count (HPA scales from here) |
| `collector.resources.requests.cpu` | `100m` | Minimum CPU guaranteed |
| `collector.resources.requests.memory` | `128Mi` | Minimum memory guaranteed |
| `collector.resources.limits.cpu` | `500m` | Maximum CPU allowed |
| `collector.resources.limits.memory` | `512Mi` | Maximum memory allowed |

### Autoscaling

The HPA scales the collector between `replicas` (min) and 5 (max) based on:
- CPU utilization > 70%
- Memory utilization > 80%

For high-throughput deployments, increase the memory limit (the batch buffer is the main memory consumer).

## UI

| Value | Default | Description |
|-------|---------|-------------|
| `ui.image` | `agentlog-ui:latest` | UI Docker image |
| `ui.replicas` | `1` | Number of UI pods |
| `ui.resources.requests.cpu` | `50m` | Minimum CPU |
| `ui.resources.requests.memory` | `64Mi` | Minimum memory |
| `ui.resources.limits.cpu` | `250m` | Maximum CPU |
| `ui.resources.limits.memory` | `256Mi` | Maximum memory |

## Ingress

| Value | Default | Description |
|-------|---------|-------------|
| `ui.ingress.enabled` | `false` | Create an Ingress resource |
| `ui.ingress.host` | `agentlog.example.com` | Hostname for the UI |
| `ui.ingress.tls` | `false` | Enable TLS (requires cert-manager or manual cert) |

## Authentication

| Value | Default | Description |
|-------|---------|-------------|
| `ui.auth.enabled` | `false` | Enable OAuth2 Proxy in front of UI |
| `ui.auth.provider` | `github` | OAuth provider (`github` or `google`) |
| `ui.auth.clientId` | `""` | OAuth app client ID |
| `ui.auth.clientSecret` | `""` | OAuth app client secret |

### Setting up GitHub OAuth

1. Go to https://github.com/settings/developers
2. New OAuth App
3. Set callback URL to `https://<your-host>/oauth2/callback`
4. Pass the client ID and secret via `--set` or a values file

### Restricting access by email domain

By default, any GitHub/Google account can login. To restrict to a specific domain, add a custom values file:

```yaml
# values-prod.yaml
ui:
  auth:
    enabled: true
    provider: github
    clientId: "your-id"
    clientSecret: "your-secret"
```

Then install with:

```bash
helm install agentlog ./chart -f values-prod.yaml
```

## Example configurations

### Local development (Kind)

```bash
helm install agentlog ./chart
# Access via port-forward
```

### Team staging

```bash
helm install agentlog ./chart \
  --set clickhouse.storage=20Gi \
  --set clickhouse.retention=14 \
  --set ui.ingress.enabled=true \
  --set ui.ingress.host=agentlog.staging.internal
```

### Production with auth

```bash
helm install agentlog ./chart \
  --namespace monitoring --create-namespace \
  --set clickhouse.storage=100Gi \
  --set clickhouse.retention=60 \
  --set collector.replicas=2 \
  --set ui.ingress.enabled=true \
  --set ui.ingress.host=agentlog.company.com \
  --set ui.ingress.tls=true \
  --set ui.auth.enabled=true \
  --set ui.auth.provider=github \
  --set ui.auth.clientId=xxx \
  --set ui.auth.clientSecret=yyy
```
