"""The ``noclick`` command's shared pieces, which every part of it uses so they agree (the TypeScript CLI,
``src/cli/``, mirrors each):

- ``spec``: the one command spec both CLIs run from: ``spec/manifest.json``, the curated commands as the parser
  defines them (``scripts/cli_manifest.py --write``), and ``spec/operations.json``, every ``/v1`` operation, generated
  from the API's own description.
- ``commands``: the commands made from the spec: ``noclick <area> <command>`` for every operation, ``noclick api``,
  ``noclick describe`` and ``noclick help --json``.
- ``exits``: what an exit status means: 0 done, 1 failed, 2 the command line was wrong, 3 waiting on a person (the
  link is printed), 4 refused by a limit, a price or a policy, 124 a wait ran out, 130 Ctrl-C.
- ``output``: how a command prints. Results to stdout, notes to stderr, each line flushed; ``--json`` prints the
  whole answer, errors as ``{"error": {...}}``; the useful value (a URL, an id) is stdout's last line; an error's
  next step is printed as the command that takes it.
- ``link``: the folder's linked app (``.noclick/project.json``), so no command needs the app named again.
- ``spend``: ``--max-usd``: what an action would cost, said before it runs, and refused above the ceiling.
- ``kit``: what a part registers its commands with.

A part is a module in ``noclick._cli.parts`` with ``register(kit)``; the parser adds each, in name order, after the
commands ``noclick.cli`` defines itself and before the generated ones, so a part's command takes its name from a
generated operation's. Every command a part adds is a curated command of the spec: run
``python scripts/cli_manifest.py --write`` after adding one, and register it in the TypeScript CLI
(``register(path, run)`` in ``src/cli/main.ts``) when it runs there too.
"""
