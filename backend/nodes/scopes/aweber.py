"""AWeber OAuth scopes per REST action.

The operation-to-scope mapping is taken from the security requirements in
https://api.aweber.com/swagger.yaml. Operations with an empty set require a
valid token but no narrower scope in the published contract.
"""

from nodes.aweber_operations import OPERATIONS
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement


AWEBER_SCOPES = ScopeRegistry(
    provider="aweber",
    requirements={
        **{action["id"]: ScopeRequirement(scopes=tuple(action["scopes"]))
           for action in OPERATIONS},
        "on_new_subscriber": ScopeRequirement(scopes=("subscriber.read",)),
    },
    enforcement=Enforcement.STRICT,
)
