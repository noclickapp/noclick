"""Scopes from Community API 20261106104747 operation security declarations.

https://api2-eu-west-1.insided.com/v2/swagger.json
Pasted bearer tokens carry provider-controlled grants; no interactive consent.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

GAINSIGHT_CUSTOMER_COMMUNITIES_SCOPES = ScopeRegistry("gainsight-customer-communities", {
    "list_categories": ScopeRequirement("read"),
    "get_category": ScopeRequirement("read"),
    "list_topics": ScopeRequirement("read"),
    "list_conversations": ScopeRequirement("read"),
    "get_conversation": ScopeRequirement("read"),
    "list_conversation_replies": ScopeRequirement("read"),
    "start_conversation": ScopeRequirement("write"),
    "reply_conversation": ScopeRequirement("write"),
    "edit_conversation_title": ScopeRequirement("write"),
    "edit_conversation_tags": ScopeRequirement("write"),
    "list_questions": ScopeRequirement("read"),
    "get_question": ScopeRequirement("read"),
    "ask_question": ScopeRequirement("write"),
    "reply_question": ScopeRequirement("write"),
    "list_articles": ScopeRequirement("read"),
    "get_article": ScopeRequirement("read"),
    "list_ideas": ScopeRequirement("read"),
    "get_idea": ScopeRequirement("read"),
    "list_tags": ScopeRequirement("read"),
    "create_tag": ScopeRequirement("write"),
})
