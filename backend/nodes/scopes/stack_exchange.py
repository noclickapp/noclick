"""Scopes from https://api.stackexchange.com/docs/authentication.

Pasted tokens are issued by the user's application, not by NoClick. This table
also exposes scope requirements to the platform's shared evidence check.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

STACK_EXCHANGE_SCOPES = ScopeRegistry(
    provider="stack_exchange",
    requirements={
        "get_me": ScopeRequirement(scopes=()),
        "list_questions": ScopeRequirement(scopes=()),
        "get_questions": ScopeRequirement(scopes=()),
        "list_question_answers": ScopeRequirement(scopes=()),
        "list_question_comments": ScopeRequirement(scopes=()),
        "get_answers": ScopeRequirement(scopes=()),
        "list_answer_comments": ScopeRequirement(scopes=()),
        "get_comments": ScopeRequirement(scopes=()),
        "search_questions": ScopeRequirement(scopes=()),
        "list_tags": ScopeRequirement(scopes=()),
        "get_users": ScopeRequirement(scopes=()),
        "list_user_questions": ScopeRequirement(scopes=()),
        "list_user_answers": ScopeRequirement(scopes=()),
        "list_my_inbox": ScopeRequirement(scopes=('read_inbox',)),
        "list_my_notifications": ScopeRequirement(scopes=('read_inbox',)),
        "create_comment": ScopeRequirement(scopes=('write_access',)),
        "edit_comment": ScopeRequirement(scopes=('write_access',)),
        "delete_comment": ScopeRequirement(scopes=('write_access',)),
    },
)
