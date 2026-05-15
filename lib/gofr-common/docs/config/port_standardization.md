# Port Configuration

To avoid conflicts, every GOFR service runs on its own dedicated set of network ports.

This page lists which ports are used by which service, so you know where to look.

## Service Ports

Each service uses 3 consecutive ports (1 for MCP, 1 for OpenAPI, 1 for Web API).

| Service | MCP Port | API Port | Web Port | Description |
| :--- | :--- | :--- | :--- | :--- |
| **gofr-doc** | 8040 | 8041 | 8042 | Document generation |
| **gofr-plot** | 8050 | 8051 | 8052 | Graph rendering |
| **gofr-np** | 8060 | 8061 | 8062 | Math/Calculations |
| **gofr-dig** | 8070 | 8071 | 8072 | Web scraping |
| **gofr-iq** | 8080 | 8081 | 8082 | Intelligence & RAG |

## Infrastructure Ports

Backend tools use these standard ports:

| Service | Port | Description |
| :--- | :--- | :--- |
| **ChromaDB** | 8000 | Vector Database |
| **Vault** | 8201 | Secrets Manager |
| **Neo4j** | 7474 | Graph Database (Web) |

## Testing

When running tests, we shift all ports up by **100** to enable testing while production is running.

*   Production `gofr-dig`: **8070**
*   Test `gofr-dig`: **8170**
