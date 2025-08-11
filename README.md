# BhashaSetu — Deployment Guide (AWS EC2)

This README documents how to deploy the **BhashaSetu** Flask backend on an AWS EC2 instance (Ubuntu). It reflects the exact setup used during development: app running in a Python virtualenv, managed by `systemd`, proxied by Nginx and secured with Let's Encrypt (Certbot). Use this to reproduce the environment or share with collaborators.

---

## Prerequisites

- An AWS EC2 instance (Ubuntu 20.04 / 22.04 recommended) with sudo access.
- A public IPv4 address assigned to the EC2 instance.
- Domain/subdomain pointed to the EC2 public IP.
- Security Group: allow **SSH(22)**, **HTTP(80)** and **HTTPS(443)** inbound. (You can restrict other ports later.)
- Python 3.8+ installed on the EC2 instance.
- Git installed if you plan to clone from GitHub.

---

## Project layout (expected)

```
/home/ubuntu/bhashaSetu-Backend/
├─ api.py                  # Flask entry-point
├─ requirements.txt
├─ venv/                   # python virtualenv
├─ uploads/                # runtime uploads & generated files
└─ .env                    # environment variables (GEMINI_API_KEY, PORT)
```

> Note: This repo used `api.py` as the app entry point and the project folder name is `bhashaSetu-Backend` (case sensitive).

---

## 1. Connect to EC2 and clone

```bash
# SSH to your instance
ssh -i <your-key.pem> ubuntu@<EC2_PUBLIC_IP>

# clone into the correct path
cd /home/ubuntu
git clone <repo-url> bhashaSetu-Backend
cd bhashaSetu-Backend
```

---

## 2. Create Python virtualenv & install deps

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If your repo does not include `requirements.txt`, generate it locally with `pip freeze > requirements.txt` from your dev environment.

---

## 3. Create runtime folders & `.env`

```bash
# Ensure uploads folder exists
mkdir -p uploads
chown -R ubuntu:ubuntu uploads
chmod 755 uploads

# Create .env file (contains secrets and config)
cat > .env <<EOF
GEMINI_API_KEY=your_actual_gemini_key_here
PORT=8001
EOF

# Restrict access
chmod 600 .env
```

**Important:** Never commit `.env` to GitHub. Add it to `.gitignore`.

---

## 4. systemd service (app supervisor)

Create `/etc/systemd/system/bhashasetu.service` with the following content (absolute paths are used):

```ini
[Unit]
Description=BhashaSetu Translation Backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/bhashaSetu-Backend
EnvironmentFile=/home/ubuntu/bhashaSetu-Backend/.env
ExecStart=/home/ubuntu/bhashaSetu-Backend/venv/bin/python /home/ubuntu/bhashaSetu-Backend/api.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Reload systemd and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl start bhashasetu
sudo systemctl enable bhashasetu
sudo systemctl status bhashasetu
# stream logs
sudo journalctl -u bhashasetu -f
```

> Alternative (recommended for production): use `gunicorn` instead of running `python api.py`. See the *Optional: Gunicorn* section below.

---

## 5. Nginx reverse proxy

Create `/etc/nginx/sites-available/bhashasetu` with:

```nginx
server {
    listen 80;
    server_name bhashasetu.duckdns.org;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/bhashasetu /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Check that Nginx is listening:

```bash
sudo lsof -i -P -n | grep LISTEN
```

Visit `http://bhashasetu.duckdns.org` to verify.

---

## 6. Point DuckDNS to EC2 public IP

- Get your public IP from EC2:

```bash
curl ifconfig.me
```

- On DuckDNS dashboard, set `bhashasetu.duckdns.org` to this IP and save. Keep the DuckDNS updater script or dynamic client running if your IP changes.

---

## 7. Install SSL with Certbot (Let's Encrypt)

```bash
sudo apt update
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d bhashasetu.duckdns.org
# choose redirect to HTTPS when prompted

# verify auto-renewal
sudo certbot renew --dry-run
```

After this you should be able to reach the site at `https://bhashasetu.duckdns.org`.

---

## 8. Firewall (UFW) & locking down the app port

