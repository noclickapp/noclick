"""Clover Platform API operation catalog, from the per-operation official source URLs."""

CLOVER_OPERATIONS = {'cash_get_all_cash_events': {'name': 'cash_get_all_cash_events',
                              'label': 'Get all cash events',
                              'description': 'Retrieve all cash events for this merchant. Cash '
                                             'events can also be consumed by registering a Webhook '
                                             'callback. See '
                                             'https://docs.clover.com/build/webhooks/',
                              'category': 'Cash',
                              'method': 'GET',
                              'path': '/v3/merchants/{mId}/cash_events',
                              'params': [{'name': 'filter',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Filter fields: [employee.id, note, '
                                                         'amountChange, employee.name, type, '
                                                         'device.id, timestamp]',
                                          'type': 'string'},
                                         {'name': 'expand',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Expandable fields: [employee, device]',
                                          'type': 'string'}],
                              'body_required': False,
                              'body': False,
                              'source': 'https://docs.clover.com/dev/reference/cashgetallcashevents.md'},
 'category_create_category': {'name': 'category_create_category',
                              'label': 'Create an item category',
                              'description': 'Create an item category',
                              'category': 'Inventory',
                              'method': 'POST',
                              'path': '/v3/merchants/{mId}/categories',
                              'params': [{'name': 'expand',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Expandable field: [items]',
                                          'type': 'string'}],
                              'body_required': False,
                              'body': True,
                              'source': 'https://docs.clover.com/dev/reference/categorycreatecategory.md'},
 'category_get_categories': {'name': 'category_get_categories',
                             'label': 'Get all categories',
                             'description': 'Retrieves all categories. Items display on the '
                                            'Register app within categories in the order in which '
                                            'they are added to a category. Items may be associated '
                                            'with one or more categories or may not be associated '
                                            'with any category. Categories display in the Register '
                                            'app based on the sort order value for each category.',
                             'category': 'Inventory',
                             'method': 'GET',
                             'path': '/v3/merchants/{mId}/categories',
                             'params': [{'name': 'filter',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Filter fields to display search results: '
                                                        '[modifiedTime, deleted, sortOrder, name, '
                                                        'colorCode, id]',
                                         'type': 'string'},
                                        {'name': 'expand',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Additional information provided as an '
                                                        'expanded response: [items]',
                                         'type': 'string'},
                                        {'name': 'offset',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Position of the first line item returned '
                                                        'in the search results. Indicates the '
                                                        'number of line items that are excluded '
                                                        'from the search results.',
                                         'type': 'integer'},
                                        {'name': 'limit',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Maximum number of line items returned in '
                                                        'the search result.\n'
                                                        ' Default: 100 \n'
                                                        ' Maximum limit: 1000',
                                         'type': 'integer'}],
                             'body_required': False,
                             'body': False,
                             'source': 'https://docs.clover.com/dev/reference/categorygetcategories.md'},
 'category_get_category': {'name': 'category_get_category',
                           'label': 'Get a category',
                           'description': 'Get a category',
                           'category': 'Inventory',
                           'method': 'GET',
                           'path': '/v3/merchants/{mId}/categories/{catId}',
                           'params': [{'name': 'expand',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Expandable field: [items]',
                                       'type': 'string'}],
                           'body_required': False,
                           'body': False,
                           'source': 'https://docs.clover.com/dev/reference/categorygetcategory.md'},
 'category_get_category_items': {'name': 'category_get_category_items',
                                 'label': 'Get all items in a single category',
                                 'description': 'Retrieves all items in a category.',
                                 'category': 'Inventory',
                                 'method': 'GET',
                                 'path': '/v3/merchants/{mId}/categories/{catId}/items',
                                 'params': [{'name': 'filter',
                                             'in': 'query',
                                             'required': False,
                                             'description': 'Filter fields to display search '
                                                            'results: [modifiedTime, deleted, '
                                                            'sortOrder, name, colorCode, id]',
                                             'type': 'string'},
                                            {'name': 'expand',
                                             'in': 'query',
                                             'required': False,
                                             'description': 'Expandable fields to display '
                                                            'additional nested information: '
                                                            '[categories, itemStock, '
                                                            'modifierRates, options, tags, '
                                                            'taxRates]',
                                             'type': 'string'},
                                            {'name': 'offset',
                                             'in': 'query',
                                             'required': False,
                                             'description': 'Position of the first line item '
                                                            'returned in the search results. '
                                                            'Indicates the number of line items '
                                                            'that are excluded from the search '
                                                            'results.',
                                             'type': 'integer'},
                                            {'name': 'limit',
                                             'in': 'query',
                                             'required': False,
                                             'description': 'Maximum number of line items returned '
                                                            'in the search result.\n'
                                                            ' Default: 100 \n'
                                                            ' Maximum limit: 1000',
                                             'type': 'integer'}],
                                 'body_required': False,
                                 'body': False,
                                 'source': 'https://docs.clover.com/dev/reference/categorygetcategoryitems.md'},
 'category_get_item_categories': {'name': 'category_get_item_categories',
                                  'label': 'Get all categories of a single item',
                                  'description': 'Retrieves all categories of an item.',
                                  'category': 'Inventory',
                                  'method': 'GET',
                                  'path': '/v3/merchants/{mId}/items/{itemId}/categories',
                                  'params': [{'name': 'filter',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Filter fields to display search '
                                                             'results: [modifiedTime, deleted, '
                                                             'sortOrder, name, colorCode, id]',
                                              'type': 'string'},
                                             {'name': 'expand',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Expandable fields to display '
                                                             'additional nested information: '
                                                             '[items]',
                                              'type': 'string'},
                                             {'name': 'offset',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Position of the first line item '
                                                             'returned in the search results. '
                                                             'Indicates the number of line items '
                                                             'that are excluded from the search '
                                                             'results.',
                                              'type': 'integer'},
                                             {'name': 'limit',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Maximum number of line items '
                                                             'returned in the search result.\n'
                                                             ' Default: 100 \n'
                                                             ' Maximum limit: 1000',
                                              'type': 'integer'}],
                                  'body_required': False,
                                  'body': False,
                                  'source': 'https://docs.clover.com/dev/reference/categorygetitemcategories.md'},
 'category_update_category': {'name': 'category_update_category',
                              'label': 'Update a category',
                              'description': 'Update a category',
                              'category': 'Inventory',
                              'method': 'POST',
                              'path': '/v3/merchants/{mId}/categories/{catId}',
                              'params': [{'name': 'expand',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Expandable field: [items]',
                                          'type': 'string'}],
                              'body_required': False,
                              'body': True,
                              'source': 'https://docs.clover.com/dev/reference/categoryupdatecategory.md'},
 'customers_create_customer': {'name': 'customers_create_customer',
                               'label': 'Create a customer',
                               'description': 'Creates customer record for a merchant. Note that '
                                              'the request body cannot be null.',
                               'category': 'Customers',
                               'method': 'POST',
                               'path': '/v3/merchants/{mId}/customers',
                               'params': [{'name': 'expand',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Expandable fields to display additional '
                                                          'nested information: [addresses, '
                                                          'emailAddresses, phoneNumbers, cards, '
                                                          'metadata]',
                                           'type': 'string'}],
                               'body_required': False,
                               'body': True,
                               'source': 'https://docs.clover.com/dev/reference/customerscreatecustomer.md'},
 'customers_delete_customer': {'name': 'customers_delete_customer',
                               'label': 'Delete a customer',
                               'description': 'Deletes a single customer from a merchant.',
                               'category': 'Customers',
                               'method': 'DELETE',
                               'path': '/v3/merchants/{mId}/customers/{customerId}',
                               'params': [],
                               'body_required': False,
                               'body': False,
                               'source': 'https://docs.clover.com/dev/reference/customersdeletecustomer.md'},
 'customers_get_customer': {'name': 'customers_get_customer',
                            'label': 'Get a single customer',
                            'description': 'Returns information for a single customer.',
                            'category': 'Customers',
                            'method': 'GET',
                            'path': '/v3/merchants/{mId}/customers/{customerId}',
                            'params': [{'name': 'filter',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Filter fields: [customerSince, firstName, '
                                                       'lastName, emailAddress, phoneNumber, '
                                                       'marketingAllowed, fullName, id, '
                                                       'deletedTime]',
                                        'type': 'string'},
                                       {'name': 'expand',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Expandable fields: [addresses, '
                                                       'emailAddresses, phoneNumbers, cards, '
                                                       'metadata]',
                                        'type': 'string'}],
                            'body_required': False,
                            'body': False,
                            'source': 'https://docs.clover.com/dev/reference/customersgetcustomer.md'},
 'customers_get_customers': {'name': 'customers_get_customers',
                             'label': 'Get a list of customers',
                             'description': 'Gives information for every customer of a merchant by '
                                            'default.',
                             'category': 'Customers',
                             'method': 'GET',
                             'path': '/v3/merchants/{mId}/customers',
                             'params': [{'name': 'filter',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Filter fields: [customerSince, firstName, '
                                                        'lastName, emailAddress, phoneNumber, '
                                                        'marketingAllowed, fullName, id, '
                                                        'deletedTime]',
                                         'type': 'string'},
                                        {'name': 'expand',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Expandable fields: [addresses, '
                                                        'emailAddresses, phoneNumbers, cards, '
                                                        'metadata]',
                                         'type': 'string'}],
                             'body_required': False,
                             'body': False,
                             'source': 'https://docs.clover.com/dev/reference/customersgetcustomers.md'},
 'customers_update_customer': {'name': 'customers_update_customer',
                               'label': 'Update a customer',
                               'description': 'Updates information for a single customer.',
                               'category': 'Customers',
                               'method': 'POST',
                               'path': '/v3/merchants/{mId}/customers/{customerId}',
                               'params': [{'name': 'expand',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Expandable fields to display additional '
                                                          'nested information: [addresses, '
                                                          'emailAddresses, phoneNumbers, cards, '
                                                          'metadata]',
                                           'type': 'string'}],
                               'body_required': False,
                               'body': True,
                               'source': 'https://docs.clover.com/dev/reference/customersupdatecustomer.md'},
 'employee_get_employee': {'name': 'employee_get_employee',
                           'label': 'Get a single employee',
                           'description': 'Returns information for a single employee. Accepts '
                                          'optional expand query parameters',
                           'category': 'Employees',
                           'method': 'GET',
                           'path': '/v3/merchants/{mId}/employees/{empId}',
                           'params': [{'name': 'expand',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Expandable fields: [roles, shifts]',
                                       'type': 'string'}],
                           'body_required': False,
                           'body': False,
                           'source': 'https://docs.clover.com/dev/reference/employeegetemployee.md'},
 'employee_get_employee_shifts': {'name': 'employee_get_employee_shifts',
                                  'label': 'Get all shifts for an employee',
                                  'description': 'Get all shifts for an employee',
                                  'category': 'Employees',
                                  'method': 'GET',
                                  'path': '/v3/merchants/{mId}/employees/{empId}/shifts',
                                  'params': [{'name': 'filter',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Filter fields: [employee.id, '
                                                             'out_time, in_time, employee.name, '
                                                             'in_and_override_time, '
                                                             'out_and_override_time, id, '
                                                             'has_in_time, override_in_time, '
                                                             'deletedTime, server_banking]',
                                              'type': 'string'},
                                             {'name': 'expand',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Expandable fields: [employee, '
                                                             'overrideInEmployee, '
                                                             'overrideOutEmployee]',
                                              'type': 'string'}],
                                  'body_required': False,
                                  'body': False,
                                  'source': 'https://docs.clover.com/dev/reference/employeegetemployeeshifts.md'},
 'employee_get_employees': {'name': 'employee_get_employees',
                            'label': 'Get all employees',
                            'description': 'Retrieves information about employees associated with '
                                           'a merchant.',
                            'category': 'Employees',
                            'method': 'GET',
                            'path': '/v3/merchants/{mId}/employees',
                            'params': [{'name': 'filter',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Filter fields to display search results: '
                                                       '[modifiedTime, role, role.id, customId, '
                                                       'name, nickname, id, deletedTime, '
                                                       'deleted_time, email]',
                                        'type': 'string'},
                                       {'name': 'expand',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Expandable fields to display additional '
                                                       'nested information: [roles, shifts]',
                                        'type': 'string'}],
                            'body_required': False,
                            'body': False,
                            'source': 'https://docs.clover.com/dev/reference/employeegetemployees.md'},
 'inventory_create_discount': {'name': 'inventory_create_discount',
                               'label': 'Create a discount',
                               'description': 'Create a discount',
                               'category': 'Inventory',
                               'method': 'POST',
                               'path': '/v3/merchants/{mId}/discounts',
                               'params': [],
                               'body_required': False,
                               'body': True,
                               'source': 'https://docs.clover.com/dev/reference/inventorycreatediscount.md'},
 'inventory_create_item': {'name': 'inventory_create_item',
                           'label': 'Create an inventory item',
                           'description': 'Creates an inventory item.',
                           'category': 'Inventory',
                           'method': 'POST',
                           'path': '/v3/merchants/{mId}/items',
                           'params': [{'name': 'expand',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Expandable fields to display additional '
                                                      'nested information: [tags, categories, '
                                                      'taxRates, modifierGroups, itemStock, '
                                                      'options, ageRestricted]',
                                       'type': 'string'}],
                           'body_required': False,
                           'body': True,
                           'source': 'https://docs.clover.com/dev/reference/inventorycreateitem.md'},
 'inventory_create_item_group': {'name': 'inventory_create_item_group',
                                 'label': 'Create an item group',
                                 'description': 'Create an item group',
                                 'category': 'Inventory',
                                 'method': 'POST',
                                 'path': '/v3/merchants/{mId}/item_groups',
                                 'params': [{'name': 'expand',
                                             'in': 'query',
                                             'required': False,
                                             'description': 'Expandable fields: [items, '
                                                            'attributes]',
                                             'type': 'string'}],
                                 'body_required': False,
                                 'body': True,
                                 'source': 'https://docs.clover.com/dev/reference/inventorycreateitemgroup.md'},
 'inventory_create_item_stock': {'name': 'inventory_create_item_stock',
                                 'label': 'Create item stock',
                                 'description': 'Create a stock count for a single item.',
                                 'category': 'Inventory',
                                 'method': 'POST',
                                 'path': '/v3/merchants/{mId}/item_stocks/{itemId}',
                                 'params': [],
                                 'body_required': False,
                                 'body': True,
                                 'source': 'https://docs.clover.com/dev/reference/inventorycreateitemstock.md'},
 'inventory_delete_item': {'name': 'inventory_delete_item',
                           'label': 'Delete an inventory item',
                           'description': 'Delete an inventory item',
                           'category': 'Inventory',
                           'method': 'DELETE',
                           'path': '/v3/merchants/{mId}/items/{itemId}',
                           'params': [],
                           'body_required': False,
                           'body': False,
                           'source': 'https://docs.clover.com/dev/reference/inventorydeleteitem.md'},
 'inventory_get_discount': {'name': 'inventory_get_discount',
                            'label': 'Get a single discount',
                            'description': 'Get a single discount',
                            'category': 'Inventory',
                            'method': 'GET',
                            'path': '/v3/merchants/{mId}/discounts/{discountId}',
                            'params': [],
                            'body_required': False,
                            'body': False,
                            'source': 'https://docs.clover.com/dev/reference/inventorygetdiscount.md'},
 'inventory_get_discounts': {'name': 'inventory_get_discounts',
                             'label': 'Get all discounts',
                             'description': 'Retrieves all discounts associated with an inventory '
                                            'item.',
                             'category': 'Inventory',
                             'method': 'GET',
                             'path': '/v3/merchants/{mId}/discounts',
                             'params': [{'name': 'filter',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Filter fields to display search results: '
                                                        '[amount, modifiedtime, percentage, id]',
                                         'type': 'string'},
                                        {'name': 'offset',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Position of the first line item returned '
                                                        'in the search results. Indicates the '
                                                        'number of line items that are excluded '
                                                        'from the search results.',
                                         'type': 'integer'},
                                        {'name': 'limit',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Maximum number of line items returned in '
                                                        'the search result.\n'
                                                        ' Default: 100 \n'
                                                        ' Maximum limit: 1000',
                                         'type': 'integer'}],
                             'body_required': False,
                             'body': False,
                             'source': 'https://docs.clover.com/dev/reference/inventorygetdiscounts.md'},
 'inventory_get_item': {'name': 'inventory_get_item',
                        'label': 'Get a single inventory item',
                        'description': 'Retrieves an existing inventory item.',
                        'category': 'Inventory',
                        'method': 'GET',
                        'path': '/v3/merchants/{mId}/items/{itemId}',
                        'params': [{'name': 'expand',
                                    'in': 'query',
                                    'required': False,
                                    'description': 'Additional information provided as an expanded '
                                                   'response: [tags, categories, taxRates, '
                                                   'modifierGroups, itemStock, options]',
                                    'type': 'string'}],
                        'body_required': False,
                        'body': False,
                        'source': 'https://docs.clover.com/dev/reference/inventorygetitem.md'},
 'inventory_get_item_group': {'name': 'inventory_get_item_group',
                              'label': 'Get a single item group',
                              'description': 'Get a single item group',
                              'category': 'Inventory',
                              'method': 'GET',
                              'path': '/v3/merchants/{mId}/item_groups/{itemGroupId}',
                              'params': [{'name': 'expand',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Expandable fields: [items, attributes]',
                                          'type': 'string'}],
                              'body_required': False,
                              'body': False,
                              'source': 'https://docs.clover.com/dev/reference/inventorygetitemgroup.md'},
 'inventory_get_item_groups': {'name': 'inventory_get_item_groups',
                               'label': 'Get all item groups',
                               'description': 'Retrieves item groups that allow merchants to '
                                              'create and manage large groups of related items, '
                                              'also known as **Item with variants**. `For '
                                              'example:` A merchant sells a T-shirt that is '
                                              'available in various sizes and colors. Each of the '
                                              'T-shirt variations is an item within the T-shirt '
                                              'item group. When an item group is created, it '
                                              'appears in the Regist',
                               'category': 'Inventory',
                               'method': 'GET',
                               'path': '/v3/merchants/{mId}/item_groups',
                               'params': [{'name': 'filter',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Filter fields to display search '
                                                          'results: [modifiedTime, name, id, '
                                                          'deletedTime]',
                                           'type': 'string'},
                                          {'name': 'expand',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Additional information provided as an '
                                                          'expanded response: [items, attributes]',
                                           'type': 'string'},
                                          {'name': 'offset',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Position of the first line item '
                                                          'returned in the search results. '
                                                          'Indicates the number of line items that '
                                                          'are excluded from the search results.',
                                           'type': 'integer'},
                                          {'name': 'limit',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Maximum number of line items returned '
                                                          'in the search result.\n'
                                                          ' Default: 100 \n'
                                                          ' Maximum limit: 1000',
                                           'type': 'integer'}],
                               'body_required': False,
                               'body': False,
                               'source': 'https://docs.clover.com/dev/reference/inventorygetitemgroups.md'},
 'inventory_get_item_stock': {'name': 'inventory_get_item_stock',
                              'label': 'Get the stock of an inventory item',
                              'description': 'Get the stock of an inventory item',
                              'category': 'Inventory',
                              'method': 'GET',
                              'path': '/v3/merchants/{mId}/item_stocks/{itemId}',
                              'params': [],
                              'body_required': False,
                              'body': False,
                              'source': 'https://docs.clover.com/dev/reference/inventorygetitemstock.md'},
 'inventory_get_item_stocks': {'name': 'inventory_get_item_stocks',
                               'label': 'Get the stock of all inventory items',
                               'description': 'Get the stock of all inventory items',
                               'category': 'Inventory',
                               'method': 'GET',
                               'path': '/v3/merchants/{mId}/item_stocks',
                               'params': [],
                               'body_required': False,
                               'body': False,
                               'source': 'https://docs.clover.com/dev/reference/inventorygetitemstocks.md'},
 'inventory_get_items': {'name': 'inventory_get_items',
                         'label': 'Get all inventory items',
                         'description': 'Displays line items for each category in the inventory '
                                        'for an order.',
                         'category': 'Inventory',
                         'method': 'GET',
                         'path': '/v3/merchants/{mId}/items',
                         'params': [{'name': 'filter',
                                     'in': 'query',
                                     'required': False,
                                     'description': 'Filter fields to display search results: '
                                                    '[lowStock, modifiedTime, hidden, itemCode, '
                                                    'available, option.id, modifierGroup.id, '
                                                    'autoManage, price, id, sku, defaultTaxRates, '
                                                    'tags.id, alternateName, isRevenue, tags.name, '
                                                    'deleted, item.id, name, itemStock.q',
                                     'type': 'string'},
                                    {'name': 'expand',
                                     'in': 'query',
                                     'required': False,
                                     'description': 'Additional information provided as an '
                                                    'expanded response: [tags, categories, '
                                                    'taxRates, modifierGroups, itemStock, options, '
                                                    'ageRestricted]',
                                     'type': 'string'},
                                    {'name': 'offset',
                                     'in': 'query',
                                     'required': False,
                                     'description': 'Position of the first line item returned in '
                                                    'the search results. Indicates the number of '
                                                    'line items that are excluded from the search '
                                                    'results.',
                                     'type': 'integer'},
                                    {'name': 'limit',
                                     'in': 'query',
                                     'required': False,
                                     'description': 'Maximum number of line items returned in the '
                                                    'search result.\n'
                                                    ' Default: 100 \n'
                                                    ' Maximum limit: 1000',
                                     'type': 'integer'}],
                         'body_required': False,
                         'body': False,
                         'source': 'https://docs.clover.com/dev/reference/inventorygetitems.md'},
 'inventory_update_item': {'name': 'inventory_update_item',
                           'label': 'Update an existing inventory item',
                           'description': 'Updates an existing inventory item. Use the POST HTTP '
                                          'method to create an inventory item.<br><br><b>Note:</b> '
                                          "This endpoint cannot be used to update an item's stock "
                                          'quantity. To create or update stock for an item, you '
                                          'must use the <a '
                                          "href='https://docs.clover.com/dev/reference/inventoryupdateitemstock'>Update "
                                          'item stock</a> endpoint.',
                           'category': 'Inventory',
                           'method': 'POST',
                           'path': '/v3/merchants/{mId}/items/{itemId}',
                           'params': [{'name': 'expand',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Additional information provided as an '
                                                      'expanded response: [tags, categories, '
                                                      'taxRates, modifierGroups, itemStock, '
                                                      'options, ageRestricted]',
                                       'type': 'string'}],
                           'body_required': False,
                           'body': True,
                           'source': 'https://docs.clover.com/dev/reference/inventoryupdateitem.md'},
 'inventory_update_item_group': {'name': 'inventory_update_item_group',
                                 'label': 'Update an item group',
                                 'description': 'Update an item group',
                                 'category': 'Inventory',
                                 'method': 'POST',
                                 'path': '/v3/merchants/{mId}/item_groups/{itemGroupId}',
                                 'params': [{'name': 'expand',
                                             'in': 'query',
                                             'required': False,
                                             'description': 'Expandable fields: [items, '
                                                            'attributes]',
                                             'type': 'string'}],
                                 'body_required': False,
                                 'body': True,
                                 'source': 'https://docs.clover.com/dev/reference/inventoryupdateitemgroup.md'},
 'inventory_update_item_stock': {'name': 'inventory_update_item_stock',
                                 'label': 'Update the stock of an inventory item',
                                 'description': 'Update the stock of an inventory item',
                                 'category': 'Inventory',
                                 'method': 'PUT',
                                 'path': '/v3/merchants/{mId}/item_stocks/{itemId}',
                                 'params': [],
                                 'body_required': False,
                                 'body': True,
                                 'source': 'https://docs.clover.com/dev/reference/inventoryupdateitemstock.md'},
 'merchant_get_all_shifts': {'name': 'merchant_get_all_shifts',
                             'label': 'Get all shifts',
                             'description': 'Get all shifts',
                             'category': 'Employees',
                             'method': 'GET',
                             'path': '/v3/merchants/{mId}/shifts',
                             'params': [{'name': 'filter',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Filter fields: [employee.id, out_time, '
                                                        'in_time, employee.name, '
                                                        'in_and_override_time, '
                                                        'out_and_override_time, id, has_in_time, '
                                                        'override_in_time, deletedTime, '
                                                        'server_banking]',
                                         'type': 'string'},
                                        {'name': 'expand',
                                         'in': 'query',
                                         'required': False,
                                         'description': 'Expandable fields: [employee, '
                                                        'overrideInEmployee, overrideOutEmployee]',
                                         'type': 'string'}],
                             'body_required': False,
                             'body': False,
                             'source': 'https://docs.clover.com/dev/reference/merchantgetallshifts.md'},
 'get_merchant': {'name': 'get_merchant',
                  'label': 'Get a single merchant',
                  'description': 'Get a single merchant',
                  'category': 'Merchants',
                  'method': 'GET',
                  'path': '/v3/merchants/{mId}',
                  'params': [{'name': 'expand',
                              'in': 'query',
                              'required': False,
                              'description': 'Expandable fields to display additional nested '
                                             'information: [employees, bankProcessing, '
                                             'externalMerchant, merchantBoarding, '
                                             'merchantL3Prerequisite, deviceBoarding, '
                                             'programExpress, hierarchy, shifts, orders, address, '
                                             'logos, owner, items, tags, tenders',
                              'type': 'string'}],
                  'body_required': False,
                  'body': False,
                  'source': 'https://docs.clover.com/dev/reference/merchantgetmerchant.md'},
 'merchant_get_merchant_address': {'name': 'merchant_get_merchant_address',
                                   'label': "Get a merchant's address",
                                   'description': "Get a merchant's address",
                                   'category': 'Merchants',
                                   'method': 'GET',
                                   'path': '/v3/merchants/{mId}/address',
                                   'params': [],
                                   'body_required': False,
                                   'body': False,
                                   'source': 'https://docs.clover.com/dev/reference/merchantgetmerchantaddress.md'},
 'merchant_get_merchant_properties': {'name': 'merchant_get_merchant_properties',
                                      'label': "Get a merchant's properties",
                                      'description': "Get a merchant's properties",
                                      'category': 'Merchants',
                                      'method': 'GET',
                                      'path': '/v3/merchants/{mId}/properties',
                                      'params': [],
                                      'body_required': False,
                                      'body': False,
                                      'source': 'https://docs.clover.com/dev/reference/merchantgetmerchantproperties.md'},
 'merchant_get_order_types': {'name': 'merchant_get_order_types',
                              'label': 'Get all order types for a merchant',
                              'description': 'Retrieves all order types for a merchant. Merchants '
                                             'can create custom order types using the [Clover '
                                             'Setup App](https://www.clover.com/setupapp). These '
                                             'custom order types can be associated with a system '
                                             'order type. See [Return a list of system order '
                                             'types](https://docs.clover.com/reference/merchantgetsystemordertypes). '
                                             'Custom order types can support',
                              'category': 'Merchants',
                              'method': 'GET',
                              'path': '/v3/merchants/{mId}/order_types',
                              'params': [{'name': 'filter',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Filter fields to display search results: '
                                                         '[id, deletedTime]',
                                          'type': 'string'},
                                         {'name': 'expand',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Expandable fields to display additional '
                                                         'nested information: [hours, attributes, '
                                                         'categories]',
                                          'type': 'string'},
                                         {'name': 'offset',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Position of the first line item returned '
                                                         'in the search results. Indicates the '
                                                         'number of line items that are excluded '
                                                         'from the search results.',
                                          'type': 'integer'},
                                         {'name': 'limit',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Maximum number of line items returned in '
                                                         'the search result.\n'
                                                         ' Default: 100 \n'
                                                         ' Maximum limit: 1000',
                                          'type': 'integer'}],
                              'body_required': False,
                              'body': False,
                              'source': 'https://docs.clover.com/dev/reference/merchantgetordertypes.md'},
 'modifier_get_modifier_groups': {'name': 'modifier_get_modifier_groups',
                                  'label': 'Get all modifier groups',
                                  'description': 'Retrieves all modifier groups. Modifier '
                                                 'groupings are the categories to which different '
                                                 'modifiers belong. Modifier groups can be made '
                                                 'available for specific inventory Items by '
                                                 'creating an item to a modifier group '
                                                 'association.',
                                  'category': 'Inventory',
                                  'method': 'GET',
                                  'path': '/v3/merchants/{mId}/modifier_groups',
                                  'params': [{'name': 'filter',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Filter fields to display search '
                                                             'results: [modifiedTime, category.id, '
                                                             'negativeSortOrder, item.id, '
                                                             'sortOrder, name, id, showByDefault]',
                                              'type': 'string'},
                                             {'name': 'expand',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Expandable fields to display '
                                                             'additional nested information: '
                                                             '[modifiers, items]',
                                              'type': 'string'},
                                             {'name': 'offset',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Position of the first line item '
                                                             'returned in the search results. '
                                                             'Indicates the number of line items '
                                                             'that are excluded from the search '
                                                             'results.',
                                              'type': 'integer'},
                                             {'name': 'limit',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Maximum number of line items '
                                                             'returned in the search result.\n'
                                                             ' Default: 100 \n'
                                                             ' Maximum limit: 1000',
                                              'type': 'integer'}],
                                  'body_required': False,
                                  'body': False,
                                  'source': 'https://docs.clover.com/dev/reference/modifiergetmodifiergroups.md'},
 'modifier_get_modifiers': {'name': 'modifier_get_modifiers',
                            'label': 'Get all modifiers',
                            'description': 'Retrieves all modifiers from all modifier groups.',
                            'category': 'Inventory',
                            'method': 'GET',
                            'path': '/v3/merchants/{mId}/modifiers',
                            'params': [{'name': 'filter',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Filter fields to display search results: '
                                                       '[modifiedTime, price, name, alternateName, '
                                                       'id, modifierGroup.id]',
                                        'type': 'string'},
                                       {'name': 'expand',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Expandable fields to display additional '
                                                       'nested information: [modifierGroup]',
                                        'type': 'string'},
                                       {'name': 'offset',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Position of the first line item returned '
                                                       'in the search results. Indicates the '
                                                       'number of line items that are excluded '
                                                       'from the search results.',
                                        'type': 'integer'},
                                       {'name': 'limit',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Maximum number of line items returned in '
                                                       'the search result.\n'
                                                       ' Default: 100 \n'
                                                       ' Maximum limit: 1000',
                                        'type': 'integer'}],
                            'body_required': False,
                            'body': False,
                            'source': 'https://docs.clover.com/dev/reference/modifiergetmodifiers.md'},
 'order_create_line_item': {'name': 'order_create_line_item',
                            'label': 'Create a new line item',
                            'description': 'Creates a new line item for an order. Requests must '
                                           'include either a `price` or an `item` object with an '
                                           'inventory item `id`. **Note:** To ensure platform '
                                           'stability, an order is limited to a maximum of 3,000 '
                                           'line items. If this call would cause the order to '
                                           'exceed this limit, the request will fail with a `400 '
                                           'Bad Request` error.',
                            'category': 'Orders',
                            'method': 'POST',
                            'path': '/v3/merchants/{mId}/orders/{orderId}/line_items',
                            'params': [],
                            'body_required': False,
                            'body': True,
                            'source': 'https://docs.clover.com/dev/reference/ordercreatelineitem.md'},
 'order_create_order': {'name': 'order_create_order',
                        'label': 'Create custom orders',
                        'description': '**Description:** Creates or updates orders with a '
                                       'non-Clover inventory and dynamically calculates taxes. '
                                       'Valid fields are: taxRemoved, note, title, state, '
                                       'testMode, manualTransaction, groupLineItems, and '
                                       'orderType. Use separate API calls to add line items. <br> '
                                       '**Tip:** Use the [create an atomic '
                                       'order](https://docs.clover.com/dev/reference/ordercre',
                        'category': 'Orders',
                        'method': 'POST',
                        'path': '/v3/merchants/{mId}/orders',
                        'params': [],
                        'body_required': False,
                        'body': True,
                        'source': 'https://docs.clover.com/dev/reference/ordercreateorder.md'},
 'order_delete_order': {'name': 'order_delete_order',
                        'label': 'Delete an order',
                        'description': 'Deletes a single order. See '
                                       'https://docs.clover.com/build/working-with-orders/ for '
                                       'more details.',
                        'category': 'Orders',
                        'method': 'DELETE',
                        'path': '/v3/merchants/{mId}/orders/{orderId}',
                        'params': [],
                        'body_required': False,
                        'body': False,
                        'source': 'https://docs.clover.com/dev/reference/orderdeleteorder.md'},
 'order_get_order': {'name': 'order_get_order',
                     'label': 'Get a single order',
                     'description': 'Returns a single order. See '
                                    'https://docs.clover.com/build/working-with-orders/ for more '
                                    'details.',
                     'category': 'Orders',
                     'method': 'GET',
                     'path': '/v3/merchants/{mId}/orders/{orderId}',
                     'params': [{'name': 'expand',
                                 'in': 'query',
                                 'required': False,
                                 'description': 'Expandable fields: [lineItems, serviceCharge, '
                                                'discounts, credits, payments, customers, '
                                                'orderFulfillmentEvent, refunds]',
                                 'type': 'string'}],
                     'body_required': False,
                     'body': False,
                     'source': 'https://docs.clover.com/dev/reference/ordergetorder.md'},
 'order_get_order_line_item': {'name': 'order_get_order_line_item',
                               'label': 'Get a line item',
                               'description': 'Returns a line item for an order.',
                               'category': 'Orders',
                               'method': 'GET',
                               'path': '/v3/merchants/{mId}/orders/{orderId}/line_items/{lineItemId}',
                               'params': [{'name': 'expand',
                                           'in': 'query',
                                           'required': False,
                                           'description': 'Expandable fields: [employee, '
                                                          'orderType, discounts, modifications, '
                                                          'taxRates, payments]',
                                           'type': 'string'}],
                               'body_required': False,
                               'body': False,
                               'source': 'https://docs.clover.com/dev/reference/ordergetorderlineitem.md'},
 'order_get_order_line_items': {'name': 'order_get_order_line_items',
                                'label': 'Get all line items for an order',
                                'description': 'Returns all line items for an order.',
                                'category': 'Orders',
                                'method': 'GET',
                                'path': '/v3/merchants/{mId}/orders/{orderId}/line_items',
                                'params': [{'name': 'expand',
                                            'in': 'query',
                                            'required': False,
                                            'description': 'Expandable fields: [employee, '
                                                           'orderType, discounts, modifications, '
                                                           'taxRates, payments]',
                                            'type': 'string'}],
                                'body_required': False,
                                'body': False,
                                'source': 'https://docs.clover.com/dev/reference/ordergetorderlineitems.md'},
 'order_get_orders': {'name': 'order_get_orders',
                      'label': 'Gets a list of orders',
                      'description': 'Displays a list of orders. See [Manage orders '
                                     'data](https://docs.clover.com/build/working-with-orders/) '
                                     'for more details.',
                      'category': 'Orders',
                      'method': 'GET',
                      'path': '/v3/merchants/{mId}/orders',
                      'params': [{'name': 'filter',
                                  'in': 'query',
                                  'required': False,
                                  'description': 'Filter fields to display search results: '
                                                 '[employee.id, note, modifiedTime, orderType, '
                                                 'touched, cardTransaction.last4, '
                                                 'manualTransaction, employee.name, title, '
                                                 'device.id, externalReferenceId, '
                                                 'clientCreatedTime, total, payType, testMode, '
                                                 'createdTime, i',
                                  'type': 'string'},
                                 {'name': 'expand',
                                  'in': 'query',
                                  'required': False,
                                  'description': 'Additional information provided as an expanded '
                                                 'response: [employee, payments, refunds, credits, '
                                                 'voids, payment.tender, payment.cardTransaction, '
                                                 'lineItems, customers, serviceCharge, discounts, '
                                                 'orderType, lineItems.discounts, '
                                                 'lineItems.modifications]',
                                  'type': 'string'}],
                      'body_required': False,
                      'body': False,
                      'source': 'https://docs.clover.com/dev/reference/ordergetorders.md'},
 'order_update_order': {'name': 'order_update_order',
                        'label': 'Update an order',
                        'description': 'Updates a single order. See '
                                       '[working-with-orders](https://docs.clover.com/build/working-with-orders/) '
                                       'for more details.',
                        'category': 'Orders',
                        'method': 'POST',
                        'path': '/v3/merchants/{mId}/orders/{orderId}',
                        'params': [{'name': 'expand',
                                    'in': 'query',
                                    'required': False,
                                    'description': 'Additional information provided as an expanded '
                                                   'response: [lineItems, serviceCharge, '
                                                   'discounts, credits, payments, customers, '
                                                   'orderFulfillmentEvent, refunds]',
                                    'type': 'string'}],
                        'body_required': False,
                        'body': True,
                        'source': 'https://docs.clover.com/dev/reference/orderupdateorder.md'},
 'order_update_order_line_item': {'name': 'order_update_order_line_item',
                                  'label': 'Update a line item',
                                  'description': 'Updates a line item for an order.',
                                  'category': 'Orders',
                                  'method': 'POST',
                                  'path': '/v3/merchants/{mId}/orders/{orderId}/line_items/{lineItemId}',
                                  'params': [{'name': 'expand',
                                              'in': 'query',
                                              'required': False,
                                              'description': 'Additional information provided as '
                                                             'an expanded response: [employee, '
                                                             'orderType, discounts, modifications, '
                                                             'taxRates, payments]',
                                              'type': 'string'}],
                                  'body_required': False,
                                  'body': True,
                                  'source': 'https://docs.clover.com/dev/reference/orderupdateorderlineitem.md'},
 'pay_get_merchant_tenders': {'name': 'pay_get_merchant_tenders',
                              'label': 'Get all tenders for a merchant',
                              'description': 'Retrieves all tenders for a merchant.',
                              'category': 'Merchants',
                              'method': 'GET',
                              'path': '/v3/merchants/{mId}/tenders',
                              'params': [{'name': 'filter',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Filter fields to display search results: '
                                                         '[modifiedTime, visible, merchantId, '
                                                         'instruction, systemTenderId, label, id, '
                                                         'labelKey, opensCashDrawer, deletedTime, '
                                                         'enabled]',
                                          'type': 'string'},
                                         {'name': 'offset',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Position of the first line item returned '
                                                         'in the search results. Indicates the '
                                                         'number of line items that are excluded '
                                                         'from the search results.',
                                          'type': 'integer'},
                                         {'name': 'limit',
                                          'in': 'query',
                                          'required': False,
                                          'description': 'Maximum number of line items returned in '
                                                         'the search result.\n'
                                                         ' Default: 100 \n'
                                                         ' Maximum limit: 1000',
                                          'type': 'integer'}],
                              'body_required': False,
                              'body': False,
                              'source': 'https://docs.clover.com/dev/reference/paygetmerchanttenders.md'},
 'pay_get_order_payments': {'name': 'pay_get_order_payments',
                            'label': 'Get all payments for an order',
                            'description': 'Displays payment information, including the total '
                                           'amount, tip amount, tax amount, and result status for '
                                           'an `order`.',
                            'category': 'Payments',
                            'method': 'GET',
                            'path': '/v3/merchants/{mId}/orders/{orderId}/payments',
                            'params': [{'name': 'filter',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Filter fields to display search results: '
                                                       '[modifiedTime, device.id, '
                                                       'externalReferenceId, result, offline, '
                                                       'createdTime, externalPaymentId, voided, '
                                                       'id, tender.id, employee.id, '
                                                       'order.modifiedTime, amount, cardType, '
                                                       'clientCreatedTime]',
                                        'type': 'string'},
                                       {'name': 'expand',
                                        'in': 'query',
                                        'required': False,
                                        'description': 'Expandable fields to display additional '
                                                       'nested information: [tender, germanInfo, '
                                                       'lineItemPayments, cardTransaction, '
                                                       'dccInfo, employee, refunds, '
                                                       'transactionInfo, externalReferenceId, '
                                                       'oceanGatewayInfo, taxRates, '
                                                       'additionalCharges, appTracking, paymentA',
                                        'type': 'string'}],
                            'body_required': False,
                            'body': False,
                            'source': 'https://docs.clover.com/dev/reference/paygetorderpayments.md'},
 'pay_get_payment': {'name': 'pay_get_payment',
                     'label': 'Get a single payment',
                     'description': 'Retrieve a single payment information, including the total '
                                    'amount, tip amount, tax amount, and result status.',
                     'category': 'Payments',
                     'method': 'GET',
                     'path': '/v3/merchants/{mId}/payments/{payId}',
                     'params': [{'name': 'expand',
                                 'in': 'query',
                                 'required': False,
                                 'description': 'Expandable fields: [tender, germanInfo, '
                                                'lineItemPayments, cardTransaction, dccInfo, '
                                                'employee, refunds, transactionInfo, '
                                                'externalReferenceId, oceanGatewayInfo, taxRates, '
                                                'additionalCharges, appTracking, '
                                                'paymentAttributes, order]',
                                 'type': 'string'}],
                     'body_required': False,
                     'body': False,
                     'source': 'https://docs.clover.com/dev/reference/paygetpayment.md'},
 'pay_get_payments': {'name': 'pay_get_payments',
                      'label': 'Get all payments',
                      'description': 'Retrieves payment information, including the total amount, '
                                     'tip amount, tax amount, and result status.',
                      'category': 'Payments',
                      'method': 'GET',
                      'path': '/v3/merchants/{mId}/payments',
                      'params': [{'name': 'filter',
                                  'in': 'query',
                                  'required': False,
                                  'description': 'Filter fields to display search results: '
                                                 '[modifiedTime, device.id, externalReferenceId, '
                                                 'result, offline, createdTime, externalPaymentId, '
                                                 'voided, id, tender.id, employee.id, '
                                                 'order.modifiedTime, amount, cardType, '
                                                 'clientCreatedTime]',
                                  'type': 'string'},
                                 {'name': 'expand',
                                  'in': 'query',
                                  'required': False,
                                  'description': 'Expandable fields to display additional nested '
                                                 'information: [tender, germanInfo, '
                                                 'lineItemPayments, cardTransaction, dccInfo, '
                                                 'refunds, transactionInfo, externalReferenceId, '
                                                 'oceanGatewayInfo, taxRates, additionalCharges, '
                                                 'appTracking, paymentAttributes,',
                                  'type': 'string'}],
                      'body_required': False,
                      'body': False,
                      'source': 'https://docs.clover.com/dev/reference/paygetpayments.md'},
 'pay_get_refund': {'name': 'pay_get_refund',
                    'label': 'Get a single refund',
                    'description': 'Displays a single refund associated with a payment, including '
                                   'taxes and tips.',
                    'category': 'Payments',
                    'method': 'GET',
                    'path': '/v3/merchants/{mId}/refunds/{refundId}',
                    'params': [{'name': 'expand',
                                'in': 'query',
                                'required': False,
                                'description': 'Fields that display when the list is expanded: '
                                               '[payment, germanInfo, appTracking, employee, '
                                               'overrideMerchantTender, serviceCharge, lineItems, '
                                               'transactionInfo, oceanGatewayInfo]',
                                'type': 'string'}],
                    'body_required': False,
                    'body': False,
                    'source': 'https://docs.clover.com/dev/reference/paygetrefund-3.md'},
 'pay_get_refunds': {'name': 'pay_get_refunds',
                     'label': 'Get all refunds for a merchant',
                     'description': 'Retrieves refunds for a merchant, including associated taxes '
                                    'and tips. **Data Retrieval Rules:** * **90-Day Limit:** This '
                                    'endpoint returns a maximum of 90 days of refund data. * '
                                    "**Automatic Time-Filter Adjustment:** If a query's time-based "
                                    'filter (e.g., `createdTime` or `clientCreatedTime`) spans '
                                    'more than 90 days, the server automatically adjusts ',
                     'category': 'Payments',
                     'method': 'GET',
                     'path': '/v3/merchants/{mId}/refunds',
                     'params': [{'name': 'filter',
                                 'in': 'query',
                                 'required': False,
                                 'description': 'Filters the results based on a set of criteria. '
                                                'For detailed syntax, see the [API filtering '
                                                'documentation](https://docs.clover.com/dev/docs/applying-filters).\n'
                                                '\n'
                                                'Filter fields to display search results: [id, '
                                                'voided, createdTime, clientCreatedTime, orde',
                                 'type': 'string'},
                                {'name': 'expand',
                                 'in': 'query',
                                 'required': False,
                                 'description': 'Fields that display when the list is expanded: '
                                                '[payment, germanInfo, appTracking, employee, '
                                                'overrideMerchantTender, serviceCharge, lineItems, '
                                                'transactionInfo, oceanGatewayInfo]',
                                 'type': 'string'}],
                     'body_required': False,
                     'body': False,
                     'source': 'https://docs.clover.com/dev/reference/paygetrefunds-3.md'},
 'role_get_roles': {'name': 'role_get_roles',
                    'label': 'Get all roles for a merchant',
                    'description': "Retrieves all system and employee roles for a merchant's "
                                   'business.',
                    'category': 'Merchants',
                    'method': 'GET',
                    'path': '/v3/merchants/{mId}/roles',
                    'params': [{'name': 'filter',
                                'in': 'query',
                                'required': False,
                                'description': 'Filter fields to display search results: '
                                               '[modifiedTime, systemRole, name, id, deletedTime]',
                                'type': 'string'},
                               {'name': 'expand',
                                'in': 'query',
                                'required': False,
                                'description': 'Expandable fields to display additional nested '
                                               'information: [employees]',
                                'type': 'string'},
                               {'name': 'offset',
                                'in': 'query',
                                'required': False,
                                'description': 'Position of the first line item returned in the '
                                               'search results. Indicates the number of line items '
                                               'that are excluded from the search results.',
                                'type': 'integer'},
                               {'name': 'limit',
                                'in': 'query',
                                'required': False,
                                'description': 'Maximum number of line items returned in the '
                                               'search result.\n'
                                               ' Default: 100 \n'
                                               ' Maximum limit: 1000',
                                'type': 'integer'}],
                    'body_required': False,
                    'body': False,
                    'source': 'https://docs.clover.com/dev/reference/rolegetroles.md'},
 'tag_create_tag': {'name': 'tag_create_tag',
                    'label': 'Create a tag',
                    'description': 'Create a tag',
                    'category': 'Inventory',
                    'method': 'POST',
                    'path': '/v3/merchants/{mId}/tags',
                    'params': [],
                    'body_required': False,
                    'body': True,
                    'source': 'https://docs.clover.com/dev/reference/tagcreatetag.md'},
 'tag_get_tag': {'name': 'tag_get_tag',
                 'label': 'Get a single tag',
                 'description': 'Get a single tag',
                 'category': 'Inventory',
                 'method': 'GET',
                 'path': '/v3/merchants/{mId}/tags/{tagId}',
                 'params': [{'name': 'expand',
                             'in': 'query',
                             'required': False,
                             'description': 'Expandable fields: [items, printers]',
                             'type': 'string'}],
                 'body_required': False,
                 'body': False,
                 'source': 'https://docs.clover.com/dev/reference/taggettag.md'},
 'tag_get_tags': {'name': 'tag_get_tags',
                  'label': 'Get all tags',
                  'description': 'Retrieves all tags for an order. `Note:` In the REST API, a '
                                 'merchant uses two types of tags: 1. Tags, also known as item '
                                 'labels, are used to keep track of these items in reports. 2. '
                                 'Tags associated with the printer work as a printer label. '
                                 '`Example:` If a tag is associated with both an item and a '
                                 'printer, when the order is printed, the tagged items',
                  'category': 'Inventory',
                  'method': 'GET',
                  'path': '/v3/merchants/{mId}/tags',
                  'params': [{'name': 'filter',
                              'in': 'query',
                              'required': False,
                              'description': 'Filter fields to display search results: '
                                             '[modifiedTime, deleted, name, showInReporting, id]',
                              'type': 'string'},
                             {'name': 'expand',
                              'in': 'query',
                              'required': False,
                              'description': 'Additional information provided as an expanded '
                                             'response: [items, printers]',
                              'type': 'string'},
                             {'name': 'offset',
                              'in': 'query',
                              'required': False,
                              'description': 'Position of the first line item returned in the '
                                             'search results. Indicates the number of line items '
                                             'that are excluded from the search results.',
                              'type': 'integer'},
                             {'name': 'limit',
                              'in': 'query',
                              'required': False,
                              'description': 'Maximum number of line items returned in the search '
                                             'result.\n'
                                             ' Default: 100 \n'
                                             ' Maximum limit: 1000',
                              'type': 'integer'}],
                  'body_required': False,
                  'body': False,
                  'source': 'https://docs.clover.com/dev/reference/taggettags.md'},
 'tag_update_tag': {'name': 'tag_update_tag',
                    'label': 'Update a single tag',
                    'description': 'Update a single tag',
                    'category': 'Inventory',
                    'method': 'POST',
                    'path': '/v3/merchants/{mId}/tags/{tagId}',
                    'params': [{'name': 'expand',
                                'in': 'query',
                                'required': False,
                                'description': 'Expandable fields: [items, printers]',
                                'type': 'string'}],
                    'body_required': False,
                    'body': True,
                    'source': 'https://docs.clover.com/dev/reference/tagupdatetag.md'},
 'taxrate_get_tax_rate': {'name': 'taxrate_get_tax_rate',
                          'label': 'Get a single tax rate',
                          'description': 'Get a single tax rate',
                          'category': 'Inventory',
                          'method': 'GET',
                          'path': '/v3/merchants/{mId}/tax_rates/{taxId}',
                          'params': [{'name': 'expand',
                                      'in': 'query',
                                      'required': False,
                                      'description': 'Expandable fields: [items]',
                                      'type': 'string'}],
                          'body_required': False,
                          'body': False,
                          'source': 'https://docs.clover.com/dev/reference/taxrategettaxrate.md'},
 'taxrate_get_tax_rates': {'name': 'taxrate_get_tax_rates',
                           'label': 'Get all tax rates',
                           'description': 'Retrieves all tax rates applicable on an order. A tax '
                                          'rate is a percentage or a flat fee at which an item is '
                                          'taxed.',
                           'category': 'Inventory',
                           'method': 'GET',
                           'path': '/v3/merchants/{mId}/tax_rates',
                           'params': [{'name': 'filter',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Filter fields to display search results: '
                                                      '[isDefault, rate, items.id, name, id, '
                                                      'taxAmount, taxType]',
                                       'type': 'string'},
                                      {'name': 'expand',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Additional information provided as an '
                                                      'expanded response: [items]',
                                       'type': 'string'},
                                      {'name': 'offset',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Position of the first line item returned in '
                                                      'the search results. Indicates the number of '
                                                      'line items that are excluded from the '
                                                      'search results.',
                                       'type': 'integer'},
                                      {'name': 'limit',
                                       'in': 'query',
                                       'required': False,
                                       'description': 'Maximum number of line items returned in '
                                                      'the search result.\n'
                                                      ' Default: 100 \n'
                                                      ' Maximum limit: 1000',
                                       'type': 'integer'}],
                           'body_required': False,
                           'body': False,
                           'source': 'https://docs.clover.com/dev/reference/taxrategettaxrates.md'}}

CLOVER_TRIGGERS = {
    "on_new_or_updated_order": ("orders", "Orders"),
    "on_new_or_updated_item": ("items", "Inventory Items"),
}
