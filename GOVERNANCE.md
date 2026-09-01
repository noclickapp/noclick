# Governance

NoClick maintains this project and sets its product direction, release policy,
community-edition boundary, and licensing. Maintainer nominations and changes
are recorded through reviewed pull requests to this document.

## Decisions

Routine changes are decided through pull-request review. Significant changes
should begin with an issue describing the problem, alternatives, compatibility
impact, security implications, and migration plan. Maintainers seek consensus
but may make a final decision when consensus is not possible.

## Maintainers

Maintainers review changes, manage releases, enforce project policies, and
handle security reports. New maintainers are appointed by existing maintainers
based on sustained, constructive contributions and sound judgment.

## Releases

Only maintainers create releases. A release requires passing automated checks,
a dependency and secret scan, review of database changes, and explicit human
approval. Security-sensitive releases may use an abbreviated process when delay
would increase risk.

## Scope

This repository is open source under the AGPL and contains complete,
self-hosted implementations of every seam it defines. The hosted service's
managed infrastructure, internal operations tooling, private diagnostics, and
its workflow-generation pipeline are maintained separately. Contributions that
cross this boundary require an explicit maintainer decision.
