"""Operations pinned to GoToTrainingV1.yml 1.0.0.

Source: https://developer.goto.com/resources/GoToTrainingV1.yml
"""
OPERATIONS = {'create_training': {'method': 'POST',
                     'path': '/organizers/{organizerKey}/trainings',
                     'label': 'Create Training',
                     'description': 'Schedules a training of one or more sessions. You can only add '
                                    'organizers to a training if you have a multi-user account. Once a '
                                    'training has been created with this method, you can accept '
                                    'registrations to the training. Registration is for the entire training '
                                    '- all sessions. (The GoTo Training admin site enables you to create '
                                    'trainings that allow participants to register for individual sessions '
                                    'as well as automatically create weekly or monthly events.) Registration '
                                    'settings controls whether you allow web registration for this training, '
                                    'and whether a confirmation email is sent to the registrant following '
                                    'registration. Disabling the confirmation email is an API-only setting. '
                                    'If the user registers through the GoTo Training website, a confirmation '
                                    'email is sent. If the user is manually approved by the training '
                                    'administrator through the GoTo Training web site, the confirmation '
                                    'email is sent. It is recommended that you disable web registration if '
                                    'you disable confirmation emails. The response contains a trainingKey '
                                    'for the scheduled training.\n',
                     'body': 'TrainingReqCreate',
                     'result': {'type': 'string'}},
 'list_trainings': {'method': 'GET',
                    'path': '/organizers/{organizerKey}/trainings',
                    'label': 'Get Trainings',
                    'description': 'Retrieves all scheduled trainings for a given organizer. The trainings '
                                   'are returned in the order in which they were created. Completed '
                                   'trainings are not included; ongoing trainings with past sessions are '
                                   'included along with the past sessions. If the organizer does not have '
                                   'any scheduled trainings, the response will be empty.\n',
                    'body': None,
                    'result': {'type': 'array', 'items': {'$ref': '#/components/schemas/Training'}}},
 'get_training': {'method': 'GET',
                  'path': '/organizers/{organizerKey}/trainings/{trainingKey}',
                  'label': 'Get Training',
                  'description': 'Uses the organizer key and training key to retrieve information on a '
                                 'scheduled training.',
                  'body': None,
                  'result': {'$ref': '#/components/schemas/Training'}},
 'delete_training': {'method': 'DELETE',
                     'path': '/organizers/{organizerKey}/trainings/{trainingKey}',
                     'label': 'Delete Training',
                     'description': 'Deletes a scheduled or completed training. For scheduled trainings, it '
                                    'deletes all scheduled sessions of the training. For completed '
                                    'trainings, the sessions remain in the database. No email is sent to '
                                    'organizers or registrants, but when participants attempt to start or '
                                    'join the training, they are directed to a page that states: Training '
                                    'Not Found: The training you are trying to join is no longer '
                                    'available.\n',
                     'body': None,
                     'result': None},
 'get_management_url': {'method': 'GET',
                        'path': '/organizers/{organizerKey}/trainings/{trainingKey}/manageUrl',
                        'label': 'Get Management URL for Training',
                        'description': 'Retrieves a direct URL to the admin portal for a specific training. '
                                       'The request identifies the organizer and the training; the response '
                                       'provides a link the organizer can use to manage or launch the '
                                       'training in the admin portal. The training organizer will be '
                                       'required to log in. You can schedule and manage the training (e.g., '
                                       'add tests, polls and training materials) from the URL provided in '
                                       'the response.\n',
                        'body': None,
                        'result': {'type': 'string'}},
 'update_training_name': {'method': 'PUT',
                          'path': '/organizers/{organizerKey}/trainings/{trainingKey}/nameDescription',
                          'label': 'Update Training Name and Description',
                          'description': 'Updates a scheduled training’s name and description.',
                          'body': 'TrainingNameDescription',
                          'result': None},
 'list_training_organizers': {'method': 'GET',
                              'path': '/organizers/{organizerKey}/trainings/{trainingKey}/organizers',
                              'label': 'Get Training Organizers',
                              'description': 'Retrieves organizer details for a specific training. This is '
                                             'only applicable to multi-user accounts with sharing enabled '
                                             '(co-organizers).\n',
                              'body': None,
                              'result': {'type': 'array',
                                         'items': {'$ref': '#/components/schemas/Organizer'}}},
 'update_training_organizers': {'method': 'PUT',
                                'path': '/organizers/{organizerKey}/trainings/{trainingKey}/organizers',
                                'label': 'Update Training Organizers',
                                'description': 'Replaces the co-organizers for a specific training. The '
                                               'scheduling organizer cannot be unassigned. Organizers will '
                                               'be notified via email if the notifyOrganizers parameter is '
                                               'set to true. Replaced organizers are not notified. This '
                                               'method is only applicable to multi-user accounts with '
                                               'sharing enabled (co-organizers).\n',
                                'body': 'TrainingOrganizers',
                                'result': None},
 'list_recordings': {'method': 'GET',
                     'path': '/trainings/{trainingKey}/recordings',
                     'label': 'Get Online Recordings for Training',
                     'description': 'Retrieves all online recordings for a given training. If there are '
                                    'none, it returns an empty list.\n',
                     'body': None,
                     'result': {'$ref': '#/components/schemas/RecordingsListForTraining'}},
 'register_for_training': {'method': 'POST',
                           'path': '/organizers/{organizerKey}/trainings/{trainingKey}/registrants',
                           'label': 'Register for Training',
                           'description': 'Registers one person, identified by a unique email address, for a '
                                          'training. Approval is automatic unless payment or approval is '
                                          'required. NOTE: If some registrants do not receive a confirmation '
                                          'email, the emails could be getting blocked by their email server '
                                          'due to spam filtering or a grey-listing setting.\n',
                           'body': 'RegistrantReqCreate',
                           'result': {'$ref': '#/components/schemas/RegistrantCreated'}},
 'list_registrants': {'method': 'GET',
                      'path': '/organizers/{organizerKey}/trainings/{trainingKey}/registrants',
                      'label': 'Get Training Registrants',
                      'description': 'Retrieve registration details for all registrants of a specific '
                                     'training. IMPORTANT: The registrant data caches are typically updated '
                                     'immediately and the data will be returned in the response. However, '
                                     'the update can take as long as two hours.\n',
                      'body': None,
                      'result': {'type': 'array', 'items': {'$ref': '#/components/schemas/Registrant'}}},
 'get_registrant': {'method': 'GET',
                    'path': '/organizers/{organizerKey}/trainings/{trainingKey}/registrants/{registrantKey}',
                    'label': 'Get Registrant',
                    'description': 'Retrieve registration details for a specific training registrant. '
                                   'IMPORTANT: The registrant data caches are typically updated immediately '
                                   'and the data will be returned in the response. However, the update can '
                                   'take as long as two hours.\n',
                    'body': None,
                    'result': {'$ref': '#/components/schemas/Registrant'}},
 'cancel_registration': {'method': 'DELETE',
                         'path': '/organizers/{organizerKey}/trainings/{trainingKey}/registrants/{registrantKey}',
                         'label': 'Cancel Registration',
                         'description': 'Cancels a registration in a scheduled training for a specific '
                                        'registrant. If the registrant has paid for the training, a '
                                        'cancellation cannot be completed with this method; it must be '
                                        'completed on the external admin site. No notification is sent to '
                                        'the registrant or the organizer by default. The registrant can '
                                        're-register if needed.\n',
                         'body': None,
                         'result': None},
 'update_registration_settings': {'method': 'PUT',
                                  'path': '/organizers/{organizerKey}/trainings/{trainingKey}/registrationSettings',
                                  'label': 'Update Training Registration Settings',
                                  'description': 'An API request to automatically enable or disable web '
                                                 'registrations and confirmation emails to registrants.\n',
                                  'body': 'RegistrationSettings',
                                  'result': None},
 'get_start_url': {'method': 'GET',
                   'path': '/organizers/{organizerKey}/trainings/{trainingKey}/startUrl',
                   'label': 'Get Start Url',
                   'description': 'Retrieves a URL that can be used to start a training. When this URL is '
                                  'opened in a web browser, the GoTo Training client will be downloaded and '
                                  'launched and the training will start after the organizer logs in with its '
                                  'credentials.\n',
                   'body': None,
                   'result': {'type': 'string'}},
 'update_training_times': {'method': 'PUT',
                           'path': '/organizers/{organizerKey}/trainings/{trainingKey}/times',
                           'label': 'Update Training Times',
                           'description': "A request to update a scheduled training's start and end times. "
                                          "If the request contains 'notifyTrainers = true' and "
                                          "'notifyRegistrants = true', both organizers and registrants are "
                                          'notified. The response provides the number of notified trainers '
                                          'and registrants.\n',
                           'body': 'TrainingTimes',
                           'result': {'$ref': '#/components/schemas/NotifiedParties'}},
 'list_sessions_by_date': {'method': 'POST',
                           'path': '/reports/organizers/{organizerKey}/sessions',
                           'label': 'Get Sessions by Date Range',
                           'description': 'This call returns all session details over a given date range for '
                                          'a given organizer. A session is a completed training event.\n',
                           'body': 'DateTimeRange',
                           'result': {'type': 'array', 'items': {'$ref': '#/components/schemas/Session'}}},
 'list_session_attendees': {'method': 'GET',
                            'path': '/reports/organizers/{organizerKey}/sessions/{sessionKey}/attendees',
                            'label': 'Get Attendance Details',
                            'description': 'Retrieves a list of registrants from a specific completed '
                                           "training session. The response includes the registrants' email "
                                           'addresses, and if they attended, it includes the duration of '
                                           'each period of their attendance in minutes, and the times at '
                                           'which they joined and left. If a registrant does not attend, '
                                           'they appear at the bottom of the listing with timeInSession = '
                                           '0.\n',
                            'body': None,
                            'result': {'type': 'array', 'items': {'$ref': '#/components/schemas/Attendee'}}},
 'list_training_sessions': {'method': 'GET',
                            'path': '/reports/organizers/{organizerKey}/trainings/{trainingKey}',
                            'label': 'Get Sessions By Training',
                            'description': 'Retrieves session details for a given training. A session is a '
                                           'completed training event. Each training may contain one or more '
                                           'sessions.\n',
                            'body': None,
                            'result': {'type': 'array', 'items': {'$ref': '#/components/schemas/Session'}}}}
