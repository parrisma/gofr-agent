# Reasoning Stream Sequence Diagram

This diagram shows the interaction shape for the reasoning stream: services are
laid out horizontally, time flows downward, and result handoff is mediated by
gofr-agent rather than passed directly from one MCP service to another.

~~~mermaid
sequenceDiagram
   autonumber
   participant Caller
   participant Agent as gofr-agent
   participant Registry as ServiceRegistry
   participant Source as MCP Service A
   participant Next as MCP Service B

   Note over Agent,Registry: Startup
   Agent->>Registry: load configured services
   Registry-->>Agent: manifest discovery status\nready or failed per service

   opt Runtime registration
      Caller->>Agent: register_service(url)
      Agent->>Registry: validate registration policy\nand probe target MCP service
      alt Registration accepted
         Registry-->>Agent: discovered valid manifest
         Agent-->>Caller: registration success
      else Registration rejected
         Registry-->>Agent: disabled disallowed host\nor invalid manifest
         Agent-->>Caller: explicit registration failure
      end
   end

   Caller->>Agent: ask(question, session_id, model_override?)
   Agent-->>Caller: run_started notification\nrequest_id assigned

   Agent->>Source: tool_call(source_tool, args)
   alt Transient source failure
      Source-->>Agent: transient error
      Agent-->>Caller: tool_retry notification
      Agent->>Source: retry source_tool
   end
   Source-->>Agent: tool_result(result set)
   Agent-->>Caller: tool_result notification

   Note over Agent: wrap result with provenance markers\nand payload bounds
   Note over Agent: model treats result as data\nand negotiates next tool call

   Agent->>Next: tool_call(next_tool, args derived from prior result set)
   alt Transient next-service failure
      Next-->>Agent: transient error
      Agent-->>Caller: tool_retry notification
      Agent->>Next: retry next_tool
   end
   Next-->>Agent: tool_result(derived result)
   Agent-->>Caller: tool_result notification

   opt Session compaction
      Agent-->>Caller: summary_update notification
   end

   Agent-->>Caller: run_completed notification
   Agent-->>Caller: final response\nanswer plus derived steps
~~~