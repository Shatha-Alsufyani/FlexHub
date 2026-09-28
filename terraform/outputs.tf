output "live_app_url" {
  value       = "https://${azurerm_linux_web_app.webapp.default_hostname}"
  description = "The live public URL of your FlexHub workspace"
}

output "container_registry_login_server" {
  value       = azurerm_container_registry.acr.login_server
  description = "The URL of the private container registry"
}
