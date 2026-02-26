# Production Deployment Guide

## Architecture

```
Internet
    ↓ HTTPS (443)
Nginx (Reverse Proxy)
    ↓ HTTP (localhost:8000)
Docker Container (Flask App)
    ↓
SQLite Database
```

**Security**: The Flask app binds to `127.0.0.1:8000` only - it's not accessible from the internet directly. Nginx handles SSL termination and proxies requests internally.

---

## 🚀 Quick Deploy

### 1. Configure Environment

```bash
cp .env.example .env
nano .env
```

Required values:
```env
FLASK_SECRET_KEY=<openssl rand -hex 32>
META_APP_ID=your-meta-app-id
META_APP_SECRET=your-meta-app-secret
META_VERIFY_TOKEN=<openssl rand -hex 16>
META_REDIRECT_URI=https://www.pysend.com/instagram/auth/callback
```

### 2. Deploy Docker Container

```bash
./deploy.sh
# or
docker-compose up -d --build
```

The container binds to **localhost:8000 only** - not exposed to the internet.

### 3. Configure Nginx

Add to your nginx config (e.g., `/etc/nginx/sites-available/pysend.com`):

```nginx
server {
    listen 80;
    server_name www.pysend.com pysend.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name www.pysend.com pysend.com;

    # SSL certificates (Let's Encrypt or your provider)
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    
    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Proxy to Flask app (localhost only - not exposed externally)
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

Test and reload nginx:
```bash
nginx -t
systemctl reload nginx
```

---

## 📋 Meta App Configuration

### OAuth Redirect URI
**Location:** Facebook Login → Settings

```
https://www.pysend.com/instagram/auth/callback
```

### Webhook Configuration
**Location:** Webhooks → Instagram

| Setting | Value |
|---------|-------|
| Callback URL | `https://www.pysend.com/webhook/instagram` |
| Verify Token | From `.env` file |
| Fields | `mentions`, `comments` |

### Required URLs

| Page | URL |
|------|-----|
| Privacy Policy | `https://www.pysend.com/privacy` |
| Terms of Service | `https://www.pysend.com/terms` |

---

## 🔐 Security

### Network Isolation
- Flask app only accessible via `127.0.0.1:8000`
- No direct internet exposure
- Nginx handles SSL/TLS termination

### Token Encryption
- AES-256 encryption for all access tokens
- Keys derived via PBKDF2 (100k iterations)
- Encrypted at rest in Docker volume

### Webhook Verification
- SHA-256 HMAC signature verification
- Rejects requests with invalid signatures

---

## 📊 Monitoring

```bash
# View logs
docker-compose logs -f

# Health check (via nginx)
curl https://www.pysend.com/health

# Health check (direct, localhost only)
curl http://127.0.0.1:8000/health

# Container stats
docker stats instagram-webhook

# Database access
docker exec -it instagram-webhook sqlite3 /app/data/instagram_service.db
```

---

## 🔄 Updates

```bash
# Pull latest code
git pull

# Rebuild and restart
./deploy.sh

# Or manually:
docker-compose down
docker-compose up -d --build

# Reload nginx (if config changed)
systemctl reload nginx
```

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| 502 Bad Gateway | Check container is running: `docker-compose ps` |
| Webhook fails | Verify `META_APP_SECRET` matches Meta Dashboard |
| OAuth fails | Check redirect URI uses HTTPS exactly as configured |
| SSL errors | Verify certificates in nginx config |
| Permission denied | Check `data/` volume permissions |

---

## 📁 File Structure on Server

```
/opt/pysend/                    # Your project directory
├── docker-compose.yml
├── Dockerfile
├── .env                        # Secrets (not in git)
└── data/                       # Database volume
    └── instagram_service.db

/etc/nginx/sites-available/     # Nginx config
└── pysend.com

/var/log/nginx/                 # Nginx logs
└── access.log / error.log
```

---

## ✅ Pre-Deployment Checklist

- [ ] `.env` file created with production values
- [ ] `FLASK_SECRET_KEY` is 32+ characters
- [ ] `META_REDIRECT_URI` uses HTTPS
- [ ] Nginx config has SSL certificates
- [ ] Nginx proxy_pass to `127.0.0.1:8000`
- [ ] Meta App in Live Mode
- [ ] Webhook URL configured in Meta Dashboard
- [ ] Privacy & Terms pages accessible
