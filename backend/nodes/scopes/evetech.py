"""Scopes from https://esi.evetech.net/meta/openapi.json (2020-01-01)."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

EVETECH_SCOPES = ScopeRegistry(provider="evetech", requirements={
    'list_market_orders': ScopeRequirement(scopes=()),
    'get_market_history': ScopeRequirement(scopes=()),
    'list_market_prices': ScopeRequirement(scopes=()),
    'get_character': ScopeRequirement(scopes=()),
    'get_corporation': ScopeRequirement(scopes=()),
    'get_type': ScopeRequirement(scopes=()),
    'get_wallet': ScopeRequirement(scopes=('esi-wallet.read_character_wallet.v1',)),
    'list_wallet_journal': ScopeRequirement(scopes=('esi-wallet.read_character_wallet.v1',)),
    'list_wallet_transactions': ScopeRequirement(scopes=('esi-wallet.read_character_wallet.v1',)),
    'list_assets': ScopeRequirement(scopes=('esi-assets.read_assets.v1',)),
    'get_skills': ScopeRequirement(scopes=('esi-skills.read_skills.v1',)),
    'get_skill_queue': ScopeRequirement(scopes=('esi-skills.read_skillqueue.v1',)),
    'get_location': ScopeRequirement(scopes=('esi-location.read_location.v1',)),
    'get_ship': ScopeRequirement(scopes=('esi-location.read_ship_type.v1',)),
    'list_mail': ScopeRequirement(scopes=('esi-mail.read_mail.v1',)),
    'get_mail': ScopeRequirement(scopes=('esi-mail.read_mail.v1',)),
    'send_mail': ScopeRequirement(scopes=('esi-mail.send_mail.v1',)),
    'update_mail': ScopeRequirement(scopes=('esi-mail.organize_mail.v1',)),
    'delete_mail': ScopeRequirement(scopes=('esi-mail.organize_mail.v1',)),
    'list_calendar': ScopeRequirement(scopes=('esi-calendar.read_calendar_events.v1',)),
    'respond_calendar': ScopeRequirement(scopes=('esi-calendar.respond_calendar_events.v1',)),
    'set_waypoint': ScopeRequirement(scopes=('esi-ui.write_waypoint.v1',)),
    'on_new_mail': ScopeRequirement(scopes=('esi-mail.read_mail.v1',)),
})
