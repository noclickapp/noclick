"""Docusign eSignature OAuth scope requirements.

Authorization Code Grant: `signature` authorizes eSignature REST calls and
`extended` renews the refresh token lifetime for unattended workflows.
https://developers.docusign.com/platform/auth/confidential-authcode-get-token
"""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


_OPERATIONS = (
    "get_account", "list_templates", "get_template", "create_from_template",
    "send_document", "get_envelope", "list_envelopes", "list_recipients",
    "list_documents", "download_document", "void_envelope",
)

DOCUSIGN_SCOPES = ScopeRegistry(
    provider="docusign",
    requirements={name: ScopeRequirement(scopes=("signature",)) for name in _OPERATIONS},
    extra_scopes={"default": ("extended",)},
)
