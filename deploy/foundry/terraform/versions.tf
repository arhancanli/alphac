terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  backend "s3" {
    endpoints = {
      s3 = "https://nyc3.digitaloceanspaces.com"
    }

    key = "production/alphac-foundry.tfstate"

    region                      = "us-east-1"
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_s3_checksum            = true
    use_lockfile                = true
  }

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "= 2.100.0"
    }
  }
}

provider "digitalocean" {}
