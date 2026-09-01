# Edition boundary

Everything in this repository is open source under the AGPL-3.0-only, and it
runs end to end without access to NoClick-managed systems. This page describes
what the hosted service at noclick.com runs on top of it, and why those pieces
live elsewhere. The boundary is structural, not a runtime feature flag.

## In this repository

- workflow editing and execution;
- integration and trigger nodes;
- credential encryption and OAuth handling;
- local scheduling and event relay;
- local agent workspaces and CLI execution;
- expiring, single-use builder input links for answering a parked builder run;
- self-hosted MCP access;
- auth email through operator SMTP, application notifications through optional
  Resend, and S3-compatible storage;
- PostgreSQL/Supabase persistence and collaboration.

## What the hosted service adds

- managed hosting, deployment, and multi-region infrastructure;
- NoClick's hosted workflow-generation and model-routing pipeline;
- internal administration, incident-response, and diagnostic endpoints;
- internal analytics pipelines or customer-support tooling;
- managed billing, usage metering, or subscription enforcement;
- managed application publishing and NoClick-owned public ingress;
- private operational configuration, credentials, datasets, or run history.

## How the two halves meet

This repository has no **required** hosted dependency. Comments, documentation,
and explicitly guarded provider seams may name the hosted implementation they
interoperate with; the implementation itself is not included. Every import
needed by the community runtime resolves inside this tree, while an optional
hosted-provider import must be guarded so its absence is the normal,
tested self-hosted path. The export checks the actual file/import boundary
rather than relying on this description alone, so the tree you have is the tree
that runs.

That works because the dependency points the other way. Where a hosted
deployment does something differently — meters a call, runs code in a managed
sandbox, mounts a shared volume, drafts node configs with a larger pipeline —
this repository owns the seam and a working default for it, and the platform
registers its own implementation at start-up:

    # here: the seam, and the default it resolves to
    # backend/nodes/core/code_runtime.py
    register_python_runtime(runner)   # unset -> run_python_locally

    # a platform, once, at boot
    register_python_runtime(run_in_its_managed_sandbox)

So the defaults are not stubs to be filled in. They are the self-hosted
implementation, and they are the only one this repository's tests exercise.
A change to a seam is a change to both editions and needs to keep the default
working; a change behind one is not visible here at all.

Community modules may define generic interfaces—such as an object store, relay,
scheduler, mail transport, or OTLP exporter—but their default implementations
are local or operator-configured. They must not contain fixed NoClick service
URLs, credentials, or imports from a private package. The distributable client
SDKs are the deliberate exception: when an external application omits `url`,
they default to the managed `https://api.noclick.io` service. Self-hosted clients
pass their instance URL explicitly; the default is an onboarding convenience,
not a community-runtime dependency.

Pull requests that would change this boundary need maintainer approval and a
documented threat-model review.
