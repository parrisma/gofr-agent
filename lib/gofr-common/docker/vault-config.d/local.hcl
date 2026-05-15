storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8201"
  tls_disable = 1
}

ui = true
cluster_addr = "https://0.0.0.0:8202"
api_addr     = "http://0.0.0.0:8201"
disable_mlock = true
