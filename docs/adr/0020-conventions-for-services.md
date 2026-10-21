# ADR-0020: Conventions for the services in `services/`

- **Status:** Accepted — implementation pending
- **Date:** 2026-10-21

## Context

memory-api was the only service built from the repository, and the release
tooling names it explicitly: `build-publish.sh` lists its build inputs, the
deployment hook removes `nyansa-memory-api:<sha>` images, and
`check-exposure.sh` has rules written for it. Phase 4b adds a second service
(ADR-0021), and the folder is meant to hold future ones.

## Decision

Every service lives in `services/<name>/` with the same structure
(`pyproject.toml`, `uv.lock` with hashes, `Dockerfile`, `src/`, `tests/`,
`README.md`, and its versioned `openapi.json`). Release building, image
cleanup and exposure checks treat every service of the folder the same way,
and rules specific to a service are declared by Compose labels, so adding a
service does not require changing these scripts.

## Alternatives considered

- **Keep naming each service in the scripts**: every new service would
  have to change `build-publish.sh`, the hook and `check-exposure.sh`.
- **A library shared by the services**: not for now; the common code (auth,
  logging, configuration) is small and is duplicated.

## Consequences

- `build-publish.sh` ships the build inputs of each `services/*/` folder and
  refuses one that breaks the convention, including a Dockerfile without a
  non-root `USER`; the hook removes every `nyansa-*:<sha>` image of a failed
  or pruned release.
- `check-exposure.sh` requires of every service built from `services/`: no
  published port, a read-only root filesystem, no capabilities and
  `no-new-privileges`. Labels add rules: `nyansa.single-instance` (one
  container, for memory-api's graph lock), `nyansa.isolated` with
  `nyansa.peers` (internal networks only, shared with the listed peers, and
  required memory, CPU and process limits).
- memory-api moves to these conventions without any change of behaviour,
  and gets resource limits only if a later decision says so.
- A drift test keeps each `openapi.json` equal to the spec the service
  generates.

## References

- Phase 4b plan (part A), validated on 2026-10-21; `services/README.md` (to
  be written).
- `scripts/build-publish.sh`, `hooks/post-receive`,
  `scripts/check-exposure.sh`.
