# Notes App — DevOps Assessment

A production-style deployment of a simple Flask CRUD app (Notes) on AWS, with Docker, Jenkins CI/CD, Nginx + SSL, and RDS PostgreSQL.

---

## Architecture Overview

```
Internet
   │
   ▼
Route 53 / Free subdomain (your-domain.com)
   │
   ▼
EC2 t2.micro  (Security Group: 80, 443 inbound from 0.0.0.0/0 ; 22 from MY_IP only)
  ├── Nginx (80 → redirect to 443 ; 443 → proxy to :5000)
  ├── Flask/Gunicorn app (port 5000, localhost only)
  └── Jenkins (port 9090, localhost only — access via SSH tunnel or restricted IP)
   │
   ▼ (private subnet / SG allows only EC2 SG)
RDS PostgreSQL (port 5432 — NOT public)
```

---

## Instance Sizing Rationale

| Resource | Choice | Why |
|---|---|---|
| Instance type | **t2.micro** | Free tier eligible; sufficient for a low-traffic demo app. Flask + Gunicorn + Nginx + Jenkins fit within 1 GB RAM for assessment purposes. In production, t3.small or t3.medium would be the minimum for Jenkins alone. |
| Storage | 20 GB gp2 | Default free-tier allocation; adequate for OS + Docker images + Jenkins workspace. |
| RDS | db.t3.micro (single-AZ) | Free tier; assessment workload only. Production would use Multi-AZ with automated backups enabled. |

---

## Port Justification (Every Open Rule Explained)

### EC2 Security Group — Inbound Rules

| Port | Protocol | Source | Reason |
|---|---|---|---|
| 80 | TCP | 0.0.0.0/0 | HTTP — required for Let's Encrypt ACME challenge and to redirect users to HTTPS. Nginx immediately redirects all traffic to 443. |
| 443 | TCP | 0.0.0.0/0 | HTTPS — production traffic. All app traffic flows through here. |
| 22 | TCP | **MY_IP/32 only** | SSH management access. Restricted to a single IP — not open to the world. Any other IP is blocked. |

> **No other inbound ports are open.** Jenkins (9090) and Flask (5000) are bound to `127.0.0.1` and are NOT reachable from the internet directly. Jenkins is accessed via SSH tunnel only.

### RDS Security Group — Inbound Rules

| Port | Protocol | Source | Reason |
|---|---|---|---|
| 5432 | TCP | EC2 Security Group ID | Only the application server can reach the database. No public internet access. |

---

## Local Development Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/notes-app-devops.git
cd notes-app-devops

# 2. Copy env template and fill in values
cp .env.example .env
# Edit .env — set DB_USER, DB_PASSWORD, DB_NAME

# 3. Start app + database locally
docker-compose up --build

# App runs at: http://localhost:5000
# Health:      http://localhost:5000/health
```

---

## Production Setup (Step by Step)

### 1. EC2 Provisioning
```bash
# Launch Ubuntu 22.04 t2.micro via AWS Console or CLI
# Attach security group per rules above
# Install Docker
sudo apt update && sudo apt install -y docker.io docker-compose
sudo usermod -aG docker ubuntu

# Install Nginx
sudo apt install -y nginx certbot python3-certbot-nginx
```

### 2. RDS Setup
```bash
# Via AWS Console:
# Engine: PostgreSQL 15
# Template: Free tier
# Instance: db.t3.micro
# Storage: 20 GB gp2
# Disable public access (crucial)
# VPC Security Group: allow only EC2 SG on port 5432

# After RDS is up, connect from EC2 and run migrations:
psql -h YOUR_RDS_ENDPOINT -U flask_user -d notesdb -f app/migrations/init.sql
```

### 3. SSL Certificate (Let's Encrypt)
```bash
# Point your domain's A record to EC2 public IP first, then:
sudo certbot --nginx -d your-domain.com

# Certbot auto-installs a cron job / systemd timer for renewal.
# Certificates renew automatically every 60 days (expire at 90 days).
# Verify renewal is configured:
sudo systemctl status certbot.timer    # systemd-based
# OR
sudo crontab -l                        # cron-based (certbot installs this automatically)

# Manual renewal test (dry run):
sudo certbot renew --dry-run
```

**Renewal strategy:** Let's Encrypt certificates expire every 90 days. Certbot automatically installs a renewal hook (systemd timer or cron) that runs `certbot renew` twice daily. It only renews certificates within 30 days of expiry. This is not a one-time manual setup — renewal is fully automated.

### 4. Nginx Configuration
```bash
# Replace YOUR_DOMAIN in nginx/nginx.conf, then:
sudo cp nginx/nginx.conf /etc/nginx/sites-available/notes-app
sudo ln -s /etc/nginx/sites-available/notes-app /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5. Jenkins Setup
```bash
# Install Jenkins
wget -q -O - https://pkg.jenkins.io/debian/jenkins.io.key | sudo apt-key add -
sudo sh -c 'echo deb http://pkg.jenkins.io/debian-stable binary/ > /etc/apt/sources.list.d/jenkins.list'
sudo apt update && sudo apt install -y jenkins

# Run on port 9090 (not default 8080)
# Port 9090 chosen to avoid conflict with common dev tools on 8080
sudo sed -i 's/HTTP_PORT=8080/HTTP_PORT=9090/' /etc/default/jenkins
sudo systemctl restart jenkins

# Access Jenkins via SSH tunnel (not exposed to internet):
# ssh -L 9090:localhost:9090 -i your-key.pem ubuntu@EC2_IP
# Then open: http://localhost:9090
```

