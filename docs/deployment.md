# Deployment Guide

Deploy agentlog to a Kubernetes cluster using Helm.

## Prerequisites

- Kubernetes cluster (1.24+)
- Helm 3
- `kubectl` configured to talk to your cluster
- (Optional) Ingress controller (nginx-ingress) for external UI access
- (Optional) GitHub OAuth app for authentication

## Quick Deploy (no auth, no ingress)

```bash
helm install agentlog ./chart
```

This creates:
- ClickHouse StatefulSet (span storage, 10Gi persistent disk)
- OTel Collector Deployment (span ingestion, port 4317)
- UI Deployment (trace viewer, port 3000)

Access via port-forward:

```bash
kubectl port-forward svc/agentlog-collector 4317:4317 &
kubectl port-forward svc/agentlog-ui 3000:3000 &
```

## Production Deploy (with auth + ingress)

### 1. Create a GitHub OAuth App

Go to https://github.com/settings/developers → New OAuth App:
- Application name: `agentlog`
- Homepage URL: `https://agentlog.yourdomain.com`
- Authorization callback URL: `https://agentlog.yourdomain.com/oauth2/callback`

Note the Client ID and Client Secret.

### 2. Install with auth enabled

```bash
helm install agentlog ./chart \
  --namespace monitoring --create-namespace \
  --set clickhouse.storage=50Gi \
  --set clickhouse.retention=30 \
  --set collector.replicas=2 \
  --set ui.ingress.enabled=true \
  --set ui.ingress.host=agentlog.yourdomain.com \
  --set ui.ingress.tls=true \
  --set ui.auth.enabled=true \
  --set ui.auth.provider=github \
  --set ui.auth.clientId=YOUR_CLIENT_ID \
  --set ui.auth.clientSecret=YOUR_CLIENT_SECRET
```

### 3. Verify

```bash
kubectl get pods -n monitoring
# All pods should show Running + Ready

kubectl get ingress -n monitoring
# Should show your hostname with an address
```

Open `https://agentlog.yourdomain.com` — you should be redirected to GitHub login.

## Pointing your SDK at the cluster

From inside the cluster (agent pods in the same namespace):

```python
agentlog.init(endpoint="agentlog-collector:4317")
```

From a different namespace:

```python
agentlog.init(endpoint="agentlog-collector.monitoring:4317")
```

From outside the cluster (local dev via port-forward):

```python
agentlog.init()  # defaults to localhost:4317
```

## Upgrading

```bash
helm upgrade agentlog ./chart --set clickhouse.retention=60
```

ClickHouse data persists across upgrades (PersistentVolume is not deleted).

## Uninstalling

```bash
helm uninstall agentlog
```

Note: This does NOT delete the PersistentVolumeClaim (your span data). To fully clean up:

```bash
kubectl delete pvc data-agentlog-clickhouse-0
```

## Architecture

```
                  SDK (your agent code)
                      │
                      │ OTLP/gRPC (:4317)
                      ▼
              ┌───────────────┐
              │   Collector   │ ← HPA (auto-scales 1-5 replicas)
              │   Deployment  │
              └───────┬───────┘
                      │ TCP (:9000)
                      ▼
              ┌───────────────┐
              │  ClickHouse   │ ← StatefulSet + PVC (persistent storage)
              │  StatefulSet  │
              └───────┬───────┘
                      │ HTTP (:8123)
                      ▼
              ┌───────────────┐
              │      UI       │ ← behind OAuth2 Proxy (optional)
              │  Deployment   │
              └───────────────┘
                      │
                      ▼
              ┌───────────────┐
              │    Ingress    │ ← external access + TLS
              └───────────────┘
```

## Troubleshooting

### Pods not starting

```bash
kubectl describe pod <pod-name>
kubectl logs <pod-name>
```

Common issues:
- ClickHouse: PVC can't bind (no StorageClass available). Fix: `kubectl get sc` and ensure a default exists.
- Collector: ClickHouse not ready yet. Fix: wait — the collector will retry connecting.
- UI: Image not found. Fix: ensure the image is built and accessible (or loaded into Kind for local testing).

### No spans appearing

1. Check collector is receiving: `kubectl logs deployment/agentlog-collector`
2. Check SDK endpoint is correct: `agentlog.init(endpoint="...")` must match where the collector is reachable
3. Check ClickHouse has data: `kubectl exec agentlog-clickhouse-0 -- clickhouse-client -q "SELECT count() FROM agentlog.spans"`

### Data retention

Spans older than the configured retention (default 30 days) are automatically deleted by ClickHouse's TTL mechanism. To change:

```bash
helm upgrade agentlog ./chart --set clickhouse.retention=90
```

Note: changing retention doesn't retroactively delete old data — it applies to new data going forward.
