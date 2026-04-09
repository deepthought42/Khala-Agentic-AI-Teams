#-----------------------------------------------------------------------------
# Droplet
#-----------------------------------------------------------------------------
resource "digitalocean_droplet" "strands" {
  name   = var.droplet_name
  region = var.region
  size   = var.droplet_size
  image  = "ubuntu-24-04-x64"

  ssh_keys = var.ssh_key_fingerprints

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    docr_registry = var.docr_registry
  })

  tags = ["strands", var.environment]

  # user_data only runs at first boot; changing it would force a destroy/recreate
  # which would wipe postgres and agent workspaces. Guard against that — set
  # -replace=digitalocean_droplet.strands explicitly when a rebuild is intended.
  lifecycle {
    ignore_changes = [user_data, image]
  }
}

#-----------------------------------------------------------------------------
# Reserved IP — stable public address that survives droplet rebuilds
#-----------------------------------------------------------------------------
resource "digitalocean_reserved_ip" "strands" {
  region = var.region
}

resource "digitalocean_reserved_ip_assignment" "strands" {
  ip_address = digitalocean_reserved_ip.strands.ip_address
  droplet_id = digitalocean_droplet.strands.id
}

#-----------------------------------------------------------------------------
# Cloud Firewall
#
# SSH is world-open per deploy choice (Ubuntu 24.04 cloud image disables
# password auth by default, so key-only access is enforced).
# UI (4201) and unified API direct (8888) are world-open.
# Postgres (5432), Temporal gRPC (7233), and Temporal UI (8080) are NOT
# exposed — reach them via SSH tunnel.
#-----------------------------------------------------------------------------
resource "digitalocean_firewall" "strands" {
  name        = "${var.droplet_name}-fw"
  droplet_ids = [digitalocean_droplet.strands.id]

  # ── Ingress ─────────────────────────────────────────────────────────────
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "4201"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "8888"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "icmp"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # ── Egress ──────────────────────────────────────────────────────────────
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
