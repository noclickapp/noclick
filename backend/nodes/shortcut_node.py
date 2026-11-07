"""Shortcut project-management node for the stable REST v3 API.

All documented v3 routes are exposed as separate canvas actions. The operation
contracts below are pinned to Shortcut's OpenAPI spec;
requests can only reach a method and path from that allowlist.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
# Operation contracts from https://developer.shortcut.com/api/rest/v3/shortcut.openapi.json
# Pinned 2026-09-29; kept with the node for integration-local discovery.
OPERATIONS = {
    "create_category": {
        "body_fields": [
            {
                "description": "The name of the new Category.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The hex color to be displayed with the Category (for "
                'example, "#ff0000").',
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In the "
                "case that the Category has been imported from another "
                "tool, the ID in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The type of entity this Category is associated with; "
                "currently Milestone or Objective is the only type of "
                "Category.",
                "name": "type",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name"],
        "body_type": "json",
        "category": "Categories",
        "description": "Create Category allows you to create a new Category in Shortcut.",
        "method": "POST",
        "parameters": [],
        "path": "/categories",
        "title": "Create Category",
    },
    "create_doc": {
        "body_fields": [
            {
                "description": "The title for the new document.",
                "name": "title",
                "required": True,
                "type": "string",
            },
            {
                "description": "The content for the new document.",
                "name": "content",
                "required": True,
                "type": "string",
            },
            {
                "description": "Default content_format: html. Format of the content being "
                "sent. If 'markdown', content will be converted to HTML for "
                "storage. Storage is always HTML; this parameter just tells "
                "us what format you're sending.",
                "name": "content_format",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["title", "content"],
        "body_type": "json",
        "category": "Documents",
        "description": "Creates a new Doc. Supports markdown or HTML input via content_format "
        "parameter. WARNING: if content_format is not supplied, `content` input "
        "defaults to html.",
        "method": "POST",
        "parameters": [],
        "path": "/documents",
        "title": "Create Doc",
    },
    "create_entity_template": {
        "body_fields": [
            {
                "description": "The name of the new entity template",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The id of the user creating this template.",
                "name": "author_id",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name", "story_contents"],
        "body_type": "json",
        "category": "Entity Templates",
        "description": "Create a new entity template for the Workspace.",
        "method": "POST",
        "parameters": [],
        "path": "/entity-templates",
        "title": "Create Entity Template",
    },
    "create_epic": {
        "body_fields": [
            {
                "description": "The Epic's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Epic was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Epic's name.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The Epic's planned start date.",
                "name": "planned_start_date",
                "required": False,
                "type": "string",
            },
            {
                "description": "`Deprecated` The Epic's state (to do, in progress, or "
                "done); will be ignored when `epic_state_id` is set.",
                "name": "state",
                "required": False,
                "type": "string",
            },
            {
                "description": "`Deprecated` The ID of the Milestone this Epic is related "
                "to. Use `objective_ids`.",
                "name": "milestone_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the member that requested the epic.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Epic State.",
                "name": "epic_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the Epic was started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "`Deprecated` The ID of the group to associate with the "
                "epic. Use `group_ids`.",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date it is created but can be set to "
                "reflect another date.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Story that was converted to an Epic.",
                "name": "converted_from_story_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "This field can be set to another unique ID. In the case "
                "that the Epic has been imported from another tool, the ID "
                "in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Epic's deadline.",
                "name": "deadline",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date it is created but can be set to "
                "reflect another date.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name"],
        "body_type": "json",
        "category": "Epics",
        "description": "Create Epic allows you to create a new Epic in Shortcut.",
        "method": "POST",
        "parameters": [],
        "path": "/epics",
        "title": "Create Epic",
    },
    "create_epic_comment": {
        "body_fields": [
            {
                "description": "The comment text.",
                "name": "text",
                "required": True,
                "type": "string",
            },
            {
                "description": "The Member ID of the Comment's author. Defaults to "
                "the user identified by the API token.",
                "name": "author_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the comment is created, "
                "but can be set to reflect another date.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the comment is last "
                "updated, but can be set to reflect another date.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In the "
                "case that the comment has been imported from "
                "another tool, the ID in the other tool can be "
                "indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["text"],
        "body_type": "json",
        "category": "Epics",
        "description": "This endpoint allows you to create a threaded Comment on an Epic.",
        "method": "POST",
        "parameters": [
            {
                "description": "The ID of the associated Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}/comments",
        "title": "Create Epic Comment",
    },
    "create_epic_comment_comment": {
        "body_fields": [
            {
                "description": "The comment text.",
                "name": "text",
                "required": True,
                "type": "string",
            },
            {
                "description": "The Member ID of the Comment's author. "
                "Defaults to the user identified by the API "
                "token.",
                "name": "author_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the comment is "
                "created, but can be set to reflect another "
                "date.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the comment is "
                "last updated, but can be set to reflect "
                "another date.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique "
                "ID. In the case that the comment has been "
                "imported from another tool, the ID in the "
                "other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["text"],
        "body_type": "json",
        "category": "Epics",
        "description": "This endpoint allows you to create a nested Comment reply "
        "to an existing Epic Comment.",
        "method": "POST",
        "parameters": [
            {
                "description": "The ID of the associated Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the parent Epic Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/epics/{epic-public-id}/comments/{comment-public-id}",
        "title": "Create Epic Comment Comment",
    },
    "create_epic_health": {
        "body_fields": [
            {
                "description": "The health status of the Epic.",
                "name": "status",
                "required": True,
                "type": "string",
            },
            {
                "description": "The description of the Health status.",
                "name": "text",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["status"],
        "body_type": "json",
        "category": "Epics",
        "description": "Create a new health status for the specified Epic.",
        "method": "POST",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}/health",
        "title": "Create Epic Health",
    },
    "create_generic_integration": {
        "body_fields": [
            {
                "description": "",
                "name": "webhook_url",
                "required": True,
                "type": "string",
            },
            {"description": "", "name": "secret", "required": False, "type": "string"},
        ],
        "body_required": ["webhook_url"],
        "body_type": "json",
        "category": "Integrations",
        "description": "",
        "method": "POST",
        "parameters": [],
        "path": "/integrations/webhook",
        "title": "Create Generic Integration",
    },
    "create_group": {
        "body_fields": [
            {
                "description": "The description of the Group.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": 'The card aging mode for stories in this Group: "gradual" '
                '(fixed fade steps at 1, 2, and 4 weeks), "immediate", or '
                '"off" (explicitly disabled for this Group). Set to null '
                "to inherit the Workspace default.",
                "name": "card_aging_mode",
                "required": False,
                "type": "string",
            },
            {
                "description": "The color you wish to use for the Group in the system.",
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "The number of days an in-progress Story can go without "
                "activity before it is considered stale. Required when "
                'card_aging_mode is "immediate"; not allowed otherwise.',
                "name": "card_aging_threshold_days",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Icon id for the avatar of this Group.",
                "name": "display_icon_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The mention name of this Group.",
                "name": "mention_name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The name of this Group.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The color key you wish to use for the Group in the "
                "system.",
                "name": "color_key",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["mention_name", "name"],
        "body_type": "json",
        "category": "Groups",
        "description": "",
        "method": "POST",
        "parameters": [],
        "path": "/groups",
        "title": "Create Group",
    },
    "create_iteration": {
        "body_fields": [
            {
                "description": "The description of the Iteration.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of this Iteration.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The date this Iteration begins, e.g. 2019-07-01.",
                "name": "start_date",
                "required": True,
                "type": "string",
            },
            {
                "description": "The date this Iteration ends, e.g. 2019-07-01.",
                "name": "end_date",
                "required": True,
                "type": "string",
            },
        ],
        "body_required": ["name", "start_date", "end_date"],
        "body_type": "json",
        "category": "Iterations",
        "description": "",
        "method": "POST",
        "parameters": [],
        "path": "/iterations",
        "title": "Create Iteration",
    },
    "create_label": {
        "body_fields": [
            {
                "description": "The name of the new Label.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The description of the new Label.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The hex color to be displayed with the Label (for "
                'example, "#ff0000").',
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In the case "
                "that the Label has been imported from another tool, the "
                "ID in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name"],
        "body_type": "json",
        "category": "Labels",
        "description": "Create Label allows you to create a new Label in Shortcut.",
        "method": "POST",
        "parameters": [],
        "path": "/labels",
        "title": "Create Label",
    },
    "create_linked_file": {
        "body_fields": [
            {
                "description": "The description of the file.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the linked story.",
                "name": "story_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The name of the file.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The URL of the thumbnail, if the integration "
                "provided it.",
                "name": "thumbnail_url",
                "required": False,
                "type": "string",
            },
            {
                "description": "The integration type of the file (e.g. google, "
                "dropbox, box).",
                "name": "type",
                "required": True,
                "type": "string",
            },
            {
                "description": "The filesize, if the integration provided it.",
                "name": "size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The UUID of the member that uploaded the file.",
                "name": "uploader_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The content type of the image (e.g. txt/plain).",
                "name": "content_type",
                "required": False,
                "type": "string",
            },
            {
                "description": "The URL of linked file.",
                "name": "url",
                "required": True,
                "type": "string",
            },
        ],
        "body_required": ["name", "type", "url"],
        "body_type": "json",
        "category": "Linked Files",
        "description": "Create Linked File allows you to create a new Linked File in "
        "Shortcut.",
        "method": "POST",
        "parameters": [],
        "path": "/linked-files",
        "title": "Create Linked File",
    },
    "create_milestone": {
        "body_fields": [
            {
                "description": "The name of the Milestone.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The Milestone's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The workflow state that the Milestone is in.",
                "name": "state",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Milestone was "
                "started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Milestone was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name"],
        "body_type": "json",
        "category": "Milestones",
        "description": "(Deprecated: Use 'Create Objective') Create Milestone allows you to "
        "create a new Milestone in Shortcut.",
        "method": "POST",
        "parameters": [],
        "path": "/milestones",
        "title": "Create Milestone",
    },
    "create_multiple_stories": {
        "body_fields": [],
        "body_required": ["stories"],
        "body_type": "json",
        "category": "Stories",
        "description": "Create Multiple Stories allows you to create multiple stories "
        "in a single request using the same syntax as [Create "
        "Story](https://developer.shortcut.com/api/rest/v3#create-story).",
        "method": "POST",
        "parameters": [],
        "path": "/stories/bulk",
        "title": "Create Multiple Stories",
    },
    "create_objective": {
        "body_fields": [
            {
                "description": "The name of the Objective.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The Objective's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The workflow state that the Objective is in.",
                "name": "state",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Objective was "
                "started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Objective was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name"],
        "body_type": "json",
        "category": "Objectives",
        "description": "Create Objective allows you to create a new Objective in Shortcut.",
        "method": "POST",
        "parameters": [],
        "path": "/objectives",
        "title": "Create Objective",
    },
    "create_objective_health": {
        "body_fields": [
            {
                "description": "The health status of the Objective.",
                "name": "status",
                "required": True,
                "type": "string",
            },
            {
                "description": "The description of the Health status.",
                "name": "text",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["status"],
        "body_type": "json",
        "category": "Objectives",
        "description": "Create a new health status for the specified Objective.",
        "method": "POST",
        "parameters": [
            {
                "description": "The unique ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}/health",
        "title": "Create Objective Health",
    },
    "create_project": {
        "body_fields": [
            {
                "description": "The Project description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The color you wish to use for the Project in the "
                "system.",
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of the Project.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The date at which the Project was started.",
                "name": "start_time",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date it is created but can be set "
                "to reflect another date.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In the case "
                "that the Project has been imported from another tool, "
                "the ID in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the team the project belongs to.",
                "name": "team_id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The number of weeks per iteration in this Project.",
                "name": "iteration_length",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Project abbreviation used in Story summaries. "
                "Should be kept to 3 characters at most.",
                "name": "abbreviation",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date it is created but can be set "
                "to reflect another date.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name", "team_id"],
        "body_type": "json",
        "category": "Projects",
        "description": "Create Project is used to create a new Shortcut Project.",
        "method": "POST",
        "parameters": [],
        "path": "/projects",
        "title": "Create Project",
    },
    "create_story": {
        "body_fields": [
            {
                "description": "The description of the story.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "Controls the story's archived state.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The type of story (feature, bug, chore).",
                "name": "story_type",
                "required": False,
                "type": "string",
            },
            {
                "description": 'One of "first" or "last". This can be used to move the '
                "given story to the first or last position in the workflow "
                "state.",
                "name": "move_to",
                "required": False,
                "type": "string",
            },
            {
                "description": "Given this story was converted from a task in another "
                "story, this is the original task ID that was converted to "
                "this story.",
                "name": "source_task_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the Story was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of the story.",
                "name": "name",
                "required": True,
                "type": "string",
            },
            {
                "description": "The ID of the epic the story belongs to.",
                "name": "epic_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The id of the story template used to create this story, "
                "if applicable. This is just an association; no content "
                "from the story template is inherited by the story simply "
                "by setting this field.",
                "name": "story_template_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the member that requested the story.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the iteration the story belongs to.",
                "name": "iteration_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the Story was "
                "started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The id of the group to associate with this story.",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the workflow state the story will be in.",
                "name": "workflow_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The time/date the Story was updated.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In the case "
                "that the Story has been imported from another tool, the "
                "ID in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the parent story to associate with this story "
                "(making the created story a sub-task).\n"
                "Field only applicable when Sub-task feature is enabled.",
                "name": "parent_story_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The numeric point estimate of the story. Can also be "
                "null, which means unestimated.",
                "name": "estimate",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the project the story belongs to.",
                "name": "project_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The due date of the story.",
                "name": "deadline",
                "required": False,
                "type": "string",
            },
            {
                "description": "The time/date the Story was created.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["name"],
        "body_type": "json",
        "category": "Stories",
        "description": "Create Story is used to add a new story to your Shortcut Workspace.\n"
        "    This endpoint requires that either **workflow_state_id** or "
        "**project_id** be provided, but will reject the request if both or neither "
        "are specified. The workflow_state_id has been marked as required and is "
        "the recommended field",
        "method": "POST",
        "parameters": [],
        "path": "/stories",
        "title": "Create Story",
    },
    "create_story_comment": {
        "body_fields": [
            {
                "description": "The comment text.",
                "name": "text",
                "required": True,
                "type": "string",
            },
            {
                "description": "The Member ID of the Comment's author. Defaults "
                "to the user identified by the API token.",
                "name": "author_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the comment is created, "
                "but can be set to reflect another date.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the comment is last "
                "updated, but can be set to reflect another date.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In "
                "the case that the comment has been imported from "
                "another tool, the ID in the other tool can be "
                "indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Comment that this comment is "
                "threaded under.",
                "name": "parent_id",
                "required": False,
                "type": "integer",
            },
        ],
        "body_required": ["text"],
        "body_type": "json",
        "category": "Stories",
        "description": "Create Comment allows you to create a Comment on any Story.",
        "method": "POST",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}/comments",
        "title": "Create Story Comment",
    },
    "create_story_from_template": {
        "body_fields": [
            {
                "description": "The description of the story.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "Controls the story's archived state.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The type of story (feature, bug, chore).",
                "name": "story_type",
                "required": False,
                "type": "string",
            },
            {
                "description": 'One of "first" or "last". This can be used '
                "to move the given story to the first or "
                "last position in the workflow state.",
                "name": "move_to",
                "required": False,
                "type": "string",
            },
            {
                "description": "Given this story was converted from a task "
                "in another story, this is the original task "
                "ID that was converted to this story.",
                "name": "source_task_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the "
                "Story was completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of the story. Must be provided if "
                "the template does not provide a name.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the epic the story belongs to.",
                "name": "epic_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The id of the story template used to create "
                "this story.",
                "name": "story_template_id",
                "required": True,
                "type": "string",
            },
            {
                "description": "The ID of the member that requested the " "story.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the iteration the story belongs " "to.",
                "name": "iteration_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the "
                "Story was started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The id of the group to associate with this " "story.",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the workflow state the story will " "be in.",
                "name": "workflow_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The time/date the Story was updated.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. "
                "In the case that the Story has been "
                "imported from another tool, the ID in the "
                "other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the parent story to associate "
                "with this story (making the created story a "
                "sub-task).\n"
                "Field only applicable when Sub-task feature "
                "is enabled.",
                "name": "parent_story_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The numeric point estimate of the story. "
                "Can also be null, which means unestimated.",
                "name": "estimate",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the project the story belongs to.",
                "name": "project_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The due date of the story.",
                "name": "deadline",
                "required": False,
                "type": "string",
            },
            {
                "description": "The time/date the Story was created.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["story_template_id"],
        "body_type": "json",
        "category": "Stories",
        "description": "Create Story From Template is used to add a new story "
        "derived from a template to your Shortcut Workspace.",
        "method": "POST",
        "parameters": [],
        "path": "/stories/from-template",
        "title": "Create Story From Template",
    },
    "create_story_link": {
        "body_fields": [
            {
                "description": "The type of link.",
                "name": "verb",
                "required": True,
                "type": "string",
            },
            {
                "description": "The ID of the subject Story.",
                "name": "subject_id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the object Story.",
                "name": "object_id",
                "required": True,
                "type": "integer",
            },
        ],
        "body_required": ["verb", "subject_id", "object_id"],
        "body_type": "json",
        "category": "Story Links",
        "description": "Story Links (called Story Relationships in the UI) allow you create "
        "semantic relationships between two stories. The parameters read like "
        "an active voice grammatical sentence:  subject -> verb -> object.\n"
        "\n"
        "The subject story acts on the object Story; the object story is the "
        "direct object of the sentenc",
        "method": "POST",
        "parameters": [],
        "path": "/story-links",
        "title": "Create Story Link",
    },
    "create_story_reaction": {
        "body_fields": [
            {
                "description": "The emoji short-code to add / remove. E.g. `:thumbsup::skin-tone-4:`.",
                "name": "emoji",
                "required": True,
                "type": "string",
            }
        ],
        "body_required": ["emoji"],
        "body_type": "json",
        "category": "Stories",
        "description": "Create a reaction to a story comment.",
        "method": "POST",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/comments/{comment-public-id}/reactions",
        "title": "Create Story Reaction",
    },
    "create_task": {
        "body_fields": [
            {
                "description": "The Task description.",
                "name": "description",
                "required": True,
                "type": "string",
            },
            {
                "description": "True/false boolean indicating whether the Task is "
                "completed. Defaults to false.",
                "name": "complete",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "This field can be set to another unique ID. In the case "
                "that the Task has been imported from another tool, the ID "
                "in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the Task is created but can be "
                "set to reflect another creation time/date.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "Defaults to the time/date the Task is created in Shortcut "
                "but can be set to reflect another time/date.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["description"],
        "body_type": "json",
        "category": "Stories",
        "description": "Create Task is used to create a new task in a Story.",
        "method": "POST",
        "parameters": [
            {
                "description": "The ID of the Story that the Task will be in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}/tasks",
        "title": "Create Task",
    },
    "delete_category": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Categories",
        "description": "Delete Category can be used to delete any Category.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Category.",
                "location": "path",
                "name": "category-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/categories/{category-public-id}",
        "title": "Delete Category",
    },
    "delete_custom_field": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Custom Fields",
        "description": "",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the CustomField.",
                "location": "path",
                "name": "custom-field-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/custom-fields/{custom-field-public-id}",
        "title": "Delete Custom Field",
    },
    "delete_doc": {
        "body_fields": [
            {
                "description": "Default content_format: markdown. Format of the content to "
                "return. If 'html', includes HTML content in response.",
                "name": "content_format",
                "required": False,
                "type": "string",
            }
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Documents",
        "description": "Permanently deletes a Doc and its associated data. Requires admin access to "
        "the doc. When a document is deleted, connected clients will be notified via "
        "SSE events.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The Doc's public ID",
                "location": "path",
                "name": "doc-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/documents/{doc-public-id}",
        "title": "Delete Doc",
    },
    "delete_entity_template": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Entity Templates",
        "description": "",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the entity template.",
                "location": "path",
                "name": "entity-template-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/entity-templates/{entity-template-public-id}",
        "title": "Delete Entity Template",
    },
    "delete_epic": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "Delete Epic can be used to delete the Epic. The only required parameter is "
        "Epic ID.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}",
        "title": "Delete Epic",
    },
    "delete_epic_comment": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "This endpoint allows you to delete a Comment from an Epic.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The ID of the associated Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/epics/{epic-public-id}/comments/{comment-public-id}",
        "title": "Delete Epic Comment",
    },
    "delete_file": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Files",
        "description": "Delete File deletes a previously uploaded file.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The File’s unique ID.",
                "location": "path",
                "name": "file-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/files/{file-public-id}",
        "title": "Delete File",
    },
    "delete_generic_integration": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Integrations",
        "description": "",
        "method": "DELETE",
        "parameters": [
            {
                "description": "",
                "location": "path",
                "name": "integration-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/integrations/webhook/{integration-public-id}",
        "title": "Delete Generic Integration",
    },
    "delete_iteration": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Iterations",
        "description": "",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Iteration.",
                "location": "path",
                "name": "iteration-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/iterations/{iteration-public-id}",
        "title": "Delete Iteration",
    },
    "delete_label": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Labels",
        "description": "Delete Label can be used to delete any Label.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Label.",
                "location": "path",
                "name": "label-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/labels/{label-public-id}",
        "title": "Delete Label",
    },
    "delete_linked_file": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Linked Files",
        "description": "Delete Linked File can be used to delete any previously attached "
        "Linked-File.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique identifier of the linked file.",
                "location": "path",
                "name": "linked-file-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/linked-files/{linked-file-public-id}",
        "title": "Delete Linked File",
    },
    "delete_milestone": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Milestones",
        "description": "(Deprecated: Use 'Delete Objective') Delete Milestone can be used to "
        "delete any Milestone.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The ID of the Milestone.",
                "location": "path",
                "name": "milestone-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/milestones/{milestone-public-id}",
        "title": "Delete Milestone",
    },
    "delete_multiple_stories": {
        "body_fields": [],
        "body_required": ["story_ids"],
        "body_type": "json",
        "category": "Stories",
        "description": "Delete Multiple Stories allows you to delete multiple archived "
        "stories at once.",
        "method": "DELETE",
        "parameters": [],
        "path": "/stories/bulk",
        "title": "Delete Multiple Stories",
    },
    "delete_objective": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Objectives",
        "description": "Delete Objective can be used to delete any Objective.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}",
        "title": "Delete Objective",
    },
    "delete_project": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Projects",
        "description": "Delete Project can be used to delete a Project. Projects can only be "
        "deleted if all associated Stories are moved or deleted. In the case that "
        "the Project cannot be deleted, you will receive a 422 response.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Project.",
                "location": "path",
                "name": "project-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/projects/{project-public-id}",
        "title": "Delete Project",
    },
    "delete_story": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Delete Story can be used to delete any Story.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The ID of the Story.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}",
        "title": "Delete Story",
    },
    "delete_story_comment": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Delete a Comment from any story.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/comments/{comment-public-id}",
        "title": "Delete Story Comment",
    },
    "delete_story_link": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Story Links",
        "description": "Removes the relationship between the stories for the given Story "
        "Link.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Story Link.",
                "location": "path",
                "name": "story-link-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/story-links/{story-link-public-id}",
        "title": "Delete Story Link",
    },
    "delete_story_reaction": {
        "body_fields": [
            {
                "description": "The emoji short-code to add / remove. E.g. `:thumbsup::skin-tone-4:`.",
                "name": "emoji",
                "required": True,
                "type": "string",
            }
        ],
        "body_required": ["emoji"],
        "body_type": "json",
        "category": "Stories",
        "description": "Delete a reaction from any story comment.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/comments/{comment-public-id}/reactions",
        "title": "Delete Story Reaction",
    },
    "delete_task": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Delete Task can be used to delete any previously created Task on a Story.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The unique ID of the Story this Task is associated with.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The unique ID of the Task.",
                "location": "path",
                "name": "task-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/tasks/{task-public-id}",
        "title": "Delete Task",
    },
    "disable_iterations": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Iterations",
        "description": "Disables Iterations for the current workspace",
        "method": "PUT",
        "parameters": [],
        "path": "/iterations/disable",
        "title": "Disable Iterations",
    },
    "disable_story_templates": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Entity Templates",
        "description": "Disables the Story Template feature for the Workspace.",
        "method": "PUT",
        "parameters": [],
        "path": "/entity-templates/disable",
        "title": "Disable Story Templates",
    },
    "enable_iterations": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Iterations",
        "description": "Enables Iterations for the current workspace",
        "method": "PUT",
        "parameters": [],
        "path": "/iterations/enable",
        "title": "Enable Iterations",
    },
    "enable_story_templates": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Entity Templates",
        "description": "Enables the Story Template feature for the Workspace.",
        "method": "PUT",
        "parameters": [],
        "path": "/entity-templates/enable",
        "title": "Enable Story Templates",
    },
    "get_category": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Categories",
        "description": "Get Category returns information about the selected Category.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Category.",
                "location": "path",
                "name": "category-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/categories/{category-public-id}",
        "title": "Get Category",
    },
    "get_current_member_info": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Member",
        "description": "Returns information about the authenticated member.",
        "method": "GET",
        "parameters": [],
        "path": "/member",
        "title": "Get Current Member Info",
    },
    "get_custom_field": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Custom Fields",
        "description": "",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the CustomField.",
                "location": "path",
                "name": "custom-field-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/custom-fields/{custom-field-public-id}",
        "title": "Get Custom Field",
    },
    "get_doc": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Documents",
        "description": "Get a Doc by its public ID with content. Use content_format=html query "
        "parameter to include HTML content.",
        "method": "GET",
        "parameters": [
            {
                "description": "The Doc's public ID",
                "location": "path",
                "name": "doc-public-id",
                "required": True,
                "type": "string",
            },
            {
                "description": "Default content_format: markdown. Format of the content to "
                "return. If 'html', includes HTML content in response.",
                "location": "query",
                "name": "content_format",
                "required": False,
                "type": "string",
            },
        ],
        "path": "/documents/{doc-public-id}",
        "title": "Get Doc",
    },
    "get_entity_template": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Entity Templates",
        "description": "Get Entity Template returns information about a given entity "
        "template.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the entity template.",
                "location": "path",
                "name": "entity-template-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/entity-templates/{entity-template-public-id}",
        "title": "Get Entity Template",
    },
    "get_epic": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "Get Epic returns information about the selected Epic.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}",
        "title": "Get Epic",
    },
    "get_epic_comment": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "This endpoint returns information about the selected Epic Comment.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the associated Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/epics/{epic-public-id}/comments/{comment-public-id}",
        "title": "Get Epic Comment",
    },
    "get_epic_health": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "Get the current health for the specified Epic.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}/health",
        "title": "Get Epic Health",
    },
    "get_epic_workflow": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epic Workflow",
        "description": "Returns the Epic Workflow for the Workspace.",
        "method": "GET",
        "parameters": [],
        "path": "/epic-workflow",
        "title": "Get Epic Workflow",
    },
    "get_external_link_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "External Link",
        "description": "Get Stories which have a given External Link associated with "
        "them.",
        "method": "GET",
        "parameters": [
            {
                "description": "The external link associated with one or more "
                "stories.",
                "location": "query",
                "name": "external_link",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/external-link/stories",
        "title": "Get External Link Stories",
    },
    "get_file": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Files",
        "description": "Get File returns information about the selected UploadedFile.",
        "method": "GET",
        "parameters": [
            {
                "description": "The File’s unique ID.",
                "location": "path",
                "name": "file-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/files/{file-public-id}",
        "title": "Get File",
    },
    "get_generic_integration": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Integrations",
        "description": "",
        "method": "GET",
        "parameters": [
            {
                "description": "",
                "location": "path",
                "name": "integration-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/integrations/webhook/{integration-public-id}",
        "title": "Get Generic Integration",
    },
    "get_group": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Groups",
        "description": "",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Group.",
                "location": "path",
                "name": "group-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/groups/{group-public-id}",
        "title": "Get Group",
    },
    "get_iteration": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Iterations",
        "description": "",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Iteration.",
                "location": "path",
                "name": "iteration-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/iterations/{iteration-public-id}",
        "title": "Get Iteration",
    },
    "get_key_result": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Key Results",
        "description": "Get Key Result returns information about a chosen Key Result.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Key Result.",
                "location": "path",
                "name": "key-result-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/key-results/{key-result-public-id}",
        "title": "Get Key Result",
    },
    "get_label": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Labels",
        "description": "Get Label returns information about the selected Label.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Label.",
                "location": "path",
                "name": "label-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/labels/{label-public-id}",
        "title": "Get Label",
    },
    "get_linked_file": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Linked Files",
        "description": "Get File returns information about the selected Linked File.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique identifier of the linked file.",
                "location": "path",
                "name": "linked-file-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/linked-files/{linked-file-public-id}",
        "title": "Get Linked File",
    },
    "get_member": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Members",
        "description": "Returns information about a Member.",
        "method": "GET",
        "parameters": [
            {
                "description": "The Member's unique ID.",
                "location": "path",
                "name": "member-public-id",
                "required": True,
                "type": "string",
            },
            {
                "description": "The unique ID of the Organization to limit the lookup to.",
                "location": "query",
                "name": "org-public-id",
                "required": False,
                "type": "string",
            },
        ],
        "path": "/members/{member-public-id}",
        "title": "Get Member",
    },
    "get_milestone": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Milestones",
        "description": "(Deprecated: Use 'Get Objective') Get Milestone returns information about "
        "a chosen Milestone.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Milestone.",
                "location": "path",
                "name": "milestone-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/milestones/{milestone-public-id}",
        "title": "Get Milestone",
    },
    "get_objective": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Objectives",
        "description": "Get Objective returns information about a chosen Objective.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}",
        "title": "Get Objective",
    },
    "get_objective_health": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Objectives",
        "description": "Get the current health for the specified Objective.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}/health",
        "title": "Get Objective Health",
    },
    "get_project": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Projects",
        "description": "Get Project returns information about the selected Project.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Project.",
                "location": "path",
                "name": "project-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/projects/{project-public-id}",
        "title": "Get Project",
    },
    "get_repository": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Repositories",
        "description": "Get Repository returns information about the selected Repository.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Repository.",
                "location": "path",
                "name": "repo-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/repositories/{repo-public-id}",
        "title": "Get Repository",
    },
    "get_story": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Get Story returns information about a chosen Story.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Story.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}",
        "title": "Get Story",
    },
    "get_story_comment": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Get Comment is used to get Comment information.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/comments/{comment-public-id}",
        "title": "Get Story Comment",
    },
    "get_story_link": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Story Links",
        "description": "Returns the stories and their relationship for the given Story Link.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Story Link.",
                "location": "path",
                "name": "story-link-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/story-links/{story-link-public-id}",
        "title": "Get Story Link",
    },
    "get_task": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Returns information about a chosen Task.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Story this Task is associated with.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The unique ID of the Task.",
                "location": "path",
                "name": "task-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/tasks/{task-public-id}",
        "title": "Get Task",
    },
    "get_workflow": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Workflows",
        "description": "Get Workflow returns information about a chosen Workflow.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Workflow.",
                "location": "path",
                "name": "workflow-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/workflows/{workflow-public-id}",
        "title": "Get Workflow",
    },
    "link_document_to_epic": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Documents",
        "description": "Create a relationship between a Document and an Epic.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The public ID of the Document.",
                "location": "path",
                "name": "doc-public-id",
                "required": True,
                "type": "string",
            },
            {
                "description": "The public ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/documents/{doc-public-id}/epics/{epic-public-id}",
        "title": "Link Document to Epic",
    },
    "list_categories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Categories",
        "description": "List Categories returns a list of all Categories and their attributes.",
        "method": "GET",
        "parameters": [],
        "path": "/categories",
        "title": "List Categories",
    },
    "list_category_milestones": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Categories",
        "description": "List Category Milestones returns a list of all Milestones with "
        "the Category.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Category.",
                "location": "path",
                "name": "category-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/categories/{category-public-id}/milestones",
        "title": "List Category Milestones",
    },
    "list_category_objectives": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Categories",
        "description": "Returns a list of all Objectives with the Category.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Category.",
                "location": "path",
                "name": "category-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/categories/{category-public-id}/objectives",
        "title": "List Category Objectives",
    },
    "list_custom_fields": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Custom Fields",
        "description": "",
        "method": "GET",
        "parameters": [],
        "path": "/custom-fields",
        "title": "List Custom Fields",
    },
    "list_docs": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Documents",
        "description": "List Docs returns a list of Doc that the current user can read.",
        "method": "GET",
        "parameters": [],
        "path": "/documents",
        "title": "List Docs",
    },
    "list_document_epics": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Documents",
        "description": "Get a list of all Epics related to this Document.",
        "method": "GET",
        "parameters": [
            {
                "description": "The public ID of the Document.",
                "location": "path",
                "name": "doc-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/documents/{doc-public-id}/epics",
        "title": "List Document Epics",
    },
    "list_entity_templates": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Entity Templates",
        "description": "List all the entity templates for the Workspace.",
        "method": "GET",
        "parameters": [],
        "path": "/entity-templates",
        "title": "List Entity Templates",
    },
    "list_epic_comments": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "Get a list of all Comments on an Epic.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}/comments",
        "title": "List Epic Comments",
    },
    "list_epic_documents": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "Get a list of all Documents related to this Epic.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}/documents",
        "title": "List Epic Documents",
    },
    "list_epic_healths": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "List the history of health statuses for the specified Epic, most "
        "recent first.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}/health-history",
        "title": "List Epic Healths",
    },
    "list_epic_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "Get a list of all Stories in an Epic.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "A true/false boolean indicating whether to return "
                "Stories with their descriptions.",
                "location": "query",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            },
        ],
        "path": "/epics/{epic-public-id}/stories",
        "title": "List Epic Stories",
    },
    "list_epics": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "List Epics returns a list of all Epics and their attributes.",
        "method": "GET",
        "parameters": [
            {
                "description": "A true/false boolean indicating whether to return Epics with "
                "their descriptions.",
                "location": "query",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            }
        ],
        "path": "/epics",
        "title": "List Epics",
    },
    "list_epics_paginated": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Epics",
        "description": "List Epics with pagination returns a paginated list of Epics and "
        "their attributes.",
        "method": "GET",
        "parameters": [
            {
                "description": "A true/false boolean indicating whether to return "
                "Epics with their descriptions.",
                "location": "query",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The page number to return, starting with 1. "
                "Defaults to 1.",
                "location": "query",
                "name": "page",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The number of Epics to return per page. Minimum 1, "
                "maximum 250, default 10.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
        ],
        "path": "/epics/paginated",
        "title": "List Epics Paginated",
    },
    "list_files": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Files",
        "description": "List Files returns a list of all UploadedFiles in the workspace.",
        "method": "GET",
        "parameters": [],
        "path": "/files",
        "title": "List Files",
    },
    "list_group_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Groups",
        "description": "List the Stories assigned to the Group. (By default, limited to "
        "1,000).",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Group.",
                "location": "path",
                "name": "group-public-id",
                "required": True,
                "type": "string",
            },
            {
                "description": "The maximum number of results to return. (Defaults "
                "to 1000, max 1000)",
                "location": "query",
                "name": "limit",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The offset at which to begin returning results. "
                "(Defaults to 0)",
                "location": "query",
                "name": "offset",
                "required": False,
                "type": "integer",
            },
        ],
        "path": "/groups/{group-public-id}/stories",
        "title": "List Group Stories",
    },
    "list_groups": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Groups",
        "description": 'A group in our API maps to a "Team" within the Shortcut Product. A Team is '
        "a collection of Users that can be associated to Stories, Epics, and "
        "Iterations within Shortcut.",
        "method": "GET",
        "parameters": [
            {
                "description": "Filter groups by their archived state. If true, returns "
                "only archived groups. If false, returns only unarchived "
                "groups. If not provided, returns all groups",
                "location": "query",
                "name": "archived",
                "required": False,
                "type": "boolean",
            }
        ],
        "path": "/groups",
        "title": "List Groups",
    },
    "list_iteration_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Iterations",
        "description": "Get a list of all Stories in an Iteration.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Iteration.",
                "location": "path",
                "name": "iteration-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "A true/false boolean indicating whether to "
                "return Stories with their descriptions.",
                "location": "query",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            },
        ],
        "path": "/iterations/{iteration-public-id}/stories",
        "title": "List Iteration Stories",
    },
    "list_iterations": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Iterations",
        "description": "",
        "method": "GET",
        "parameters": [],
        "path": "/iterations",
        "title": "List Iterations",
    },
    "list_label_epics": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Labels",
        "description": "List all of the Epics with the Label.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Label.",
                "location": "path",
                "name": "label-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/labels/{label-public-id}/epics",
        "title": "List Label Epics",
    },
    "list_label_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Labels",
        "description": "List all of the Stories with the Label.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Label.",
                "location": "path",
                "name": "label-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "A true/false boolean indicating whether to return "
                "Stories with their descriptions.",
                "location": "query",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            },
        ],
        "path": "/labels/{label-public-id}/stories",
        "title": "List Label Stories",
    },
    "list_labels": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Labels",
        "description": "List Labels returns a list of all Labels and their attributes.",
        "method": "GET",
        "parameters": [
            {
                "description": "A true/false boolean indicating if the slim versions of the "
                "Label should be returned.",
                "location": "query",
                "name": "slim",
                "required": False,
                "type": "boolean",
            }
        ],
        "path": "/labels",
        "title": "List Labels",
    },
    "list_linked_files": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Linked Files",
        "description": "List Linked Files returns a list of all Linked-Files and their "
        "attributes.",
        "method": "GET",
        "parameters": [],
        "path": "/linked-files",
        "title": "List Linked Files",
    },
    "list_members": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Members",
        "description": "Returns information about members of the Workspace.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Organization to limit the list to.",
                "location": "query",
                "name": "org-public-id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Filter members by their disabled state. If true, return "
                "only disabled members. If false, return only enabled "
                "members.",
                "location": "query",
                "name": "disabled",
                "required": False,
                "type": "boolean",
            },
        ],
        "path": "/members",
        "title": "List Members",
    },
    "list_milestone_epics": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Milestones",
        "description": "(Deprecated: Use 'List Objective Epics') List all of the Epics "
        "within the Milestone.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Milestone.",
                "location": "path",
                "name": "milestone-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/milestones/{milestone-public-id}/epics",
        "title": "List Milestone Epics",
    },
    "list_milestones": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Milestones",
        "description": "(Deprecated: Use 'List Objectives') List Milestones returns a list of "
        "all Milestones and their attributes.",
        "method": "GET",
        "parameters": [],
        "path": "/milestones",
        "title": "List Milestones",
    },
    "list_objective_epics": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Objectives",
        "description": "List all of the Epics within the Objective.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}/epics",
        "title": "List Objective Epics",
    },
    "list_objective_healths": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Objectives",
        "description": "List the history of health statuses for the specified Objective, "
        "most recent first.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}/health-history",
        "title": "List Objective Healths",
    },
    "list_objectives": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Objectives",
        "description": "List Objectives returns a list of all Objectives and their attributes.",
        "method": "GET",
        "parameters": [],
        "path": "/objectives",
        "title": "List Objectives",
    },
    "list_projects": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Projects",
        "description": "List Projects returns a list of all Projects and their attributes.",
        "method": "GET",
        "parameters": [],
        "path": "/projects",
        "title": "List Projects",
    },
    "list_repositories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Repositories",
        "description": "List Repositories returns a list of all Repositories and their "
        "attributes.",
        "method": "GET",
        "parameters": [],
        "path": "/repositories",
        "title": "List Repositories",
    },
    "list_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Projects",
        "description": "List Stories returns a list of all Stories in a selected Project and their "
        "attributes.",
        "method": "GET",
        "parameters": [
            {
                "description": "The unique ID of the Project.",
                "location": "path",
                "name": "project-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "A true/false boolean indicating whether to return Stories "
                "with their descriptions.",
                "location": "query",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            },
        ],
        "path": "/projects/{project-public-id}/stories",
        "title": "List Stories",
    },
    "list_story_comment": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Lists Comments associated with a Story",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}/comments",
        "title": "List Story Comment",
    },
    "list_story_sub_tasks": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "List Story Sub tasks returns a list of all Sub-task Stories for a "
        "given parent Story.",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Story.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}/sub-tasks",
        "title": "List Story Sub tasks",
    },
    "list_workflows": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Workflows",
        "description": "Returns a list of all Workflows in the Workspace.",
        "method": "GET",
        "parameters": [],
        "path": "/workflows",
        "title": "List Workflows",
    },
    "query_stories": {
        "body_fields": [
            {
                "description": "A true/false boolean indicating whether the Story is in "
                "archived state.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "An array of UUIDs for any Users who may be Owners of the "
                "Stories.",
                "name": "owner_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The type of Stories that you want returned.",
                "name": "story_type",
                "required": False,
                "type": "string",
            },
            {
                "description": "Stories should have been updated on or before this date.",
                "name": "updated_at_end",
                "required": False,
                "type": "string",
            },
            {
                "description": "Stories should have been completed on or before this "
                "date.",
                "name": "completed_at_end",
                "required": False,
                "type": "string",
            },
            {
                "description": "Stories should have a deadline on or before this date.",
                "name": "deadline_end",
                "required": False,
                "type": "string",
            },
            {
                "description": "Stories should have been created on or after this date.",
                "name": "created_at_start",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Epic IDs that may be associated with the Stories.",
                "name": "epic_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The name of any associated Labels.",
                "name": "label_name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The UUID of any Users who may have requested the "
                "Stories.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Iteration ID that may be associated with the "
                "Stories.",
                "name": "iteration_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Group ID that is associated with the Stories",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The unique IDs of the specific Workflow States that the "
                "Stories should be in.",
                "name": "workflow_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "Stories should have been created on or before this date.",
                "name": "created_at_end",
                "required": False,
                "type": "string",
            },
            {
                "description": "Stories should have a deadline on or after this date.",
                "name": "deadline_start",
                "required": False,
                "type": "string",
            },
            {
                "description": "An ID or URL that references an external resource. "
                "Useful during imports.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "Whether to include the story description in the "
                "response.",
                "name": "includes_description",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The number of estimate points associate with the "
                "Stories.",
                "name": "estimate",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The IDs for the Projects the Stories may be assigned to.",
                "name": "project_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "Stories should have been completed on or after this "
                "date.",
                "name": "completed_at_start",
                "required": False,
                "type": "string",
            },
            {
                "description": "Stories should have been updated on or after this date.",
                "name": "updated_at_start",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Stories",
        "description": "Search Stories lets you search Stories based on desired parameters.",
        "method": "POST",
        "parameters": [],
        "path": "/stories/search",
        "title": "Query Stories",
    },
    "search": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search lets you search Epics and Stories based on desired parameters. Since "
        "ordering of the results can change over time (due to search ranking decay, new "
        "Epics and Stories being created), the `next` value from the previous response "
        "can be used as the path and query string for the next page to ensur",
        "method": "GET",
        "parameters": [
            {
                "description": "See our help center article on [search "
                "operators](https://help.shortcut.com/hc/en-us/articles/360000046646-Search-Operators)",
                "location": "query",
                "name": "query",
                "required": True,
                "type": "string",
            },
            {
                "description": "The number of search results to include in a page. Minimum of 1 "
                "and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The amount of detail included in each result item.\n"
                '   "full" will include all descriptions and comments and more '
                "fields on\n"
                "   related items such as pull requests, branches and tasks.\n"
                '   "slim" omits larger fulltext fields such as descriptions and '
                "comments\n"
                "   and only references related items by id.\n",
                "location": "query",
                "name": "detail",
                "required": False,
                "type": "string",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
            {
                "description": "A collection of entity_types to search. Defaults to story and "
                "epic. Supports: epic, iteration, objective, story.",
                "location": "query",
                "name": "entity_types",
                "required": False,
                "type": "array",
            },
        ],
        "path": "/search",
        "title": "Search",
    },
    "search_documents": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search Documents lets you search Documents based on desired "
        "parameters.\n"
        "                          Supports structured filters: title, "
        "archived, created_by_me, followed_by_me.",
        "method": "GET",
        "parameters": [
            {
                "description": "Search text to match against document titles. Supports "
                "fuzzy matching. Required.",
                "location": "query",
                "name": "title",
                "required": True,
                "type": "string",
            },
            {
                "description": "When true, find archived documents. When false, find "
                "non-archived documents.",
                "location": "query",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "When true, find documents created by the current user. "
                "When false, find documents NOT created by current "
                "user.",
                "location": "query",
                "name": "created_by_me",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "When true, find documents that the current user is "
                "following. When false, find documents NOT followed.",
                "location": "query",
                "name": "followed_by_me",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The number of search results to include in a page. "
                "Minimum of 1 and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
        ],
        "path": "/search/documents",
        "title": "Search Documents",
    },
    "search_epics": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search Epics lets you search Epics based on desired parameters. Since "
        "ordering of stories can change over time (due to search ranking decay, new "
        "Epics being created), the `next` value from the previous response can be "
        "used as the path and query string for the next page to ensure stable "
        "ordering.",
        "method": "GET",
        "parameters": [
            {
                "description": "See our help center article on [search "
                "operators](https://help.shortcut.com/hc/en-us/articles/360000046646-Search-Operators)",
                "location": "query",
                "name": "query",
                "required": True,
                "type": "string",
            },
            {
                "description": "The number of search results to include in a page. Minimum "
                "of 1 and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The amount of detail included in each result item.\n"
                '   "full" will include all descriptions and comments and '
                "more fields on\n"
                "   related items such as pull requests, branches and "
                "tasks.\n"
                '   "slim" omits larger fulltext fields such as '
                "descriptions and comments\n"
                "   and only references related items by id.\n",
                "location": "query",
                "name": "detail",
                "required": False,
                "type": "string",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
            {
                "description": "A collection of entity_types to search. Defaults to story "
                "and epic. Supports: epic, iteration, objective, story.",
                "location": "query",
                "name": "entity_types",
                "required": False,
                "type": "array",
            },
        ],
        "path": "/search/epics",
        "title": "Search Epics",
    },
    "search_iterations": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search Iterations lets you search Iterations based on desired "
        "parameters. Since ordering of results can change over time (due to "
        "search ranking decay, new Iterations being created), the `next` value "
        "from the previous response can be used as the path and query string "
        "for the next page to ensure stabl",
        "method": "GET",
        "parameters": [
            {
                "description": "See our help center article on [search "
                "operators](https://help.shortcut.com/hc/en-us/articles/360000046646-Search-Operators)",
                "location": "query",
                "name": "query",
                "required": True,
                "type": "string",
            },
            {
                "description": "The number of search results to include in a page. "
                "Minimum of 1 and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The amount of detail included in each result item.\n"
                '   "full" will include all descriptions and comments '
                "and more fields on\n"
                "   related items such as pull requests, branches and "
                "tasks.\n"
                '   "slim" omits larger fulltext fields such as '
                "descriptions and comments\n"
                "   and only references related items by id.\n",
                "location": "query",
                "name": "detail",
                "required": False,
                "type": "string",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
            {
                "description": "A collection of entity_types to search. Defaults to "
                "story and epic. Supports: epic, iteration, objective, "
                "story.",
                "location": "query",
                "name": "entity_types",
                "required": False,
                "type": "array",
            },
        ],
        "path": "/search/iterations",
        "title": "Search Iterations",
    },
    "search_milestones": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search Milestones lets you search Milestones based on desired "
        "parameters. Since ordering of results can change over time (due to "
        "search ranking decay, new Milestones being created), the `next` value "
        "from the previous response can be used as the path and query string "
        "for the next page to ensure stabl",
        "method": "GET",
        "parameters": [
            {
                "description": "See our help center article on [search "
                "operators](https://help.shortcut.com/hc/en-us/articles/360000046646-Search-Operators)",
                "location": "query",
                "name": "query",
                "required": True,
                "type": "string",
            },
            {
                "description": "The number of search results to include in a page. "
                "Minimum of 1 and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The amount of detail included in each result item.\n"
                '   "full" will include all descriptions and comments '
                "and more fields on\n"
                "   related items such as pull requests, branches and "
                "tasks.\n"
                '   "slim" omits larger fulltext fields such as '
                "descriptions and comments\n"
                "   and only references related items by id.\n",
                "location": "query",
                "name": "detail",
                "required": False,
                "type": "string",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
            {
                "description": "A collection of entity_types to search. Defaults to "
                "story and epic. Supports: epic, iteration, objective, "
                "story.",
                "location": "query",
                "name": "entity_types",
                "required": False,
                "type": "array",
            },
        ],
        "path": "/search/milestones",
        "title": "Search Milestones",
    },
    "search_objectives": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search Objectives lets you search Objectives based on desired "
        "parameters. Since ordering of results can change over time (due to "
        "search ranking decay, new Objectives being created), the `next` value "
        "from the previous response can be used as the path and query string "
        "for the next page to ensure stabl",
        "method": "GET",
        "parameters": [
            {
                "description": "See our help center article on [search "
                "operators](https://help.shortcut.com/hc/en-us/articles/360000046646-Search-Operators)",
                "location": "query",
                "name": "query",
                "required": True,
                "type": "string",
            },
            {
                "description": "The number of search results to include in a page. "
                "Minimum of 1 and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The amount of detail included in each result item.\n"
                '   "full" will include all descriptions and comments '
                "and more fields on\n"
                "   related items such as pull requests, branches and "
                "tasks.\n"
                '   "slim" omits larger fulltext fields such as '
                "descriptions and comments\n"
                "   and only references related items by id.\n",
                "location": "query",
                "name": "detail",
                "required": False,
                "type": "string",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
            {
                "description": "A collection of entity_types to search. Defaults to "
                "story and epic. Supports: epic, iteration, objective, "
                "story.",
                "location": "query",
                "name": "entity_types",
                "required": False,
                "type": "array",
            },
        ],
        "path": "/search/objectives",
        "title": "Search Objectives",
    },
    "search_stories": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Search",
        "description": "Search Stories lets you search Stories based on desired parameters. "
        "Since ordering of stories can change over time (due to search ranking "
        "decay, new stories being created), the `next` value from the previous "
        "response can be used as the path and query string for the next page to "
        "ensure stable orderin",
        "method": "GET",
        "parameters": [
            {
                "description": "See our help center article on [search "
                "operators](https://help.shortcut.com/hc/en-us/articles/360000046646-Search-Operators)",
                "location": "query",
                "name": "query",
                "required": True,
                "type": "string",
            },
            {
                "description": "The number of search results to include in a page. "
                "Minimum of 1 and maximum of 250.",
                "location": "query",
                "name": "page_size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The amount of detail included in each result item.\n"
                '   "full" will include all descriptions and comments and '
                "more fields on\n"
                "   related items such as pull requests, branches and "
                "tasks.\n"
                '   "slim" omits larger fulltext fields such as '
                "descriptions and comments\n"
                "   and only references related items by id.\n",
                "location": "query",
                "name": "detail",
                "required": False,
                "type": "string",
            },
            {
                "description": "The next page token.",
                "location": "query",
                "name": "next",
                "required": False,
                "type": "string",
            },
            {
                "description": "A collection of entity_types to search. Defaults to "
                "story and epic. Supports: epic, iteration, objective, "
                "story.",
                "location": "query",
                "name": "entity_types",
                "required": False,
                "type": "array",
            },
        ],
        "path": "/search/stories",
        "title": "Search Stories",
    },
    "story_history": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "",
        "method": "GET",
        "parameters": [
            {
                "description": "The ID of the Story.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}/history",
        "title": "Story History",
    },
    "unlink_comment_thread_from_slack": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Stories",
        "description": "Unlinks a Comment from its linked Slack thread "
        "(Comment replies and Slack replies will no longer be "
        "synced)",
        "method": "POST",
        "parameters": [
            {
                "description": "The ID of the Story to unlink.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment to unlink.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/comments/{comment-public-id}/unlink-from-slack",
        "title": "Unlink Comment thread from Slack",
    },
    "unlink_document_from_epic": {
        "body_fields": [],
        "body_required": [],
        "body_type": None,
        "category": "Documents",
        "description": "Remove a relationship between a Document and an Epic.",
        "method": "DELETE",
        "parameters": [
            {
                "description": "The public ID of the Document.",
                "location": "path",
                "name": "doc-public-id",
                "required": True,
                "type": "string",
            },
            {
                "description": "The public ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/documents/{doc-public-id}/epics/{epic-public-id}",
        "title": "Unlink Document from Epic",
    },
    "update_category": {
        "body_fields": [
            {
                "description": "The new name of the Category.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The hex color to be displayed with the Category (for "
                'example, "#ff0000").',
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "A true/false boolean indicating if the Category has "
                "been archived.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Categories",
        "description": "Update Category allows you to replace a Category name with another "
        "name. If you try to name a Category something that already exists, you "
        "will receive a 422 response.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Category you wish to update.",
                "location": "path",
                "name": "category-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/categories/{category-public-id}",
        "title": "Update Category",
    },
    "update_custom_field": {
        "body_fields": [
            {
                "description": "Indicates whether the Field is enabled for the "
                "Workspace. Only enabled fields can be applied to "
                "Stories.",
                "name": "enabled",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "A collection of objects representing reporting "
                "periods for years.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "A frontend-controlled string that represents the "
                "icon for this custom field.",
                "name": "icon_set_identifier",
                "required": False,
                "type": "string",
            },
            {
                "description": "A description of the purpose of this field.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the CustomField we want to move this "
                "CustomField before.",
                "name": "before_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the CustomField we want to move this "
                "CustomField after.",
                "name": "after_id",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Custom Fields",
        "description": "Update Custom Field can be used to update the definition of a "
        "Custom Field. The order of items in the 'values' collection is "
        "interpreted to be their ascending sort order.To delete an existing "
        "enum value, simply omit it from the 'values' collection. New enum "
        "values may be created inline by including ",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the CustomField.",
                "location": "path",
                "name": "custom-field-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/custom-fields/{custom-field-public-id}",
        "title": "Update Custom Field",
    },
    "update_doc": {
        "body_fields": [
            {
                "description": "The new title for the document",
                "name": "title",
                "required": False,
                "type": "string",
            },
            {
                "description": "The new content for the document.",
                "name": "content",
                "required": False,
                "type": "string",
            },
            {
                "description": "Default content_format: html. Format of content. For input: "
                "specifies format of provided content (defaults to 'html'). "
                "For output: controls response format - 'markdown' (default) "
                "or 'html' to include HTML content. Because output defaults "
                "to markdown, set 'markdown' when editing and writing back "
                "cont",
                "name": "content_format",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Documents",
        "description": "Updates an existing Doc's title and/or content. Supports markdown or HTML "
        "input via content_format parameter. WARNING: if content_format is not "
        "supplied, `content` input defaults to html. When a document is updated: (1) "
        "For Tiptap-migrated docs, SSE events notify connected Tiptap clients to "
        "refresh.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The Doc's public ID",
                "location": "path",
                "name": "doc-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/documents/{doc-public-id}",
        "title": "Update Doc",
    },
    "update_entity_template": {
        "body_fields": [
            {
                "description": "The updated template name.",
                "name": "name",
                "required": False,
                "type": "string",
            }
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Entity Templates",
        "description": "Update an entity template's name or its contents.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the template to be updated.",
                "location": "path",
                "name": "entity-template-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/entity-templates/{entity-template-public-id}",
        "title": "Update Entity Template",
    },
    "update_epic": {
        "body_fields": [
            {
                "description": "The Epic's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "A true/false boolean indicating whether the Epic is in "
                "archived state.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "A manual override for the time/date the Epic was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Epic's name.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Epic's planned start date.",
                "name": "planned_start_date",
                "required": False,
                "type": "string",
            },
            {
                "description": "`Deprecated` The Epic's state (to do, in progress, or "
                "done); will be ignored when `epic_state_id` is set.",
                "name": "state",
                "required": False,
                "type": "string",
            },
            {
                "description": "`Deprecated` The ID of the Milestone this Epic is related "
                "to. Use `objective_ids`.",
                "name": "milestone_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the member that requested the epic.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Epic State.",
                "name": "epic_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the Epic was started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "`Deprecated` The ID of the group to associate with the "
                "epic. Use `group_ids`.",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "This field can be set to another unique ID. In the case "
                "that the Epic has been imported from another tool, the ID "
                "in the other tool can be indicated here.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Epic we want to move this Epic before.",
                "name": "before_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the Epic we want to move this Epic after.",
                "name": "after_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Epic's deadline.",
                "name": "deadline",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Epics",
        "description": "Update Epic can be used to update numerous fields in the Epic. The only "
        "required parameter is Epic ID, which can be found in the Shortcut UI.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/epics/{epic-public-id}",
        "title": "Update Epic",
    },
    "update_epic_comment": {
        "body_fields": [
            {
                "description": "The updated comment text.",
                "name": "text",
                "required": True,
                "type": "string",
            }
        ],
        "body_required": ["text"],
        "body_type": "json",
        "category": "Epics",
        "description": "This endpoint allows you to update a threaded Comment on an Epic.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The ID of the associated Epic.",
                "location": "path",
                "name": "epic-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment.",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/epics/{epic-public-id}/comments/{comment-public-id}",
        "title": "Update Epic Comment",
    },
    "update_file": {
        "body_fields": [
            {
                "description": "The description of the file.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The time/date that the file was uploaded.",
                "name": "created_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "The time/date that the file was last updated.",
                "name": "updated_at",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of the file.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The unique ID assigned to the Member who uploaded the file "
                "to Shortcut.",
                "name": "uploader_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "An additional ID that you may wish to assign to the file.",
                "name": "external_id",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Files",
        "description": "Update File updates the properties of an UploadedFile (but not its "
        "content).",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID assigned to the file in Shortcut.",
                "location": "path",
                "name": "file-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/files/{file-public-id}",
        "title": "Update File",
    },
    "update_group": {
        "body_fields": [
            {
                "description": "The description of this Group.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "Whether or not this Group is archived.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": 'The card aging mode for stories in this Group: "gradual" '
                '(fixed fade steps at 1, 2, and 4 weeks), "immediate", or '
                '"off" (explicitly disabled for this Group). Set to null '
                "to inherit the Workspace default.",
                "name": "card_aging_mode",
                "required": False,
                "type": "string",
            },
            {
                "description": "The color you wish to use for the Group in the system.",
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "The number of days an in-progress Story can go without "
                "activity before it is considered stale. Required when "
                'card_aging_mode is "immediate"; not allowed otherwise.',
                "name": "card_aging_threshold_days",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Icon id for the avatar of this Group.",
                "name": "display_icon_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The mention name of this Group.",
                "name": "mention_name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of this Group.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The color key you wish to use for the Group in the "
                "system.",
                "name": "color_key",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the default workflow for stories created in "
                "this group.",
                "name": "default_workflow_id",
                "required": False,
                "type": "integer",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Groups",
        "description": "",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Group.",
                "location": "path",
                "name": "group-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/groups/{group-public-id}",
        "title": "Update Group",
    },
    "update_health": {
        "body_fields": [
            {
                "description": "The health status of the Epic.",
                "name": "status",
                "required": False,
                "type": "string",
            },
            {
                "description": "The description of the Health status.",
                "name": "text",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Health",
        "description": "Update an existing health status by its ID.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Health record.",
                "location": "path",
                "name": "health-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/health/{health-public-id}",
        "title": "Update Health",
    },
    "update_iteration": {
        "body_fields": [
            {
                "description": "The description of the Iteration.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of this Iteration",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The date this Iteration begins, e.g. 2019-07-01",
                "name": "start_date",
                "required": False,
                "type": "string",
            },
            {
                "description": "The date this Iteration ends, e.g. 2019-07-05.",
                "name": "end_date",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Iterations",
        "description": "",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Iteration.",
                "location": "path",
                "name": "iteration-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/iterations/{iteration-public-id}",
        "title": "Update Iteration",
    },
    "update_key_result": {
        "body_fields": [
            {
                "description": "The name of the Key Result.",
                "name": "name",
                "required": False,
                "type": "string",
            }
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Key Results",
        "description": "Update Key Result allows updating a Key Result's name or initial, "
        "observed, or target values.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The ID of the Key Result.",
                "location": "path",
                "name": "key-result-public-id",
                "required": True,
                "type": "string",
            }
        ],
        "path": "/key-results/{key-result-public-id}",
        "title": "Update Key Result",
    },
    "update_label": {
        "body_fields": [
            {
                "description": "The new name of the label.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The new description of the label.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The hex color to be displayed with the Label (for "
                'example, "#ff0000").',
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "A true/false boolean indicating if the Label has been "
                "archived.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Labels",
        "description": "Update Label allows you to replace a Label name with another name. If you "
        "try to name a Label something that already exists, you will receive a 422 "
        "response.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Label you wish to update.",
                "location": "path",
                "name": "label-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/labels/{label-public-id}",
        "title": "Update Label",
    },
    "update_linked_file": {
        "body_fields": [
            {
                "description": "The description of the file.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the linked story.",
                "name": "story_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The name of the file.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The URL of the thumbnail, if the integration "
                "provided it.",
                "name": "thumbnail_url",
                "required": False,
                "type": "string",
            },
            {
                "description": "The integration type of the file (e.g. google, "
                "dropbox, box).",
                "name": "type",
                "required": False,
                "type": "string",
            },
            {
                "description": "The filesize, if the integration provided it.",
                "name": "size",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The UUID of the member that uploaded the file.",
                "name": "uploader_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The URL of linked file.",
                "name": "url",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Linked Files",
        "description": "Updated Linked File allows you to update properties of a previously "
        "attached Linked-File.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique identifier of the linked file.",
                "location": "path",
                "name": "linked-file-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/linked-files/{linked-file-public-id}",
        "title": "Update Linked File",
    },
    "update_milestone": {
        "body_fields": [
            {
                "description": "The Milestone's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "A boolean indicating whether the Milestone is "
                "archived or not",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "A manual override for the time/date the Milestone was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of the Milestone.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The workflow state that the Milestone is in.",
                "name": "state",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Milestone was "
                "started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Milestone we want to move this "
                "Milestone before.",
                "name": "before_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the Milestone we want to move this "
                "Milestone after.",
                "name": "after_id",
                "required": False,
                "type": "integer",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Milestones",
        "description": "(Deprecated: Use 'Update Objective') Update Milestone can be used to "
        "update Milestone properties.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The ID of the Milestone.",
                "location": "path",
                "name": "milestone-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/milestones/{milestone-public-id}",
        "title": "Update Milestone",
    },
    "update_multiple_stories": {
        "body_fields": [
            {
                "description": "If the Stories should be archived or not.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The type of story (feature, bug, chore).",
                "name": "story_type",
                "required": False,
                "type": "string",
            },
            {
                "description": 'One of "first" or "last". This can be used to '
                "move the given story to the first or last "
                "position in the workflow state.",
                "name": "move_to",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the epic the story belongs to.",
                "name": "epic_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the member that requested the story.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the iteration the story belongs to.",
                "name": "iteration_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Id of the Group the Stories should belong " "to.",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the workflow state to put the " "stories in.",
                "name": "workflow_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the story that the stories are to be "
                "moved before.",
                "name": "before_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The numeric point estimate of the story. Can "
                "also be null, which means unestimated.",
                "name": "estimate",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the story that the stories are to be "
                "moved below.",
                "name": "after_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the Project the Stories should " "belong to.",
                "name": "project_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The due date of the story.",
                "name": "deadline",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": ["story_ids"],
        "body_type": "json",
        "category": "Stories",
        "description": "Update Multiple Stories allows you to make changes to numerous "
        "stories at once.",
        "method": "PUT",
        "parameters": [],
        "path": "/stories/bulk",
        "title": "Update Multiple Stories",
    },
    "update_objective": {
        "body_fields": [
            {
                "description": "The Objective's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "A boolean indicating whether the Objective is "
                "archived or not",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "A manual override for the time/date the Objective was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The name of the Objective.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The workflow state that the Objective is in.",
                "name": "state",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Objective was "
                "started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the Objective we want to move this "
                "Objective before.",
                "name": "before_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the Objective we want to move this "
                "Objective after.",
                "name": "after_id",
                "required": False,
                "type": "integer",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Objectives",
        "description": "Update Objective can be used to update Objective properties.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The ID of the Objective.",
                "location": "path",
                "name": "objective-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/objectives/{objective-public-id}",
        "title": "Update Objective",
    },
    "update_project": {
        "body_fields": [
            {
                "description": "The Project's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "A true/false boolean indicating whether the Story is in "
                "archived state.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The number of days before the thermometer appears in "
                "the Story summary.",
                "name": "days_to_thermometer",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The color that represents the Project in the UI.",
                "name": "color",
                "required": False,
                "type": "string",
            },
            {
                "description": "The Project's name.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "Configuration to enable or disable thermometers in the "
                "Story summary.",
                "name": "show_thermometer",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The ID of the team the project belongs to.",
                "name": "team_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The Project abbreviation used in Story summaries. "
                "Should be kept to 3 characters at most.",
                "name": "abbreviation",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Projects",
        "description": "Update Project can be used to change properties of a Project.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Project.",
                "location": "path",
                "name": "project-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/projects/{project-public-id}",
        "title": "Update Project",
    },
    "update_story": {
        "body_fields": [
            {
                "description": "The description of the story.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "True if the story is archived, otherwise false.",
                "name": "archived",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "The type of story (feature, bug, chore).",
                "name": "story_type",
                "required": False,
                "type": "string",
            },
            {
                "description": 'One of "first" or "last". This can be used to move the '
                "given story to the first or last position in the workflow "
                "state.",
                "name": "move_to",
                "required": False,
                "type": "string",
            },
            {
                "description": "A manual override for the time/date the Story was "
                "completed.",
                "name": "completed_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The title of the story.",
                "name": "name",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the epic the story belongs to.",
                "name": "epic_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the member that requested the story.",
                "name": "requested_by_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the iteration the story belongs to.",
                "name": "iteration_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "A manual override for the time/date the Story was "
                "started.",
                "name": "started_at_override",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the group to associate with this story",
                "name": "group_id",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the workflow state to put the story in.",
                "name": "workflow_state_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The parent story id. If you want to unset this value set "
                "parent_story_id to null.",
                "name": "parent_story_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the story we want to move this story before.",
                "name": "before_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The numeric point estimate of the story. Can also be "
                "null, which means unestimated.",
                "name": "estimate",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the story we want to move this story after.",
                "name": "after_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the project the story belongs to.",
                "name": "project_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The due date of the story.",
                "name": "deadline",
                "required": False,
                "type": "string",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Stories",
        "description": "Update Story can be used to update Story properties.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique identifier of this story.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/stories/{story-public-id}",
        "title": "Update Story",
    },
    "update_story_comment": {
        "body_fields": [
            {
                "description": "The updated comment text.",
                "name": "text",
                "required": True,
                "type": "string",
            }
        ],
        "body_required": ["text"],
        "body_type": "json",
        "category": "Stories",
        "description": "Update Comment replaces the text of the existing Comment.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The ID of the Story that the Comment is in.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The ID of the Comment",
                "location": "path",
                "name": "comment-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/comments/{comment-public-id}",
        "title": "Update Story Comment",
    },
    "update_story_link": {
        "body_fields": [
            {
                "description": "The type of link.",
                "name": "verb",
                "required": False,
                "type": "string",
            },
            {
                "description": "The ID of the subject Story.",
                "name": "subject_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "The ID of the object Story.",
                "name": "object_id",
                "required": False,
                "type": "integer",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Story Links",
        "description": "Updates the stories and/or the relationship for the given Story Link.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique ID of the Story Link.",
                "location": "path",
                "name": "story-link-public-id",
                "required": True,
                "type": "integer",
            }
        ],
        "path": "/story-links/{story-link-public-id}",
        "title": "Update Story Link",
    },
    "update_task": {
        "body_fields": [
            {
                "description": "The Task's description.",
                "name": "description",
                "required": False,
                "type": "string",
            },
            {
                "description": "A true/false boolean indicating whether the task is "
                "complete.",
                "name": "complete",
                "required": False,
                "type": "boolean",
            },
            {
                "description": "Move task before this task ID.",
                "name": "before_id",
                "required": False,
                "type": "integer",
            },
            {
                "description": "Move task after this task ID.",
                "name": "after_id",
                "required": False,
                "type": "integer",
            },
        ],
        "body_required": [],
        "body_type": "json",
        "category": "Stories",
        "description": "Update Task can be used to update Task properties.",
        "method": "PUT",
        "parameters": [
            {
                "description": "The unique identifier of the parent Story.",
                "location": "path",
                "name": "story-public-id",
                "required": True,
                "type": "integer",
            },
            {
                "description": "The unique identifier of the Task you wish to update.",
                "location": "path",
                "name": "task-public-id",
                "required": True,
                "type": "integer",
            },
        ],
        "path": "/stories/{story-public-id}/tasks/{task-public-id}",
        "title": "Update Task",
    },
    "upload_files": {
        "body_fields": [],
        "body_required": [],
        "body_type": "multipart",
        "category": "Files",
        "description": "Upload Files uploads one or many files and optionally associates them with "
        "a story.\n"
        "   Use the multipart/form-data content-type to upload.\n"
        "   Each `file` key should contain a separate file.\n"
        "   Each UploadedFile's name comes from the Content-Disposition header "
        '"filename" directive for that field.',
        "method": "POST",
        "parameters": [],
        "path": "/files",
        "title": "Upload Files",
    },
}


SHORTCUT_API_BASE = "https://api.app.shortcut.com/api/v3"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class ShortcutApiTokenCredential(BaseModel):
    """Shortcut's stable REST API uses per-user API tokens, not third-party OAuth."""

    credential_type: Literal["shortcut_api_token"] = Field(
        "shortcut_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="Create a token in Shortcut under Settings → Your Account → API Tokens.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Shortcut API Token",
        json_schema_extra={
            "x-credential-url": "https://app.shortcut.com/settings/account/api-tokens"
        }
    )


