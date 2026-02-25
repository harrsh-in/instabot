# Production Deployment Guide

## 🚀 Quick Deploy with Docker

### 1. Set Environment Variables

Create a `.env` file with production values:

```bash
# Flask Configuration
FLASK_SECRET_KEY=your-super-secret-production-key-min-32-chars

# Meta App Credentials (from developers.facebook.com)
META_APP_ID=your-app-id
META_APP_SECRET=your-app-secret
META_REDIRECT_URI=https://yourdomain.com/instagram/auth/callback
META_VERIFY_TOKEN=your-random-verify-token

# Production Settings
FLASK_ENV=production
FLASK_DEBUG=false
```

### 2. Deploy

```bash
# Make deploy script executable
chmod +x deploy.sh

# Run deployment
./deploy.sh
```

Or manually with Docker Compose:

```bash
# Build and start
docker-compose up -d --build

# Check logs
docker-compose logs -f

# Stop
docker-compose down
```

### 3. Verify Deployment

```bash
# Health check
curl https://yourdomain.com/health

# Check auth status
curl https://yourdomain.com/instagram/auth/status
```

## 📋 Pre-Deployment Checklist

### Meta App Settings (https://developers.facebook.com/apps/)

#### 1. OAuth Redirect URI (CRITICAL)
This MUST match exactly in your Meta App settings:

**Go to:** Products → Facebook Login → Settings

**Add to "Valid OAuth Redirect URIs":**
```
https://yourdomain.com/instagram/auth/callback
```

⚠️ **Important:**
- Must include the **full path** `/instagram/auth/callback`
- Must use **HTTPS** in production
- Must match `META_REDIRECT_URI` in your `.env` file exactly
- Trailing slash matters! `/callback` ≠ `/callback/`

#### 2. Other Settings
- [ ] Meta App is in **Live Mode**
- [ ] All required permissions approved (`instagram_basic`, `instagram_manage_comments`, `business_management`)
- [ ] Webhook callback URL configured: `https://yourdomain.com/instagram/webhook`
- [ ] Webhook fields subscribed (`comments`, `mentions`)
- [ ] HTTPS enabled (required for webhooks)
- [ ] Environment variables set correctly
- [ ] `SKIP_WEBHOOK_SIGNATURE` is **NOT** set (or set to `false`)

## 🔐 Security Notes

1. **App Secret**: Never commit to git. Use environment variables.
2. **Database**: SQLite is persisted in `./data/instance/`
3. **Logs**: Stored in `./data/logs/`
4. **Non-root user**: Container runs as `appuser` for security

## 📊 Monitoring

```bash
# View logs
docker-compose logs -f

# Container stats
docker stats instagram-webhook

# Restart service
docker-compose restart
```

## 🔄 Updates

```bash
# Pull latest code
git pull

# Rebuild and deploy
./deploy.sh
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Webhook signature invalid | Verify `META_APP_SECRET` matches Meta Dashboard |
| OAuth fails | Check `META_REDIRECT_URI` matches exactly (including HTTPS) |
| Database not persisting | Check `./data/instance/` permissions |
| Port already in use | Change port in `docker-compose.yml` |

## 📖 Meta App Configuration

### Step 1: OAuth Redirect URI (MUST DO FIRST)

**Location:** https://developers.facebook.com/apps/YOUR_APP_ID/fb-login/settings/

| Setting | Value |
|---------|-------|
| **Valid OAuth Redirect URIs** | `https://yourdomain.com/instagram/auth/callback` |

**Why this matters:** During OAuth, Meta redirects the user to this URL after authentication. If it's not configured exactly, OAuth will fail with "Can't Load URL" error.

### Step 2: Webhook Configuration

**Location:** https://developers.facebook.com/apps/YOUR_APP_ID/webhooks/

| Setting | Value |
|---------|-------|
| **Callback URL** | `https://yourdomain.com/instagram/webhook` |
| **Verify Token** | Same as `META_VERIFY_TOKEN` in `.env` |
| **Fields to Subscribe** | `comments`, `mentions` |

### Required Permissions

**Location:** https://developers.facebook.com/apps/YOUR_APP_ID/app-review/permissions/

Required permissions for production:
- `instagram_basic`
- `instagram_manage_comments`
- `business_management` (if using Business Manager)
- `pages_read_engagement`
