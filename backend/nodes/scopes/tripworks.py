"""REST key resource scopes from https://api-docs.tripworks.com/openapi.json (1.1.6)."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

TRIPWORKS_SCOPES = ScopeRegistry(provider="tripworks", requirements={
    'list_customers': ScopeRequirement(scopes=('customers.read',)),
    'get_customers': ScopeRequirement(scopes=('customers.read',)),
    'list_trips': ScopeRequirement(scopes=('trips.read',)),
    'get_trips': ScopeRequirement(scopes=('trips.read',)),
    'list_bookings': ScopeRequirement(scopes=('bookings.read',)),
    'get_bookings': ScopeRequirement(scopes=('bookings.read',)),
    'list_experiences': ScopeRequirement(scopes=('experiences.read',)),
    'get_experiences': ScopeRequirement(scopes=('experiences.read',)),
    'list_locations': ScopeRequirement(scopes=('locations.read',)),
    'get_locations': ScopeRequirement(scopes=('locations.read',)),
    'list_gift_cards': ScopeRequirement(scopes=('gift-cards.read',)),
    'get_gift_cards': ScopeRequirement(scopes=('gift-cards.read',)),
    'create_customer': ScopeRequirement(scopes=('customers.write',)),
    'update_customer': ScopeRequirement(scopes=('customers.write',)),
    'create_booking': ScopeRequirement(scopes=('bookings.write',)),
    'list_booking_statuses': ScopeRequirement(scopes=('bookings.read',)),
    'set_booking_status': ScopeRequirement(scopes=('bookings.write',)),
    'list_trip_notes': ScopeRequirement(scopes=('trip-notes.read',)),
    'create_trip_note': ScopeRequirement(scopes=('trip-notes.write',)),
    'update_trip_note': ScopeRequirement(scopes=('trip-notes.write',)),
    'on_new_customers': ScopeRequirement(scopes=('customers.read',)),
    'on_new_trips': ScopeRequirement(scopes=('trips.read',)),
})
