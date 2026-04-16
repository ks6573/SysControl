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

## Ollama Security Policy

For Ollama’s official vulnerability disclosure and security policy, see:

- https://github.com/ollama/ollama/security/policy

## Reporting a Vulnerability

If you discover a security issue in SysControl:

1. Do not post exploit details publicly.
2. Open a private security advisory in this repository (GitHub Security Advisories), if available.
3. If private advisories are unavailable, open an issue with minimal details and request a private contact channel.

