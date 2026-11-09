"""Outreach operation scope requirements.

Verified against the Scopes enum published by Outreach's API access app:
https://developers.outreach.io/apps/
https://developers.outreach.io/apps/marketplace.6d31acd2330ed155.js
OAuth setup: https://developers.outreach.io/api/oauth/

Keep the existing broad grants for supported resources. Scope names cannot be
inferred from HTTP methods: Kaia Voice Import only defines .write, with neither
.all nor .read. The public OpenAPI describes endpoints but omits OAuth scopes.
"""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.outreach_operations import OPERATIONS


_RESOURCE_SCOPES = {
    "accountNotes": "accountNotes.all",
    "accounts": "accounts.all",
    "auditLogs": "auditLogs.read",
    "batchItems": "batchItems.read",
    "batches": "batches.all",
    "callDispositions": "callDispositions.all",
    "callPurposes": "callPurposes.all",
    "calls": "calls.all",
    "complianceRequests": "complianceRequests.all",
    "contentCategories": "contentCategories.all",
    "contentCategoryMemberships": "contentCategoryMemberships.all",
    "contentCategoryOwnerships": "contentCategoryOwnerships.all",
    "duties": "duties.read",
    "emailAddresses": "emailAddresses.all",
    "events": "events.read",
    "favorites": "favorites.all",
    "imports": "imports.all",
    "kaiaRecordings": "kaiaRecordings.read",
    "kaiaVoiceImports": "kaiaVoiceImports.write",
    "mailAliases": "mailAliases.read",
    "mailboxes": "mailboxes.all",
    "mailings": "mailings.all",
    "opportunities": "opportunities.all",
    "opportunityProspectRoles": "opportunityProspectRoles.all",
    "opportunityStages": "opportunityStages.all",
    "orgSettings": "orgSettings.all",
    "personas": "personas.all",
    "phoneNumbers": "phoneNumbers.all",
    "products": "products.all",
    "profiles": "profiles.all",
    "prospectNotes": "prospectNotes.all",
    "prospects": "prospects.all",
    "purchases": "purchases.all",
    "recipients": "recipients.all",
    "roles": "roles.all",
    "rulesets": "rulesets.all",
    "sequenceStates": "sequenceStates.all",
    "sequenceSteps": "sequenceSteps.all",
    "sequenceTemplates": "sequenceTemplates.all",
    "sequences": "sequences.all",
    "snippets": "snippets.all",
    "stages": "stages.all",
    "taskDispositions": "taskDispositions.all",
    "taskPriorities": "taskPriorities.read",
    "taskPurposes": "taskPurposes.all",
    "tasks": "tasks.all",
    "teams": "teams.all",
    "templates": "templates.all",
    "users": "users.all",
    "webhooks": "webhooks.all",
}

OUTREACH_SCOPES = ScopeRegistry(
    provider="outreach",
    requirements={
        name: ScopeRequirement(scopes=(_RESOURCE_SCOPES[op.path.strip("/").split("/")[0]],))
        for name, op in OPERATIONS.items()
    } | {"on_event": ScopeRequirement(scopes=("webhooks.all",))},
)
