"""Twilio SendGrid workflow actions generated from the official v3 OpenAPI specs."""

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


# Provider operation metadata stays in the self-contained integration module.
OPERATIONS: dict[str, dict[str, Any]] = {'account_provisioning_authenticate_account': {'name': 'account_provisioning_authenticate_account',
                                               'label': 'Authenticate an account with single sign '
                                                        'on',
                                               'description': 'Authenticates and logs in a user to '
                                                              'Twilio Sendgrid as a specific admin '
                                                              'identity configured for SSO by '
                                                              'partner. Any additional teammates '
                                                              'or subusers will need to log in '
                                                              'directly via app.sendgrid.com',
                                               'category': 'Account',
                                               'family': 'account_provisioning',
                                               'method': 'POST',
                                               'path': '/v3/partners/accounts/{accountID}/sso',
                                               'required_params': [],
                                               'body_required': False,
                                               'body_type': None,
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_create_account': {'name': 'account_provisioning_create_account',
                                         'label': 'Create an account',
                                         'description': 'Creates a new account, with specified '
                                                        'offering, under the organization.',
                                         'category': 'Account',
                                         'family': 'account_provisioning',
                                         'method': 'POST',
                                         'path': '/v3/partners/accounts',
                                         'required_params': [],
                                         'body_required': True,
                                         'body_type': 'application/json',
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_delete_account': {'name': 'account_provisioning_delete_account',
                                         'label': 'Delete an account',
                                         'description': 'Delete a specific account under your '
                                                        'organization by account ID. Note that '
                                                        'this is an **irreversible** action that '
                                                        'does the following: - Revokes API Keys '
                                                        'and SSO so that the account user cannot '
                                                        'log in or access SendGrid data. - Removes '
                                                        'all offerings and configured SendGrid '
                                                        'resources such as dedicated IPs. - '
                                                        'Cancels billing effective immediately.',
                                         'category': 'Account',
                                         'family': 'account_provisioning',
                                         'method': 'DELETE',
                                         'path': '/v3/partners/accounts/{accountID}',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_get_account_state': {'name': 'account_provisioning_get_account_state',
                                            'label': "Get an account's state",
                                            'description': 'Retrieve the state of the specified '
                                                           'account.',
                                            'category': 'Account State',
                                            'family': 'account_provisioning',
                                            'method': 'GET',
                                            'path': '/v3/partners/accounts/{accountID}/state',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': None,
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_list_account': {'name': 'account_provisioning_list_account',
                                       'label': 'Get all accounts',
                                       'description': 'Retrieves all accounts under the '
                                                      'organization.',
                                       'category': 'Account',
                                       'family': 'account_provisioning',
                                       'method': 'GET',
                                       'path': '/v3/partners/accounts',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_list_account_offering': {'name': 'account_provisioning_list_account_offering',
                                                'label': 'Get account offerings',
                                                'description': 'Retrieves offering information '
                                                               'about the specified account.',
                                                'category': 'Offering',
                                                'family': 'account_provisioning',
                                                'method': 'GET',
                                                'path': '/v3/partners/accounts/{accountID}/offerings',
                                                'required_params': [],
                                                'body_required': False,
                                                'body_type': None,
                                                'regions': ['us', 'eu'],
                                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_list_offering': {'name': 'account_provisioning_list_offering',
                                        'label': 'Get all available offerings',
                                        'description': 'Retrieves offerings available under the '
                                                       'organization.',
                                        'category': 'Offering',
                                        'family': 'account_provisioning',
                                        'method': 'GET',
                                        'path': '/v3/partners/offerings',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_update_account_offering': {'name': 'account_provisioning_update_account_offering',
                                                  'label': 'Update account offerings',
                                                  'description': 'Changes a package offering for '
                                                                 'the specified account. Please '
                                                                 'note that an account can have '
                                                                 'only one package offering. Also '
                                                                 'associates one or more add-on '
                                                                 'offerings such as Marketing '
                                                                 'Campaigns, Dedicated IP '
                                                                 'Addresses, and Expert Services '
                                                                 'to the specified account.',
                                                  'category': 'Offering',
                                                  'family': 'account_provisioning',
                                                  'method': 'PUT',
                                                  'path': '/v3/partners/accounts/{accountID}/offerings',
                                                  'required_params': [],
                                                  'body_required': True,
                                                  'body_type': 'application/json',
                                                  'regions': ['us', 'eu'],
                                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'account_provisioning_update_account_state': {'name': 'account_provisioning_update_account_state',
                                               'label': "Update an account's state",
                                               'description': 'Update the state of the specified '
                                                              'account.',
                                               'category': 'Account State',
                                               'family': 'account_provisioning',
                                               'method': 'PUT',
                                               'path': '/v3/partners/accounts/{accountID}/state',
                                               'required_params': [],
                                               'body_required': True,
                                               'body_type': 'application/json',
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_account_provisioning_v3.json'},
 'alerts_create_alert': {'name': 'alerts_create_alert',
                         'label': 'Create a new Alert',
                         'description': '**This endpoint allows you to create a new alert.**',
                         'category': 'Alerts',
                         'family': 'alerts',
                         'method': 'POST',
                         'path': '/v3/alerts',
                         'required_params': [],
                         'body_required': False,
                         'body_type': 'application/json',
                         'regions': ['us', 'eu'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_alerts_v3.json'},
 'alerts_delete_alert': {'name': 'alerts_delete_alert',
                         'label': 'Delete an alert',
                         'description': '**This endpoint allows you to delete an alert.**',
                         'category': 'Alerts',
                         'family': 'alerts',
                         'method': 'DELETE',
                         'path': '/v3/alerts/{alert_id}',
                         'required_params': [],
                         'body_required': False,
                         'body_type': None,
                         'regions': ['us', 'eu'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_alerts_v3.json'},
 'alerts_get_alert': {'name': 'alerts_get_alert',
                      'label': 'Retrieve a specific alert',
                      'description': '**This endpoint allows you to retrieve a specific alert.**',
                      'category': 'Alerts',
                      'family': 'alerts',
                      'method': 'GET',
                      'path': '/v3/alerts/{alert_id}',
                      'required_params': [],
                      'body_required': False,
                      'body_type': None,
                      'regions': ['us', 'eu'],
                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_alerts_v3.json'},
 'alerts_list_alert': {'name': 'alerts_list_alert',
                       'label': 'Retrieve all alerts',
                       'description': '**This endpoint allows you to retrieve all of your '
                                      'alerts.**',
                       'category': 'Alerts',
                       'family': 'alerts',
                       'method': 'GET',
                       'path': '/v3/alerts',
                       'required_params': [],
                       'body_required': False,
                       'body_type': None,
                       'regions': ['us', 'eu'],
                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_alerts_v3.json'},
 'alerts_update_alert': {'name': 'alerts_update_alert',
                         'label': 'Update an alert',
                         'description': '**This endpoint allows you to update an alert.**',
                         'category': 'Alerts',
                         'family': 'alerts',
                         'method': 'PATCH',
                         'path': '/v3/alerts/{alert_id}',
                         'required_params': [],
                         'body_required': False,
                         'body_type': 'application/json',
                         'regions': ['us', 'eu'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_alerts_v3.json'},
 'api_keys_create_api_key': {'name': 'api_keys_create_api_key',
                             'label': 'Create API keys',
                             'description': '**This endpoint allows you to create a new API Key '
                                            'for the user.** To create your initial SendGrid API '
                                            'Key, you should [use the SendGrid '
                                            'App](https://app.sendgrid.com/settings/api_keys). '
                                            'Once you have created a first key with scopes to '
                                            'manage additional API keys, you can use this API for '
                                            'all other key management. A JSON request body '
                                            'containing a `name` property is required when making '
                                            'requests to ',
                             'category': 'API Keys',
                             'family': 'api_keys',
                             'method': 'POST',
                             'path': '/v3/api_keys',
                             'required_params': [],
                             'body_required': False,
                             'body_type': 'application/json',
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_api_keys_v3.json'},
 'api_keys_delete_api_key': {'name': 'api_keys_delete_api_key',
                             'label': 'Delete API keys',
                             'description': '**This endpoint allows you to revoke an existing API '
                                            'Key using an `api_key_id`** Authentications using a '
                                            'revoked API Key will fail after after some small '
                                            'propogation delay. If the API Key ID does not exist, '
                                            'a `404` status will be returned.',
                             'category': 'API Keys',
                             'family': 'api_keys',
                             'method': 'DELETE',
                             'path': '/v3/api_keys/{api_key_id}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_api_keys_v3.json'},
 'api_keys_get_api_key': {'name': 'api_keys_get_api_key',
                          'label': 'Retrieve an existing API Key',
                          'description': '**This endpoint allows you to retrieve a single API key '
                                         'using an `api_key_id`.** The endpoint will return a '
                                         "key's name, ID, and scopes. If the API Key ID does not, "
                                         'exist a `404` status will be returned. See the [API Key '
                                         'Permissions '
                                         'List](https://docs.sendgrid.com/api-reference/how-to-use-the-sendgrid-v3-api/authorization) '
                                         "for all available scopes. An API key's scopes can be "
                                         'updated after creation ',
                          'category': 'API Keys',
                          'family': 'api_keys',
                          'method': 'GET',
                          'path': '/v3/api_keys/{api_key_id}',
                          'required_params': [],
                          'body_required': False,
                          'body_type': None,
                          'regions': ['us', 'eu'],
                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_api_keys_v3.json'},
 'api_keys_list_api_key': {'name': 'api_keys_list_api_key',
                           'label': 'Retrieve all API Keys belonging to the authenticated user',
                           'description': '**This endpoint allows you to retrieve all API Keys '
                                          'that belong to the authenticated user.** A successful '
                                          'response from this API will include all available API '
                                          "keys' names and IDs. For security reasons, there is not "
                                          "a way to retrieve the key itself after it's created. If "
                                          'you lose your API key, you must create a new one. Only '
                                          'the "Create API keys" endpoint will return a key to you '
                                          'and only at the t',
                           'category': 'API Keys',
                           'family': 'api_keys',
                           'method': 'GET',
                           'path': '/v3/api_keys',
                           'required_params': [],
                           'body_required': False,
                           'body_type': None,
                           'regions': ['us', 'eu'],
                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_api_keys_v3.json'},
 'api_keys_update_api_key': {'name': 'api_keys_update_api_key',
                             'label': 'Update API key name and scopes',
                             'description': '**This endpoint allows you to update the name and '
                                            'scopes of a given API key.** You must pass this '
                                            'endpoint a JSON request body with a `name` field and '
                                            'a `scopes` array containing at least one scope. The '
                                            '`name` and `scopes` fields will be used to update the '
                                            'key associated with the `api_key_id` in the request '
                                            "URL. If you need to update a key's scopes only, pass "
                                            "the `name` field with the key's existi",
                             'category': 'API Keys',
                             'family': 'api_keys',
                             'method': 'PUT',
                             'path': '/v3/api_keys/{api_key_id}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': 'application/json',
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_api_keys_v3.json'},
 'api_keys_update_api_key_name': {'name': 'api_keys_update_api_key_name',
                                  'label': 'Update API key name',
                                  'description': '**This endpoint allows you to update the name of '
                                                 'an existing API Key.** You must pass this '
                                                 'endpoint a JSON request body with a `name` '
                                                 'property, which will be used to rename the key '
                                                 'associated with the `api_key_id` passed in the '
                                                 'URL.',
                                  'category': 'API Keys',
                                  'family': 'api_keys',
                                  'method': 'PATCH',
                                  'path': '/v3/api_keys/{api_key_id}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': 'application/json',
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_api_keys_v3.json'},
 'domain_authentication_add_ip_to_authenticated_domain': {'name': 'domain_authentication_add_ip_to_authenticated_domain',
                                                          'label': 'Add an IP to an authenticated '
                                                                   'domain',
                                                          'description': '**This endpoint allows '
                                                                         'you to add an IP address '
                                                                         'to an authenticated '
                                                                         'domain.**',
                                                          'category': 'Domain Authentication',
                                                          'family': 'domain_authentication',
                                                          'method': 'POST',
                                                          'path': '/v3/whitelabel/domains/{id}/ips',
                                                          'required_params': [],
                                                          'body_required': False,
                                                          'body_type': 'application/json',
                                                          'regions': ['us', 'eu'],
                                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_associate_subuser_with_domain': {'name': 'domain_authentication_associate_subuser_with_domain',
                                                         'label': 'Associate an authenticated '
                                                                  'domain with a given user',
                                                         'description': '**This endpoint allows '
                                                                        'you to associate a '
                                                                        'specific authenticated '
                                                                        'domain with a subuser.** '
                                                                        'Authenticated domains can '
                                                                        'be associated with (i.e. '
                                                                        'assigned to) subusers '
                                                                        'from a parent account. '
                                                                        'This functionality allows '
                                                                        'subusers to send mail '
                                                                        "using their parent's "
                                                                        'domain. To associate an '
                                                                        'authenticated domain with '
                                                                        'a subuser, the parent '
                                                                        'account must first '
                                                                        'authenticate and validate '
                                                                        'the domain. The parent '
                                                                        'may t',
                                                         'category': 'Domain Authentication',
                                                         'family': 'domain_authentication',
                                                         'method': 'POST',
                                                         'path': '/v3/whitelabel/domains/{domain_id}/subuser',
                                                         'required_params': [],
                                                         'body_required': False,
                                                         'body_type': 'application/json',
                                                         'regions': ['us', 'eu'],
                                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_associate_subuser_with_domain_multiple': {'name': 'domain_authentication_associate_subuser_with_domain_multiple',
                                                                  'label': 'Associate an '
                                                                           'authenticated domain '
                                                                           'with a given user, for '
                                                                           'up to five domains',
                                                                  'description': '**This endpoint '
                                                                                 'allows you to '
                                                                                 'associate a '
                                                                                 'specific '
                                                                                 'authenticated '
                                                                                 'domain with a '
                                                                                 'subuser. It can '
                                                                                 'be used to '
                                                                                 'associate up to '
                                                                                 'five '
                                                                                 'authenticated '
                                                                                 'domains.** This '
                                                                                 'functionality '
                                                                                 'allows subusers '
                                                                                 'to send mail '
                                                                                 'using their '
                                                                                 "parent's domain. "
                                                                                 'Authenticated '
                                                                                 'domains can be '
                                                                                 'associated with '
                                                                                 '(i.e. assigned '
                                                                                 'to) subusers '
                                                                                 'from a parent '
                                                                                 'account. To '
                                                                                 'associate an '
                                                                                 'authenticated '
                                                                                 'domain with a '
                                                                                 'subuser, the '
                                                                                 'parent account '
                                                                                 'mus',
                                                                  'category': 'Domain '
                                                                              'Authentication',
                                                                  'family': 'domain_authentication',
                                                                  'method': 'POST',
                                                                  'path': '/v3/whitelabel/domains/{domain_id}/subuser:add',
                                                                  'required_params': [],
                                                                  'body_required': False,
                                                                  'body_type': 'application/json',
                                                                  'regions': ['us', 'eu'],
                                                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_authenticate_domain': {'name': 'domain_authentication_authenticate_domain',
                                               'label': 'Authenticate a domain',
                                               'description': '**This endpoint allows you to '
                                                              'authenticate a domain.** If you are '
                                                              'authenticating a domain for a '
                                                              'subuser, you have two options: 1. '
                                                              'Use the "username" parameter. This '
                                                              'allows you to authenticate a domain '
                                                              'on behalf of your subuser. This '
                                                              'means the subuser is able to see '
                                                              'and modify the authenticated '
                                                              'domain. 2. Use the Association '
                                                              'workflow (see Associate Domain '
                                                              'section). This allows you to '
                                                              'authenticate a',
                                               'category': 'Domain Authentication',
                                               'family': 'domain_authentication',
                                               'method': 'POST',
                                               'path': '/v3/whitelabel/domains',
                                               'required_params': [],
                                               'body_required': False,
                                               'body_type': 'application/json',
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_delete_authenticated_domain': {'name': 'domain_authentication_delete_authenticated_domain',
                                                       'label': 'Delete an authenticated domain',
                                                       'description': '**This endpoint allows you '
                                                                      'to delete an authenticated '
                                                                      'domain.**',
                                                       'category': 'Domain Authentication',
                                                       'family': 'domain_authentication',
                                                       'method': 'DELETE',
                                                       'path': '/v3/whitelabel/domains/{domain_id}',
                                                       'required_params': [],
                                                       'body_required': False,
                                                       'body_type': None,
                                                       'regions': ['us', 'eu'],
                                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_delete_ip_from_authenticated_domain': {'name': 'domain_authentication_delete_ip_from_authenticated_domain',
                                                               'label': 'Remove an IP from an '
                                                                        'authenticated domain',
                                                               'description': '**This endpoint '
                                                                              'allows you to '
                                                                              'remove an IP '
                                                                              'address from that '
                                                                              "domain's "
                                                                              'authentication.**',
                                                               'category': 'Domain Authentication',
                                                               'family': 'domain_authentication',
                                                               'method': 'DELETE',
                                                               'path': '/v3/whitelabel/domains/{id}/ips/{ip}',
                                                               'required_params': [],
                                                               'body_required': False,
                                                               'body_type': None,
                                                               'regions': ['us', 'eu'],
                                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_disassociate_authenticated_domain_from_user': {'name': 'domain_authentication_disassociate_authenticated_domain_from_user',
                                                                       'label': 'Disassociate an '
                                                                                'authenticated '
                                                                                'domain from a '
                                                                                'given user',
                                                                       'description': '**This '
                                                                                      'endpoint '
                                                                                      'allows you '
                                                                                      'to '
                                                                                      'disassociate '
                                                                                      'a specific '
                                                                                      'authenticated '
                                                                                      'domain from '
                                                                                      'a '
                                                                                      'subuser.** '
                                                                                      'Authenticated '
                                                                                      'domains can '
                                                                                      'be '
                                                                                      'associated '
                                                                                      'with (i.e. '
                                                                                      'assigned '
                                                                                      'to) '
                                                                                      'subusers '
                                                                                      'from a '
                                                                                      'parent '
                                                                                      'account. '
                                                                                      'This '
                                                                                      'functionality '
                                                                                      'allows '
                                                                                      'subusers to '
                                                                                      'send mail '
                                                                                      'using their '
                                                                                      "parent's "
                                                                                      'domain. To '
                                                                                      'associate '
                                                                                      'an '
                                                                                      'authenticated '
                                                                                      'domain with '
                                                                                      'a subuser, '
                                                                                      'the parent '
                                                                                      'account '
                                                                                      'must first '
                                                                                      'authenticate '
                                                                                      'and '
                                                                                      'validate '
                                                                                      'the domain. '
                                                                                      'The parent '
                                                                                      'ma',
                                                                       'category': 'Domain '
                                                                                   'Authentication',
                                                                       'family': 'domain_authentication',
                                                                       'method': 'DELETE',
                                                                       'path': '/v3/whitelabel/domains/subuser',
                                                                       'required_params': [],
                                                                       'body_required': False,
                                                                       'body_type': None,
                                                                       'regions': ['us', 'eu'],
                                                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_disassociate_subuser_from_domain': {'name': 'domain_authentication_disassociate_subuser_from_domain',
                                                            'label': 'Disassociate an '
                                                                     'authenticated domain from a '
                                                                     'given user for users with up '
                                                                     'to five associated domains',
                                                            'description': '**This endpoint allows '
                                                                           'you to disassociate a '
                                                                           'specific authenticated '
                                                                           'domain from a subuser, '
                                                                           'for users with up to '
                                                                           'five associated '
                                                                           'domains.** This '
                                                                           'functionality allows '
                                                                           'subusers to send mail '
                                                                           "using their parent's "
                                                                           'domain. Authenticated '
                                                                           'domains can be '
                                                                           'associated with (i.e. '
                                                                           'assigned to) subusers '
                                                                           'kknt, and a subuser '
                                                                           'can have up to five '
                                                                           'associated '
                                                                           'authenticated domains. '
                                                                           'You can dissociate an '
                                                                           'authenticated d',
                                                            'category': 'Domain Authentication',
                                                            'family': 'domain_authentication',
                                                            'method': 'DELETE',
                                                            'path': '/v3/whitelabel/domains/{domain_id}/subuser',
                                                            'required_params': [],
                                                            'body_required': False,
                                                            'body_type': None,
                                                            'regions': ['us', 'eu'],
                                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_email_dns_record': {'name': 'domain_authentication_email_dns_record',
                                            'label': 'Email DNS records to a co-worker',
                                            'description': '**This endpoint is used to share DNS '
                                                           'records with a colleagues** Use this '
                                                           'endpoint to send SendGrid-generated '
                                                           'DNS record information to a co-worker '
                                                           'so they can enter it into your DNS '
                                                           'provider to validate your domain and '
                                                           'link branding. What type of records '
                                                           'are sent will depend on whether you '
                                                           'have chosen Automated Security or not. '
                                                           'When using Automated Security, '
                                                           'SendGrid provides you with three CNAME',
                                            'category': 'Domain Authentication',
                                            'family': 'domain_authentication',
                                            'method': 'POST',
                                            'path': '/v3/whitelabel/dns/email',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': 'application/json',
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_get_authenticated_domain': {'name': 'domain_authentication_get_authenticated_domain',
                                                    'label': 'Retrieve an authenticated domain',
                                                    'description': '**This endpoint allows you to '
                                                                   'retrieve a specific '
                                                                   'authenticated domain.**',
                                                    'category': 'Domain Authentication',
                                                    'family': 'domain_authentication',
                                                    'method': 'GET',
                                                    'path': '/v3/whitelabel/domains/{domain_id}',
                                                    'required_params': [],
                                                    'body_required': False,
                                                    'body_type': None,
                                                    'regions': ['us', 'eu'],
                                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_list_all_authenticated_domain_with_user': {'name': 'domain_authentication_list_all_authenticated_domain_with_user',
                                                                   'label': 'List all the '
                                                                            'authenticated domains '
                                                                            'associated with the '
                                                                            'given user',
                                                                   'description': '**This endpoint '
                                                                                  'allows you to '
                                                                                  'retrieve all of '
                                                                                  'the '
                                                                                  'authenticated '
                                                                                  'domains that '
                                                                                  'have been '
                                                                                  'assigned to a '
                                                                                  'specific '
                                                                                  'subuser.** This '
                                                                                  'functionality '
                                                                                  'allows subusers '
                                                                                  'to send mail '
                                                                                  'using their '
                                                                                  "parent's "
                                                                                  'domain. '
                                                                                  'Authenticated '
                                                                                  'domains can be '
                                                                                  'associated with '
                                                                                  '(i.e. assigned '
                                                                                  'to) subusers '
                                                                                  'from a parent '
                                                                                  'account, and a '
                                                                                  'subuser can '
                                                                                  'have up to five '
                                                                                  'associated '
                                                                                  'domains. To '
                                                                                  'associate an '
                                                                                  'authenticated '
                                                                                  'domain with a '
                                                                                  'subuser,',
                                                                   'category': 'Domain '
                                                                               'Authentication',
                                                                   'family': 'domain_authentication',
                                                                   'method': 'GET',
                                                                   'path': '/v3/whitelabel/domains/subuser/all',
                                                                   'required_params': [{'name': 'username',
                                                                                        'in': 'query'}],
                                                                   'body_required': False,
                                                                   'body_type': None,
                                                                   'regions': ['us', 'eu'],
                                                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_list_authenticated_domain': {'name': 'domain_authentication_list_authenticated_domain',
                                                     'label': 'List all authenticated domains',
                                                     'description': '**This endpoint allows you to '
                                                                    'retrieve a paginated list of '
                                                                    'all domains you have '
                                                                    'authenticated.** You can use '
                                                                    'the `limit` query parameter '
                                                                    'to set the page size. If your '
                                                                    'list contains more items than '
                                                                    'the page size permits, you '
                                                                    'can make multiple requests. '
                                                                    'Use the `offset` query '
                                                                    'parameter to control the '
                                                                    'position in the list from '
                                                                    'which to start retrieving '
                                                                    'additional items.',
                                                     'category': 'Domain Authentication',
                                                     'family': 'domain_authentication',
                                                     'method': 'GET',
                                                     'path': '/v3/whitelabel/domains',
                                                     'required_params': [],
                                                     'body_required': False,
                                                     'body_type': None,
                                                     'regions': ['us', 'eu'],
                                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_list_authenticated_domain_with_user': {'name': 'domain_authentication_list_authenticated_domain_with_user',
                                                               'label': 'List the authenticated '
                                                                        'domain associated with '
                                                                        'the given user',
                                                               'description': '**This endpoint '
                                                                              'allows you to '
                                                                              'retrieve all of the '
                                                                              'authenticated '
                                                                              'domains that have '
                                                                              'been assigned to a '
                                                                              'specific subuser.** '
                                                                              'Authenticated '
                                                                              'domains can be '
                                                                              'associated with '
                                                                              '(i.e. assigned to) '
                                                                              'subusers from a '
                                                                              'parent account. '
                                                                              'This functionality '
                                                                              'allows subusers to '
                                                                              'send mail using '
                                                                              "their parent's "
                                                                              'domain. To '
                                                                              'associate an '
                                                                              'authenticated '
                                                                              'domain with a '
                                                                              'subuser, the parent '
                                                                              'account must first '
                                                                              'authenticate and '
                                                                              'valida',
                                                               'category': 'Domain Authentication',
                                                               'family': 'domain_authentication',
                                                               'method': 'GET',
                                                               'path': '/v3/whitelabel/domains/subuser',
                                                               'required_params': [{'name': 'username',
                                                                                    'in': 'query'}],
                                                               'body_required': False,
                                                               'body_type': None,
                                                               'regions': ['us', 'eu'],
                                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_list_default_authenticated_domain': {'name': 'domain_authentication_list_default_authenticated_domain',
                                                             'label': 'Get the default '
                                                                      'authentication',
                                                             'description': '**This endpoint '
                                                                            'allows you to '
                                                                            'retrieve the default '
                                                                            'authentication for a '
                                                                            'domain.** When '
                                                                            'creating or updating '
                                                                            'a domain '
                                                                            'authentication, you '
                                                                            'can set the domain as '
                                                                            'a default. The '
                                                                            'default domain will '
                                                                            'be used to send all '
                                                                            'mail. If you have '
                                                                            'multiple '
                                                                            'authenticated '
                                                                            'domains, the '
                                                                            'authenticated domain '
                                                                            'matching the domain '
                                                                            'of the From address '
                                                                            'will be used, and the '
                                                                            'default will be '
                                                                            'overridden. This '
                                                                            'endpoint will re',
                                                             'category': 'Domain Authentication',
                                                             'family': 'domain_authentication',
                                                             'method': 'GET',
                                                             'path': '/v3/whitelabel/domains/default',
                                                             'required_params': [],
                                                             'body_required': False,
                                                             'body_type': None,
                                                             'regions': ['us', 'eu'],
                                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_update_authenticated_domain': {'name': 'domain_authentication_update_authenticated_domain',
                                                       'label': 'Update an authenticated domain',
                                                       'description': '**This endpoint allows you '
                                                                      'to update the settings for '
                                                                      'an authenticated domain.**',
                                                       'category': 'Domain Authentication',
                                                       'family': 'domain_authentication',
                                                       'method': 'PATCH',
                                                       'path': '/v3/whitelabel/domains/{domain_id}',
                                                       'required_params': [],
                                                       'body_required': False,
                                                       'body_type': 'application/json',
                                                       'regions': ['us', 'eu'],
                                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'domain_authentication_validate_authenticated_domain': {'name': 'domain_authentication_validate_authenticated_domain',
                                                         'label': 'Validate a domain '
                                                                  'authentication',
                                                         'description': '**This endpoint allows '
                                                                        'you to validate an '
                                                                        'authenticated domain. If '
                                                                        'it fails, it will return '
                                                                        'an error message '
                                                                        'describing why the domain '
                                                                        'could not be validated.**',
                                                         'category': 'Domain Authentication',
                                                         'family': 'domain_authentication',
                                                         'method': 'POST',
                                                         'path': '/v3/whitelabel/domains/{id}/validate',
                                                         'required_params': [],
                                                         'body_required': False,
                                                         'body_type': None,
                                                         'regions': ['us', 'eu'],
                                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_domain_authentication_v3.json'},
 'email_activity_download_csv': {'name': 'email_activity_download_csv',
                                 'label': 'Download CSV',
                                 'description': '**This endpoint will return a presigned URL that '
                                                'can be used to download the CSV that was '
                                                'requested from the "Request a CSV" endpoint.**',
                                 'category': 'Email Activity',
                                 'family': 'email_activity',
                                 'method': 'GET',
                                 'path': '/v3/messages/download/{download_uuid}',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_activity_v3.json'},
 'email_activity_get_message': {'name': 'email_activity_get_message',
                                'label': 'Filter messages by message ID',
                                'description': 'Get all of the details about the specified '
                                               'message. For Regional (EU) subusers, no data will '
                                               'be generated for this service.',
                                'category': 'Email Activity',
                                'family': 'email_activity',
                                'method': 'GET',
                                'path': '/v3/messages/{msg_id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_activity_v3.json'},
 'email_activity_list_message': {'name': 'email_activity_list_message',
                                 'label': 'Filter all messages',
                                 'description': 'Filter all messages to search your Email '
                                                'Activity. All queries must be [URL '
                                                'encoded](https://meyerweb.com/eric/tools/dencoder/), '
                                                'and use the following format: '
                                                '`query={query_type}="{query_content}"` Once URL '
                                                'encoded, the previous query will look like this: '
                                                '`query=type%3D%22query_content%22` For example, '
                                                'to filter by a specific email, use the following '
                                                'query: `query=to_email%3D%22example%40example.c',
                                 'category': 'Email Activity',
                                 'family': 'email_activity',
                                 'method': 'GET',
                                 'path': '/v3/messages',
                                 'required_params': [{'name': 'query', 'in': 'query'}],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_activity_v3.json'},
 'email_activity_request_csv': {'name': 'email_activity_request_csv',
                                'label': 'Request CSV',
                                'description': 'This request will kick off a backend process to '
                                               'generate a CSV file. Once generated, the worker '
                                               'will then send an email for the user download the '
                                               'file. The link will expire in 3 days. The CSV will '
                                               'contain the events from the last 30 days, limited '
                                               'to the last 1 million events maximum. This '
                                               'endpoint will be rate limited to 1 request every '
                                               '12 hours (rate limit may change). This endpoint is '
                                               'similar to',
                                'category': 'Email Activity',
                                'family': 'email_activity',
                                'method': 'POST',
                                'path': '/v3/messages/download',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_activity_v3.json'},
 'email_validation_get_email_job_for_verification': {'name': 'email_validation_get_email_job_for_verification',
                                                     'label': 'This request returns a single Bulk '
                                                              'Email Validation Job',
                                                     'description': '**This endpoint returns a '
                                                                    'specific Bulk Email '
                                                                    'Validation Job. You can use '
                                                                    'this endpoint to check on the '
                                                                    'progress of a Job.**',
                                                     'category': 'Bulk Email Address Validation',
                                                     'family': 'email_validation',
                                                     'method': 'GET',
                                                     'path': '/v3/validations/email/jobs/{job_id}',
                                                     'required_params': [],
                                                     'body_required': False,
                                                     'body_type': None,
                                                     'regions': ['us'],
                                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_validation_v3.json'},
 'email_validation_get_validations_email_jobs': {'name': 'email_validation_get_validations_email_jobs',
                                                 'label': "This request lists all of a user's Bulk "
                                                          'Email Validation Jobs',
                                                 'description': '**This endpoint returns a list of '
                                                                "all of a user's Bulk Email "
                                                                'Validation Jobs.**',
                                                 'category': 'Bulk Email Address Validation',
                                                 'family': 'email_validation',
                                                 'method': 'GET',
                                                 'path': '/v3/validations/email/jobs',
                                                 'required_params': [],
                                                 'body_required': False,
                                                 'body_type': None,
                                                 'regions': ['us'],
                                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_validation_v3.json'},
 'email_validation_list_email_job_for_verification': {'name': 'email_validation_list_email_job_for_verification',
                                                      'label': 'Request a presigned URL and '
                                                               'headers for Bulk Email Address '
                                                               'Validation list upload',
                                                      'description': '**This endpoint returns a '
                                                                     'presigned URL and request '
                                                                     'headers. Use this '
                                                                     'information to upload a list '
                                                                     'of email addresses for '
                                                                     'verification.** Note that in '
                                                                     'a successful response the '
                                                                     '`content-type` header value '
                                                                     'matches the provided '
                                                                     '`file_type` parameter in the '
                                                                     '`PUT` request. Once you have '
                                                                     'an `upload_uri` and the '
                                                                     "`upload_headers`, you're "
                                                                     'ready to upload your email '
                                                                     'address list for '
                                                                     'verification. For the e',
                                                      'category': 'Bulk Email Address Validation',
                                                      'family': 'email_validation',
                                                      'method': 'PUT',
                                                      'path': '/v3/validations/email/jobs',
                                                      'required_params': [],
                                                      'body_required': False,
                                                      'body_type': 'application/json',
                                                      'regions': ['us'],
                                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_validation_v3.json'},
 'email_validation_validate_email': {'name': 'email_validation_validate_email',
                                     'label': 'Validate an email',
                                     'description': '**This endpoint allows you to validate an '
                                                    'email address.**',
                                     'category': 'Email Address Validation',
                                     'family': 'email_validation',
                                     'method': 'POST',
                                     'path': '/v3/validations/email',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': 'application/json',
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_email_validation_v3.json'},
 'enforced_tls_list_enforced_tls_setting': {'name': 'enforced_tls_list_enforced_tls_setting',
                                            'label': 'Retrieve current Enforced TLS settings',
                                            'description': '**This endpoint allows you to retrieve '
                                                           'your current Enforced TLS settings.** '
                                                           'The Enforced TLS settings specify '
                                                           'whether or not the recipient is '
                                                           'required to support TLS or have a '
                                                           'valid certificate. If either '
                                                           '`require_tls` or `require_valid_cert` '
                                                           'is set to `true`, the recipient must '
                                                           'support TLS 1.1 or higher or have a '
                                                           'valid certificate. If these conditions '
                                                           'are not met, Twilio SendGrid will drop '
                                                           'the m',
                                            'category': 'Enforced TLS',
                                            'family': 'enforced_tls',
                                            'method': 'GET',
                                            'path': '/v3/user/settings/enforced_tls',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': None,
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_enforced_tls_v3.json'},
 'enforced_tls_update_enforced_tls_setting': {'name': 'enforced_tls_update_enforced_tls_setting',
                                              'label': 'Update Enforced TLS settings',
                                              'description': '**This endpoint allows you to update '
                                                             'your Enforced TLS settings.** To '
                                                             'require TLS from recipients, set '
                                                             '`require_tls` to `true`. If either '
                                                             '`require_tls` or '
                                                             '`require_valid_cert` is set to '
                                                             '`true`, the recipient must support '
                                                             'TLS 1.1 or higher or have a valid '
                                                             'certificate. If these conditions are '
                                                             'not met, Twilio SendGrid will drop '
                                                             'the message and send a block event '
                                                             'with “TLS required but not '
                                                             'supported” ',
                                              'category': 'Enforced TLS',
                                              'family': 'enforced_tls',
                                              'method': 'PATCH',
                                              'path': '/v3/user/settings/enforced_tls',
                                              'required_params': [],
                                              'body_required': False,
                                              'body_type': 'application/json',
                                              'regions': ['us', 'eu'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_enforced_tls_v3.json'},
 'integrations_add_integration': {'name': 'integrations_add_integration',
                                  'label': 'CreateIntegration',
                                  'description': 'This endpoint creates an Integration for email '
                                                 'event forwarding. Each Integration has a maximum '
                                                 'number of allowed Integration instances per '
                                                 'user. For example, users can create up to 10 '
                                                 'Segment Integrations.',
                                  'category': 'External Integration Endpoints',
                                  'family': 'integrations',
                                  'method': 'POST',
                                  'path': '/v3/marketing/integrations',
                                  'required_params': [],
                                  'body_required': True,
                                  'body_type': 'application/json',
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_integrations_v3.json'},
 'integrations_delete_integration': {'name': 'integrations_delete_integration',
                                     'label': 'DeleteBulkIntegration',
                                     'description': 'This endpoint deletes Integrations.',
                                     'category': 'External Integration Endpoints',
                                     'family': 'integrations',
                                     'method': 'DELETE',
                                     'path': '/v3/marketing/integrations',
                                     'required_params': [{'name': 'ids', 'in': 'query'}],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_integrations_v3.json'},
 'integrations_find_integration_by_id': {'name': 'integrations_find_integration_by_id',
                                         'label': 'GetIntegration',
                                         'description': 'This endpoint returns the data for a '
                                                        'specific Integration.',
                                         'category': 'External Integration Endpoints',
                                         'family': 'integrations',
                                         'method': 'GET',
                                         'path': '/v3/marketing/integrations/{id}',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_integrations_v3.json'},
 'integrations_get_integrations_by_user': {'name': 'integrations_get_integrations_by_user',
                                           'label': 'ListIntegration',
                                           'description': 'This endpoint returns all the '
                                                          'Integrations for the user making this '
                                                          'call.',
                                           'category': 'External Integration Endpoints',
                                           'family': 'integrations',
                                           'method': 'GET',
                                           'path': '/v3/marketing/integrations',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': None,
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_integrations_v3.json'},
 'integrations_update_integration': {'name': 'integrations_update_integration',
                                     'label': 'UpdateIntegration',
                                     'description': 'This endpoint updates an existing '
                                                    'Integration.',
                                     'category': 'External Integration Endpoints',
                                     'family': 'integrations',
                                     'method': 'PATCH',
                                     'path': '/v3/marketing/integrations/{id}',
                                     'required_params': [],
                                     'body_required': True,
                                     'body_type': 'application/json',
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_integrations_v3.json'},
 'ip_access_management_add_ip_to_allow_list': {'name': 'ip_access_management_add_ip_to_allow_list',
                                               'label': 'Add one or more IPs to the allow list',
                                               'description': '**This endpoint allows you to add '
                                                              'one or more allowed IP addresses.** '
                                                              'To allow one or more IP addresses, '
                                                              'pass them to this endpoint in an '
                                                              'array. Once an IP address is added '
                                                              'to your allow list, it will be '
                                                              'assigned an `id` that can be used '
                                                              'to remove the address. You can '
                                                              'retrieve the ID associated with an '
                                                              'IP using the "Retrieve a list of '
                                                              'currently allowed IPs" endpoint.',
                                               'category': 'IP Access Management',
                                               'family': 'ip_access_management',
                                               'method': 'POST',
                                               'path': '/v3/access_settings/whitelist',
                                               'required_params': [],
                                               'body_required': False,
                                               'body_type': 'application/json',
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_access_management_v3.json'},
 'ip_access_management_delete_allowed_ip': {'name': 'ip_access_management_delete_allowed_ip',
                                            'label': 'Remove a specific IP from the allowed list',
                                            'description': '**This endpoint allows you to remove a '
                                                           'specific IP address from your list of '
                                                           'allowed addresses.** When removing a '
                                                           'specific IP address from your list, '
                                                           'you must include the ID in your call. '
                                                           'You can retrieve the IDs associated '
                                                           'with your allowed IP addresses using '
                                                           'the "Retrieve a list of currently '
                                                           'allowed IPs" endpoint.',
                                            'category': 'IP Access Management',
                                            'family': 'ip_access_management',
                                            'method': 'DELETE',
                                            'path': '/v3/access_settings/whitelist/{rule_id}',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': None,
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_access_management_v3.json'},
 'ip_access_management_delete_allowed_ips': {'name': 'ip_access_management_delete_allowed_ips',
                                             'label': 'Remove one or more IPs from the allow list',
                                             'description': '**This endpoint allows you to remove '
                                                            'one or more IP addresses from your '
                                                            'list of allowed addresses.** To '
                                                            'remove one or more IP addresses, pass '
                                                            'this endpoint an array containing the '
                                                            'ID(s) associated with the IP(s) you '
                                                            'intend to remove. You can retrieve '
                                                            'the IDs associated with your allowed '
                                                            'IP addresses using the "Retrieve a '
                                                            'list of currently allowed IPs" '
                                                            'endpoint. It is possible to remove '
                                                            'your own IP',
                                             'category': 'IP Access Management',
                                             'family': 'ip_access_management',
                                             'method': 'DELETE',
                                             'path': '/v3/access_settings/whitelist',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': 'application/json',
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_access_management_v3.json'},
 'ip_access_management_get_allowed_ip': {'name': 'ip_access_management_get_allowed_ip',
                                         'label': 'Retrieve a specific allowed IP',
                                         'description': '**This endpoint allows you to retreive a '
                                                        'specific IP address that has been allowed '
                                                        'to access your account.** You must '
                                                        'include the ID for the specific IP '
                                                        'address you want to retrieve in your '
                                                        'call. You can retrieve the IDs associated '
                                                        'with your allowed IP addresses using the '
                                                        '"Retrieve a list of currently allowed '
                                                        'IPs" endpoint.',
                                         'category': 'IP Access Management',
                                         'family': 'ip_access_management',
                                         'method': 'GET',
                                         'path': '/v3/access_settings/whitelist/{rule_id}',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_access_management_v3.json'},
 'ip_access_management_list_access_activity': {'name': 'ip_access_management_list_access_activity',
                                               'label': 'Retrieve all recent access attempts',
                                               'description': '**This endpoint allows you to '
                                                              'retrieve a list of all of the IP '
                                                              'addresses that recently attempted '
                                                              'to access your account either '
                                                              'through the User Interface or the '
                                                              'API.**',
                                               'category': 'IP Access Management',
                                               'family': 'ip_access_management',
                                               'method': 'GET',
                                               'path': '/v3/access_settings/activity',
                                               'required_params': [],
                                               'body_required': False,
                                               'body_type': None,
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_access_management_v3.json'},
 'ip_access_management_list_allowed_ip': {'name': 'ip_access_management_list_allowed_ip',
                                          'label': 'Retrieve a list of currently allowed IPs',
                                          'description': '**This endpoint allows you to retrieve a '
                                                         'list of IP addresses that are currently '
                                                         'allowed to access your account.** Each '
                                                         'IP address returned to you will have '
                                                         '`created_at` and `updated_at` dates. '
                                                         'Each IP will also be associated with an '
                                                         '`id` that can be used to remove the '
                                                         'address from your allow list.',
                                          'category': 'IP Access Management',
                                          'family': 'ip_access_management',
                                          'method': 'GET',
                                          'path': '/v3/access_settings/whitelist',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_access_management_v3.json'},
 'ip_address_management_add_ip': {'name': 'ip_address_management_add_ip',
                                  'label': 'Add a Twilio SendGrid IP Address',
                                  'description': 'This operation adds a Twilio SendGrid IP address '
                                                 'to your account. You can also assign up to 100 '
                                                 'Subusers to the IP address at creation.',
                                  'category': 'IP Address Management',
                                  'family': 'ip_address_management',
                                  'method': 'POST',
                                  'path': '/v3/send_ips/ips',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': 'application/json',
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_add_ips_to_ip_pool': {'name': 'ip_address_management_add_ips_to_ip_pool',
                                              'label': 'Add a Batch of IPs to an IP Pool',
                                              'description': 'This operation appends a batch of '
                                                             'IPs to an IP Pool. This operation '
                                                             'requires all IP assignments to '
                                                             'succeed. If any IP assignments fail, '
                                                             'this endpoint will return an error.',
                                              'category': 'IP Address Management',
                                              'family': 'ip_address_management',
                                              'method': 'POST',
                                              'path': '/v3/send_ips/pools/{poolid}/ips:batchAdd',
                                              'required_params': [],
                                              'body_required': False,
                                              'body_type': 'application/json',
                                              'regions': ['us', 'eu'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_add_sub_users_to_ip': {'name': 'ip_address_management_add_sub_users_to_ip',
                                               'label': 'Assign a Batch of Subusers to an IP',
                                               'description': 'This operation appends a batch of '
                                                              'Subusers to a specified IP address. '
                                                              'This endpoint requires all Subuser '
                                                              'assignments to succeed. If a '
                                                              'Subuser assignment fails, this '
                                                              'endpoint will return an error.',
                                               'category': 'IP Address Management',
                                               'family': 'ip_address_management',
                                               'method': 'POST',
                                               'path': '/v3/send_ips/ips/{ip}/subusers:batchAdd',
                                               'required_params': [],
                                               'body_required': False,
                                               'body_type': 'application/json',
                                               'regions': ['us'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_create_ip_pool': {'name': 'ip_address_management_create_ip_pool',
                                          'label': 'Create an IP Pool with a Name and IP '
                                                   'Assignments',
                                          'description': 'This operation will create a named IP '
                                                         'Pool and associate specified IP '
                                                         'addresses with the newly created Pool. '
                                                         'This operation requires all IP '
                                                         'assignments to succeed. If any IP '
                                                         'assignments fail, this endpoint will '
                                                         'return an error and the Pool will not be '
                                                         'created. Each IP Pool may have a maximum '
                                                         'of 100 assigned IP addresses.',
                                          'category': 'IP Address Management',
                                          'family': 'ip_address_management',
                                          'method': 'POST',
                                          'path': '/v3/send_ips/pools',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': 'application/json',
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_delete_ip_pool': {'name': 'ip_address_management_delete_ip_pool',
                                          'label': 'Delete IP Pool',
                                          'description': 'This operation deletes an IP Pool and '
                                                         'unassigns all IP addresses associated '
                                                         'with the Pool. IP addresses associated '
                                                         'with the deleted Pool will remain in '
                                                         'your account.',
                                          'category': 'IP Address Management',
                                          'family': 'ip_address_management',
                                          'method': 'DELETE',
                                          'path': '/v3/send_ips/pools/{poolid}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_delete_ips_from_ip_pool': {'name': 'ip_address_management_delete_ips_from_ip_pool',
                                                   'label': 'Delete a Batch of IPs from an IP Pool',
                                                   'description': 'This operation removes a batch '
                                                                  'of IPs from an IP Pool. All IPs '
                                                                  'associated with the Pool will '
                                                                  'be unassigned from the deleted '
                                                                  'Pool. However, this operation '
                                                                  'does not remove the IPs from '
                                                                  'your account.',
                                                   'category': 'IP Address Management',
                                                   'family': 'ip_address_management',
                                                   'method': 'POST',
                                                   'path': '/v3/send_ips/pools/{poolid}/ips:batchDelete',
                                                   'required_params': [],
                                                   'body_required': False,
                                                   'body_type': 'application/json',
                                                   'regions': ['us', 'eu'],
                                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_delete_sub_users_from_ip': {'name': 'ip_address_management_delete_sub_users_from_ip',
                                                    'label': 'Delete a Batch of Subusers from an '
                                                             'IP',
                                                    'description': 'This operation removes a batch '
                                                                   'of Subusers from a specified '
                                                                   'IP address.',
                                                    'category': 'IP Address Management',
                                                    'family': 'ip_address_management',
                                                    'method': 'POST',
                                                    'path': '/v3/send_ips/ips/{ip}/subusers:batchDelete',
                                                    'required_params': [],
                                                    'body_required': False,
                                                    'body_type': 'application/json',
                                                    'regions': ['us'],
                                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_get_ip': {'name': 'ip_address_management_get_ip',
                                  'label': 'Get Details for an IP Address',
                                  'description': 'This operation returns details for a specified '
                                                 'IP address. Details include whether the IP is '
                                                 'assigned to a parent account, set to warm up '
                                                 'automatically, which Pools the IP is associated '
                                                 'with, when the IP was added and modified, '
                                                 'whether the IP is leased, and whether the IP is '
                                                 'enabled. Note that this operation will not '
                                                 'return Subuser information associated with the '
                                                 'IP. To retrieve Subuser informatio',
                                  'category': 'IP Address Management',
                                  'family': 'ip_address_management',
                                  'method': 'GET',
                                  'path': '/v3/send_ips/ips/{ip}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_get_ip_pool': {'name': 'ip_address_management_get_ip_pool',
                                       'label': 'Get Details for an IP Pool',
                                       'description': 'This operation will return the details for '
                                                      "a specified IP Pool, including the Pool's "
                                                      'name, ID, a sample list of the IPs '
                                                      'associated with the Pool, and the total '
                                                      'number of IPs belonging to the Pool. A '
                                                      'maximum of 10 IPs will be returned per IP '
                                                      'Pool by default. To retrieve additional IP '
                                                      'addresses associated with a Pool, use the '
                                                      '"Get IPs Assigned to an IP Pool" operation.',
                                       'category': 'IP Address Management',
                                       'family': 'ip_address_management',
                                       'method': 'GET',
                                       'path': '/v3/send_ips/pools/{poolid}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_list_ip': {'name': 'ip_address_management_list_ip',
                                   'label': 'Get a List of all IP Addresses on your Account',
                                   'description': 'This operation returns a list of all IP '
                                                  'addresses associated with your account. A '
                                                  'sample of IP details is returned with each IP, '
                                                  'including which Pools the IP is associated '
                                                  'with, whether the IP is set to warm up '
                                                  'automatically, and when the IP was last '
                                                  'updated. ### Limitations The '
                                                  '`is_parent_assigned` parameter and `pool` '
                                                  'parameter cannot be used at the same time. By '
                                                  'definition, an IP cannot be assi',
                                   'category': 'IP Address Management',
                                   'family': 'ip_address_management',
                                   'method': 'GET',
                                   'path': '/v3/send_ips/ips',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_list_ip_assigned_to_ip_pool': {'name': 'ip_address_management_list_ip_assigned_to_ip_pool',
                                                       'label': 'Get IPs Assigned to an IP Pool',
                                                       'description': 'This operation returns the '
                                                                      'IP addresses that are '
                                                                      'assigned to the specified '
                                                                      'IP pool.',
                                                       'category': 'IP Address Management',
                                                       'family': 'ip_address_management',
                                                       'method': 'GET',
                                                       'path': '/v3/send_ips/pools/{poolid}/ips',
                                                       'required_params': [],
                                                       'body_required': False,
                                                       'body_type': None,
                                                       'regions': ['us', 'eu'],
                                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_list_ip_pool': {'name': 'ip_address_management_list_ip_pool',
                                        'label': 'GET all IP Pools that have Associated IPs',
                                        'description': 'This operation returns a list of your IP '
                                                       "Pools and a sample of each Pools' "
                                                       'associated IP addresses. A maximum of 10 '
                                                       'IPs will be returned per IP Pool by '
                                                       'default. To retrieve additional IP '
                                                       'addresses associated with a Pool, use the '
                                                       '"Get IPs Assigned to an IP Pool" '
                                                       'operation. Each user may have a maximum of '
                                                       '100 IP Pools.',
                                        'category': 'IP Address Management',
                                        'family': 'ip_address_management',
                                        'method': 'GET',
                                        'path': '/v3/send_ips/pools',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_list_sub_user_assigned_to_ip': {'name': 'ip_address_management_list_sub_user_assigned_to_ip',
                                                        'label': 'Get a List of Subusers Assigned '
                                                                 'to an IP',
                                                        'description': 'This operation returns a '
                                                                       'list of Subuser IDs that '
                                                                       'have been assigned the '
                                                                       'specified IP address. To '
                                                                       'retrieve more information '
                                                                       'about the returned '
                                                                       'Subusers, use the '
                                                                       '[Subusers '
                                                                       'API](https://docs.sendgrid.com/api-reference/subusers-api/list-all-subusers). '
                                                                       'You can use the '
                                                                       '`after_key` and `limit` '
                                                                       'query parameters to '
                                                                       'iterate through paginated '
                                                                       'results. The maximum limit '
                                                                       'is 100, meaning you may '
                                                                       'retrieve up to',
                                                        'category': 'IP Address Management',
                                                        'family': 'ip_address_management',
                                                        'method': 'GET',
                                                        'path': '/v3/send_ips/ips/{ip}/subusers',
                                                        'required_params': [],
                                                        'body_required': False,
                                                        'body_type': None,
                                                        'regions': ['us'],
                                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_update_ip': {'name': 'ip_address_management_update_ip',
                                     'label': 'Update Details for an IP Address',
                                     'description': "This operation updates an IP address's "
                                                    'settings, including whether the IP is set to '
                                                    'warm up automatically, if the IP is assigned '
                                                    'by a parent account, and whether the IP is '
                                                    'enabled or disabled. The request body must '
                                                    'include at least one of the `is_auto_warmup`, '
                                                    '`is_parent_assigned`, or `is_enabled` fields.',
                                     'category': 'IP Address Management',
                                     'family': 'ip_address_management',
                                     'method': 'PATCH',
                                     'path': '/v3/send_ips/ips/{ip}',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': 'application/json',
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_address_management_update_ip_pool': {'name': 'ip_address_management_update_ip_pool',
                                          'label': 'Update an IP Pool Name',
                                          'description': 'This operation will rename an IP Pool. '
                                                         'An IP Pool name cannot start with a '
                                                         'dot/period (.) or space.',
                                          'category': 'IP Address Management',
                                          'family': 'ip_address_management',
                                          'method': 'PUT',
                                          'path': '/v3/send_ips/pools/{poolid}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': 'application/json',
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_address_management_v3.json'},
 'ip_provisioning_add_account_ips': {'name': 'ip_provisioning_add_account_ips',
                                     'label': 'Add Account IPs',
                                     'description': 'Adds IP(s) to the specified account.',
                                     'category': 'IP Provisioning',
                                     'family': 'ip_provisioning',
                                     'method': 'POST',
                                     'path': '/v3/partners/accounts/{accountID}/ips',
                                     'required_params': [],
                                     'body_required': True,
                                     'body_type': 'application/json',
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_provisioning_v3.json'},
 'ip_provisioning_list_account_ips': {'name': 'ip_provisioning_list_account_ips',
                                      'label': 'List Account IPs',
                                      'description': 'Retrieves a paginated list of IPs associated '
                                                     'with the specified account, ordered by most '
                                                     'recently added IP.',
                                      'category': 'IP Provisioning',
                                      'family': 'ip_provisioning',
                                      'method': 'GET',
                                      'path': '/v3/partners/accounts/{accountID}/ips',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_provisioning_v3.json'},
 'ip_provisioning_remove_account_ips': {'name': 'ip_provisioning_remove_account_ips',
                                        'label': 'Remove Account IPs',
                                        'description': 'Removes IP(s) from the specified account.',
                                        'category': 'IP Provisioning',
                                        'family': 'ip_provisioning',
                                        'method': 'DELETE',
                                        'path': '/v3/partners/accounts/{accountID}/ips',
                                        'required_params': [],
                                        'body_required': True,
                                        'body_type': 'application/json',
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_provisioning_v3.json'},
 'ip_warmup_get_warm_up_ip': {'name': 'ip_warmup_get_warm_up_ip',
                              'label': 'Retrieve the warmup status for a specific IP address',
                              'description': '**This endpoint allows you to retrieve the warmup '
                                             'status for a specific IP address.** You can retrieve '
                                             'all of your warming IPs using the "Retrieve all IPs '
                                             'currently in warmup" endpoint.',
                              'category': 'IP Warmup',
                              'family': 'ip_warmup',
                              'method': 'GET',
                              'path': '/v3/ips/warmup/{ip_address}',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_warmup_v3.json'},
 'ip_warmup_list_warm_up_ip': {'name': 'ip_warmup_list_warm_up_ip',
                               'label': 'Retrieve all IPs currently in warmup',
                               'description': '**This endpoint allows you to retrieve all of your '
                                              'IP addresses that are currently warming up.**',
                               'category': 'IP Warmup',
                               'family': 'ip_warmup',
                               'method': 'GET',
                               'path': '/v3/ips/warmup',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_warmup_v3.json'},
 'ip_warmup_stop_ip_warm_up': {'name': 'ip_warmup_stop_ip_warm_up',
                               'label': 'Stop warming up an IP address',
                               'description': '**This endpoint allows you to remove an IP address '
                                              'from warmup mode.** Your request will return a 204 '
                                              'status code if the specified IP was successfully '
                                              'removed from warmup mode. To retrieve details of '
                                              'the IP’s warmup status *before* removing it from '
                                              'warmup mode, call the "Retrieve the warmpup status '
                                              'for a specific IP address" endpoint.',
                               'category': 'IP Warmup',
                               'family': 'ip_warmup',
                               'method': 'DELETE',
                               'path': '/v3/ips/warmup/{ip_address}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_warmup_v3.json'},
 'ip_warmup_warm_up_ip': {'name': 'ip_warmup_warm_up_ip',
                          'label': 'Start warming up an IP address',
                          'description': '**This endpoint allows you to put an IP address into '
                                         'warmup mode.**',
                          'category': 'IP Warmup',
                          'family': 'ip_warmup',
                          'method': 'POST',
                          'path': '/v3/ips/warmup',
                          'required_params': [],
                          'body_required': False,
                          'body_type': 'application/json',
                          'regions': ['us', 'eu'],
                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ip_warmup_v3.json'},
 'ips_add_ip': {'name': 'ips_add_ip',
                'label': 'Add IPs',
                'description': '**This endpoint is for adding a(n) IP Address(es) to your '
                               'account.**',
                'category': 'IP Addresses',
                'family': 'ips',
                'method': 'POST',
                'path': '/v3/ips',
                'required_params': [],
                'body_required': False,
                'body_type': 'application/json',
                'regions': ['us'],
                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_add_ip_to_ip_pool': {'name': 'ips_add_ip_to_ip_pool',
                           'label': 'Add an IP address to a pool',
                           'description': '**This endpoint allows you to add an IP address to an '
                                          'IP pool.** You can add the same IP address to multiple '
                                          'pools. It may take up to 60 seconds for your IP address '
                                          'to be added to a pool after your request is made. '
                                          'Before you can add an IP to a pool, you need to '
                                          'activate it in your SendGrid account: 1. Log into your '
                                          'SendGrid account. 1. Navigate to **Settings** and then '
                                          'select **IP Addresses**. 1.',
                           'category': 'IP Pools',
                           'family': 'ips',
                           'method': 'POST',
                           'path': '/v3/ips/pools/{pool_name}/ips',
                           'required_params': [],
                           'body_required': False,
                           'body_type': 'application/json',
                           'regions': ['us', 'eu'],
                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_create_ip_pool': {'name': 'ips_create_ip_pool',
                        'label': 'Create an IP pool',
                        'description': '**This endpoint allows you to create an IP pool.** Before '
                                       'you can create an IP pool, you need to activate the IP in '
                                       'your SendGrid account: 1. Log into your SendGrid account. '
                                       '1. Navigate to **Settings** and then select **IP '
                                       'Addresses**. 1. Find the IP address you want to activate '
                                       'and then click **Edit**. 1. Check **Allow my account to '
                                       'send mail using this IP address**. 1. Click **Save**.',
                        'category': 'IP Pools',
                        'family': 'ips',
                        'method': 'POST',
                        'path': '/v3/ips/pools',
                        'required_params': [],
                        'body_required': False,
                        'body_type': 'application/json',
                        'regions': ['us', 'eu'],
                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_delete_ip_from_ip_pool': {'name': 'ips_delete_ip_from_ip_pool',
                                'label': 'Remove an IP address from a pool',
                                'description': '**This endpoint allows you to remove an IP address '
                                               'from an IP pool.**',
                                'category': 'IP Pools',
                                'family': 'ips',
                                'method': 'DELETE',
                                'path': '/v3/ips/pools/{pool_name}/ips/{ip}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_delete_ip_pool': {'name': 'ips_delete_ip_pool',
                        'label': 'Delete an IP pool',
                        'description': '**This endpoint allows you to delete an IP pool.**',
                        'category': 'IP Pools',
                        'family': 'ips',
                        'method': 'DELETE',
                        'path': '/v3/ips/pools/{pool_name}',
                        'required_params': [],
                        'body_required': False,
                        'body_type': None,
                        'regions': ['us', 'eu'],
                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_get_ip': {'name': 'ips_get_ip',
                'label': 'Retrieve all IP pools an IP address belongs to',
                'description': '**This endpoint allows you to see which IP pools a particular IP '
                               'address has been added to.** The same IP address can be added to '
                               'multiple IP pools. A single IP address or a range of IP addresses '
                               'may be dedicated to an account in order to send email for multiple '
                               'domains. The reputation of this IP is based on the aggregate '
                               'performance of all the senders who use it.',
                'category': 'IP Addresses',
                'family': 'ips',
                'method': 'GET',
                'path': '/v3/ips/{ip_address}',
                'required_params': [],
                'body_required': False,
                'body_type': None,
                'regions': ['us'],
                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_get_ip_pool': {'name': 'ips_get_ip_pool',
                     'label': 'Retrieve all the IPs in a specified pool',
                     'description': '**This endpoint allows you to get all of the IP addresses '
                                    'that are in a specific IP pool.**',
                     'category': 'IP Pools',
                     'family': 'ips',
                     'method': 'GET',
                     'path': '/v3/ips/pools/{pool_name}',
                     'required_params': [],
                     'body_required': False,
                     'body_type': None,
                     'regions': ['us', 'eu'],
                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_list_assigned_ip': {'name': 'ips_list_assigned_ip',
                          'label': 'Retrieve all assigned IPs',
                          'description': '**This endpoint allows you to retrieve only assigned IP '
                                         'addresses.** A single IP address or a range of IP '
                                         'addresses may be dedicated to an account in order to '
                                         'send email for multiple domains. The reputation of this '
                                         'IP is based on the aggregate performance of all the '
                                         'senders who use it.',
                          'category': 'IP Addresses',
                          'family': 'ips',
                          'method': 'GET',
                          'path': '/v3/ips/assigned',
                          'required_params': [],
                          'body_required': False,
                          'body_type': None,
                          'regions': ['us', 'eu'],
                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_list_ip': {'name': 'ips_list_ip',
                 'label': 'Retrieve all IP addresses',
                 'description': '**This endpoint allows you to retrieve a paginated list of all '
                                'assigned and unassigned IPs.** Response includes warm up status, '
                                'pools, assigned subusers, and reverse DNS info. The start_date '
                                'field corresponds to when warmup started for that IP. A single IP '
                                'address or a range of IP addresses may be dedicated to an account '
                                'in order to send email for multiple domains. The reputation of '
                                'this IP is det',
                 'category': 'IP Addresses',
                 'family': 'ips',
                 'method': 'GET',
                 'path': '/v3/ips',
                 'required_params': [],
                 'body_required': False,
                 'body_type': None,
                 'regions': ['us', 'eu'],
                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_list_ip_pool': {'name': 'ips_list_ip_pool',
                      'label': 'Retrieve all IP pools',
                      'description': '**This endpoint allows you to get all of your IP pools.**',
                      'category': 'IP Pools',
                      'family': 'ips',
                      'method': 'GET',
                      'path': '/v3/ips/pools',
                      'required_params': [],
                      'body_required': False,
                      'body_type': None,
                      'regions': ['us', 'eu'],
                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_list_remaining_ip_count': {'name': 'ips_list_remaining_ip_count',
                                 'label': 'Get remaining IPs count',
                                 'description': '**This endpoint gets amount of IP Addresses that '
                                                'can still be created during a given period and '
                                                'the price of those IPs.**',
                                 'category': 'IP Addresses',
                                 'family': 'ips',
                                 'method': 'GET',
                                 'path': '/v3/ips/remaining',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'ips_update_ip_pool': {'name': 'ips_update_ip_pool',
                        'label': 'Rename an IP pool',
                        'description': '**This endpoint allows you to update the name of an IP '
                                       'pool.**',
                        'category': 'IP Pools',
                        'family': 'ips',
                        'method': 'PUT',
                        'path': '/v3/ips/pools/{pool_name}',
                        'required_params': [],
                        'body_required': False,
                        'body_type': 'application/json',
                        'regions': ['us', 'eu'],
                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_ips_v3.json'},
 'link_branding_associate_branded_link_with_subuser': {'name': 'link_branding_associate_branded_link_with_subuser',
                                                       'label': 'Associate a branded link with a '
                                                                'subuser',
                                                       'description': '**This endpoint allows you '
                                                                      'to associate a branded link '
                                                                      'with a subuser account.** '
                                                                      'Link branding can be '
                                                                      'associated with subusers '
                                                                      'from the parent account. '
                                                                      'This functionality allows '
                                                                      'subusers to send mail using '
                                                                      "their parent's link "
                                                                      'branding. To associate link '
                                                                      'branding, the parent '
                                                                      'account must first create a '
                                                                      'branded link and validate '
                                                                      'it. The parent may then '
                                                                      'associate that branded link '
                                                                      'with a subuser via ',
                                                       'category': 'Link Branding',
                                                       'family': 'link_branding',
                                                       'method': 'POST',
                                                       'path': '/v3/whitelabel/links/{link_id}/subuser',
                                                       'required_params': [],
                                                       'body_required': False,
                                                       'body_type': 'application/json',
                                                       'regions': ['us', 'eu'],
                                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_create_branded_link': {'name': 'link_branding_create_branded_link',
                                       'label': 'Create a branded link',
                                       'description': '**This endpoint allows you to create a new '
                                                      'branded link.** To create the link '
                                                      'branding, supply the root domain and, '
                                                      'optionally, the subdomain — these go into '
                                                      'separate fields in your request body. The '
                                                      'root domain should match your FROM email '
                                                      'address. If you provide a subdomain, it '
                                                      'must be different from the subdomain you '
                                                      'used for authenticating your domain. You '
                                                      'can submit this request as one of you',
                                       'category': 'Link Branding',
                                       'family': 'link_branding',
                                       'method': 'POST',
                                       'path': '/v3/whitelabel/links',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_delete_branded_link': {'name': 'link_branding_delete_branded_link',
                                       'label': 'Delete a branded link',
                                       'description': '**This endpoint allows you to delete a '
                                                      'branded link.** Your request will receive a '
                                                      'response with a 204 status code if the '
                                                      'deletion was successful. The call does not '
                                                      "return the link's details, so if you wish "
                                                      'to record these make sure you call the '
                                                      '"Retrieve a branded link" endpoint *before* '
                                                      'you request its deletion. You can submit '
                                                      'this request as one of your subusers if you '
                                                      'include their ID in the `',
                                       'category': 'Link Branding',
                                       'family': 'link_branding',
                                       'method': 'DELETE',
                                       'path': '/v3/whitelabel/links/{id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_disassociate_branded_link_from_subuser': {'name': 'link_branding_disassociate_branded_link_from_subuser',
                                                          'label': 'Disassociate a branded link '
                                                                   'from a subuser',
                                                          'description': '**This endpoint allows '
                                                                         'you to take a branded '
                                                                         'link away from a '
                                                                         'subuser.** Link branding '
                                                                         'can be associated with '
                                                                         'subusers from the parent '
                                                                         'account. This '
                                                                         'functionality allows '
                                                                         'subusers to send mail '
                                                                         "using their parent's "
                                                                         'link branding. To '
                                                                         'associate link branding, '
                                                                         'the parent account must '
                                                                         'first create a branded '
                                                                         'link and validate it. '
                                                                         'The parent may then '
                                                                         'associate that branded '
                                                                         'link with a subuser via '
                                                                         'the API ',
                                                          'category': 'Link Branding',
                                                          'family': 'link_branding',
                                                          'method': 'DELETE',
                                                          'path': '/v3/whitelabel/links/subuser',
                                                          'required_params': [{'name': 'username',
                                                                               'in': 'query'}],
                                                          'body_required': False,
                                                          'body_type': None,
                                                          'regions': ['us', 'eu'],
                                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_get_branded_link': {'name': 'link_branding_get_branded_link',
                                    'label': 'Retrieve a branded link',
                                    'description': '**This endpoint allows you to retrieve a '
                                                   'specific branded link by providing its ID.** '
                                                   'You can submit this request as one of your '
                                                   'subusers if you include their ID in the '
                                                   '`on-behalf-of` header in the request.',
                                    'category': 'Link Branding',
                                    'family': 'link_branding',
                                    'method': 'GET',
                                    'path': '/v3/whitelabel/links/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us', 'eu'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_list_branded_link': {'name': 'link_branding_list_branded_link',
                                     'label': 'Retrieve all branded links',
                                     'description': '**This endpoint allows you to retrieve all '
                                                    'branded links**. You can submit this request '
                                                    'as one of your subusers if you include their '
                                                    'ID in the `on-behalf-of` header in the '
                                                    'request.',
                                     'category': 'Link Branding',
                                     'family': 'link_branding',
                                     'method': 'GET',
                                     'path': '/v3/whitelabel/links',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_list_default_branded_link': {'name': 'link_branding_list_default_branded_link',
                                             'label': 'Retrieve the default branded link',
                                             'description': '**This endpoint allows you to '
                                                            'retrieve the default branded link.** '
                                                            'The default branded link is the '
                                                            'actual URL to be used when sending '
                                                            'messages. If you have more than one '
                                                            'branded link, the default is '
                                                            'determined by the following order: * '
                                                            'The validated branded link marked as '
                                                            '`default` (set when you call the '
                                                            '"Create a branded link" endpoint or '
                                                            'by calling the "Update a branded '
                                                            'link" endpoint on an exis',
                                             'category': 'Link Branding',
                                             'family': 'link_branding',
                                             'method': 'GET',
                                             'path': '/v3/whitelabel/links/default',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': None,
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_list_subuser_branded_link': {'name': 'link_branding_list_subuser_branded_link',
                                             'label': "Retrieve a subuser's branded link",
                                             'description': '**This endpoint allows you to '
                                                            'retrieve the branded link associated '
                                                            'with a subuser.** Link branding can '
                                                            'be associated with subusers from the '
                                                            'parent account. This functionality '
                                                            'allows subusers to send mail using '
                                                            "their parent's link branding. To "
                                                            'associate link branding, the parent '
                                                            'account must first create a branded '
                                                            'link and then validate it. The parent '
                                                            'may then associate that branded link '
                                                            'with a sub',
                                             'category': 'Link Branding',
                                             'family': 'link_branding',
                                             'method': 'GET',
                                             'path': '/v3/whitelabel/links/subuser',
                                             'required_params': [{'name': 'username',
                                                                  'in': 'query'}],
                                             'body_required': False,
                                             'body_type': None,
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_update_branded_link': {'name': 'link_branding_update_branded_link',
                                       'label': 'Update a branded link',
                                       'description': '**This endpoint allows you to update a '
                                                      'specific branded link. You can use this '
                                                      "endpoint to change a branded link's default "
                                                      'status.** You can submit this request as '
                                                      'one of your subusers if you include their '
                                                      'ID in the `on-behalf-of` header in the '
                                                      'request.',
                                       'category': 'Link Branding',
                                       'family': 'link_branding',
                                       'method': 'PATCH',
                                       'path': '/v3/whitelabel/links/{id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'link_branding_validate_branded_link': {'name': 'link_branding_validate_branded_link',
                                         'label': 'Validate a branded link',
                                         'description': '**This endpoint allows you to validate a '
                                                        'branded link.** You can submit this '
                                                        'request as one of your subusers if you '
                                                        'include their ID in the `on-behalf-of` '
                                                        'header in the request.',
                                         'category': 'Link Branding',
                                         'family': 'link_branding',
                                         'method': 'POST',
                                         'path': '/v3/whitelabel/links/{id}/validate',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_link_branding_v3.json'},
 'lmc_campaigns_create_campaign': {'name': 'lmc_campaigns_create_campaign',
                                   'label': 'Create a Campaign',
                                   'description': '**This endpoint allows you to create a '
                                                  'campaign.** In order to send or schedule the '
                                                  'campaign, you will be required to provide a '
                                                  'subject, sender ID, content (we suggest both '
                                                  'html and plain text), and at least one list or '
                                                  'segment ID. This information is not required '
                                                  'when you create a campaign.',
                                   'category': 'Campaigns API',
                                   'family': 'lmc_campaigns',
                                   'method': 'POST',
                                   'path': '/v3/campaigns',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_delete_campaign': {'name': 'lmc_campaigns_delete_campaign',
                                   'label': 'Delete a Campaign',
                                   'description': '**This endpoint allows you to delete a specific '
                                                  'campaign.**',
                                   'category': 'Campaigns API',
                                   'family': 'lmc_campaigns',
                                   'method': 'DELETE',
                                   'path': '/v3/campaigns/{campaign_id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_get_campaign': {'name': 'lmc_campaigns_get_campaign',
                                'label': 'Retrieve a single campaign',
                                'description': '**This endpoint allows you to retrieve a specific '
                                               'campaign.**',
                                'category': 'Campaigns API',
                                'family': 'lmc_campaigns',
                                'method': 'GET',
                                'path': '/v3/campaigns/{campaign_id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_get_scheduled_campaign': {'name': 'lmc_campaigns_get_scheduled_campaign',
                                          'label': 'View Scheduled Time of a Campaign',
                                          'description': '**This endpoint allows you to retrieve '
                                                         'the date and time that a campaign has '
                                                         'been scheduled to be sent.**',
                                          'category': 'Campaigns API',
                                          'family': 'lmc_campaigns',
                                          'method': 'GET',
                                          'path': '/v3/campaigns/{campaign_id}/schedules',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_list_campaign': {'name': 'lmc_campaigns_list_campaign',
                                 'label': 'Retrieve all Campaigns',
                                 'description': '**This endpoint allows you to retrieve a '
                                                'paginated list of all of your campaigns.** '
                                                'Returns campaigns in reverse order they were '
                                                'created (newest first). Returns an empty array if '
                                                'no campaigns exist. You can use the `limit` query '
                                                'parameter to set the page size. If your list '
                                                'contains more items than the page size permits, '
                                                'you can make multiple requests. Use the `offset` '
                                                'query parameter to control th',
                                 'category': 'Campaigns API',
                                 'family': 'lmc_campaigns',
                                 'method': 'GET',
                                 'path': '/v3/campaigns',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_schedule_campaign': {'name': 'lmc_campaigns_schedule_campaign',
                                     'label': 'Schedule a Campaign',
                                     'description': '**This endpoint allows you to schedule a '
                                                    'specific date and time for your campaign to '
                                                    "be sent.** If you have the flexibility, it's "
                                                    'better to schedule mail for off-peak times. '
                                                    'Most emails are scheduled and sent at the top '
                                                    'of the hour or half hour. Scheduling email to '
                                                    'avoid those times (for example, scheduling at '
                                                    '10:53) can result in lower deferral rates '
                                                    "because it won't be going through our "
                                                    'servers ',
                                     'category': 'Campaigns API',
                                     'family': 'lmc_campaigns',
                                     'method': 'POST',
                                     'path': '/v3/campaigns/{campaign_id}/schedules',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': 'application/json',
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_send_campaign': {'name': 'lmc_campaigns_send_campaign',
                                 'label': 'Send a Campaign',
                                 'description': '**This endpoint allows you to immediately send an '
                                                'existing campaign.** Normally a POST request '
                                                'would have a body, but since this endpoint is '
                                                'telling us to send a resource that is already '
                                                'created, a request body is not needed.',
                                 'category': 'Campaigns API',
                                 'family': 'lmc_campaigns',
                                 'method': 'POST',
                                 'path': '/v3/campaigns/{campaign_id}/schedules/now',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_send_test_campaign': {'name': 'lmc_campaigns_send_test_campaign',
                                      'label': 'Send a Test Campaign',
                                      'description': '**This endpoint allows you to send a test '
                                                     'campaign.** To send to multiple addresses, '
                                                     'use an array for the JSON "to" value '
                                                     '["one@address","two@address"]',
                                      'category': 'Campaigns API',
                                      'family': 'lmc_campaigns',
                                      'method': 'POST',
                                      'path': '/v3/campaigns/{campaign_id}/schedules/test',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': 'application/json',
                                      'regions': ['us'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_un_schedule_campaign': {'name': 'lmc_campaigns_un_schedule_campaign',
                                        'label': 'Unschedule a Scheduled Campaign',
                                        'description': '**This endpoint allows you to unschedule a '
                                                       'campaign that has already been scheduled '
                                                       'to be sent.** A successful unschedule will '
                                                       'return a 204. If the specified campaign is '
                                                       'in the process of being sent, the only '
                                                       'option is to cancel (a different method).',
                                        'category': 'Campaigns API',
                                        'family': 'lmc_campaigns',
                                        'method': 'DELETE',
                                        'path': '/v3/campaigns/{campaign_id}/schedules',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_update_campaign': {'name': 'lmc_campaigns_update_campaign',
                                   'label': 'Update a Campaign',
                                   'description': '**This endpoint allows you to update a specific '
                                                  'campaign.** This is especially useful if you '
                                                  'only set up the campaign using POST /campaigns, '
                                                  "but didn't set many of the parameters.",
                                   'category': 'Campaigns API',
                                   'family': 'lmc_campaigns',
                                   'method': 'PATCH',
                                   'path': '/v3/campaigns/{campaign_id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_campaigns_update_scheduled_campaign': {'name': 'lmc_campaigns_update_scheduled_campaign',
                                             'label': 'Update a Scheduled Campaign',
                                             'description': '**This endpoint allows to you change '
                                                            'the scheduled time and date for a '
                                                            'campaign to be sent.**',
                                             'category': 'Campaigns API',
                                             'family': 'lmc_campaigns',
                                             'method': 'PATCH',
                                             'path': '/v3/campaigns/{campaign_id}/schedules',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': 'application/json',
                                             'regions': ['us'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_campaigns_v3.json'},
 'lmc_contactdb_add_recipient': {'name': 'lmc_contactdb_add_recipient',
                                 'label': 'Add recipients',
                                 'description': '**This endpoint allows you to add a Marketing '
                                                'Campaigns recipient.** You can add custom field '
                                                'data as a parameter on this endpoint. We have '
                                                'provided an example using some of the default '
                                                'custom fields SendGrid provides. The rate limit '
                                                'is three requests every 2 seconds. You can upload '
                                                '1000 contacts per request. So the maximum upload '
                                                'rate is 1500 recipients per second.',
                                 'category': 'Recipients',
                                 'family': 'lmc_contactdb',
                                 'method': 'POST',
                                 'path': '/v3/contactdb/recipients',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': 'application/json',
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_add_recipient_to_contact_db_list': {'name': 'lmc_contactdb_add_recipient_to_contact_db_list',
                                                    'label': 'Add a Single Recipient to a List',
                                                    'description': '**This endpoint allows you to '
                                                                   'add a single recipient to a '
                                                                   'list.**',
                                                    'category': 'Lists',
                                                    'family': 'lmc_contactdb',
                                                    'method': 'POST',
                                                    'path': '/v3/contactdb/lists/{list_id}/recipients/{recipient_id}',
                                                    'required_params': [],
                                                    'body_required': False,
                                                    'body_type': None,
                                                    'regions': ['us'],
                                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_add_recipients_to_contact_db_list': {'name': 'lmc_contactdb_add_recipients_to_contact_db_list',
                                                     'label': 'Add Multiple Recipients to a List',
                                                     'description': '**This endpoint allows you to '
                                                                    'add multiple recipients to a '
                                                                    'list.** Adds existing '
                                                                    'recipients to a list, passing '
                                                                    'in the recipient IDs to add. '
                                                                    'Recipient IDs (base64-encoded '
                                                                    'email addresses) should be '
                                                                    'passed exactly as they are '
                                                                    'returned from recipient '
                                                                    'endpoints.',
                                                     'category': 'Lists',
                                                     'family': 'lmc_contactdb',
                                                     'method': 'POST',
                                                     'path': '/v3/contactdb/lists/{list_id}/recipients',
                                                     'required_params': [],
                                                     'body_required': False,
                                                     'body_type': 'application/json',
                                                     'regions': ['us'],
                                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_create_contact_db_list': {'name': 'lmc_contactdb_create_contact_db_list',
                                          'label': 'Create a List',
                                          'description': '**This endpoint allows you to create a '
                                                         'list for your recipients.**',
                                          'category': 'Lists',
                                          'family': 'lmc_contactdb',
                                          'method': 'POST',
                                          'path': '/v3/contactdb/lists',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': 'application/json',
                                          'regions': ['us'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_create_custom_field': {'name': 'lmc_contactdb_create_custom_field',
                                       'label': 'Create a Custom Field',
                                       'description': '**This endpoint allows you to create a '
                                                      'custom field.** **You can create up to 120 '
                                                      'custom fields.**',
                                       'category': 'Custom Fields',
                                       'family': 'lmc_contactdb',
                                       'method': 'POST',
                                       'path': '/v3/contactdb/custom_fields',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_create_segment': {'name': 'lmc_contactdb_create_segment',
                                  'label': 'Create a Segment',
                                  'description': '**This endpoint allows you to create a new '
                                                 'segment.** Valid operators for create and update '
                                                 'depend on the type of the field for which you '
                                                 'are searching. **Dates** - "eq", "ne", "lt" '
                                                 '(before), "gt" (after) - You may use MM/DD/YYYY '
                                                 'for day granularity or an epoch for second '
                                                 'granularity. - "empty", "not_empty" - "is '
                                                 'within" - You may use an [ISO 8601 date '
                                                 'format](https://en.wikipedia.org/wiki/ISO_860',
                                  'category': 'Segments',
                                  'family': 'lmc_contactdb',
                                  'method': 'POST',
                                  'path': '/v3/contactdb/segments',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': 'application/json',
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_contact_db_list': {'name': 'lmc_contactdb_delete_contact_db_list',
                                          'label': 'Delete a List',
                                          'description': '**This endpoint allows you to delete a '
                                                         'specific recipient list with the given '
                                                         'ID.**',
                                          'category': 'Lists',
                                          'family': 'lmc_contactdb',
                                          'method': 'DELETE',
                                          'path': '/v3/contactdb/lists/{list_id}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_contact_db_lists': {'name': 'lmc_contactdb_delete_contact_db_lists',
                                           'label': 'Delete Multiple lists',
                                           'description': '**This endpoint allows you to delete '
                                                          'multiple recipient lists.**',
                                           'category': 'Lists',
                                           'family': 'lmc_contactdb',
                                           'method': 'DELETE',
                                           'path': '/v3/contactdb/lists',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': 'application/json',
                                           'regions': ['us'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_custom_field': {'name': 'lmc_contactdb_delete_custom_field',
                                       'label': 'Delete a Custom Field',
                                       'description': '**This endpoint allows you to delete a '
                                                      'custom field by ID.**',
                                       'category': 'Custom Fields',
                                       'family': 'lmc_contactdb',
                                       'method': 'DELETE',
                                       'path': '/v3/contactdb/custom_fields/{custom_field_id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_recipient': {'name': 'lmc_contactdb_delete_recipient',
                                    'label': 'Delete a Recipient',
                                    'description': '**This endpoint allows you to delete a single '
                                                   'recipient with the given ID from your contact '
                                                   'database.** > Use this to permanently delete '
                                                   'your recipients from all of your contact lists '
                                                   'and all segments if required by applicable '
                                                   'law.',
                                    'category': 'Recipients',
                                    'family': 'lmc_contactdb',
                                    'method': 'DELETE',
                                    'path': '/v3/contactdb/recipients/{recipient_id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_recipient_from_contact_db_list': {'name': 'lmc_contactdb_delete_recipient_from_contact_db_list',
                                                         'label': 'Delete a Single Recipient from '
                                                                  'a Single List',
                                                         'description': '**This endpoint allows '
                                                                        'you to delete a single '
                                                                        'recipient from a list.**',
                                                         'category': 'Lists',
                                                         'family': 'lmc_contactdb',
                                                         'method': 'DELETE',
                                                         'path': '/v3/contactdb/lists/{list_id}/recipients/{recipient_id}',
                                                         'required_params': [],
                                                         'body_required': False,
                                                         'body_type': None,
                                                         'regions': ['us'],
                                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_recipients': {'name': 'lmc_contactdb_delete_recipients',
                                     'label': 'Delete Recipients',
                                     'description': '**This endpoint allows you to deletes one or '
                                                    'more recipients.** The body of an API call to '
                                                    'this endpoint must include an array of '
                                                    'recipient IDs of the recipients you want to '
                                                    'delete.',
                                     'category': 'Recipients',
                                     'family': 'lmc_contactdb',
                                     'method': 'DELETE',
                                     'path': '/v3/contactdb/recipients',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': 'application/json',
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_delete_segment': {'name': 'lmc_contactdb_delete_segment',
                                  'label': 'Delete a segment',
                                  'description': '**This endpoint allows you to delete a segment '
                                                 'from your recipients database.** You also have '
                                                 'the option to delete all the contacts from your '
                                                 'Marketing Campaigns recipient database who were '
                                                 'in this segment.',
                                  'category': 'Segments',
                                  'family': 'lmc_contactdb',
                                  'method': 'DELETE',
                                  'path': '/v3/contactdb/segments/{segment_id}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_export_recipient': {'name': 'lmc_contactdb_export_recipient',
                                    'label': 'Export Recipients',
                                    'description': '**Use this endpoint to export lists or '
                                                   'segments of recipients**. If you would just '
                                                   'like to have a link to the exported list sent '
                                                   'to your email set the `notifications.email` '
                                                   'option to `true` in the `POST` payload. If you '
                                                   'would like to download the list, take the `id` '
                                                   'that is returned and use the "Export '
                                                   'Recipients Status" endpoint to get the `urls`. '
                                                   'Once you have the list of URLs, make a `GET` '
                                                   'requ',
                                    'category': 'Recipients',
                                    'family': 'lmc_contactdb',
                                    'method': 'POST',
                                    'path': '/v3/contactdb/exports',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_billable': {'name': 'lmc_contactdb_get_billable',
                                'label': 'Retrieve the count of billable recipients',
                                'description': '**This endpoint allows you to retrieve the number '
                                               'of Marketing Campaigns recipients that you will be '
                                               'billed for.** You are billed for marketing '
                                               'campaigns based on the highest number of '
                                               'recipients you have had in your account at one '
                                               'time. This endpoint will allow you to know the '
                                               'current billable count value.',
                                'category': 'Recipients',
                                'family': 'lmc_contactdb',
                                'method': 'GET',
                                'path': '/v3/contactdb/recipients/billable_count',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_contact_db_list': {'name': 'lmc_contactdb_get_contact_db_list',
                                       'label': 'Retrieve a single list',
                                       'description': '**This endpoint allows you to retrieve a '
                                                      'single recipient list.**',
                                       'category': 'Lists',
                                       'family': 'lmc_contactdb',
                                       'method': 'GET',
                                       'path': '/v3/contactdb/lists/{list_id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_custom_field': {'name': 'lmc_contactdb_get_custom_field',
                                    'label': 'Retrieve a Custom Field',
                                    'description': '**This endpoint allows you to retrieve a '
                                                   'custom field by ID.**',
                                    'category': 'Custom Fields',
                                    'family': 'lmc_contactdb',
                                    'method': 'GET',
                                    'path': '/v3/contactdb/custom_fields/{custom_field_id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_export_recipient': {'name': 'lmc_contactdb_get_export_recipient',
                                        'label': 'Export Recipients Status',
                                        'description': '**This endpoint can be used to check the '
                                                       'status of a recipient export job**. To use '
                                                       'this call, you will need the `id` from the '
                                                       '"Export Recipients" call. If you would '
                                                       'like to download a list, take the `id` '
                                                       'that is returned from the "Export '
                                                       'Recipients" endpoint and make an API '
                                                       'request here to get the `urls`. Once you '
                                                       'have the list of URLs, make a `GET` '
                                                       'request on each URL to download your CSV '
                                                       'file(s',
                                        'category': 'Recipients',
                                        'family': 'lmc_contactdb',
                                        'method': 'GET',
                                        'path': '/v3/contactdb/exports/{id}',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_recipient': {'name': 'lmc_contactdb_get_recipient',
                                 'label': 'Retrieve a single recipient',
                                 'description': '**This endpoint allows you to retrieve a single '
                                                'recipient by ID from your contact database.**',
                                 'category': 'Recipients',
                                 'family': 'lmc_contactdb',
                                 'method': 'GET',
                                 'path': '/v3/contactdb/recipients/{recipient_id}',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_recipient_list': {'name': 'lmc_contactdb_get_recipient_list',
                                      'label': 'Retrieve the lists that a recipient is on',
                                      'description': '**This endpoint allows you to retrieve the '
                                                     'lists that a given recipient belongs to.** '
                                                     'Each recipient can be on many lists. This '
                                                     'endpoint gives you all of the lists that any '
                                                     'one recipient has been added to.',
                                      'category': 'Recipients',
                                      'family': 'lmc_contactdb',
                                      'method': 'GET',
                                      'path': '/v3/contactdb/recipients/{recipient_id}/lists',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_get_segment': {'name': 'lmc_contactdb_get_segment',
                               'label': 'Retrieve a segment',
                               'description': '**This endpoint allows you to retrieve a single '
                                              'segment with the given ID.**',
                               'category': 'Segments',
                               'family': 'lmc_contactdb',
                               'method': 'GET',
                               'path': '/v3/contactdb/segments/{segment_id}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_contact_db_list': {'name': 'lmc_contactdb_list_contact_db_list',
                                        'label': 'Retrieve all lists',
                                        'description': '**This endpoint allows you to retrieve all '
                                                       "of your recipient lists. If you don't have "
                                                       'any lists, an empty array will be '
                                                       'returned.**',
                                        'category': 'Lists',
                                        'family': 'lmc_contactdb',
                                        'method': 'GET',
                                        'path': '/v3/contactdb/lists',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_custom_field': {'name': 'lmc_contactdb_list_custom_field',
                                     'label': 'Retrieve all custom fields',
                                     'description': '**This endpoint allows you to retrieve all '
                                                    'custom fields.**',
                                     'category': 'Custom Fields',
                                     'family': 'lmc_contactdb',
                                     'method': 'GET',
                                     'path': '/v3/contactdb/custom_fields',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_export_recipient': {'name': 'lmc_contactdb_list_export_recipient',
                                         'label': 'Get All Existing Exports',
                                         'description': '**Use this endpoint to retrieve details '
                                                        'of all current exported jobs**. It will '
                                                        'return an array of objects, each of which '
                                                        'records an export job in flight or '
                                                        "recently completed. Each object's "
                                                        '`export_type` field will tell you which '
                                                        'kind of export it is and its `status` '
                                                        'field will indicate what stage of '
                                                        'processing it has reached. Exports which '
                                                        'are `ready` will be accompanied by a '
                                                        '`urls` field which ',
                                         'category': 'Recipients',
                                         'family': 'lmc_contactdb',
                                         'method': 'GET',
                                         'path': '/v3/contactdb/exports',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_recipient': {'name': 'lmc_contactdb_list_recipient',
                                  'label': 'Retrieve recipients',
                                  'description': '**This endpoint allows you to retrieve all of '
                                                 'your Marketing Campaigns recipients.** Batch '
                                                 'deletion of a page makes it possible to receive '
                                                 'an empty page of recipients before reaching the '
                                                 'end of the list of recipients. To avoid this '
                                                 'issue; iterate over pages until a 404 is '
                                                 'retrieved.',
                                  'category': 'Recipients',
                                  'family': 'lmc_contactdb',
                                  'method': 'GET',
                                  'path': '/v3/contactdb/recipients',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_recipient_count': {'name': 'lmc_contactdb_list_recipient_count',
                                        'label': 'Retrieve a Count of Recipients',
                                        'description': '**This endpoint allows you to retrieve the '
                                                       'total number of Marketing Campaigns '
                                                       'recipients.**',
                                        'category': 'Recipients',
                                        'family': 'lmc_contactdb',
                                        'method': 'GET',
                                        'path': '/v3/contactdb/recipients/count',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_recipient_for_segment': {'name': 'lmc_contactdb_list_recipient_for_segment',
                                              'label': 'Retrieve recipients on a segment',
                                              'description': '**This endpoint allows you to '
                                                             'retrieve all of the recipients in a '
                                                             'segment with the given ID.**',
                                              'category': 'Segments',
                                              'family': 'lmc_contactdb',
                                              'method': 'GET',
                                              'path': '/v3/contactdb/segments/{segment_id}/recipients',
                                              'required_params': [],
                                              'body_required': False,
                                              'body_type': None,
                                              'regions': ['us'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_recipients_from_contact_db_list': {'name': 'lmc_contactdb_list_recipients_from_contact_db_list',
                                                        'label': 'Retrieve all recipients on a '
                                                                 'List',
                                                        'description': '**This endpoint allows you '
                                                                       'to retrieve all recipients '
                                                                       'on the list with the given '
                                                                       'ID.**',
                                                        'category': 'Lists',
                                                        'family': 'lmc_contactdb',
                                                        'method': 'GET',
                                                        'path': '/v3/contactdb/lists/{list_id}/recipients',
                                                        'required_params': [],
                                                        'body_required': False,
                                                        'body_type': None,
                                                        'regions': ['us'],
                                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_reserved_field': {'name': 'lmc_contactdb_list_reserved_field',
                                       'label': 'Retrieve reserved fields',
                                       'description': '**This endpoint allows you to list all '
                                                      "fields that are reserved and can't be used "
                                                      'for custom field names.**',
                                       'category': 'Custom Fields',
                                       'family': 'lmc_contactdb',
                                       'method': 'GET',
                                       'path': '/v3/contactdb/reserved_fields',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_search_recipient': {'name': 'lmc_contactdb_list_search_recipient',
                                         'label': 'Search recipients',
                                         'description': '**This endpoint allows you to perform a '
                                                        'search on all of your Marketing Campaigns '
                                                        'recipients.** field_name: * is a variable '
                                                        'that is substituted for your actual '
                                                        'custom field name from your recipient. * '
                                                        'Text fields must be url-encoded. Date '
                                                        'fields are searchable only by unix '
                                                        'timestamp (e.g. 2/2/2015 becomes '
                                                        '1422835200) * If field_name is a '
                                                        "'reserved' date field, such as created_at "
                                                        'or updated_at, the',
                                         'category': 'Recipients',
                                         'family': 'lmc_contactdb',
                                         'method': 'GET',
                                         'path': '/v3/contactdb/recipients/search',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_segment': {'name': 'lmc_contactdb_list_segment',
                                'label': 'Retrieve all segments',
                                'description': '**This endpoint allows you to retrieve all of your '
                                               'segments.**',
                                'category': 'Segments',
                                'family': 'lmc_contactdb',
                                'method': 'GET',
                                'path': '/v3/contactdb/segments',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_list_status': {'name': 'lmc_contactdb_list_status',
                               'label': 'Get Recipient Upload Status',
                               'description': '**This endpoint allows you to check the upload '
                                              'status of a Marketing Campaigns recipient.**',
                               'category': 'Recipients',
                               'family': 'lmc_contactdb',
                               'method': 'GET',
                               'path': '/v3/contactdb/status',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_search_recipient': {'name': 'lmc_contactdb_search_recipient',
                                    'label': 'Search recipients',
                                    'description': 'Search using segment conditions without '
                                                   'actually creating a segment. Body contains a '
                                                   'JSON object with `conditions`, a list of '
                                                   'conditions as described below, and an optional '
                                                   '`list_id`, which is a valid list ID for a list '
                                                   'to limit the search on. Valid operators for '
                                                   'create and update depend on the type of the '
                                                   'field for which you are searching. - Dates: - '
                                                   '`"eq"`, `"ne"`, `"lt"` (before), `"gt"` (after',
                                    'category': 'Recipients',
                                    'family': 'lmc_contactdb',
                                    'method': 'POST',
                                    'path': '/v3/contactdb/recipients/search',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_update_contact_db_list': {'name': 'lmc_contactdb_update_contact_db_list',
                                          'label': 'Update a List',
                                          'description': '**This endpoint allows you to update the '
                                                         'name of one of your recipient lists.**',
                                          'category': 'Lists',
                                          'family': 'lmc_contactdb',
                                          'method': 'PATCH',
                                          'path': '/v3/contactdb/lists/{list_id}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': 'application/json',
                                          'regions': ['us'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_update_recipient': {'name': 'lmc_contactdb_update_recipient',
                                    'label': 'Update Recipient',
                                    'description': '**This endpoint allows you to update one or '
                                                   'more recipients.** The body of an API call to '
                                                   'this endpoint must include an array of one or '
                                                   'more recipient objects. It is of note that you '
                                                   'can add custom field data as parameters on '
                                                   'recipient objects. We have provided an example '
                                                   'using some of the default custom fields '
                                                   'SendGrid provides.',
                                    'category': 'Recipients',
                                    'family': 'lmc_contactdb',
                                    'method': 'PATCH',
                                    'path': '/v3/contactdb/recipients',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_contactdb_update_segment': {'name': 'lmc_contactdb_update_segment',
                                  'label': 'Update a segment',
                                  'description': '**This endpoint allows you to update a '
                                                 'segment.**',
                                  'category': 'Segments',
                                  'family': 'lmc_contactdb',
                                  'method': 'PATCH',
                                  'path': '/v3/contactdb/segments/{segment_id}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': 'application/json',
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_contactdb_v3.json'},
 'lmc_senders_create_sender': {'name': 'lmc_senders_create_sender',
                               'label': 'Create a Sender Identity',
                               'description': '**This endpoint allows you to create a new sender '
                                              'identity.** You may create up to 100 unique sender '
                                              'identities.',
                               'category': 'Sender Identities',
                               'family': 'lmc_senders',
                               'method': 'POST',
                               'path': '/v3/senders',
                               'required_params': [],
                               'body_required': False,
                               'body_type': 'application/json',
                               'regions': ['us'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_senders_v3.json'},
 'lmc_senders_delete_sender': {'name': 'lmc_senders_delete_sender',
                               'label': 'Delete a Sender Identity',
                               'description': '**This endpoint allows you to delete one of your '
                                              'sender identities.**',
                               'category': 'Sender Identities',
                               'family': 'lmc_senders',
                               'method': 'DELETE',
                               'path': '/v3/senders/{sender_id}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_senders_v3.json'},
 'lmc_senders_get_sender': {'name': 'lmc_senders_get_sender',
                            'label': 'View a Sender Identity',
                            'description': '**This endpoint allows you to retrieve a specific '
                                           'sender identity.**',
                            'category': 'Sender Identities',
                            'family': 'lmc_senders',
                            'method': 'GET',
                            'path': '/v3/senders/{sender_id}',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_senders_v3.json'},
 'lmc_senders_list_sender': {'name': 'lmc_senders_list_sender',
                             'label': 'Get all Sender Identities',
                             'description': '**This endpoint allows you to retrieve a list of all '
                                            'sender identities that have been created for your '
                                            'account.**',
                             'category': 'Sender Identities',
                             'family': 'lmc_senders',
                             'method': 'GET',
                             'path': '/v3/senders',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_senders_v3.json'},
 'lmc_senders_reset_sender_verification': {'name': 'lmc_senders_reset_sender_verification',
                                           'label': 'Resend Sender Identity Verification',
                                           'description': '**This endpoint allows you to resend a '
                                                          'sender identity verification email.**',
                                           'category': 'Sender Identities',
                                           'family': 'lmc_senders',
                                           'method': 'POST',
                                           'path': '/v3/senders/{sender_id}/resend_verification',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': None,
                                           'regions': ['us'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_senders_v3.json'},
 'lmc_senders_update_sender': {'name': 'lmc_senders_update_sender',
                               'label': 'Update a Sender Identity',
                               'description': '**This endpoint allows you to update a sender '
                                              'identity.** Updates to `from.email` require '
                                              're-verification. Partial updates are allowed, but '
                                              'fields that are marked as "required" in the POST '
                                              '(create) endpoint must not be nil if that field is '
                                              'included in the PATCH request.',
                               'category': 'Sender Identities',
                               'family': 'lmc_senders',
                               'method': 'PATCH',
                               'path': '/v3/senders/{sender_id}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': 'application/json',
                               'regions': ['us'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_lmc_senders_v3.json'},
 'logs_get_message_by_id': {'name': 'logs_get_message_by_id',
                            'label': 'Get all details for the specified message ID',
                            'description': 'Get all of the details about the specified message.',
                            'category': 'Email Logs',
                            'family': 'logs',
                            'method': 'GET',
                            'path': '/v3/logs/{sg_message_id}',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_logs_v3.json'},
 'logs_list_messages_by_filter': {'name': 'logs_list_messages_by_filter',
                                  'label': 'Search all messages using the provided query filters',
                                  'description': 'List recent messages within Email Logs, or '
                                                 'search for messages using a filter.',
                                  'category': 'Email Logs',
                                  'family': 'logs',
                                  'method': 'POST',
                                  'path': '/v3/logs',
                                  'required_params': [],
                                  'body_required': True,
                                  'body_type': 'application/json',
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_logs_v3.json'},
 'mail_create_mail_batch': {'name': 'mail_create_mail_batch',
                            'label': 'Create a batch ID',
                            'description': '**This operation allows you to generate a new mail '
                                           'batch ID.** Once a batch ID is created, you can '
                                           'associate it with a mail send by passing it in the '
                                           'request body of the [Mail Send '
                                           'operation](https://docs.sendgrid.com/api-reference/mail-send/mail-send). '
                                           'This makes it possible to group multiple requests to '
                                           'the Mail Send operation by assigning them the same '
                                           "batch ID. A batch ID that's associated wit",
                            'category': 'Mail Batch',
                            'family': 'mail',
                            'method': 'POST',
                            'path': '/v3/mail/batch',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_v3.json'},
 'mail_get_mail_batch': {'name': 'mail_get_mail_batch',
                         'label': 'Validate a batch ID',
                         'description': '**This operation allows you to validate a mail batch '
                                        'ID.** If you provide a valid batch ID, this operation '
                                        'will return a `200` status code and the batch ID itself. '
                                        'If you provide an invalid batch ID, you will receive a '
                                        '`400` level status code and an error message. A batch ID '
                                        'does not need to be assigned to a send to be considered '
                                        'valid. A successful response means only that the batch ID '
                                        'has been c',
                         'category': 'Mail Batch',
                         'family': 'mail',
                         'method': 'GET',
                         'path': '/v3/mail/batch/{batch_id}',
                         'required_params': [],
                         'body_required': False,
                         'body_type': None,
                         'regions': ['us', 'eu'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_v3.json'},
 'mail_settings_list_address_whitelist': {'name': 'mail_settings_list_address_whitelist',
                                          'label': 'Retrieve address whitelist mail settings',
                                          'description': '**This endpoint allows you to retrieve '
                                                         'your current email address whitelist '
                                                         'settings.** The Address Whitelist '
                                                         'setting allows you to specify email '
                                                         'addresses or domains for which mail '
                                                         'should never be suppressed. For Regional '
                                                         'Subusers - Utilizing this feature for '
                                                         'Regional (EU) subusers will cause '
                                                         'customer personal information to be '
                                                         'stored outside of the EU. For example, '
                                                         'if you own the domain `example',
                                          'category': 'Mail Settings',
                                          'family': 'mail_settings',
                                          'method': 'GET',
                                          'path': '/v3/mail_settings/address_whitelist',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_list_bounce_purge': {'name': 'mail_settings_list_bounce_purge',
                                     'label': 'Retrieve Bounce Purge Mail Settings',
                                     'description': '**This endpoint allows you to retrieve your '
                                                    'current Bounce Purge mail settings.** The '
                                                    'Bounce Purge mail setting allows you to '
                                                    'configure the maximum age of contacts in your '
                                                    'hard and soft bounce suppressions lists. All '
                                                    'contacts older than their respective '
                                                    'configured age are deleted. A hard bounce '
                                                    'occurs when an email message has been '
                                                    'returned to the sender because the '
                                                    "recipient's address is invalid.",
                                     'category': 'Mail Settings',
                                     'family': 'mail_settings',
                                     'method': 'GET',
                                     'path': '/v3/mail_settings/bounce_purge',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_list_footer': {'name': 'mail_settings_list_footer',
                               'label': 'Retrieve footer mail settings',
                               'description': '**This endpoint allows you to retrieve your current '
                                              'Footer mail settings.** The Footer setting will '
                                              'insert a custom footer at the bottom of your text '
                                              'and HTML email message bodies. You can insert your '
                                              'HTML or plain text directly using the "Update '
                                              'footer mail settings" endpoint, or you can create '
                                              'the footer using the [Mail Settings menu in the '
                                              'Twilio SendGrid '
                                              'App](https://app.sendgrid.com/settings/',
                               'category': 'Mail Settings',
                               'family': 'mail_settings',
                               'method': 'GET',
                               'path': '/v3/mail_settings/footer',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_list_forward_bounce': {'name': 'mail_settings_list_forward_bounce',
                                       'label': 'Retrieve forward bounce mail settings',
                                       'description': '**This endpoint allows you to retrieve your '
                                                      'current bounce forwarding mail settings.** '
                                                      'Enabling the Forward Bounce setting allows '
                                                      'you to specify `email` addresses to which '
                                                      'bounce reports will be forwarded. This '
                                                      'endpoint returns the email address you have '
                                                      'set to receive forwarded bounces and an '
                                                      '`enabled` status indicating if the setting '
                                                      'is active.',
                                       'category': 'Mail Settings',
                                       'family': 'mail_settings',
                                       'method': 'GET',
                                       'path': '/v3/mail_settings/forward_bounce',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_list_forward_spam': {'name': 'mail_settings_list_forward_spam',
                                     'label': 'Retrieve forward spam mail settings',
                                     'description': '**This endpoint allows you to retrieve your '
                                                    'current Forward Spam mail settings.** '
                                                    'Enabling the Forward Spam setting allows you '
                                                    'to specify `email` addresses to which spam '
                                                    'reports will be forwarded. This endpoint '
                                                    'returns any email address(es) you have set to '
                                                    'receive forwarded spam and an `enabled` '
                                                    'status indicating if the setting is active.',
                                     'category': 'Mail Settings',
                                     'family': 'mail_settings',
                                     'method': 'GET',
                                     'path': '/v3/mail_settings/forward_spam',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_list_mail_setting': {'name': 'mail_settings_list_mail_setting',
                                     'label': 'Retrieve all mail settings',
                                     'description': '**This endpoint allows you to retrieve a '
                                                    'paginated list of all mail settings.** Each '
                                                    'setting will be returned with an `enabled` '
                                                    'status set to `true` or `false` and a short '
                                                    'description that explains what the setting '
                                                    'does. You can use the `limit` query parameter '
                                                    'to set the page size. If your list contains '
                                                    'more items than the page size permits, you '
                                                    'can make multiple requests. Use the `offset` '
                                                    'query p',
                                     'category': 'Mail Settings',
                                     'family': 'mail_settings',
                                     'method': 'GET',
                                     'path': '/v3/mail_settings',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_list_template': {'name': 'mail_settings_list_template',
                                 'label': 'Retrieve legacy template mail settings',
                                 'description': '**This endpoint allows you to retrieve your '
                                                'current legacy email template settings.** This '
                                                'setting refers to our original email templates. '
                                                'We currently support more fully featured [Dynamic '
                                                'Transactional '
                                                'Templates](https://sendgrid.com/docs/ui/sending-email/how-to-send-an-email-with-dynamic-transactional-templates/). '
                                                'The legacy email template setting wraps an HTML '
                                                'template around your email content',
                                 'category': 'Mail Settings',
                                 'family': 'mail_settings',
                                 'method': 'GET',
                                 'path': '/v3/mail_settings/template',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_update_address_whitelist': {'name': 'mail_settings_update_address_whitelist',
                                            'label': 'Update address whitelist mail settings',
                                            'description': '**This endpoint allows you to update '
                                                           'your current email address whitelist '
                                                           'settings.** For Regional Subusers - '
                                                           'Utilizing this feature for Regional '
                                                           '(EU) subusers will cause customer '
                                                           'personal information to be stored '
                                                           'outside of the EU. You can select '
                                                           'whether or not this setting should be '
                                                           'enabled by assigning the `enabled` '
                                                           'field a `true` or `false` value. '
                                                           'Passing only the `enabled` field to '
                                                           'this endpo',
                                            'category': 'Mail Settings',
                                            'family': 'mail_settings',
                                            'method': 'PATCH',
                                            'path': '/v3/mail_settings/address_whitelist',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': 'application/json',
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_update_bounce_purge': {'name': 'mail_settings_update_bounce_purge',
                                       'label': 'Update Bounce Purge Mail Settings',
                                       'description': '**This endpoint allows you to update your '
                                                      'current Bounce Purge mail settings.** The '
                                                      'Bounce Purge mail metting allows you to '
                                                      'configure the maximum age of contacts in '
                                                      'your hard and soft bounce suppressions '
                                                      'lists. All contacts older than their '
                                                      'respective configured age are deleted. A '
                                                      'hard bounce occurs when an email message '
                                                      'has been returned to the sender because the '
                                                      "recipient's address is invalid. A",
                                       'category': 'Mail Settings',
                                       'family': 'mail_settings',
                                       'method': 'PATCH',
                                       'path': '/v3/mail_settings/bounce_purge',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_update_footer': {'name': 'mail_settings_update_footer',
                                 'label': 'Update footer mail settings',
                                 'description': '**This endpoint allows you to update your current '
                                                'Footer mail settings.** The Footer setting will '
                                                'insert a custom footer at the bottom of your text '
                                                'and HTML email message bodies. You can insert '
                                                'your HTML or plain text directly using this '
                                                'endpoint, or you can create the footer using the '
                                                '[Mail Settings menu in the Twilio SendGrid '
                                                'App](https://app.sendgrid.com/settings/mail_settings).',
                                 'category': 'Mail Settings',
                                 'family': 'mail_settings',
                                 'method': 'PATCH',
                                 'path': '/v3/mail_settings/footer',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': 'application/json',
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_update_forward_bounce': {'name': 'mail_settings_update_forward_bounce',
                                         'label': 'Update forward bounce mail settings',
                                         'description': '**This endpoint allows you to update your '
                                                        'current bounce forwarding mail '
                                                        'settings.** Enabling the Forward Bounce '
                                                        'setting allows you to specify an `email` '
                                                        'address to which bounce reports will be '
                                                        'forwarded. You can also configure the '
                                                        'Forward Spam mail settings in the [Mail '
                                                        'Settings section of the Twilio SendGrid '
                                                        'App](https://app.sendgrid.com/settings/mail_settings).',
                                         'category': 'Mail Settings',
                                         'family': 'mail_settings',
                                         'method': 'PATCH',
                                         'path': '/v3/mail_settings/forward_bounce',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': 'application/json',
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_update_forward_spam': {'name': 'mail_settings_update_forward_spam',
                                       'label': 'Update forward spam mail settings',
                                       'description': '**This endpoint allows you to update your '
                                                      'current Forward Spam mail settings.** '
                                                      'Enabling the Forward Spam setting allows '
                                                      'you to specify `email` addresses to which '
                                                      'spam reports will be forwarded. You can set '
                                                      'multiple addresses by passing this endpoint '
                                                      'a comma separated list of emails in a '
                                                      'single string. ``` { "email": '
                                                      '"address1@example.com, '
                                                      'address2@exapmle.com", "enabled": true } '
                                                      '``` The Forward S',
                                       'category': 'Mail Settings',
                                       'family': 'mail_settings',
                                       'method': 'PATCH',
                                       'path': '/v3/mail_settings/forward_spam',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mail_settings_update_template': {'name': 'mail_settings_update_template',
                                   'label': 'Update template mail settings',
                                   'description': '**This endpoint allows you to update your '
                                                  'current legacy email template settings.** This '
                                                  'setting refers to our original email templates. '
                                                  'We currently support more fully featured '
                                                  '[Dynamic Transactional '
                                                  'Templates](https://sendgrid.com/docs/ui/sending-email/how-to-send-an-email-with-dynamic-transactional-templates/). '
                                                  'The legacy email template setting wraps an HTML '
                                                  'template around your email content. ',
                                   'category': 'Mail Settings',
                                   'family': 'mail_settings',
                                   'method': 'PATCH',
                                   'path': '/v3/mail_settings/template',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_settings_v3.json'},
 'mc_contacts_delete_contact': {'name': 'mc_contacts_delete_contact',
                                'label': 'Delete Contacts',
                                'description': '**This endpoint can be used to delete one or more '
                                               'contacts**. The query parameter `ids` must set to '
                                               'a comma-separated list of contact IDs for bulk '
                                               'contact deletion. The query parameter '
                                               '`delete_all_contacts` must be set to `"true"` to '
                                               'delete **all** contacts. You must set either `ids` '
                                               'or `delete_all_contacts`. Deletion jobs are '
                                               'processed asynchronously. Twilio SendGrid '
                                               'recommends exporting your con',
                                'category': 'Contacts',
                                'family': 'mc_contacts',
                                'method': 'DELETE',
                                'path': '/v3/marketing/contacts',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_delete_contact_identifier': {'name': 'mc_contacts_delete_contact_identifier',
                                           'label': 'Delete a Contact Identifier',
                                           'description': '**This endpoint can be used to delete '
                                                          'one identifier from a contact.** '
                                                          'Deletion jobs are processed '
                                                          'asynchronously. Note this is different '
                                                          'from deleting a contact. If the contact '
                                                          'has only one identifier, the '
                                                          'asynchronous request will fail. All '
                                                          'contacts are required to have at least '
                                                          'one identifier. The request body field '
                                                          '`identifier_type` must have a valid '
                                                          'value of "EMAIL", "PHONENUMBERID", '
                                                          '"EXTERNA',
                                           'category': 'Contacts',
                                           'family': 'mc_contacts',
                                           'method': 'DELETE',
                                           'path': '/v3/marketing/contacts/{contact_id}/identifiers',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': 'application/json',
                                           'regions': ['us'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_export_contact': {'name': 'mc_contacts_export_contact',
                                'label': 'Export Contacts',
                                'description': '**Use this endpoint to export lists or segments of '
                                               'contacts**. If you would just like to have a link '
                                               'to the exported list sent to your email set the '
                                               '`notifications.email` option to `true` in the '
                                               '`POST` payload. If you would like to download the '
                                               'list, take the `id` that is returned and use the '
                                               '"Export Contacts Status" endpoint to get the '
                                               '`urls`. Once you have the list of URLs, make a '
                                               '`GET` request ',
                                'category': 'Contacts',
                                'family': 'mc_contacts',
                                'method': 'POST',
                                'path': '/v3/marketing/contacts/exports',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_get_contact': {'name': 'mc_contacts_get_contact',
                             'label': 'Get a Contact by ID',
                             'description': '**This endpoint returns the full details and all '
                                            'fields for the specified contact**. The "Get Contacts '
                                            'by Identifier" endpoint can be used to get the ID of '
                                            'a contact.',
                             'category': 'Contacts',
                             'family': 'mc_contacts',
                             'method': 'GET',
                             'path': '/v3/marketing/contacts/{id}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_get_contact_by_identifiers': {'name': 'mc_contacts_get_contact_by_identifiers',
                                            'label': 'Get Contacts by Identifiers',
                                            'description': 'Use this endpoint to retrieve up to '
                                                           '100 contacts that match the requested '
                                                           'identifier values for a single '
                                                           'identifier type. `identifier_type` '
                                                           'must be a valid identifier type: '
                                                           '`email`, `phone_number_id`, '
                                                           '`external_id`, or `anonymous_id`. Use '
                                                           'this endpoint instead of the [Search '
                                                           'Contacts '
                                                           'endpoint](https://www.twilio.com/docs/sendgrid/api-reference/contacts/search-contacts) '
                                                           'when you can provide exact i',
                                            'category': 'Contacts',
                                            'family': 'mc_contacts',
                                            'method': 'POST',
                                            'path': '/v3/marketing/contacts/search/identifiers/{identifier_type}',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': 'application/json',
                                            'regions': ['us'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_get_export_contact': {'name': 'mc_contacts_get_export_contact',
                                    'label': 'Export Contacts Status',
                                    'description': '**This endpoint can be used to check the '
                                                   'status of a contact export job**. To use this '
                                                   'call, you will need the `id` from the "Export '
                                                   'Contacts" call. If you would like to download '
                                                   'a list, take the `id` that is returned from '
                                                   'the "Export Contacts" endpoint and make an API '
                                                   'request here to get the `urls`. Once you have '
                                                   'the list of URLs, make a `GET` request on each '
                                                   'URL to download your CSV file(s). Twi',
                                    'category': 'Contacts',
                                    'family': 'mc_contacts',
                                    'method': 'GET',
                                    'path': '/v3/marketing/contacts/exports/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_get_import_contact': {'name': 'mc_contacts_get_import_contact',
                                    'label': 'Import Contacts Status',
                                    'description': '**This endpoint can be used to check the '
                                                   'status of a contact import job**. Use the '
                                                   '`job_id` from the "Import Contacts," "Add or '
                                                   'Update a Contact," or "Delete Contacts" '
                                                   'endpoints as the `id` in the path parameter. '
                                                   'If there is an error with your `PUT` request, '
                                                   'download the `errors_url` file and open it to '
                                                   'view more details. The job `status` field '
                                                   'indicates whether the job is `pending`, '
                                                   '`completed`, ',
                                    'category': 'Contacts',
                                    'family': 'mc_contacts',
                                    'method': 'GET',
                                    'path': '/v3/marketing/contacts/imports/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_import_contact': {'name': 'mc_contacts_import_contact',
                                'label': 'Import Contacts',
                                'description': '**This endpoint allows a CSV upload containing up '
                                               'to one million contacts or 5GB of data, whichever '
                                               'is smaller. At least one identifier is required '
                                               'for a successful import.** Imports take place '
                                               'asynchronously: the endpoint returns a URL '
                                               '(`upload_uri`) and HTTP headers (`upload_headers`) '
                                               'which can subsequently be used to `PUT` a file of '
                                               'contacts to be imported into our system. Uploaded '
                                               'CSV files ma',
                                'category': 'Contacts',
                                'family': 'mc_contacts',
                                'method': 'PUT',
                                'path': '/v3/marketing/contacts/imports',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_list_batched_contact': {'name': 'mc_contacts_list_batched_contact',
                                      'label': 'Get Batched Contacts by IDs',
                                      'description': '**This endpoint is used to retrieve a set of '
                                                     'contacts identified by their IDs.** This can '
                                                     'be more efficient endpoint to get contacts '
                                                     'than making a series of individual `GET` '
                                                     'requests to the "Get a Contact by ID" '
                                                     'endpoint. You can supply up to 100 IDs. Pass '
                                                     'them into the `ids` field in your request '
                                                     'body as an array or one or more strings. '
                                                     'Twilio SendGrid recommends exporting your '
                                                     'contacts regularly',
                                      'category': 'Contacts',
                                      'family': 'mc_contacts',
                                      'method': 'POST',
                                      'path': '/v3/marketing/contacts/batch',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': 'application/json',
                                      'regions': ['us'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_list_contact': {'name': 'mc_contacts_list_contact',
                              'label': 'Get Sample Contacts',
                              'description': '**This endpoint will return up to 50 of the most '
                                             'recent contacts uploaded or attached to a list**. '
                                             'This list will then be sorted by email address. The '
                                             'full contact count is also returned. Please note '
                                             'that pagination of the contacts has been deprecated. '
                                             'Twilio SendGrid recommends exporting your contacts '
                                             'regularly as a backup to avoid issues or lost data.',
                              'category': 'Contacts',
                              'family': 'mc_contacts',
                              'method': 'GET',
                              'path': '/v3/marketing/contacts',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_list_contact_by_email': {'name': 'mc_contacts_list_contact_by_email',
                                       'label': 'Get Contacts by Emails',
                                       'description': '**This endpoint allows you to retrieve up '
                                                      'to 100 contacts matching the searched '
                                                      '`email` address(es), including any '
                                                      '`alternate_emails`.** Email addresses are '
                                                      'unique to a contact, meaning this endpoint '
                                                      'can treat an email address as a primary key '
                                                      'to search by. The contact object associated '
                                                      'with the address, whether it is their '
                                                      '`email` or one of their `alternate_emails` '
                                                      'will be returned if matched. Em',
                                       'category': 'Contacts',
                                       'family': 'mc_contacts',
                                       'method': 'POST',
                                       'path': '/v3/marketing/contacts/search/emails',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_list_contact_count': {'name': 'mc_contacts_list_contact_count',
                                    'label': 'Get Total Contact Count',
                                    'description': '**This endpoint returns the total number of '
                                                   'contacts you have stored.** Twilio SendGrid '
                                                   'recommends exporting your contacts regularly '
                                                   'as a backup to avoid issues or lost data.',
                                    'category': 'Contacts',
                                    'family': 'mc_contacts',
                                    'method': 'GET',
                                    'path': '/v3/marketing/contacts/count',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_list_export_contact': {'name': 'mc_contacts_list_export_contact',
                                     'label': 'Get All Existing Exports',
                                     'description': '**Use this endpoint to retrieve details of '
                                                    'all current exported jobs**. It will return '
                                                    'an array of objects, each of which records an '
                                                    'export job in flight or recently completed. '
                                                    "Each object's `export_type` field will tell "
                                                    'you which kind of export it is and its '
                                                    '`status` field will indicate what stage of '
                                                    'processing it has reached. Exports which are '
                                                    '`ready` will be accompanied by a `urls` field '
                                                    'which ',
                                     'category': 'Contacts',
                                     'family': 'mc_contacts',
                                     'method': 'GET',
                                     'path': '/v3/marketing/contacts/exports',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_search_contact': {'name': 'mc_contacts_search_contact',
                                'label': 'Search Contacts',
                                'description': '**Use this endpoint to locate contacts**. The '
                                               "request body's `query` field accepts valid "
                                               '[SGQL](https://sendgrid.com/docs/for-developers/sending-email/segmentation-query-language/) '
                                               'for searching for a contact. Because contact '
                                               'emails are stored in lower case, using SGQL to '
                                               'search by email address requires the provided '
                                               'email address to be in lower case. The SGQL '
                                               '`lower()` function can be used for th',
                                'category': 'Contacts',
                                'family': 'mc_contacts',
                                'method': 'POST',
                                'path': '/v3/marketing/contacts/search',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_contacts_update_contact': {'name': 'mc_contacts_update_contact',
                                'label': 'Add or Update a Contact',
                                'description': '**This endpoint allows the '
                                               '[upsert](https://en.wiktionary.org/wiki/upsert) '
                                               '(insert or update) of up to 30,000 contacts, or '
                                               '6MB of data, whichever is lower**. Because the '
                                               'creation and update of contacts is an asynchronous '
                                               'process, the response will not contain immediate '
                                               'feedback on the processing of your upserted '
                                               'contacts. Rather, it will contain an HTTP 202 '
                                               'response indicating the contacts are que',
                                'category': 'Contacts',
                                'family': 'mc_contacts',
                                'method': 'PUT',
                                'path': '/v3/marketing/contacts',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_contacts_v3.json'},
 'mc_custom_fields_create_field_definition': {'name': 'mc_custom_fields_create_field_definition',
                                              'label': 'Create Custom Field Definition',
                                              'description': '**This endpoint creates a new custom '
                                                             'field definition.** Custom field '
                                                             'definitions are created with the '
                                                             'given `name` and `field_type`. '
                                                             'Although field names are stored in a '
                                                             'case-sensitive manner, all field '
                                                             'names must be case-insensitively '
                                                             'unique. This means you may create a '
                                                             'field named `CamelCase` or '
                                                             '`camelcase`, but not both. '
                                                             'Additionally, a Custom Field name '
                                                             'cannot collide with any Reserved '
                                                             'Field ',
                                              'category': 'Custom Fields',
                                              'family': 'mc_custom_fields',
                                              'method': 'POST',
                                              'path': '/v3/marketing/field_definitions',
                                              'required_params': [],
                                              'body_required': False,
                                              'body_type': 'application/json',
                                              'regions': ['us'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_custom_fields_v3.json'},
 'mc_custom_fields_delete_field_definition': {'name': 'mc_custom_fields_delete_field_definition',
                                              'label': 'Delete Custom Field Definition',
                                              'description': '**This endpoint deletes a defined '
                                                             'Custom Field.** You can delete only '
                                                             'Custom Fields; Reserved Fields '
                                                             'cannot be deleted.',
                                              'category': 'Custom Fields',
                                              'family': 'mc_custom_fields',
                                              'method': 'DELETE',
                                              'path': '/v3/marketing/field_definitions/{custom_field_id}',
                                              'required_params': [],
                                              'body_required': False,
                                              'body_type': None,
                                              'regions': ['us'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_custom_fields_v3.json'},
 'mc_custom_fields_list_field_definition': {'name': 'mc_custom_fields_list_field_definition',
                                            'label': 'Get All Field Definitions',
                                            'description': '**This endpoint retrieves all defined '
                                                           'Custom Fields and Reserved Fields.**',
                                            'category': 'Custom Fields',
                                            'family': 'mc_custom_fields',
                                            'method': 'GET',
                                            'path': '/v3/marketing/field_definitions',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': None,
                                            'regions': ['us'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_custom_fields_v3.json'},
 'mc_custom_fields_update_field_definition': {'name': 'mc_custom_fields_update_field_definition',
                                              'label': 'Update Custom Field Definition',
                                              'description': '**This endpoint allows you to update '
                                                             'a defined Custom Field.** Only your '
                                                             'Custom fields can be modified; '
                                                             'Reserved Fields cannot be updated.',
                                              'category': 'Custom Fields',
                                              'family': 'mc_custom_fields',
                                              'method': 'PATCH',
                                              'path': '/v3/marketing/field_definitions/{custom_field_id}',
                                              'required_params': [],
                                              'body_required': False,
                                              'body_type': 'application/json',
                                              'regions': ['us'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_custom_fields_v3.json'},
 'mc_designs_create_design': {'name': 'mc_designs_create_design',
                              'label': 'Create Design',
                              'description': '**This endpoint allows you to create a new design**. '
                                             'You can add a new design by passing data, including '
                                             'a string of HTML email content, to `/designs`. When '
                                             'creating designs from scratch, be aware of the '
                                             'styling constraints inherent to many email clients. '
                                             'For a list of best practices, see our guide to '
                                             '[Cross-Platform Email '
                                             'Design](https://sendgrid.com/docs/ui/sending-email/cross-platform-html-desi',
                              'category': 'Designs',
                              'family': 'mc_designs',
                              'method': 'POST',
                              'path': '/v3/designs',
                              'required_params': [],
                              'body_required': False,
                              'body_type': 'application/json',
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_delete_design': {'name': 'mc_designs_delete_design',
                              'label': 'Delete Design',
                              'description': '**This endpoint allows you to delete a single '
                                             'design**. Be sure to check the ID of the design you '
                                             'intend to delete before making this request; '
                                             'deleting a design is a permanent action.',
                              'category': 'Designs',
                              'family': 'mc_designs',
                              'method': 'DELETE',
                              'path': '/v3/designs/{id}',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_duplicate_design': {'name': 'mc_designs_duplicate_design',
                                 'label': 'Duplicate Design',
                                 'description': '**This endpoint allows you to duplicate one of '
                                                'your existing designs**. Modifying an existing '
                                                'design is often the easiest way to create '
                                                'something new. You are not required to pass any '
                                                'data in the body of a request to this endpoint. '
                                                'If you choose to leave the `name` field blank, '
                                                'your duplicate will be assigned the name of the '
                                                'design it was copied from with the text '
                                                '"Duplicate: " prepended to it. Th',
                                 'category': 'Designs',
                                 'family': 'mc_designs',
                                 'method': 'POST',
                                 'path': '/v3/designs/{id}',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': 'application/json',
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_duplicate_pre_built_design': {'name': 'mc_designs_duplicate_pre_built_design',
                                           'label': 'Duplicate SendGrid Pre-built Design',
                                           'description': '**This endpoint allows you to duplicate '
                                                          'one of the pre-built Twilio SendGrid '
                                                          'designs**. Like duplicating one of your '
                                                          'existing designs, you are not required '
                                                          'to pass any data in the body of a '
                                                          'request to this endpoint. If you choose '
                                                          'to leave the `name` field blank, your '
                                                          'duplicate will be assigned the name of '
                                                          'the design it was copied from with the '
                                                          'text "Duplicate: " prepended to it. '
                                                          'This name change i',
                                           'category': 'Designs',
                                           'family': 'mc_designs',
                                           'method': 'POST',
                                           'path': '/v3/designs/pre-builts/{id}',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': 'application/json',
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_get_design': {'name': 'mc_designs_get_design',
                           'label': 'Get Design',
                           'description': '**This endpoint allows you to retrieve a single '
                                          'design**. A GET request to `/designs/{id}` will '
                                          'retrieve details about a specific design in your Design '
                                          'Library. This endpoint is valuable when retrieving '
                                          'information stored in a field that you wish to update '
                                          'using a PATCH request.',
                           'category': 'Designs',
                           'family': 'mc_designs',
                           'method': 'GET',
                           'path': '/v3/designs/{id}',
                           'required_params': [],
                           'body_required': False,
                           'body_type': None,
                           'regions': ['us', 'eu'],
                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_get_pre_built_design': {'name': 'mc_designs_get_pre_built_design',
                                     'label': 'Get SendGrid Pre-built Design',
                                     'description': '**This endpoint allows you to retrieve a '
                                                    'single pre-built design**. A GET request to '
                                                    '`/designs/pre-builts/{id}` will retrieve '
                                                    'details about a specific pre-built design. '
                                                    'This endpoint is valuable when retrieving '
                                                    'details about a pre-built design that you '
                                                    'wish to duplicate and modify.',
                                     'category': 'Designs',
                                     'family': 'mc_designs',
                                     'method': 'GET',
                                     'path': '/v3/designs/pre-builts/{id}',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_list_design': {'name': 'mc_designs_list_design',
                            'label': 'List Designs',
                            'description': '**This endpoint allows you to retrieve a list of '
                                           'designs already stored in your Design Library**. A GET '
                                           'request to `/designs` will return a list of your '
                                           'existing designs. This endpoint will not return the '
                                           'pre-built Twilio SendGrid designs. Pre-built designs '
                                           'can be retrieved using the `/designs/pre-builts` '
                                           'endpoint, which is detailed below. By default, you '
                                           'will receive 100 results per request; howe',
                            'category': 'Designs',
                            'family': 'mc_designs',
                            'method': 'GET',
                            'path': '/v3/designs',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_list_pre_built_design': {'name': 'mc_designs_list_pre_built_design',
                                      'label': 'List SendGrid Pre-built Designs',
                                      'description': '**This endpoint allows you to retrieve a '
                                                     'list of pre-built designs provided by Twilio '
                                                     'SendGrid**. Unlike the `/designs` endpoint '
                                                     'where *your* designs are stored, a GET '
                                                     'request made to `designs/pre-builts` will '
                                                     'retrieve a list of the pre-built Twilio '
                                                     'SendGrid designs. This endpoint will not '
                                                     'return the designs stored in your Design '
                                                     'Library. By default, you will receive 100 '
                                                     'results per request; howev',
                                      'category': 'Designs',
                                      'family': 'mc_designs',
                                      'method': 'GET',
                                      'path': '/v3/designs/pre-builts',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_designs_update_design': {'name': 'mc_designs_update_design',
                              'label': 'Update Design',
                              'description': '**This endpoint allows you to edit a design**. The '
                                             'Design API supports PATCH requests, which allow you '
                                             'to make partial updates to a single design. Passing '
                                             'data to a specific field will update only the data '
                                             'stored in that field; all other fields will be '
                                             "unaltered. For example, updating a design's name "
                                             'requires that you make a PATCH request to this '
                                             'endpoint with data specified for the `name` field o',
                              'category': 'Designs',
                              'family': 'mc_designs',
                              'method': 'PATCH',
                              'path': '/v3/designs/{id}',
                              'required_params': [],
                              'body_required': False,
                              'body_type': 'application/json',
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_designs_v3.json'},
 'mc_lists_create_marketing_list': {'name': 'mc_lists_create_marketing_list',
                                    'label': 'Create List',
                                    'description': '**This endpoint creates a new contacts list.** '
                                                   'Once you create a list, you can use the UI to '
                                                   '[trigger an '
                                                   'automation](https://sendgrid.com/docs/ui/sending-email/getting-started-with-automation/#create-an-automation) '
                                                   'every time you add a new contact to the list. '
                                                   'A link to the newly created object is in '
                                                   '`_metadata`.',
                                    'category': 'Lists',
                                    'family': 'mc_lists',
                                    'method': 'POST',
                                    'path': '/v3/marketing/lists',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_lists_delete_contact': {'name': 'mc_lists_delete_contact',
                             'label': 'Remove Contacts from a List',
                             'description': '**This endpoint allows you to remove contacts from a '
                                            'given list.** The contacts will not be deleted. Only '
                                            'their list membership will be changed.',
                             'category': 'Lists',
                             'family': 'mc_lists',
                             'method': 'DELETE',
                             'path': '/v3/marketing/lists/{id}/contacts',
                             'required_params': [{'name': 'contact_ids', 'in': 'query'}],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_lists_delete_marketing_list': {'name': 'mc_lists_delete_marketing_list',
                                    'label': 'Delete a list',
                                    'description': '**This endpoint allows you to deletes a '
                                                   'specific list.** Optionally, you can also '
                                                   'delete contacts associated to the list. The '
                                                   'query parameter, `delete_contacts=true`, will '
                                                   'delete the list and start an asynchronous job '
                                                   'to delete associated contacts.',
                                    'category': 'Lists',
                                    'family': 'mc_lists',
                                    'method': 'DELETE',
                                    'path': '/v3/marketing/lists/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_lists_get_marketing_list': {'name': 'mc_lists_get_marketing_list',
                                 'label': 'Get a List by ID',
                                 'description': '**This endpoint returns data about a specific '
                                                'list.** Setting the optional parameter '
                                                '`contact_sample=true` returns the '
                                                '`contact_sample` in the response body. Up to 50 '
                                                'of the most recent contacts uploaded or attached '
                                                'to a list will be returned. The full contact '
                                                'count is also returned.',
                                 'category': 'Lists',
                                 'family': 'mc_lists',
                                 'method': 'GET',
                                 'path': '/v3/marketing/lists/{id}',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_lists_list_contact_count': {'name': 'mc_lists_list_contact_count',
                                 'label': 'Get List Contact Count',
                                 'description': '**This endpoint returns the number of contacts on '
                                                'a specific list.**',
                                 'category': 'Lists',
                                 'family': 'mc_lists',
                                 'method': 'GET',
                                 'path': '/v3/marketing/lists/{id}/contacts/count',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_lists_list_marketing_list': {'name': 'mc_lists_list_marketing_list',
                                  'label': 'Get All Lists',
                                  'description': '**This endpoint returns an array of all of your '
                                                 'contact lists.**',
                                  'category': 'Lists',
                                  'family': 'mc_lists',
                                  'method': 'GET',
                                  'path': '/v3/marketing/lists',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_lists_update_marketing_list': {'name': 'mc_lists_update_marketing_list',
                                    'label': 'Update List',
                                    'description': '**This endpoint updates the name of a list.**',
                                    'category': 'Lists',
                                    'family': 'mc_lists',
                                    'method': 'PATCH',
                                    'path': '/v3/marketing/lists/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_lists_v3.json'},
 'mc_segments_2_0_create_segment': {'name': 'mc_segments_2_0_create_segment',
                                    'label': 'Create Segment',
                                    'description': 'Segment `name` has to be unique. A user can '
                                                   'not create a new segment with an existing '
                                                   'segment name.',
                                    'category': 'Segmenting Contacts V2',
                                    'family': 'mc_segments_2_0',
                                    'method': 'POST',
                                    'path': '/v3/marketing/segments/2.0',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_2.0_v3.json'},
 'mc_segments_2_0_delete_segment': {'name': 'mc_segments_2_0_delete_segment',
                                    'label': 'Delete segment',
                                    'description': '**This endpoint allows you to delete a segment '
                                                   'by ID.**',
                                    'category': 'Segmenting Contacts V2',
                                    'family': 'mc_segments_2_0',
                                    'method': 'DELETE',
                                    'path': '/v3/marketing/segments/2.0/{segment_id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_2.0_v3.json'},
 'mc_segments_2_0_get_segment': {'name': 'mc_segments_2_0_get_segment',
                                 'label': 'Get Segment by ID',
                                 'description': 'Get Marketing Campaigns Segment by ID',
                                 'category': 'Segmenting Contacts V2',
                                 'family': 'mc_segments_2_0',
                                 'method': 'GET',
                                 'path': '/v3/marketing/segments/2.0/{segment_id}',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_2.0_v3.json'},
 'mc_segments_2_0_list_segment': {'name': 'mc_segments_2_0_list_segment',
                                  'label': 'Get List of Segments',
                                  'description': '**This endpoint allows you to retrieve a list of '
                                                 'segments.** The query param `parent_list_ids` is '
                                                 'treated as a filter. Any match will be returned. '
                                                 'Zero matches will return a response code of 200 '
                                                 'with an empty `results` array. `parent_list_ids` '
                                                 '| `no_parent_list_id` | `ids` | `result` '
                                                 '-----------------:|:--------------------:|:-------------:|:-------------: '
                                                 'empty | false | empty | all segments valu',
                                  'category': 'Segmenting Contacts V2',
                                  'family': 'mc_segments_2_0',
                                  'method': 'GET',
                                  'path': '/v3/marketing/segments/2.0',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_2.0_v3.json'},
 'mc_segments_2_0_refresh_segment': {'name': 'mc_segments_2_0_refresh_segment',
                                     'label': 'Manually refresh a segment',
                                     'description': 'Manually refresh a segment by segment ID.',
                                     'category': 'Segmenting Contacts V2',
                                     'family': 'mc_segments_2_0',
                                     'method': 'POST',
                                     'path': '/v3/marketing/segments/2.0/refresh/{segment_id}',
                                     'required_params': [],
                                     'body_required': True,
                                     'body_type': 'application/json',
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_2.0_v3.json'},
 'mc_segments_2_0_update_segment': {'name': 'mc_segments_2_0_update_segment',
                                    'label': 'Update Segment',
                                    'description': 'Segment `name` has to be unique. A user can '
                                                   'not create a new segment with an existing '
                                                   'segment name.',
                                    'category': 'Segmenting Contacts V2',
                                    'family': 'mc_segments_2_0',
                                    'method': 'PATCH',
                                    'path': '/v3/marketing/segments/2.0/{segment_id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_2.0_v3.json'},
 'mc_segments_delete_segment': {'name': 'mc_segments_delete_segment',
                                'label': 'Delete Segment',
                                'description': '**This endpoint allows you to delete a segment by '
                                               '`segment_id`.** Note that deleting a segment does '
                                               'not delete the contacts associated with the '
                                               'segment by default. Contacts associated with a '
                                               'deleted segment will remain in your list of all '
                                               'contacts and any other segments they belong to.',
                                'category': 'Segmenting Contacts',
                                'family': 'mc_segments',
                                'method': 'DELETE',
                                'path': '/v3/marketing/segments/{segment_id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_v3.json'},
 'mc_segments_get_segment': {'name': 'mc_segments_get_segment',
                             'label': 'Get Segment by ID',
                             'description': '**This endpoint allows you to retrieve a single '
                                            'segment by ID.**',
                             'category': 'Segmenting Contacts',
                             'family': 'mc_segments',
                             'method': 'GET',
                             'path': '/v3/marketing/segments/{segment_id}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_v3.json'},
 'mc_segments_list_segment': {'name': 'mc_segments_list_segment',
                              'label': 'Get List of Segments',
                              'description': '**This endpoint allows you to retrieve a list of '
                                             'segments.** The query param `parent_list_ids` is '
                                             'treated as a filter. Any match will be returned. '
                                             'Zero matches will return a response code of 200 with '
                                             'an empty `results` array. `parent_list_ids` | '
                                             '`no_parent_list_id` | `ids` | `result` '
                                             '-----------------:|:--------------------:|:-------------:|:-------------: '
                                             'empty | false | empty | all segments valu',
                              'category': 'Segmenting Contacts',
                              'family': 'mc_segments',
                              'method': 'GET',
                              'path': '/v3/marketing/segments',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_segments_v3.json'},
 'mc_senders_create_sender': {'name': 'mc_senders_create_sender',
                              'label': 'Create a Sender',
                              'description': '**This endpoint allows you to create a new Sender.** '
                                             '*You may create up to 100 unique Senders.* Senders '
                                             'are required to be verified before use. If your '
                                             'domain has been authenticated, a new Sender will '
                                             'auto verify on creation. Otherwise an email will be '
                                             'sent to the `from.email`.',
                              'category': 'Senders',
                              'family': 'mc_senders',
                              'method': 'POST',
                              'path': '/v3/marketing/senders',
                              'required_params': [],
                              'body_required': False,
                              'body_type': 'application/json',
                              'regions': ['us'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_senders_v3.json'},
 'mc_senders_delete_sender': {'name': 'mc_senders_delete_sender',
                              'label': 'Delete a Sender',
                              'description': '**This endpoint allows you to delete an existing '
                                             'Sender.**',
                              'category': 'Senders',
                              'family': 'mc_senders',
                              'method': 'DELETE',
                              'path': '/v3/marketing/senders/{id}',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_senders_v3.json'},
 'mc_senders_get_sender': {'name': 'mc_senders_get_sender',
                           'label': 'Get a specific Sender',
                           'description': '**This endpoint allows you to get the details for a '
                                          'specific Sender by `id`.**',
                           'category': 'Senders',
                           'family': 'mc_senders',
                           'method': 'GET',
                           'path': '/v3/marketing/senders/{id}',
                           'required_params': [],
                           'body_required': False,
                           'body_type': None,
                           'regions': ['us'],
                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_senders_v3.json'},
 'mc_senders_list_sender': {'name': 'mc_senders_list_sender',
                            'label': 'Get a list of all Senders',
                            'description': '**This endpoint allows you to get a list of all your '
                                           'Senders.**',
                            'category': 'Senders',
                            'family': 'mc_senders',
                            'method': 'GET',
                            'path': '/v3/marketing/senders',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_senders_v3.json'},
 'mc_senders_reset_sender_verification': {'name': 'mc_senders_reset_sender_verification',
                                          'label': 'Resend a Sender verification',
                                          'description': '**This endpoint allows you to resend the '
                                                         'verification request for a specific '
                                                         'Sender.**',
                                          'category': 'Senders',
                                          'family': 'mc_senders',
                                          'method': 'POST',
                                          'path': '/v3/marketing/senders/{id}/resend_verification',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_senders_v3.json'},
 'mc_senders_update_sender': {'name': 'mc_senders_update_sender',
                              'label': 'Update a Sender',
                              'description': '**This endpoint allows you to update an existing '
                                             'Sender.** Updates to `from.email` require '
                                             're-verification. If your domain has been '
                                             'authenticated, a new Sender will auto verify on '
                                             'creation. Otherwise, an email will be sent to the '
                                             '`from.email`. Partial updates are allowed, but '
                                             'fields that are marked as "required" in the `POST` '
                                             '(create) endpoint must not be nil if that field is '
                                             'included in the `PATC',
                              'category': 'Senders',
                              'family': 'mc_senders',
                              'method': 'PATCH',
                              'path': '/v3/marketing/senders/{id}',
                              'required_params': [],
                              'body_required': False,
                              'body_type': 'application/json',
                              'regions': ['us'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_senders_v3.json'},
 'mc_singlesends_create_single_send': {'name': 'mc_singlesends_create_single_send',
                                       'label': 'Create Single Send',
                                       'description': '**This endpoint allows you to create a new '
                                                      'Single Send.** Please note that if you are '
                                                      'migrating from the previous version of '
                                                      'Single Sends, you no longer need to pass a '
                                                      'template ID with your request to this '
                                                      'endpoint. Instead, you will pass all '
                                                      'template data in the `email_config` object. '
                                                      'This endpoint will create a draft of the '
                                                      'Single Send but will not send it or '
                                                      'schedule it to be sent. Any `send_at',
                                       'category': 'Single Sends',
                                       'family': 'mc_singlesends',
                                       'method': 'POST',
                                       'path': '/v3/marketing/singlesends',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_delete_scheduled_single_send': {'name': 'mc_singlesends_delete_scheduled_single_send',
                                                 'label': 'Delete Single Send Schedule',
                                                 'description': '**This endpoint allows you to '
                                                                'cancel a scheduled Single Send '
                                                                'using a Single Send ID.** Making '
                                                                'a DELETE request to this endpoint '
                                                                'will cancel the scheduled sending '
                                                                'of a Single Send. The request '
                                                                'will not delete the Single Send '
                                                                'itself. Deleting a Single Send '
                                                                'can be done by passing a DELETE '
                                                                'request to '
                                                                '`/marketing/singlesends/{id}`.',
                                                 'category': 'Single Sends',
                                                 'family': 'mc_singlesends',
                                                 'method': 'DELETE',
                                                 'path': '/v3/marketing/singlesends/{id}/schedule',
                                                 'required_params': [],
                                                 'body_required': False,
                                                 'body_type': None,
                                                 'regions': ['us'],
                                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_delete_single_send': {'name': 'mc_singlesends_delete_single_send',
                                       'label': 'Delete Single Send by ID',
                                       'description': '**This endpoint allows you to delete one '
                                                      'Single Send using a Single Send ID.** To '
                                                      "first retrieve all your Single Sends' IDs, "
                                                      'you can make a GET request to the '
                                                      '`/marketing/singlensends` endpoint. Please '
                                                      'note that a `DELETE` request is permanent, '
                                                      'and your Single Send will not be '
                                                      'recoverable after deletion.',
                                       'category': 'Single Sends',
                                       'family': 'mc_singlesends',
                                       'method': 'DELETE',
                                       'path': '/v3/marketing/singlesends/{id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_delete_single_sends': {'name': 'mc_singlesends_delete_single_sends',
                                        'label': 'Bulk Delete Single Sends',
                                        'description': '**This endpoint allows you to delete '
                                                       'multiple Single Sends using an array of '
                                                       'Single Sends IDs.** To first retrieve all '
                                                       "your Single Sends' IDs, you can make a GET "
                                                       'request to the `/marketing/singlensends` '
                                                       'endpoint. Please note that a DELETE '
                                                       'request is permanent, and your Single '
                                                       'Sends will not be recoverable after '
                                                       'deletion.',
                                        'category': 'Single Sends',
                                        'family': 'mc_singlesends',
                                        'method': 'DELETE',
                                        'path': '/v3/marketing/singlesends',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_duplicate_single_send': {'name': 'mc_singlesends_duplicate_single_send',
                                          'label': 'Duplicate Single Send',
                                          'description': '**This endpoint allows you to duplicate '
                                                         'an existing Single Send using its Single '
                                                         'Send ID.** Duplicating a Single Send is '
                                                         'useful when you want to create a Single '
                                                         "Send but don't want to start from "
                                                         'scratch. Once duplicated, you can update '
                                                         'or edit the Single Send by making a '
                                                         'PATCH request to the '
                                                         '`/marketing/singlesends/{id}` endpoint. '
                                                         'If you leave the `name` field blank, '
                                                         'your duplicate will be assigne',
                                          'category': 'Single Sends',
                                          'family': 'mc_singlesends',
                                          'method': 'POST',
                                          'path': '/v3/marketing/singlesends/{id}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': 'application/json',
                                          'regions': ['us'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_get_single_send': {'name': 'mc_singlesends_get_single_send',
                                    'label': 'Get Single Send by ID',
                                    'description': '**This endpoint allows you to retrieve details '
                                                   'about one Single Send using a Single Send '
                                                   'ID.** You can retrieve all of your Single '
                                                   'Sends by making a GET request to the '
                                                   '`/marketing/singlesends` endpoint.',
                                    'category': 'Single Sends',
                                    'family': 'mc_singlesends',
                                    'method': 'GET',
                                    'path': '/v3/marketing/singlesends/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_list_category': {'name': 'mc_singlesends_list_category',
                                  'label': 'Get All Categories',
                                  'description': '**This endpoint allows you to retrieve all the '
                                                 'categories associated with your Single Sends.** '
                                                 'This endpoint will return your latest 1,000 '
                                                 'categories.',
                                  'category': 'Single Sends',
                                  'family': 'mc_singlesends',
                                  'method': 'GET',
                                  'path': '/v3/marketing/singlesends/categories',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_list_single_send': {'name': 'mc_singlesends_list_single_send',
                                     'label': 'Get All Single Sends',
                                     'description': '**This endpoint allows you to retrieve all '
                                                    'your Single Sends.** Returns all of your '
                                                    'Single Sends with condensed details about '
                                                    "each, including the Single Sends' IDs. For "
                                                    'more details about an individual Single Send, '
                                                    "pass the Single Send's ID to the "
                                                    '`/marketing/singlesends/{id}` endpoint.',
                                     'category': 'Single Sends',
                                     'family': 'mc_singlesends',
                                     'method': 'GET',
                                     'path': '/v3/marketing/singlesends',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_schedule_single_send': {'name': 'mc_singlesends_schedule_single_send',
                                         'label': 'Schedule Single Send',
                                         'description': '**This endpoint allows you to send a '
                                                        'Single Send immediately or schedule it to '
                                                        'be sent at a later time.** To send your '
                                                        'message immediately, set the `send_at` '
                                                        'property value to the string `now`. To '
                                                        'schedule the Single Send for future '
                                                        'delivery, set the `send_at` value to your '
                                                        'desired send time in [ISO 8601 date time '
                                                        'format](https://www.iso.org/iso-8601-date-and-time-format.html) '
                                                        '(`yyyy-MM-ddTHH:mm:s',
                                         'category': 'Single Sends',
                                         'family': 'mc_singlesends',
                                         'method': 'PUT',
                                         'path': '/v3/marketing/singlesends/{id}/schedule',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': 'application/json',
                                         'regions': ['us'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_search_single_send': {'name': 'mc_singlesends_search_single_send',
                                       'label': 'Get Single Sends Search',
                                       'description': '**This endpoint allows you to search for '
                                                      'Single Sends based on specified criteria.** '
                                                      'You can search for Single Sends by passing '
                                                      'a combination of values using the `name`, '
                                                      '`status`, and `categories` request body '
                                                      'fields. For example, if you want to search '
                                                      'for all Single Sends that are "drafts" or '
                                                      '"scheduled" and also associated with the '
                                                      'category "shoes," your request body may '
                                                      'look like the example be',
                                       'category': 'Single Sends',
                                       'family': 'mc_singlesends',
                                       'method': 'POST',
                                       'path': '/v3/marketing/singlesends/search',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_singlesends_update_single_send': {'name': 'mc_singlesends_update_single_send',
                                       'label': 'Update Single Send',
                                       'description': '**This endpoint allows you to update a '
                                                      'Single Send using a Single Send ID.** You '
                                                      'only need to pass the properties you want '
                                                      'to update. Any blank or missing properties '
                                                      'will remain unaltered. This endpoint will '
                                                      'update a draft of the Single Send but will '
                                                      'not send it or schedule it to be sent. Any '
                                                      '`send_at` property value set with this '
                                                      "endpoint will prepopulate the Single Send's "
                                                      'send date. However, the',
                                       'category': 'Single Sends',
                                       'family': 'mc_singlesends',
                                       'method': 'PATCH',
                                       'path': '/v3/marketing/singlesends/{id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_singlesends_v3.json'},
 'mc_stats_export_automation_stat': {'name': 'mc_stats_export_automation_stat',
                                     'label': 'Export Single Send Stats',
                                     'description': '**This endpoint allows you to export Single '
                                                    'Send stats as .CSV data**. You can specify '
                                                    'one Single Send or many: include as many '
                                                    'Single Send IDs as you need, separating them '
                                                    'with commas, as the value of the `ids` query '
                                                    'string parameter. The data is returned as '
                                                    'plain text response but in .CSV format, so '
                                                    'your application making the call can present '
                                                    'the information in whatever way is most '
                                                    'appropriate,',
                                     'category': 'Stats',
                                     'family': 'mc_stats',
                                     'method': 'GET',
                                     'path': '/v3/marketing/stats/automations/export',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_export_single_send_stat': {'name': 'mc_stats_export_single_send_stat',
                                      'label': 'Export Single Send Stats',
                                      'description': '**This endpoint allows you to export Single '
                                                     'Send stats as .CSV data**. You can specify '
                                                     'one Single Send or many: include as many '
                                                     'Single Send IDs as you need, separating them '
                                                     'with commas, as the value of the `ids` query '
                                                     'string parameter. The data is returned as '
                                                     'plain text response but in .CSV format, so '
                                                     'your application making the call can present '
                                                     'the information in whatever way is most '
                                                     'appropriate,',
                                      'category': 'Stats',
                                      'family': 'mc_stats',
                                      'method': 'GET',
                                      'path': '/v3/marketing/stats/singlesends/export',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_get_automation_stat': {'name': 'mc_stats_get_automation_stat',
                                  'label': 'Get Automation Stats by ID',
                                  'description': '**This endpoint allows you to retrieve stats for '
                                                 'a single Automation using its ID.** Multiple '
                                                 'Automation IDs can be retrieved using the "Get '
                                                 'All Automation Stats" endpoint. Once you have an '
                                                 'ID, this endpoint will return detailed stats for '
                                                 'the single automation specified. You may '
                                                 'constrain the stats returned using the '
                                                 '`start_date` and `end_date` query string '
                                                 'parameters. You can also use the `group_',
                                  'category': 'Stats',
                                  'family': 'mc_stats',
                                  'method': 'GET',
                                  'path': '/v3/marketing/stats/automations/{id}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_get_single_send_stat': {'name': 'mc_stats_get_single_send_stat',
                                   'label': 'Get Single Send Stats by ID',
                                   'description': '**This endpoint allows you to retrieve stats '
                                                  'for an individual Single Send using a Single '
                                                  'Send ID.** Multiple Single Send IDs can be '
                                                  'retrieved using the "Get All Single Sends '
                                                  'Stats" endpoint. Once you have an ID, this '
                                                  'endpoint will return detailed stats for the '
                                                  'Single Send specified. You may constrain the '
                                                  'stats returned using the `start_date` and '
                                                  '`end_date` query string parameters. You can '
                                                  'also us',
                                   'category': 'Stats',
                                   'family': 'mc_stats',
                                   'method': 'GET',
                                   'path': '/v3/marketing/stats/singlesends/{id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_list_automation_stat': {'name': 'mc_stats_list_automation_stat',
                                   'label': 'Get All Automation Stats',
                                   'description': '**This endpoint allows you to retrieve stats '
                                                  'for all your Automations.** By default, all of '
                                                  'your Automations will be returned, but you can '
                                                  'specify a selection by passing in a '
                                                  'comma-separated list of Automation IDs as the '
                                                  'value of the query string parameter '
                                                  '`automation_ids`. Responses are paginated. You '
                                                  'can limit the number of responses returned per '
                                                  'batch using the `page_size` query string '
                                                  'paramete',
                                   'category': 'Stats',
                                   'family': 'mc_stats',
                                   'method': 'GET',
                                   'path': '/v3/marketing/stats/automations',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_list_click_tracking_stat': {'name': 'mc_stats_list_click_tracking_stat',
                                       'label': 'Get Automation Click Tracking Stats by ID',
                                       'description': '**This endpoint lets you retrieve '
                                                      'click-tracking stats for a single '
                                                      'Automation**. The stats returned list the '
                                                      'URLs embedded in your Automation and the '
                                                      'number of clicks each one received.',
                                       'category': 'Stats',
                                       'family': 'mc_stats',
                                       'method': 'GET',
                                       'path': '/v3/marketing/stats/automations/{id}/links',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_list_single_send_stat': {'name': 'mc_stats_list_single_send_stat',
                                    'label': 'Get All Single Sends Stats',
                                    'description': '**This endpoint allows you to retrieve stats '
                                                   'for all your Single Sends.** By default, all '
                                                   'of your Single Sends will be returned, but you '
                                                   'can specify a selection by passing in a '
                                                   'comma-separated list of Single Send IDs as the '
                                                   'value of the query string parameter '
                                                   '`singlesend_ids`. Responses are paginated. You '
                                                   'can limit the number of responses returned per '
                                                   'batch using the `page_size` query string param',
                                    'category': 'Stats',
                                    'family': 'mc_stats',
                                    'method': 'GET',
                                    'path': '/v3/marketing/stats/singlesends',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_stats_list_single_send_tracking_stat': {'name': 'mc_stats_list_single_send_tracking_stat',
                                             'label': 'Get Single Send Click Tracking Stats by ID',
                                             'description': '**This endpoint lets you retrieve '
                                                            'click-tracking stats for one Single '
                                                            'Send**. The stats returned list the '
                                                            'URLs embedded in the specified Single '
                                                            'Send and the number of clicks each '
                                                            'one received.',
                                             'category': 'Stats',
                                             'family': 'mc_stats',
                                             'method': 'GET',
                                             'path': '/v3/marketing/stats/singlesends/{id}/links',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': None,
                                             'regions': ['us'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_stats_v3.json'},
 'mc_test_send_test_marketing_email': {'name': 'mc_test_send_test_marketing_email',
                                       'label': 'Send a Test Marketing Email',
                                       'description': '**This endpoint allows you to send a test '
                                                      'marketing email to a list of email '
                                                      'addresses**. Before sending a marketing '
                                                      'message, you can test it using this '
                                                      'endpoint. You may specify up to **10 '
                                                      'contacts** in the `emails` request body '
                                                      'field. You must also specify a '
                                                      '`template_id` and include either a '
                                                      '`from_address` or `sender_id`. You can '
                                                      'manage your templates with the [Twilio '
                                                      'SendGrid App](https://mc.s',
                                       'category': 'Send Test Email',
                                       'family': 'mc_test',
                                       'method': 'POST',
                                       'path': '/v3/marketing/test/send_email',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mc_test_v3.json'},
 'partner_list_partner_setting': {'name': 'partner_list_partner_setting',
                                  'label': 'Returns a list of all partner settings',
                                  'description': '**This endpoint allows you to retrieve a '
                                                 'paginated list of all partner settings that you '
                                                 'can enable.** You can use the `limit` query '
                                                 'parameter to set the page size. If your list '
                                                 'contains more items than the page size permits, '
                                                 'you can make multiple requests. Use the `offset` '
                                                 'query parameter to control the position in the '
                                                 'list from which to start retrieving additional '
                                                 "items.'",
                                  'category': 'Partner Settings',
                                  'family': 'partner',
                                  'method': 'GET',
                                  'path': '/v3/partner_settings',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_partner_v3.json'},
 'recipients_data_erasure_erase_recipient_email_data': {'name': 'recipients_data_erasure_erase_recipient_email_data',
                                                        'label': "Erase recipients' email data",
                                                        'description': '**This operation allows '
                                                                       'you to delete your '
                                                                       "recipients' personal email "
                                                                       'data** The Delete '
                                                                       "Recipients' Email Data "
                                                                       'operation accepts a list '
                                                                       'of 5,000 `email_addresses` '
                                                                       'or a total payload size of '
                                                                       '256Kb per request, '
                                                                       'whichever comes first. '
                                                                       'Upon a successful request '
                                                                       'with this operation, '
                                                                       'SendGrid will run a search '
                                                                       'on the email addresses '
                                                                       'provided against the '
                                                                       'SendGrid system to '
                                                                       'identify matches. SendGrid '
                                                                       'will',
                                                        'category': 'Point Delete System',
                                                        'family': 'recipients_data_erasure',
                                                        'method': 'POST',
                                                        'path': '/v3/recipients/erasejob',
                                                        'required_params': [],
                                                        'body_required': True,
                                                        'body_type': 'application/json',
                                                        'regions': ['us', 'eu'],
                                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_recipients_data_erasure_v3.json'},
 'reverse_dns_delete_reverse_dns': {'name': 'reverse_dns_delete_reverse_dns',
                                    'label': 'Delete a reverse DNS record',
                                    'description': '**This endpoint allows you to delete a reverse '
                                                   'DNS record.** A call to this endpoint will '
                                                   'respond with a 204 status code if the deletion '
                                                   'was successful. You can retrieve the IDs '
                                                   'associated with all your reverse DNS records '
                                                   'using the "Retrieve all reverse DNS records" '
                                                   'endpoint.',
                                    'category': 'Reverse DNS',
                                    'family': 'reverse_dns',
                                    'method': 'DELETE',
                                    'path': '/v3/whitelabel/ips/{id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us', 'eu'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_reverse_dns_v3.json'},
 'reverse_dns_get_reverse_dns': {'name': 'reverse_dns_get_reverse_dns',
                                 'label': 'Retrieve a reverse DNS record',
                                 'description': '**This endpoint allows you to retrieve a reverse '
                                                'DNS record.** You can retrieve the IDs associated '
                                                'with all your reverse DNS records using the '
                                                '"Retrieve all reverse DNS records" endpoint.',
                                 'category': 'Reverse DNS',
                                 'family': 'reverse_dns',
                                 'method': 'GET',
                                 'path': '/v3/whitelabel/ips/{id}',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_reverse_dns_v3.json'},
 'reverse_dns_list_reverse_dns': {'name': 'reverse_dns_list_reverse_dns',
                                  'label': 'Retrieve all reverse DNS records',
                                  'description': '**This endpoint allows you to retrieve a '
                                                 'paginated list of all the Reverse DNS records '
                                                 'created by this account.** You may include a '
                                                 'search key by using the `ip` query string '
                                                 'parameter. This enables you to perform a prefix '
                                                 'search for a given IP segment (e.g., '
                                                 '`?ip="192."`). You can use the `limit` query '
                                                 'parameter to set the page size. If your list '
                                                 'contains more items than the page size permits, '
                                                 'you',
                                  'category': 'Reverse DNS',
                                  'family': 'reverse_dns',
                                  'method': 'GET',
                                  'path': '/v3/whitelabel/ips',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_reverse_dns_v3.json'},
 'reverse_dns_set_up_reverse_dns': {'name': 'reverse_dns_set_up_reverse_dns',
                                    'label': 'Set up reverse DNS',
                                    'description': '**This endpoint allows you to set up reverse '
                                                   'DNS.**',
                                    'category': 'Reverse DNS',
                                    'family': 'reverse_dns',
                                    'method': 'POST',
                                    'path': '/v3/whitelabel/ips',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': 'application/json',
                                    'regions': ['us', 'eu'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_reverse_dns_v3.json'},
 'reverse_dns_validate_reverse_dns': {'name': 'reverse_dns_validate_reverse_dns',
                                      'label': 'Validate a reverse DNS record',
                                      'description': '**This endpoint allows you to validate a '
                                                     'reverse DNS record.** Always check the '
                                                     '`valid` property of the response’s '
                                                     '`validation_results.a_record` object. This '
                                                     'field will indicate whether it was possible '
                                                     'to validate the reverse DNS record. If the '
                                                     '`validation_results.a_record.valid` is '
                                                     '`false`, this indicates only that Twilio '
                                                     'SendGrid could not determine the validity '
                                                     'your reverse DNS record — it may ',
                                      'category': 'Reverse DNS',
                                      'family': 'reverse_dns',
                                      'method': 'POST',
                                      'path': '/v3/whitelabel/ips/{id}/validate',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_reverse_dns_v3.json'},
 'scheduled_sends_create_scheduled_send': {'name': 'scheduled_sends_create_scheduled_send',
                                           'label': 'Cancel or pause a scheduled send',
                                           'description': '**This endpoint allows you to cancel or '
                                                          'pause a scheduled send associated with '
                                                          'a `batch_id`.** Passing this endpoint a '
                                                          '`batch_id` and status will cancel or '
                                                          'pause the scheduled send. Once a '
                                                          'scheduled send is set to `pause` or '
                                                          '`cancel` you must use the "Update a '
                                                          'scheduled send" endpoint to change its '
                                                          'status or the "Delete a cancellation or '
                                                          'pause from a scheduled send" endpoint '
                                                          'to remove the status. ',
                                           'category': 'Scheduled Sends',
                                           'family': 'scheduled_sends',
                                           'method': 'POST',
                                           'path': '/v3/user/scheduled_sends',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': 'application/json',
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_scheduled_sends_v3.json'},
 'scheduled_sends_delete_scheduled_send': {'name': 'scheduled_sends_delete_scheduled_send',
                                           'label': 'Delete a cancellation or pause from a '
                                                    'scheduled send',
                                           'description': '**This endpoint allows you to delete '
                                                          'the cancellation/pause of a scheduled '
                                                          'send.** Scheduled sends cancelled less '
                                                          'than 10 minutes before the scheduled '
                                                          'time are not guaranteed to be '
                                                          'cancelled.',
                                           'category': 'Scheduled Sends',
                                           'family': 'scheduled_sends',
                                           'method': 'DELETE',
                                           'path': '/v3/user/scheduled_sends/{batch_id}',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': None,
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_scheduled_sends_v3.json'},
 'scheduled_sends_get_scheduled_send': {'name': 'scheduled_sends_get_scheduled_send',
                                        'label': 'Retrieve scheduled send',
                                        'description': '**This endpoint allows you to retrieve the '
                                                       'cancel/paused scheduled send information '
                                                       'for a specific `batch_id`.**',
                                        'category': 'Scheduled Sends',
                                        'family': 'scheduled_sends',
                                        'method': 'GET',
                                        'path': '/v3/user/scheduled_sends/{batch_id}',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_scheduled_sends_v3.json'},
 'scheduled_sends_list_scheduled_send': {'name': 'scheduled_sends_list_scheduled_send',
                                         'label': 'Retrieve all scheduled sends',
                                         'description': '**This endpoint allows you to retrieve '
                                                        'all cancelled and paused scheduled send '
                                                        'information.** This endpoint will return '
                                                        'only the scheduled sends that are '
                                                        'associated with a `batch_id`. If you have '
                                                        'scheduled a send using the `/mail/send` '
                                                        'endpoint and the `send_at` field but no '
                                                        '`batch_id`, the send will be scheduled '
                                                        'for delivery; however, it will not be '
                                                        'returned by this endpoint. For this '
                                                        'reason, you',
                                         'category': 'Scheduled Sends',
                                         'family': 'scheduled_sends',
                                         'method': 'GET',
                                         'path': '/v3/user/scheduled_sends',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_scheduled_sends_v3.json'},
 'scheduled_sends_update_scheduled_send': {'name': 'scheduled_sends_update_scheduled_send',
                                           'label': 'Update a scheduled send',
                                           'description': '**This endpoint allows you to update '
                                                          'the status of a scheduled send for the '
                                                          'given `batch_id`.** If you have already '
                                                          'set a `cancel` or `pause` status on a '
                                                          'scheduled send using the "Cancel or '
                                                          'pause a scheduled send" endpoint, you '
                                                          "can update it's status using this "
                                                          'endpoint. Attempting to update a status '
                                                          'once it has been set with the "Cancel '
                                                          'or pause a scheduled send" endpoint '
                                                          'will result in a `400` e',
                                           'category': 'Scheduled Sends',
                                           'family': 'scheduled_sends',
                                           'method': 'PATCH',
                                           'path': '/v3/user/scheduled_sends/{batch_id}',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': 'application/json',
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_scheduled_sends_v3.json'},
 'scopes_list_scope': {'name': 'scopes_list_scope',
                       'label': 'Retrieve a list of scopes for which this user has access',
                       'description': '**This endpoint returns a list of all scopes that this user '
                                      'has access to.** API Keys are used to authenticate with '
                                      "[SendGrid's v3 "
                                      'API](https://docs.sendgrid.com/api-reference/how-to-use-the-sendgrid-v3-api/authorization). '
                                      'API Keys may be assigned certain permissions, or scopes, '
                                      'that limit which API endpoints they are able to access. '
                                      'This endpoint returns all the scopes assigned to the key '
                                      'you use',
                       'category': 'Scopes',
                       'family': 'scopes',
                       'method': 'GET',
                       'path': '/v3/scopes',
                       'required_params': [],
                       'body_required': False,
                       'body_type': None,
                       'regions': ['us', 'eu'],
                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_scopes_v3.json'},
 'send_email': {'name': 'send_email',
                'label': 'Send Email with Twilio SendGrid',
                'description': "*The Mail Send operation allows you to send email over SendGrid's "
                               'v3 Web API* For an overview of this API, including its features '
                               'and limitations, please see the [Mail Send API overview '
                               'page](https://www.twilio.com/docs/sendgrid/api-reference/mail-send) '
                               "The overview page also includes links to SendGrid's Email API "
                               'quickstarts and helper libraries to get you working with this '
                               'endpoint even faster.',
                'category': 'Mail Send',
                'family': 'mail',
                'method': 'POST',
                'path': '/v3/mail/send',
                'required_params': [],
                'body_required': False,
                'body_type': 'application/json',
                'regions': ['us', 'eu'],
                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_mail_v3.json'},
 'seq_list_engagement_quality_score': {'name': 'seq_list_engagement_quality_score',
                                       'label': 'Get Engagement Quality Scores',
                                       'description': '**This operation allows you to retrieve '
                                                      'your SendGrid Engagement Quality (SEQ) '
                                                      'scores for a specified date range**. A '
                                                      'successful request with this API operation '
                                                      'will return either a `200` or `202` '
                                                      'response. ### 202 This operation returns a '
                                                      '`202` response when SendGrid does not yet '
                                                      'have scores available for the specified '
                                                      'date range. Scores are calculated '
                                                      'asynchronously from requests to this '
                                                      'endpoin',
                                       'category': 'Engagement Quality',
                                       'family': 'seq',
                                       'method': 'GET',
                                       'path': '/v3/engagementquality/scores',
                                       'required_params': [{'name': 'from', 'in': 'query'},
                                                           {'name': 'to', 'in': 'query'}],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_seq_v3.json'},
 'seq_list_subuser_engagement_quality_score': {'name': 'seq_list_subuser_engagement_quality_score',
                                               'label': "Get Subusers' Engagement Quality Scores",
                                               'description': '**This operation allows you to '
                                                              'retrieve SendGrid Engagement '
                                                              'Quality (SEQ) scores for your '
                                                              'Subusers or customer accounts for a '
                                                              'specific date.** A successful '
                                                              'request with this API operation '
                                                              'will return either a `200` or `202` '
                                                              'response. ### 202 This operation '
                                                              'returns a `202` response when '
                                                              'SendGrid does not yet have scores '
                                                              'available for the specified date '
                                                              'range. Scores are calculated '
                                                              'asynchronously fr',
                                               'category': 'Engagement Quality',
                                               'family': 'seq',
                                               'method': 'GET',
                                               'path': '/v3/engagementquality/subusers/scores',
                                               'required_params': [{'name': 'date', 'in': 'query'}],
                                               'body_required': False,
                                               'body_type': None,
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_seq_v3.json'},
 'sso_create_sso_certificate': {'name': 'sso_create_sso_certificate',
                                'label': 'Create an SSO Certificate',
                                'description': '**This endpoint allows you to create an SSO '
                                               'certificate.**',
                                'category': 'SSO Certificates',
                                'family': 'sso',
                                'method': 'POST',
                                'path': '/v3/sso/certificates',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_create_sso_integration': {'name': 'sso_create_sso_integration',
                                'label': 'Create an SSO Integration',
                                'description': '**This endpoint allows you to create an SSO '
                                               'integration.**',
                                'category': 'SSO Settings',
                                'family': 'sso',
                                'method': 'POST',
                                'path': '/v3/sso/integrations',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_create_sso_teammate': {'name': 'sso_create_sso_teammate',
                             'label': 'Create an SSO Teammate',
                             'description': '**This endpoint allows you to create an SSO '
                                            'Teammate.** The email address provided for the '
                                            "Teammate will also function as the Teammate's "
                                            "username. Once created, the Teammate's email address "
                                            'cannot be changed. ### Scopes When creating a '
                                            'Teammate, you will assign it permissions or scopes. '
                                            'These scopes determine which actions the Teammate can '
                                            'perform and which features they can access. Scopes '
                                            'are pro',
                             'category': 'SSO Teammates',
                             'family': 'sso',
                             'method': 'POST',
                             'path': '/v3/sso/teammates',
                             'required_params': [],
                             'body_required': False,
                             'body_type': 'application/json',
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_delete_sso_certificate': {'name': 'sso_delete_sso_certificate',
                                'label': 'Delete an SSO Certificate',
                                'description': '**This endpoint allows you to delete an SSO '
                                               "certificate.** You can retrieve a certificate's ID "
                                               'from the response provided by the "Get All SSO '
                                               'Integrations" endpoint.',
                                'category': 'SSO Certificates',
                                'family': 'sso',
                                'method': 'DELETE',
                                'path': '/v3/sso/certificates/{cert_id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_delete_sso_integration': {'name': 'sso_delete_sso_integration',
                                'label': 'Delete an SSO Integration',
                                'description': '**This endpoint allows you to delete an IdP '
                                               'configuration by ID.** You can retrieve the IDs '
                                               'for your configurations from the response provided '
                                               'by the "Get All SSO Integrations" endpoint.',
                                'category': 'SSO Settings',
                                'family': 'sso',
                                'method': 'DELETE',
                                'path': '/v3/sso/integrations/{id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_get_sso_certificate': {'name': 'sso_get_sso_certificate',
                             'label': 'Get an SSO Certificate',
                             'description': '**This endpoint allows you to retrieve an individual '
                                            'SSO certificate.**',
                             'category': 'SSO Certificates',
                             'family': 'sso',
                             'method': 'GET',
                             'path': '/v3/sso/certificates/{cert_id}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_get_sso_integration': {'name': 'sso_get_sso_integration',
                             'label': 'Get an SSO Integration',
                             'description': '**This endpoint allows you to retrieve an SSO '
                                            'integration by ID.** You can retrieve the IDs for '
                                            'your configurations from the response provided by the '
                                            '"Get All SSO Integrations" endpoint.',
                             'category': 'SSO Settings',
                             'family': 'sso',
                             'method': 'GET',
                             'path': '/v3/sso/integrations/{id}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_list_sso_integration': {'name': 'sso_list_sso_integration',
                              'label': 'Get All SSO Integrations',
                              'description': '**This endpoint allows you to retrieve all SSO '
                                             'integrations tied to your Twilio SendGrid account.** '
                                             'The IDs returned by this endpoint can be used by the '
                                             'APIs additional endpoints to modify your SSO '
                                             'integrations.',
                              'category': 'SSO Settings',
                              'family': 'sso',
                              'method': 'GET',
                              'path': '/v3/sso/integrations',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_list_sso_integration_certificate': {'name': 'sso_list_sso_integration_certificate',
                                          'label': 'Get All SSO Certificates by Integration',
                                          'description': '**This endpoint allows you to retrieve '
                                                         'all your IdP configurations by '
                                                         'configuration ID.** The `integration_id` '
                                                         'expected by this endpoint is the `id` '
                                                         'returned in the response by the "Get All '
                                                         'SSO Integrations" endpoint.',
                                          'category': 'SSO Certificates',
                                          'family': 'sso',
                                          'method': 'GET',
                                          'path': '/v3/sso/integrations/{integration_id}/certificates',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_update_sso_certificate': {'name': 'sso_update_sso_certificate',
                                'label': 'Update SSO Certificate',
                                'description': '**This endpoint allows you to update an existing '
                                               'certificate by ID.** You can retrieve a '
                                               "certificate's ID from the response provided by the "
                                               '"Get All SSO Integrations" endpoint.',
                                'category': 'SSO Certificates',
                                'family': 'sso',
                                'method': 'PATCH',
                                'path': '/v3/sso/certificates/{cert_id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_update_sso_integration': {'name': 'sso_update_sso_integration',
                                'label': 'Update an SSO Integration',
                                'description': '**This endpoint allows you to modify an exisiting '
                                               'SSO integration.** You can retrieve the IDs for '
                                               'your configurations from the response provided by '
                                               'the "Get All SSO Integrations" endpoint.',
                                'category': 'SSO Settings',
                                'family': 'sso',
                                'method': 'PATCH',
                                'path': '/v3/sso/integrations/{id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'sso_update_sso_teammate': {'name': 'sso_update_sso_teammate',
                             'label': 'Edit an SSO Teammate',
                             'description': '**This endpoint allows you to modify an existing SSO '
                                            'Teammate.** Only the parent user and Teammates with '
                                            "admin permissions can update another Teammate's "
                                            'permissions. ### Scopes When updating a Teammate, you '
                                            'will assign it permissions or scopes. These scopes '
                                            'determine which actions the Teammate can perform and '
                                            'which features they can access. Scopes are provided '
                                            'with one of three properties passed t',
                             'category': 'SSO Teammates',
                             'family': 'sso',
                             'method': 'PATCH',
                             'path': '/v3/sso/teammates/{username}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': 'application/json',
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_sso_v3.json'},
 'stats_get_client_stat': {'name': 'stats_get_client_stat',
                           'label': 'Retrieve stats by a specific client type',
                           'description': '**This endpoint allows you to retrieve your email '
                                          'statistics segmented by a specific client type.** **We '
                                          'only store up to 7 days of email activity in our '
                                          'database.** By default, 500 items will be returned per '
                                          'request via the Advanced Stats API endpoints. ### '
                                          'Available Client Types - phone - tablet - webmail - '
                                          'desktop Advanced Stats provide a more in-depth view of '
                                          'your email statistics and the acti',
                           'category': 'Stats',
                           'family': 'stats',
                           'method': 'GET',
                           'path': '/v3/clients/{client_type}/stats',
                           'required_params': [{'name': 'start_date', 'in': 'query'}],
                           'body_required': False,
                           'body_type': None,
                           'regions': ['us', 'eu'],
                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_browser_stat': {'name': 'stats_list_browser_stat',
                             'label': 'Retrieve email statistics by browser',
                             'description': '**This endpoint allows you to retrieve your email '
                                            'statistics segmented by browser type.** **We only '
                                            'store up to 7 days of email activity in our '
                                            'database.** By default, 500 items will be returned '
                                            'per request via the Advanced Stats API endpoints. '
                                            'Advanced Stats provide a more in-depth view of your '
                                            'email statistics and the actions taken by your '
                                            'recipients. You can segment these statistics by '
                                            'geograph',
                             'category': 'Stats',
                             'family': 'stats',
                             'method': 'GET',
                             'path': '/v3/browsers/stats',
                             'required_params': [{'name': 'start_date', 'in': 'query'}],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_category': {'name': 'stats_list_category',
                         'label': 'Retrieve all categories',
                         'description': '**This endpoint allows you to retrieve a paginated list '
                                        'of all of your categories.** You can use the `limit` '
                                        'query parameter to set the page size. If your list '
                                        'contains more items than the page size permits, you can '
                                        'make multiple requests. Use the `offset` query parameter '
                                        'to control the position in the list from which to start '
                                        'retrieving additional items.',
                         'category': 'Categories',
                         'family': 'stats',
                         'method': 'GET',
                         'path': '/v3/categories',
                         'required_params': [],
                         'body_required': False,
                         'body_type': None,
                         'regions': ['us', 'eu'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_category_stat': {'name': 'stats_list_category_stat',
                              'label': 'Retrieve Email Statistics for Categories',
                              'description': '**This endpoint allows you to retrieve all of your '
                                             'email statistics for each of your categories.** If '
                                             'you do not define any query parameters, this '
                                             'endpoint will return a sum for each category in '
                                             'groups of 10.',
                              'category': 'Categories',
                              'family': 'stats',
                              'method': 'GET',
                              'path': '/v3/categories/stats',
                              'required_params': [{'name': 'start_date', 'in': 'query'},
                                                  {'name': 'categories', 'in': 'query'}],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_category_stat_sum': {'name': 'stats_list_category_stat_sum',
                                  'label': 'Retrieve sums of email stats for each category',
                                  'description': '**This endpoint allows you to retrieve the total '
                                                 'sum of each email statistic for every category '
                                                 'over the given date range.** If you do not '
                                                 'define any query parameters, this endpoint will '
                                                 'return a sum for each category in groups of 10.',
                                  'category': 'Categories',
                                  'family': 'stats',
                                  'method': 'GET',
                                  'path': '/v3/categories/stats/sums',
                                  'required_params': [{'name': 'start_date', 'in': 'query'}],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_client_stat': {'name': 'stats_list_client_stat',
                            'label': 'Retrieve email statistics by client type',
                            'description': '**This endpoint allows you to retrieve your email '
                                           'statistics segmented by client type.** **We only store '
                                           'up to 7 days of email activity in our database.** By '
                                           'default, 500 items will be returned per request via '
                                           'the Advanced Stats API endpoints. Advanced Stats '
                                           'provide a more in-depth view of your email statistics '
                                           'and the actions taken by your recipients. You can '
                                           'segment these statistics by geographi',
                            'category': 'Stats',
                            'family': 'stats',
                            'method': 'GET',
                            'path': '/v3/clients/stats',
                            'required_params': [{'name': 'start_date', 'in': 'query'}],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_device_stat': {'name': 'stats_list_device_stat',
                            'label': 'Retrieve email statistics by device type',
                            'description': '**This endpoint allows you to retrieve your email '
                                           'statistics segmented by the device type.** **We only '
                                           'store up to 7 days of email activity in our '
                                           'database.** By default, 500 items will be returned per '
                                           'request via the Advanced Stats API endpoints. ## '
                                           'Available Device Types | **Device** | **Description** '
                                           '| **Example** | |---|---|---| | Desktop | Email '
                                           'software on desktop computer. | I.E., Outlook, ',
                            'category': 'Stats',
                            'family': 'stats',
                            'method': 'GET',
                            'path': '/v3/devices/stats',
                            'required_params': [{'name': 'start_date', 'in': 'query'}],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_geo_stat': {'name': 'stats_list_geo_stat',
                         'label': 'Retrieve email statistics by country and state/province',
                         'description': '**This endpoint allows you to retrieve your email '
                                        'statistics segmented by country and state/province.** '
                                        '**We only store up to 7 days of email activity in our '
                                        'database.** By default, 500 items will be returned per '
                                        'request via the Advanced Stats API endpoints. For '
                                        'Regional (EU) subusers, this service is not available due '
                                        'to PII restrictions. Advanced Stats provide a more '
                                        'in-depth view of your email ',
                         'category': 'Stats',
                         'family': 'stats',
                         'method': 'GET',
                         'path': '/v3/geo/stats',
                         'required_params': [{'name': 'start_date', 'in': 'query'}],
                         'body_required': False,
                         'body_type': None,
                         'regions': ['us'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_mailbox_provider_stat': {'name': 'stats_list_mailbox_provider_stat',
                                      'label': 'Retrieve email statistics by mailbox provider',
                                      'description': '**This endpoint allows you to retrieve your '
                                                     'email statistics segmented by recipient '
                                                     'mailbox provider.** **We only store up to 7 '
                                                     'days of email activity in our database.** By '
                                                     'default, 500 items will be returned per '
                                                     'request via the Advanced Stats API '
                                                     'endpoints. Advanced Stats provide a more '
                                                     'in-depth view of your email statistics and '
                                                     'the actions taken by your recipients. You '
                                                     'can segment these statisti',
                                      'category': 'Stats',
                                      'family': 'stats',
                                      'method': 'GET',
                                      'path': '/v3/mailbox_providers/stats',
                                      'required_params': [{'name': 'start_date', 'in': 'query'}],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'stats_list_stat': {'name': 'stats_list_stat',
                     'label': 'Retrieve global email statistics',
                     'description': '**This endpoint allows you to retrieve all of your global '
                                    'email statistics between a given date range.** Parent '
                                    'accounts can see either aggregated stats for the parent '
                                    'account or aggregated stats for a subuser specified in the '
                                    '`on-behalf-of` header. Subuser accounts will see only their '
                                    'own stats.',
                     'category': 'Stats',
                     'family': 'stats',
                     'method': 'GET',
                     'path': '/v3/stats',
                     'required_params': [{'name': 'start_date', 'in': 'query'}],
                     'body_required': False,
                     'body_type': None,
                     'regions': ['us', 'eu'],
                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_stats_v3.json'},
 'subusers_create_subuser': {'name': 'subusers_create_subuser',
                             'label': 'Create Subuser',
                             'description': '**This endpoint allows you to create a new subuser.**',
                             'category': 'Subusers',
                             'family': 'subusers',
                             'method': 'POST',
                             'path': '/v3/subusers',
                             'required_params': [],
                             'body_required': False,
                             'body_type': 'application/json',
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_delete_subuser': {'name': 'subusers_delete_subuser',
                             'label': 'Delete a subuser',
                             'description': '**This endpoint allows you to delete a subuser.** '
                                            'This is a permanent action. Once deleted, a subuser '
                                            'cannot be retrieved.',
                             'category': 'Subusers',
                             'family': 'subusers',
                             'method': 'DELETE',
                             'path': '/v3/subusers/{subuser_name}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_get_subuser_credit': {'name': 'subusers_get_subuser_credit',
                                 'label': 'Get the Credits for a Subuser',
                                 'description': '**This endpoint allows you to retrieve a Credits '
                                                'overview for a Subuser.**',
                                 'category': 'Subusers',
                                 'family': 'subusers',
                                 'method': 'GET',
                                 'path': '/v3/subusers/{subuser_name}/credits',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_list_monthly_stat': {'name': 'subusers_list_monthly_stat',
                                'label': 'Retrieve monthly stats for all subusers',
                                'description': '**This endpoint allows you to retrieve the monthly '
                                               'email statistics for all subusers over the given '
                                               'date range.** When using the `sort_by_metric` to '
                                               'sort your stats by a specific metric, you can not '
                                               'sort by the following metrics: `bounce_drops`, '
                                               '`deferred`, `invalid_emails`, `processed`, '
                                               '`spam_report_drops`, `spam_reports`, or '
                                               '`unsubscribe_drops`.',
                                'category': 'Subuser Statistics',
                                'family': 'subusers',
                                'method': 'GET',
                                'path': '/v3/subusers/stats/monthly',
                                'required_params': [{'name': 'date', 'in': 'query'}],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_list_reputation': {'name': 'subusers_list_reputation',
                              'label': 'Retrieve Subuser Reputations',
                              'description': '**This endpoint allows you to request the '
                                             'reputations for your subusers.** Subuser sender '
                                             'reputations give a good idea how well a sender is '
                                             'doing with regards to how recipients and recipient '
                                             'servers react to the mail that is being received. '
                                             'When a bounce, spam report, or other negative action '
                                             'happens on a sent email, it will affect your sender '
                                             'rating. For Regional (EU) subusers, subuser '
                                             'reputation',
                              'category': 'Subusers',
                              'family': 'subusers',
                              'method': 'GET',
                              'path': '/v3/subusers/reputations',
                              'required_params': [],
                              'body_required': False,
                              'body_type': None,
                              'regions': ['us', 'eu'],
                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_list_stat': {'name': 'subusers_list_stat',
                        'label': 'Retrieve email statistics for your subusers',
                        'description': '**This endpoint allows you to retrieve the email '
                                       'statistics for the given subusers.** You may retrieve '
                                       'statistics for up to 10 different subusers by including an '
                                       'additional _subusers_ parameter for each additional '
                                       'subuser.',
                        'category': 'Subuser Statistics',
                        'family': 'subusers',
                        'method': 'GET',
                        'path': '/v3/subusers/stats',
                        'required_params': [{'name': 'subusers', 'in': 'query'},
                                            {'name': 'start_date', 'in': 'query'}],
                        'body_required': False,
                        'body_type': None,
                        'regions': ['us', 'eu'],
                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_list_stat_sum': {'name': 'subusers_list_stat_sum',
                            'label': 'Retrieve the totals for each email statistic metric for all '
                                     'subusers',
                            'description': '**This endpoint allows you to retrieve the total sums '
                                           'of each email statistic metric for all subusers over '
                                           'the given date range.**',
                            'category': 'Subuser Statistics',
                            'family': 'subusers',
                            'method': 'GET',
                            'path': '/v3/subusers/stats/sums',
                            'required_params': [{'name': 'start_date', 'in': 'query'}],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_list_subuser': {'name': 'subusers_list_subuser',
                           'label': 'List all Subusers',
                           'description': '**This endpoint allows you to retrieve a paginated list '
                                          'of all your subusers.** You can use the `username` '
                                          'query parameter to filter the list for specific '
                                          'subusers. You can use the `limit` query parameter to '
                                          'set the page size. If your list contains more items '
                                          'than the page size permits, you can make multiple '
                                          'requests. Use the `offset` query parameter to control '
                                          'the position in the list from which ',
                           'category': 'Subusers',
                           'family': 'subusers',
                           'method': 'GET',
                           'path': '/v3/subusers',
                           'required_params': [],
                           'body_required': False,
                           'body_type': None,
                           'regions': ['us', 'eu'],
                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_list_subuser_monthly_stat': {'name': 'subusers_list_subuser_monthly_stat',
                                        'label': 'Retrieve the monthly email statistics for a '
                                                 'single subuser',
                                        'description': '**This endpoint allows you to retrive the '
                                                       'monthly email statistics for a specific '
                                                       'subuser.** When using the `sort_by_metric` '
                                                       'to sort your stats by a specific metric, '
                                                       'you can not sort by the following metrics: '
                                                       '`bounce_drops`, `deferred`, '
                                                       '`invalid_emails`, `processed`, '
                                                       '`spam_report_drops`, `spam_reports`, or '
                                                       '`unsubscribe_drops`.',
                                        'category': 'Subuser Statistics',
                                        'family': 'subusers',
                                        'method': 'GET',
                                        'path': '/v3/subusers/{subuser_name}/stats/monthly',
                                        'required_params': [{'name': 'date', 'in': 'query'}],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_update_subuser': {'name': 'subusers_update_subuser',
                             'label': 'Enable/disable a subuser',
                             'description': '**This endpoint allows you to enable or disable a '
                                            'subuser.**',
                             'category': 'Subusers',
                             'family': 'subusers',
                             'method': 'PATCH',
                             'path': '/v3/subusers/{subuser_name}',
                             'required_params': [],
                             'body_required': False,
                             'body_type': 'application/json',
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_update_subuser_credit': {'name': 'subusers_update_subuser_credit',
                                    'label': 'Update the Credits for a Subuser',
                                    'description': '**This endpoint allows you to update the '
                                                   'Credits for a Subuser.**',
                                    'category': 'Subusers',
                                    'family': 'subusers',
                                    'method': 'PUT',
                                    'path': '/v3/subusers/{subuser_name}/credits',
                                    'required_params': [],
                                    'body_required': True,
                                    'body_type': 'application/json',
                                    'regions': ['us', 'eu'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_update_subuser_ip': {'name': 'subusers_update_subuser_ip',
                                'label': 'Update IPs assigned to a subuser',
                                'description': "**This endpoint allows you update your subusers' "
                                               'assigned IP.** Each subuser should be assigned to '
                                               "an IP address from which all of this subuser's "
                                               'mail will be sent. Often, this is the same IP as '
                                               'the parent account, but each subuser can have one '
                                               'or more of their own IP addresses as well. More '
                                               'information: * [How to request more '
                                               'IPs](https://sendgrid.com/docs/ui/account-and-settings/dedicated-ip-add',
                                'category': 'Subusers',
                                'family': 'subusers',
                                'method': 'PUT',
                                'path': '/v3/subusers/{subuser_name}/ips',
                                'required_params': [],
                                'body_required': False,
                                'body_type': 'application/json',
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_update_subuser_remaining_credit': {'name': 'subusers_update_subuser_remaining_credit',
                                              'label': 'Update the remaining credits for a Subuser',
                                              'description': '**This endpoint allows you to update '
                                                             'the remaining credits for a '
                                                             'Subuser.**',
                                              'category': 'Subusers',
                                              'family': 'subusers',
                                              'method': 'PATCH',
                                              'path': '/v3/subusers/{subuser_name}/credits/remaining',
                                              'required_params': [],
                                              'body_required': True,
                                              'body_type': 'application/json',
                                              'regions': ['us', 'eu'],
                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'subusers_update_subuser_website_access': {'name': 'subusers_update_subuser_website_access',
                                            'label': 'Enable/Disable website access for a Subuser',
                                            'description': 'Enable/Disable website access for a '
                                                           'Subuser, while still preserving email '
                                                           'send functionality.',
                                            'category': 'Subuser Website Access',
                                            'family': 'subusers',
                                            'method': 'PATCH',
                                            'path': '/v3/subusers/{subuser_name}/website_access',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': 'application/json',
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_subusers_v3.json'},
 'suppressions_add_suppression_to_asm_group': {'name': 'suppressions_add_suppression_to_asm_group',
                                               'label': 'Add suppressions to a suppression group',
                                               'description': '**This endpoint allows you to add '
                                                              'email addresses to an unsubscribe '
                                                              'group.** If you attempt to add '
                                                              'suppressions to a group that has '
                                                              'been deleted or does not exist, the '
                                                              'suppressions will be added to the '
                                                              'global suppressions list.',
                                               'category': 'Suppressions',
                                               'family': 'suppressions',
                                               'method': 'POST',
                                               'path': '/v3/asm/groups/{group_id}/suppressions',
                                               'required_params': [],
                                               'body_required': False,
                                               'body_type': 'application/json',
                                               'regions': ['us', 'eu'],
                                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_creat_asm_group': {'name': 'suppressions_creat_asm_group',
                                  'label': 'Create a new suppression group',
                                  'description': '**This endpoint allows you to create a new '
                                                 'suppression group.** To add an email address to '
                                                 'the suppression group, [create a '
                                                 'Suppression](https://docs.sendgrid.com/api-reference/suppressions-suppressions/add-suppressions-to-a-suppression-group).',
                                  'category': 'Unsubscribe Groups',
                                  'family': 'suppressions',
                                  'method': 'POST',
                                  'path': '/v3/asm/groups',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': 'application/json',
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_create_global_suppression': {'name': 'suppressions_create_global_suppression',
                                            'label': 'Add recipient addresses to the global '
                                                     'suppression group',
                                            'description': '**This endpoint allows you to add one '
                                                           'or more email addresses to the global '
                                                           'suppressions group.**',
                                            'category': 'Global Suppressions',
                                            'family': 'suppressions',
                                            'method': 'POST',
                                            'path': '/v3/asm/suppressions/global',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': 'application/json',
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_asm_group': {'name': 'suppressions_delete_asm_group',
                                   'label': 'Delete a Suppression Group',
                                   'description': '**This endpoint allows you to delete a '
                                                  'suppression group.** If a recipient uses the '
                                                  '"one-click unsubscribe" option on an email '
                                                  'associated with a deleted group, that recipient '
                                                  'will be added to the global suppression list. '
                                                  'Deleting a suppression group will remove the '
                                                  'suppression, meaning email will once again be '
                                                  'sent to the previously suppressed addresses. '
                                                  'This should be avoided unless a recipient i',
                                   'category': 'Unsubscribe Groups',
                                   'family': 'suppressions',
                                   'method': 'DELETE',
                                   'path': '/v3/asm/groups/{group_id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_global_suppression': {'name': 'suppressions_delete_global_suppression',
                                            'label': 'Delete a Global Suppression',
                                            'description': '**This endpoint allows you to remove '
                                                           'an email address from the global '
                                                           'suppressions group.** Deleting a '
                                                           'suppression group will remove the '
                                                           'suppression, meaning email will once '
                                                           'again be sent to the previously '
                                                           'suppressed addresses. This should be '
                                                           'avoided unless a recipient indicates '
                                                           'they wish to receive email from you '
                                                           'again. You can use our [bypass '
                                                           'filters](https://sendgrid.com/docs/ui/sending-email/i',
                                            'category': 'Global Suppressions',
                                            'family': 'suppressions',
                                            'method': 'DELETE',
                                            'path': '/v3/asm/suppressions/global/{email}',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': None,
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_invalid_email': {'name': 'suppressions_delete_invalid_email',
                                       'label': 'Delete a specific invalid email',
                                       'description': '**This endpoint allows you to remove a '
                                                      'specific email address from the invalid '
                                                      'email address list.**',
                                       'category': 'Invalid Emails',
                                       'family': 'suppressions',
                                       'method': 'DELETE',
                                       'path': '/v3/suppression/invalid_emails/{email}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_invalid_emails': {'name': 'suppressions_delete_invalid_emails',
                                        'label': 'Delete invalid emails',
                                        'description': '**This endpoint allows you to remove email '
                                                       'addresses from your invalid email address '
                                                       'list.** There are two options for deleting '
                                                       'invalid email addresses: 1) You can delete '
                                                       'all invalid email addresses by setting '
                                                       '`delete_all` to true in the request body. '
                                                       '2) You can delete some invalid email '
                                                       'addresses by specifying certain addresses '
                                                       'in an array in the request body.',
                                        'category': 'Invalid Emails',
                                        'family': 'suppressions',
                                        'method': 'DELETE',
                                        'path': '/v3/suppression/invalid_emails',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': 'application/json',
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_spam_report': {'name': 'suppressions_delete_spam_report',
                                     'label': 'Delete a specific spam report',
                                     'description': '**This endpoint allows you to delete a '
                                                    'specific spam report by email address.** '
                                                    'Deleting a spam report will remove the '
                                                    'suppression, meaning email will once again be '
                                                    'sent to the previously suppressed address. '
                                                    'This should be avoided unless a recipient '
                                                    'indicates they wish to receive email from you '
                                                    'again. You can use our [bypass '
                                                    'filters](https://sendgrid.com/docs/ui/sending-email/index-suppressions/#b',
                                     'category': 'Spam Reports',
                                     'family': 'suppressions',
                                     'method': 'DELETE',
                                     'path': '/v3/suppression/spam_reports/{email}',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_spam_reports': {'name': 'suppressions_delete_spam_reports',
                                      'label': 'Delete spam reports',
                                      'description': '**This endpoint allows you to delete your '
                                                     'spam reports.** Deleting a spam report will '
                                                     'remove the suppression, meaning email will '
                                                     'once again be sent to the previously '
                                                     'suppressed address. This should be avoided '
                                                     'unless a recipient indicates they wish to '
                                                     'receive email from you again. You can use '
                                                     'our [bypass '
                                                     'filters](https://sendgrid.com/docs/ui/sending-email/index-suppressions/#bypass-suppressions) '
                                                     'to',
                                      'category': 'Spam Reports',
                                      'family': 'suppressions',
                                      'method': 'DELETE',
                                      'path': '/v3/suppression/spam_reports',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': 'application/json',
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_suppression_block': {'name': 'suppressions_delete_suppression_block',
                                           'label': 'Delete a specific block',
                                           'description': '**This endpoint allows you to delete a '
                                                          'specific email address from your blocks '
                                                          'list.**',
                                           'category': 'Blocks',
                                           'family': 'suppressions',
                                           'method': 'DELETE',
                                           'path': '/v3/suppression/blocks/{email}',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': None,
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_suppression_blocks': {'name': 'suppressions_delete_suppression_blocks',
                                            'label': 'Delete blocks',
                                            'description': '**This endpoint allows you to delete '
                                                           'all email addresses on your blocks '
                                                           'list.** There are two options for '
                                                           'deleting blocked emails: 1. You can '
                                                           'delete all blocked emails by setting '
                                                           '`delete_all` to `true` in the request '
                                                           'body. 2. You can delete a selection of '
                                                           'blocked emails by specifying the email '
                                                           'addresses in the `emails` array of the '
                                                           'request body.',
                                            'category': 'Blocks',
                                            'family': 'suppressions',
                                            'method': 'DELETE',
                                            'path': '/v3/suppression/blocks',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': 'application/json',
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_suppression_bounce': {'name': 'suppressions_delete_suppression_bounce',
                                            'label': 'Delete a bounce',
                                            'description': '**This endpoint allows you to remove '
                                                           'an email address from your bounce '
                                                           'list.**',
                                            'category': 'Bounces',
                                            'family': 'suppressions',
                                            'method': 'DELETE',
                                            'path': '/v3/suppression/bounces/{email}',
                                            'required_params': [],
                                            'body_required': False,
                                            'body_type': None,
                                            'regions': ['us', 'eu'],
                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_suppression_bounces': {'name': 'suppressions_delete_suppression_bounces',
                                             'label': 'Delete bounces',
                                             'description': '**This endpoint allows you to delete '
                                                            'all emails on your bounces list.** '
                                                            'There are two options for deleting '
                                                            'bounced emails: 1. You can delete all '
                                                            'bounced emails by setting '
                                                            '`delete_all` to `true` in the request '
                                                            'body. 2. You can delete a selection '
                                                            'of bounced emails by specifying the '
                                                            'email addresses in the `emails` array '
                                                            'of the request body. **WARNING:** You '
                                                            'can not have both `emails` and '
                                                            '`delete_all`',
                                             'category': 'Bounces',
                                             'family': 'suppressions',
                                             'method': 'DELETE',
                                             'path': '/v3/suppression/bounces',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': 'application/json',
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_delete_suppression_from_asm_group': {'name': 'suppressions_delete_suppression_from_asm_group',
                                                    'label': 'Delete a suppression from a '
                                                             'suppression group',
                                                    'description': '**This endpoint allows you to '
                                                                   'remove a suppressed email '
                                                                   'address from the given '
                                                                   'suppression group.** Removing '
                                                                   'an address will remove the '
                                                                   'suppression, meaning email '
                                                                   'will once again be sent to the '
                                                                   'previously suppressed '
                                                                   'addresses. This should be '
                                                                   'avoided unless a recipient '
                                                                   'indicates they wish to receive '
                                                                   'email from you again. You can '
                                                                   'use our [bypass '
                                                                   'filters](https://sendgrid.com/docs/ui/sending-email/in',
                                                    'category': 'Suppressions',
                                                    'family': 'suppressions',
                                                    'method': 'DELETE',
                                                    'path': '/v3/asm/groups/{group_id}/suppressions/{email}',
                                                    'required_params': [],
                                                    'body_required': False,
                                                    'body_type': None,
                                                    'regions': ['us', 'eu'],
                                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_asm_group': {'name': 'suppressions_get_asm_group',
                                'label': 'Get information on a single suppression group',
                                'description': '**This endpoint allows you to retrieve a single '
                                               'suppression group.**',
                                'category': 'Unsubscribe Groups',
                                'family': 'suppressions',
                                'method': 'GET',
                                'path': '/v3/asm/groups/{group_id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_asm_suppression': {'name': 'suppressions_get_asm_suppression',
                                      'label': 'Retrieve all suppression groups for an email '
                                               'address',
                                      'description': '**This endpoint returns a list of all groups '
                                                     'from which the given email address has been '
                                                     'unsubscribed.**',
                                      'category': 'Suppressions',
                                      'family': 'suppressions',
                                      'method': 'GET',
                                      'path': '/v3/asm/suppressions/{email}',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_global_suppression': {'name': 'suppressions_get_global_suppression',
                                         'label': 'Retrieve a Global Suppression',
                                         'description': '**This endpoint allows you to retrieve a '
                                                        'global suppression. You can also use this '
                                                        'endpoint to confirm if an email address '
                                                        'is already globally suppresed.** If the '
                                                        'email address you include in the URL path '
                                                        'parameter `{email}` is already globally '
                                                        'suppressed, the response will include '
                                                        'that email address. If the address you '
                                                        'enter for `{email}` is not globally '
                                                        'suppressed, an empty JSON object `{}` '
                                                        'will',
                                         'category': 'Global Suppressions',
                                         'family': 'suppressions',
                                         'method': 'GET',
                                         'path': '/v3/asm/suppressions/global/{email}',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_invalid_email': {'name': 'suppressions_get_invalid_email',
                                    'label': 'Retrieve a specific invalid email',
                                    'description': '**This endpoint allows you to retrieve a '
                                                   'specific invalid email addresses.**',
                                    'category': 'Invalid Emails',
                                    'family': 'suppressions',
                                    'method': 'GET',
                                    'path': '/v3/suppression/invalid_emails/{email}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us', 'eu'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_spam_report': {'name': 'suppressions_get_spam_report',
                                  'label': 'Retrieve a specific spam report',
                                  'description': '**This endpoint allows you to retrieve a '
                                                 'specific spam report by email address.**',
                                  'category': 'Spam Reports',
                                  'family': 'suppressions',
                                  'method': 'GET',
                                  'path': '/v3/suppression/spam_reports/{email}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_suppression_block': {'name': 'suppressions_get_suppression_block',
                                        'label': 'Retrieve a specific block',
                                        'description': '**This endpoint allows you to retrieve a '
                                                       'specific email address from your blocks '
                                                       'list.**',
                                        'category': 'Blocks',
                                        'family': 'suppressions',
                                        'method': 'GET',
                                        'path': '/v3/suppression/blocks/{email}',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_suppression_bounces': {'name': 'suppressions_get_suppression_bounces',
                                          'label': 'Retrieve a Bounce',
                                          'description': '**This endpoint allows you to retrieve a '
                                                         'specific bounce by email address.**',
                                          'category': 'Bounces',
                                          'family': 'suppressions',
                                          'method': 'GET',
                                          'path': '/v3/suppression/bounces/{email}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_get_suppression_bounces_classifications': {'name': 'suppressions_get_suppression_bounces_classifications',
                                                          'label': 'Retrieve bounce classification '
                                                                   'over time by domain stats',
                                                          'description': 'This endpoint will '
                                                                         'return the number of '
                                                                         'bounces for the '
                                                                         'classification specified '
                                                                         'in descending order for '
                                                                         'each day. You can '
                                                                         'retrieve the bounce '
                                                                         'classification totals in '
                                                                         'CSV format by specifying '
                                                                         '`"text/csv"` in the '
                                                                         'Accept header.',
                                                          'category': 'Bounces',
                                                          'family': 'suppressions',
                                                          'method': 'GET',
                                                          'path': '/v3/suppression/bounces/classifications/{classification}',
                                                          'required_params': [],
                                                          'body_required': False,
                                                          'body_type': None,
                                                          'regions': ['us', 'eu'],
                                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_asm_group': {'name': 'suppressions_list_asm_group',
                                 'label': 'Retrieve all suppression groups associated with the '
                                          'user',
                                 'description': '**This endpoint allows you to retrieve a list of '
                                                'all suppression groups created by this user.** '
                                                'This endpoint can also return information for '
                                                'multiple group IDs that you include in your '
                                                'request. To add a group ID to your request, '
                                                'simply append `?id=123456&id=123456`, with the '
                                                'appropriate group IDs.',
                                 'category': 'Unsubscribe Groups',
                                 'family': 'suppressions',
                                 'method': 'GET',
                                 'path': '/v3/asm/groups',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_asm_suppression': {'name': 'suppressions_list_asm_suppression',
                                       'label': 'Retrieve all suppressions',
                                       'description': '**This endpoint allows you to retrieve a '
                                                      'list of all suppressions.**',
                                       'category': 'Suppressions',
                                       'family': 'suppressions',
                                       'method': 'GET',
                                       'path': '/v3/asm/suppressions',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_global_suppression': {'name': 'suppressions_list_global_suppression',
                                          'label': 'Retrieve all global suppressions',
                                          'description': '**This endpoint allows you to retrieve a '
                                                         'paginated list of all email address that '
                                                         'are globally suppressed.** You can use '
                                                         'the `limit` query parameter to set the '
                                                         'page size. If your list contains more '
                                                         'items than the page size permits, you '
                                                         'can make multiple requests. Use the '
                                                         '`offset` query parameter to control the '
                                                         'position in the list from which to start '
                                                         'retrieving additional items.',
                                          'category': 'Global Suppressions',
                                          'family': 'suppressions',
                                          'method': 'GET',
                                          'path': '/v3/suppression/unsubscribes',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_invalid_email': {'name': 'suppressions_list_invalid_email',
                                     'label': 'Retrieve all invalid emails',
                                     'description': '**This endpoint allows you to retrieve a '
                                                    'paginated list of all invalid email '
                                                    'addresses.** You can use the `limit` query '
                                                    'parameter to set the page size. If your list '
                                                    'contains more items than the page size '
                                                    'permits, you can make multiple requests. Use '
                                                    'the `offset` query parameter to control the '
                                                    'position in the list from which to start '
                                                    'retrieving additional items.',
                                     'category': 'Invalid Emails',
                                     'family': 'suppressions',
                                     'method': 'GET',
                                     'path': '/v3/suppression/invalid_emails',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_spam_report': {'name': 'suppressions_list_spam_report',
                                   'label': 'Retrieve all spam reports',
                                   'description': '**This endpoint allows you to retrieve a '
                                                  'paginated list of all spam reports.** You can '
                                                  'use the `limit` query parameter to set the page '
                                                  'size. If your list contains more items than the '
                                                  'page size permits, you can make multiple '
                                                  'requests. Use the `offset` query parameter to '
                                                  'control the position in the list from which to '
                                                  'start retrieving additional items.',
                                   'category': 'Spam Reports',
                                   'family': 'suppressions',
                                   'method': 'GET',
                                   'path': '/v3/suppression/spam_reports',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_suppression_block': {'name': 'suppressions_list_suppression_block',
                                         'label': 'Retrieve all blocks',
                                         'description': '**This endpoint allows you to retrieve a '
                                                        'paginated list of all email addresses '
                                                        'that are currently on your blocks list.** '
                                                        'You can use the `limit` query parameter '
                                                        'to set the page size. If your list '
                                                        'contains more items than the page size '
                                                        'permits, you can make multiple requests. '
                                                        'Use the `offset` query parameter to '
                                                        'control the position in the list from '
                                                        'which to start retrieving additional '
                                                        'items.',
                                         'category': 'Blocks',
                                         'family': 'suppressions',
                                         'method': 'GET',
                                         'path': '/v3/suppression/blocks',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_suppression_bounces': {'name': 'suppressions_list_suppression_bounces',
                                           'label': 'Retrieve all bounces',
                                           'description': '**This endpoint allows you to retrieve '
                                                          'a paginated list of all your bounces.** '
                                                          'You can use the `limit` query parameter '
                                                          'to set the page size. If your list '
                                                          'contains more items than the page size '
                                                          'permits, you can make multiple '
                                                          'requests. Use the `offset` query '
                                                          'parameter to control the position in '
                                                          'the list from which to start retrieving '
                                                          'additional items.',
                                           'category': 'Bounces',
                                           'family': 'suppressions',
                                           'method': 'GET',
                                           'path': '/v3/suppression/bounces',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': None,
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_suppression_bounces_classifications': {'name': 'suppressions_list_suppression_bounces_classifications',
                                                           'label': 'Retrieve bounce '
                                                                    'classification totals',
                                                           'description': 'This endpoint will '
                                                                          'return the total number '
                                                                          'of bounces by '
                                                                          'classification in '
                                                                          'descending order for '
                                                                          'each day. You can '
                                                                          'retrieve the bounce '
                                                                          'classification totals '
                                                                          'in CSV format by '
                                                                          'specifying `"text/csv"` '
                                                                          'in the Accept header.',
                                                           'category': 'Bounces',
                                                           'family': 'suppressions',
                                                           'method': 'GET',
                                                           'path': '/v3/suppression/bounces/classifications',
                                                           'required_params': [],
                                                           'body_required': False,
                                                           'body_type': None,
                                                           'regions': ['us', 'eu'],
                                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_list_suppression_from_asm_group': {'name': 'suppressions_list_suppression_from_asm_group',
                                                  'label': 'Retrieve all suppressions for a '
                                                           'suppression group',
                                                  'description': '**This endpoint allows you to '
                                                                 'retrieve all suppressed email '
                                                                 'addresses belonging to the given '
                                                                 'group.**',
                                                  'category': 'Suppressions',
                                                  'family': 'suppressions',
                                                  'method': 'GET',
                                                  'path': '/v3/asm/groups/{group_id}/suppressions',
                                                  'required_params': [],
                                                  'body_required': False,
                                                  'body_type': None,
                                                  'regions': ['us', 'eu'],
                                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_search_suppression_from_asm_group': {'name': 'suppressions_search_suppression_from_asm_group',
                                                    'label': 'Search for suppressions within a '
                                                             'group',
                                                    'description': '**This endpoint allows you to '
                                                                   'search a suppression group for '
                                                                   'multiple suppressions.** When '
                                                                   'given a list of email '
                                                                   'addresses and a group ID, this '
                                                                   'endpoint will only return the '
                                                                   'email addresses that have been '
                                                                   'unsubscribed from the given '
                                                                   'group.',
                                                    'category': 'Suppressions',
                                                    'family': 'suppressions',
                                                    'method': 'POST',
                                                    'path': '/v3/asm/groups/{group_id}/suppressions/search',
                                                    'required_params': [],
                                                    'body_required': False,
                                                    'body_type': 'application/json',
                                                    'regions': ['us', 'eu'],
                                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'suppressions_update_asm_group': {'name': 'suppressions_update_asm_group',
                                   'label': 'Update a suppression group',
                                   'description': '**This endpoint allows you to update or change '
                                                  'a suppression group.**',
                                   'category': 'Unsubscribe Groups',
                                   'family': 'suppressions',
                                   'method': 'PATCH',
                                   'path': '/v3/asm/groups/{group_id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_suppressions_v3.json'},
 'teammates_delete_pending_teammate': {'name': 'teammates_delete_pending_teammate',
                                       'label': 'Delete pending teammate',
                                       'description': '**This endpoint allows you to delete a '
                                                      'pending teammate invite.**',
                                       'category': 'Teammates',
                                       'family': 'teammates',
                                       'method': 'DELETE',
                                       'path': '/v3/teammates/pending/{token}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_delete_teammate': {'name': 'teammates_delete_teammate',
                               'label': 'Delete teammate',
                               'description': '**This endpoint allows you to delete a teammate.** '
                                              '**Only the parent user or an admin teammate can '
                                              'delete another teammate.**',
                               'category': 'Teammates',
                               'family': 'teammates',
                               'method': 'DELETE',
                               'path': '/v3/teammates/{username}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_get_teammate': {'name': 'teammates_get_teammate',
                            'label': 'Retrieve specific teammate',
                            'description': '**This endpoint allows you to retrieve a specific '
                                           'Teammate by username.** You can retrieve the '
                                           "username's for each of your Teammates using the "
                                           '"Retrieve all Teammates" endpoint.',
                            'category': 'Teammates',
                            'family': 'teammates',
                            'method': 'GET',
                            'path': '/v3/teammates/{username}',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_invite_teammate': {'name': 'teammates_invite_teammate',
                               'label': 'Invite teammate',
                               'description': '**This endpoint allows you to invite a Teammate to '
                                              "your account via email.** You can set a Teammate's "
                                              'initial permissions using the `scopes` array in the '
                                              "request body. Teammate's will receive a minimum set "
                                              'of scopes from Twilio SendGrid that are necessary '
                                              'for the Teammate to function. **Note:** A teammate '
                                              'invite will expire after 7 days, but you may resend '
                                              'the invitation at any time to reset the e',
                               'category': 'Teammates',
                               'family': 'teammates',
                               'method': 'POST',
                               'path': '/v3/teammates',
                               'required_params': [],
                               'body_required': False,
                               'body_type': 'application/json',
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_list_pending_teammate': {'name': 'teammates_list_pending_teammate',
                                     'label': 'Retrieve all pending teammates',
                                     'description': '**This endpoint allows you to retrieve a list '
                                                    'of all pending Teammate invitations.** Each '
                                                    'teammate invitation is valid for 7 days. '
                                                    'Users may resend the invitation to refresh '
                                                    'the expiration date.',
                                     'category': 'Teammates',
                                     'family': 'teammates',
                                     'method': 'GET',
                                     'path': '/v3/teammates/pending',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_list_subuser_by_template': {'name': 'teammates_list_subuser_by_template',
                                        'label': 'Get Teammate Subuser Access',
                                        'description': '**This operation allows you to retrieve '
                                                       'the Subusers that can be accessed by a '
                                                       'specified Teammate.** This operation will '
                                                       'return the Subusers available to a '
                                                       'Teammate, including the scopes available. '
                                                       'If the Teammate is an administrator, all '
                                                       'Subusers will be returned.',
                                        'category': 'Teammates',
                                        'family': 'teammates',
                                        'method': 'GET',
                                        'path': '/v3/teammates/{teammate_name}/subuser_access',
                                        'required_params': [],
                                        'body_required': False,
                                        'body_type': None,
                                        'regions': ['us', 'eu'],
                                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_list_teammate': {'name': 'teammates_list_teammate',
                             'label': 'Retrieve all teammates',
                             'description': '**This endpoint allows you to retrieve a paginated '
                                            'list of all current Teammates.** You can use the '
                                            '`limit` query parameter to set the page size. If your '
                                            'list contains more items than the page size permits, '
                                            'you can make multiple requests. Use the `offset` '
                                            'query parameter to control the position in the list '
                                            'from which to start retrieving additional items.',
                             'category': 'Teammates',
                             'family': 'teammates',
                             'method': 'GET',
                             'path': '/v3/teammates',
                             'required_params': [],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_resend_teammate_invite': {'name': 'teammates_resend_teammate_invite',
                                      'label': 'Resend teammate invite',
                                      'description': '**This endpoint allows you to resend a '
                                                     'Teammate invitation.** Teammate invitations '
                                                     'will expire after 7 days. Resending an '
                                                     'invitation will reset the expiration date.',
                                      'category': 'Teammates',
                                      'family': 'teammates',
                                      'method': 'POST',
                                      'path': '/v3/teammates/pending/{token}/resend',
                                      'required_params': [],
                                      'body_required': False,
                                      'body_type': None,
                                      'regions': ['us', 'eu'],
                                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'teammates_update_teammate': {'name': 'teammates_update_teammate',
                               'label': "Update teammate's permissions",
                               'description': '**This endpoint allows you to update a teammate’s '
                                              'permissions.** To turn a teammate into an admin, '
                                              'the request body should contain an `is_admin` set '
                                              'to `true`. Otherwise, set `is_admin` to `false` and '
                                              'pass in all the scopes that a teammate should have. '
                                              '**Only the parent user or other admin teammates can '
                                              'update another teammate’s permissions.** **Admin '
                                              'users can only update permissions.**',
                               'category': 'Teammates',
                               'family': 'teammates',
                               'method': 'PATCH',
                               'path': '/v3/teammates/{username}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': 'application/json',
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_teammates_v3.json'},
 'templates_activate_template_version': {'name': 'templates_activate_template_version',
                                         'label': 'Activate a transactional template version',
                                         'description': '**This endpoint allows you to activate a '
                                                        'version of one of your templates.**',
                                         'category': 'Templates Versions',
                                         'family': 'templates',
                                         'method': 'POST',
                                         'path': '/v3/templates/{template_id}/versions/{version_id}/activate',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_create_template': {'name': 'templates_create_template',
                               'label': 'Create a transactional template',
                               'description': '**This endpoint allows you to create a '
                                              'transactional template.**',
                               'category': 'Templates',
                               'family': 'templates',
                               'method': 'POST',
                               'path': '/v3/templates',
                               'required_params': [],
                               'body_required': False,
                               'body_type': 'application/json',
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_create_template_version': {'name': 'templates_create_template_version',
                                       'label': 'Create a new transactional template version',
                                       'description': '**This endpoint allows you to create a new '
                                                      'version of a template.**',
                                       'category': 'Templates Versions',
                                       'family': 'templates',
                                       'method': 'POST',
                                       'path': '/v3/templates/{template_id}/versions',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_delete_template': {'name': 'templates_delete_template',
                               'label': 'Delete a template',
                               'description': '**This endpoint allows you to delete a '
                                              'transactional template.**',
                               'category': 'Templates',
                               'family': 'templates',
                               'method': 'DELETE',
                               'path': '/v3/templates/{template_id}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': None,
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_delete_template_version': {'name': 'templates_delete_template_version',
                                       'label': 'Delete a transactional template version',
                                       'description': '**This endpoint allows you to delete a '
                                                      'transactional template version.**',
                                       'category': 'Templates Versions',
                                       'family': 'templates',
                                       'method': 'DELETE',
                                       'path': '/v3/templates/{template_id}/versions/{version_id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_duplicate_template': {'name': 'templates_duplicate_template',
                                  'label': 'Duplicate a transactional template',
                                  'description': '**This endpoint allows you to duplicate a '
                                                 'transactional template.**',
                                  'category': 'Templates',
                                  'family': 'templates',
                                  'method': 'POST',
                                  'path': '/v3/templates/{template_id}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': 'application/json',
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_get_template': {'name': 'templates_get_template',
                            'label': 'Retrieve a single transactional template',
                            'description': '**This endpoint allows you to retrieve a single '
                                           'transactional template.**',
                            'category': 'Templates',
                            'family': 'templates',
                            'method': 'GET',
                            'path': '/v3/templates/{template_id}',
                            'required_params': [],
                            'body_required': False,
                            'body_type': None,
                            'regions': ['us', 'eu'],
                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_get_template_version': {'name': 'templates_get_template_version',
                                    'label': 'Retrieve a specific transactional template version',
                                    'description': '**This endpoint allows you to retrieve a '
                                                   'specific version of a template.**',
                                    'category': 'Templates Versions',
                                    'family': 'templates',
                                    'method': 'GET',
                                    'path': '/v3/templates/{template_id}/versions/{version_id}',
                                    'required_params': [],
                                    'body_required': False,
                                    'body_type': None,
                                    'regions': ['us', 'eu'],
                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_list_template': {'name': 'templates_list_template',
                             'label': 'Retrieve paged transactional templates',
                             'description': '**This endpoint allows you to retrieve all '
                                            'transactional templates.**',
                             'category': 'Templates',
                             'family': 'templates',
                             'method': 'GET',
                             'path': '/v3/templates',
                             'required_params': [{'name': 'page_size', 'in': 'query'}],
                             'body_required': False,
                             'body_type': None,
                             'regions': ['us', 'eu'],
                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_update_template': {'name': 'templates_update_template',
                               'label': 'Edit a transactional template',
                               'description': '**This endpoint allows you to edit the name of a '
                                              'transactional template.** To edit the template '
                                              'itself, [create a new transactional template '
                                              'version](https://docs.sendgrid.com/api-reference/transactional-templates-versions/create-a-new-transactional-template-version).',
                               'category': 'Templates',
                               'family': 'templates',
                               'method': 'PATCH',
                               'path': '/v3/templates/{template_id}',
                               'required_params': [],
                               'body_required': False,
                               'body_type': 'application/json',
                               'regions': ['us', 'eu'],
                               'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'templates_update_template_version': {'name': 'templates_update_template_version',
                                       'label': 'Edit a transactional template version',
                                       'description': '**This endpoint allows you to edit the '
                                                      'content of your template version.**',
                                       'category': 'Templates Versions',
                                       'family': 'templates',
                                       'method': 'PATCH',
                                       'path': '/v3/templates/{template_id}/versions/{version_id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': 'application/json',
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_templates_v3.json'},
 'test_connection': {'name': 'test_connection',
                     'label': 'Test Connection',
                     'description': 'Read the permissions granted to this API key.',
                     'category': 'Account',
                     'family': 'scopes',
                     'method': 'GET',
                     'path': '/v3/scopes',
                     'required_params': [],
                     'body_required': False,
                     'body_type': None,
                     'regions': ['us', 'eu'],
                     'source': 'https://www.twilio.com/docs/sendgrid/api-reference/api-keys/retrieve-scopes'},
 'tracking_settings_list_click_tracking_setting': {'name': 'tracking_settings_list_click_tracking_setting',
                                                   'label': 'Retrieve Click Track Settings',
                                                   'description': '**This endpoint allows you to '
                                                                  'retrieve your current click '
                                                                  'tracking setting.** Click '
                                                                  'Tracking overrides all the '
                                                                  'links and URLs in your emails '
                                                                  'and points them to either '
                                                                  'SendGrid’s servers or the '
                                                                  'domain with which you branded '
                                                                  'your link. When a customer '
                                                                  'clicks a link, SendGrid tracks '
                                                                  'those '
                                                                  '[clicks](https://sendgrid.com/docs/glossary/clicks/). '
                                                                  'Click tracking helps you '
                                                                  'understand how users are '
                                                                  'engaging ',
                                                   'category': 'Tracking',
                                                   'family': 'tracking_settings',
                                                   'method': 'GET',
                                                   'path': '/v3/tracking_settings/click',
                                                   'required_params': [],
                                                   'body_required': False,
                                                   'body_type': None,
                                                   'regions': ['us', 'eu'],
                                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_list_google_analytics_tracking_setting': {'name': 'tracking_settings_list_google_analytics_tracking_setting',
                                                              'label': 'Retrieve Google Analytics '
                                                                       'Settings',
                                                              'description': '**This endpoint '
                                                                             'allows you to '
                                                                             'retrieve your '
                                                                             'current setting for '
                                                                             'Google Analytics.** '
                                                                             'Google Analytics '
                                                                             'helps you understand '
                                                                             'how users got to '
                                                                             'your site and what '
                                                                             "they're doing there. "
                                                                             'For more information '
                                                                             'about using Google '
                                                                             'Analytics, please '
                                                                             'refer to [Google’s '
                                                                             'URL '
                                                                             'Builder](https://support.google.com/analytics/answer/1033867?hl=en) '
                                                                             'and their article on '
                                                                             '["Best Practices for '
                                                                             'Campaign '
                                                                             'Building"](https://su',
                                                              'category': 'Tracking',
                                                              'family': 'tracking_settings',
                                                              'method': 'GET',
                                                              'path': '/v3/tracking_settings/google_analytics',
                                                              'required_params': [],
                                                              'body_required': False,
                                                              'body_type': None,
                                                              'regions': ['us', 'eu'],
                                                              'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_list_open_tracking_setting': {'name': 'tracking_settings_list_open_tracking_setting',
                                                  'label': 'Get Open Tracking Settings',
                                                  'description': '**This endpoint allows you to '
                                                                 'retrieve your current settings '
                                                                 'for open tracking.** Open '
                                                                 'Tracking adds an invisible image '
                                                                 'at the end of the email which '
                                                                 'can track email opens. If the '
                                                                 'email recipient has images '
                                                                 'enabled on their email client, a '
                                                                 'request to SendGrid’s server for '
                                                                 'the invisible image is executed '
                                                                 'and an open event is logged. '
                                                                 'These events are logged in the '
                                                                 'Statistics portal, Email '
                                                                 'Activity i',
                                                  'category': 'Tracking',
                                                  'family': 'tracking_settings',
                                                  'method': 'GET',
                                                  'path': '/v3/tracking_settings/open',
                                                  'required_params': [],
                                                  'body_required': False,
                                                  'body_type': None,
                                                  'regions': ['us', 'eu'],
                                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_list_subscription_tracking_setting': {'name': 'tracking_settings_list_subscription_tracking_setting',
                                                          'label': 'Retrieve Subscription Tracking '
                                                                   'Settings',
                                                          'description': '**This endpoint allows '
                                                                         'you to retrieve your '
                                                                         'current settings for '
                                                                         'subscription tracking.** '
                                                                         'Subscription tracking '
                                                                         'adds links to the bottom '
                                                                         'of your emails that '
                                                                         'allows your recipients '
                                                                         'to subscribe to, or '
                                                                         'unsubscribe from, your '
                                                                         'emails.',
                                                          'category': 'Tracking',
                                                          'family': 'tracking_settings',
                                                          'method': 'GET',
                                                          'path': '/v3/tracking_settings/subscription',
                                                          'required_params': [],
                                                          'body_required': False,
                                                          'body_type': None,
                                                          'regions': ['us', 'eu'],
                                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_list_tracking_setting': {'name': 'tracking_settings_list_tracking_setting',
                                             'label': 'Retrieve Tracking Settings',
                                             'description': '**This endpoint allows you to '
                                                            'retrieve a list of all tracking '
                                                            'settings on your account.**',
                                             'category': 'Tracking',
                                             'family': 'tracking_settings',
                                             'method': 'GET',
                                             'path': '/v3/tracking_settings',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': None,
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_update_click_tracking_setting': {'name': 'tracking_settings_update_click_tracking_setting',
                                                     'label': 'Update Click Tracking Settings',
                                                     'description': '**This endpoint allows you to '
                                                                    'enable or disable your '
                                                                    'current click tracking '
                                                                    'setting.** Click Tracking '
                                                                    'overrides all the links and '
                                                                    'URLs in your emails and '
                                                                    'points them to either '
                                                                    'SendGrid’s servers or the '
                                                                    'domain with which you branded '
                                                                    'your link. When a customer '
                                                                    'clicks a link, SendGrid '
                                                                    'tracks those '
                                                                    '[clicks](https://sendgrid.com/docs/glossary/clicks/). '
                                                                    'Click tracking helps you '
                                                                    'understand how users are ',
                                                     'category': 'Tracking',
                                                     'family': 'tracking_settings',
                                                     'method': 'PATCH',
                                                     'path': '/v3/tracking_settings/click',
                                                     'required_params': [],
                                                     'body_required': False,
                                                     'body_type': 'application/json',
                                                     'regions': ['us', 'eu'],
                                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_update_google_analytics_tracking_setting': {'name': 'tracking_settings_update_google_analytics_tracking_setting',
                                                                'label': 'Update Google Analytics '
                                                                         'Settings',
                                                                'description': '**This endpoint '
                                                                               'allows you to '
                                                                               'update your '
                                                                               'current setting '
                                                                               'for Google '
                                                                               'Analytics.** '
                                                                               'Google Analytics '
                                                                               'helps you '
                                                                               'understand how '
                                                                               'users got to your '
                                                                               'site and what '
                                                                               "they're doing "
                                                                               'there. For more '
                                                                               'information about '
                                                                               'using Google '
                                                                               'Analytics, please '
                                                                               'refer to [Google’s '
                                                                               'URL '
                                                                               'Builder](https://support.google.com/analytics/answer/1033867?hl=en) '
                                                                               'and their article '
                                                                               'on ["Best '
                                                                               'Practices for '
                                                                               'Campaign '
                                                                               'Building"](https://supp',
                                                                'category': 'Tracking',
                                                                'family': 'tracking_settings',
                                                                'method': 'PATCH',
                                                                'path': '/v3/tracking_settings/google_analytics',
                                                                'required_params': [],
                                                                'body_required': False,
                                                                'body_type': 'application/json',
                                                                'regions': ['us', 'eu'],
                                                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_update_open_tracking_setting': {'name': 'tracking_settings_update_open_tracking_setting',
                                                    'label': 'Update Open Tracking Settings',
                                                    'description': '**This endpoint allows you to '
                                                                   'update your current settings '
                                                                   'for open tracking.** Open '
                                                                   'Tracking adds an invisible '
                                                                   'image at the end of the email '
                                                                   'which can track email opens. '
                                                                   'If the email recipient has '
                                                                   'images enabled on their email '
                                                                   'client, a request to '
                                                                   'SendGrid’s server for the '
                                                                   'invisible image is executed '
                                                                   'and an open event is logged. '
                                                                   'These events are logged in the '
                                                                   'Statistics portal, Email '
                                                                   'Activity int',
                                                    'category': 'Tracking',
                                                    'family': 'tracking_settings',
                                                    'method': 'PATCH',
                                                    'path': '/v3/tracking_settings/open',
                                                    'required_params': [],
                                                    'body_required': False,
                                                    'body_type': 'application/json',
                                                    'regions': ['us', 'eu'],
                                                    'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'tracking_settings_update_subscription_tracking_setting': {'name': 'tracking_settings_update_subscription_tracking_setting',
                                                            'label': 'Update Subscription Tracking '
                                                                     'Settings',
                                                            'description': '**This endpoint allows '
                                                                           'you to update your '
                                                                           'current settings for '
                                                                           'subscription '
                                                                           'tracking.** '
                                                                           'Subscription tracking '
                                                                           'adds links to the '
                                                                           'bottom of your emails '
                                                                           'that allows your '
                                                                           'recipients to '
                                                                           'subscribe to, or '
                                                                           'unsubscribe from, your '
                                                                           'emails.',
                                                            'category': 'Tracking',
                                                            'family': 'tracking_settings',
                                                            'method': 'PATCH',
                                                            'path': '/v3/tracking_settings/subscription',
                                                            'required_params': [],
                                                            'body_required': False,
                                                            'body_type': 'application/json',
                                                            'regions': ['us', 'eu'],
                                                            'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_tracking_settings_v3.json'},
 'user_list_account': {'name': 'user_list_account',
                       'label': "Get a user's account information",
                       'description': '**This endpoint allows you to retrieve your user account '
                                      "details.** Your user's account information includes the "
                                      "user's account type and reputation.",
                       'category': 'Users API',
                       'family': 'user',
                       'method': 'GET',
                       'path': '/v3/user/account',
                       'required_params': [],
                       'body_required': False,
                       'body_type': None,
                       'regions': ['us', 'eu'],
                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_list_credit': {'name': 'user_list_credit',
                      'label': 'Retrieve your credit balance',
                      'description': '**This endpoint allows you to retrieve the current credit '
                                     'balance for your account.** Each account has a credit '
                                     'balance, which is a base number of emails it can send before '
                                     'receiving per-email charges. For more information about '
                                     'credits and billing, see [Billing and Plan details '
                                     'information](https://sendgrid.com/docs/ui/account-and-settings/billing/).',
                      'category': 'Users API',
                      'family': 'user',
                      'method': 'GET',
                      'path': '/v3/user/credits',
                      'required_params': [],
                      'body_required': False,
                      'body_type': None,
                      'regions': ['us', 'eu'],
                      'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_list_email': {'name': 'user_list_email',
                     'label': 'Retrieve your account email address',
                     'description': '**This endpoint allows you to retrieve the email address '
                                    'currently on file for your account.**',
                     'category': 'Users API',
                     'family': 'user',
                     'method': 'GET',
                     'path': '/v3/user/email',
                     'required_params': [],
                     'body_required': False,
                     'body_type': None,
                     'regions': ['us', 'eu'],
                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_list_profile': {'name': 'user_list_profile',
                       'label': "Get a user's profile",
                       'description': '**This endpoint allows you to retrieve your current profile '
                                      'details.**',
                       'category': 'Users API',
                       'family': 'user',
                       'method': 'GET',
                       'path': '/v3/user/profile',
                       'required_params': [],
                       'body_required': False,
                       'body_type': None,
                       'regions': ['us', 'eu'],
                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_list_username': {'name': 'user_list_username',
                        'label': 'Retrieve your username',
                        'description': '**This endpoint allows you to retrieve your current '
                                       'account username.**',
                        'category': 'Users API',
                        'family': 'user',
                        'method': 'GET',
                        'path': '/v3/user/username',
                        'required_params': [],
                        'body_required': False,
                        'body_type': None,
                        'regions': ['us', 'eu'],
                        'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_update_email': {'name': 'user_update_email',
                       'label': 'Update your account email address',
                       'description': '**This endpoint allows you to update the email address '
                                      'currently on file for your account.**',
                       'category': 'Users API',
                       'family': 'user',
                       'method': 'PUT',
                       'path': '/v3/user/email',
                       'required_params': [],
                       'body_required': False,
                       'body_type': 'application/json',
                       'regions': ['us', 'eu'],
                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_update_password': {'name': 'user_update_password',
                          'label': 'Update your password',
                          'description': '**This endpoint allows you to update your password.**',
                          'category': 'Users API',
                          'family': 'user',
                          'method': 'PUT',
                          'path': '/v3/user/password',
                          'required_params': [],
                          'body_required': False,
                          'body_type': 'application/json',
                          'regions': ['us', 'eu'],
                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_update_profile': {'name': 'user_update_profile',
                         'label': "Update a user's profile",
                         'description': '**This endpoint allows you to update your current profile '
                                        'details.** Any one or more of the parameters can be '
                                        'updated via the PATCH `/user/profile` endpoint. You must '
                                        'include at least one when you PATCH.',
                         'category': 'Users API',
                         'family': 'user',
                         'method': 'PATCH',
                         'path': '/v3/user/profile',
                         'required_params': [],
                         'body_required': False,
                         'body_type': 'application/json',
                         'regions': ['us', 'eu'],
                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'user_update_username': {'name': 'user_update_username',
                          'label': 'Update your username',
                          'description': '**This endpoint allows you to update the username for '
                                         'your account.**',
                          'category': 'Users API',
                          'family': 'user',
                          'method': 'PUT',
                          'path': '/v3/user/username',
                          'required_params': [],
                          'body_required': False,
                          'body_type': 'application/json',
                          'regions': ['us', 'eu'],
                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_user_v3.json'},
 'verified_senders_create_verified_sender': {'name': 'verified_senders_create_verified_sender',
                                             'label': 'Create Verified Sender Request',
                                             'description': '**This endpoint allows you to create '
                                                            'a new Sender Identify**. Upon '
                                                            'successful submission of a `POST` '
                                                            'request to this endpoint, an identity '
                                                            'will be created, and a verification '
                                                            'email will be sent to the address '
                                                            'assigned to the `from_email` field. '
                                                            'You must complete the verification '
                                                            'process using the sent email to fully '
                                                            'verify the sender. If you need to '
                                                            'resend the verification email, you '
                                                            'can do so wit',
                                             'category': 'Sender Verification',
                                             'family': 'verified_senders',
                                             'method': 'POST',
                                             'path': '/v3/verified_senders',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': 'application/json',
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_delete_verified_sender': {'name': 'verified_senders_delete_verified_sender',
                                             'label': 'Delete Verified Sender',
                                             'description': '**This endpoint allows you to delete '
                                                            'a Sender Identity**. Pass the `id` '
                                                            'assigned to a Sender Identity to this '
                                                            'endpoint to delete the Sender '
                                                            'Identity from your account. You can '
                                                            'retrieve the IDs associated with '
                                                            'Sender Identities using the "Get All '
                                                            'Verified Senders" endpoint.',
                                             'category': 'Sender Verification',
                                             'family': 'verified_senders',
                                             'method': 'DELETE',
                                             'path': '/v3/verified_senders/{id}',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': None,
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_list_verified_sender': {'name': 'verified_senders_list_verified_sender',
                                           'label': 'Get All Verified Senders',
                                           'description': '**This endpoint allows you to retrieve '
                                                          'all the Sender Identities associated '
                                                          'with an account.** This endpoint will '
                                                          'return both verified and unverified '
                                                          'senders. You can limit the number of '
                                                          'results returned using the `limit`, '
                                                          '`lastSeenID`, and `id` query string '
                                                          'parameters. * `limit` allows you to '
                                                          'specify an exact number of Sender '
                                                          'Identities to return. * `lastSeenID` '
                                                          'will return senders with an ID num',
                                           'category': 'Sender Verification',
                                           'family': 'verified_senders',
                                           'method': 'GET',
                                           'path': '/v3/verified_senders',
                                           'required_params': [],
                                           'body_required': False,
                                           'body_type': None,
                                           'regions': ['us', 'eu'],
                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_list_verified_sender_domain': {'name': 'verified_senders_list_verified_sender_domain',
                                                  'label': 'Domain Warn List',
                                                  'description': '**This endpoint returns a list '
                                                                 'of domains known to implement '
                                                                 'DMARC and categorizes them by '
                                                                 'failure type — hard failure or '
                                                                 'soft failure**. Domains listed '
                                                                 'as hard failures will not '
                                                                 'deliver mail when used as a '
                                                                 '[Sender '
                                                                 'Identity](https://sendgrid.com/docs/for-developers/sending-email/sender-identity/) '
                                                                 "due to the domain's DMARC policy "
                                                                 'settings. For example, using a '
                                                                 '`yahoo.com` email address as a '
                                                                 'Sender ',
                                                  'category': 'Sender Verification',
                                                  'family': 'verified_senders',
                                                  'method': 'GET',
                                                  'path': '/v3/verified_senders/domains',
                                                  'required_params': [],
                                                  'body_required': False,
                                                  'body_type': None,
                                                  'regions': ['us', 'eu'],
                                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_list_verified_sender_steps_completed': {'name': 'verified_senders_list_verified_sender_steps_completed',
                                                           'label': 'Completed Steps',
                                                           'description': '**This endpoint allows '
                                                                          'you to determine which '
                                                                          'of SendGrid’s '
                                                                          'verification processes '
                                                                          'have been completed for '
                                                                          'an account**. This '
                                                                          'endpoint returns '
                                                                          'boolean values, `true` '
                                                                          'and `false`, for '
                                                                          '[Domain '
                                                                          'Authentication](https://sendgrid.com/docs/for-developers/sending-email/sender-identity/#domain-authentication), '
                                                                          '`domain_verified`, and '
                                                                          '[Single Sender '
                                                                          'Verification](https://sendgrid.com/docs/for-developers/send',
                                                           'category': 'Sender Verification',
                                                           'family': 'verified_senders',
                                                           'method': 'GET',
                                                           'path': '/v3/verified_senders/steps_completed',
                                                           'required_params': [],
                                                           'body_required': False,
                                                           'body_type': None,
                                                           'regions': ['us', 'eu'],
                                                           'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_resend_verified_sender': {'name': 'verified_senders_resend_verified_sender',
                                             'label': 'Resend Verified Sender Request',
                                             'description': '**This endpoint allows you to resend '
                                                            'a verification email to a specified '
                                                            'Sender Identity**. Passing the `id` '
                                                            'assigned to a Sender Identity to this '
                                                            'endpoint will resend a verification '
                                                            'email to the `from_address` '
                                                            'associated with the Sender Identity. '
                                                            'This can be useful if someone loses '
                                                            'their verification email or needs to '
                                                            'have it resent for any other reason. '
                                                            'You can retrieve the IDs associated '
                                                            'with S',
                                             'category': 'Sender Verification',
                                             'family': 'verified_senders',
                                             'method': 'POST',
                                             'path': '/v3/verified_senders/resend/{id}',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': None,
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_update_verified_sender': {'name': 'verified_senders_update_verified_sender',
                                             'label': 'Edit Verified Sender',
                                             'description': '**This endpoint allows you to update '
                                                            'an existing Sender Identity**. Pass '
                                                            'the `id` assigned to a Sender '
                                                            'Identity to this endpoint as a path '
                                                            'parameter. Include any fields you '
                                                            'wish to update in the request body in '
                                                            'JSON format. You can retrieve the IDs '
                                                            'associated with Sender Identities by '
                                                            'passing a `GET` request to the Get '
                                                            'All Verified Senders endpoint, '
                                                            '`/verified_senders`. **Note:** Unlike '
                                                            'a `PUT` re',
                                             'category': 'Sender Verification',
                                             'family': 'verified_senders',
                                             'method': 'PATCH',
                                             'path': '/v3/verified_senders/{id}',
                                             'required_params': [],
                                             'body_required': False,
                                             'body_type': 'application/json',
                                             'regions': ['us', 'eu'],
                                             'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'verified_senders_verify_sender_token': {'name': 'verified_senders_verify_sender_token',
                                          'label': 'Verify Sender Request',
                                          'description': '**This endpoint allows you to verify a '
                                                         'sender requests.** The token is '
                                                         'generated by SendGrid and included in a '
                                                         'verification email delivered to the '
                                                         "address that's pending verification.",
                                          'category': 'Sender Verification',
                                          'family': 'verified_senders',
                                          'method': 'GET',
                                          'path': '/v3/verified_senders/verify/{token}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': None,
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_verified_senders_v3.json'},
 'webhooks_create_event_webhook': {'name': 'webhooks_create_event_webhook',
                                   'label': 'Create a new Event Webhook',
                                   'description': '**This endpoint allows you to create a new '
                                                  'Event Webhook.** When creating a webhook, you '
                                                  'will provide a URL where you want the webhook '
                                                  'to send POST requests, and you will select '
                                                  'which events you want to receive in those '
                                                  'request. See the [**Event Webhook '
                                                  'Reference**](https://docs.sendgrid.com/for-developers/tracking-events/event#delivery-events) '
                                                  'for details about each event type. ### Webhook '
                                                  'identi',
                                   'category': 'Event Webhook',
                                   'family': 'webhooks',
                                   'method': 'POST',
                                   'path': '/v3/user/webhooks/event/settings',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_create_parse_setting': {'name': 'webhooks_create_parse_setting',
                                   'label': 'Create a parse setting',
                                   'description': '**This endpoint allows you to create a new '
                                                  'inbound parse setting.** Creating an Inbound '
                                                  'Parse setting requires two pieces of '
                                                  'information: a `url` and a `hostname`. The '
                                                  '`hostname` must correspond to a domain '
                                                  'authenticated by Twilio SendGrid on your '
                                                  'account. If you need to complete domain '
                                                  'authentication, you can use the [Twilio '
                                                  'SendGrid '
                                                  'App](https://app.sendgrid.com/settings/sender_auth) '
                                                  'or the **Au',
                                   'category': 'Parse Webhook',
                                   'family': 'webhooks',
                                   'method': 'POST',
                                   'path': '/v3/user/webhooks/parse/settings',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_create_security_policy': {'name': 'webhooks_create_security_policy',
                                     'label': 'Create a new webhook security policy',
                                     'description': 'Create a new webhook security policy. Note: '
                                                    'One of signature or oauth must be given to '
                                                    'have a valid security policy.',
                                     'category': 'Webhook Security',
                                     'family': 'webhooks',
                                     'method': 'POST',
                                     'path': '/v3/user/webhooks/security/policies',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': 'application/json',
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_delete_event_webhook': {'name': 'webhooks_delete_event_webhook',
                                   'label': 'Delete a single Event Webhook by ID',
                                   'description': '**This endpoint allows you to delete a single '
                                                  'Event Webhook by ID.** Unlike the [**Get an '
                                                  'Event '
                                                  'Webhook**](https://docs.sendgrid.com/api-reference/webhooks/get-an-event-webhook) '
                                                  'and [**Update an Event '
                                                  'Webhook**](https://docs.sendgrid.com/api-reference/webhooks/update-an-event-webhook) '
                                                  'endpoints, which will operate on your oldest '
                                                  "webhook by `created_date` when you don't "
                                                  'provide an ID, this endpoint',
                                   'category': 'Event Webhook',
                                   'family': 'webhooks',
                                   'method': 'DELETE',
                                   'path': '/v3/user/webhooks/event/settings/{id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_delete_parse_setting': {'name': 'webhooks_delete_parse_setting',
                                   'label': 'Delete a parse setting',
                                   'description': '**This endpoint allows you to delete a specific '
                                                  'inbound parse setting by hostname.** You can '
                                                  'retrieve all your Inbound Parse settings and '
                                                  'their associated host names with the "Retrieve '
                                                  'all parse settings" endpoint.',
                                   'category': 'Parse Webhook',
                                   'family': 'webhooks',
                                   'method': 'DELETE',
                                   'path': '/v3/user/webhooks/parse/settings/{hostname}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': None,
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_delete_security_policy': {'name': 'webhooks_delete_security_policy',
                                     'label': 'Delete a specific webhook security policy',
                                     'description': 'Permanently delete a webhook security policy '
                                                    'by its ID.',
                                     'category': 'Webhook Security',
                                     'family': 'webhooks',
                                     'method': 'DELETE',
                                     'path': '/v3/user/webhooks/security/policies/{id}',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': None,
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_get_event_webhook': {'name': 'webhooks_get_event_webhook',
                                'label': 'Get the settings for a single Event Webhook',
                                'description': '**This endpoint allows you to retrieve a single '
                                               'Event Webhook by ID.** If you do not pass a '
                                               'webhook ID to this endpoint, it will return your '
                                               'oldest webhook by `created_date`. This means the '
                                               'default webhook returned by this endpoint when no '
                                               'ID is provided will be the first one you created. '
                                               'This functionality allows customers who do not '
                                               'have multiple webhooks to use this endpoint to '
                                               'retrieve their o',
                                'category': 'Event Webhook',
                                'family': 'webhooks',
                                'method': 'GET',
                                'path': '/v3/user/webhooks/event/settings/{id}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_get_parse_setting': {'name': 'webhooks_get_parse_setting',
                                'label': 'Retrieve a specific parse setting',
                                'description': '**This endpoint allows you to retrieve a specific '
                                               'inbound parse setting by hostname.** You can '
                                               'retrieve all your Inbound Parse settings and their '
                                               'associated host names with the "Retrieve all parse '
                                               'settings" endpoint.',
                                'category': 'Parse Webhook',
                                'family': 'webhooks',
                                'method': 'GET',
                                'path': '/v3/user/webhooks/parse/settings/{hostname}',
                                'required_params': [],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_get_security_policy': {'name': 'webhooks_get_security_policy',
                                  'label': 'Retrieve a specific webhook security policy',
                                  'description': 'Retrieve the details of a specific webhook '
                                                 'security policy by its ID.',
                                  'category': 'Webhook Security',
                                  'family': 'webhooks',
                                  'method': 'GET',
                                  'path': '/v3/user/webhooks/security/policies/{id}',
                                  'required_params': [],
                                  'body_required': False,
                                  'body_type': None,
                                  'regions': ['us', 'eu'],
                                  'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_get_signed_event_webhook': {'name': 'webhooks_get_signed_event_webhook',
                                       'label': "Get Signed Event Webhook's Public Key",
                                       'description': '**This endpoint allows you to retrieve the '
                                                      'public key for a single Event Webhook by '
                                                      'ID.** If you do not pass a webhook ID to '
                                                      'this endpoint, it will return the public '
                                                      'key for your oldest webhook by '
                                                      '`created_date`. This means the default key '
                                                      'returned by this endpoint when no ID is '
                                                      'provided will be for the first webhook you '
                                                      'created. This functionality allows '
                                                      'customers who do not have multiple webhook',
                                       'category': 'Event Webhook',
                                       'family': 'webhooks',
                                       'method': 'GET',
                                       'path': '/v3/user/webhooks/event/settings/signed/{id}',
                                       'required_params': [],
                                       'body_required': False,
                                       'body_type': None,
                                       'regions': ['us', 'eu'],
                                       'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_list_all_security_policies': {'name': 'webhooks_list_all_security_policies',
                                         'label': 'Retrieve all webhook security policies for your '
                                                  'account',
                                         'description': 'Returns a list of all webhook security '
                                                        'policies configured for your account, '
                                                        'including their IDs, names, and security '
                                                        'configurations.',
                                         'category': 'Webhook Security',
                                         'family': 'webhooks',
                                         'method': 'GET',
                                         'path': '/v3/user/webhooks/security/policies',
                                         'required_params': [],
                                         'body_required': False,
                                         'body_type': None,
                                         'regions': ['us', 'eu'],
                                         'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_list_event_webhook': {'name': 'webhooks_list_event_webhook',
                                 'label': 'Retrieve all of your Event Webhooks',
                                 'description': '**This endpoint allows you to retrieve all of '
                                                'your Event Webhooks.** Each webhook will be '
                                                'returned as an object in the `webhooks` array '
                                                "with the webhook's configuration details and ID. "
                                                "You can use a webhook's ID to [update the "
                                                "webhook's "
                                                'settings](https://docs.sendgrid.com/api-reference/webhooks/update-an-event-webhook), '
                                                '[delete the '
                                                'webhook](https://docs.sendgrid.com/api-reference/webhooks/delete-a',
                                 'category': 'Event Webhook',
                                 'family': 'webhooks',
                                 'method': 'GET',
                                 'path': '/v3/user/webhooks/event/settings/all',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_list_parse_setting': {'name': 'webhooks_list_parse_setting',
                                 'label': 'Retrieve all parse settings',
                                 'description': '**This endpoint allows you to retrieve all of '
                                                'your current inbound parse settings.**',
                                 'category': 'Parse Webhook',
                                 'family': 'webhooks',
                                 'method': 'GET',
                                 'path': '/v3/user/webhooks/parse/settings',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': None,
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_list_parse_static': {'name': 'webhooks_list_parse_static',
                                'label': 'Retrieves Inbound Parse Webhook statistics',
                                'description': '**This endpoint allows you to retrieve the '
                                               'statistics for your Parse Webhook usage.** '
                                               "SendGrid's Inbound Parse Webhook allows you to "
                                               'parse the contents and attachments of incoming '
                                               'emails. The Parse API can then POST the parsed '
                                               'emails to a URL that you specify. The Inbound '
                                               'Parse Webhook cannot parse messages greater than '
                                               '30MB in size, including all attachments. There are '
                                               'a number of pre-made integr',
                                'category': 'Parse Webhook',
                                'family': 'webhooks',
                                'method': 'GET',
                                'path': '/v3/user/webhooks/parse/stats',
                                'required_params': [{'name': 'start_date', 'in': 'query'}],
                                'body_required': False,
                                'body_type': None,
                                'regions': ['us', 'eu'],
                                'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_test_event_webhook': {'name': 'webhooks_test_event_webhook',
                                 'label': "Test an Event Webhook's settings",
                                 'description': '**This endpoint allows you to test an Event '
                                                'Webhook.** Retry logic for this endpoint differs '
                                                'from other endpoints, which use a rolling 24-hour '
                                                'retry. This endpoint will make a POST request '
                                                'with a fake event notification to a URL you '
                                                'provide. This allows you to verify that you have '
                                                'properly configured the webhook before sending '
                                                'real data to your URL. ### Test OAuth '
                                                'configuration To test your OAuth ',
                                 'category': 'Event Webhook',
                                 'family': 'webhooks',
                                 'method': 'POST',
                                 'path': '/v3/user/webhooks/event/test',
                                 'required_params': [],
                                 'body_required': False,
                                 'body_type': 'application/json',
                                 'regions': ['us', 'eu'],
                                 'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_update_event_webhook': {'name': 'webhooks_update_event_webhook',
                                   'label': 'Update a single Event Webhook by ID',
                                   'description': '**This endpoint allows you to update a single '
                                                  'Event Webhook by ID.** If you do not pass a '
                                                  'webhook ID to this endpoint, it will update and '
                                                  'return your oldest webhook by `created_date`. '
                                                  'This means the default webhook updated by this '
                                                  'endpoint when no ID is provided will be the '
                                                  'first one you created. This functionality '
                                                  'allows customers who do not have multiple '
                                                  'webhooks to use this endpoint to update t',
                                   'category': 'Event Webhook',
                                   'family': 'webhooks',
                                   'method': 'PATCH',
                                   'path': '/v3/user/webhooks/event/settings/{id}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_update_parse_setting': {'name': 'webhooks_update_parse_setting',
                                   'label': 'Update a parse setting',
                                   'description': '**This endpoint allows you to update a specific '
                                                  'inbound parse setting by hostname.** You can '
                                                  'retrieve all your Inbound Parse settings and '
                                                  'their associated host names with the "Retrieve '
                                                  'all parse settings" endpoint.',
                                   'category': 'Parse Webhook',
                                   'family': 'webhooks',
                                   'method': 'PATCH',
                                   'path': '/v3/user/webhooks/parse/settings/{hostname}',
                                   'required_params': [],
                                   'body_required': False,
                                   'body_type': 'application/json',
                                   'regions': ['us', 'eu'],
                                   'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_update_security_policy': {'name': 'webhooks_update_security_policy',
                                     'label': 'Update an existing webhook security policy',
                                     'description': 'Update an existing webhook security policy '
                                                    'with new configuration values.',
                                     'category': 'Webhook Security',
                                     'family': 'webhooks',
                                     'method': 'PATCH',
                                     'path': '/v3/user/webhooks/security/policies/{id}',
                                     'required_params': [],
                                     'body_required': False,
                                     'body_type': 'application/json',
                                     'regions': ['us', 'eu'],
                                     'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'},
 'webhooks_update_signed_event_webhook': {'name': 'webhooks_update_signed_event_webhook',
                                          'label': 'Toggle signature verification for a single '
                                                   'Event Webhook by ID',
                                          'description': '**This endpoint allows you to enable or '
                                                         'disable signature verification for a '
                                                         'single Event Webhook by ID.** If you do '
                                                         'not pass a webhook ID to this endpoint, '
                                                         'it will enable signature verification '
                                                         'for your oldest webhook by '
                                                         '`created_date`. This means the default '
                                                         'webhook operated on by this endpoint '
                                                         'when no ID is provided will be the first '
                                                         'one you created. This functionality '
                                                         'allows customers who do n',
                                          'category': 'Event Webhook',
                                          'family': 'webhooks',
                                          'method': 'PATCH',
                                          'path': '/v3/user/webhooks/event/settings/signed/{id}',
                                          'required_params': [],
                                          'body_required': False,
                                          'body_type': 'application/json',
                                          'regions': ['us', 'eu'],
                                          'source': 'https://github.com/twilio/sendgrid-oai/blob/main/spec/json/tsg_webhooks_v3.json'}}
HOSTS = {"us": "https://api.sendgrid.com", "eu": "https://api.eu.sendgrid.com"}


class SendGridApiKeyCredential(BaseModel):
    credential_type: Literal["sendgrid_api_key"] = Field("sendgrid_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="API Region")

    model_config = ConfigDict(title="SendGrid API Key", json_schema_extra={
        "x-credential-url": "https://app.sendgrid.com/settings/api_keys",
        "x-credential-instructions": "Create a SendGrid API key with the permissions needed for your selected actions. SendGrid uses API keys rather than an OAuth sign-in flow for these APIs.",
    })


def _field_name(name: str, location: str) -> str:
    return f"{location}_{re.sub(r'[^a-zA-Z0-9]+', '_', name).strip('_').lower()}"


def _make_config(name: str, op: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for variable in re.findall(r"\{([^}]+)\}", op["path"]):
        fields[_field_name(variable, "path")] = (
            str, Field(..., title=variable.replace("_", " ").title())
        )
    for param in op["required_params"]:
        if param["name"].lower() == "accept":
            continue
        fields[_field_name(param["name"], param["in"])] = (
            str, Field(..., title=param["name"].replace("_", " ").title())
        )
    fields["query_json"] = (
        Optional[str], Field(None, title="Other Query Parameters JSON",
                             description="Optional API query parameters as a JSON object.",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    )
    fields["on_behalf_of"] = (
        Optional[str], Field(None, title="On Behalf Of",
                             description="Optional SendGrid subuser name for an On-Behalf-Of request.")
    )
    if name == "send_email":
        fields.update({
            "from_email": (Optional[str], Field(None, title="From Email")),
            "to_emails": (Optional[str], Field(None, title="To Emails", description="Comma-separated recipients.")),
            "cc_emails": (Optional[str], Field(None, title="CC Emails", description="Optional comma-separated recipients.")),
            "bcc_emails": (Optional[str], Field(None, title="BCC Emails", description="Optional comma-separated recipients.")),
            "reply_to_email": (Optional[str], Field(None, title="Reply-To Email")),
            "subject": (Optional[str], Field(None, title="Subject")),
            "text_body": (Optional[str], Field(None, title="Text Body", json_schema_extra={"ui:widget": "textarea"})),
            "html_body": (Optional[str], Field(None, title="HTML Body", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"})),
            "template_id": (Optional[str], Field(None, title="Dynamic Template ID")),
            "dynamic_template_data_json": (Optional[str], Field(None, title="Dynamic Template Data JSON",
                                                        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})),
        })
    if op["body_type"]:
        required = op["body_required"] and name != "send_email"
        fields["body_input"] = (
            str if required else Optional[str],
            Field(... if required else None, title="Request Body JSON",
                  description="Raw SendGrid request body. For Send Email, this overrides the simple email fields.",
                  json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}),
        )
    return create_model(
        "SendGrid" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op["category"], "x-is-trigger": False,
                               "x-display-name": op["label"]},
        )),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
SendGridConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class SendGridNodeConfig(NodeConfig[SendGridConfig, SendGridApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc


def _addresses(raw: Optional[str]) -> list[dict[str, str]]:
    return [{"email": address.strip()} for address in (raw or "").split(",") if address.strip()]


def _email_body(values: dict[str, Any]) -> dict[str, Any]:
    if values.get("body_input"):
        body = _parse_json(values["body_input"], "Request Body JSON")
        if not isinstance(body, dict):
            raise ValueError("Request Body JSON must be an object for Send Email")
        return body
    sender = values.get("from_email")
    recipients = _addresses(values.get("to_emails"))
    if not sender or not recipients:
        raise ValueError("From Email and To Emails are required unless Request Body JSON is supplied")
    personalization: dict[str, Any] = {"to": recipients}
    for field in ("cc", "bcc"):
        addresses = _addresses(values.get(f"{field}_emails"))
        if addresses:
            personalization[field] = addresses
    if values.get("dynamic_template_data_json"):
        data = _parse_json(values["dynamic_template_data_json"], "Dynamic Template Data JSON")
        if not isinstance(data, dict):
            raise ValueError("Dynamic Template Data JSON must be an object")
        personalization["dynamic_template_data"] = data
    body: dict[str, Any] = {"personalizations": [personalization], "from": {"email": sender}}
    if values.get("subject"):
        body["subject"] = values["subject"]
    if values.get("reply_to_email"):
        body["reply_to"] = {"email": values["reply_to_email"]}
    if values.get("template_id"):
        body["template_id"] = values["template_id"]
    content = []
    if values.get("text_body"):
        content.append({"type": "text/plain", "value": values["text_body"]})
    if values.get("html_body"):
        content.append({"type": "text/html", "value": values["html_body"]})
    if content:
        body["content"] = content
    if not content and not values.get("template_id"):
        raise ValueError("Provide Text Body, HTML Body, or a Dynamic Template ID")
    return body


class SendGridNode(WorkflowNode):
    integration_type = "automation-sendgrid"
    connection_evidence = ConnectionEvidence(identity_operation="test_connection", noun="SendGrid account")
    edit_examples = [
        "Send a transactional email with SendGrid",
        "Add contacts to a SendGrid marketing list",
        "Read SendGrid email activity",
        "Manage a SendGrid dynamic template",
    ]

    @classmethod
    def get_config_model(cls):
        return SendGridNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, SendGridNodeConfig):
            raise ValueError("SendGrid configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SendGrid API key")
        config = self.config.config
        op = OPERATIONS[config.operation]
        if credential.region not in op["regions"]:
            raise ValueError(f"{op['label']} is unavailable on SendGrid's {credential.region.upper()} API")

        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op["path"]
        for variable in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + variable + "}", quote(str(values.pop(_field_name(variable, "path"))), safe=""))
        query_raw = values.pop("query_json", None)
        params = _parse_json(query_raw, "Other Query Parameters JSON") if query_raw else {}
        if not isinstance(params, dict):
            raise ValueError("Other Query Parameters JSON must be an object")
        headers = {"Authorization": f"Bearer {credential.api_key}", "Accept": "application/json"}
        on_behalf_of = values.pop("on_behalf_of", None)
        if on_behalf_of:
            headers["On-Behalf-Of"] = on_behalf_of
        for param in op["required_params"]:
            if param["name"].lower() == "accept":
                continue
            value = values.pop(_field_name(param["name"], param["in"]))
            if param["in"] == "query":
                params[param["name"]] = value
            else:
                headers[param["name"]] = value
        request: dict[str, Any] = {}
        if config.operation == "send_email":
            request["json"] = _email_body(values)
        else:
            raw_body = values.pop("body_input", None)
            if raw_body is not None:
                request["json"] = _parse_json(raw_body, "Request Body JSON")
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"], HOSTS[credential.region] + path,
                params=params or None, headers=headers, **request,
            )
        # The partner SSO endpoint documents 303 as its successful API response.
        # Surface its destination to the caller without following it with the API key.
        sso_redirect = config.operation == "account_provisioning_authenticate_account" and response.status_code == 303
        if response.is_error or (response.is_redirect and not sso_redirect):
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:300]
            raise ValueError(f"SendGrid API error {response.status_code}: {str(detail)[:400]}")
        if not response.content:
            data: Any = {"ok": True}
        elif "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            data = response.json()
        else:
            data = {"text": response.text}
        result = {"status": "success", "operation": config.operation,
                  "status_code": response.status_code, "data": data}
        if sso_redirect and response.headers.get("location"):
            result["redirect_url"] = response.headers["location"]
        if response.headers.get("x-message-id"):
            result["message_id"] = response.headers["x-message-id"]
        return result
