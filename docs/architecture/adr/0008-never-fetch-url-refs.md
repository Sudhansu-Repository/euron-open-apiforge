# ADR-0008: Never fetching URL `$ref`s, on the CLI or the server

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

OpenAPI allows `$ref` to point anywhere: another file next to the spec, or a URL. Many
tools resolve URL references by downloading them. In a service that accepts specs from
users, that turns every upload into a server-side request forgery primitive: a spec can
make the server request cloud metadata (`http://169.254.169.254/`), internal services, or
an attacker's server that serves a different document each time. On the CLI it makes
generation depend on the network, breaks determinism (the remote file can change) and
leaks which specs a developer is working on.

## Decision

- `$ref` targets are resolved only inside the spec itself: the same document, or another
  file of the same spec (a folder on the CLI, a zip upload in the service). Paths are
  normalized and may not leave the spec's folder.
- A `$ref` whose target contains `://` or starts with `//` is refused with a message that
  says what to do: download the file and pass it alongside the spec (a folder or a zip).
- Other URLs in a spec (`servers`, `externalDocs`, OpenID Connect discovery URLs) are data:
  copied into the generated project where they belong, never requested by APIForge.
- The service has no outbound HTTP client at all, so there is nothing to misuse.

## Consequences

**Good**
- No SSRF through specs, by construction rather than by allowlist.
- Generation is a pure function of the uploaded bytes, which keeps archives
  deterministic and the lint cache content-addressed.
- The CLI works offline, which the generator's tests enforce by blocking sockets.

**Bad / caveats**
- Specs that reference shared schemas by URL must be bundled first (or passed as a folder
  or zip with the referenced files).

## Alternatives considered

- **Fetch with an allowlist and address checks.** Defensible but fragile (DNS rebinding,
  redirects, IPv6 forms) and still nondeterministic.
- **Fetch on the CLI only.** Would make CLI and service output differ for the same spec,
  against [ADR-0005](0005-generator-as-a-shared-library.md).
