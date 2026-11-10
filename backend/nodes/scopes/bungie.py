"""Bungie permissions from its published OpenAPI 2.21.9 contract.

Private Destiny reads additionally require the inventory scope as documented by
the contract's OAuth scope description. Manual tokens keep their existing grants.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

BUNGIE_SCOPES = ScopeRegistry(provider="bungie", requirements={
    'get_current_user': ScopeRequirement(scopes=('ReadBasicUserProfile',)),
    'get_manifest': ScopeRequirement(scopes=()),
    'search_player': ScopeRequirement(scopes=()),
    'get_memberships': ScopeRequirement(scopes=()),
    'get_profile': ScopeRequirement(scopes=('ReadDestinyInventoryAndVault',)),
    'get_character': ScopeRequirement(scopes=('ReadDestinyInventoryAndVault',)),
    'get_item': ScopeRequirement(scopes=('ReadDestinyInventoryAndVault',)),
    'get_vendors': ScopeRequirement(scopes=('ReadDestinyInventoryAndVault',)),
    'get_milestones': ScopeRequirement(scopes=()),
    'get_activity_history': ScopeRequirement(scopes=()),
    'get_post_game_report': ScopeRequirement(scopes=()),
    'transfer_item': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'pull_from_postmaster': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'equip_item': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'equip_items': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'set_item_lock_state': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'equip_loadout': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'snapshot_loadout': ScopeRequirement(scopes=('MoveEquipDestinyItems',)),
    'on_new_activity': ScopeRequirement(scopes=()),
})
