# Security policy

## Supported versions

Nyansa is deployed from the `main` branch; there are no versioned releases.
Only the latest commit of `main` receives security fixes.

| Version | Supported |
|---|---|
| `main` (latest commit) | Yes |
| Older commits, forks | No |

## Reporting a vulnerability

Please do not open a public issue, discussion or pull request for a
vulnerability.

Report it privately through GitHub: on the repository, open the **Security**
tab, then **Report a vulnerability**
([private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)).
Only the maintainer sees the report.

Please include:

- the affected component (Compose file, Caddy configuration, memory-api,
  n8n workflow, Open WebUI pipe, deployment hook or script) and the commit;
- the steps to reproduce, and the profiles used (`cpu`, `public`,
  `tailscale`, ...);
- the impact you expect (for example access to the notes, to a secret, or to
  a service from outside).

Never include a real secret, a real domain or a server address in the
report: use placeholders.

Nyansa is a personal project with a single maintainer, so there is no
guaranteed response time. You will get an acknowledgement in the advisory,
then updates there until the report is fixed or declined, with the reason.
Once a fix is on `main`, the advisory is published, crediting you unless you
prefer otherwise.

## Scope

In scope: the code and configuration of this repository, and the security
measures described in the [README](README.md#security), including their
known limits.

Out of scope: vulnerabilities of the upstream projects themselves (n8n,
Ollama, Qdrant, PostgreSQL, Open WebUI, Caddy, Tailscale, LadybugDB), which
should be reported to them, unless Nyansa's configuration makes them
exploitable.
