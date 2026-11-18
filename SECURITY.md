# Security Policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Email
`security@noclick.com` with:

- the affected package and version, or the commit;
- reproduction steps or a proof of concept;
- the security impact you expect; and
- any known mitigations.

Please avoid accessing data that is not yours, disrupting a service, or using
automated scanners against systems you do not own. We will acknowledge a report
within five business days. We do not promise a bounty.

## Disclosure

We aim to publish a fix within **90 days** of acknowledging a report, and to
credit the reporter unless they ask otherwise. If a fix will take longer we will
say so and why, rather than let the date pass in silence. If a vulnerability is
already being exploited, we will publish as soon as there is something for
users to act on, which may be shorter than 90 days and may precede a fix.

A reporter is free to publish after 90 days whether or not we have shipped. We
would rather know a deadline is approaching than be surprised by it.

## How a fix reaches this repository

This repository is copied, commit by commit, from a folder of NoClick's main
repository, so a fix is committed there first and appears here once it lands
on that repository's main branch. A fix to a package is in the next
release of that package on npm or PyPI.

## Supported versions

Security fixes go into the current default branch and the next release of each
package. No long-term-support release line has been announced; upgrade to the
latest release.
