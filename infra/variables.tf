variable "droplet_name" {
  type        = string
  default     = "strands-dev"
  description = "Name/hostname of the droplet"
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Tag applied to DO resources for grouping"
}

variable "region" {
  type        = string
  default     = "nyc3"
  description = "DigitalOcean region slug (e.g. nyc3, sfo3, ams3, fra1, sgp1)"
}

variable "droplet_size" {
  type        = string
  default     = "s-4vcpu-8gb"
  description = <<-EOT
    Droplet size slug. Default s-4vcpu-8gb = Basic 4 vCPU / 8 GB / 160 GB SSD / $48/mo.
    The stack idles at ~8 GB so this tier will swap under load — acceptable for dev.
    Bump to s-4vcpu-16gb ($72/mo) or s-8vcpu-16gb ($96/mo) if you see OOM kills.
  EOT
}

variable "ssh_key_fingerprints" {
  type        = list(string)
  description = "Fingerprints of SSH keys already registered in DigitalOcean to install on the droplet"
}

variable "docr_registry" {
  type        = string
  description = "DigitalOcean Container Registry name (the part after registry.digitalocean.com/)"
}
