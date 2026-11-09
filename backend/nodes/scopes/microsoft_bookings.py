"""Microsoft Bookings delegated Graph permissions for work or school accounts.

ReadWrite.All is the documented common permission covering this node's reads,
appointment/customer writes and service/business writes; Manage.All is unnecessary.
See https://learn.microsoft.com/graph/api/bookingbusiness-post-services?view=graph-rest-1.0.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

BOOKINGS_SCOPES = ScopeRegistry(
    provider="microsoft-bookings",
    requirements={name: ScopeRequirement(scopes=("https://graph.microsoft.com/Bookings.ReadWrite.All",))
        for name in (
            "list_businesses", "get_business", "update_business",
            "list_appointments", "get_appointment", "create_appointment", "update_appointment", "delete_appointment",
            "list_customers", "get_customer", "create_customer", "update_customer", "delete_customer",
            "list_services", "get_service", "create_service", "update_service", "delete_service",
            "list_staff_members", "get_staff_member",
        )},
    extra_scopes={"default": ("https://graph.microsoft.com/User.Read", "offline_access")},
)
