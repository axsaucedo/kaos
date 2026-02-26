# KAOS-UI Deployment Guide

This document covers deployment options for KAOS-UI.

## Table of Contents

- [GitHub Pages](#github-pages)
- [Netlify](#netlify)
- [Vercel](#vercel)
- [Docker](#docker)
- [Kubernetes](#kubernetes)
- [Custom Deployment](#custom-deployment)

---

## GitHub Pages

KAOS-UI includes automatic GitHub Pages deployment via GitHub Actions.

### Automatic Deployment

The repository is configured for automatic deployment on push to `main`:

```yaml
# .github/workflows/deploy.yml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm run build
      - uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./dist
```

### Manual Deployment

```bash
# Build the project
npm run build

# Deploy to gh-pages branch
npx gh-pages -d dist
```

### Configuration

Ensure `vite.config.ts` has the correct base path:

```typescript
export default defineConfig({
  base: '/kaos-ui/', // Repository name
  // ...
});
```

---

## Netlify

### Option 1: Netlify CLI

```bash
# Install Netlify CLI
npm install -g netlify-cli

# Build
npm run build

# Deploy
netlify deploy --prod --dir=dist
```

### Option 2: Git Integration

1. Connect your GitHub repository to Netlify
2. Configure build settings:
   - Build command: `npm run build`
   - Publish directory: `dist`
   - Node version: `20`

### netlify.toml

```toml
[build]
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

---

## Vercel

### Option 1: Vercel CLI

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
vercel --prod
```

### Option 2: Git Integration

1. Import your GitHub repository in Vercel
2. Framework Preset: Vite
3. Build settings are auto-detected

### vercel.json

```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

---

## Docker

### Dockerfile

```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### nginx.conf

```nginx
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    server {
        listen 80;
        root /usr/share/nginx/html;
        index index.html;

        # SPA routing
        location / {
            try_files $uri $uri/ /index.html;
        }

        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}
```

### Build and Run

```bash
# Build image
docker build -t kaos-ui:latest .

# Run container
docker run -p 8080:80 kaos-ui:latest
```

---

## Kubernetes

Deploy KAOS-UI as a Kubernetes application.

### Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kaos-ui
  labels:
    app: kaos-ui
spec:
  replicas: 2
  selector:
    matchLabels:
      app: kaos-ui
  template:
    metadata:
      labels:
        app: kaos-ui
    spec:
      containers:
        - name: kaos-ui
          image: your-registry/kaos-ui:latest
          ports:
            - containerPort: 80
          resources:
            requests:
              memory: "64Mi"
              cpu: "50m"
            limits:
              memory: "128Mi"
              cpu: "100m"
          livenessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: kaos-ui
spec:
  selector:
    app: kaos-ui
  ports:
    - port: 80
      targetPort: 80
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kaos-ui
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
    - host: kaos-ui.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kaos-ui
                port:
                  number: 80
```

### Helm Chart

For more complex deployments, consider creating a Helm chart:

```
kaos-ui-chart/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    └── ingress.yaml
```

---

## Custom Deployment

### Build Output

After running `npm run build`, the `dist/` folder contains:

```
dist/
├── index.html
├── assets/
│   ├── index-[hash].js
│   ├── index-[hash].css
│   └── ...
└── favicon.ico
```

### Static Hosting Requirements

Any static file server can host KAOS-UI:
- Serve the `dist/` folder
- Configure SPA routing (all paths → index.html)
- Enable HTTPS (recommended)
- Set appropriate cache headers

### Example: AWS S3 + CloudFront

1. Create S3 bucket with static website hosting
2. Upload `dist/` contents
3. Create CloudFront distribution
4. Configure error page: 404 → /index.html (200)

### Example: Apache

```apache
<VirtualHost *:80>
    DocumentRoot /var/www/kaos-ui
    
    <Directory /var/www/kaos-ui>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
        
        # SPA routing
        FallbackResource /index.html
    </Directory>
</VirtualHost>
```

---

## Environment-Specific Builds

### Development

```bash
npm run dev
```

### Staging

```bash
BASE_URL=/staging/ npm run build
```

### Production

```bash
BASE_URL=/ npm run build
```

---

## Health Checks

For production deployments, implement health checks:

### Endpoint

The root path `/` returns a 200 status when the app is healthy.

### Example Health Check

```bash
curl -f http://localhost:8080/ || exit 1
```

---

## Monitoring

### Recommended Metrics

- Response time (p50, p95, p99)
- Error rate
- Cache hit ratio
- Page load time

### Error Tracking

Consider integrating error tracking:
- Sentry
- LogRocket
- Datadog RUM

---

*Last updated: January 2026*
