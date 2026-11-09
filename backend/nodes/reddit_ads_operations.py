"""Reddit Ads v3 operation routes, each corresponding to one published endpoint.

This catalog keeps request dispatch and scope declarations in agreement without
changing a shared registry. Source: https://ads-api.reddit.com/api/v3/openapi.json.
"""

# operation -> (HTTP method, contract path, display name, UI group)
OPERATIONS = {'get_me': ('GET', '/me', 'Get My Ads Identity', 'Account'),
 'list_my_businesses': ('GET', '/me/businesses', 'List My Businesses', 'Account'),
 'get_business': ('GET', '/businesses/{business_id}', 'Get Business', 'Account'),
 'list_ad_accounts': ('GET',
                      '/businesses/{business_id}/ad_accounts',
                      'List Business Ad Accounts',
                      'Account'),
 'get_ad_account': ('GET', '/ad_accounts/{ad_account_id}', 'Get Ad Account', 'Account'),
 'list_campaigns': ('GET', '/ad_accounts/{ad_account_id}/campaigns', 'List Campaigns', 'Campaign'),
 'get_campaign': ('GET', '/campaigns/{campaign_id}', 'Get Campaign', 'Campaign'),
 'create_campaign': ('POST',
                     '/ad_accounts/{ad_account_id}/campaigns',
                     'Create Manual Campaign',
                     'Campaign'),
 'update_campaign': ('PATCH', '/campaigns/{campaign_id}', 'Update Campaign', 'Campaign'),
 'list_ad_groups': ('GET', '/ad_accounts/{ad_account_id}/ad_groups', 'List Ad Groups', 'Ad Group'),
 'get_ad_group': ('GET', '/ad_groups/{ad_group_id}', 'Get Ad Group', 'Ad Group'),
 'create_ad_group': ('POST',
                     '/ad_accounts/{ad_account_id}/ad_groups',
                     'Create Manual Ad Group',
                     'Ad Group'),
 'update_ad_group': ('PATCH', '/ad_groups/{ad_group_id}', 'Update Ad Group', 'Ad Group'),
 'list_ads': ('GET', '/ad_accounts/{ad_account_id}/ads', 'List Ads', 'Ad'),
 'get_ad': ('GET', '/ads/{ad_id}', 'Get Ad', 'Ad'),
 'create_ad': ('POST', '/ad_accounts/{ad_account_id}/ads', 'Create Standard Ad', 'Ad'),
 'update_ad': ('PATCH', '/ads/{ad_id}', 'Update Ad', 'Ad'),
 'get_report': ('POST', '/ad_accounts/{ad_account_id}/reports', 'Get Performance Report', 'Reporting'),
 'list_custom_audiences': ('GET',
                           '/ad_accounts/{ad_account_id}/custom_audiences',
                           'List Custom Audiences',
                           'Audience'),
 'list_pixels': ('GET', '/ad_accounts/{ad_account_id}/pixels', 'List Pixels', 'Measurement'),
 'list_profiles': ('GET', '/ad_accounts/{ad_account_id}/profiles', 'List Profiles', 'Creative')}