Keep only Nginx ports exposed and block direct external access to the app port (8001):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # this opens 80 and 443
sudo ufw enable
# Deny direct access to the app port
sudo ufw deny 8001
```

This ensures only Nginx (running on the same host) can access the app on 8001.

---

## 9. Updating code (deploy workflow)

When you want to push updates from GitHub and deploy on the server:

```bash
cd /home/ubuntu/bhashaSetu-Backend
git pull origin main
source venv/bin/activate
pip install -r requirements.txt   # if dependencies changed
# restart the service
sudo systemctl restart bhashasetu
# tail logs to verify
sudo journalctl -u bhashasetu -f
```

---

## Optional: Gunicorn (production WSGI)

Install gunicorn in your venv:

```bash
source venv/bin/activate
pip install gunicorn
```

Change `ExecStart` in `/etc/systemd/system/bhashasetu.service` to use gunicorn:

```ini
ExecStart=/home/ubuntu/bhashaSetu-Backend/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8001 api:app
```

Reload systemd and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bhashasetu
```

Gunicorn will usually be more reliable and performant than the Flask dev server.

---

## Troubleshooting

- **Service fails to start**: run `sudo journalctl -xeu bhashasetu.service` and `sudo systemctl status bhashasetu` to see Python tracebacks.
- **Wrong working directory / file not found**: systemd is case-sensitive; ensure `WorkingDirectory` and `ExecStart` use absolute paths and correct casing.
- **GEMINI_API_KEY missing**: verify `.env` path and permissions (chmod 600). You can test by running `export $(cat .env | xargs)` then `python api.py` manually.
- **Port already in use**: `sudo lsof -i -P -n | grep LISTEN`.
- **Nginx 502/504** errors: ensure app is listening on configured port and not crashing. Check `journalctl -u bhashasetu -f`.

---

## Security & Best Practices

- Keep secrets out of Git (use `.env` and add it to `.gitignore`). Consider using AWS Secrets Manager for production.
- Use a process manager (systemd + gunicorn) instead of `flask run` for production workloads.
- Configure UFW and security groups to only expose necessary ports.
- Rotate API keys and monitor logs for unusual activity.

---

## Contact / Notes

If you followed this README and run into issues, include the output of these commands when asking for help:

```bash
sudo systemctl status bhashasetu
sudo journalctl -u bhashasetu -n 200
sudo nginx -t
sudo lsof -i -P -n | grep LISTEN
```
# GitHub Actions CI/CD to EC2

This repository is configured to automatically deploy changes from the `main` branch to an AWS EC2 instance using **GitHub Actions** and **SSH**.

## How It Works

1. **Push to Main Branch**
   - Whenever you push commits to the `main` branch, GitHub Actions workflow (`.github/workflows/deploy.yml`) will run.

2. **GitHub Actions Workflow**
   - The workflow checks out the repository code.
   - Connects to your EC2 instance via SSH using the private key stored in GitHub Secrets.
   - Runs deployment commands on the EC2 instance:
     - `git pull origin main` to update the code.
     - Restarts your application using `systemctl`.

3. **Secrets Used**
   - `EC2_HOST` → Public IP or domain of your EC2 instance.
   - `EC2_SSH_KEY` → Private SSH key for accessing EC2.

## Setup Steps

1. **Generate SSH Key (without passphrase)**
   ```bash
   ssh-keygen -t rsa -b 4096 -C "github-actions" -f github_action_key_new
   ```

2. **Add Public Key to EC2**
   ```bash
   ssh ubuntu@<EC2-IP>
   mkdir -p ~/.ssh
   cat github_action_key_new.pub >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

3. **Store Private Key in GitHub Secrets**
   - Go to **Repo → Settings → Secrets and variables → Actions → New repository secret**
   - Name: `EC2_SSH_KEY`
   - Value: contents of `github_action_key_new`

4. **Store EC2 Host in GitHub Secrets**
   - Name: `EC2_HOST`
   - Value: your EC2 public IP or domain.

5. **Deploy Workflow File**
   - File: `.github/workflows/deploy.yml`
   ```yaml
   name: Deploy to EC2

   on:
     push:
       branches:
         - main

   jobs:
     deploy:
       runs-on: ubuntu-latest

       steps:
         - name: Checkout repo
           uses: actions/checkout@v3

         - name: Deploy to EC2 via SSH
           uses: appleboy/ssh-action@v0.1.7
           with:
             host: ${{ secrets.EC2_HOST }}
             username: ubuntu
             key: ${{ secrets.EC2_SSH_KEY }}
             port: 22
             script: |
               cd /path/to/your/project
               git pull origin main
               sudo systemctl restart myapp.service
   ```
---

*Prepared to match the deployment steps used for Bhasha-Setu on an EC2 instance.*
