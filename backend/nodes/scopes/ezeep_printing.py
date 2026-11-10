"""ezeep scope contract.
Printing: https://apidocs.ezeep.com/ezeepblue/auth/README.html
Webhooks: https://apidocs.ezeep.com/ezeepblue/api/rest_api/webhooks/README.html
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

EZEEP_PRINTING_SCOPES = ScopeRegistry(provider="ezeep-printing", requirements={
    "get_current_user": ScopeRequirement(("printing",)),
    "list_printers": ScopeRequirement(("printing",)),
    "get_printer": ScopeRequirement(("printing",)),
    "update_printer": ScopeRequirement(("printing",)),
    "delete_printer": ScopeRequirement(("printing",)),
    "get_printer_capabilities": ScopeRequirement(("printing",)),
    "list_print_jobs": ScopeRequirement(("printing",)),
    "get_print_job": ScopeRequirement(("printing",)),
    "delete_print_job": ScopeRequirement(("printing",)),
    "list_connectors": ScopeRequirement(("printing",)),
    "get_connector": ScopeRequirement(("printing",)),
    "update_connector": ScopeRequirement(("printing",)),
    "list_groups": ScopeRequirement(("printing",)),
    "get_group": ScopeRequirement(("printing",)),
    "create_group": ScopeRequirement(("printing",)),
    "update_group": ScopeRequirement(("printing",)),
    "delete_group": ScopeRequirement(("printing",)),
    "list_users": ScopeRequirement(("printing",)),
    "get_user": ScopeRequirement(("printing",)),
    "list_printer_profiles": ScopeRequirement(("printing",)),
    "get_printer_profile": ScopeRequirement(("printing",)),
    "create_printer_profile": ScopeRequirement(("printing",)),
    "update_printer_profile": ScopeRequirement(("printing",)),
    "delete_printer_profile": ScopeRequirement(("printing",)),
    "on_print_job_succeeded": ScopeRequirement(("webhooks",)),
})
