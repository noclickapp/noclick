"""Registry API 0.0.1 operation mappings from the pinned upstream OpenAPI.

https://github.com/apigee/registry/blob/main/openapi.yaml
"""

OPERATIONS = {'list_apis': {'method': 'GET',
               'path': '/v1/projects/{project}/locations/{location}/apis',
               'operation_id': 'Registry_ListApis',
               'query': [('pageSize',
                          'The maximum number of APIs to return. The service may return fewer than this '
                          'value. If unspecified, at most 50 values will be returned. The maximum is 1000; '
                          'values above 1000 will be coerced to 1000.'),
                         ('pageToken',
                          'A page token, received from a previous `ListApis` call. Provide this to retrieve '
                          'the subsequent page. When paginating, all other parameters provided to `ListApis` '
                          'must match the call that provided the page token.'),
                         ('filter',
                          'An expression that can be used to filter the list. Filters use the Common '
                          'Expression Language and can refer to all message fields.')],
               'body': {},
               'description': 'ListApis returns matching APIs.'},
 'create_api': {'method': 'POST',
                'path': '/v1/projects/{project}/locations/{location}/apis',
                'operation_id': 'Registry_CreateApi',
                'query': [('apiId',
                           'Required. The ID to use for the api, which will become the final component of '
                           "the api's resource name. This value should be 4-63 characters, and valid "
                           'characters are /[a-z][0-9]-/. Following AIP-162, IDs must not have the form of a '
                           'UUID.')],
                'body': {'display_name': 'displayName',
                         'description': 'description',
                         'availability': 'availability',
                         'recommended_version': 'recommendedVersion',
                         'recommended_deployment': 'recommendedDeployment',
                         'labels': 'labels',
                         'annotations': 'annotations'},
                'description': 'CreateApi creates a specified API.'},
 'get_api': {'method': 'GET',
             'path': '/v1/projects/{project}/locations/{location}/apis/{api}',
             'operation_id': 'Registry_GetApi',
             'query': [],
             'body': {},
             'description': 'GetApi returns a specified API.'},
 'delete_api': {'method': 'DELETE',
                'path': '/v1/projects/{project}/locations/{location}/apis/{api}',
                'operation_id': 'Registry_DeleteApi',
                'query': [('force',
                           'If set to true, any child resources will also be deleted. (Otherwise, the '
                           'request will only work if there are no child resources.)')],
                'body': {},
                'description': 'DeleteApi removes a specified API and all of the resources that it\n owns.'},
 'update_api': {'method': 'PATCH',
                'path': '/v1/projects/{project}/locations/{location}/apis/{api}',
                'operation_id': 'Registry_UpdateApi',
                'query': [('updateMask',
                           'The list of fields to be updated. If omitted, all fields are updated that are '
                           'set in the request message (fields set to default values are ignored). If a "*" '
                           'is specified, all fields are updated, including fields that are '
                           'unspecified/default in the request.'),
                          ('allowMissing',
                           'If set to true, and the api is not found, a new api_versions will be created. In '
                           'this situation, `update_mask` is ignored.')],
                'body': {'display_name': 'displayName',
                         'description': 'description',
                         'availability': 'availability',
                         'recommended_version': 'recommendedVersion',
                         'recommended_deployment': 'recommendedDeployment',
                         'labels': 'labels',
                         'annotations': 'annotations'},
                'description': 'UpdateApi can be used to modify a specified API.'},
 'list_deployments': {'method': 'GET',
                      'path': '/v1/projects/{project}/locations/{location}/apis/{api}/deployments',
                      'operation_id': 'Registry_ListApiDeployments',
                      'query': [('pageSize',
                                 'The maximum number of deployments to return. The service may return fewer '
                                 'than this value. If unspecified, at most 50 values will be returned. The '
                                 'maximum is 1000; values above 1000 will be coerced to 1000.'),
                                ('pageToken',
                                 'A page token, received from a previous `ListApiDeployments` call. Provide '
                                 'this to retrieve the subsequent page. When paginating, all other '
                                 'parameters provided to `ListApiDeployments` must match the call that '
                                 'provided the page token.'),
                                ('filter',
                                 'An expression that can be used to filter the list. Filters use the Common '
                                 'Expression Language and can refer to all message fields.')],
                      'body': {},
                      'description': 'ListApiDeployments returns matching deployments.'},
 'create_deployment': {'method': 'POST',
                       'path': '/v1/projects/{project}/locations/{location}/apis/{api}/deployments',
                       'operation_id': 'Registry_CreateApiDeployment',
                       'query': [('apiDeploymentId',
                                  'Required. The ID to use for the deployment, which will become the final '
                                  "component of the deployment's resource name. This value should be 4-63 "
                                  'characters, and valid characters are /[a-z][0-9]-/. Following AIP-162, '
                                  'IDs must not have the form of a UUID.')],
                       'body': {'display_name': 'displayName',
                                'description': 'description',
                                'api_spec_revision': 'apiSpecRevision',
                                'endpoint_uri': 'endpointUri',
                                'external_channel_uri': 'externalChannelUri',
                                'intended_audience': 'intendedAudience',
                                'access_guidance': 'accessGuidance',
                                'labels': 'labels',
                                'annotations': 'annotations'},
                       'description': 'CreateApiDeployment creates a specified deployment.'},
 'get_deployment': {'method': 'GET',
                    'path': '/v1/projects/{project}/locations/{location}/apis/{api}/deployments/{deployment}',
                    'operation_id': 'Registry_GetApiDeployment',
                    'query': [],
                    'body': {},
                    'description': 'GetApiDeployment returns a specified deployment.'},
 'delete_deployment': {'method': 'DELETE',
                       'path': '/v1/projects/{project}/locations/{location}/apis/{api}/deployments/{deployment}',
                       'operation_id': 'Registry_DeleteApiDeployment',
                       'query': [('force',
                                  'If set to true, any child resources will also be deleted. (Otherwise, the '
                                  'request will only work if there are no child resources.)')],
                       'body': {},
                       'description': 'DeleteApiDeployment removes a specified deployment, all revisions, '
                                      'and all\n'
                                      ' child resources (e.g. artifacts).'},
 'update_deployment': {'method': 'PATCH',
                       'path': '/v1/projects/{project}/locations/{location}/apis/{api}/deployments/{deployment}',
                       'operation_id': 'Registry_UpdateApiDeployment',
                       'query': [('updateMask',
                                  'The list of fields to be updated. If omitted, all fields are updated that '
                                  'are set in the request message (fields set to default values are '
                                  'ignored). If a "*" is specified, all fields are updated, including fields '
                                  'that are unspecified/default in the request.'),
                                 ('allowMissing',
                                  'If set to true, and the deployment is not found, a new deployment will be '
                                  'created. In this situation, `update_mask` is ignored.')],
                       'body': {'display_name': 'displayName',
                                'description': 'description',
                                'api_spec_revision': 'apiSpecRevision',
                                'endpoint_uri': 'endpointUri',
                                'external_channel_uri': 'externalChannelUri',
                                'intended_audience': 'intendedAudience',
                                'access_guidance': 'accessGuidance',
                                'labels': 'labels',
                                'annotations': 'annotations'},
                       'description': 'UpdateApiDeployment can be used to modify a specified deployment.'},
 'list_versions': {'method': 'GET',
                   'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions',
                   'operation_id': 'Registry_ListApiVersions',
                   'query': [('pageSize',
                              'The maximum number of versions to return. The service may return fewer than '
                              'this value. If unspecified, at most 50 values will be returned. The maximum '
                              'is 1000; values above 1000 will be coerced to 1000.'),
                             ('pageToken',
                              'A page token, received from a previous `ListApiVersions` call. Provide this '
                              'to retrieve the subsequent page. When paginating, all other parameters '
                              'provided to `ListApiVersions` must match the call that provided the page '
                              'token.'),
                             ('filter',
                              'An expression that can be used to filter the list. Filters use the Common '
                              'Expression Language and can refer to all message fields.')],
                   'body': {},
                   'description': 'ListApiVersions returns matching versions.'},
 'create_version': {'method': 'POST',
                    'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions',
                    'operation_id': 'Registry_CreateApiVersion',
                    'query': [('apiVersionId',
                               'Required. The ID to use for the version, which will become the final '
                               "component of the version's resource name. This value should be 4-63 "
                               'characters, and valid characters are /[a-z][0-9]-/. Following AIP-162, IDs '
                               'must not have the form of a UUID.')],
                    'body': {'display_name': 'displayName',
                             'description': 'description',
                             'state': 'state',
                             'labels': 'labels',
                             'annotations': 'annotations'},
                    'description': 'CreateApiVersion creates a specified version.'},
 'get_version': {'method': 'GET',
                 'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}',
                 'operation_id': 'Registry_GetApiVersion',
                 'query': [],
                 'body': {},
                 'description': 'GetApiVersion returns a specified version.'},
 'delete_version': {'method': 'DELETE',
                    'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}',
                    'operation_id': 'Registry_DeleteApiVersion',
                    'query': [('force',
                               'If set to true, any child resources will also be deleted. (Otherwise, the '
                               'request will only work if there are no child resources.)')],
                    'body': {},
                    'description': 'DeleteApiVersion removes a specified version and all of the resources '
                                   'that\n'
                                   ' it owns.'},
 'update_version': {'method': 'PATCH',
                    'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}',
                    'operation_id': 'Registry_UpdateApiVersion',
                    'query': [('updateMask',
                               'The list of fields to be updated. If omitted, all fields are updated that '
                               'are set in the request message (fields set to default values are ignored). '
                               'If a "*" is specified, all fields are updated, including fields that are '
                               'unspecified/default in the request.'),
                              ('allowMissing',
                               'If set to true, and the version is not found, a new version will be created. '
                               'In this situation, `update_mask` is ignored.')],
                    'body': {'display_name': 'displayName',
                             'description': 'description',
                             'state': 'state',
                             'labels': 'labels',
                             'annotations': 'annotations'},
                    'description': 'UpdateApiVersion can be used to modify a specified version.'},
 'list_specs': {'method': 'GET',
                'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}/specs',
                'operation_id': 'Registry_ListApiSpecs',
                'query': [('pageSize',
                           'The maximum number of specs to return. The service may return fewer than this '
                           'value. If unspecified, at most 50 values will be returned. The maximum is 1000; '
                           'values above 1000 will be coerced to 1000.'),
                          ('pageToken',
                           'A page token, received from a previous `ListApiSpecs` call. Provide this to '
                           'retrieve the subsequent page. When paginating, all other parameters provided to '
                           '`ListApiSpecs` must match the call that provided the page token.'),
                          ('filter',
                           'An expression that can be used to filter the list. Filters use the Common '
                           'Expression Language and can refer to all message fields except contents.')],
                'body': {},
                'description': 'ListApiSpecs returns matching specs.'},
 'create_spec': {'method': 'POST',
                 'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}/specs',
                 'operation_id': 'Registry_CreateApiSpec',
                 'query': [('apiSpecId',
                            'Required. The ID to use for the spec, which will become the final component of '
                            "the spec's resource name. This value should be 4-63 characters, and valid "
                            'characters are /[a-z][0-9]-/. Following AIP-162, IDs must not have the form of '
                            'a UUID.')],
                 'body': {'filename': 'filename',
                          'description': 'description',
                          'mime_type': 'mimeType',
                          'source_uri': 'sourceUri',
                          'contents': 'contents',
                          'labels': 'labels',
                          'annotations': 'annotations'},
                 'description': 'CreateApiSpec creates a specified spec.'},
 'get_spec': {'method': 'GET',
              'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}/specs/{spec}',
              'operation_id': 'Registry_GetApiSpec',
              'query': [],
              'body': {},
              'description': 'GetApiSpec returns a specified spec.'},
 'delete_spec': {'method': 'DELETE',
                 'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}/specs/{spec}',
                 'operation_id': 'Registry_DeleteApiSpec',
                 'query': [('force',
                            'If set to true, any child resources will also be deleted. (Otherwise, the '
                            'request will only work if there are no child resources.)')],
                 'body': {},
                 'description': 'DeleteApiSpec removes a specified spec, all revisions, and all child\n'
                                ' resources (e.g. artifacts).'},
 'update_spec': {'method': 'PATCH',
                 'path': '/v1/projects/{project}/locations/{location}/apis/{api}/versions/{version}/specs/{spec}',
                 'operation_id': 'Registry_UpdateApiSpec',
                 'query': [('updateMask',
                            'The list of fields to be updated. If omitted, all fields are updated that are '
                            'set in the request message (fields set to default values are ignored). If a "*" '
                            'is specified, all fields are updated, including fields that are '
                            'unspecified/default in the request.'),
                           ('allowMissing',
                            'If set to true, and the spec is not found, a new spec will be created. In this '
                            'situation, `update_mask` is ignored.')],
                 'body': {'filename': 'filename',
                          'description': 'description',
                          'mime_type': 'mimeType',
                          'source_uri': 'sourceUri',
                          'contents': 'contents',
                          'labels': 'labels',
                          'annotations': 'annotations'},
                 'description': 'UpdateApiSpec can be used to modify a specified spec.'}}
