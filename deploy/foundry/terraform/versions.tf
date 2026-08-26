terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "= 2.100.0"
    }
  }
}

provider "digitalocean" {}
