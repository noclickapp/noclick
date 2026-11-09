"""GoTo Webinar product access is configured on the OAuth client.

The official v1 contract declares OAuth2 without named scopes:
https://developer.goto.com/resources/GoToWebinarV1.yml
Omitting scope requests the client's assigned scopes:
https://developer.goto.com/resources/Authentication.yml
SCIM /me requires no scope:
https://developer.goto.com/guides/Authentication/New_Token_Retrieval_Migration_Guide/
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.gotowebinar_operations import OPERATIONS

GOTOWEBINAR_SCOPES = ScopeRegistry(
    provider="gotowebinar",
    requirements={name: ScopeRequirement(scopes=()) for name in OPERATIONS},
    enforcement=Enforcement.STRICT,
)
