"""Selected operations from Visma's published v2 OpenAPI contract.
Source: https://eaccountingapi.vismaonline.com/openapi/v2.json
SHA256: ad6785cd956fcbda7a3a878a210e0a6cc8c7e3cea58de7efb25700468e5b83da
Only writable, commonly automated body fields are exposed. PUT replaces data.
Pagination: https://developer.vismaonline.com/docs/pagination-copy
"""
VISMA_OPERATIONS = {'get_company_settings': {'method': 'GET',
                          'path': '/companysettings',
                          'summary': 'Get company settings',
                          'parameters': [],
                          'scope': 'ea:sales',
                          'response': 'object'},
 'list_customers': {'method': 'GET',
                    'path': '/customers',
                    'summary': 'Get customers',
                    'parameters': [{'name': '$page',
                                    'in': 'query',
                                    'required': False,
                                    'schema': {'type': 'integer',
                                               'minimum': 1,
                                               'maximum': 2147483647,
                                               'default': 1},
                                    'field': 'page'},
                                   {'name': '$pagesize',
                                    'in': 'query',
                                    'required': False,
                                    'schema': {'type': 'integer',
                                               'minimum': 1,
                                               'maximum': 1000,
                                               'default': 50},
                                    'field': 'page_size'}],
                    'scope': 'ea:sales',
                    'response': 'page'},
 'get_customer': {'method': 'GET',
                  'path': '/customers/{customerId}',
                  'summary': 'Get a specific customer based on id',
                  'parameters': [{'name': 'customerId',
                                  'in': 'path',
                                  'description': 'This represents the Id of the customer you want to get',
                                  'required': True,
                                  'schema': {'type': 'string', 'format': 'uuid'}}],
                  'scope': 'ea:sales',
                  'response': 'object'},
 'create_customer': {'method': 'POST',
                     'path': '/customers',
                     'summary': 'Create a customer',
                     'parameters': [],
                     'scope': 'ea:sales',
                     'body': {'type': 'object',
                              'required': ['InvoiceCity',
                                           'InvoicePostalCode',
                                           'IsActive',
                                           'IsPrivatePerson',
                                           'Name',
                                           'TermsOfPaymentId'],
                              'properties': {'InvoiceCity': {'maxLength': 50,
                                                             'minLength': 0,
                                                             'type': 'string'},
                                             'InvoicePostalCode': {'maxLength': 10,
                                                                   'minLength': 0,
                                                                   'type': 'string'},
                                             'CustomerNumber': {'maxLength': 16,
                                                                'minLength': 0,
                                                                'type': 'string',
                                                                'description': 'Unique identifier, if not '
                                                                               'provided, the system will '
                                                                               'provide one. For batch POST '
                                                                               'requests it is mandatory.',
                                                                'nullable': True},
                                             'ContactPersonName': {'maxLength': 100,
                                                                   'minLength': 0,
                                                                   'type': 'string',
                                                                   'nullable': True},
                                             'CurrencyCode': {'maxLength': 3,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'Default value: Currency of the '
                                                                             'user company',
                                                              'nullable': True},
                                             'EmailAddress': {'maxLength': 255,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'This is a default email '
                                                                             'address for sending customer '
                                                                             'invoices.',
                                                              'nullable': True},
                                             'InvoiceAddress1': {'maxLength': 50,
                                                                 'minLength': 0,
                                                                 'type': 'string',
                                                                 'nullable': True},
                                             'InvoiceCountryCode': {'maxLength': 2,
                                                                    'minLength': 0,
                                                                    'type': 'string',
                                                                    'description': 'When setting a VAT '
                                                                                   'number this should be '
                                                                                   'filled in as well.',
                                                                    'nullable': True},
                                             'Name': {'maxLength': 50, 'minLength': 0, 'type': 'string'},
                                             'Note': {'maxLength': 4000,
                                                      'minLength': 0,
                                                      'type': 'string',
                                                      'nullable': True},
                                             'Telephone': {'maxLength': 50,
                                                           'minLength': 0,
                                                           'type': 'string',
                                                           'nullable': True},
                                             'TermsOfPaymentId': {'type': 'string',
                                                                  'description': 'Source: Get from '
                                                                                 '/v2/termsofpayment',
                                                                  'format': 'uuid'},
                                             'VatNumber': {'maxLength': 20,
                                                           'minLength': 0,
                                                           'type': 'string',
                                                           'description': '<strong>Possible '
                                                                          'values:</strong><br/>8-12 numbers '
                                                                          'and letters<br/><br/>Format: 2 '
                                                                          'character country code followed '
                                                                          'by.',
                                                           'nullable': True},
                                             'IsPrivatePerson': {'type': 'boolean'},
                                             'IsActive': {'type': 'boolean'}}},
                     'response': 'object'},
 'update_customer': {'method': 'PUT',
                     'path': '/customers/{customerId}',
                     'summary': 'Update a customer',
                     'parameters': [{'name': 'customerId',
                                     'in': 'path',
                                     'description': 'This represents the Id of the customer you want to '
                                                    'update',
                                     'required': True,
                                     'schema': {'type': 'string', 'format': 'uuid'}}],
                     'scope': 'ea:sales',
                     'body': {'type': 'object',
                              'required': ['InvoiceCity',
                                           'InvoicePostalCode',
                                           'IsActive',
                                           'IsPrivatePerson',
                                           'Name',
                                           'TermsOfPaymentId'],
                              'properties': {'InvoiceCity': {'maxLength': 50,
                                                             'minLength': 0,
                                                             'type': 'string'},
                                             'InvoicePostalCode': {'maxLength': 10,
                                                                   'minLength': 0,
                                                                   'type': 'string'},
                                             'CustomerNumber': {'maxLength': 16,
                                                                'minLength': 0,
                                                                'type': 'string',
                                                                'description': 'Unique identifier, if not '
                                                                               'provided, the system will '
                                                                               'provide one. For batch POST '
                                                                               'requests it is mandatory.',
                                                                'nullable': True},
                                             'ContactPersonName': {'maxLength': 100,
                                                                   'minLength': 0,
                                                                   'type': 'string',
                                                                   'nullable': True},
                                             'CurrencyCode': {'maxLength': 3,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'Default value: Currency of the '
                                                                             'user company',
                                                              'nullable': True},
                                             'EmailAddress': {'maxLength': 255,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'This is a default email '
                                                                             'address for sending customer '
                                                                             'invoices.',
                                                              'nullable': True},
                                             'InvoiceAddress1': {'maxLength': 50,
                                                                 'minLength': 0,
                                                                 'type': 'string',
                                                                 'nullable': True},
                                             'InvoiceCountryCode': {'maxLength': 2,
                                                                    'minLength': 0,
                                                                    'type': 'string',
                                                                    'description': 'When setting a VAT '
                                                                                   'number this should be '
                                                                                   'filled in as well.',
                                                                    'nullable': True},
                                             'Name': {'maxLength': 50, 'minLength': 0, 'type': 'string'},
                                             'Note': {'maxLength': 4000,
                                                      'minLength': 0,
                                                      'type': 'string',
                                                      'nullable': True},
                                             'Telephone': {'maxLength': 50,
                                                           'minLength': 0,
                                                           'type': 'string',
                                                           'nullable': True},
                                             'TermsOfPaymentId': {'type': 'string',
                                                                  'description': 'Source: Get from '
                                                                                 '/v2/termsofpayment',
                                                                  'format': 'uuid'},
                                             'VatNumber': {'maxLength': 20,
                                                           'minLength': 0,
                                                           'type': 'string',
                                                           'description': '<strong>Possible '
                                                                          'values:</strong><br/>8-12 numbers '
                                                                          'and letters<br/><br/>Format: 2 '
                                                                          'character country code followed '
                                                                          'by.',
                                                           'nullable': True},
                                             'IsPrivatePerson': {'type': 'boolean'},
                                             'IsActive': {'type': 'boolean'}}},
                     'response': 'object'},
 'list_articles': {'method': 'GET',
                   'path': '/articles',
                   'summary': 'Gets articles',
                   'parameters': [{'name': 'showPricesWithTwoDecimals',
                                   'in': 'query',
                                   'description': 'Show prices with two decimals',
                                   'schema': {'type': 'boolean', 'default': False}},
                                  {'name': 'customerId',
                                   'in': 'query',
                                   'description': 'Customer ID for price calculations.If customerId is '
                                                  'provided in querystring,\r\n'
                                                  '                                       then article '
                                                  'prices and discounts will be returned based on which '
                                                  'pricelist \r\n'
                                                  '                                       and discount '
                                                  'agreement is assigned to customer.',
                                   'schema': {'type': 'string', 'format': 'uuid'}},
                                  {'name': '$page',
                                   'in': 'query',
                                   'required': False,
                                   'schema': {'type': 'integer',
                                              'minimum': 1,
                                              'maximum': 2147483647,
                                              'default': 1},
                                   'field': 'page'},
                                  {'name': '$pagesize',
                                   'in': 'query',
                                   'required': False,
                                   'schema': {'type': 'integer',
                                              'minimum': 1,
                                              'maximum': 1000,
                                              'default': 50},
                                   'field': 'page_size'}],
                   'scope': 'ea:sales',
                   'response': 'page'},
 'get_article': {'method': 'GET',
                 'path': '/articles/{articleId}',
                 'summary': 'Gets an article by id',
                 'parameters': [{'name': 'articleId',
                                 'in': 'path',
                                 'description': 'This represents the Id of the article',
                                 'required': True,
                                 'schema': {'type': 'string', 'format': 'uuid'}},
                                {'name': 'showPricesWithTwoDecimals',
                                 'in': 'query',
                                 'description': 'Show prices with two decimals',
                                 'schema': {'type': 'boolean', 'default': False}},
                                {'name': 'customerId',
                                 'in': 'query',
                                 'description': 'Customer ID for price calculations.If customerId is '
                                                'provided in querystring,\r\n'
                                                '                                       then article prices '
                                                'and discounts will be returned based on which pricelist\r\n'
                                                '                                       and discount '
                                                'agreement is assigned to customer.',
                                 'schema': {'type': 'string', 'format': 'uuid'}}],
                 'scope': 'ea:sales',
                 'response': 'object'},
 'create_article': {'method': 'POST',
                    'path': '/articles',
                    'summary': 'Create a single article',
                    'parameters': [],
                    'scope': 'ea:sales',
                    'body': {'type': 'object',
                             'required': ['CodingId', 'IsActive', 'Name', 'Number', 'UnitId'],
                             'properties': {'IsActive': {'type': 'boolean',
                                                         'description': 'Indicates whether the article is '
                                                                        'active'},
                                            'Number': {'maxLength': 40,
                                                       'minLength': 0,
                                                       'type': 'string',
                                                       'description': 'Article number'},
                                            'Name': {'maxLength': 50,
                                                     'minLength': 0,
                                                     'type': 'string',
                                                     'description': 'Article name (Swedish)'},
                                            'NetPrice': {'maximum': 99000000,
                                                         'minimum': 0,
                                                         'type': 'number',
                                                         'format': 'double'},
                                            'GrossPrice': {'maximum': 99000000,
                                                           'minimum': 0,
                                                           'type': 'number',
                                                           'format': 'double'},
                                            'CodingId': {'type': 'string',
                                                         'description': 'Get from /v2/articleaccountcodings',
                                                         'format': 'uuid'},
                                            'UnitId': {'type': 'string',
                                                       'description': 'Source: Get from /v2/units',
                                                       'format': 'uuid'},
                                            'StockBalance': {'maximum': 1000000000000000,
                                                             'minimum': -1000000000000000,
                                                             'type': 'number',
                                                             'description': 'Purpose: Sets the stock balance '
                                                                            'for this article Default: 0 '
                                                                            'When stock module is active, '
                                                                            'this is read only',
                                                             'format': 'double'},
                                            'PurchasePrice': {'maximum': 99000000,
                                                              'minimum': 0,
                                                              'type': 'number',
                                                              'description': 'Purchase price of the article '
                                                                             'in domestic currency. When '
                                                                             'saved on the article this is '
                                                                             'rounded to 2 decimals.',
                                                              'format': 'double'},
                                            'Note': {'maxLength': 4000,
                                                     'minLength': 0,
                                                     'type': 'string',
                                                     'description': 'Article Note',
                                                     'nullable': True}}},
                    'response': 'object'},
 'update_article': {'method': 'PUT',
                    'path': '/articles/{articleId}',
                    'summary': 'Replace an article',
                    'parameters': [{'name': 'articleId',
                                    'in': 'path',
                                    'description': 'This represents the Id of the article',
                                    'required': True,
                                    'schema': {'type': 'string', 'format': 'uuid'}}],
                    'scope': 'ea:sales',
                    'body': {'type': 'object',
                             'required': ['CodingId', 'IsActive', 'Name', 'Number', 'UnitId'],
                             'properties': {'IsActive': {'type': 'boolean',
                                                         'description': 'Indicates whether the article is '
                                                                        'active'},
                                            'Number': {'maxLength': 40,
                                                       'minLength': 0,
                                                       'type': 'string',
                                                       'description': 'Article number'},
                                            'Name': {'maxLength': 50,
                                                     'minLength': 0,
                                                     'type': 'string',
                                                     'description': 'Article name (Swedish)'},
                                            'NetPrice': {'maximum': 99000000,
                                                         'minimum': 0,
                                                         'type': 'number',
                                                         'format': 'double'},
                                            'GrossPrice': {'maximum': 99000000,
                                                           'minimum': 0,
                                                           'type': 'number',
                                                           'format': 'double'},
                                            'CodingId': {'type': 'string',
                                                         'description': 'Get from /v2/articleaccountcodings',
                                                         'format': 'uuid'},
                                            'UnitId': {'type': 'string',
                                                       'description': 'Source: Get from /v2/units',
                                                       'format': 'uuid'},
                                            'StockBalance': {'maximum': 1000000000000000,
                                                             'minimum': -1000000000000000,
                                                             'type': 'number',
                                                             'description': 'Purpose: Sets the stock balance '
                                                                            'for this article Default: 0 '
                                                                            'When stock module is active, '
                                                                            'this is read only',
                                                             'format': 'double'},
                                            'PurchasePrice': {'maximum': 99000000,
                                                              'minimum': 0,
                                                              'type': 'number',
                                                              'description': 'Purchase price of the article '
                                                                             'in domestic currency. When '
                                                                             'saved on the article this is '
                                                                             'rounded to 2 decimals.',
                                                              'format': 'double'},
                                            'Note': {'maxLength': 4000,
                                                     'minLength': 0,
                                                     'type': 'string',
                                                     'description': 'Article Note',
                                                     'nullable': True}}},
                    'response': 'object'},
 'list_suppliers': {'method': 'GET',
                    'path': '/suppliers',
                    'summary': 'Get suppliers',
                    'parameters': [{'name': '$page',
                                    'in': 'query',
                                    'required': False,
                                    'schema': {'type': 'integer',
                                               'minimum': 1,
                                               'maximum': 2147483647,
                                               'default': 1},
                                    'field': 'page'},
                                   {'name': '$pagesize',
                                    'in': 'query',
                                    'required': False,
                                    'schema': {'type': 'integer',
                                               'minimum': 1,
                                               'maximum': 1000,
                                               'default': 50},
                                    'field': 'page_size'}],
                    'scope': 'ea:purchase',
                    'response': 'page'},
 'get_supplier': {'method': 'GET',
                  'path': '/suppliers/{id}',
                  'summary': 'Get a supplier',
                  'parameters': [{'name': 'id',
                                  'in': 'path',
                                  'description': 'This represents the Id of the Supplier.',
                                  'required': True,
                                  'schema': {'type': 'string', 'format': 'uuid'}}],
                  'scope': 'ea:purchase',
                  'response': 'object'},
 'create_supplier': {'method': 'POST',
                     'path': '/suppliers',
                     'summary': 'Create a supplier',
                     'parameters': [],
                     'scope': 'ea:purchase',
                     'body': {'type': 'object',
                              'required': ['Name', 'TermsOfPaymentId'],
                              'properties': {'SupplierNumber': {'maxLength': 16,
                                                                'minLength': 0,
                                                                'type': 'string',
                                                                'description': 'Purpose: Unique identifier. '
                                                                               'If not provided, Bookkeeping '
                                                                               '& Invoicing/eAccounting will '
                                                                               'provide one',
                                                                'nullable': True},
                                             'Address1': {'maxLength': 50,
                                                          'minLength': 0,
                                                          'type': 'string',
                                                          'description': 'Purpose: Street address of the '
                                                                         'supplier',
                                                          'nullable': True},
                                             'City': {'maxLength': 50,
                                                      'minLength': 0,
                                                      'type': 'string',
                                                      'nullable': True},
                                             'CorporateIdentityNumber': {'maxLength': 20,
                                                                         'minLength': 0,
                                                                         'type': 'string',
                                                                         'description': 'Purpose: Corporate '
                                                                                        'identity number of '
                                                                                        'the supplier',
                                                                         'nullable': True},
                                             'CountryCode': {'maxLength': 2,
                                                             'minLength': 0,
                                                             'type': 'string',
                                                             'description': 'Default value: Country of the '
                                                                            'user company',
                                                             'nullable': True},
                                             'CurrencyCode': {'maxLength': 3,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'Default value: Currency of the '
                                                                             'user company',
                                                              'nullable': True},
                                             'EmailAddress': {'maxLength': 255,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'Purpose: Email address of the '
                                                                             'supplier',
                                                              'nullable': True},
                                             'Name': {'maxLength': 50, 'minLength': 0, 'type': 'string'},
                                             'Note': {'maxLength': 4000,
                                                      'minLength': 0,
                                                      'type': 'string',
                                                      'description': 'Purpose: Custom note for the supplier',
                                                      'nullable': True},
                                             'PostalCode': {'maxLength': 10,
                                                            'minLength': 0,
                                                            'type': 'string',
                                                            'nullable': True},
                                             'Telephone': {'maxLength': 50,
                                                           'minLength': 0,
                                                           'type': 'string',
                                                           'description': 'Purpose: Phone number of the '
                                                                          'supplier',
                                                           'nullable': True},
                                             'TermsOfPaymentId': {'type': 'string',
                                                                  'description': 'Source: Get from '
                                                                                 '/v2/termsofpayment',
                                                                  'format': 'uuid'},
                                             'IsActive': {'type': 'boolean',
                                                          'description': 'Indicates if the supplier is '
                                                                         'active'}}},
                     'response': 'object'},
 'update_supplier': {'method': 'PUT',
                     'path': '/suppliers/{id}',
                     'summary': 'Replace a supplier',
                     'parameters': [{'name': 'id',
                                     'in': 'path',
                                     'description': 'This represents the Id of the Supplier.',
                                     'required': True,
                                     'schema': {'type': 'string', 'format': 'uuid'}}],
                     'scope': 'ea:purchase',
                     'body': {'type': 'object',
                              'required': ['Name', 'TermsOfPaymentId'],
                              'properties': {'SupplierNumber': {'maxLength': 16,
                                                                'minLength': 0,
                                                                'type': 'string',
                                                                'description': 'Purpose: Unique identifier. '
                                                                               'If not provided, Bookkeeping '
                                                                               '& Invoicing/eAccounting will '
                                                                               'provide one',
                                                                'nullable': True},
                                             'Address1': {'maxLength': 50,
                                                          'minLength': 0,
                                                          'type': 'string',
                                                          'description': 'Purpose: Street address of the '
                                                                         'supplier',
                                                          'nullable': True},
                                             'City': {'maxLength': 50,
                                                      'minLength': 0,
                                                      'type': 'string',
                                                      'nullable': True},
                                             'CorporateIdentityNumber': {'maxLength': 20,
                                                                         'minLength': 0,
                                                                         'type': 'string',
                                                                         'description': 'Purpose: Corporate '
                                                                                        'identity number of '
                                                                                        'the supplier',
                                                                         'nullable': True},
                                             'CountryCode': {'maxLength': 2,
                                                             'minLength': 0,
                                                             'type': 'string',
                                                             'description': 'Default value: Country of the '
                                                                            'user company',
                                                             'nullable': True},
                                             'CurrencyCode': {'maxLength': 3,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'Default value: Currency of the '
                                                                             'user company',
                                                              'nullable': True},
                                             'EmailAddress': {'maxLength': 255,
                                                              'minLength': 0,
                                                              'type': 'string',
                                                              'description': 'Purpose: Email address of the '
                                                                             'supplier',
                                                              'nullable': True},
                                             'Name': {'maxLength': 50, 'minLength': 0, 'type': 'string'},
                                             'Note': {'maxLength': 4000,
                                                      'minLength': 0,
                                                      'type': 'string',
                                                      'description': 'Purpose: Custom note for the supplier',
                                                      'nullable': True},
                                             'PostalCode': {'maxLength': 10,
                                                            'minLength': 0,
                                                            'type': 'string',
                                                            'nullable': True},
                                             'Telephone': {'maxLength': 50,
                                                           'minLength': 0,
                                                           'type': 'string',
                                                           'description': 'Purpose: Phone number of the '
                                                                          'supplier',
                                                           'nullable': True},
                                             'TermsOfPaymentId': {'type': 'string',
                                                                  'description': 'Source: Get from '
                                                                                 '/v2/termsofpayment',
                                                                  'format': 'uuid'},
                                             'IsActive': {'type': 'boolean',
                                                          'description': 'Indicates if the supplier is '
                                                                         'active'}}},
                     'response': 'object'},
 'list_customer_invoices': {'method': 'GET',
                            'path': '/customerinvoices',
                            'summary': 'Get all customer invoices',
                            'parameters': [{'name': 'modifiedSinceUtc',
                                            'in': 'query',
                                            'description': 'Used to get the invoices which have been '
                                                           'modified since a prompted date',
                                            'schema': {'type': 'string', 'format': 'date-time'}},
                                           {'name': '$page',
                                            'in': 'query',
                                            'required': False,
                                            'schema': {'type': 'integer',
                                                       'minimum': 1,
                                                       'maximum': 2147483647,
                                                       'default': 1},
                                            'field': 'page'},
                                           {'name': '$pagesize',
                                            'in': 'query',
                                            'required': False,
                                            'schema': {'type': 'integer',
                                                       'minimum': 1,
                                                       'maximum': 1000,
                                                       'default': 50},
                                            'field': 'page_size'}],
                            'scope': 'ea:sales',
                            'response': 'page'},
 'get_customer_invoice': {'method': 'GET',
                          'path': '/customerinvoices/{invoiceId}',
                          'summary': 'Gets a customer invoice with a specific id',
                          'parameters': [{'name': 'invoiceId',
                                          'in': 'path',
                                          'description': 'Customer invoice id',
                                          'required': True,
                                          'schema': {'type': 'string', 'format': 'uuid'}}],
                          'scope': 'ea:sales',
                          'response': 'object'},
 'create_customer_invoice': {'method': 'POST',
                             'path': '/customerinvoices',
                             'summary': 'Create a single customer invoice',
                             'parameters': [{'name': 'rotReducedAutomaticDistribution',
                                             'in': 'query',
                                             'description': 'Used for the automatic distribution per person '
                                                            'of the rot reduced invoicing amount',
                                             'schema': {'type': 'boolean', 'default': False}}],
                             'scope': 'ea:sales',
                             'body': {'type': 'object',
                                      'required': ['CustomerId',
                                                   'EuThirdParty',
                                                   'RotReducedInvoicingType',
                                                   'Rows'],
                                      'properties': {'EuThirdParty': {'type': 'boolean',
                                                                      'description': 'Default is false. True '
                                                                                     'only if EU '
                                                                                     'intermediary, VAT '
                                                                                     'triangulation rules '
                                                                                     'apply. Only if EU '
                                                                                     'company is invoicing '
                                                                                     'to a company from a '
                                                                                     'different EU country, '
                                                                                     'may set to True if '
                                                                                     'desired.'},
                                                     'CustomerId': {'type': 'string', 'format': 'uuid'},
                                                     'Rows': {'type': 'array',
                                                              'items': {'type': 'object',
                                                                        'required': [],
                                                                        'properties': {'ArticleId': {'type': 'string',
                                                                                                     'description': 'Purpose: '
                                                                                                                    'Null '
                                                                                                                    'if '
                                                                                                                    'text '
                                                                                                                    'row',
                                                                                                     'format': 'uuid',
                                                                                                     'nullable': True},
                                                                                       'Text': {'maxLength': 2000,
                                                                                                'minLength': 0,
                                                                                                'type': 'string',
                                                                                                'description': 'Default: '
                                                                                                               'For '
                                                                                                               'non '
                                                                                                               'text '
                                                                                                               'rows, '
                                                                                                               'default '
                                                                                                               'value '
                                                                                                               'will '
                                                                                                               'be '
                                                                                                               'the '
                                                                                                               "article's "
                                                                                                               'name; '
                                                                                                               'for '
                                                                                                               'text '
                                                                                                               'rows, '
                                                                                                               'there '
                                                                                                               'should '
                                                                                                               'be '
                                                                                                               'at '
                                                                                                               'least '
                                                                                                               'one '
                                                                                                               'character '
                                                                                                               'in '
                                                                                                               'place',
                                                                                                'nullable': True},
                                                                                       'UnitPrice': {'type': 'number',
                                                                                                     'description': 'Format: '
                                                                                                                    '2 '
                                                                                                                    'decimals '
                                                                                                                    'allowed '
                                                                                                                    'if '
                                                                                                                    'the '
                                                                                                                    'customer '
                                                                                                                    'and '
                                                                                                                    'currency '
                                                                                                                    'are '
                                                                                                                    'domestic '
                                                                                                                    'or '
                                                                                                                    '4 '
                                                                                                                    'decimals '
                                                                                                                    'if '
                                                                                                                    'customer '
                                                                                                                    'or '
                                                                                                                    'currency '
                                                                                                                    'is '
                                                                                                                    'foreign',
                                                                                                     'format': 'double'},
                                                                                       'DiscountPercentage': {'maximum': 1,
                                                                                                              'minimum': 0,
                                                                                                              'type': 'number',
                                                                                                              'description': 'Percentage '
                                                                                                                             'discount '
                                                                                                                             'n '
                                                                                                                             'the '
                                                                                                                             'row. '
                                                                                                                             'Format: '
                                                                                                                             '4 '
                                                                                                                             'decimals',
                                                                                                              'format': 'double'},
                                                                                       'Quantity': {'type': 'number',
                                                                                                    'description': 'Format: '
                                                                                                                   '4 '
                                                                                                                   'decimals',
                                                                                                    'format': 'double'},
                                                                                       'IsVatFree': {'type': 'boolean',
                                                                                                     'description': 'True '
                                                                                                                    'if '
                                                                                                                    'this '
                                                                                                                    'row '
                                                                                                                    'is '
                                                                                                                    'marked '
                                                                                                                    'as '
                                                                                                                    'VAT '
                                                                                                                    'free. '
                                                                                                                    'False '
                                                                                                                    'otherwise'}}}},
                                                     'InvoiceDate': {'type': 'string',
                                                                     'format': 'date-time',
                                                                     'nullable': True},
                                                     'DueDate': {'type': 'string',
                                                                 'format': 'date-time',
                                                                 'nullable': True},
                                                     'RotReducedInvoicingType': {'maximum': 2,
                                                                                 'minimum': 0,
                                                                                 'type': 'integer',
                                                                                 'description': '<strong>Possible '
                                                                                                'values:</strong><br/>0 '
                                                                                                '= '
                                                                                                'Normal,<br/>1 '
                                                                                                '= '
                                                                                                'Rot,<br/>2 '
                                                                                                '= Rut',
                                                                                 'format': 'int32'},
                                                     'OurReference': {'maxLength': 100,
                                                                      'minLength': 0,
                                                                      'type': 'string',
                                                                      'nullable': True},
                                                     'YourReference': {'maxLength': 100,
                                                                       'minLength': 0,
                                                                       'type': 'string',
                                                                       'nullable': True},
                                                     'TermsOfPaymentId': {'type': 'string',
                                                                          'description': 'Specify a '
                                                                                         'different terms of '
                                                                                         'payment for the '
                                                                                         'invoice. If not '
                                                                                         "filled customer's "
                                                                                         'terms of payment '
                                                                                         'will be used',
                                                                          'format': 'uuid'}}},
                             'response': 'object'},
 'list_customer_invoice_drafts': {'method': 'GET',
                                  'path': '/customerinvoicedrafts',
                                  'summary': 'Get all customer invoice drafts',
                                  'parameters': [{'name': '$page',
                                                  'in': 'query',
                                                  'required': False,
                                                  'schema': {'type': 'integer',
                                                             'minimum': 1,
                                                             'maximum': 2147483647,
                                                             'default': 1},
                                                  'field': 'page'},
                                                 {'name': '$pagesize',
                                                  'in': 'query',
                                                  'required': False,
                                                  'schema': {'type': 'integer',
                                                             'minimum': 1,
                                                             'maximum': 1000,
                                                             'default': 50},
                                                  'field': 'page_size'}],
                                  'scope': 'ea:sales',
                                  'response': 'page'},
 'get_customer_invoice_draft': {'method': 'GET',
                                'path': '/customerinvoicedrafts/{invoiceDraftId}',
                                'summary': 'Get a customer invoice draft by id',
                                'parameters': [{'name': 'invoiceDraftId',
                                                'in': 'path',
                                                'description': 'Id of the draft',
                                                'required': True,
                                                'schema': {'type': 'string', 'format': 'uuid'}}],
                                'scope': 'ea:sales',
                                'response': 'object'},
 'create_customer_invoice_draft': {'method': 'POST',
                                   'path': '/customerinvoicedrafts',
                                   'summary': 'Create a single customer invoice draft',
                                   'parameters': [{'name': 'overrideCustomerIsPrivatePerson',
                                                   'in': 'query',
                                                   'description': 'True to override if the customer on the '
                                                                  'draft is a private individual',
                                                   'schema': {'type': 'boolean', 'default': False}}],
                                   'scope': 'ea:sales',
                                   'body': {'type': 'object',
                                            'required': ['CustomerId',
                                                         'EuThirdParty',
                                                         'RotReducedInvoicingType'],
                                            'properties': {'CustomerId': {'type': 'string',
                                                                          'description': 'Source: Get from '
                                                                                         '/v2/customers',
                                                                          'format': 'uuid'},
                                                           'RotReducedInvoicingType': {'enum': [0, 1, 2],
                                                                                       'type': 'integer',
                                                                                       'format': 'int32'},
                                                           'Rows': {'type': 'array',
                                                                    'items': {'type': 'object',
                                                                              'required': ['IsTextRow',
                                                                                           'ReversedConstructionServicesVatFree'],
                                                                              'properties': {'ArticleId': {'type': 'string',
                                                                                                           'description': 'Source: '
                                                                                                                          'Get '
                                                                                                                          'from '
                                                                                                                          '/v2/articles. '
                                                                                                                          'Required '
                                                                                                                          'if '
                                                                                                                          'IsTextRow '
                                                                                                                          'is '
                                                                                                                          'false',
                                                                                                           'format': 'uuid',
                                                                                                           'nullable': True},
                                                                                             'IsTextRow': {'type': 'boolean'},
                                                                                             'Text': {'maxLength': 2000,
                                                                                                      'minLength': 0,
                                                                                                      'type': 'string',
                                                                                                      'description': 'Default: '
                                                                                                                     'For '
                                                                                                                     'non '
                                                                                                                     'text '
                                                                                                                     'rows, '
                                                                                                                     'default '
                                                                                                                     'value '
                                                                                                                     'will '
                                                                                                                     'be '
                                                                                                                     'the '
                                                                                                                     "article's "
                                                                                                                     'name; '
                                                                                                                     'for '
                                                                                                                     'text '
                                                                                                                     'rows, '
                                                                                                                     'there '
                                                                                                                     'should '
                                                                                                                     'be '
                                                                                                                     'at '
                                                                                                                     'least '
                                                                                                                     'one '
                                                                                                                     'character '
                                                                                                                     'in '
                                                                                                                     'place',
                                                                                                      'nullable': True},
                                                                                             'UnitPrice': {'type': 'number',
                                                                                                           'description': 'Format: '
                                                                                                                          '2 '
                                                                                                                          'decimals '
                                                                                                                          'allowed '
                                                                                                                          'if '
                                                                                                                          'the '
                                                                                                                          'customer '
                                                                                                                          'is '
                                                                                                                          'domestic '
                                                                                                                          'or '
                                                                                                                          '4 '
                                                                                                                          'decimals '
                                                                                                                          'if '
                                                                                                                          'foreign. '
                                                                                                                          'When '
                                                                                                                          'omitted '
                                                                                                                          'and '
                                                                                                                          'ArticleId '
                                                                                                                          'is '
                                                                                                                          'provided, '
                                                                                                                          'the '
                                                                                                                          "article's "
                                                                                                                          'stored '
                                                                                                                          'price '
                                                                                                                          'may '
                                                                                                                          'be '
                                                                                                                          'used '
                                                                                                                          'automatically '
                                                                                                                          'depending '
                                                                                                                          'on '
                                                                                                                          'account '
                                                                                                                          'configuration '
                                                                                                                          '(net '
                                                                                                                          'price '
                                                                                                                          'or '
                                                                                                                          'gross '
                                                                                                                          'price '
                                                                                                                          'depending '
                                                                                                                          'on '
                                                                                                                          'whether '
                                                                                                                          'the '
                                                                                                                          'invoice '
                                                                                                                          'includes '
                                                                                                                          'VAT). '
                                                                                                                          'An '
                                                                                                                          'explicitly '
                                                                                                                          'provided '
                                                                                                                          'value '
                                                                                                                          'is '
                                                                                                                          'always '
                                                                                                                          'used '
                                                                                                                          'as-is. '
                                                                                                                          'The '
                                                                                                                          'default '
                                                                                                                          'behavior '
                                                                                                                          'when '
                                                                                                                          'unit '
                                                                                                                          'price '
                                                                                                                          'is '
                                                                                                                          'zero '
                                                                                                                          'is '
                                                                                                                          'specified '
                                                                                                                          'by '
                                                                                                                          'setting '
                                                                                                                          'ReplaceUnitPriceWhenZero '
                                                                                                                          'on '
                                                                                                                          'the '
                                                                                                                          'customer '
                                                                                                                          'invoice '
                                                                                                                          'draft.',
                                                                                                           'format': 'double',
                                                                                                           'nullable': True},
                                                                                             'DiscountPercentage': {'maximum': 1,
                                                                                                                    'minimum': 0,
                                                                                                                    'type': 'number',
                                                                                                                    'description': 'Format: '
                                                                                                                                   '4 '
                                                                                                                                   'decimals '
                                                                                                                                   'allowed. '
                                                                                                                                   'Discount '
                                                                                                                                   'of '
                                                                                                                                   'the '
                                                                                                                                   'row '
                                                                                                                                   'in '
                                                                                                                                   'percentage.',
                                                                                                                    'format': 'double'},
                                                                                             'Quantity': {'type': 'number',
                                                                                                          'description': 'Format: '
                                                                                                                         '2 '
                                                                                                                         'decimals. '
                                                                                                                         'Quantity '
                                                                                                                         'of '
                                                                                                                         'the '
                                                                                                                         'article '
                                                                                                                         'on '
                                                                                                                         'the '
                                                                                                                         'row.',
                                                                                                          'format': 'double'},
                                                                                             'ReversedConstructionServicesVatFree': {'type': 'boolean'}}},
                                                                    'nullable': True},
                                                           'YourReference': {'maxLength': 100,
                                                                             'minLength': 0,
                                                                             'type': 'string',
                                                                             'nullable': True},
                                                           'OurReference': {'maxLength': 100,
                                                                            'minLength': 0,
                                                                            'type': 'string',
                                                                            'nullable': True},
                                                           'TermsOfPaymentId': {'type': 'string',
                                                                                'description': 'Specify a '
                                                                                               'different '
                                                                                               'terms of '
                                                                                               'payment for '
                                                                                               'the invoice. '
                                                                                               'If not '
                                                                                               'filled '
                                                                                               "customer's "
                                                                                               'terms of '
                                                                                               'payment will '
                                                                                               'be used',
                                                                                'format': 'uuid',
                                                                                'nullable': True},
                                                           'EuThirdParty': {'type': 'boolean'},
                                                           'InvoiceDate': {'type': 'string',
                                                                           'format': 'date-time',
                                                                           'nullable': True},
                                                           'DueDate': {'type': 'string',
                                                                       'description': 'Due date of the '
                                                                                      'customer invoice '
                                                                                      'draft',
                                                                       'format': 'date-time',
                                                                       'nullable': True}}},
                                   'response': 'object'},
 'update_customer_invoice_draft': {'method': 'PUT',
                                   'path': '/customerinvoicedrafts/{customerInvoiceDraftId}',
                                   'summary': 'Replace the data in a customer invoice draft',
                                   'parameters': [{'name': 'customerInvoiceDraftId',
                                                   'in': 'path',
                                                   'description': 'This is the id of the draft to update',
                                                   'required': True,
                                                   'schema': {'type': 'string', 'format': 'uuid'}}],
                                   'scope': 'ea:sales',
                                   'body': {'type': 'object',
                                            'required': ['CustomerId',
                                                         'EuThirdParty',
                                                         'RotReducedInvoicingType'],
                                            'properties': {'CustomerId': {'type': 'string',
                                                                          'description': 'Source: Get from '
                                                                                         '/v2/customers',
                                                                          'format': 'uuid'},
                                                           'RotReducedInvoicingType': {'enum': [0, 1, 2],
                                                                                       'type': 'integer',
                                                                                       'format': 'int32'},
                                                           'Rows': {'type': 'array',
                                                                    'items': {'type': 'object',
                                                                              'required': ['IsTextRow',
                                                                                           'ReversedConstructionServicesVatFree'],
                                                                              'properties': {'ArticleId': {'type': 'string',
                                                                                                           'description': 'Source: '
                                                                                                                          'Get '
                                                                                                                          'from '
                                                                                                                          '/v2/articles. '
                                                                                                                          'Required '
                                                                                                                          'if '
                                                                                                                          'IsTextRow '
                                                                                                                          'is '
                                                                                                                          'false',
                                                                                                           'format': 'uuid',
                                                                                                           'nullable': True},
                                                                                             'IsTextRow': {'type': 'boolean'},
                                                                                             'Text': {'maxLength': 2000,
                                                                                                      'minLength': 0,
                                                                                                      'type': 'string',
                                                                                                      'description': 'Default: '
                                                                                                                     'For '
                                                                                                                     'non '
                                                                                                                     'text '
                                                                                                                     'rows, '
                                                                                                                     'default '
                                                                                                                     'value '
                                                                                                                     'will '
                                                                                                                     'be '
                                                                                                                     'the '
                                                                                                                     "article's "
                                                                                                                     'name; '
                                                                                                                     'for '
                                                                                                                     'text '
                                                                                                                     'rows, '
                                                                                                                     'there '
                                                                                                                     'should '
                                                                                                                     'be '
                                                                                                                     'at '
                                                                                                                     'least '
                                                                                                                     'one '
                                                                                                                     'character '
                                                                                                                     'in '
                                                                                                                     'place',
                                                                                                      'nullable': True},
                                                                                             'UnitPrice': {'type': 'number',
                                                                                                           'description': 'Format: '
                                                                                                                          '2 '
                                                                                                                          'decimals '
                                                                                                                          'allowed '
                                                                                                                          'if '
                                                                                                                          'the '
                                                                                                                          'customer '
                                                                                                                          'is '
                                                                                                                          'domestic '
                                                                                                                          'or '
                                                                                                                          '4 '
                                                                                                                          'decimals '
                                                                                                                          'if '
                                                                                                                          'foreign. '
                                                                                                                          'When '
                                                                                                                          'omitted '
                                                                                                                          'and '
                                                                                                                          'ArticleId '
                                                                                                                          'is '
                                                                                                                          'provided, '
                                                                                                                          'the '
                                                                                                                          "article's "
                                                                                                                          'stored '
                                                                                                                          'price '
                                                                                                                          'may '
                                                                                                                          'be '
                                                                                                                          'used '
                                                                                                                          'automatically '
                                                                                                                          'depending '
                                                                                                                          'on '
                                                                                                                          'account '
                                                                                                                          'configuration '
                                                                                                                          '(net '
                                                                                                                          'price '
                                                                                                                          'or '
                                                                                                                          'gross '
                                                                                                                          'price '
                                                                                                                          'depending '
                                                                                                                          'on '
                                                                                                                          'whether '
                                                                                                                          'the '
                                                                                                                          'invoice '
                                                                                                                          'includes '
                                                                                                                          'VAT). '
                                                                                                                          'An '
                                                                                                                          'explicitly '
                                                                                                                          'provided '
                                                                                                                          'value '
                                                                                                                          'is '
                                                                                                                          'always '
                                                                                                                          'used '
                                                                                                                          'as-is. '
                                                                                                                          'The '
                                                                                                                          'default '
                                                                                                                          'behavior '
                                                                                                                          'when '
                                                                                                                          'unit '
                                                                                                                          'price '
                                                                                                                          'is '
                                                                                                                          'zero '
                                                                                                                          'is '
                                                                                                                          'specified '
                                                                                                                          'by '
                                                                                                                          'setting '
                                                                                                                          'ReplaceUnitPriceWhenZero '
                                                                                                                          'on '
                                                                                                                          'the '
                                                                                                                          'customer '
                                                                                                                          'invoice '
                                                                                                                          'draft.',
                                                                                                           'format': 'double',
                                                                                                           'nullable': True},
                                                                                             'DiscountPercentage': {'maximum': 1,
                                                                                                                    'minimum': 0,
                                                                                                                    'type': 'number',
                                                                                                                    'description': 'Format: '
                                                                                                                                   '4 '
                                                                                                                                   'decimals '
                                                                                                                                   'allowed. '
                                                                                                                                   'Discount '
                                                                                                                                   'of '
                                                                                                                                   'the '
                                                                                                                                   'row '
                                                                                                                                   'in '
                                                                                                                                   'percentage.',
                                                                                                                    'format': 'double'},
                                                                                             'Quantity': {'type': 'number',
                                                                                                          'description': 'Format: '
                                                                                                                         '2 '
                                                                                                                         'decimals. '
                                                                                                                         'Quantity '
                                                                                                                         'of '
                                                                                                                         'the '
                                                                                                                         'article '
                                                                                                                         'on '
                                                                                                                         'the '
                                                                                                                         'row.',
                                                                                                          'format': 'double'},
                                                                                             'ReversedConstructionServicesVatFree': {'type': 'boolean'}}},
                                                                    'nullable': True},
                                                           'YourReference': {'maxLength': 100,
                                                                             'minLength': 0,
                                                                             'type': 'string',
                                                                             'nullable': True},
                                                           'OurReference': {'maxLength': 100,
                                                                            'minLength': 0,
                                                                            'type': 'string',
                                                                            'nullable': True},
                                                           'TermsOfPaymentId': {'type': 'string',
                                                                                'description': 'Specify a '
                                                                                               'different '
                                                                                               'terms of '
                                                                                               'payment for '
                                                                                               'the invoice. '
                                                                                               'If not '
                                                                                               'filled '
                                                                                               "customer's "
                                                                                               'terms of '
                                                                                               'payment will '
                                                                                               'be used',
                                                                                'format': 'uuid',
                                                                                'nullable': True},
                                                           'EuThirdParty': {'type': 'boolean'},
                                                           'InvoiceDate': {'type': 'string',
                                                                           'format': 'date-time',
                                                                           'nullable': True},
                                                           'DueDate': {'type': 'string',
                                                                       'description': 'Due date of the '
                                                                                      'customer invoice '
                                                                                      'draft',
                                                                       'format': 'date-time',
                                                                       'nullable': True}}},
                                   'response': 'object'},
 'delete_customer_invoice_draft': {'method': 'DELETE',
                                   'path': '/customerinvoicedrafts/{customerInvoiceDraftId}',
                                   'summary': 'Delete a customer invoice draft',
                                   'parameters': [{'name': 'customerInvoiceDraftId',
                                                   'in': 'path',
                                                   'description': 'The id of the draft you want to delete',
                                                   'required': True,
                                                   'schema': {'type': 'string', 'format': 'uuid'}}],
                                   'scope': 'ea:sales',
                                   'response': 'empty'},
 'list_terms_of_payment': {'method': 'GET',
                           'path': '/termsofpayments',
                           'summary': 'Get all terms of payments',
                           'parameters': [{'name': '$page',
                                           'in': 'query',
                                           'required': False,
                                           'schema': {'type': 'integer',
                                                      'minimum': 1,
                                                      'maximum': 2147483647,
                                                      'default': 1},
                                           'field': 'page'},
                                          {'name': '$pagesize',
                                           'in': 'query',
                                           'required': False,
                                           'schema': {'type': 'integer',
                                                      'minimum': 1,
                                                      'maximum': 1000,
                                                      'default': 50},
                                           'field': 'page_size'}],
                           'scope': 'ea:sales',
                           'response': 'page'},
 'list_units': {'method': 'GET',
                'path': '/units',
                'summary': 'Get units',
                'parameters': [{'name': '$page',
                                'in': 'query',
                                'required': False,
                                'schema': {'type': 'integer',
                                           'minimum': 1,
                                           'maximum': 2147483647,
                                           'default': 1},
                                'field': 'page'},
                               {'name': '$pagesize',
                                'in': 'query',
                                'required': False,
                                'schema': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 50},
                                'field': 'page_size'}],
                'scope': 'ea:sales',
                'response': 'page'},
 'list_article_account_codings': {'method': 'GET',
                                  'path': '/articleaccountcodings',
                                  'summary': 'Get article account codings',
                                  'parameters': [{'name': 'vatRateDate',
                                                  'in': 'query',
                                                  'description': 'Date to get VAT rates for. Defaults to '
                                                                 'today',
                                                  'schema': {'type': 'string'}},
                                                 {'name': '$page',
                                                  'in': 'query',
                                                  'required': False,
                                                  'schema': {'type': 'integer',
                                                             'minimum': 1,
                                                             'maximum': 2147483647,
                                                             'default': 1},
                                                  'field': 'page'},
                                                 {'name': '$pagesize',
                                                  'in': 'query',
                                                  'required': False,
                                                  'schema': {'type': 'integer',
                                                             'minimum': 1,
                                                             'maximum': 1000,
                                                             'default': 50},
                                                  'field': 'page_size'}],
                                  'scope': 'ea:sales',
                                  'response': 'page'}}
