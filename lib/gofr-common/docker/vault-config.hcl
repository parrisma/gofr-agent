# Vault Production Configuration for GOFR (shared)
# File storage backend with KV secrets engine

storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8201"
  tls_disable = 1
}

api_addr     = "http://0.0.0.0:8201"
cluster_addr = "https://0.0.0.0:8202"
ui           = true

disable_mlock = true
