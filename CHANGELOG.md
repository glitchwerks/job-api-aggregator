# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** Version `0.1.0` is pre-release scaffolding (Issue A skeleton).
> No public release has been made yet. The first public release will be
> `v1.0.0` once the Code-complete gate defined in the execution plan is
> satisfied and the external consumer has validated the package contract.

## [Unreleased]

### Added

- v1.0 documentation set: output_schema.md, plugin_authoring.md, credentials_format.md, sample-output.jsonl, README quickstart (#19)
- Community meta files: CONTRIBUTING, SECURITY, issue templates, PR template (#20)
- Plugin: `adzuna` source migrated from legacy repo (#5)
- Plugin: `arbeitnow` source migrated from legacy repo (#6)
- Plugin: `himalayas` source migrated from legacy repo (#7)
- Plugin: `jobicy` source migrated from legacy repo (#8)
- Plugin: `jooble` source migrated from legacy repo (#9)
- Plugin: `jsearch` source migrated from legacy repo (#10)
- Plugin: `remoteok` source migrated from legacy repo (#11)
- Plugin: `remotive` source migrated from legacy repo (#12)
- Plugin: `the_muse` source migrated from legacy repo (#13)
- Plugin: `usajobs` source migrated from legacy repo (#14)

### Changed

- Dropped `--ignore-vuln CVE-2026-3219` workaround from the `pip-audit` CI step; pip 26.1 (pypa/pip PR #13870, merged 2026-04-19) ships the fix, so the suppression is no longer needed. (#48)

### Deprecated

### Removed

### Fixed

- `jobs` subcommand no longer requires `--credentials` when all selected sources are no-auth. When some selected sources do require credentials, the error names them explicitly instead of the generic argparse message. (#50)
- README quickstart example now explicitly excludes credentialed sources (`adzuna,jooble,jsearch,usajobs`) so the bare copy-paste invocation runs out of the box without a credentials file. The previous example was inconsistent with the new `--credentials` guard introduced in #51. (#52)

### Security
