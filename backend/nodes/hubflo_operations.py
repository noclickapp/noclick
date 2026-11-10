"""Hubflo v2 operation forms and their fixed HTTP routes.

Fields mirror the provider contract so each action has one request shape.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, create_model

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

OPERATIONS = {}
CONFIG_MODELS = {}

OPERATIONS['list_contacts'] = ('GET', '/api/v2/contacts', ('page', 'per_page', 'owner_id', 'phone', 'email', 'project_id', 'company_id', 'contact_id', 'linkedin'), ())
CONFIG_MODELS['list_contacts'] = create_model(
    'HubfloListContactsConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['list_contacts'], Field('list_contacts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Contacts', "x-category": 'Contact', "x-is-trigger": False})),
    page=(int | None, Field(1, title='Page', description='Page number', ge=1)),
    per_page=(int | None, Field(20, title='Per Page', description='Number of items per page (max 100)', ge=1, le=100)),
    owner_id=(str | None, Field(None, title='Owner Id', description='Filter by owner ID')),
    phone=(str | None, Field(None, title='Phone', description='Filter by phone number')),
    email=(str | None, Field(None, title='Email', description='Filter by email')),
    project_id=(str | None, Field(None, title='Project Id', description='Filter by project ID')),
    company_id=(str | None, Field(None, title='Company Id', description='Filter by company ID')),
    contact_id=(str | None, Field(None, title='Contact Id', description='Filter by contact ID')),
    linkedin=(str | None, Field(None, title='Linkedin', description='Filter by LinkedIn')),
)

OPERATIONS['get_contact'] = ('GET', '/api/v2/contacts/{id}', (), ())
CONFIG_MODELS['get_contact'] = create_model(
    'HubfloGetContactConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['get_contact'], Field('get_contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Contact', "x-category": 'Contact', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Contact ID', min_length=1)),
)

OPERATIONS['create_contact'] = ('POST', '/api/v2/contacts', (), ('first_name', 'last_name', 'full_name', 'email', 'phone', 'secondary_phone', 'contact_type', 'priority', 'address', 'postal_code', 'city', 'state', 'country', 'job_title', 'url_linkedin', 'hubspot_id', 'owner_id', 'owner_email', 'company_id', 'company_name', 'tags'))
CONFIG_MODELS['create_contact'] = create_model(
    'HubfloCreateContactConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['create_contact'], Field('create_contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Contact', "x-category": 'Contact', "x-is-trigger": False})),
    first_name=(str, Field(..., title='First Name', min_length=1)),
    last_name=(str, Field(..., title='Last Name', min_length=1)),
    full_name=(str | None, Field(None, title='Full Name')),
    email=(str | None, Field(None, title='Email')),
    phone=(str | None, Field(None, title='Phone')),
    secondary_phone=(str | None, Field(None, title='Secondary Phone')),
    contact_type=(Literal['prospect', 'client', 'partner', 'provider'] | None, Field(None, title='Contact Type')),
    priority=(Literal['low', 'medium', 'high'] | None, Field(None, title='Priority')),
    address=(str | None, Field(None, title='Address')),
    postal_code=(str | None, Field(None, title='Postal Code')),
    city=(str | None, Field(None, title='City')),
    state=(str | None, Field(None, title='State')),
    country=(str | None, Field(None, title='Country')),
    job_title=(str | None, Field(None, title='Job Title')),
    url_linkedin=(str | None, Field(None, title='Url Linkedin')),
    hubspot_id=(str | None, Field(None, title='Hubspot Id')),
    owner_id=(str | None, Field(None, title='Owner Id')),
    owner_email=(str | None, Field(None, title='Owner Email')),
    company_id=(str | None, Field(None, title='Company Id')),
    company_name=(str | None, Field(None, title='Company Name')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
)

OPERATIONS['update_contact'] = ('PATCH', '/api/v2/contacts/{id}', (), ('first_name', 'last_name', 'full_name', 'email', 'phone', 'secondary_phone', 'contact_type', 'priority', 'address', 'postal_code', 'city', 'state', 'country', 'job_title', 'url_linkedin', 'hubspot_id', 'owner_id', 'owner_email', 'company_id', 'company_name', 'tags'))
CONFIG_MODELS['update_contact'] = create_model(
    'HubfloUpdateContactConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['update_contact'], Field('update_contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Contact', "x-category": 'Contact', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Contact ID', min_length=1)),
    first_name=(str, Field(..., title='First Name', min_length=1)),
    last_name=(str, Field(..., title='Last Name', min_length=1)),
    full_name=(str | None, Field(None, title='Full Name')),
    email=(str | None, Field(None, title='Email')),
    phone=(str | None, Field(None, title='Phone')),
    secondary_phone=(str | None, Field(None, title='Secondary Phone')),
    contact_type=(Literal['prospect', 'client', 'partner', 'provider'] | None, Field(None, title='Contact Type')),
    priority=(Literal['low', 'medium', 'high'] | None, Field(None, title='Priority')),
    address=(str | None, Field(None, title='Address')),
    postal_code=(str | None, Field(None, title='Postal Code')),
    city=(str | None, Field(None, title='City')),
    state=(str | None, Field(None, title='State')),
    country=(str | None, Field(None, title='Country')),
    job_title=(str | None, Field(None, title='Job Title')),
    url_linkedin=(str | None, Field(None, title='Url Linkedin')),
    hubspot_id=(str | None, Field(None, title='Hubspot Id')),
    owner_id=(str | None, Field(None, title='Owner Id')),
    owner_email=(str | None, Field(None, title='Owner Email')),
    company_id=(str | None, Field(None, title='Company Id')),
    company_name=(str | None, Field(None, title='Company Name')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
)

OPERATIONS['list_companies'] = ('GET', '/api/v2/companies', ('page', 'per_page', 'project_id', 'parent_id', 'owner_id', 'contact_id', 'name'), ())
CONFIG_MODELS['list_companies'] = create_model(
    'HubfloListCompaniesConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['list_companies'], Field('list_companies', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Companies', "x-category": 'Company', "x-is-trigger": False})),
    page=(int | None, Field(1, title='Page', description='Page number', ge=1)),
    per_page=(int | None, Field(20, title='Per Page', description='Number of items per page (max 100)', ge=1, le=100)),
    project_id=(str | None, Field(None, title='Project Id', description='Filter by project ID')),
    parent_id=(str | None, Field(None, title='Parent Id', description='Filter by parent ID')),
    owner_id=(str | None, Field(None, title='Owner Id', description='Filter by owner ID')),
    contact_id=(str | None, Field(None, title='Contact Id', description='Filter by contact ID')),
    name=(str | None, Field(None, title='Name', description='Filter by name')),
)

OPERATIONS['get_company'] = ('GET', '/api/v2/companies/{id}', (), ())
CONFIG_MODELS['get_company'] = create_model(
    'HubfloGetCompanyConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['get_company'], Field('get_company', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Company', "x-category": 'Company', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Company ID', min_length=1)),
)

OPERATIONS['create_company'] = ('POST', '/api/v2/companies', (), ('name', 'business_description', 'email', 'address', 'postal_code', 'city', 'state', 'country', 'staff', 'siret', 'vat_number', 'website', 'url_linkedin', 'hubspot_id', 'owner_id', 'tags'))
CONFIG_MODELS['create_company'] = create_model(
    'HubfloCreateCompanyConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['create_company'], Field('create_company', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Company', "x-category": 'Company', "x-is-trigger": False})),
    name=(str, Field(..., title='Name', min_length=1)),
    business_description=(str | None, Field(None, title='Business Description')),
    email=(str | None, Field(None, title='Email')),
    address=(str | None, Field(None, title='Address')),
    postal_code=(str | None, Field(None, title='Postal Code')),
    city=(str | None, Field(None, title='City')),
    state=(str | None, Field(None, title='State')),
    country=(str | None, Field(None, title='Country')),
    staff=(str | None, Field(None, title='Staff')),
    siret=(str | None, Field(None, title='Siret')),
    vat_number=(str | None, Field(None, title='Vat Number')),
    website=(str | None, Field(None, title='Website')),
    url_linkedin=(str | None, Field(None, title='Url Linkedin')),
    hubspot_id=(str | None, Field(None, title='Hubspot Id')),
    owner_id=(str | None, Field(None, title='Owner Id')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
)

OPERATIONS['update_company'] = ('PATCH', '/api/v2/companies/{id}', (), ('name', 'business_description', 'email', 'address', 'postal_code', 'city', 'state', 'country', 'staff', 'siret', 'vat_number', 'website', 'url_linkedin', 'hubspot_id', 'owner_id', 'tags'))
CONFIG_MODELS['update_company'] = create_model(
    'HubfloUpdateCompanyConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['update_company'], Field('update_company', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Company', "x-category": 'Company', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Company ID', min_length=1)),
    name=(str, Field(..., title='Name', min_length=1)),
    business_description=(str | None, Field(None, title='Business Description')),
    email=(str | None, Field(None, title='Email')),
    address=(str | None, Field(None, title='Address')),
    postal_code=(str | None, Field(None, title='Postal Code')),
    city=(str | None, Field(None, title='City')),
    state=(str | None, Field(None, title='State')),
    country=(str | None, Field(None, title='Country')),
    staff=(str | None, Field(None, title='Staff')),
    siret=(str | None, Field(None, title='Siret')),
    vat_number=(str | None, Field(None, title='Vat Number')),
    website=(str | None, Field(None, title='Website')),
    url_linkedin=(str | None, Field(None, title='Url Linkedin')),
    hubspot_id=(str | None, Field(None, title='Hubspot Id')),
    owner_id=(str | None, Field(None, title='Owner Id')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
)

OPERATIONS['list_tasks'] = ('GET', '/api/v2/tasks', ('page', 'per_page', 'overdue', 'project_id', 'contact_id', 'assignee_id', 'creator_type', 'completed', 'parent_id', 'clickup_id', 'monday_id', 'tag'), ())
CONFIG_MODELS['list_tasks'] = create_model(
    'HubfloListTasksConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['list_tasks'], Field('list_tasks', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Tasks', "x-category": 'Task', "x-is-trigger": False})),
    page=(int | None, Field(1, title='Page', description='Page number', ge=1)),
    per_page=(int | None, Field(20, title='Per Page', description='Number of items per page (max 100)', ge=1, le=100)),
    overdue=(bool | None, Field(None, title='Overdue', description='Filter by overdue tasks')),
    project_id=(str | None, Field(None, title='Project Id', description='Filter by project ID')),
    contact_id=(str | None, Field(None, title='Contact Id', description='Filter by contact ID')),
    assignee_id=(str | None, Field(None, title='Assignee Id', description='Filter by assignee ID')),
    creator_type=(str | None, Field(None, title='Creator Type', description='Filter by creator type (user or contact)')),
    completed=(bool | None, Field(None, title='Completed', description='Filter by completion status')),
    parent_id=(str | None, Field(None, title='Parent Id', description='Filter by parent task ID. If not provided, the endpoint will return\nfirst level tasks (no subtasks).\n')),
    clickup_id=(str | None, Field(None, title='Clickup Id', description='Filter by clickup_id')),
    monday_id=(str | None, Field(None, title='Monday Id', description='Filter by monday_id')),
    tag=(str | None, Field(None, title='Tag', description='Filter by tag')),
)

OPERATIONS['get_task'] = ('GET', '/api/v2/tasks/{id}', (), ())
CONFIG_MODELS['get_task'] = create_model(
    'HubfloGetTaskConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['get_task'], Field('get_task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Task', "x-category": 'Task', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Task ID', min_length=1)),
)

OPERATIONS['create_task'] = ('POST', '/api/v2/tasks', (), ('name', 'description', 'start_time', 'completed', 'clickup_id', 'monday_id', 'kind', 'visible_by_contact', 'template_id', 'parent_task_id', 'project_id', 'project_section_id', 'contact_id', 'workspace_id', 'user_ids', 'contact_ids', 'tags', 'recurrence_type', 'recurrence_frequency', 'recurrence_customable_type', 'recurrence_week_days', 'recurrence_day_into_month', 'recurrence_days_after_completion'))
CONFIG_MODELS['create_task'] = create_model(
    'HubfloCreateTaskConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['create_task'], Field('create_task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Task', "x-category": 'Task', "x-is-trigger": False})),
    name=(str, Field(..., title='Name', min_length=1)),
    description=(str | None, Field(None, title='Description')),
    start_time=(str | None, Field(None, title='Start Time')),
    completed=(bool | None, Field(None, title='Completed')),
    clickup_id=(str | None, Field(None, title='Clickup Id')),
    monday_id=(str | None, Field(None, title='Monday Id')),
    kind=(Literal['to_do', 'call', 'meeting', 'email', 'milestone'] | None, Field(None, title='Kind')),
    visible_by_contact=(bool | None, Field(None, title='Visible By Contact')),
    template_id=(str | None, Field(None, title='Template Id', description='ID of a task template to instantiate the task from. When provided, the task is created from the template (its name, description, assignments, tags, custom fields, files and subtasks are copied) and the template attributes take precedence over the other attributes.')),
    parent_task_id=(str | None, Field(None, title='Parent Task Id')),
    project_id=(str | None, Field(None, title='Project Id')),
    project_section_id=(str | None, Field(None, title='Project Section Id', description='Only project sections that are not templates can be used. Deprecated: attaching a task to a non-template project section is deprecated.')),
    contact_id=(str | None, Field(None, title='Contact Id')),
    workspace_id=(str | None, Field(None, title='Workspace Id', description='Deprecated: attaching a task to a non-template workspace is deprecated.')),
    user_ids=(list[str] | None, Field(None, title='User Ids')),
    contact_ids=(list[str] | None, Field(None, title='Contact Ids')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
    recurrence_type=(Literal['Weekly', 'Monthly', 'Yearly', 'Periodically', 'Custom'] | None, Field(None, title='Recurrence Type', description='Recurrence kind. Send `null` to remove an existing rule. Other\n`recurrence_*` attributes depend on this type.\n')),
    recurrence_frequency=(int | None, Field(None, title='Recurrence Frequency')),
    recurrence_customable_type=(Literal['Weekly', 'Monthly'] | None, Field(None, title='Recurrence Customable Type')),
    recurrence_week_days=(list[str] | None, Field(None, title='Recurrence Week Days')),
    recurrence_day_into_month=(int | None, Field(None, title='Recurrence Day Into Month')),
    recurrence_days_after_completion=(int | None, Field(None, title='Recurrence Days After Completion')),
)

OPERATIONS['update_task'] = ('PATCH', '/api/v2/tasks/{id}', (), ('name', 'description', 'start_time', 'completed', 'clickup_id', 'monday_id', 'kind', 'visible_by_contact', 'project_id', 'project_section_id', 'contact_id', 'workspace_id', 'user_ids', 'contact_ids', 'tags', 'recurrence_type', 'recurrence_frequency', 'recurrence_customable_type', 'recurrence_week_days', 'recurrence_day_into_month', 'recurrence_days_after_completion'))
CONFIG_MODELS['update_task'] = create_model(
    'HubfloUpdateTaskConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['update_task'], Field('update_task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Task', "x-category": 'Task', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Task ID', min_length=1)),
    name=(str, Field(..., title='Name', min_length=1)),
    description=(str | None, Field(None, title='Description')),
    start_time=(str | None, Field(None, title='Start Time')),
    completed=(bool | None, Field(None, title='Completed')),
    clickup_id=(str | None, Field(None, title='Clickup Id')),
    monday_id=(str | None, Field(None, title='Monday Id')),
    kind=(Literal['to_do', 'call', 'meeting', 'email', 'milestone'] | None, Field(None, title='Kind')),
    visible_by_contact=(bool | None, Field(None, title='Visible By Contact')),
    project_id=(str | None, Field(None, title='Project Id')),
    project_section_id=(str | None, Field(None, title='Project Section Id', description='Only project sections that are not templates can be used. Deprecated: attaching a task to a non-template project section is deprecated.')),
    contact_id=(str | None, Field(None, title='Contact Id')),
    workspace_id=(str | None, Field(None, title='Workspace Id', description='Deprecated: attaching a task to a non-template workspace is deprecated.')),
    user_ids=(list[str] | None, Field(None, title='User Ids')),
    contact_ids=(list[str] | None, Field(None, title='Contact Ids')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
    recurrence_type=(Literal['Weekly', 'Monthly', 'Yearly', 'Periodically', 'Custom'] | None, Field(None, title='Recurrence Type', description='Recurrence kind. Omit to leave the existing rule unchanged.\nSend `null` to remove an existing rule. Other `recurrence_*`\nattributes depend on this type.\n')),
    recurrence_frequency=(int | None, Field(None, title='Recurrence Frequency')),
    recurrence_customable_type=(Literal['Weekly', 'Monthly'] | None, Field(None, title='Recurrence Customable Type')),
    recurrence_week_days=(list[str] | None, Field(None, title='Recurrence Week Days')),
    recurrence_day_into_month=(int | None, Field(None, title='Recurrence Day Into Month')),
    recurrence_days_after_completion=(int | None, Field(None, title='Recurrence Days After Completion')),
)

OPERATIONS['list_projects'] = ('GET', '/api/v2/projects', ('page', 'per_page', 'owner_id', 'owner_email', 'contact_id', 'contact_email', 'contact_phone', 'workspace_id', 'name'), ())
CONFIG_MODELS['list_projects'] = create_model(
    'HubfloListProjectsConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['list_projects'], Field('list_projects', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Projects', "x-category": 'Project', "x-is-trigger": False})),
    page=(int | None, Field(1, title='Page', description='Page number', ge=1)),
    per_page=(int | None, Field(20, title='Per Page', description='Number of items per page (max 100)', ge=1, le=100)),
    owner_id=(str | None, Field(None, title='Owner Id', description='Filter by owner ID')),
    owner_email=(str | None, Field(None, title='Owner Email', description='Filter by owner email')),
    contact_id=(str | None, Field(None, title='Contact Id', description='Filter by contact ID')),
    contact_email=(str | None, Field(None, title='Contact Email', description='Filter by contact email')),
    contact_phone=(str | None, Field(None, title='Contact Phone', description='Filter by contact phone')),
    workspace_id=(str | None, Field(None, title='Workspace Id', description='Filter by workspace ID')),
    name=(str | None, Field(None, title='Name', description='Filter by name')),
)

OPERATIONS['get_project'] = ('GET', '/api/v2/projects/{id}', (), ())
CONFIG_MODELS['get_project'] = create_model(
    'HubfloGetProjectConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['get_project'], Field('get_project', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Project', "x-category": 'Project', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Project ID', min_length=1)),
)

OPERATIONS['create_project'] = ('POST', '/api/v2/projects', (), ('name', 'estimated_revenue_amount', 'start_date', 'end_date', 'owner_id', 'owner_email', 'stage_id', 'primary_contact_id', 'address', 'workspace_id', 'tags', 'user_ids'))
CONFIG_MODELS['create_project'] = create_model(
    'HubfloCreateProjectConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['create_project'], Field('create_project', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Project', "x-category": 'Project', "x-is-trigger": False})),
    name=(str, Field(..., title='Name', min_length=1)),
    estimated_revenue_amount=(float | None, Field(None, title='Estimated Revenue Amount')),
    start_date=(str | None, Field(None, title='Start Date')),
    end_date=(str | None, Field(None, title='End Date')),
    owner_id=(str | None, Field(None, title='Owner Id')),
    owner_email=(str | None, Field(None, title='Owner Email')),
    stage_id=(str | None, Field(None, title='Stage Id')),
    primary_contact_id=(str | None, Field(None, title='Primary Contact Id')),
    address=(str | None, Field(None, title='Address')),
    workspace_id=(str | None, Field(None, title='Workspace Id')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
    user_ids=(list[str] | None, Field(None, title='User Ids')),
)

OPERATIONS['update_project'] = ('PATCH', '/api/v2/projects/{id}', (), ('name', 'estimated_revenue_amount', 'start_date', 'end_date', 'owner_id', 'owner_email', 'stage_id', 'primary_contact_id', 'address', 'workspace_id', 'tags', 'user_ids'))
CONFIG_MODELS['update_project'] = create_model(
    'HubfloUpdateProjectConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['update_project'], Field('update_project', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Project', "x-category": 'Project', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Project ID', min_length=1)),
    name=(str, Field(..., title='Name', min_length=1)),
    estimated_revenue_amount=(float | None, Field(None, title='Estimated Revenue Amount')),
    start_date=(str | None, Field(None, title='Start Date')),
    end_date=(str | None, Field(None, title='End Date')),
    owner_id=(str | None, Field(None, title='Owner Id')),
    owner_email=(str | None, Field(None, title='Owner Email')),
    stage_id=(str | None, Field(None, title='Stage Id')),
    primary_contact_id=(str | None, Field(None, title='Primary Contact Id')),
    address=(str | None, Field(None, title='Address')),
    workspace_id=(str | None, Field(None, title='Workspace Id')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
    user_ids=(list[str] | None, Field(None, title='User Ids')),
)

OPERATIONS['list_workspaces'] = ('GET', '/api/v2/workspaces', ('page', 'per_page', 'project_id', 'workspace_id', 'title'), ())
CONFIG_MODELS['list_workspaces'] = create_model(
    'HubfloListWorkspacesConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['list_workspaces'], Field('list_workspaces', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Workspaces', "x-category": 'Workspace', "x-is-trigger": False})),
    page=(int | None, Field(1, title='Page', description='Page number', ge=1)),
    per_page=(int | None, Field(20, title='Per Page', description='Number of items per page (max 100)', ge=1, le=100)),
    project_id=(str | None, Field(None, title='Project Id', description='Filter by project ID')),
    workspace_id=(str | None, Field(None, title='Workspace Id', description='Filter by workspace ID')),
    title=(str | None, Field(None, title='Title', description='Filter by title')),
)

OPERATIONS['get_workspace'] = ('GET', '/api/v2/workspaces/{id}', (), ())
CONFIG_MODELS['get_workspace'] = create_model(
    'HubfloGetWorkspaceConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['get_workspace'], Field('get_workspace', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Workspace', "x-category": 'Workspace', "x-is-trigger": False})),
    id=(str, Field(..., title='Id', description='Workspace ID', min_length=1)),
)

OPERATIONS['create_workspace'] = ('POST', '/api/v2/workspaces', (), ('title', 'subtitle', 'welcome_message', 'chat_room_id', 'new_chat_room', 'user_ids', 'project_id', 'template_id', 'template', 'tags'))
CONFIG_MODELS['create_workspace'] = create_model(
    'HubfloCreateWorkspaceConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['create_workspace'], Field('create_workspace', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Workspace', "x-category": 'Workspace', "x-is-trigger": False})),
    title=(str, Field(..., title='Title', min_length=1)),
    subtitle=(str | None, Field(None, title='Subtitle')),
    welcome_message=(str | None, Field(None, title='Welcome Message')),
    chat_room_id=(str | None, Field(None, title='Chat Room Id')),
    new_chat_room=(bool | None, Field(None, title='New Chat Room')),
    user_ids=(list[str] | None, Field(None, title='User Ids')),
    project_id=(str | None, Field(None, title='Project Id')),
    template_id=(str | None, Field(None, title='Template Id')),
    template=(bool | None, Field(None, title='Template')),
    tags=(list[str] | None, Field(None, title='Tags', max_length=100)),
)

OPERATIONS['create_note'] = ('POST', '/api/v2/notes', (), ('title', 'content', 'project_ids', 'contact_ids'))
CONFIG_MODELS['create_note'] = create_model(
    'HubfloCreateNoteConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['create_note'], Field('create_note', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Note', "x-category": 'Note', "x-is-trigger": False})),
    title=(str, Field(..., title='Title', min_length=1)),
    content=(str, Field(..., title='Content', min_length=1)),
    project_ids=(list[str] | None, Field(None, title='Project Ids')),
    contact_ids=(list[str] | None, Field(None, title='Contact Ids')),
)

OPERATIONS['get_organization'] = ('GET', '/api/v2/organizations', (), ())
CONFIG_MODELS['get_organization'] = create_model(
    'HubfloGetOrganizationConfig', __base__=_Input, __module__=__name__,
    operation=(Literal['get_organization'], Field('get_organization', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Organization', "x-category": 'Organizations', "x-is-trigger": False})),
)

globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
