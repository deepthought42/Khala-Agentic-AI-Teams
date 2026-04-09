terraform {
  required_version = ">= 1.6"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.40"
    }
  }

  # Terraform Cloud free tier — state storage + locking only.
  # Set the workspace "Execution Mode" to "Local" in the TFC UI so plan/apply
  # runs in GitHub Actions and uses TFC purely for state.
  # Replace REPLACE_ME with your TFC organization name before the first init.
  cloud {
    organization = "REPLACE_ME"

    workspaces {
      name = "strands-dev"
    }
  }
}

provider "digitalocean" {
  # Token is read from DIGITALOCEAN_TOKEN env var (set in the workflow)
}
