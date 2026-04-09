output "droplet_id" {
  value       = digitalocean_droplet.strands.id
  description = "DigitalOcean droplet ID"
}

output "public_ip" {
  value       = digitalocean_reserved_ip.strands.ip_address
  description = "Reserved IP attached to the droplet. Set this as the DROPLET_HOST secret in GitHub so the deploy workflow knows where to SSH."
}

output "ui_url" {
  value = "http://${digitalocean_reserved_ip.strands.ip_address}:4201"
}

output "api_url" {
  value = "http://${digitalocean_reserved_ip.strands.ip_address}:8888/health"
}

output "ssh_command" {
  value = "ssh root@${digitalocean_reserved_ip.strands.ip_address}"
}