**Why port 9090?** The task explicitly requires a non-default port. Port 9090 is chosen because: (a) it avoids conflicts with common dev tools that use 8080, (b) port 8080 is often mistakenly left open — using 9090 with no SG rule removes the temptation. Jenkins is NOT accessible from the public internet — only via SSH tunnel.

### 6. Jenkins Credentials (Store — not in git)
Add these as Jenkins Secret Text / SSH credentials (Manage Jenkins → Credentials):
- `EC2_HOST` — EC2 public DNS
- `EC2_SSH_KEY` — SSH private key (type: SSH Username with private key)
- `DB_PASSWORD` — RDS password (type: Secret text)
- `DB_USER` — DB username
- `DB_HOST` — RDS endpoint
- `DB_NAME` — database name

---

## Health Check & Rollback — Precise Definition

| Parameter | Value | Rationale |
|---|---|---|
| Max retries | **5** | Allows for slow container startup; avoids false positives from a single slow response. |
| Wait between retries | **10 seconds** | Gives gunicorn + DB connection pool time to initialize. 5 × 10 = 50 s total window. |
| Per-call timeout | **5 seconds** | curl `--max-time 5`. A healthy app must respond within 5 s — longer indicates a problem. |
| Unhealthy condition | HTTP status **≠ 200** OR curl failure (timeout, connection refused) | The `/health` endpoint returns 200 only when both the app and DB are reachable. A 503 or timeout means something is broken. |
| Rollback trigger | All 5 attempts fail | Not a single failure — avoids rollback on transient network blips. |

**What rollback does:** Stops the new container, starts the previously-running image tag (saved before deploy begins). The old image is always kept locally on the EC2 host.

---

## Deploy/Rollback Downtime Analysis

**During deploy:** There is a brief (~2–5 second) window where the old container is stopped and the new one is starting. In-flight requests during this window will receive a connection refused error from Nginx (502 Bad Gateway). This is an **in-place deployment** — not zero-downtime.

**During rollback:** Same ~2–5 second gap as the new container is replaced with the old one.

**Acceptable for this assessment.** A zero-downtime approach (blue-green or canary) is described in the Bonus section below but not implemented here. The README honestly states the downtime window rather than hiding it.

---

## Local vs Production Database — Why Different?

| Concern | docker-compose DB container | RDS Managed Service |
|---|---|---|
| **Persistence** | Data lost if container is removed | Persistent, survives instance termination |
| **Backups** | None by default | Automated daily backups with point-in-time recovery |
| **High availability** | Single container, no failover | Multi-AZ option with automatic failover |
| **Maintenance** | Manual patching | AWS handles minor version patching |
| **Scaling** | Tied to EC2 instance resources | Can scale independently |
| **Security** | On same host as app | Isolated in private subnet, separate SG |

**What would break if docker-compose DB were used in production:** If the EC2 instance is terminated, replaced, or restarted, all data is lost. There are no automated backups. The database shares CPU/memory with the app and Jenkins, causing resource contention. It cannot be scaled independently.

---

## IAM Reviewer — Read-Only User (Scoped Permissions)

The reviewer IAM user has **only these specific permissions** — not the broad `ReadOnlyAccess` managed policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2Describe",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RDSDescribe",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances",
        "rds:DescribeDBSecurityGroups"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

**Why each permission:**
- `ec2:Describe*` — Reviewer can verify instance type, SG rules, and networking match what's documented here.
- `rds:Describe*` — Reviewer can confirm RDS is in a private subnet with correct SG.
- `logs:*` — Reviewer can read CloudWatch logs to verify health checks and pipeline runs.

**Why NOT `ReadOnlyAccess` managed policy:** It grants describe/list/get on nearly every AWS service — IAM, S3, Lambda, billing, etc. None of those are needed to verify this task. Attaching it would violate least-privilege even if it's technically read-only.

---

## Secrets Handling — Trace

| Stage | Where do DB credentials live? |
|---|---|
| **Build time** | Nowhere. Dockerfile does not receive or embed any credentials. The image contains only application code. |
| **Test stage (Jenkins)** | Injected as environment variables into a throwaway test container. Never written to disk or logs. |
| **Deploy stage (Jenkins)** | Retrieved from Jenkins Credentials store at runtime. Passed as `-e` flags to `docker run` on EC2 via SSH. Never appear in the Jenkinsfile as plaintext. |
| **Runtime (EC2)** | Live only in the container's process environment. Not written to any file on disk. |
| **Git history** | Never committed. `.env` is in `.gitignore`. Only `.env.example` with placeholder values is committed. |

---

## Bonus (Optional — Implemented)

- [x] **Slack notifications** — commented out in Jenkinsfile; uncomment and configure `SLACK_WEBHOOK` credential to enable.
- [ ] Infrastructure as Code (Terraform) — not implemented; time constraint noted.
- [ ] Blue-green deployment — not implemented; would require a load balancer or two EC2 instances.

---

## Repository Commit Structure

Commits follow logical progress (not a single dump):
1. `init: project scaffold and Flask app`
2. `feat: add /health endpoint and DB schema`
3. `docker: Dockerfile and docker-compose for local dev`
4. `ci: Jenkinsfile with build/test/deploy stages`
5. `infra: nginx config and SSL setup notes`
6. `ci: health check and auto-rollback logic`
7. `docs: README with architecture, ports, IAM, and trade-offs`

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | App + DB health check |
| GET | `/notes` | List all notes |
| POST | `/notes` | Create a note (`{"title": "...", "content": "..."}`) |
| GET | `/notes/:id` | Get a single note |
| PUT | `/notes/:id` | Update a note |
| DELETE | `/notes/:id` | Delete a note |

---

> **Credentials:** Jenkins viewer login and IAM access key/secret are sent separately via email — never committed here.
