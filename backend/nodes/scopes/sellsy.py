"""Sellsy v2 scopes, pinned API 2.316.0: https://docs.sellsy.com/api/v2/."""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

SELLSY_SCOPES = ScopeRegistry(
    provider="sellsy",
    requirements={
        **{f"{verb}_{singular if verb != 'list' else plural}": ScopeRequirement(scopes=(f"{plural}.{access}",))
           for plural, singular in (("companies", "company"), ("contacts", "contact"),
                                    ("individuals", "individual"), ("opportunities", "opportunity"))
           for verb, access in (("list", "read"), ("get", "read"), ("create", "write"), ("update", "write"))},
        "get_me": ScopeRequirement(scopes=("staffs.read",)),
    },
    enforcement=Enforcement.STRICT,
)
