# KAOS-UI Configuration Guide

This document covers all configuration options for KAOS-UI.

## Table of Contents

- [Environment Variables](#environment-variables)
- [URL Parameters](#url-parameters)
- [Local Storage](#local-storage)
- [Build Configuration](#build-configuration)

---

## Environment Variables

KAOS-UI is a static frontend application and uses environment variables at build time.

### Vite Environment Variables

Create a `.env` file in the project root:

```env
# Base URL for the application (for subdirectory deployments)
VITE_BASE_URL=/

# Default Kubernetes API URL (optional)
VITE_DEFAULT_K8S_URL=http://localhost:8010
```

### Build-time Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `/` | Application base path |

---

## URL Parameters

KAOS-UI supports configuration via URL parameters:

### Connection Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kubernetesUrl` | string | `http://localhost:8010` | Kubernetes API proxy URL |
| `namespace` | string | `default` | Initial namespace to select |

### Examples

**Connect to a remote cluster:**
```
https://kaos-ui.example.com/?kubernetesUrl=https://k8s-proxy.example.com
```

**Connect with a specific namespace:**
```
https://kaos-ui.example.com/?kubernetesUrl=https://k8s-proxy.example.com&namespace=production
```

**Override namespace only:**
```
https://kaos-ui.example.com/?namespace=staging
```

### Parameter Behavior

1. **kubernetesUrl**: If provided, overrides any saved configuration and auto-connects
2. **namespace**: If provided with `kubernetesUrl`, uses that namespace; if provided alone, overrides the saved namespace

---

## Local Storage

KAOS-UI persists settings in browser localStorage:

### Stored Keys

| Key | Format | Description |
|-----|--------|-------------|
| `k8s-config` | JSON | Connection settings |
| `theme` | string | Current theme (light/dark/system) |
| `kaos-kubernetes-store` | JSON | Application state (Zustand) |

### k8s-config Structure

```json
{
  "baseUrl": "https://k8s-proxy.example.com",
  "namespace": "default"
}
```

### Clearing Settings

To reset all settings:
1. Open browser DevTools (F12)
2. Go to Application → Local Storage
3. Delete keys starting with `kaos-` or `k8s-`

Or use the browser console:
```javascript
localStorage.removeItem('k8s-config');
localStorage.removeItem('theme');
localStorage.removeItem('kaos-kubernetes-store');
```

---

## Build Configuration

### Vite Configuration

The `vite.config.ts` file contains build settings:

```typescript
export default defineConfig({
  base: process.env.BASE_URL || '/',
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  // ...
});
```

### GitHub Pages Configuration

For GitHub Pages deployment, the base URL is automatically set to the repository name:

```typescript
base: '/kaos-ui/'
```

### Custom Deployment

For custom deployments, set the `BASE_URL` environment variable:

```bash
# Netlify
BASE_URL=/ npm run build

# Subdirectory deployment
BASE_URL=/dashboard/ npm run build
```

---

## Tailwind Configuration

Theme customization is done in `tailwind.config.ts`:

### Color Tokens

All colors use semantic tokens for proper theming:

```typescript
colors: {
  primary: "hsl(var(--primary))",
  background: "hsl(var(--background))",
  foreground: "hsl(var(--foreground))",
  // ...
}
```

### Custom Colors

KAOS-UI includes custom colors for resource types:

```css
/* src/index.css */
:root {
  --agent: 142 76% 36%;    /* Green for agents */
  --mcp: 262 83% 58%;      /* Purple for MCP servers */
  --modelapi: 45 93% 47%;  /* Yellow for Model APIs */
}
```

---

## Kubernetes RBAC

KAOS-UI requires appropriate RBAC permissions on the cluster.

### Required Permissions

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kaos-ui-reader
rules:
  # Custom Resources
  - apiGroups: ["kaos.io"]
    resources: ["agents", "mcpservers", "modelapis"]
    verbs: ["get", "list", "watch", "create", "update", "delete"]
  
  # Core Resources
  - apiGroups: [""]
    resources: ["pods", "pods/log", "secrets", "namespaces", "services"]
    verbs: ["get", "list", "watch", "create", "delete"]
  
  # Deployments
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch"]
```

### Namespace-scoped Access

For restricted access:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kaos-ui-reader
  namespace: my-namespace
rules:
  # Same rules as above
```

---

## Proxy Configuration

KAOS-UI connects to Kubernetes via an API proxy.

### kubectl proxy

The simplest option for local development:

```bash
kubectl proxy --port=8010 --address=0.0.0.0 --accept-hosts='.*'
```

### CORS Proxy

For production, use a CORS-enabled proxy:

```yaml
# Example: nginx configuration
server {
    listen 80;
    
    location / {
        proxy_pass https://kubernetes.default.svc;
        
        # CORS headers
        add_header 'Access-Control-Allow-Origin' '*';
        add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
        add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type';
        
        # Handle preflight
        if ($request_method = 'OPTIONS') {
            return 204;
        }
    }
}
```

### Security Considerations

- Never expose kubectl proxy directly to the internet
- Use authentication/authorization on your proxy
- Consider using a VPN or private network
- Limit CORS origins in production

---

## Auto-Refresh Settings

Configure auto-refresh behavior in Settings or via the header control:

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Enabled | on/off | on | Toggle auto-refresh |
| Interval | 5s-120s | 30s | Refresh frequency |

### Programmatic Control

The refresh interval is stored in Zustand and can be modified:

```typescript
// Access store
const { autoRefreshEnabled, autoRefreshInterval, setAutoRefreshInterval } = useKubernetesStore();

// Change interval to 10 seconds
setAutoRefreshInterval(10000);
```

---

*Last updated: January 2026*
