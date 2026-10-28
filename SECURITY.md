# Security Policy

APIForge reads specs from anyone, turns them into code your team will run, and stores
your API designs and the projects generated from them, so we take reports seriously and
respond quickly.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x | Yes |
| Earlier | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include:

- the affected component (`apps/forge`, `apps/api`, `apps/web`, `infra/terraform/...`)
  and version or commit,
- a description of the issue and its impact,
- steps to reproduce, or a proof of concept (a spec that triggers it is ideal),
- any suggested mitigation.

What to expect:

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## Scope

In scope: the code in this repository, the projects it generates, and the infrastructure
it provisions with its default settings. We are especially interested in:

- any spec that makes **generated code** do something the spec did not describe: text from
  a name, description, example, default, enum or pattern ending up outside a string
  literal, docstring or comment, or a generated project that compiles to different
  behaviour than its spec;
- any spec that makes the **CLI or the server** fetch a URL, read a file outside the spec,
  write outside its output folder or storage prefix, or execute code;
- a spec, zip or YAML document that exhausts memory or CPU despite the documented limits
  (size, depth, alias and value budgets, zip sizes);
- path traversal through upload file names, zip member names or the file browser;
- authentication or authorization bypasses: a viewer or an API key that can upload,
  generate, delete or change users; a signed-out or demoted session that keeps working;
- any way to recover an API key or a session from the API, logs or database;
- tampering with stored specs or archives that the service would not notice, or with the
  audit log;
- insecure defaults in generated projects (a secured operation answering without
  credentials, an empty secret accepted).

Out of scope:

- **The demo seed.** `make demo` creates well-known demo logins on purpose; do not run it
  on a real deployment (the command refuses `ENVIRONMENT=production`).
- **Code you wrote in a generated project.** Once you edit `app/auth.py` or a handler, its
  security is yours.
- Vulnerabilities in a generated project's third-party dependencies (FastAPI, Pydantic,
  SQLAlchemy and so on); report those upstream.
- Findings that require a compromised AWS account, database superuser access or leaked
  deployment secrets.
- Denial of service through legitimate load on a deployment you operate yourself.

## Hardening checklist for operators

See [docs/architecture/security.md](docs/architecture/security.md#operator-checklist). The
threat model is in [docs/architecture/threat-model.md](docs/architecture/threat-model.md).
