# Changelog

All notable changes to ReconForge will be documented in this file.

The project follows semantic versioning while it remains in early development.

## [Unreleased]


### Added

- Offline investigator evaluation harness.
- Structured evaluation results for contract status, case context,
  evidence coverage, extra evidence usage, and playbook-order agreement.
- Human-readable and JSON evaluation demo.
- Regression tests for evaluator behavior.

### Notes

- Reference-order agreement is descriptive and is not presented as a
  model-quality score.
- Evaluation requires no paid model API calls.

## [0.0.6] - 2026-09-28

### Added

- Bounded model-assisted investigation flow.
- Anthropic Messages tool-use provider adapter.
- OpenAI Responses function-calling provider adapter.
- Provider-independent investigator contract.
- Case-specific investigation playbook schemas.
- Host-side validation for final investigation proposals.
- Regression coverage for incomplete model playbook submissions.
- Live Anthropic verification for both bundled synthetic cases.
- Public security policy.
- Architecture-focused README documentation.

### Changed

- Tightened provider-facing schemas so models can select only playbook codes
  applicable to the selected investigation report.
- Improved documentation around deterministic financial calculations,
  evidence boundaries, model permissions, and current limitations.

### Verified

- 122 offline tests passing.
- Real local MCP subprocess integration tests.
- Mocked provider transport tests.
- Live Claude Sonnet 5 tool-use execution across both synthetic cases.

### Known limitations

- Synthetic data only.
- No authentication or tenant authorization.
- No production payment-provider integrations.
- No persistent production database.
- No human approval interface.
- No financial mutation or payment execution.
- No formal model-quality benchmark.
- No production deployment.

[0.0.6]: https://github.com/SamanGharagozlou/reconforge/releases/tag/v0.0.6