# ADR-0005: Deploy with Git hooks and immutable release folders

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Production must never run from a working tree, and a failed deployment must
leave the running stack usable. The server is a single host running Docker
Compose; the owner deploys by hand and wants each deployment's outcome in
the terminal of `git push`.

## Decision

`git push prod main` triggers a `post-receive` hook on the server, run by a
dedicated non-root user. It builds a release folder for the commit
(`releases/<sha>`, from `git archive`, runtime files only, no `.env`), takes
a backup, starts the stack under a fixed Compose project name, waits for
every container to be healthy, and only then switches the `current` link;
otherwise it restarts the previous release. Locally built images are tagged
with the release.

## Alternatives considered

- **An external CI/CD pipeline**: with one server and one developer, it
  would have had to hold access to the production server.
- **An image registry**: one more service to host and secure.

## Consequences

- A `pre-push` hook scans for secrets and builds the release locally with all
  checks before anything reaches the server.
- Each release keeps its own memory-api image, so a rollback runs the
  previous code; the 5 latest releases are kept by default (the active and
  the previous one never removed).
- A crash loop is detected after 3 restarts without waiting for the timeout,
  and a failed release is discarded with its image so it does not evict a
  working one.
- The production `.env` lives in `shared/` and is linked into each release;
  data volumes are shared by every release.
- Trade-off accepted: the images of the services in `services/` are built on
  the production server, during the deployment of each new release.

## References

- `fee91ea`, `d2d36e2`, `8f8de55`, `56ce5a3`, `23be770`, `9db3b8a`;
  phase 1 merged in `f191246`.
- `hooks/post-receive`, `hooks/pre-push`, `scripts/build-publish.sh`,
  `scripts/wait-healthy.sh`, `docs/DEPLOY.md` (sections "How deployment
  works" and "Rollback").
