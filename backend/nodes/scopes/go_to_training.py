"""GoTo product access is selected on the OAuth client, not invented scope strings.

The published Training contract declares OAuth2 with an empty scope list.
Omitting scope requests all scopes assigned to the client: select GoTo Training.
https://developer.goto.com/Authentication
https://developer.goto.com/guides/Get%20Started/02_HOW_createClient/
The SCIM current-user identity read needs no token scope:
https://developer.goto.com/guides/Authentication/New_Token_Retrieval_Migration_Guide/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement
from nodes.go_to_training_operations import OPERATIONS

GO_TO_TRAINING_SCOPES = ScopeRegistry(
    provider="go_to_training",
    requirements={name: ScopeRequirement(scopes=()) for name in OPERATIONS},
    enforcement=Enforcement.STRICT,
)
