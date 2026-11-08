"""Operations pinned to the official Teamwork API references."""

OPERATIONS = {
    "list_projects": {
        "name": "list_projects",
        "label": "List Projects",
        "category": "Projects",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects.json",
        "description": "Returns a list of projects",
        "body": False,
    },
    "get_project": {
        "name": "get_project",
        "label": "Get Project",
        "category": "Projects",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}.json",
        "description": "Returns a project",
        "body": False,
    },
    "get_project_summary": {
        "name": "get_project_summary",
        "label": "Get Project Summary",
        "category": "Projects",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectIds}/summary.json",
        "description": "Get project summary dashboard",
        "body": False,
    },
    "list_project_updates": {
        "name": "list_project_updates",
        "label": "List Project Updates",
        "category": "Projects",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectIds}/updates.json",
        "description": "Get all updates from a specific project",
        "body": False,
    },
    "list_project_people": {
        "name": "list_project_people",
        "label": "List Project People",
        "category": "Projects",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/people.json",
        "description": "Returns a list of people on a project",
        "body": False,
    },
    "add_project_person": {
        "name": "add_project_person",
        "label": "Add Project Person",
        "category": "Projects",
        "version": 3,
        "method": "PUT",
        "path": "/projects/api/v3/projects/{projectId}/people.json",
        "description": "Add people to a project",
        "body": True,
    },
    "create_project": {
        "name": "create_project",
        "label": "Create Project",
        "category": "Projects",
        "version": 1,
        "method": "POST",
        "path": "/projects.json",
        "description": "Create Project",
        "body": True,
    },
    "update_project": {
        "name": "update_project",
        "label": "Update Project",
        "category": "Projects",
        "version": 1,
        "method": "PUT",
        "path": "/projects/{id}.json",
        "description": "Update Project",
        "body": True,
    },
    "delete_project": {
        "name": "delete_project",
        "label": "Delete Project",
        "category": "Projects",
        "version": 1,
        "method": "DELETE",
        "path": "/projects/{id}.json",
        "description": "Delete Project",
        "body": False,
    },
    "star_project": {
        "name": "star_project",
        "label": "Star Project",
        "category": "Projects",
        "version": 1,
        "method": "PUT",
        "path": "/projects/{id}/star.json",
        "description": "Star a Project",
        "body": False,
    },
    "unstar_project": {
        "name": "unstar_project",
        "label": "Unstar Project",
        "category": "Projects",
        "version": 1,
        "method": "PUT",
        "path": "/projects/{id}/unstar.json",
        "description": "Un-star a Project",
        "body": True,
    },
    "list_tasklists": {
        "name": "list_tasklists",
        "label": "List Tasklists",
        "category": "Task Lists",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasklists.json",
        "description": "Get all tasklists",
        "body": False,
    },
    "get_tasklist": {
        "name": "get_tasklist",
        "label": "Get Tasklist",
        "category": "Task Lists",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasklists/{tasklistId}.json",
        "description": "Get specific tasklist",
        "body": False,
    },
    "list_project_tasklists": {
        "name": "list_project_tasklists",
        "label": "List Project Tasklists",
        "category": "Task Lists",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/tasklists.json",
        "description": "Get tasklists in a project",
        "body": False,
    },
    "create_tasklist": {
        "name": "create_tasklist",
        "label": "Create Tasklist",
        "category": "Task Lists",
        "version": 1,
        "method": "POST",
        "path": "/projects/{id}/tasklists.json",
        "description": "Create Task List",
        "body": True,
    },
    "update_tasklist": {
        "name": "update_tasklist",
        "label": "Update Tasklist",
        "category": "Task Lists",
        "version": 1,
        "method": "PUT",
        "path": "/tasklists/{id}.json",
        "description": "Update Task List",
        "body": True,
    },
    "delete_tasklist": {
        "name": "delete_tasklist",
        "label": "Delete Tasklist",
        "category": "Task Lists",
        "version": 1,
        "method": "DELETE",
        "path": "/tasklists/{id}.json",
        "description": "Delete a Task List",
        "body": False,
    },
    "list_tasks": {
        "name": "list_tasks",
        "label": "List Tasks",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasks.json",
        "description": "Get all tasks",
        "body": False,
    },
    "list_project_tasks": {
        "name": "list_project_tasks",
        "label": "List Project Tasks",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/tasks.json",
        "description": "Get a specific project's tasks",
        "body": False,
    },
    "list_tasklist_tasks": {
        "name": "list_tasklist_tasks",
        "label": "List Tasklist Tasks",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasklists/{tasklistId}/tasks.json",
        "description": "Get a specific tasklist's tasks",
        "body": False,
    },
    "get_task": {
        "name": "get_task",
        "label": "Get Task",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasks/{taskId}.json",
        "description": "Get a specific task",
        "body": False,
    },
    "create_task": {
        "name": "create_task",
        "label": "Create Task",
        "category": "Tasks",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/tasklists/{tasklistId}/tasks.json",
        "description": "Creates a task",
        "body": True,
    },
    "update_task": {
        "name": "update_task",
        "label": "Update Task",
        "category": "Tasks",
        "version": 3,
        "method": "PATCH",
        "path": "/projects/api/v3/tasks/{taskId}.json",
        "description": "Update an existing task",
        "body": True,
    },
    "delete_task": {
        "name": "delete_task",
        "label": "Delete Task",
        "category": "Tasks",
        "version": 3,
        "method": "DELETE",
        "path": "/projects/api/v3/tasks/{taskId}.json",
        "description": "Delete an existing task",
        "body": False,
    },
    "list_subtasks": {
        "name": "list_subtasks",
        "label": "List Subtasks",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasks/{taskId}/subtasks.json",
        "description": "Get all subtasks for a specific task",
        "body": False,
    },
    "create_subtask": {
        "name": "create_subtask",
        "label": "Create Subtask",
        "category": "Tasks",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/tasks/{taskId}/subtasks.json",
        "description": "Creates a subtask",
        "body": True,
    },
    "list_task_comments": {
        "name": "list_task_comments",
        "label": "List Task Comments",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasks/{taskId}/comments.json",
        "description": "Get a list of comments for a task",
        "body": False,
    },
    "create_task_comment": {
        "name": "create_task_comment",
        "label": "Create Task Comment",
        "category": "Tasks",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/tasks/{taskId}/comments.json",
        "description": "Create a comment on a task",
        "body": True,
    },
    "get_task_time_total": {
        "name": "get_task_time_total",
        "label": "Get Task Time Total",
        "category": "Tasks",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasks/{taskId}/time/total.json",
        "description": "Get timelog totals for a specific task",
        "body": False,
    },
    "complete_task": {
        "name": "complete_task",
        "label": "Complete Task",
        "category": "Tasks",
        "version": 1,
        "method": "PUT",
        "path": "/tasks/{id}/complete.json",
        "description": "Mark a Task complete",
        "body": False,
    },
    "uncomplete_task": {
        "name": "uncomplete_task",
        "label": "Uncomplete Task",
        "category": "Tasks",
        "version": 1,
        "method": "PUT",
        "path": "/tasks/{id}/uncomplete.json",
        "description": "Mark a Task uncomplete",
        "body": False,
    },
    "list_milestones": {
        "name": "list_milestones",
        "label": "List Milestones",
        "category": "Milestones",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/milestones.json",
        "description": "Get all milestones",
        "body": False,
    },
    "list_project_milestones": {
        "name": "list_project_milestones",
        "label": "List Project Milestones",
        "category": "Milestones",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/milestones.json",
        "description": "Get milestones in a project",
        "body": False,
    },
    "get_milestone": {
        "name": "get_milestone",
        "label": "Get Milestone",
        "category": "Milestones",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/milestones/{milestoneId}.json",
        "description": "Get a milestone by id",
        "body": False,
    },
    "create_milestone": {
        "name": "create_milestone",
        "label": "Create Milestone",
        "category": "Milestones",
        "version": 1,
        "method": "POST",
        "path": "/projects/{id}/milestones.json",
        "description": "Create a Single Milestone",
        "body": True,
    },
    "update_milestone": {
        "name": "update_milestone",
        "label": "Update Milestone",
        "category": "Milestones",
        "version": 1,
        "method": "PUT",
        "path": "/milestones/{id}.json",
        "description": "Update a Single Milestone",
        "body": True,
    },
    "delete_milestone": {
        "name": "delete_milestone",
        "label": "Delete Milestone",
        "category": "Milestones",
        "version": 1,
        "method": "DELETE",
        "path": "/milestones/{id}.json",
        "description": "Delete a Milestone",
        "body": False,
    },
    "complete_milestone": {
        "name": "complete_milestone",
        "label": "Complete Milestone",
        "category": "Milestones",
        "version": 1,
        "method": "PUT",
        "path": "/milestones/{id}/complete.json",
        "description": "Complete a Milestone",
        "body": False,
    },
    "uncomplete_milestone": {
        "name": "uncomplete_milestone",
        "label": "Uncomplete Milestone",
        "category": "Milestones",
        "version": 1,
        "method": "PUT",
        "path": "/milestones/{id}/uncomplete.json",
        "description": "Un-complete a Milestone",
        "body": False,
    },
    "list_people": {
        "name": "list_people",
        "label": "List People",
        "category": "People",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/people.json",
        "description": "Returns a list of people",
        "body": False,
    },
    "get_person": {
        "name": "get_person",
        "label": "Get Person",
        "category": "People",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/people/{personId}.json",
        "description": "Returns a person",
        "body": False,
    },
    "list_project_people_details": {
        "name": "list_project_people_details",
        "label": "List Project People Details",
        "category": "People",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/people/{personId}.json",
        "description": "Returns a person on a project",
        "body": False,
    },
    "get_current_user": {
        "name": "get_current_user",
        "label": "Get Current User",
        "category": "People",
        "version": 1,
        "method": "GET",
        "path": "/me.json",
        "description": "Get Current User Details",
        "body": False,
    },
    "list_companies": {
        "name": "list_companies",
        "label": "List Companies",
        "category": "Companies",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/companies.json",
        "description": "Get all companies",
        "body": False,
    },
    "get_company": {
        "name": "get_company",
        "label": "Get Company",
        "category": "Companies",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/companies/{companyId}.json",
        "description": "Get a specific company",
        "body": False,
    },
    "create_company": {
        "name": "create_company",
        "label": "Create Company",
        "category": "Companies",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/companies.json",
        "description": "Create a company",
        "body": True,
    },
    "update_company": {
        "name": "update_company",
        "label": "Update Company",
        "category": "Companies",
        "version": 3,
        "method": "PATCH",
        "path": "/projects/api/v3/companies/{companyId}.json",
        "description": "Update an existing company",
        "body": True,
    },
    "delete_company": {
        "name": "delete_company",
        "label": "Delete Company",
        "category": "Companies",
        "version": 3,
        "method": "DELETE",
        "path": "/projects/api/v3/companies/{companyId}.json",
        "description": "Delete an existing company",
        "body": False,
    },
    "list_tags": {
        "name": "list_tags",
        "label": "List Tags",
        "category": "Tags",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tags.json",
        "description": "Get all tags",
        "body": False,
    },
    "get_tag": {
        "name": "get_tag",
        "label": "Get Tag",
        "category": "Tags",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tags/{tagId}.json",
        "description": "Get details of an individual tag",
        "body": False,
    },
    "create_tag": {
        "name": "create_tag",
        "label": "Create Tag",
        "category": "Tags",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/tags.json",
        "description": "Create a single tag",
        "body": True,
    },
    "update_tag": {
        "name": "update_tag",
        "label": "Update Tag",
        "category": "Tags",
        "version": 3,
        "method": "PATCH",
        "path": "/projects/api/v3/tags/{tagId}.json",
        "description": "Update a single tag",
        "body": True,
    },
    "delete_tag": {
        "name": "delete_tag",
        "label": "Delete Tag",
        "category": "Tags",
        "version": 3,
        "method": "DELETE",
        "path": "/projects/api/v3/tags/{tagId}.json",
        "description": "Deletes a tag",
        "body": False,
    },
    "list_project_time": {
        "name": "list_project_time",
        "label": "List Project Time",
        "category": "Time",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/time.json",
        "description": "Get time entries for a specific project",
        "body": False,
    },
    "list_task_time": {
        "name": "list_task_time",
        "label": "List Task Time",
        "category": "Time",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/tasks/{taskId}/time.json",
        "description": "Get time entries for a specific task",
        "body": False,
    },
    "log_project_time": {
        "name": "log_project_time",
        "label": "Log Project Time",
        "category": "Time",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/projects/{projectId}/time.json",
        "description": "Create a time entry in a specific project",
        "body": True,
    },
    "log_task_time": {
        "name": "log_task_time",
        "label": "Log Task Time",
        "category": "Time",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/tasks/{taskId}/time.json",
        "description": "Create a time entry linked to a specific task",
        "body": True,
    },
    "get_project_time_total": {
        "name": "get_project_time_total",
        "label": "Get Project Time Total",
        "category": "Time",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/projects/{projectId}/time/total.json",
        "description": "Get timelog totals for a specific project",
        "body": False,
    },
    "list_my_timers": {
        "name": "list_my_timers",
        "label": "List My Timers",
        "category": "Time",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/me/timers.json",
        "description": "Get all your running timers",
        "body": False,
    },
    "create_timer": {
        "name": "create_timer",
        "label": "Create Timer",
        "category": "Time",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/me/timers.json",
        "description": "Create a new timer",
        "body": True,
    },
    "pause_timer": {
        "name": "pause_timer",
        "label": "Pause Timer",
        "category": "Time",
        "version": 3,
        "method": "PUT",
        "path": "/projects/api/v3/me/timers/{timerId}/pause.json",
        "description": "Pause a timer by ID",
        "body": False,
    },
    "resume_timer": {
        "name": "resume_timer",
        "label": "Resume Timer",
        "category": "Time",
        "version": 3,
        "method": "PUT",
        "path": "/projects/api/v3/me/timers/{timerId}/resume.json",
        "description": "Resume a timer by ID",
        "body": False,
    },
    "complete_timer": {
        "name": "complete_timer",
        "label": "Complete Timer",
        "category": "Time",
        "version": 3,
        "method": "PUT",
        "path": "/projects/api/v3/me/timers/{timerId}/complete.json",
        "description": "Complete a timer by ID",
        "body": False,
    },
    "delete_timer": {
        "name": "delete_timer",
        "label": "Delete Timer",
        "category": "Time",
        "version": 3,
        "method": "DELETE",
        "path": "/projects/api/v3/me/timers/{timerId}.json",
        "description": "Delete a timer by ID",
        "body": True,
    },
    "list_comments": {
        "name": "list_comments",
        "label": "List Comments",
        "category": "Comments",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/comments.json",
        "description": "Get a list of comments",
        "body": False,
    },
    "get_comment": {
        "name": "get_comment",
        "label": "Get Comment",
        "category": "Comments",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/comments/{id}.json",
        "description": "Retrieve a specific comment",
        "body": False,
    },
    "create_comment": {
        "name": "create_comment",
        "label": "Create Comment",
        "category": "Comments",
        "version": 3,
        "method": "POST",
        "path": "/projects/api/v3/comments.json",
        "description": "Create a comment",
        "body": True,
    },
    "search": {
        "name": "search",
        "label": "Search",
        "category": "Search",
        "version": 3,
        "method": "GET",
        "path": "/projects/api/v3/search.json",
        "description": "Search items in the installation",
        "body": False,
    },
}

