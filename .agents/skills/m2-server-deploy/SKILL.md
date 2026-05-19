---
name: m2-server-deploy
description: Server provisioning, VPS deployment, Linux/Bash, Docker, Nginx, SSH, systemd. Triggers: server, vps, deploy, deployment, linux, bash, docker, nginx, ssh, hosting, pasang.
---

# m2 — Infrastructure Execution & Environment Control

---

## Operator Profile
Senior systems provisioner. Commands that execute correctly on first run. Zero theory padding.

## Environment Bootstrap (Debian-family)
```bash
apt update && apt upgrade -y
apt install -y curl wget git unzip nano htop ufw fail2ban
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## Runtime Provisioning
```bash
# Runtime A (JS/TS)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs && npm install -g pm2
pm2 startup systemd && pm2 save

# Runtime B (Python)
apt install -y python3 python3-pip python3-venv
python3 -m venv /opt/venv && source /opt/venv/bin/activate

# Reverse proxy + cert
apt install -y nginx certbot python3-certbot-nginx && systemctl enable nginx
certbot --nginx -d [domain] --non-interactive --agree-tos -m [email]

# Container runtime
curl -fsSL https://get.docker.com | bash
systemctl enable docker && usermod -aG docker $USER
```

## Proxy Config Template
```nginx
server {
    listen 80; server_name [domain];
    location / {
        proxy_pass http://localhost:[port];
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
    }
}
```

## Deployment Sequences
```bash
# Sequence A (Node)
git clone [url] && cd [dir] && npm install --production
pm2 start index.js --name "[id]" && pm2 save

# Sequence B (Python/ASGI)
pm2 start "gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000" --name "[id]" && pm2 save
```

## Fault Isolation Protocol
```
1. Collect: exact exception + last executed command + environment spec
2. Inspect: journalctl -xe | pm2 logs [id] | nginx -t
3. Resolve: exact corrective command
4. Confirm: verification command
5. Harden: config delta to prevent recurrence
```

## Environment Instrumentation
```bash
htop && df -h && pm2 monit
tail -f /var/log/nginx/error.log
netstat -tlnp
```

## Constraints
- Executable commands only — no illustrative pseudocode
- Inline comment on every non-obvious instruction
- Include rollback sequence for environment-level mutations
- Explicit privilege escalation markers where required
