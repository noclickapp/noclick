# Contributing

Issues and pull requests are welcome. Open an issue for a bug (with the version and the smallest
code that shows it) or to discuss a change before you make it; send a pull request for a fix.

## How a change lands

This repository is copied, commit by commit, from a folder of NoClick's main repository, so
nothing is merged here directly. An accepted pull request is applied in the main repository and
comes back here as a commit with you as its author. The pull request is then closed as landed,
not merged with the merge button.

Before you send one, run `scripts/check.sh`: it builds and tests everything, as CI does.

## Licence

This repository is Apache-2.0, and so is what you contribute to it (section 5 of the
[licence](LICENSE)). There is no contributor agreement to sign.

To report a vulnerability, follow [SECURITY.md](SECURITY.md) rather than opening an issue.

Everyone taking part here follows the [code of conduct](CODE_OF_CONDUCT.md).