def _field_name(location: str, name: str) -> str:
    return f"{location}_{name.replace('-', '_')}"


def _python_type(kind: str) -> type:
    return {"integer": int, "number": float, "boolean": bool}.get(kind, str)


def _title(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").title().replace("Id", "ID")


def _make_operation_model(action: str, contract: dict[str, Any]) -> type[BaseModel]:
    """Make a distinct discriminated config for every documented endpoint."""

    title = contract["title"]
    fields: dict[str, Any] = {
        "operation": (
            Literal[action],
            Field(
                action,
                title=title,
                json_schema_extra={
                    "const": action,
                    "ui:hidden": True,
                    "x-category": contract["category"],
                    "x-display-name": title,
                    "x-is-trigger": False,
                },
            ),
        )
    }
    for parameter in contract["parameters"]:
        name = _field_name(parameter["location"], parameter["name"])
        value_type = _python_type(parameter["type"])
        # Comma-separated query arrays can be filled from an expression or
        # entered by hand. The wire serializer turns them back into arrays.
        if parameter["type"] == "array":
            value_type = str
        required = parameter["required"]
        fields[name] = (
            value_type if required else Optional[value_type],
            Field(
                ... if required else None,
                title=_title(parameter["name"]),
                description=parameter["description"]
                or f"Shortcut {parameter['location']} parameter.",
            ),
        )
    if contract["body_type"] == "json":
        # Typed scalar fields make frequent actions quick to configure; the
        # JSON field exposes every nested/array field in the official schema.
        for body_field in contract["body_fields"]:
            name = _field_name("body", body_field["name"])
            required = body_field["required"]
            field_type = _python_type(body_field["type"])
            fields[name] = (
                field_type if required else Optional[field_type],
                Field(
                    ... if required else None,
                    title=_title(body_field["name"]),
                    description=body_field["description"]
                    or "Shortcut request body field.",
                ),
            )
        fields["body_json"] = (
            Optional[str],
            Field(
                None,
                title="Additional JSON Body",
                description="JSON object for nested fields or other documented request fields."
                " Explicit fields above take precedence.",
                json_schema_extra={"ui:widget": "textarea"},
            ),
        )
    elif contract["body_type"] == "multipart":
        fields["file_base64"] = (
            str,
            Field(
                ...,
                title="File (Base64)",
                description="Base64-encoded file to upload, up to 20 MB.",
            ),
        )
        fields["filename"] = (
            Optional[str],
            Field(None, title="Filename", description="Name shown in Shortcut."),
        )
        fields["body_story_id"] = (
            Optional[int],
            Field(None, title="Story ID", description="Story to attach the file to."),
        )
    model_name = (
        "Shortcut" + "".join(part.title() for part in action.split("_")) + "Config"
    )
    model = create_model(
        model_name, __module__=__name__, __config__=ConfigDict(title=title), **fields
    )
    model.__doc__ = contract["description"] or f"{title} using the Shortcut REST API."
    return model


OPERATION_MODELS = {
    action: _make_operation_model(action, contract)
    for action, contract in OPERATIONS.items()
}
ShortcutConfig = Annotated[
    Union[tuple(OPERATION_MODELS.values())], Discriminator("operation")
]


class ShortcutNodeConfig(NodeConfig[ShortcutConfig, ShortcutApiTokenCredential]):
    """Shortcut operation and per-user API token."""


class ShortcutNode(WorkflowNode):
    """Execute a documented Shortcut REST v3 operation."""

    integration_type = "automation-shortcut"

    edit_examples = [
        "Search stories for the latest customer request and add a comment",
        "Create a Story for every high-priority support ticket",
        "Move a Story to the completed workflow state",
        "List an Epic's Stories and summarize their status",
    ]
    connection_evidence = ConnectionEvidence(
        operation="list_projects",
        noun="projects",
        label_keys=("name", "id"),
        identity_operation="get_current_member_info",
    )

    @classmethod
    def get_config_model(cls):
        return ShortcutNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        if not isinstance(self.config, ShortcutNodeConfig):
            raise ValueError("Shortcut node configuration is required")
        if not self.config.credentials or not self.config.credentials.api_token:
            raise ValueError("Shortcut API token is required")

        config = self.config.config
        action = config.operation
        contract = OPERATIONS[action]
        values = config.model_dump(exclude_none=True)
        path = contract["path"]
        query: dict[str, Any] = {}
        for parameter in contract["parameters"]:
            key = _field_name(parameter["location"], parameter["name"])
            value = values.get(key)
            if value is None:
                continue
            if parameter["location"] == "path":
                path = path.replace(
                    "{" + parameter["name"] + "}", quote(str(value), safe="")
                )
            else:
                if parameter["type"] == "array" and isinstance(value, str):
                    value = [part.strip() for part in value.split(",") if part.strip()]
                query[parameter["name"]] = value
        if re.search(r"\{[^}]+\}", path):
            raise ValueError("A required Shortcut path parameter is missing")

        request_kwargs: dict[str, Any] = {}
        if contract["body_type"] == "json":
            body: dict[str, Any] = {}
            if values.get("body_json"):
                try:
                    body = json.loads(values["body_json"])
                except json.JSONDecodeError as exc:
                    raise ValueError("Additional JSON Body must be valid JSON") from exc
                if not isinstance(body, dict):
                    raise ValueError("Additional JSON Body must be a JSON object")
            for field in contract["body_fields"]:
                key = _field_name("body", field["name"])
                if key in values:
                    body[field["name"]] = values[key]
            if action == "create_story" and not (
                body.get("project_id") or body.get("workflow_state_id")
            ):
                raise ValueError(
                    "Create Story requires a Project ID or Workflow State ID"
                )
            missing = [name for name in contract["body_required"] if name not in body]
            if missing:
                raise ValueError(
                    "Shortcut request body is missing: " + ", ".join(missing)
                )
            request_kwargs["json"] = body
        elif contract["body_type"] == "multipart":
            try:
                blob = base64.b64decode(values["file_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("File must be valid Base64") from exc
            if not blob or len(blob) > MAX_UPLOAD_BYTES:
                raise ValueError("File must be between 1 byte and 20 MB")
            filename = values.get("filename") or "upload"
            request_kwargs["files"] = {"file0": (filename, blob)}
            if values.get("body_story_id") is not None:
                request_kwargs["data"] = {"story_id": str(values["body_story_id"])}

        headers = {"Shortcut-Token": self.config.credentials.api_token}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(
                    contract["method"],
                    SHORTCUT_API_BASE + path,
                    headers=headers,
                    params=query,
                    **request_kwargs,
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "status": "error",
                "action": action,
                "status_code": exc.response.status_code,
                "error": exc.response.text[:2000],
                "timing_ms": {
                    "api_request": round((time.perf_counter() - start) * 1000, 2)
                },
            }
        except httpx.RequestError as exc:
            return {
                "status": "error",
                "action": action,
                "error": str(exc),
                "timing_ms": {
                    "api_request": round((time.perf_counter() - start) * 1000, 2)
                },
            }

        if not response.content:
            data: dict[str, Any] = {}
        else:
            try:
                payload = response.json()
            except ValueError:
                data = {"text": response.text}
            else:
                if isinstance(payload, dict):
                    data = payload
                elif isinstance(payload, list):
                    data = {
                        "items": [
                            item if isinstance(item, dict) else {"value": item}
                            for item in payload
                        ]
                    }
                else:
                    data = {"value": payload}
        return {
            "status": "success",
            "action": action,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {
                "api_request": round((time.perf_counter() - start) * 1000, 2)
            },
        }
