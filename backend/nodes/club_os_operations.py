"""Club OS v2 request mappings from the pinned API and Calendar contracts.
Each entry represents one provider operation; query fields retain their published placement.
"""

OPERATIONS = {'list_locations': {'method': 'GET',
                    'path': '/access/locations',
                    'label': 'List Locations',
                    'description': 'Returns a list of locations the API user has permission to access',
                    'fields': {},
                    'query': [],
                    'body': []},
 'list_leads': {'method': 'GET',
                'path': '/leads',
                'label': 'List Leads',
                'description': 'Returns the leads for a location',
                'fields': {'club_id': {'wire': 'clubId',
                                       'type': 'integer',
                                       'required': True,
                                       'description': 'The club OS ID of the club for which the query is being '
                                                      'made'},
                           'location_id': {'wire': 'locationId',
                                           'type': 'integer',
                                           'required': True,
                                           'description': 'The Club OS ID of the location for which the query is '
                                                          'being made'},
                           'start_at': {'wire': 'startAt',
                                        'type': 'string',
                                        'required': True,
                                        'description': 'When retrieving leads who were created within a given '
                                                       'date range, this is the beginning of the range (formatted '
                                                       'as 2018-05-04T17:00:00.000Z)'},
                           'end_at': {'wire': 'endAt',
                                      'type': 'string',
                                      'required': True,
                                      'description': 'When retrieving leads who were created within a given date '
                                                     'range, this is the end of the range (formatted as '
                                                     '2018-05-04T17:00:00.000Z)'}},
                'query': ['club_id', 'location_id', 'start_at', 'end_at'],
                'body': []},
 'list_followups': {'method': 'GET',
                    'path': '/followups',
                    'label': 'List Followups',
                    'description': 'Returns the follow-ups for a location, excluding those with an outcome of 5, '
                                   '8, or 12 (Not Interested, Transferred, or Override)',
                    'fields': {'club_id': {'wire': 'clubId',
                                           'type': 'integer',
                                           'required': True,
                                           'description': 'The club OS ID of the club for which the query is '
                                                          'being made'},
                               'location_id': {'wire': 'locationId',
                                               'type': 'integer',
                                               'required': True,
                                               'description': 'The Club OS ID of the location for which the query '
                                                              'is being made'},
                               'start_at': {'wire': 'startAt',
                                            'type': 'string',
                                            'required': True,
                                            'description': 'When retrieving follow-up events within a given date '
                                                           'range, this is the beginning of the range (formatted '
                                                           'as 2018-05-04T17:00:00.000Z)'},
                               'end_at': {'wire': 'endAt',
                                          'type': 'string',
                                          'required': True,
                                          'description': 'When retrieving follow-up events within a given date '
                                                         'range, this is the end of the range (formatted as '
                                                         '2018-05-04T17:00:00.000Z)'},
                               'include_outcome': {'wire': 'includeOutcome',
                                                   'type': 'string',
                                                   'required': False,
                                                   'description': 'Determines whether to include information '
                                                                  'about followup outcomes in response'},
                               'include_notes_and_message': {'wire': 'includeNotesAndMessage',
                                                             'type': 'string',
                                                             'required': False,
                                                             'description': 'Determines whether to include '
                                                                            'information about followup notes and '
                                                                            'message body in response'}},
                    'query': ['club_id',
                              'location_id',
                              'start_at',
                              'end_at',
                              'include_outcome',
                              'include_notes_and_message'],
                    'body': []},
 'get_kpis': {'method': 'GET',
              'path': '/kpis',
              'label': 'Get KPIs',
              'description': 'Used to retrieve KPI data for a location or locations',
              'fields': {'club_id': {'wire': 'clubId',
                                     'type': 'integer',
                                     'required': True,
                                     'description': 'The club OS ID of the club for which the query is being '
                                                    'made'},
                         'start_time': {'wire': 'startTime',
                                        'type': 'string',
                                        'required': True,
                                        'description': 'When retrieving KPI data within a given date range, this '
                                                       'is the beginning of the range (formatted as '
                                                       '2018-05-04T17:00:00.000Z)'},
                         'end_time': {'wire': 'endTime',
                                      'type': 'string',
                                      'required': True,
                                      'description': 'When retrieving KPI data within a given date range, this is '
                                                     'the end of the range (formatted as '
                                                     '2018-05-04T17:00:00.000Z)'},
                         'group_by': {'wire': 'groupBy',
                                      'type': 'string',
                                      'required': True,
                                      'description': 'The entity to group results by (location, user, or club). '
                                                     "Inputting 'user' will group the results by employee."},
                         'kpis': {'wire': 'kpis',
                                  'type': 'string',
                                  'required': False,
                                  'description': 'Specify which KPIs to return (the default is all)'},
                         'location_ids': {'wire': 'locationIds',
                                          'type': 'integer',
                                          'required': True,
                                          'description': 'If retrieving data for more than one location, list '
                                                         'them here; the format should be integers (comma '
                                                         'separated) and the default is all locations in the '
                                                         'club'}},
              'query': ['club_id', 'start_time', 'end_time', 'group_by', 'kpis', 'location_ids'],
              'body': []},
 'list_memberships': {'method': 'GET',
                      'path': '/memberships',
                      'label': 'List Memberships',
                      'description': 'Used to retrieve data for a membership agreement',
                      'fields': {'club_id': {'wire': 'clubId',
                                             'type': 'integer',
                                             'required': True,
                                             'description': 'The club OS ID of the club at which the membership '
                                                            'was sold'},
                                 'location_id': {'wire': 'locationId',
                                                 'type': 'integer',
                                                 'required': True,
                                                 'description': 'The ID of the location at which the membership '
                                                                'was sold'},
                                 'sale_date_start_at': {'wire': 'saleDateStartAt',
                                                        'type': 'string',
                                                        'required': True,
                                                        'description': 'When searching for membership agreements '
                                                                       'whose sale dates fall into a given date '
                                                                       'range, this is the beginning of the date '
                                                                       'range (expressed as a date in the '
                                                                       'current, logged-in user’s local time and '
                                                                       'formatted as 2018-05-04T17:00:00.000Z)'},
                                 'sale_date_end_at': {'wire': 'saleDateEndAt',
                                                      'type': 'string',
                                                      'required': True,
                                                      'description': 'When searching for membership agreements '
                                                                     'whose sale dates fall into a given date '
                                                                     'range, this is the end of the date range '
                                                                     '(expressed as a date in the current, '
                                                                     'logged-in user’s local time and formatted '
                                                                     'as 2018-05-04T17:00:00.000Z)'},
                                 'external_location_id': {'wire': 'externalLocationId',
                                                          'type': 'string',
                                                          'required': False,
                                                          'description': "The billing partner's ID for the "
                                                                         'location at which the membership was '
                                                                         'sold'},
                                 'location_name': {'wire': 'locationName',
                                                   'type': 'string',
                                                   'required': False,
                                                   'description': 'The name of the location'},
                                 'origin_name': {'wire': 'originName',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': "The name of the user's origin type; possible "
                                                                'values are Walk-In, TI, Web, Referral, Other, '
                                                                'Outreach'},
                                 'external_member_id': {'wire': 'externalMemberId',
                                                        'type': 'string',
                                                        'required': False,
                                                        'description': "The billing partner's ID for the member"},
                                 'member_first_name': {'wire': 'memberFirstName',
                                                       'type': 'string',
                                                       'required': False,
                                                       'description': 'The first name of the member'},
                                 'member_last_name': {'wire': 'memberLastName',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'The last name of the member'},
                                 'agreement_status': {'wire': 'agreementStatus',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'The status of the membership agreement; '
                                                                     'possible values are DRAFT (1), ACTIVE (2), '
                                                                     'PENDING_DOWNPAYMENT (3), COMPLETED (4), '
                                                                     'CANCELLED (5), INTEGRATING (6), AND '
                                                                     'DELETED_DRAFT (7)'}},
                      'query': ['club_id',
                                'location_id',
                                'sale_date_start_at',
                                'sale_date_end_at',
                                'external_location_id',
                                'location_name',
                                'origin_name',
                                'external_member_id',
                                'member_first_name',
                                'member_last_name',
                                'agreement_status'],
                      'body': []},
 'list_created_sales_events': {'method': 'GET',
                               'path': '/sales-events-created',
                               'label': 'List Created Sales Events',
                               'description': 'Used to retrieve sales-event data based on the time at which the '
                                              'events were created',
                               'fields': {'club_id': {'wire': 'clubId',
                                                      'type': 'integer',
                                                      'required': True,
                                                      'description': 'The club OS ID of the club at which the '
                                                                     'sales event was created'},
                                          'location_id': {'wire': 'locationId',
                                                          'type': 'integer',
                                                          'required': True,
                                                          'description': 'The Club OS ID of the location at which '
                                                                         'the sales event was created'},
                                          'created_at_start_at': {'wire': 'createdAtStartAt',
                                                                  'type': 'string',
                                                                  'required': True,
                                                                  'description': 'When searching for sales events '
                                                                                 'that were created in a given '
                                                                                 'date range, this is the '
                                                                                 'beginning of the date range (in '
                                                                                 'UTC datetime, formatted as '
                                                                                 '2018-05-04T17:00:00.000Z)'},
                                          'created_at_end_at': {'wire': 'createdAtEndAt',
                                                                'type': 'string',
                                                                'required': True,
                                                                'description': 'When searching for sales events '
                                                                               'that were created in a given date '
                                                                               'range, this is the end of the '
                                                                               'date range (in UTC datetime, '
                                                                               'formatted as '
                                                                               '2018-05-04T17:00:00.000Z)'},
                                          'external_location_id': {'wire': 'externalLocationId',
                                                                   'type': 'string',
                                                                   'required': False,
                                                                   'description': "The billing partner's ID for "
                                                                                  'the location at which the '
                                                                                  'event was created'},
                                          'location_name': {'wire': 'locationName',
                                                            'type': 'string',
                                                            'required': False,
                                                            'description': 'The name of the location'},
                                          'external_event_owner_id': {'wire': 'externalEventOwnerId',
                                                                      'type': 'string',
                                                                      'required': False,
                                                                      'description': "The billing partner's ID "
                                                                                     'for the event owner'},
                                          'event_owner_first_name': {'wire': 'eventOwnerFirstName',
                                                                     'type': 'string',
                                                                     'required': False,
                                                                     'description': 'The first name of the event '
                                                                                    'owner'},
                                          'event_owner_last_name': {'wire': 'eventOwnerLastName',
                                                                    'type': 'string',
                                                                    'required': False,
                                                                    'description': 'The last name of the event '
                                                                                   'owner'},
                                          'external_attendee_id': {'wire': 'externalAttendeeId',
                                                                   'type': 'string',
                                                                   'required': False,
                                                                   'description': "The billing partner's ID for "
                                                                                  'the attendee'},
                                          'attendee_first_name': {'wire': 'attendeeFirstName',
                                                                  'type': 'string',
                                                                  'required': False,
                                                                  'description': 'The first name of the attendee'},
                                          'attendee_last_name': {'wire': 'attendeeLastName',
                                                                 'type': 'string',
                                                                 'required': False,
                                                                 'description': 'The last name of the attendee'},
                                          'event_type_name': {'wire': 'eventTypeName',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': 'The name of the event type; '
                                                                             'possible values are Meeting, '
                                                                             'Personal Training, Group Class, '
                                                                             'Appointment, Orientation, '
                                                                             'Assessment, and Small Group '
                                                                             'Training'},
                                          'attendee_origin_name': {'wire': 'attendeeOriginName',
                                                                   'type': 'string',
                                                                   'required': False,
                                                                   'description': "The name of the attendee's "
                                                                                  'origin type; possible values '
                                                                                  'are Walk-In, TI, Web, '
                                                                                  'Referral, Other, Outreach'},
                                          'attendee_sales_event_status_name': {'wire': 'attendeeSalesEventStatusName',
                                                                               'type': 'string',
                                                                               'required': False,
                                                                               'description': 'The attendee event '
                                                                                              'status; possible '
                                                                                              'values are ACTIVE, '
                                                                                              'CONFIRMED, '
                                                                                              'CANCELLED, '
                                                                                              'CANCELLED_CHARGE, '
                                                                                              'RESCHEDULED, '
                                                                                              'NO_SHOW, '
                                                                                              'NO_SHOW_CHARGE, '
                                                                                              'COMPLETED'},
                                          'attendee_outcome_status': {'wire': 'attendeeOutcomeStatus',
                                                                      'type': 'string',
                                                                      'required': False,
                                                                      'description': 'The attendee outcome '
                                                                                     'status; possible values are '
                                                                                     '0 (No Outcome), 1 '
                                                                                     '(Completed), or -1 '
                                                                                     '(Incomplete)'}},
                               'query': ['club_id',
                                         'location_id',
                                         'created_at_start_at',
                                         'created_at_end_at',
                                         'external_location_id',
                                         'location_name',
                                         'external_event_owner_id',
                                         'event_owner_first_name',
                                         'event_owner_last_name',
                                         'external_attendee_id',
                                         'attendee_first_name',
                                         'attendee_last_name',
                                         'event_type_name',
                                         'attendee_origin_name',
                                         'attendee_sales_event_status_name',
                                         'attendee_outcome_status'],
                               'body': []},
 'list_occurring_sales_events': {'method': 'GET',
                                 'path': '/sales-events-occurring',
                                 'label': 'List Occurring Sales Events',
                                 'description': 'Used to retrieve sales-event data based on when the events '
                                                'occurred',
                                 'fields': {'club_id': {'wire': 'clubId',
                                                        'type': 'integer',
                                                        'required': True,
                                                        'description': 'The ID of the club at which the sales '
                                                                       'event occurred'},
                                            'location_id': {'wire': 'locationId',
                                                            'type': 'integer',
                                                            'required': True,
                                                            'description': 'The ID of the location at which the '
                                                                           'sales event occurred'},
                                            'occurring_at_start_at': {'wire': 'occurringAtStartAt',
                                                                      'type': 'string',
                                                                      'required': True,
                                                                      'description': 'When searching for sales '
                                                                                     'events that occurred in a '
                                                                                     'given date range, this is '
                                                                                     'the beginning of the date '
                                                                                     'range (in UTC datetime, '
                                                                                     'formatted as '
                                                                                     '2018-05-04T17:00:00.000Z)'},
                                            'occurring_at_end_at': {'wire': 'occurringAtEndAt',
                                                                    'type': 'string',
                                                                    'required': True,
                                                                    'description': 'When searching for sales '
                                                                                   'events that occurred in a '
                                                                                   'given date range, this is the '
                                                                                   'end of the date range (in UTC '
                                                                                   'datetime, formatted as '
                                                                                   '2018-05-04T17:00:00.000Z)'},
                                            'external_location_id': {'wire': 'externalLocationId',
                                                                     'type': 'string',
                                                                     'required': False,
                                                                     'description': "The billing partner's ID for "
                                                                                    'the location at which the '
                                                                                    'event occurred'},
                                            'location_name': {'wire': 'locationName',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': 'The name of the location where the '
                                                                             'event occurred'},
                                            'external_event_owner_id': {'wire': 'externalEventOwnerId',
                                                                        'type': 'string',
                                                                        'required': False,
                                                                        'description': "The billing partner's ID "
                                                                                       'for the event owner'},
                                            'event_owner_first_name': {'wire': 'eventOwnerFirstName',
                                                                       'type': 'string',
                                                                       'required': False,
                                                                       'description': 'The first name of the '
                                                                                      'event owner'},
                                            'event_owner_last_name': {'wire': 'eventOwnerLastName',
                                                                      'type': 'string',
                                                                      'required': False,
                                                                      'description': 'The last name of the event '
                                                                                     'owner'},
                                            'external_attendee_id': {'wire': 'externalAttendeeId',
                                                                     'type': 'string',
                                                                     'required': False,
                                                                     'description': "The billing partner's ID for "
                                                                                    'the attendee'},
                                            'attendee_first_name': {'wire': 'attendeeFirstName',
                                                                    'type': 'string',
                                                                    'required': False,
                                                                    'description': 'The first name of the '
                                                                                   'attendee'},
                                            'attendee_last_name': {'wire': 'attendeeLastName',
                                                                   'type': 'string',
                                                                   'required': False,
                                                                   'description': 'The last name of the attendee'},
                                            'event_type_name': {'wire': 'eventTypeName',
                                                                'type': 'string',
                                                                'required': False,
                                                                'description': 'The name of the event type; '
                                                                               'possible values are Meeting, '
                                                                               'Personal Training, Group Class, '
                                                                               'Appointment, Orientation, '
                                                                               'Assessment, and Small Group '
                                                                               'Training'},
                                            'attendee_origin_name': {'wire': 'attendeeOriginName',
                                                                     'type': 'string',
                                                                     'required': False,
                                                                     'description': "The name of the attendee's "
                                                                                    'origin type; possible values '
                                                                                    'are Walk-In, TI, Web, '
                                                                                    'Referral, Other, Outreach'},
                                            'attendee_sales_event_status': {'wire': 'attendeeSalesEventStatus',
                                                                            'type': 'string',
                                                                            'required': False,
                                                                            'description': 'The attendee event '
                                                                                           'status; possible '
                                                                                           'values are (A), (CF), '
                                                                                           '(CN), (CC), ( R ), '
                                                                                           '(NN), (NC), (CP)'},
                                            'attendee_sales_event_status_name': {'wire': 'attendeeSalesEventStatusName',
                                                                                 'type': 'string',
                                                                                 'required': False,
                                                                                 'description': 'The name of the '
                                                                                                'attendee event '
                                                                                                'status; possible '
                                                                                                'values are '
                                                                                                'ACTIVE, '
                                                                                                'CONFIRMED, '
                                                                                                'CANCELLED, '
                                                                                                'CANCELLED_CHARGE, '
                                                                                                'RESCHEDULED, '
                                                                                                'NO_SHOW, '
                                                                                                'NO_SHOW_CHARGE, '
                                                                                                'COMPLETED'},
                                            'attendee_outcome_status': {'wire': 'attendeeOutcomeStatus',
                                                                        'type': 'string',
                                                                        'required': False,
                                                                        'description': 'The attendee outcome '
                                                                                       'status; possible values '
                                                                                       'are 0 (No Outcome), 1 '
                                                                                       '(Completed), or -1 '
                                                                                       '(Incomplete)'}},
                                 'query': ['club_id',
                                           'location_id',
                                           'occurring_at_start_at',
                                           'occurring_at_end_at',
                                           'external_location_id',
                                           'location_name',
                                           'external_event_owner_id',
                                           'event_owner_first_name',
                                           'event_owner_last_name',
                                           'external_attendee_id',
                                           'attendee_first_name',
                                           'attendee_last_name',
                                           'event_type_name',
                                           'attendee_origin_name',
                                           'attendee_sales_event_status',
                                           'attendee_sales_event_status_name',
                                           'attendee_outcome_status'],
                                 'body': []},
 'list_referrals': {'method': 'GET',
                    'path': '/referrals',
                    'label': 'List Referrals',
                    'description': 'Used to retrieve data related to referrals',
                    'fields': {'club_id': {'wire': 'clubId',
                                           'type': 'integer',
                                           'required': True,
                                           'description': 'The ID of the club at which the referral was made'},
                               'location_id': {'wire': 'locationId',
                                               'type': 'integer',
                                               'required': True,
                                               'description': 'The ID of the location at which the referral was '
                                                              'made'},
                               'referral_date_start_at': {'wire': 'referralDateStartAt',
                                                          'type': 'string',
                                                          'required': True,
                                                          'description': 'When searching for referrals that were '
                                                                         'made within a given date range, this is '
                                                                         'the beginning of the date range (in UTC '
                                                                         'datetime, formatted as '
                                                                         '2018-05-04T17:00:00.000Z)'},
                               'referral_date_end_at': {'wire': 'referralDateEndAt',
                                                        'type': 'string',
                                                        'required': True,
                                                        'description': 'When searching for referrals that were '
                                                                       'made within a given date range, this is '
                                                                       'the end of the date range (in UTC '
                                                                       'datetime, formatted as '
                                                                       '2018-05-04T17:00:00.000Z)'},
                               'location_name': {'wire': 'locationName',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'The name of the location'},
                               'employee_first_name': {'wire': 'employeeFirstName',
                                                       'type': 'string',
                                                       'required': False,
                                                       'description': 'The first name of the employee involved in '
                                                                      'the referral'},
                               'employee_last_name': {'wire': 'employeeLastName',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'The last name of the employee involved in '
                                                                     'the referral'},
                               'external_referring_user_id': {'wire': 'externalReferringUserId',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': "The billing partner's ID for the "
                                                                             'member who made the referral'},
                               'referring_user_source': {'wire': 'referringUserSource',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'The marketing source for the member who '
                                                                        'made the referral'},
                               'referring_user_first_name': {'wire': 'referringUserFirstName',
                                                             'type': 'string',
                                                             'required': False,
                                                             'description': 'The first name of the user who made '
                                                                            'the referral'},
                               'referring_user_last_name': {'wire': 'referringUserLastName',
                                                            'type': 'string',
                                                            'required': False,
                                                            'description': 'The last name of the user who made '
                                                                           'the referral'},
                               'referring_user_origin_name': {'wire': 'referringUserOriginName',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': "The name of the referring user's "
                                                                             'origin type'},
                               'external_referred_user_id': {'wire': 'externalReferredUserId',
                                                             'type': 'string',
                                                             'required': False,
                                                             'description': "The billing partner's ID for the "
                                                                            'member who was referred'},
                               'referred_user_source': {'wire': 'referredUserSource',
                                                        'type': 'string',
                                                        'required': False,
                                                        'description': 'The marketing source for the member who '
                                                                       'was referred'},
                               'referred_user_first_name': {'wire': 'referredUserFirstName',
                                                            'type': 'string',
                                                            'required': False,
                                                            'description': 'The first name of the member who was '
                                                                           'referred'},
                               'referred_user_last_name': {'wire': 'referredUserLastName',
                                                           'type': 'string',
                                                           'required': False,
                                                           'description': 'The last name of the member who was '
                                                                          'referred'},
                               'referred_user_origin_name': {'wire': 'referredUserOriginName',
                                                             'type': 'string',
                                                             'required': False,
                                                             'description': 'The name of the origin type for the '
                                                                            'member who was referred'}},
                    'query': ['club_id',
                              'location_id',
                              'referral_date_start_at',
                              'referral_date_end_at',
                              'location_name',
                              'employee_first_name',
                              'employee_last_name',
                              'external_referring_user_id',
                              'referring_user_source',
                              'referring_user_first_name',
                              'referring_user_last_name',
                              'referring_user_origin_name',
                              'external_referred_user_id',
                              'referred_user_source',
                              'referred_user_first_name',
                              'referred_user_last_name',
                              'referred_user_origin_name'],
                    'body': []},
 'list_training_agreements': {'method': 'GET',
                              'path': '/training-agreements',
                              'label': 'List Training Agreements',
                              'description': 'Used to retrieve data for package agreements; when any agreement is '
                                             'added to the PACKAGE_AGREEMENTS table, it should be recorded in '
                                             'TRAINING_AGREEMENTS',
                              'fields': {'club_id': {'wire': 'clubId',
                                                     'type': 'integer',
                                                     'required': True,
                                                     'description': 'The ID of the club at which the agreement '
                                                                    'was sold'},
                                         'location_id': {'wire': 'locationId',
                                                         'type': 'integer',
                                                         'required': True,
                                                         'description': 'The ID of the location at which the '
                                                                        'agreement was sold'},
                                         'sale_date_start_at': {'wire': 'saleDateStartAt',
                                                                'type': 'string',
                                                                'required': True,
                                                                'description': 'When searching for training '
                                                                               'agreements that were sold within '
                                                                               'a given date range, this is the '
                                                                               'beginning of the date range. '
                                                                               'Formatted as '
                                                                               '2018-05-04T17:00:00.000Z; the '
                                                                               'date matches the local time zone '
                                                                               'and the time is always 00:00:00'},
                                         'sale_date_end_at': {'wire': 'saleDateEndAt',
                                                              'type': 'string',
                                                              'required': True,
                                                              'description': 'When searching for training '
                                                                             'agreements that were sold within a '
                                                                             'given date range, this is the end '
                                                                             'of the date range. Formatted as '
                                                                             '2018-05-04T17:00:00.000Z; the date '
                                                                             'matches the local time zone and the '
                                                                             'time is always 00:00:00'},
                                         'location_name': {'wire': 'locationName',
                                                           'type': 'string',
                                                           'required': False,
                                                           'description': 'The name of the location'},
                                         'external_location_id': {'wire': 'externalLocationId',
                                                                  'type': 'string',
                                                                  'required': False,
                                                                  'description': "The billing partner's ID for "
                                                                                 'the location at which the '
                                                                                 'agreement was sold'},
                                         'external_sales_person_id': {'wire': 'externalSalesPersonId',
                                                                      'type': 'string',
                                                                      'required': False,
                                                                      'description': "The billing partner's ID "
                                                                                     'for the person who sold the '
                                                                                     'agreement'},
                                         'sales_person_first_name': {'wire': 'salesPersonFirstName',
                                                                     'type': 'string',
                                                                     'required': False,
                                                                     'description': 'The first name of the person '
                                                                                    'who sold the agreement'},
                                         'sales_person_last_name': {'wire': 'salesPersonLastName',
                                                                    'type': 'string',
                                                                    'required': False,
                                                                    'description': 'The last name of the person '
                                                                                   'who sold the agreement'},
                                         'member_first_name': {'wire': 'memberFirstName',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': 'The first name of the person who '
                                                                              'bought the agreement'},
                                         'member_last_name': {'wire': 'memberLastName',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': 'The last name of the person who '
                                                                             'bought the agreement'},
                                         'external_member_id': {'wire': 'externalMemberId',
                                                                'type': 'string',
                                                                'required': False,
                                                                'description': "The billing partner's ID for the "
                                                                               'person who bought the agreement'}},
                              'query': ['club_id',
                                        'location_id',
                                        'sale_date_start_at',
                                        'sale_date_end_at',
                                        'location_name',
                                        'external_location_id',
                                        'external_sales_person_id',
                                        'sales_person_first_name',
                                        'sales_person_last_name',
                                        'member_first_name',
                                        'member_last_name',
                                        'external_member_id'],
                              'body': []},
 'list_training_invoices': {'method': 'GET',
                            'path': '/training-agreements-invoices',
                            'label': 'List Training Invoices',
                            'description': 'Used to retrieve data related to invoices that are scheduled for the '
                                           'life of an agreement or up to one year, whichever is greater. Any '
                                           'changes to the PACKAGE_AGREEMENT_INVOICES table or changes that '
                                           'affect the future billing of an agreement shoud be recorded in this '
                                           'domain.',
                            'fields': {'club_id': {'wire': 'clubId',
                                                   'type': 'integer',
                                                   'required': True,
                                                   'description': 'The ID of the club associated with the '
                                                                  'invoice'},
                                       'location_id': {'wire': 'locationId',
                                                       'type': 'integer',
                                                       'required': True,
                                                       'description': 'The ID of the location associated with the '
                                                                      'invoice'},
                                       'invoice_date_start_at': {'wire': 'invoiceDateStartAt',
                                                                 'type': 'string',
                                                                 'required': True,
                                                                 'description': 'When searching for invoices that '
                                                                                'are expected to be billed within '
                                                                                'a given date range, this is the '
                                                                                'beginning of the date range '
                                                                                '(expressed as a date in the '
                                                                                'current, logged-in user’s local '
                                                                                'time and formatted as '
                                                                                '2018-05-04T17:00:00.000Z)'},
                                       'invoice_date_end_at': {'wire': 'invoiceDateEndAt',
                                                               'type': 'string',
                                                               'required': True,
                                                               'description': 'When searching for invoices that '
                                                                              'are expected to be billed within a '
                                                                              'given date range, this is the end '
                                                                              'of the date range (expressed as a '
                                                                              'date in the current, logged-in '
                                                                              'user’s local time and formatted as '
                                                                              '2018-05-04T17:00:00.000Z)'},
                                       'location_name': {'wire': 'locationName',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'The name of the location'}},
                            'query': ['club_id',
                                      'location_id',
                                      'invoice_date_start_at',
                                      'invoice_date_end_at',
                                      'location_name'],
                            'body': []},
 'list_training_payments': {'method': 'GET',
                            'path': '/training-agreements-payments',
                            'label': 'List Training Payments',
                            'description': 'Used to retrieve data related to payment attempts made against a '
                                           'training agreement invoice',
                            'fields': {'club_id': {'wire': 'clubId',
                                                   'type': 'integer',
                                                   'required': True,
                                                   'description': 'The ID of the club associated with the '
                                                                  'payment'},
                                       'location_id': {'wire': 'locationId',
                                                       'type': 'integer',
                                                       'required': True,
                                                       'description': 'The ID of the location associated with the '
                                                                      'payment'},
                                       'payment_attempt_date_start_at': {'wire': 'paymentAttemptDateStartAt',
                                                                         'type': 'string',
                                                                         'required': True,
                                                                         'description': 'When searching for '
                                                                                        'training agreement '
                                                                                        'payments that were made '
                                                                                        'within a given date '
                                                                                        'range, this is the '
                                                                                        'beginning of the date '
                                                                                        'range; it is based on '
                                                                                        'origTransactionTime, '
                                                                                        'expressed in UTC '
                                                                                        'datetime, and formatted '
                                                                                        'as '
                                                                                        '2018-05-04T17:00:00.000Z'},
                                       'payment_attempt_date_end_at': {'wire': 'paymentAttemptDateEndAt',
                                                                       'type': 'string',
                                                                       'required': True,
                                                                       'description': 'When searching for '
                                                                                      'training agreement '
                                                                                      'payments that were made '
                                                                                      'within a given date range, '
                                                                                      'this is the end of the '
                                                                                      'date range; it is based on '
                                                                                      'origTransactionTime, '
                                                                                      'expressed in UTC datetime, '
                                                                                      'and formatted as '
                                                                                      '2018-05-04T17:00:00.000Z'},
                                       'external_location_id': {'wire': 'externalLocationId',
                                                                'type': 'string',
                                                                'required': False,
                                                                'description': "The billng partner's ID for the "
                                                                               'location'},
                                       'location_name': {'wire': 'locationName',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'The name of the location'},
                                       'invoice_status_name': {'wire': 'invoiceStatusName',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': 'The name of the invoice status'},
                                       'member_service_names': {'wire': 'memberServiceNames',
                                                                'type': 'string',
                                                                'required': False,
                                                                'description': 'Concatenated string wtih all the '
                                                                               'member services in the invoice'},
                                       'email': {'wire': 'email',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'The email address of the person being billed'},
                                       'customer_first_name': {'wire': 'customerFirstName',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': 'The first name of the person being '
                                                                              'billed'},
                                       'customer_last_name': {'wire': 'customerLastName',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': 'The last name of the person being '
                                                                             'billed'},
                                       'time_zone_id': {'wire': 'timeZoneId',
                                                        'type': 'string',
                                                        'required': False,
                                                        'description': 'The time zone for the person being '
                                                                       'billed'},
                                       'customer_home_phone': {'wire': 'customerHomePhone',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': 'The home phone number of the '
                                                                              'person being billed'},
                                       'customer_mobile_phone': {'wire': 'customerMobilePhone',
                                                                 'type': 'string',
                                                                 'required': False,
                                                                 'description': 'The mobile phone number of the '
                                                                                'person being billed'},
                                       'customer_work_phone': {'wire': 'customerWorkPhone',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': 'The work phone number of the '
                                                                              'person being billed'},
                                       'external_customer_location_id': {'wire': 'externalCustomerLocationId',
                                                                         'type': 'string',
                                                                         'required': False,
                                                                         'description': "The billing partner's ID "
                                                                                        "for the customer's "
                                                                                        'location'},
                                       'transaction_id': {'wire': 'transactionId',
                                                          'type': 'string',
                                                          'required': False,
                                                          'description': 'The formatted transaction ID received '
                                                                         'from the billing system; used to link '
                                                                         'notifications'},
                                       'error_code': {'wire': 'errorCode',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'The error code received from the billing '
                                                                     'system'},
                                       'error_message': {'wire': 'errorMessage',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'The error message received from the '
                                                                        'billing system'},
                                       'transaction_id_orig': {'wire': 'transactionIdOrig',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': 'The transaction ID received from '
                                                                              'the billing system; used to link '
                                                                              'notifications'},
                                       'payment_attempt_caller': {'wire': 'paymentAttemptCaller',
                                                                  'type': 'string',
                                                                  'required': False,
                                                                  'description': 'Indicates whether the payment '
                                                                                 'attempt is ad-hoc or '
                                                                                 'auto-billing'},
                                       'payment_attempt_raw_request': {'wire': 'paymentAttemptRawRequest',
                                                                       'type': 'string',
                                                                       'required': False,
                                                                       'description': 'The raw data for the '
                                                                                      'payment attempt'},
                                       'salesperson_first_name': {'wire': 'salespersonFirstName',
                                                                  'type': 'string',
                                                                  'required': False,
                                                                  'description': 'The first name of the '
                                                                                 'salesperson for the agreement '
                                                                                 'against which the payment '
                                                                                 'attempt is being made'},
                                       'salesperson_last_name': {'wire': 'salespersonLastName',
                                                                 'type': 'string',
                                                                 'required': False,
                                                                 'description': 'The last name of the salesperson '
                                                                                'for the agreement against which '
                                                                                'the payment attempt is being '
                                                                                'made'},
                                       'trainer_external_id': {'wire': 'trainerExternalId',
                                                               'type': 'string',
                                                               'required': False,
                                                               'description': "The billing partner's ID for the "
                                                                              'trainer'},
                                       'trainer_first_name': {'wire': 'trainerFirstName',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': 'The first name of the trainer'},
                                       'trainer_last_name': {'wire': 'trainerLastName',
                                                             'type': 'string',
                                                             'required': False,
                                                             'description': 'The last name of the trainer'},
                                       'agreement_name': {'wire': 'agreementName',
                                                          'type': 'string',
                                                          'required': False,
                                                          'description': 'The name of the agreement against which '
                                                                         'the payment attempt is being made'},
                                       'description': {'wire': 'description',
                                                       'type': 'string',
                                                       'required': False,
                                                       'description': 'The description of the agreement against '
                                                                      'which the payment attempt is being made'}},
                            'query': ['club_id',
                                      'location_id',
                                      'payment_attempt_date_start_at',
                                      'payment_attempt_date_end_at',
                                      'external_location_id',
                                      'location_name',
                                      'invoice_status_name',
                                      'member_service_names',
                                      'email',
                                      'customer_first_name',
                                      'customer_last_name',
                                      'time_zone_id',
                                      'customer_home_phone',
                                      'customer_mobile_phone',
                                      'customer_work_phone',
                                      'external_customer_location_id',
                                      'transaction_id',
                                      'error_code',
                                      'error_message',
                                      'transaction_id_orig',
                                      'payment_attempt_caller',
                                      'payment_attempt_raw_request',
                                      'salesperson_first_name',
                                      'salesperson_last_name',
                                      'trainer_external_id',
                                      'trainer_first_name',
                                      'trainer_last_name',
                                      'agreement_name',
                                      'description'],
                            'body': []},
 'list_location_trainers': {'method': 'GET',
                            'path': '/locations/{locationId}/trainers',
                            'label': 'List Location Trainers',
                            'description': 'For a given location ID, returns all trainers (roleId = 6)',
                            'fields': {'location_id': {'wire': 'locationId',
                                                       'type': 'integer',
                                                       'required': True,
                                                       'description': "The Club OS ID for the trainer's location"},
                                       'include_deleted': {'wire': 'includeDeleted',
                                                           'type': 'string',
                                                           'required': False,
                                                           'description': 'Indicate whether you want deleted '
                                                                          'staff accounts included in the '
                                                                          'results; default is false'}},
                            'query': ['location_id', 'include_deleted'],
                            'body': []},
 'list_customer_trainers': {'method': 'GET',
                            'path': '/customers/{customerId}/trainers',
                            'label': 'List Customer Trainers',
                            'description': 'Returns all trainers assigned to the given customer ID',
                            'fields': {'customer_id': {'wire': 'customerId',
                                                       'type': 'integer',
                                                       'required': True,
                                                       'description': 'The Club OS ID for the customer being '
                                                                      'queried'}},
                            'query': ['customer_id'],
                            'body': []},
 'get_customer_inventory': {'method': 'GET',
                            'path': '/customers/{customerId}/service-inventory',
                            'label': 'Get Customer Inventory',
                            'description': 'Returns the current list of services that a customer has available to '
                                           'use',
                            'fields': {'customer_id': {'wire': 'customerId',
                                                       'type': 'integer',
                                                       'required': True,
                                                       'description': 'The Club OS ID for the customer being '
                                                                      'queried'},
                                       'event_type_id': {'wire': 'eventTypeId',
                                                         'type': 'string',
                                                         'required': True,
                                                         'description': 'Include at least one Event Type ID for '
                                                                        'the available sessions; possible values '
                                                                        'are 2 (Personal Training), 3 (Group '
                                                                        'Class), 7 (Group Training), and 8 (Small '
                                                                        'Group Training)'}},
                            'query': ['customer_id', 'event_type_id'],
                            'body': []},
 'get_event': {'method': 'GET',
               'path': '/events/{eventId}',
               'label': 'Get Event',
               'description': 'Returns information about a single event',
               'fields': {'start_time_start_at': {'wire': 'startTimeStartAt',
                                                  'type': 'string',
                                                  'required': True,
                                                  'description': 'The start time of the event (in UTC). Is used '
                                                                 'to distinguish proxy repeat events from root '
                                                                 'events (which have the same eventId).'},
                          'event_id': {'wire': 'eventId',
                                       'type': 'integer',
                                       'required': True,
                                       'description': 'Club OS resource ID used in the URL.'}},
               'query': ['start_time_start_at'],
               'body': []},
 'list_location_events': {'method': 'GET',
                          'path': '/locations/{locationId}/events',
                          'label': 'List Location Events',
                          'description': 'Returns the list of events for a given locationId',
                          'fields': {'location_id': {'wire': 'locationId',
                                                     'type': 'integer',
                                                     'required': True,
                                                     'description': 'The Club OS ID for the location being '
                                                                    'queried'},
                                     'start_time_start_at': {'wire': 'startTimeStartAt',
                                                             'type': 'string',
                                                             'required': True,
                                                             'description': 'When searching for events that begin '
                                                                            'within a given date range, this is '
                                                                            'the beginning of that range (in '
                                                                            'UTC)'},
                                     'start_time_end_at': {'wire': 'startTimeEndAt',
                                                           'type': 'string',
                                                           'required': True,
                                                           'description': 'When searching for events that begin '
                                                                          'within a given date range, this is the '
                                                                          'end of that range (in UTC)'},
                                     'event_type_id': {'wire': 'eventTypeId',
                                                       'type': 'string',
                                                       'required': False,
                                                       'description': 'Include at least one Event Type ID for the '
                                                                      'available sessions; possible values are 2 '
                                                                      '(Personal Training), 3 (Group Class), 7 '
                                                                      '(Group Training), and 8 (Small Group '
                                                                      'Training)'},
                                     'include_deleted': {'wire': 'includeDeleted',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'Indicate whether you want deleted events '
                                                                        'included in the results; default is '
                                                                        'false'}},
                          'query': ['location_id',
                                    'start_time_start_at',
                                    'start_time_end_at',
                                    'event_type_id',
                                    'include_deleted'],
                          'body': []},
 'list_staff_events': {'method': 'GET',
                       'path': '/staff/{staffId}/events',
                       'label': 'List Staff Events',
                       'description': 'Returns the list of events for a given staff ID',
                       'fields': {'staff_id': {'wire': 'staffId',
                                               'type': 'integer',
                                               'required': True,
                                               'description': 'The Club OS ID for the staff person'},
                                  'start_time_start_at': {'wire': 'startTimeStartAt',
                                                          'type': 'string',
                                                          'required': True,
                                                          'description': 'When searching for events that begin '
                                                                         'within a given date range, this is the '
                                                                         'beginning of that range (in UTC)'},
                                  'start_time_end_at': {'wire': 'startTimeEndAt',
                                                        'type': 'string',
                                                        'required': True,
                                                        'description': 'When searching for events that begin '
                                                                       'within a given date range, this is the '
                                                                       'end of that range (in UTC)'},
                                  'event_type_id': {'wire': 'eventTypeId',
                                                    'type': 'string',
                                                    'required': False,
                                                    'description': 'Include at least one Event Type ID for the '
                                                                   'available sessions; possible values are 2 '
                                                                   '(Personal Training), 3 (Group Class), 7 '
                                                                   '(Group Training), and 8 (Small Group '
                                                                   'Training)'},
                                  'include_deleted': {'wire': 'includeDeleted',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'Indicate whether you want deleted events '
                                                                     'included in the results; default is false'}},
                       'query': ['staff_id',
                                 'start_time_start_at',
                                 'start_time_end_at',
                                 'event_type_id',
                                 'include_deleted'],
                       'body': []},
 'list_customer_events': {'method': 'GET',
                          'path': '/customers/{customerId}/events',
                          'label': 'List Customer Events',
                          'description': 'Returns the list of events for a given customer ID',
                          'fields': {'customer_id': {'wire': 'customerId',
                                                     'type': 'integer',
                                                     'required': True,
                                                     'description': 'The Club OS ID for the customer'},
                                     'start_time_start_at': {'wire': 'startTimeStartAt',
                                                             'type': 'string',
                                                             'required': True,
                                                             'description': 'When searching for events that begin '
                                                                            'within a given date range, this is '
                                                                            'the beginning of that range (in '
                                                                            'UTC)'},
                                     'start_time_end_at': {'wire': 'startTimeEndAt',
                                                           'type': 'string',
                                                           'required': True,
                                                           'description': 'When searching for events that begin '
                                                                          'within a given date range, this is the '
                                                                          'end of that range (in UTC)'},
                                     'event_type_id': {'wire': 'eventTypeId',
                                                       'type': 'string',
                                                       'required': False,
                                                       'description': 'Include at least one Event Type ID for the '
                                                                      'available sessions; possible values are 2 '
                                                                      '(Personal Training), 3 (Group Class), 7 '
                                                                      '(Group Training), and 8 (Small Group '
                                                                      'Training)'},
                                     'include_deleted': {'wire': 'includeDeleted',
                                                         'type': 'string',
                                                         'required': False,
                                                         'description': 'Indicate whether you want deleted events '
                                                                        'included in the results; default is '
                                                                        'false'}},
                          'query': ['customer_id',
                                    'start_time_start_at',
                                    'start_time_end_at',
                                    'event_type_id',
                                    'include_deleted'],
                          'body': []},
 'list_pt_openings': {'method': 'GET',
                      'path': '/locations/{locationId}/staff/{staffId}/pt-openings',
                      'label': 'List PT Openings',
                      'description': 'Returns availability openings for a staff member in 30-min slots.',
                      'fields': {'start_time_start_at': {'wire': 'startTimeStartAt',
                                                         'type': 'integer',
                                                         'required': True,
                                                         'description': 'The earliest start time to get PT '
                                                                        'availability for'},
                                 'start_time_end_at': {'wire': 'startTimeEndAt',
                                                       'type': 'integer',
                                                       'required': True,
                                                       'description': 'The latest start time to get PT '
                                                                      'availability for'},
                                 'location_id': {'wire': 'locationId',
                                                 'type': 'integer',
                                                 'required': True,
                                                 'description': 'Club OS resource ID used in the URL.'},
                                 'staff_id': {'wire': 'staffId',
                                              'type': 'integer',
                                              'required': True,
                                              'description': 'Club OS resource ID used in the URL.'}},
                      'query': ['start_time_start_at', 'start_time_end_at'],
                      'body': []},
 'create_pt_booking': {'method': 'POST',
                       'path': '/locations/{locationId}/staff/{staffId}/pt-bookings',
                       'label': 'Create PT Booking',
                       'description': 'Creates a type 2 event (Personal Training) and the customer as an attendee '
                                      'with a status of Confirmed',
                       'fields': {'location_id': {'wire': 'locationId',
                                                  'type': 'integer',
                                                  'required': True,
                                                  'description': 'The Club OS ID for the location being queried'},
                                  'staff_id': {'wire': 'staffId',
                                               'type': 'integer',
                                               'required': True,
                                               'description': 'The Club OS ID for the employee associated with '
                                                              'the event'},
                                  'customer_id': {'wire': 'customerId',
                                                  'type': 'integer',
                                                  'required': True,
                                                  'description': 'The Club OS ID for the customer'},
                                  'start_time': {'wire': 'startTime',
                                                 'type': 'string',
                                                 'required': True,
                                                 'description': 'The event start time'},
                                  'duration': {'wire': 'duration',
                                               'type': 'integer',
                                               'required': True,
                                               'description': 'The duration of the member service in minutes'},
                                  'service_id': {'wire': 'serviceId',
                                                 'type': 'integer',
                                                 'required': True,
                                                 'description': 'The ID of the member service of the event'}},
                       'query': ['location_id', 'staff_id'],
                       'body': ['customer_id', 'start_time', 'duration', 'service_id']},
 'update_event_attendee': {'method': 'PATCH',
                           'path': '/locations/{locationId}/events/{eventId}/attendees',
                           'label': 'Update Event Attendee',
                           'description': 'Adds a customer to an event with a status of Confirmed when no '
                                          "attendeeStatus is passed in, or marks a customer's status as Canceled "
                                          "when a status of 'CANCEL' is passed in.",
                           'fields': {'customer_id': {'wire': 'customerId',
                                                      'type': 'integer',
                                                      'required': True,
                                                      'description': 'The Club OS ID for the customer'},
                                      'series_start_time': {'wire': 'seriesStartTime',
                                                            'type': 'string',
                                                            'required': True,
                                                            'description': 'The start time of the event. This '
                                                                           'field is used to distinguish proxy '
                                                                           'repeat events from root events.'},
                                      'attendee_status': {'wire': 'attendeeStatus',
                                                          'type': 'string',
                                                          'required': False,
                                                          'description': 'Can be empty (which is interpreted as '
                                                                         "CONFIRM), 'CONFIRM', or'CANCEL'"},
                                      'location_id': {'wire': 'locationId',
                                                      'type': 'integer',
                                                      'required': True,
                                                      'description': 'Club OS resource ID used in the URL.'},
                                      'event_id': {'wire': 'eventId',
                                                   'type': 'integer',
                                                   'required': True,
                                                   'description': 'Club OS resource ID used in the URL.'}},
                           'query': ['customer_id', 'series_start_time', 'attendee_status'],
                           'body': []}}
