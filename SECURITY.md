# Security Policy

## Project status

ReconForge is currently an engineering prototype using synthetic data.

It is not a production payment system and should not be used to process real
financial transactions or sensitive customer data.

## Reporting a vulnerability

Please do not publish security vulnerabilities, credentials, exploit details,
or sensitive data in a public GitHub issue.

Prefer GitHub's private vulnerability reporting when it is available for this
repository.

If private reporting is unavailable, open a minimal issue requesting a private
contact channel without including vulnerability details.

## Secrets

API credentials must never be committed to the repository.

ReconForge expects provider credentials to be supplied through the local
environment. CI and the offline test suite do not require paid-model API keys.

## Current security boundaries

The current prototype intentionally provides:

- read-only MCP tools;
- host-controlled case and version scope;
- bounded model tool access;
- deterministic financial calculations outside the model;
- evidence validation before investigation output is accepted;
- no accounting or payment execution.

The prototype does not yet provide authentication, tenant authorization,
production secret management, or a hardened deployment environment.

See the README and verification documentation for the current implementation
scope.