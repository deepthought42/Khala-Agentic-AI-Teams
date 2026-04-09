# infra/ — DigitalOcean droplet provisioning

Terraform that provisions a single DigitalOcean droplet running the Strands
Agents Docker Compose stack, with container images served from DOCR
(DigitalOcean Container Registry) built by GitHub Actions.

## What this creates

| Resource | Default | Notes |
|---|---|---|
| Droplet | `s-4vcpu-8gb` (Basic, $48/mo) | Ubuntu 24.04, 160 GB SSD |
| Reserved IP | — | Stable public address |
| Cloud firewall | 22, 4201, 8888 world-open | Postgres/Temporal internal only |

The droplet is bootstrapped by cloud-init (`cloud-init.yaml.tftpl`) which
installs Docker, sets up 8 GB of swap, opens the UFW firewall, and marks
itself ready. It does **not** clone the repo or start containers — the
`deploy.yml` workflow does that on its first run.

## One-time bootstrap

### 1. Create a DOCR registry

DO → **Container Registry → Create**. Pick a unique name (e.g. `my-strands`).
The free "Starter" tier gives 500 MB of storage — not enough for this stack.
You need at least the **Basic** tier ($5/mo, 5 GB) to hold all 6 images with a
few historical tags.

### 2. Create a Terraform Cloud workspace (free tier)

1. Sign up at https://app.terraform.io
2. Create an organization (note the name — you'll paste it into `versions.tf`)
3. Create a workspace named `strands-dev`, **CLI-driven workflow**
4. Workspace **Settings → General → Execution Mode → Local**
   (this makes TF run in GitHub Actions, not in TFC; TFC stores state only)
5. **User Settings → Tokens → Create an API token** — copy it

Edit `infra/versions.tf` and replace `REPLACE_ME` with your TFC org name.

### 3. Register an SSH key in DigitalOcean

DO → **Settings → Security → Add SSH Key**. Paste the public half
(`~/.ssh/id_ed25519.pub`). Note the MD5 fingerprint DigitalOcean displays.

### 4. Configure GitHub repository secrets and variables

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Name | Value |
|---|---|
| `DO_TOKEN` | DO → **API → Personal Access Tokens** (read+write, full access) |
| `TF_API_TOKEN` | TFC user API token from step 2 |
| `DO_SSH_FINGERPRINTS` | JSON array: `["aa:bb:cc:..."]` |
| `DROPLET_SSH_KEY` | Private half of the key from step 3 (full contents, `-----BEGIN OPENSSH PRIVATE KEY-----` ...) |
| `DROPLET_HOST` | *Leave empty until after step 5* |
| `OLLAMA_API_KEY` | From https://ollama.com/settings/keys |
| `POSTGRES_PASSWORD` | Strong random string (24+ chars) |

**Variables** (Settings → Secrets and variables → Actions → Variables):

| Name | Value |
|---|---|
| `DOCR_REGISTRY` | Registry name from step 1 (e.g. `my-strands`) |

### 5. First provision

Run the **"Provision infra (Terraform)"** workflow from the Actions tab:

1. First with `action=plan` — review the output
2. Then with `action=apply` — creates the droplet

When apply finishes, the workflow logs the reserved IP. **Copy that IP into
the `DROPLET_HOST` secret** in GitHub settings.

### 6. First deploy

Run the **"Build images & deploy to droplet"** workflow. This:

1. Builds all 6 distinct images in parallel (matrix build)
2. Pushes them to DOCR with tags `:latest` and `:<git-sha>`
3. SSHes into the droplet, clones the repo, writes `.env`, pulls images,
   runs `docker compose up -d --no-build`

First run: ~15–25 minutes (dominated by Playwright/Chromium build for
`strands-blogging-service`). Subsequent runs: ~3–5 minutes.

Open `http://<reserved-ip>:4201` and you should see the Angular UI.

## Day-2 operations

### Code changes

Merge to `main` → `deploy.yml` runs automatically on changes under
`backend/`, `user-interface/`, or the compose files.

### Infra changes

Edit `infra/*.tf` → run `provision.yml` with `action=plan`, review, then
`action=apply`.

Changing `user_data` in `cloud-init.yaml.tftpl` is **ignored** by default
(see `lifecycle.ignore_changes` in `main.tf`) to prevent accidental droplet
rebuilds that would wipe Postgres and agent workspaces. If you need to
re-run cloud-init, destroy and recreate the droplet deliberately:

```bash
# In the TFC workspace: Queue Destroy Plan
# Or from CLI:
terraform apply -replace=digitalocean_droplet.strands
```

### Tear down

Run `provision.yml` with `action=destroy`. This removes the droplet,
reserved IP, and firewall. DOCR images remain — delete them manually in the
DO console if you want a full cleanup.

### SSH into the droplet

```bash
ssh root@<reserved-ip>
cd /opt/strands-agents

# Logs for a single service
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.docr.yml \
  logs -f --tail=100 blogging-service

# Restart one service
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.docr.yml \
  restart se-service

# Full stack status
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.docr.yml \
  ps
```

## Notes on the 4 vCPU / 8 GB droplet size

The Strands stack idles at **~8 GB RAM** across its 27 containers. On an
8 GB droplet this is right at the edge — cloud-init creates an 8 GB swapfile
to absorb spikes, but any concurrent SE pipeline run or blogging Chromium
session will push into swap and slow down noticeably.

This is an intentional trade-off for a $48/mo dev environment. If you see
OOM kills in `docker compose ps` (containers stuck restarting with exit
code 137), bump the droplet size in `variables.tf`:

```hcl
variable "droplet_size" {
  default = "s-4vcpu-16gb"   # $72/mo, comfortable for dev
  # or  = "s-8vcpu-16gb"     # $96/mo, production-ish
}
```

Then run `provision.yml apply`. Resizing a droplet in-place preserves
volumes and the reserved IP (DO flags a brief reboot).

## Why this split?

Infra changes are rare and destructive; code changes are frequent and
cheap. Splitting the two workflows means:

- `provision.yml` is manual (`workflow_dispatch` only) — you explicitly
  decide when to touch infra
- `deploy.yml` runs automatically on `main` pushes — fast, image-pull only,
  no rebuild on the droplet
- A typo in a `.tf` file can't break a code deploy; a bad commit can't
  destroy your droplet
