# CI security gates

The CI workflow is deliberately fail-closed for dependency vulnerabilities and
static analysis. The checks use public, credential-free OSS tooling; they do
not upload findings to a scanning service or use a scanner token.

## Enforced checks

| Check | Tool and scope | Failure condition |
| --- | --- | --- |
| Dependency vulnerabilities | Trivy filesystem vulnerability scanner, commit-pinned to the reviewed `v0.28.0` Action revision. It scans the API's fully resolved `apps/api/requirements.lock`, the six root `packages/*/pyproject.toml` manifests installed by the API image, and each deployed JavaScript application's lockfile: `apps/admin/package-lock.json`, `apps/widget/package-lock.json`, and `apps/shopify-mcp/package-lock.json`. | Any library vulnerability with severity `HIGH` or `CRITICAL`, or a scanner execution failure. Unfixed findings are included. |
| SAST | The digest-pinned `semgrep/semgrep:1.91.0` container runs the public `p/default` ruleset only against canonical deployable code: `apps/api/app`, root `packages`, and each deployed JavaScript application's `src` directory. It also scans the four deployment Dockerfiles and `docker-compose.yml`. Test and spec files are excluded because they are not shipped runtime code. | Any SAST finding or scanner/rule-loading failure. `--disable-nosem` prevents inline `nosemgrep` comments from suppressing a finding. |
| SBOM and immutable inputs | `scripts/generate_sbom.py` creates a deterministic CycloneDX 1.5 inventory for every deployed Python/Node manifest. `scripts/verify_supply_chain.py` requires that output and verifies full-SHA GitHub Action refs across **all** repository workflows plus digest-pinned runtime Docker bases. | Missing/unreadable SBOM, any unpinned action, or any unpinned runtime base image. |
| Canonical source and API contract | `scripts/verify_canonical_packages.py` rejects an API-local copy of shared Python packages. The API job then verifies the committed OpenAPI 3.1 snapshot and Postman collection regenerate identically from FastAPI. | Missing canonical package, duplicate API-local source, or stale generated API artefact. |

Neither job uses `continue-on-error`, `--ignore-unfixed`, a baseline, nor an
ignore list. The dependency gate uses Trivy's `vuln` scanner only, so it does
not conflate vulnerability enforcement with optional secret or configuration
checks.

## Exception policy

There is no CI bypass or suppression path for these gates. A red security job
blocks the change until the finding is remediated, a dependency is upgraded or
replaced, or a SAST rule is corrected upstream. Do not add `nosemgrep` markers,
baselines, ignore files, `continue-on-error`, or `--ignore-unfixed` to make a
job pass.

If an operational release deadline cannot wait for remediation, record a
time-bounded risk-acceptance issue that identifies the scanner, finding ID,
affected component, compensating controls, owner, and expiry date; obtain
approval from the security owner and service owner. This records deployment
risk only—it does not waive or alter the CI result. The follow-up must restore
a green gate through an actual remediation before the expiry date.

## Python dependency locking

Dependabot checks npm and pip manifests weekly and now covers every deployed
Dockerfile directory: `/apps/api`, `/apps/admin`, `/apps/widget`, and
`/apps/shopify-mcp`.

`apps/api/requirements.txt` remains the API's direct, lower-bound dependency
intent. `apps/api/requirements.in` includes that file and the external runtime
requirements declared by the repository-root packages installed with the API.
`apps/api/requirements.lock` is the committed Python 3.12/Linux lock for their
complete external dependency graph. CI and the API image install it with
`--require-hashes`, install the local packages with `--no-deps
--no-build-isolation`, and run `pip check`.

When changing `requirements.txt`, a dependency declaration in one of the root
packages consumed by the API image, or a package build-system requirement,
update `requirements.in` as needed and regenerate the lock from the repository
root with this exact command:

```bash
docker run --rm --platform linux/amd64 \
  -v "$PWD:/src" -w /src/apps/api \
  python:3.12 \
  sh -c 'python -m pip install --no-cache-dir pip-tools==7.5.1 && pip-compile --resolver=backtracking --generate-hashes --allow-unsafe --output-file=requirements.lock requirements.in'
```

Review the resulting diff, then validate it through the clean API install and
`pip check` commands used by CI. Do not hand-edit hashes or package versions in
the lock. Dependabot continues to monitor the supported API pip manifest;
Dependabot updates that require a new resolved graph must be followed by this
regeneration step.

## Remaining release prerequisites

The lock fixes Python dependency reproducibility, but release integrity still
depends on externally retrieved artifacts. Before treating releases as fully
hermetic, mirror or otherwise control the Python package index/wheels used for
lock regeneration and installation, and mirror the public Trivy binary/database,
Semgrep image, and Semgrep ruleset used by CI. Verify that those mirrors retain
the exact locked artifacts and that normal image builds can run without public
registry access.

## Operational limitation

Both gates retrieve public artifacts at runtime: Trivy downloads its binary and
vulnerability database, while GitHub Actions pulls the Semgrep image and the
scanner retrieves the public ruleset. The Semgrep executable image is pinned by
digest; there is no in-repository mirror yet. Network or registry failures
therefore make the relevant job fail rather than silently skipping the security
check; add a controlled internal mirror if availability becomes a release
concern.

## Pinned build inputs

All GitHub Actions in CI and the protected release workflow are pinned to full
commit SHAs, and every runtime Docker base image used by the four services and Compose dependencies is pinned
to a digest. The human-readable tag is retained before the digest for upgrade
maintenance. Dependabot covers both service Dockerfile directories and the
repository-root Compose images, and remains responsible for proposing Docker updates;
reviewing such a change includes rebuilding, scanning, and accepting its new
digest deliberately.

## Release evidence handoff

The CI job uploads its generated CycloneDX file as the
`agentbuilder-sbom-<commit>` artifact for 90 days. The deployment workflow or
release operator must retain that artifact with the release record, alongside
the source commit, built image digest(s), CI run URL, approver, and deployment
timestamp. A green CI result proves the evidence was generated and validated;
it does not itself publish an image or sign an attestation.

The protected release workflow performs that separate promotion step: it
deploys only resolved `@sha256:` images, runs a dependency-aware smoke gate,
and signs release evidence with GitHub OIDC. See the [GA release and operations
contract](operations/GA_RELEASE_OPERATIONS.md).
