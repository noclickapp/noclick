"""Delegated work/school Graph permissions, verified against each method's Learn page.

https://learn.microsoft.com/graph/api/virtualeventwebinar-getbyuserrole
https://learn.microsoft.com/graph/api/virtualeventsroot-post-webinars
https://learn.microsoft.com/graph/api/virtualevent-post-presenters
https://learn.microsoft.com/graph/api/virtualeventregistrationconfiguration-list-questions
https://learn.microsoft.com/graph/api/virtualeventregistration-get
https://learn.microsoft.com/graph/api/virtualevent-list-sessions
https://learn.microsoft.com/graph/api/user-get
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

READ = "https://graph.microsoft.com/VirtualEvent.Read"
WRITE = "https://graph.microsoft.com/VirtualEvent.ReadWrite"
USER = "https://graph.microsoft.com/User.Read"
TEAMS_EVENTS_SCOPES = ScopeRegistry(
    provider="microsoft",
    requirements={
        "get_account": ScopeRequirement(scopes=(USER,)),
        **{name: ScopeRequirement(scopes=(WRITE,)) for name in (
            "list_my_webinars", "get_webinar", "create_webinar", "update_webinar",
            "create_presenter", "update_presenter", "get_registration_configuration",
            "create_registration_question", "delete_registration_question",
            "get_registration", "list_sessions", "get_session",
        )},
        "list_registration_questions": ScopeRequirement(scopes=(READ,)),
    },
    extra_scopes={"default": ("offline_access",)},
)
