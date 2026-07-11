# Security Policy

## Scope

This policy applies to the SysControl repository and official builds published from this project.

## Local-First Security and Privacy

SysControl is designed to run locally on your machine:

- Tool execution happens on-device.
- Chat history and config are stored locally (for example under `~/.syscontrol/`).
- SysControl does not include telemetry or analytics collection.
- SysControl does not send your data to a SysControl-managed cloud service.

## Cloud Usage Clarification

SysControl supports optional third-party providers if you manually configure them.

- In local mode (Ollama), prompts and responses stay local.
- If you enable a third-party cloud provider, data is sent directly to that provider by your choice.
- SysControl does not proxy or re-host those requests.

## External MCP Connectors

External connectors are disabled by default and require the explicit
`allow_connectors` permission. SysControl launches configured stdio connectors
without a shell, namespaces their tools, supplies a minimal process environment,
and only passes additional environment variables by explicit name. Connector
commands are third-party code and should only be configured from trusted sources.

## Local Credentials and Audit Data

Provider keys use macOS Keychain or Windows Credential Manager when available.
Headless Linux systems without a credential backend fall back to an owner-only
(`0600`) JSON file. The local tool audit records timestamps, tool names, risk,
argument names, and status; it deliberately does not store argument or result
values. Scheduled automations are disabled by default and are restricted to
read-only built-in tools.

## Ollama Security Policy

For Ollama’s official vulnerability disclosure and security policy, see:

- https://github.com/ollama/ollama/security/policy

## Reporting a Vulnerability

If you discover a security issue in SysControl:

1. Do not post exploit details publicly.
2. Open a private security advisory in this repository (GitHub Security Advisories), if available.
3. If private advisories are unavailable, open an issue with minimal details and request a private contact channel.
