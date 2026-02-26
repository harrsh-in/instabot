# Instagram Auto-Reply Service

A production-grade Flask server that automatically replies to comments on your Instagram posts using Meta's Graph API and Webhooks.

## Features

- 🔐 **OAuth 2.0 Integration**: Secure Instagram Business account connection
- 🪝 **Verified Webhooks**: SHA-256 signature verification on all requests
- 💬 **Auto-Reply**: Automated responses to comments on your posts
- 💾 **Persistent Storage**: SQLite with encrypted access tokens
- 🔒 **AES-256 Encryption**: All access tokens encrypted at rest
- 📊 **Monitoring**: Health check endpoints and comprehensive logging
- 🐳 **Docker Ready**: Production deployment via Docker Compose

## Prerequisites

1. **Instagram Business/Creator Account** (personal accounts not supported)
2. **Facebook Page** connected to your Instagram account
3. **Meta Developer Account**: [developers.facebook.com](https://developers.facebook.com)
4. **Docker & Docker Compose**

## Quick Start

### 1. Configure

```bash
cp .env.example .env
nano .env
```

Required:
```env
FLASK_SECRET_KEY=<openssl-rand-hex-32>
META_APP_ID=your-meta-app-id
META_APP_SECRET=your-meta-app-secret
META_VERIFY_TOKEN=<openssl-rand-hex-16>
META_REDIRECT_URI=https://www.pysend.com/instagram/auth/callback
```

### 2. Deploy

```bash
./deploy.sh
```

The app binds to **localhost:8000** (not exposed to internet). Use nginx as reverse proxy.

### 3. Verify

```bash
# Check health
curl https://www.pysend.com/health

# View logs
docker-compose logs -f
```

### 4. Connect Instagram Account

1. Visit `https://www.pysend.com`
2. Click "Connect Instagram Account"
3. Authorize with Facebook
4. Configure webhooks in Meta Dashboard (see below)

## Meta Developer Dashboard Setup

### Step 1: Create Meta App

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps)
2. Click **Create App** → Select **Business** type

### Step 2: Add Instagram Graph API

1. In app dashboard, click **Add Product**
2. Select **Instagram Graph API**

### Step 3: Configure OAuth

**Location:** Products → Facebook Login → Settings

Add to "Valid OAuth Redirect URIs":
```
https://www.pysend.com/instagram/auth/callback
```

### Step 4: Configure Webhooks

**Location:** Webhooks → Instagram

| Setting | Value |
|---------|-------|
| **Callback URL** | `https://www.pysend.com/webhook/instagram` |
| **Verify Token** | Same as `META_VERIFY_TOKEN` in `.env` |
| **Fields** | `mentions`, `comments` |

### Step 5: Go Live

1. Add Privacy Policy URL: `https://www.pysend.com/privacy`
2. Add Terms URL: `https://www.pysend.com/terms`
3. Toggle **Live Mode** to ON

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/connect` | GET | Start OAuth flow |
| `/instagram/auth/callback` | GET | OAuth callback |
| `/disconnect/<id>` | GET | Disconnect account |
| `/webhook/instagram` | GET/POST | Webhook handler |
| `/webhook/health` | GET | Webhook stats |
| `/health` | GET | Service health |
| `/privacy` | GET | Privacy Policy |
| `/terms` | GET | Terms of Service |

## Project Structure

```
├── app.py              # Flask app factory
├── models.py           # Database models
├── meta_service.py     # Meta API client
├── auth.py             # OAuth handlers
├── webhooks.py         # Webhook processing
├── token_store.py      # AES-256 encryption
├── legal.py            # Privacy/Terms
├── wsgi.py             # WSGI entry point
├── Dockerfile          # Docker image
├── docker-compose.yml  # Docker orchestration
├── deploy.sh           # Deployment script
├── requirements.txt    # Python dependencies
└── .env.example        # Configuration template
```

## Docker Commands

```bash
# Build and start (binds to localhost:8000 only)
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Access database
docker exec -it instagram-webhook sqlite3 /app/data/instagram_service.db

# Health check (localhost only)
curl http://127.0.0.1:8000/health
```

### Nginx Reverse Proxy

The container only accepts connections from localhost. Configure nginx:

```nginx
server {
    listen 443 ssl;
    server_name www.pysend.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Security

### Encryption
- **Tokens**: AES-256-CBC with HMAC (Fernet)
- **Key Derivation**: PBKDF2 with 100,000 iterations
- **Storage**: Encrypted at rest in SQLite

### Webhook Security
- **Signature Verification**: SHA-256 HMAC on all webhooks
- **CSRF Protection**: State parameter in OAuth flow
- **Input Validation**: All user inputs validated

## Customization

### Auto-Reply Message

Edit in `webhooks.py`:
```python
AUTO_REPLY_MESSAGE = """👋 Thanks for your comment!

I'll get back to you soon."""
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Webhook fails | Verify `META_APP_SECRET` matches Meta Dashboard |
| OAuth fails | Check `META_REDIRECT_URI` uses HTTPS and matches exactly |
| Database issues | Check Docker volume `docker volume ls` |
| Port conflict | Change port in `docker-compose.yml` |

## Health Check

```bash
curl https://www.pysend.com/health
```

Response:
```json
{
  "status": "healthy",
  "database": "connected",
  "encryption": "enabled"
}
```

## License

MIT License

## Meta API Documentation

- [Instagram Graph API](https://developers.facebook.com/docs/instagram-api)
- [Webhooks](https://developers.facebook.com/docs/graph-api/webhooks)