# Request constraints copied from the provider's published Projects v3 contract:
# https://contento-assets.s3.eu-west-1.amazonaws.com/oas/teamwork_docs/projects/reference/projects-api-v3.oas2.yml
# References are inlined; no example or constraint is synthesized.
BODY_SCHEMAS = {
    "add_project_person": {
        "description": "UsersPayload consists of userIDs",
        "properties": {
            "checkTeamIds": {"items": {"type": "integer"}, "type": "array"},
            "userIds": {"items": {"type": "integer"}, "type": "array"},
        },
        "required": ["userIds", "checkTeamIds"],
        "title": "UsersPayload",
        "type": "object",
    },
    "create_task": {
        "description": "Request contains information of a task to be created or updated.",
        "properties": {
            "attachmentOptions": {
                "properties": {"removeOtherFiles": {"type": "boolean"}},
                "type": "object",
            },
            "attachments": {
                "properties": {
                    "files": {
                        "items": {
                            "description": "File stores "
                            "information about a "
                            "uploaded file.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "id": {"type": "integer"},
                            },
                            "required": ["id"],
                            "title": "File",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "pendingFiles": {
                        "items": {
                            "description": "PendingFile "
                            "stores "
                            "information "
                            "about a file "
                            "uploaded "
                            "on-the-fly.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "reference": {"type": "string"},
                            },
                            "required": ["reference"],
                            "title": "PendingFile",
                            "type": "object",
                        },
                        "type": "array",
                    },
                },
                "type": "object",
            },
            "predecessors": {
                "items": {
                    "description": "Predecessor stores information about task "
                    "predecessors.",
                    "properties": {
                        "id": {"type": "integer"},
                        "type": {"type": "string"},
                    },
                    "required": ["id", "type"],
                    "title": "Predecessor",
                    "type": "object",
                },
                "type": "array",
            },
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from a "
                    "tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
            "task": {
                "description": "Task contains all the information returned from a task.",
                "properties": {
                    "allocationId": {"type": "integer"},
                    "assignees": {
                        "description": "UserGroups are common lists for "
                        "storing users, companies, teams "
                        "and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "attachmentIds": {"items": {"type": "integer"}, "type": "array"},
                    "changeFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "commentFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "completeFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "completedAt": {"type": "string"},
                    "completedBy": {"type": "integer"},
                    "createdAt": {"type": "string"},
                    "createdBy": {"type": "integer"},
                    "crmDealIds": {"items": {"type": "integer"}, "type": "array"},
                    "customFields": {
                        "description": "CustomFields is the custom " "fields type.",
                        "properties": {
                            "Values": {
                                "items": {
                                    "description": "CustomFieldValue "
                                    "contains "
                                    "all "
                                    "the "
                                    "information "
                                    "returned "
                                    "from "
                                    "a "
                                    "customfield.",
                                    "properties": {
                                        "countryCode": {"type": "string"},
                                        "currencySymbol": {"type": "string"},
                                        "customfieldId": {"type": "integer"},
                                        "urlTextToDisplay": {"type": "string"},
                                        "value": {
                                            "description": "The "
                                            "shape "
                                            "depends "
                                            "on "
                                            "the "
                                            "type "
                                            "of "
                                            "the "
                                            "related "
                                            "custom "
                                            "field; "
                                            "null "
                                            "clears "
                                            "it. "
                                            "One "
                                            "of: "
                                            "string, "
                                            "number, "
                                            "boolean, "
                                            "string[].",
                                            "type": "any",
                                        },
                                    },
                                    "required": [
                                        "customfieldId",
                                        "value",
                                        "countryCode",
                                        "currencySymbol",
                                        "urlTextToDisplay",
                                    ],
                                    "title": "CustomFieldValue",
                                    "type": "object",
                                },
                                "type": "array",
                            }
                        },
                        "required": ["Values"],
                        "title": "CustomFields",
                        "type": "object",
                    },
                    "description": {"type": "string"},
                    "descriptionContentType": {"type": "string"},
                    "dueAt": {"format": "date", "type": "string"},
                    "dueDate": {
                        "description": "DueDate is an alias for DueAt, "
                        "matching the field name the task "
                        "views\n"
                        "return",
                        "type": "string",
                    },
                    "estimatedMinutes": {"type": "integer"},
                    "grantAccessTo": {
                        "description": "UserGroups are common lists "
                        "for storing users, "
                        "companies, teams and jobRole "
                        "ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "hasDeskTickets": {"type": "boolean"},
                    "name": {"type": "string"},
                    "notify": {"type": "boolean"},
                    "originalDueDate": {"format": "date", "type": "string"},
                    "parentTaskId": {"type": "integer"},
                    "priority": {
                        "description": "NullableTaskPriority implements "
                        "json.Unmarshaler to allow "
                        "testing\n"
                        "between a value that explicitly "
                        "set to null or omitted.",
                        "properties": {
                            "Null": {"type": "boolean"},
                            "Set": {"type": "boolean"},
                            "Value": {"type": "string"},
                        },
                        "required": ["Value", "Null", "Set"],
                        "title": "NullableTaskPriority",
                        "type": "object",
                    },
                    "private": {"type": "boolean"},
                    "progress": {"type": "integer"},
                    "projectId": {"type": "integer"},
                    "reminders": {
                        "items": {
                            "description": "Reminder stores all "
                            "necessary information "
                            "to create a task "
                            "reminder.",
                            "properties": {
                                "isRelative": {"type": "boolean"},
                                "note": {"type": "string"},
                                "relativeNumberDays": {"type": "integer"},
                                "remindAt": {"type": "string"},
                                "type": {"type": "string"},
                                "userId": {"type": "integer"},
                            },
                            "required": [
                                "userId",
                                "remindAt",
                                "type",
                                "note",
                                "isRelative",
                                "relativeNumberDays",
                            ],
                            "title": "Reminder",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "repeatOptions": {
                        "description": "RepeatOptions stores "
                        "recurring information for "
                        "the task.",
                        "properties": {
                            "duration": {"type": "integer"},
                            "editOption": {"type": "string"},
                            "endsAt": {"format": "date", "type": "string"},
                            "frequency": {
                                "description": "NullableTaskRepeatFrequency "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableTaskRepeatFrequency",
                                "type": "object",
                            },
                            "monthlyRepeatType": {
                                "description": "NullableTaskRepeatMonthlyType "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableTaskRepeatMonthlyType",
                                "type": "object",
                            },
                            "rrule": {
                                "description": "Adds "
                                "the "
                                "RRule "
                                "definition "
                                "for "
                                "repeating "
                                "tasks. "
                                "It "
                                "replaces "
                                "all "
                                "other "
                                "repeating "
                                "fields.",
                                "title": "RRule",
                                "type": "string",
                            },
                            "selectedDays": {
                                "description": "NullableWorkingHourEntryWeekdays "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "string"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableWorkingHourEntryWeekdays",
                                "type": "object",
                            },
                        },
                        "required": [
                            "selectedDays",
                            "endsAt",
                            "frequency",
                            "monthlyRepeatType",
                            "duration",
                            "rrule",
                        ],
                        "title": "RepeatOptions",
                        "type": "object",
                    },
                    "startAt": {"format": "date", "type": "string"},
                    "startDate": {
                        "description": "StartDate is an alias for "
                        "StartAt, matching the field name "
                        "the task views\n"
                        "return",
                        "type": "string",
                    },
                    "status": {"type": "string"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "taskgroupId": {"type": "integer"},
                    "tasklistId": {"type": "integer"},
                    "templateRoleName": {"type": "string"},
                    "ticketId": {"type": "integer"},
                },
                "required": [
                    "startAt",
                    "startDate",
                    "dueAt",
                    "dueDate",
                    "originalDueDate",
                    "priority",
                    "customFields",
                ],
                "title": "Task",
                "type": "object",
            },
            "taskOptions": {
                "description": "Options contains any options which can be set\n"
                "for the task request",
                "properties": {
                    "appendAssignees": {"type": "boolean"},
                    "checkInvalidusers": {"type": "boolean"},
                    "everyoneMustDo": {"type": "boolean"},
                    "fireWebhook": {"type": "boolean"},
                    "isTemplate": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "notify": {"type": "boolean"},
                    "parseInlineTags": {"type": "boolean"},
                    "positionAfterTaskId": {"type": "integer"},
                    "pushDependents": {"type": "boolean"},
                    "pushSubtasks": {"type": "boolean"},
                    "shiftProjectDates": {"type": "boolean"},
                    "useDefaults": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "required": [
                    "notify",
                    "everyoneMustDo",
                    "isTemplate",
                    "parseInlineTags",
                    "appendAssignees",
                    "checkInvalidusers",
                    "pushSubtasks",
                    "pushDependents",
                ],
                "title": "Options",
                "type": "object",
            },
            "workflows": {
                "description": "Workflows stores information about where the task lives "
                "in the workflow",
                "properties": {
                    "positionAfterTask": {"type": "integer"},
                    "stageId": {"type": "integer"},
                    "workflowId": {"type": "integer"},
                },
                "title": "Workflows",
                "type": "object",
            },
        },
        "required": [
            "task",
            "taskOptions",
            "tags",
            "attachments",
            "attachmentOptions",
            "predecessors",
            "workflows",
        ],
        "title": "Request",
        "type": "object",
    },
    "update_task": {
        "description": "Request contains information of a task to be created or updated.",
        "properties": {
            "attachmentOptions": {
                "properties": {"removeOtherFiles": {"type": "boolean"}},
                "type": "object",
            },
            "attachments": {
                "properties": {
                    "files": {
                        "items": {
                            "description": "File stores "
                            "information about a "
                            "uploaded file.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "id": {"type": "integer"},
                            },
                            "required": ["id"],
                            "title": "File",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "pendingFiles": {
                        "items": {
                            "description": "PendingFile "
                            "stores "
                            "information "
                            "about a file "
                            "uploaded "
                            "on-the-fly.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "reference": {"type": "string"},
                            },
                            "required": ["reference"],
                            "title": "PendingFile",
                            "type": "object",
                        },
                        "type": "array",
                    },
                },
                "type": "object",
            },
            "predecessors": {
                "items": {
                    "description": "Predecessor stores information about task "
                    "predecessors.",
                    "properties": {
                        "id": {"type": "integer"},
                        "type": {"type": "string"},
                    },
                    "required": ["id", "type"],
                    "title": "Predecessor",
                    "type": "object",
                },
                "type": "array",
            },
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from a "
                    "tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
            "task": {
                "description": "Task contains all the information returned from a task.",
                "properties": {
                    "allocationId": {"type": "integer"},
                    "assignees": {
                        "description": "UserGroups are common lists for "
                        "storing users, companies, teams "
                        "and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "attachmentIds": {"items": {"type": "integer"}, "type": "array"},
                    "changeFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "commentFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "completeFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "completedAt": {"type": "string"},
                    "completedBy": {"type": "integer"},
                    "createdAt": {"type": "string"},
                    "createdBy": {"type": "integer"},
                    "crmDealIds": {"items": {"type": "integer"}, "type": "array"},
                    "customFields": {
                        "description": "CustomFields is the custom " "fields type.",
                        "properties": {
                            "Values": {
                                "items": {
                                    "description": "CustomFieldValue "
                                    "contains "
                                    "all "
                                    "the "
                                    "information "
                                    "returned "
                                    "from "
                                    "a "
                                    "customfield.",
                                    "properties": {
                                        "countryCode": {"type": "string"},
                                        "currencySymbol": {"type": "string"},
                                        "customfieldId": {"type": "integer"},
                                        "urlTextToDisplay": {"type": "string"},
                                        "value": {
                                            "description": "The "
                                            "shape "
                                            "depends "
                                            "on "
                                            "the "
                                            "type "
                                            "of "
                                            "the "
                                            "related "
                                            "custom "
                                            "field; "
                                            "null "
                                            "clears "
                                            "it. "
                                            "One "
                                            "of: "
                                            "string, "
                                            "number, "
                                            "boolean, "
                                            "string[].",
                                            "type": "any",
                                        },
                                    },
                                    "required": [
                                        "customfieldId",
                                        "value",
                                        "countryCode",
                                        "currencySymbol",
                                        "urlTextToDisplay",
                                    ],
                                    "title": "CustomFieldValue",
                                    "type": "object",
                                },
                                "type": "array",
                            }
                        },
                        "required": ["Values"],
                        "title": "CustomFields",
                        "type": "object",
                    },
                    "description": {"type": "string"},
                    "descriptionContentType": {"type": "string"},
                    "dueAt": {"format": "date", "type": "string"},
                    "dueDate": {
                        "description": "DueDate is an alias for DueAt, "
                        "matching the field name the task "
                        "views\n"
                        "return",
                        "type": "string",
                    },
                    "estimatedMinutes": {"type": "integer"},
                    "grantAccessTo": {
                        "description": "UserGroups are common lists "
                        "for storing users, "
                        "companies, teams and jobRole "
                        "ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "hasDeskTickets": {"type": "boolean"},
                    "name": {"type": "string"},
                    "notify": {"type": "boolean"},
                    "originalDueDate": {"format": "date", "type": "string"},
                    "parentTaskId": {"type": "integer"},
                    "priority": {
                        "description": "NullableTaskPriority implements "
                        "json.Unmarshaler to allow "
                        "testing\n"
                        "between a value that explicitly "
                        "set to null or omitted.",
                        "properties": {
                            "Null": {"type": "boolean"},
                            "Set": {"type": "boolean"},
                            "Value": {"type": "string"},
                        },
                        "required": ["Value", "Null", "Set"],
                        "title": "NullableTaskPriority",
                        "type": "object",
                    },
                    "private": {"type": "boolean"},
                    "progress": {"type": "integer"},
                    "projectId": {"type": "integer"},
                    "reminders": {
                        "items": {
                            "description": "Reminder stores all "
                            "necessary information "
                            "to create a task "
                            "reminder.",
                            "properties": {
                                "isRelative": {"type": "boolean"},
                                "note": {"type": "string"},
                                "relativeNumberDays": {"type": "integer"},
                                "remindAt": {"type": "string"},
                                "type": {"type": "string"},
                                "userId": {"type": "integer"},
                            },
                            "required": [
                                "userId",
                                "remindAt",
                                "type",
                                "note",
                                "isRelative",
                                "relativeNumberDays",
                            ],
                            "title": "Reminder",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "repeatOptions": {
                        "description": "RepeatOptions stores "
                        "recurring information for "
                        "the task.",
                        "properties": {
                            "duration": {"type": "integer"},
                            "editOption": {"type": "string"},
                            "endsAt": {"format": "date", "type": "string"},
                            "frequency": {
                                "description": "NullableTaskRepeatFrequency "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableTaskRepeatFrequency",
                                "type": "object",
                            },
                            "monthlyRepeatType": {
                                "description": "NullableTaskRepeatMonthlyType "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableTaskRepeatMonthlyType",
                                "type": "object",
                            },
                            "rrule": {
                                "description": "Adds "
                                "the "
                                "RRule "
                                "definition "
                                "for "
                                "repeating "
                                "tasks. "
                                "It "
                                "replaces "
                                "all "
                                "other "
                                "repeating "
                                "fields.",
                                "title": "RRule",
                                "type": "string",
                            },
                            "selectedDays": {
                                "description": "NullableWorkingHourEntryWeekdays "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "string"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableWorkingHourEntryWeekdays",
                                "type": "object",
                            },
                        },
                        "required": [
                            "selectedDays",
                            "endsAt",
                            "frequency",
                            "monthlyRepeatType",
                            "duration",
                            "rrule",
                        ],
                        "title": "RepeatOptions",
                        "type": "object",
                    },
                    "startAt": {"format": "date", "type": "string"},
                    "startDate": {
                        "description": "StartDate is an alias for "
                        "StartAt, matching the field name "
                        "the task views\n"
                        "return",
                        "type": "string",
                    },
                    "status": {"type": "string"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "taskgroupId": {"type": "integer"},
                    "tasklistId": {"type": "integer"},
                    "templateRoleName": {"type": "string"},
                    "ticketId": {"type": "integer"},
                },
                "required": [
                    "startAt",
                    "startDate",
                    "dueAt",
                    "dueDate",
                    "originalDueDate",
                    "priority",
                    "customFields",
                ],
                "title": "Task",
                "type": "object",
            },
            "taskOptions": {
                "description": "Options contains any options which can be set\n"
                "for the task request",
                "properties": {
                    "appendAssignees": {"type": "boolean"},
                    "checkInvalidusers": {"type": "boolean"},
                    "everyoneMustDo": {"type": "boolean"},
                    "fireWebhook": {"type": "boolean"},
                    "isTemplate": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "notify": {"type": "boolean"},
                    "parseInlineTags": {"type": "boolean"},
                    "positionAfterTaskId": {"type": "integer"},
                    "pushDependents": {"type": "boolean"},
                    "pushSubtasks": {"type": "boolean"},
                    "shiftProjectDates": {"type": "boolean"},
                    "useDefaults": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "required": [
                    "notify",
                    "everyoneMustDo",
                    "isTemplate",
                    "parseInlineTags",
                    "appendAssignees",
                    "checkInvalidusers",
                    "pushSubtasks",
                    "pushDependents",
                ],
                "title": "Options",
                "type": "object",
            },
            "workflows": {
                "description": "Workflows stores information about where the task lives "
                "in the workflow",
                "properties": {
                    "positionAfterTask": {"type": "integer"},
                    "stageId": {"type": "integer"},
                    "workflowId": {"type": "integer"},
                },
                "title": "Workflows",
                "type": "object",
            },
        },
        "required": [
            "task",
            "taskOptions",
            "tags",
            "attachments",
            "attachmentOptions",
            "predecessors",
            "workflows",
        ],
        "title": "Request",
        "type": "object",
    },
    "create_subtask": {
        "description": "Request contains information of a task to be created or updated.",
        "properties": {
            "attachmentOptions": {
                "properties": {"removeOtherFiles": {"type": "boolean"}},
                "type": "object",
            },
            "attachments": {
                "properties": {
                    "files": {
                        "items": {
                            "description": "File stores "
                            "information "
                            "about a uploaded "
                            "file.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "id": {"type": "integer"},
                            },
                            "required": ["id"],
                            "title": "File",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "pendingFiles": {
                        "items": {
                            "description": "PendingFile "
                            "stores "
                            "information "
                            "about a "
                            "file "
                            "uploaded "
                            "on-the-fly.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "reference": {"type": "string"},
                            },
                            "required": ["reference"],
                            "title": "PendingFile",
                            "type": "object",
                        },
                        "type": "array",
                    },
                },
                "type": "object",
            },
            "predecessors": {
                "items": {
                    "description": "Predecessor stores information about "
                    "task predecessors.",
                    "properties": {
                        "id": {"type": "integer"},
                        "type": {"type": "string"},
                    },
                    "required": ["id", "type"],
                    "title": "Predecessor",
                    "type": "object",
                },
                "type": "array",
            },
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from a "
                    "tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
            "task": {
                "description": "Task contains all the information returned from a task.",
                "properties": {
                    "allocationId": {"type": "integer"},
                    "assignees": {
                        "description": "UserGroups are common lists "
                        "for storing users, companies, "
                        "teams and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "attachmentIds": {"items": {"type": "integer"}, "type": "array"},
                    "changeFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing "
                        "users, companies, teams "
                        "and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "commentFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing "
                        "users, companies, "
                        "teams and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "completeFollowers": {
                        "description": "UserGroups are common "
                        "lists for storing "
                        "users, companies, "
                        "teams and jobRole "
                        "ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "completedAt": {"type": "string"},
                    "completedBy": {"type": "integer"},
                    "createdAt": {"type": "string"},
                    "createdBy": {"type": "integer"},
                    "crmDealIds": {"items": {"type": "integer"}, "type": "array"},
                    "customFields": {
                        "description": "CustomFields is the custom " "fields type.",
                        "properties": {
                            "Values": {
                                "items": {
                                    "description": "CustomFieldValue "
                                    "contains "
                                    "all "
                                    "the "
                                    "information "
                                    "returned "
                                    "from "
                                    "a "
                                    "customfield.",
                                    "properties": {
                                        "countryCode": {"type": "string"},
                                        "currencySymbol": {"type": "string"},
                                        "customfieldId": {"type": "integer"},
                                        "urlTextToDisplay": {"type": "string"},
                                        "value": {
                                            "description": "The "
                                            "shape "
                                            "depends "
                                            "on "
                                            "the "
                                            "type "
                                            "of "
                                            "the "
                                            "related "
                                            "custom "
                                            "field; "
                                            "null "
                                            "clears "
                                            "it. "
                                            "One "
                                            "of: "
                                            "string, "
                                            "number, "
                                            "boolean, "
                                            "string[].",
                                            "type": "any",
                                        },
                                    },
                                    "required": [
                                        "customfieldId",
                                        "value",
                                        "countryCode",
                                        "currencySymbol",
                                        "urlTextToDisplay",
                                    ],
                                    "title": "CustomFieldValue",
                                    "type": "object",
                                },
                                "type": "array",
                            }
                        },
                        "required": ["Values"],
                        "title": "CustomFields",
                        "type": "object",
                    },
                    "description": {"type": "string"},
                    "descriptionContentType": {"type": "string"},
                    "dueAt": {"format": "date", "type": "string"},
                    "dueDate": {
                        "description": "DueDate is an alias for DueAt, "
                        "matching the field name the "
                        "task views\n"
                        "return",
                        "type": "string",
                    },
                    "estimatedMinutes": {"type": "integer"},
                    "grantAccessTo": {
                        "description": "UserGroups are common "
                        "lists for storing users, "
                        "companies, teams and "
                        "jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "hasDeskTickets": {"type": "boolean"},
                    "name": {"type": "string"},
                    "notify": {"type": "boolean"},
                    "originalDueDate": {"format": "date", "type": "string"},
                    "parentTaskId": {"type": "integer"},
                    "priority": {
                        "description": "NullableTaskPriority "
                        "implements json.Unmarshaler to "
                        "allow testing\n"
                        "between a value that "
                        "explicitly set to null or "
                        "omitted.",
                        "properties": {
                            "Null": {"type": "boolean"},
                            "Set": {"type": "boolean"},
                            "Value": {"type": "string"},
                        },
                        "required": ["Value", "Null", "Set"],
                        "title": "NullableTaskPriority",
                        "type": "object",
                    },
                    "private": {"type": "boolean"},
                    "progress": {"type": "integer"},
                    "projectId": {"type": "integer"},
                    "reminders": {
                        "items": {
                            "description": "Reminder stores all "
                            "necessary "
                            "information to "
                            "create a task "
                            "reminder.",
                            "properties": {
                                "isRelative": {"type": "boolean"},
                                "note": {"type": "string"},
                                "relativeNumberDays": {"type": "integer"},
                                "remindAt": {"type": "string"},
                                "type": {"type": "string"},
                                "userId": {"type": "integer"},
                            },
                            "required": [
                                "userId",
                                "remindAt",
                                "type",
                                "note",
                                "isRelative",
                                "relativeNumberDays",
                            ],
                            "title": "Reminder",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "repeatOptions": {
                        "description": "RepeatOptions stores "
                        "recurring information for "
                        "the task.",
                        "properties": {
                            "duration": {"type": "integer"},
                            "editOption": {"type": "string"},
                            "endsAt": {"format": "date", "type": "string"},
                            "frequency": {
                                "description": "NullableTaskRepeatFrequency "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableTaskRepeatFrequency",
                                "type": "object",
                            },
                            "monthlyRepeatType": {
                                "description": "NullableTaskRepeatMonthlyType "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableTaskRepeatMonthlyType",
                                "type": "object",
                            },
                            "rrule": {
                                "description": "Adds "
                                "the "
                                "RRule "
                                "definition "
                                "for "
                                "repeating "
                                "tasks. "
                                "It "
                                "replaces "
                                "all "
                                "other "
                                "repeating "
                                "fields.",
                                "title": "RRule",
                                "type": "string",
                            },
                            "selectedDays": {
                                "description": "NullableWorkingHourEntryWeekdays "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing\n"
                                "between "
                                "a "
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "string"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableWorkingHourEntryWeekdays",
                                "type": "object",
                            },
                        },
                        "required": [
                            "selectedDays",
                            "endsAt",
                            "frequency",
                            "monthlyRepeatType",
                            "duration",
                            "rrule",
                        ],
                        "title": "RepeatOptions",
                        "type": "object",
                    },
                    "startAt": {"format": "date", "type": "string"},
                    "startDate": {
                        "description": "StartDate is an alias for "
                        "StartAt, matching the field "
                        "name the task views\n"
                        "return",
                        "type": "string",
                    },
                    "status": {"type": "string"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "taskgroupId": {"type": "integer"},
                    "tasklistId": {"type": "integer"},
                    "templateRoleName": {"type": "string"},
                    "ticketId": {"type": "integer"},
                },
                "required": [
                    "startAt",
                    "startDate",
                    "dueAt",
                    "dueDate",
                    "originalDueDate",
                    "priority",
                    "customFields",
                ],
                "title": "Task",
                "type": "object",
            },
            "taskOptions": {
                "description": "Options contains any options which can be set\n"
                "for the task request",
                "properties": {
                    "appendAssignees": {"type": "boolean"},
                    "checkInvalidusers": {"type": "boolean"},
                    "everyoneMustDo": {"type": "boolean"},
                    "fireWebhook": {"type": "boolean"},
                    "isTemplate": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "notify": {"type": "boolean"},
                    "parseInlineTags": {"type": "boolean"},
                    "positionAfterTaskId": {"type": "integer"},
                    "pushDependents": {"type": "boolean"},
                    "pushSubtasks": {"type": "boolean"},
                    "shiftProjectDates": {"type": "boolean"},
                    "useDefaults": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "required": [
                    "notify",
                    "everyoneMustDo",
                    "isTemplate",
                    "parseInlineTags",
                    "appendAssignees",
                    "checkInvalidusers",
                    "pushSubtasks",
                    "pushDependents",
                ],
                "title": "Options",
                "type": "object",
            },
            "workflows": {
                "description": "Workflows stores information about where the task "
                "lives in the workflow",
                "properties": {
                    "positionAfterTask": {"type": "integer"},
                    "stageId": {"type": "integer"},
                    "workflowId": {"type": "integer"},
                },
                "title": "Workflows",
                "type": "object",
            },
        },
        "required": [
            "task",
            "taskOptions",
            "tags",
            "attachments",
            "attachmentOptions",
            "predecessors",
            "workflows",
        ],
        "title": "Request",
        "type": "object",
    },
    "create_task_comment": {
        "description": "Request contains information of a comment to be created or updated.",
        "properties": {
            "attachments": {
                "properties": {
                    "files": {
                        "items": {
                            "description": "File stores "
                            "information "
                            "about a "
                            "uploaded "
                            "file.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "id": {"type": "integer"},
                            },
                            "required": ["id"],
                            "title": "File",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "pendingFiles": {
                        "items": {
                            "description": "PendingFile "
                            "stores "
                            "information "
                            "about "
                            "a "
                            "file "
                            "uploaded "
                            "on-the-fly.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "reference": {"type": "string"},
                            },
                            "required": ["reference"],
                            "title": "PendingFile",
                            "type": "object",
                        },
                        "type": "array",
                    },
                },
                "type": "object",
            },
            "comment": {
                "description": "Comment contains all the information from a "
                "comment.",
                "properties": {
                    "body": {"type": "string"},
                    "contentType": {"type": "string"},
                    "createdAt": {"description": "only for admins", "type": "string"},
                    "createdBy": {"type": "integer"},
                    "fileIds": {
                        "description": "NullableInt64Slice "
                        "implements "
                        "json.Unmarshaler to "
                        "allow testing between "
                        "a\n"
                        "value that explicitly "
                        "set to null or omitted.",
                        "properties": {
                            "Null": {"type": "boolean"},
                            "Set": {"type": "boolean"},
                            "Value": {"items": {"type": "integer"}, "type": "array"},
                        },
                        "required": ["Value", "Null", "Set"],
                        "title": "NullableInt64Slice",
                        "type": "object",
                    },
                    "grantAccessTo": {
                        "description": "UserGroups are "
                        "common lists for "
                        "storing users, "
                        "companies, teams "
                        "and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "private": {"type": "boolean"},
                },
                "required": ["fileIds"],
                "title": "Comment",
                "type": "object",
            },
            "commentOptions": {
                "properties": {
                    "fireWebhook": {"type": "boolean"},
                    "markdownToHTML": {"type": "boolean"},
                    "notify": {
                        "description": "Notify defines " "the access lists.",
                        "properties": {
                            "ids": {
                                "description": "UserGroups "
                                "are "
                                "common "
                                "lists "
                                "for "
                                "storing "
                                "users, "
                                "companies, "
                                "teams "
                                "and "
                                "jobRole "
                                "ids\n"
                                "together.",
                                "properties": {
                                    "companyIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                    "jobRoleIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                    "teamIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                    "userIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                },
                                "required": [
                                    "userIds",
                                    "companyIds",
                                    "teamIds",
                                    "jobRoleIds",
                                ],
                                "title": "UserGroups",
                                "type": "object",
                            },
                            "type": {
                                "description": "NotifyType "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a "
                                "value\n"
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NotifyType",
                                "type": "object",
                            },
                        },
                        "required": ["type", "ids"],
                        "title": "Notify",
                        "type": "object",
                    },
                    "notifyCurrentUser": {"type": "boolean"},
                    "parseMentions": {"type": "boolean"},
                },
                "type": "object",
            },
        },
        "required": ["comment", "commentOptions", "attachments"],
        "title": "Request",
        "type": "object",
    },
    "create_company": {
        "description": "Request contains information of a company to be created or updated.",
        "properties": {
            "company": {
                "description": "Company contains all the information returned from a "
                "company.",
                "properties": {
                    "addressOne": {"type": "string"},
                    "addressTwo": {"type": "string"},
                    "cid": {"type": "string"},
                    "city": {"type": "string"},
                    "clientManagedBy": {"type": "integer"},
                    "countrycode": {"type": "string"},
                    "currencyId": {"type": "integer"},
                    "customFields": {
                        "description": "CustomFields is the " "custom fields type.",
                        "properties": {
                            "Values": {
                                "items": {
                                    "description": "CustomFieldValue "
                                    "contains "
                                    "all "
                                    "the "
                                    "information "
                                    "returned "
                                    "from "
                                    "a "
                                    "customfield.",
                                    "properties": {
                                        "countryCode": {"type": "string"},
                                        "currencySymbol": {"type": "string"},
                                        "customfieldId": {"type": "integer"},
                                        "urlTextToDisplay": {"type": "string"},
                                        "value": {
                                            "description": "The "
                                            "shape "
                                            "depends "
                                            "on "
                                            "the "
                                            "type "
                                            "of "
                                            "the "
                                            "related "
                                            "custom "
                                            "field; "
                                            "null "
                                            "clears "
                                            "it. "
                                            "One "
                                            "of: "
                                            "string, "
                                            "number, "
                                            "boolean, "
                                            "string[].",
                                            "type": "any",
                                        },
                                    },
                                    "required": [
                                        "customfieldId",
                                        "value",
                                        "countryCode",
                                        "currencySymbol",
                                        "urlTextToDisplay",
                                    ],
                                    "title": "CustomFieldValue",
                                    "type": "object",
                                },
                                "type": "array",
                            }
                        },
                        "required": ["Values"],
                        "title": "CustomFields",
                        "type": "object",
                    },
                    "emailOne": {"type": "string"},
                    "emailThree": {"type": "string"},
                    "emailTwo": {"type": "string"},
                    "fax": {"type": "string"},
                    "industryCatId": {"type": "integer"},
                    "logoPendingFileRef": {"type": "string"},
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "privateNotes": {"type": "string"},
                    "profile": {"type": "string"},
                    "removeLogo": {"type": "boolean"},
                    "state": {"type": "string"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "website": {"type": "string"},
                    "zip": {"type": "string"},
                },
                "required": ["clientManagedBy", "customFields"],
                "title": "Company",
                "type": "object",
            },
            "companyOptions": {
                "properties": {
                    "fireWebhook": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "type": "object",
            },
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from a "
                    "tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
        },
        "required": ["company", "companyOptions", "tags"],
        "title": "Request",
        "type": "object",
    },
    "update_company": {
        "description": "Request contains information of a company to be created or updated.",
        "properties": {
            "company": {
                "description": "Company contains all the information returned from a "
                "company.",
                "properties": {
                    "addressOne": {"type": "string"},
                    "addressTwo": {"type": "string"},
                    "cid": {"type": "string"},
                    "city": {"type": "string"},
                    "clientManagedBy": {"type": "integer"},
                    "countrycode": {"type": "string"},
                    "currencyId": {"type": "integer"},
                    "customFields": {
                        "description": "CustomFields is the " "custom fields type.",
                        "properties": {
                            "Values": {
                                "items": {
                                    "description": "CustomFieldValue "
                                    "contains "
                                    "all "
                                    "the "
                                    "information "
                                    "returned "
                                    "from "
                                    "a "
                                    "customfield.",
                                    "properties": {
                                        "countryCode": {"type": "string"},
                                        "currencySymbol": {"type": "string"},
                                        "customfieldId": {"type": "integer"},
                                        "urlTextToDisplay": {"type": "string"},
                                        "value": {
                                            "description": "The "
                                            "shape "
                                            "depends "
                                            "on "
                                            "the "
                                            "type "
                                            "of "
                                            "the "
                                            "related "
                                            "custom "
                                            "field; "
                                            "null "
                                            "clears "
                                            "it. "
                                            "One "
                                            "of: "
                                            "string, "
                                            "number, "
                                            "boolean, "
                                            "string[].",
                                            "type": "any",
                                        },
                                    },
                                    "required": [
                                        "customfieldId",
                                        "value",
                                        "countryCode",
                                        "currencySymbol",
                                        "urlTextToDisplay",
                                    ],
                                    "title": "CustomFieldValue",
                                    "type": "object",
                                },
                                "type": "array",
                            }
                        },
                        "required": ["Values"],
                        "title": "CustomFields",
                        "type": "object",
                    },
                    "emailOne": {"type": "string"},
                    "emailThree": {"type": "string"},
                    "emailTwo": {"type": "string"},
                    "fax": {"type": "string"},
                    "industryCatId": {"type": "integer"},
                    "logoPendingFileRef": {"type": "string"},
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "privateNotes": {"type": "string"},
                    "profile": {"type": "string"},
                    "removeLogo": {"type": "boolean"},
                    "state": {"type": "string"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "website": {"type": "string"},
                    "zip": {"type": "string"},
                },
                "required": ["clientManagedBy", "customFields"],
                "title": "Company",
                "type": "object",
            },
            "companyOptions": {
                "properties": {
                    "fireWebhook": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "type": "object",
            },
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from a "
                    "tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
        },
        "required": ["company", "companyOptions", "tags"],
        "title": "Request",
        "type": "object",
    },
    "create_tag": {
        "description": "Request contains information of a tag to be created or updated.",
        "properties": {
            "tag": {
                "description": "Tag contains all the information returned from a tag.",
                "properties": {
                    "color": {"type": "string"},
                    "name": {"type": "string"},
                    "projectId": {"type": "integer"},
                },
                "title": "Tag",
                "type": "object",
            }
        },
        "required": ["tag"],
        "title": "Request",
        "type": "object",
    },
    "update_tag": {
        "description": "Request contains information of a tag to be created or updated.",
        "properties": {
            "tag": {
                "description": "Tag contains all the information returned from a tag.",
                "properties": {
                    "color": {"type": "string"},
                    "name": {"type": "string"},
                    "projectId": {"type": "integer"},
                },
                "title": "Tag",
                "type": "object",
            }
        },
        "required": ["tag"],
        "title": "Request",
        "type": "object",
    },
    "log_project_time": {
        "description": "Request contains information of a timelog to be created or updated.",
        "properties": {
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from "
                    "a tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
            "timelog": {
                "description": "Timelog contains all the information returned from a "
                "timelog.",
                "properties": {
                    "date": {"format": "date", "type": "string"},
                    "description": {"type": "string"},
                    "hasStartTime": {"type": "boolean"},
                    "hours": {"type": "integer"},
                    "invoiceId": {"type": "integer"},
                    "isBillable": {"type": "boolean"},
                    "isUtc": {"type": "boolean"},
                    "minutes": {"type": "integer"},
                    "projectId": {"type": "integer"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "taskId": {"type": "integer"},
                    "ticketId": {"type": "integer"},
                    "time": {"format": "time", "type": "string"},
                    "userId": {"type": "integer"},
                    "verified": {"type": "boolean"},
                },
                "required": ["taskId", "isUtc"],
                "title": "Timelog",
                "type": "object",
            },
            "timelogOptions": {
                "description": "Options are the options of a timelog create or "
                "update, the request body's\n"
                '"timelogOptions". Named rather than inline so '
                "a bulk create can extend it\n"
                "instead of restating the same fields at batch "
                "level.",
                "properties": {
                    "fireWebhook": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "markTaskComplete": {"type": "boolean"},
                    "parseInlineTags": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "title": "Options",
                "type": "object",
            },
        },
        "required": ["timelog", "timelogOptions", "tags"],
        "title": "Request",
        "type": "object",
    },
    "log_task_time": {
        "description": "Request contains information of a timelog to be created or updated.",
        "properties": {
            "tags": {
                "items": {
                    "description": "Tag contains all the information returned from a "
                    "tag.",
                    "properties": {
                        "color": {"type": "string"},
                        "name": {"type": "string"},
                        "projectId": {"type": "integer"},
                    },
                    "title": "Tag",
                    "type": "object",
                },
                "type": "array",
            },
            "timelog": {
                "description": "Timelog contains all the information returned from a "
                "timelog.",
                "properties": {
                    "date": {"format": "date", "type": "string"},
                    "description": {"type": "string"},
                    "hasStartTime": {"type": "boolean"},
                    "hours": {"type": "integer"},
                    "invoiceId": {"type": "integer"},
                    "isBillable": {"type": "boolean"},
                    "isUtc": {"type": "boolean"},
                    "minutes": {"type": "integer"},
                    "projectId": {"type": "integer"},
                    "tagIds": {"items": {"type": "integer"}, "type": "array"},
                    "taskId": {"type": "integer"},
                    "ticketId": {"type": "integer"},
                    "time": {"format": "time", "type": "string"},
                    "userId": {"type": "integer"},
                    "verified": {"type": "boolean"},
                },
                "required": ["taskId", "isUtc"],
                "title": "Timelog",
                "type": "object",
            },
            "timelogOptions": {
                "description": "Options are the options of a timelog create or "
                "update, the request body's\n"
                '"timelogOptions". Named rather than inline so a '
                "bulk create can extend it\n"
                "instead of restating the same fields at batch "
                "level.",
                "properties": {
                    "fireWebhook": {"type": "boolean"},
                    "logActivity": {"type": "boolean"},
                    "markTaskComplete": {"type": "boolean"},
                    "parseInlineTags": {"type": "boolean"},
                    "useNotifyViaTWIM": {"type": "boolean"},
                },
                "title": "Options",
                "type": "object",
            },
        },
        "required": ["timelog", "timelogOptions", "tags"],
        "title": "Request",
        "type": "object",
    },
    "create_timer": {
        "description": "Request contains information of a timer to be created or updated.",
        "properties": {
            "timer": {
                "description": "Timer contains all the information returned from a timer.",
                "properties": {
                    "description": {"type": "string"},
                    "isBillable": {"type": "boolean"},
                    "isRunning": {"type": "boolean"},
                    "projectId": {"type": "integer"},
                    "seconds": {
                        "description": "On POST, backdates the timer's "
                        "DateCreated by the given "
                        "seconds.\n"
                        "On PUT/PATCH, replaces the "
                        "timer's intervals with a single "
                        "normalized\n"
                        "interval whose duration equals "
                        "the given seconds.",
                        "type": "integer",
                    },
                    "stopRunningTimers": {"type": "boolean"},
                    "taskId": {"type": "integer"},
                },
                "required": ["projectId", "taskId"],
                "title": "Timer",
                "type": "object",
            }
        },
        "required": ["timer"],
        "title": "Request",
        "type": "object",
    },
    "delete_timer": {
        "description": "DeleteRequest contains the whether or not a timer should be hard deleted\n"
        "or soft deleted. Hard delete will remove the timer row from the DB and\n"
        "remove its timer intervals. Soft delete will just mark it as deleted.",
        "properties": {"hardDelete": {"type": "boolean"}},
        "title": "DeleteRequest",
        "type": "object",
    },
    "create_comment": {
        "description": "Request contains information of a comment to be created or updated.",
        "properties": {
            "attachments": {
                "properties": {
                    "files": {
                        "items": {
                            "description": "File stores "
                            "information "
                            "about a uploaded "
                            "file.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "id": {"type": "integer"},
                            },
                            "required": ["id"],
                            "title": "File",
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "pendingFiles": {
                        "items": {
                            "description": "PendingFile "
                            "stores "
                            "information "
                            "about a "
                            "file "
                            "uploaded "
                            "on-the-fly.",
                            "properties": {
                                "categoryId": {"type": "integer"},
                                "reference": {"type": "string"},
                            },
                            "required": ["reference"],
                            "title": "PendingFile",
                            "type": "object",
                        },
                        "type": "array",
                    },
                },
                "type": "object",
            },
            "comment": {
                "description": "Comment contains all the information from a comment.",
                "properties": {
                    "body": {"type": "string"},
                    "contentType": {"type": "string"},
                    "createdAt": {"description": "only for admins", "type": "string"},
                    "createdBy": {"type": "integer"},
                    "fileIds": {
                        "description": "NullableInt64Slice "
                        "implements json.Unmarshaler "
                        "to allow testing between a\n"
                        "value that explicitly set to "
                        "null or omitted.",
                        "properties": {
                            "Null": {"type": "boolean"},
                            "Set": {"type": "boolean"},
                            "Value": {"items": {"type": "integer"}, "type": "array"},
                        },
                        "required": ["Value", "Null", "Set"],
                        "title": "NullableInt64Slice",
                        "type": "object",
                    },
                    "grantAccessTo": {
                        "description": "UserGroups are common "
                        "lists for storing "
                        "users, companies, "
                        "teams and jobRole ids\n"
                        "together.",
                        "properties": {
                            "companyIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "jobRoleIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "teamIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                            "userIds": {
                                "description": "NullableInt64Slice "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a\n"
                                "value "
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {
                                        "items": {"type": "integer"},
                                        "type": "array",
                                    },
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NullableInt64Slice",
                                "type": "object",
                            },
                        },
                        "required": ["userIds", "companyIds", "teamIds", "jobRoleIds"],
                        "title": "UserGroups",
                        "type": "object",
                    },
                    "private": {"type": "boolean"},
                },
                "required": ["fileIds"],
                "title": "Comment",
                "type": "object",
            },
            "commentOptions": {
                "properties": {
                    "fireWebhook": {"type": "boolean"},
                    "markdownToHTML": {"type": "boolean"},
                    "notify": {
                        "description": "Notify defines the " "access lists.",
                        "properties": {
                            "ids": {
                                "description": "UserGroups "
                                "are "
                                "common "
                                "lists "
                                "for "
                                "storing "
                                "users, "
                                "companies, "
                                "teams "
                                "and "
                                "jobRole "
                                "ids\n"
                                "together.",
                                "properties": {
                                    "companyIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                    "jobRoleIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                    "teamIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                    "userIds": {
                                        "description": "NullableInt64Slice "
                                        "implements "
                                        "json.Unmarshaler "
                                        "to "
                                        "allow "
                                        "testing "
                                        "between "
                                        "a\n"
                                        "value "
                                        "that "
                                        "explicitly "
                                        "set "
                                        "to "
                                        "null "
                                        "or "
                                        "omitted.",
                                        "properties": {
                                            "Null": {"type": "boolean"},
                                            "Set": {"type": "boolean"},
                                            "Value": {
                                                "items": {"type": "integer"},
                                                "type": "array",
                                            },
                                        },
                                        "required": ["Value", "Null", "Set"],
                                        "title": "NullableInt64Slice",
                                        "type": "object",
                                    },
                                },
                                "required": [
                                    "userIds",
                                    "companyIds",
                                    "teamIds",
                                    "jobRoleIds",
                                ],
                                "title": "UserGroups",
                                "type": "object",
                            },
                            "type": {
                                "description": "NotifyType "
                                "implements "
                                "json.Unmarshaler "
                                "to "
                                "allow "
                                "testing "
                                "between "
                                "a "
                                "value\n"
                                "that "
                                "explicitly "
                                "set "
                                "to "
                                "null "
                                "or "
                                "omitted.",
                                "properties": {
                                    "Null": {"type": "boolean"},
                                    "Set": {"type": "boolean"},
                                    "Value": {"type": "string"},
                                },
                                "required": ["Value", "Null", "Set"],
                                "title": "NotifyType",
                                "type": "object",
                            },
                        },
                        "required": ["type", "ids"],
                        "title": "Notify",
                        "type": "object",
                    },
                    "notifyCurrentUser": {"type": "boolean"},
                    "parseMentions": {"type": "boolean"},
                },
                "type": "object",
            },
        },
        "required": ["comment", "commentOptions", "attachments"],
        "title": "Request",
        "type": "object",
    },
}
