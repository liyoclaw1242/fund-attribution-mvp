#!/bin/bash
# Deploy fund-attribution-mvp to Ubuntu 22.04 VM.
# Usage: sudo bash deploy.sh YOUR_DOMAIN
set -euo pipefail

DOMAIN="${1:?Usage: sudo bash deploy.sh YOUR_DOMAIN}"
APP_DIR="/opt/fund-attribution"

echo "=== 1. Install dependencies ==="
apt-get update
apt-get install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx

systemctl enable --now docker

echo "=== 2. Deploy application ==="
mkdir -p "$APP_DIR"
cp -r . "$APP_DIR/"

cd "$APP_DIR"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "WARNING: Edit $APP_DIR/.env and set ANTHROPIC_API_KEY before starting."
fi

mkdir -p data/sitca_raw output

docker compose up -d --build

echo "=== 3. Configure Nginx ==="
sed "s/YOUR_DOMAIN/$DOMAIN/g" ops/nginx.conf > /etc/nginx/sites-available/fund-attribution
ln -sf /etc/nginx/sites-available/fund-attribution /etc/nginx/sites-enabled/fund-attribution
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx

echo "=== 4. HTTPS (Let's Encrypt) ==="
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email
systemctl enable certbot.timer

echo "=== 5. systemd service ==="
cp ops/fund-attribution.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable fund-attribution

echo "=== 6. Cron jobs ==="
mkdir -p /var/log/fund-attribution

# TWSE warmup: daily at 14:30 (after 14:00 market close)
CRON_TWSE="30 14 * * 1-5 cd $APP_DIR && bash cron/twse_warmup.sh >> /var/log/fund-attribution/twse_warmup.log 2>&1"
# SITCA check: monthly on the 20th at 09:00
CRON_SITCA="0 9 20 * * cd $APP_DIR && bash cron/sitca_check.sh >> /var/log/fund-attribution/sitca_check.log 2>&1"

(crontab -l 2>/dev/null | grep -v "twse_warmup\|sitca_check"; echo "$CRON_TWSE"; echo "$CRON_SITCA") | crontab -

echo "=== Done ==="
echo "App: https://$DOMAIN"
echo "Logs: docker compose -f $APP_DIR/docker-compose.yml logs -f"
