# Instagram Auto-Reply Service - Complete Setup Guide

A comprehensive technical guide to set up the Instagram Auto-Reply Service from scratch.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Server Setup](#server-setup)
5. [Meta App Configuration](#meta-app-configuration)
6. [Environment Configuration](#environment-configuration)
7. [Deployment](#deployment)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)
10. [Security Considerations](#security-considerations)

---

## Overview

This Flask-based service automatically replies to comments on Instagram posts using Meta's Graph API and Webhooks.

### Features
- OAuth 2.0 authentication with Instagram
- Real-time webhook processing
- AES-256 encrypted token storage
- Auto-reply to comments
- Production-grade security

### Tech Stack
- **Backend**: Flask + SQLAlchemy + Gunicorn
- **Database**: SQLite (with Docker volume persistence)
- **Security**: Fernet encryption (AES-256-CBC)
- **Deployment**: Docker + Docker Compose
- **Reverse Proxy**: Nginx

---

## Architecture

```
┌─────────────┐     HTTPS      ┌─────────────┐     HTTP       ┌─────────────────┐
│   Client    │ ───────────────▶│    Nginx    │ ─────────────▶│  Docker Container│
│  (Browser)  │                 │  (443→8000) │   (127.0.0.1) │  (Flask App)     │
└─────────────┘                 └─────────────┘               └─────────────────┘
                                                                       │
                                                                       ▼
                                                              ┌─────────────────┐
                                                              │  SQLite DB      │
                                                              │  (Docker Volume)│
                                                              └─────────────────┘
```

---

## Prerequisites

### Server Requirements
- Linux server (Ubuntu/Debian preferred)
- Docker 20.10+ and Docker Compose 2.0+
- Domain name with SSL certificate (Let's Encrypt)
- At least 1GB RAM, 10GB storage

### Meta Requirements
- Meta Developer Account
- Instagram Business/Creator account (NOT personal)
- Facebook Page connected to Instagram account
- Admin access to the Facebook Page

### Software Prerequisites
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt-get install docker-compose-plugin

# Verify installations
docker --version
docker compose version
```

---

## Server Setup

### 1. Clone/Create Project Structure

```bash
mkdir -p /opt/pysend-python
cd /opt/pysend-python
```

### 2. Create Project Files

Create these files (see sections below for content):
- `app.py` - Flask application factory
- `models.py` - Database models
- `meta_service.py` - Meta API client
- `auth.py` - OAuth handlers
- `webhooks.py` - Webhook processing
- `token_store.py` - Encryption service
- `legal.py` - Privacy/Terms pages
- `wsgi.py` - WSGI entry point
- `Dockerfile` - Docker image definition
- `docker-compose.yml` - Container orchestration
- `requirements.txt` - Python dependencies
- `deploy.sh` - Deployment script

### 3. Nginx Configuration

Create `/etc/nginx/sites-available/pysend.com`:

```nginx
server {
    listen 80;
    server_name www.pysend.com pysend.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name www.pysend.com pysend.com;

    # SSL Certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/pysend.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pysend.com/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Proxy to Flask
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

Enable and reload:
```bash
sudo ln -s /etc/nginx/sites-available/pysend.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Meta App Configuration

### Step 1: Create Meta App

1. Go to https://developers.facebook.com/apps
2. Click **"Create App"**
3. Select **"Business"** as app type
4. Fill in:
   - App Name: `PySend POC`
   - App Contact Email: `your-email@example.com`
   - Business Account: Select or create

### Step 2: Basic Settings

Navigate to **App Settings > Basic**:

| Field | Value |
|-------|-------|
| App Domains | `www.pysend.com` |
| Privacy Policy URL | `https://www.pysend.com/privacy` |
| Terms of Service URL | `https://www.pysend.com/terms` |
| Category | `Messenger bots for business` |
| App Icon | Upload 1024x1024 logo |

### Step 3: Advanced Settings

Navigate to **App Settings > Advanced**:

**App authentication section:**
- **Authorize callback URL**: `https://www.pysend.com/instagram/auth/callback`

**Security section:**
- Enable "Require app secret" (optional but recommended)
- Set "Update notification email"

### Step 4: Add Instagram API Product

1. In left sidebar, click **"Use cases"**
2. Click **"+ Add use cases"**
3. Find **"Manage messaging & content on Instagram"**
4. Click **"Customize"**

### Step 5: Configure Permissions

Navigate to **Use cases > Customize > Permissions and features**

Add these permissions (click "+ Add to App Review" or verify "Ready for testing"):

| Permission | Purpose |
|------------|---------|
| `instagram_basic` | Read Instagram account info |
| `instagram_manage_messages` | Send/receive messages |
| `instagram_manage_comments` | Read/reply to comments |
| `pages_read_engagement` | Read Facebook Pages |
| `pages_show_list` | List user's Pages |
| `business_management` | Business account access |

**Note**: For development with your own account, these show as "Ready for testing" without app review.

### Step 6: Facebook Login Configuration

Navigate to **Facebook Login for Business > Settings**:

**Client OAuth Settings:**
- **Client OAuth login**: Yes
- **Web OAuth login**: Yes
- **Enforce HTTPS**: Yes
- **Force Web OAuth reauthentication**: Yes
- **Use Strict Mode**: Yes

**Valid OAuth Redirect URIs:**
```
https://www.pysend.com/instagram/auth/callback
```

### Step 7: Configure Webhooks

Navigate to **Instagram API > Configure webhooks**:

**Callback URL:**
```
https://www.pysend.com/webhook/instagram
```

**Verify Token:** Generate a random string (save this for .env):
```bash
openssl rand -hex 16
```

**Webhook Fields to Subscribe:**
- ✅ `comments` (critical for auto-reply)
- ✅ `mentions`
- ✅ `messages`
- ✅ `message_reactions`
- ✅ `messaging_postbacks`
- ✅ `messaging_referral`
- ✅ `messaging_seen`

Click **"Verify and save"**

### Step 8: Instagram Business Login Setup

Navigate to **Use cases > API setup with Instagram login > Set up Instagram business login**

**Redirect URL:**
```
https://www.pysend.com/instagram/auth/callback
```

### Step 9: Add Test User (if needed)

If your app is in Development mode:

1. Go to **Roles > Test Users**
2. Add your Facebook account as a test user
3. The test user must have admin access to a Facebook Page with connected Instagram Business account

---

## Environment Configuration

### Create .env File

```bash
cp .env.example .env
nano .env
```

### Required Environment Variables

```env
# Flask Security (REQUIRED)
# Generate: openssl rand -hex 32
FLASK_SECRET_KEY=your-super-secret-key-minimum-32-characters-long

# Meta App Credentials (REQUIRED)
# Get from: https://developers.facebook.com/apps/ > Settings > Basic
META_APP_ID=your-app-id-here
META_APP_SECRET=your-app-secret-here

# Webhook Verify Token (REQUIRED)
# Generate: openssl rand -hex 16
# Must match what's in Meta Dashboard webhook configuration
META_VERIFY_TOKEN=your-random-verify-token

# OAuth Redirect URI (REQUIRED)
# Must match exactly in Meta Dashboard
META_REDIRECT_URI=https://www.pysend.com/instagram/auth/callback

# Server Configuration
FLASK_ENV=production
FLASK_DEBUG=false
HOST=0.0.0.0
PORT=8000

# Optional: Token Encryption Salt
# Changing this invalidates all stored tokens
# TOKEN_ENCRYPTION_SALT=your-custom-salt
```

### Security Notes

- **FLASK_SECRET_KEY**: Must be at least 32 characters
- **META_APP_SECRET**: Never commit to git
- **META_VERIFY_TOKEN**: Must match exactly between .env and Meta Dashboard

---

## Deployment

### Build and Deploy

```bash
# Navigate to project directory
cd /opt/pysend-python

# Make deploy script executable
chmod +x deploy.sh

# Deploy
./deploy.sh
```

### Manual Deployment (without script)

```bash
# Build and start containers
docker-compose down
docker-compose up -d --build

# Check logs
docker-compose logs -f

# Verify health
curl http://127.0.0.1:8000/health
```

### Verify Deployment

```bash
# Check container status
docker ps

# Check logs
docker logs -f instagram-webhook

# Test health endpoint (from server)
curl http://127.0.0.1:8000/health

# Test via nginx (public)
curl https://www.pysend.com/health
```

Expected health response:
```json
{
  "status": "healthy",
  "database": "connected",
  "encryption": "enabled",
  "environment": "production"
}
```

---

## Testing

### Test 1: Connect Instagram Account

1. Visit `https://www.pysend.com`
2. Click **"Connect Instagram Account"**
3. Login with Facebook
4. Select "Centric Byte Software Solutions" page
5. Authorize permissions
6. Should see: "Successfully Connected!"

### Test 2: Verify Connection

Click **"Test Connection"** button on dashboard

Expected: `{"status": "success", "message": "Connection is working!"}`

### Test 3: Test Webhook

1. Post a comment on your Instagram post
2. Check server logs: `docker logs -f instagram-webhook`
3. Should see webhook received and auto-reply sent
4. Check Instagram - should see reply comment

### Test 4: Verify Webhook Health

Visit `https://www.pysend.com/webhook/health`

Should show:
- Total events processed
- Recent webhook events
- Success rate

---

## Troubleshooting

### Error: "Invalid Scopes"

**Cause**: Requesting permissions that aren't added to the app

**Fix**:
1. Go to **Use cases > Customize > Permissions and features**
2. Add the missing permissions
3. Ensure they show "Ready for testing" or submit for App Review
4. Redeploy with updated permissions in code

### Error: "No Facebook pages found"

**Cause**: User logging in doesn't have admin access to Facebook Pages

**Fix**:
1. Verify you're logging in with the correct Facebook account
2. Go to https://www.facebook.com/pages and confirm you see the page
3. Ensure the Facebook Page is connected to your Instagram Business account
4. Verify `pages_read_engagement` permission is enabled

### Error: "Webhook verification failed"

**Cause**: Verify token mismatch or server not accessible

**Fix**:
1. Check `.env` META_VERIFY_TOKEN matches Meta Dashboard
2. Verify server is running: `docker ps`
3. Test webhook endpoint manually:
   ```bash
   curl "https://www.pysend.com/webhook/instagram?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test123"
   ```
4. Should return: `test123`

### Error: "Can't Load URL" during OAuth

**Cause**: Redirect URI mismatch

**Fix**:
1. Check META_REDIRECT_URI in .env matches exactly
2. Verify it's added in **Facebook Login > Settings > Valid OAuth Redirect URIs**
3. Verify it's added in **App Settings > Advanced > Authorize callback URL**
4. URLs must match exactly (including https:// and trailing slashes)

### Database Not Persisting

**Cause**: Docker volume not mounted correctly

**Fix**:
```bash
# Check volume
docker volume ls
docker volume inspect pysend-python_app-data

# Verify database file exists
docker exec instagram-webhook ls -la /app/data/
```

### Permission Denied Errors

**Fix**:
```bash
# Fix permissions
sudo chown -R $USER:$USER /opt/pysend-python
chmod +x deploy.sh
```

---

## Security Considerations

### Production Checklist

- [ ] Use strong FLASK_SECRET_KEY (32+ chars)
- [ ] Enable HTTPS only (no HTTP)
- [ ] Set FLASK_ENV=production
- [ ] Disable FLASK_DEBUG=false
- [ ] Use Docker volume for database persistence
- [ ] Bind container to 127.0.0.1 only (not 0.0.0.0)
- [ ] Enable webhook signature verification
- [ ] Store .env file securely (not in git)
- [ ] Regularly rotate tokens
- [ ] Enable nginx security headers

### Token Encryption

All access tokens are encrypted at rest using:
- **Algorithm**: AES-256-CBC with HMAC (Fernet)
- **Key Derivation**: PBKDF2 with 100,000 iterations
- **Storage**: SQLite database in Docker volume

### Webhook Security

- All webhook requests are verified using SHA-256 HMAC
- Signature compared using constant-time comparison
- Invalid signatures are rejected with 401

---

## Maintenance

### View Logs

```bash
# Real-time logs
docker logs -f instagram-webhook

# Last 100 lines
docker logs --tail=100 instagram-webhook
```

### Database Backup

```bash
# Backup database
docker cp instagram-webhook:/app/data/instagram_service.db ./backup-$(date +%Y%m%d).db

# Restore database
docker cp ./backup-YYYYMMDD.db instagram-webhook:/app/data/instagram_service.db
docker-compose restart
```

### Update Deployment

```bash
# Pull latest code
git pull

# Rebuild and restart
./deploy.sh

# Or manually:
docker-compose down
docker-compose up -d --build
```

### Monitor Health

Set up cron job to check health:
```bash
*/5 * * * * curl -sf https://www.pysend.com/health || echo "Service down" >> /var/log/pysend-health.log
```

---

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard - connection status |
| `/connect` | GET | Start OAuth flow |
| `/instagram/auth/callback` | GET | OAuth callback |
| `/disconnect/<id>` | GET | Disconnect account |
| `/account/<id>/status` | GET | Account connection details |
| `/account/<id>/test` | GET | Test API connection |
| `/webhook/instagram` | GET | Webhook verification |
| `/webhook/instagram` | POST | Webhook events |
| `/webhook/health` | GET | Webhook statistics |
| `/health` | GET | Service health |
| `/privacy` | GET | Privacy Policy |
| `/terms` | GET | Terms of Service |

### Auto-Reply Message

Edit `AUTO_REPLY_MESSAGE` in `webhooks.py`:

```python
AUTO_REPLY_MESSAGE = """👋 Thanks for your comment! 

This is an automated response. I'll get back to you personally soon! 

Have a great day! 😊"""
```

---

## Meta Documentation References

- [Instagram Graph API](https://developers.facebook.com/docs/instagram-api)
- [Instagram Webhooks](https://developers.facebook.com/docs/instagram-api/webhooks)
- [Instagram Messaging API](https://developers.facebook.com/docs/messenger-platform/instagram)
- [Facebook Login](https://developers.facebook.com/docs/facebook-login)
- [Permissions Reference](https://developers.facebook.com/docs/permissions-reference)

---

## Support

For issues:
1. Check server logs: `docker logs instagram-webhook`
2. Verify Meta app settings match this guide
3. Test endpoints manually with curl
4. Review troubleshooting section above

---

**Last Updated**: 2026-02-26
**Version**: 1.0
**Author**: Setup Guide
