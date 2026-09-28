terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# 1. The Resource Group
resource "azurerm_resource_group" "rg" {
  name     = "${var.project_name}-rg"
  location = var.location
}

# 2. Azure Container Registry (To store the Docker images)
resource "azurerm_container_registry" "acr" {
  name                = "${var.project_name}acr2026" # ACR names must be globally unique and alphanumeric
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true
}

# 3. The Server Farm (App Service Plan)
resource "azurerm_service_plan" "app_plan" {
  name                = "${var.project_name}-plan"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "B1" # Basic tier, perfect for bootcamp projects
}

# 4. The Live Web App
resource "azurerm_linux_web_app" "webapp" {
  name                = "${var.project_name}-webapp-2026"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.app_plan.id

  site_config {
    always_on = true
  }

  app_settings = {
    # This tells Azure to route web traffic to Streamlit's port
    "WEBSITES_PORT" = "8502"
  }
}