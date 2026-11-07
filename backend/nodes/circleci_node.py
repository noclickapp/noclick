"""CircleCI API v2 workflow actions generated from the official OpenAPI spec.

CircleCI's OAuth DCR flow only permits loopback redirect URIs, so hosted
NoClick uses a user-created personal API token. See the credential setup URL.
"""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://circleci.com/api/v2"
# Operation definitions derived from https://circleci.com/api/v2/openapi.json.
_catalog = json.loads(r'''
{
  "source": "https://circleci.com/api/v2/openapi.json",
  "sha256": "6273a5c611833aebe9b1a09b2a6929145ecf0d8f7ce562e1821792a7497c8df7",
  "operations": [
    {
      "name": "add_environment_variable_to_context",
      "label": "Add or update an environment variable",
      "category": "Context",
      "description": "Create or update an environment variable within a context. Returns information about the environment variable, not including its value.",
      "method": "PUT",
      "path": "/context/{context_id}/environment-variable/{env_var_name}",
      "path_params": [
        "context_id",
        "env_var_name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "value"
      ]
    },
    {
      "name": "create_context",
      "label": "Create a new context",
      "category": "Context",
      "description": "Creates a new context in the specified organization.",
      "method": "POST",
      "path": "/context",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "name",
        "owner"
      ]
    },
    {
      "name": "create_context_restriction",
      "label": "Create context restriction",
      "category": "Context",
      "description": "Creates project or expression restriction on a context.",
      "method": "POST",
      "path": "/context/{context_id}/restrictions",
      "path_params": [
        "context_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "delete_context",
      "label": "Delete a context",
      "category": "Context",
      "description": "Delete a context by its ID. Will also delete all environment variables inside the context.",
      "method": "DELETE",
      "path": "/context/{context_id}",
      "path_params": [
        "context_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "delete_context_restriction",
      "label": "Delete context restriction",
      "category": "Context",
      "description": "Deletes a project, expression or group restriction from a context.",
      "method": "DELETE",
      "path": "/context/{context_id}/restrictions/{restriction_id}",
      "path_params": [
        "context_id",
        "restriction_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "delete_environment_variable_from_context",
      "label": "Remove an environment variable",
      "category": "Context",
      "description": "Delete an environment variable from a context.",
      "method": "DELETE",
      "path": "/context/{context_id}/environment-variable/{env_var_name}",
      "path_params": [
        "context_id",
        "env_var_name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_context",
      "label": "Get a context",
      "category": "Context",
      "description": "Returns basic information about a context.",
      "method": "GET",
      "path": "/context/{context_id}",
      "path_params": [
        "context_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_context_restrictions",
      "label": "Get context restrictions",
      "category": "Context",
      "description": "Gets a list of project and expression restrictions associated with a context.",
      "method": "GET",
      "path": "/context/{context_id}/restrictions",
      "path_params": [
        "context_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_contexts",
      "label": "List contexts",
      "category": "Context",
      "description": "List all contexts for an owner.",
      "method": "GET",
      "path": "/context",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_environment_variables_from_context",
      "label": "List environment variables",
      "category": "Context",
      "description": "List information about environment variables in a context, not including their values.",
      "method": "GET",
      "path": "/context/{context_id}/environment-variable",
      "path_params": [
        "context_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_component",
      "label": "Get Component",
      "category": "Deploy",
      "description": "Get the details of a component by ID.",
      "method": "GET",
      "path": "/deploy/components/{component_id}",
      "path_params": [
        "component_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_environment",
      "label": "Get Environment",
      "category": "Deploy",
      "description": "Allows getting an environment for a given environment ID.",
      "method": "GET",
      "path": "/deploy/environments/{environment_id}",
      "path_params": [
        "environment_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_component_versions",
      "label": "List Component Versions",
      "category": "Deploy",
      "description": "List the versions for a component.",
      "method": "GET",
      "path": "/deploy/components/{component_id}/versions",
      "path_params": [
        "component_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_components",
      "label": "List Components",
      "category": "Deploy",
      "description": "Allows for listing of components for a given organization ID.",
      "method": "GET",
      "path": "/deploy/components",
      "path_params": [],
      "required_query": [
        "org-id",
        "page-size"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_environments",
      "label": "List Environments",
      "category": "Deploy",
      "description": "Allows listing environments for a given organization ID.",
      "method": "GET",
      "path": "/deploy/environments",
      "path_params": [],
      "required_query": [
        "org-id",
        "page-size"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "create_organization_group",
      "label": "Create Groups",
      "category": "Groups",
      "description": "Create a new group under the organization. Currently only supported for standalone organizations.",
      "method": "POST",
      "path": "/organizations/{org_id}/groups",
      "path_params": [
        "org_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "name"
      ]
    },
    {
      "name": "delete_group",
      "label": "Delete a group",
      "category": "Groups",
      "description": "Delete a group in an organization. This will remove all members from the group as well, and the subsequent role grants tied to the group. Currently only supported for standalone organizations.",
      "method": "DELETE",
      "path": "/organizations/{org_id}/groups/{group_id}",
      "path_params": [
        "org_id",
        "group_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_group",
      "label": "A group in an organization",
      "category": "Groups",
      "description": "Get details for a group in an organization. Currently only supported for standalone organizations.",
      "method": "GET",
      "path": "/organizations/{org_id}/groups/{group_id}",
      "path_params": [
        "org_id",
        "group_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_organization_groups",
      "label": "Groups in an organization",
      "category": "Groups",
      "description": "Get all the groups in an organization.",
      "method": "GET",
      "path": "/organizations/{org_id}/groups",
      "path_params": [
        "org_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_all_insights_branches",
      "label": "Get all branches for a project",
      "category": "Insights",
      "description": "Get a list of all branches for a specified project. The list will only contain branches currently available within Insights. The maximum number of branches returned by this endpoint is 5,000.",
      "method": "GET",
      "path": "/insights/{project-slug}/branches",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_flaky_tests",
      "label": "Get flaky tests for a project",
      "category": "Insights",
      "description": "Get a list of flaky tests for a given project. Flaky tests are branch agnostic.\n             A flaky test is a test that passed and failed in the same commit.",
      "method": "GET",
      "path": "/insights/{project-slug}/flaky-tests",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_job_timeseries",
      "label": "Job timeseries data",
      "category": "Insights",
      "description": "Get timeseries data for all jobs within a workflow. Hourly granularity data is only retained for 48 hours while daily granularity data is retained for 90 days.",
      "method": "GET",
      "path": "/insights/time-series/{project-slug}/workflows/{workflow-name}/jobs",
      "path_params": [
        "project-slug",
        "workflow-name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_org_summary_data",
      "label": "Get summary metrics with trends for the entire org, and for each project.",
      "category": "Insights",
      "description": "Gets aggregated summary metrics with trends for the entire org.\n              Also gets aggregated metrics and trends for each project belonging to the org.",
      "method": "GET",
      "path": "/insights/{org-slug}/summary",
      "path_params": [
        "org-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_workflow_job_metrics",
      "label": "Get summary metrics for a project workflow's jobs.",
      "category": "Insights",
      "description": "Get summary metrics for a project workflow's jobs. Job runs going back at most 90 days are included in the aggregation window. Metrics are refreshed daily, and thus may not include executions from the last 24 hours. Please note that Insights is not a financial reporting tool and should not be used for precise credit reporting.  Credit reporting from Insights does not use the same source of truth as the billing information that is found in the Plan Overview page in the CircleCI UI, nor does the u",
      "method": "GET",
      "path": "/insights/{project-slug}/workflows/{workflow-name}/jobs",
      "path_params": [
        "project-slug",
        "workflow-name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_workflow_metrics",
      "label": "Get summary metrics for a project's workflows",
      "category": "Insights",
      "description": "Get summary metrics for a project's workflows.  Workflow runs going back at most 90 days are included in the aggregation window. Metrics are refreshed daily, and thus may not include executions from the last 24 hours.  Please note that Insights is not a financial reporting tool and should not be used for precise credit reporting.  Credit reporting from Insights does not use the same source of truth as the billing information that is found in the Plan Overview page in the CircleCI UI, nor does th",
      "method": "GET",
      "path": "/insights/{project-slug}/workflows",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_workflow_runs",
      "label": "Get recent runs of a workflow",
      "category": "Insights",
      "description": "Get recent runs of a workflow. Runs going back at most 90 days are returned. Please note that Insights is not a financial reporting tool and should not be used for precise credit reporting.  Credit reporting from Insights does not use the same source of truth as the billing information that is found in the Plan Overview page in the CircleCI UI, nor does the underlying data have the same data accuracy guarantees as the billing information in the CircleCI UI.  This may lead to discrepancies betwee",
      "method": "GET",
      "path": "/insights/{project-slug}/workflows/{workflow-name}",
      "path_params": [
        "project-slug",
        "workflow-name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_workflow_test_metrics",
      "label": "Get test metrics for a project's workflows",
      "category": "Insights",
      "description": "Get test metrics for a project's workflows. Currently tests metrics are calculated based on 10 most recent workflow runs.",
      "method": "GET",
      "path": "/insights/{project-slug}/workflows/{workflow-name}/test-metrics",
      "path_params": [
        "project-slug",
        "workflow-name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_workflows_page_data",
      "label": "Get summary metrics and trends for a project across it's workflows and branches",
      "category": "Insights",
      "description": "Get summary metrics and trends for a project at workflow and branch level.\n             Workflow runs going back at most 90 days are included in the aggregation window.\n             Trends are only supported upto last 30 days.\n             Please note that Insights is not a financial reporting tool and should not be used for precise credit reporting.  Credit reporting from Insights does not use the same source of truth as the billing information that is found in the Plan Overview page in the Cir",
      "method": "GET",
      "path": "/insights/pages/{project-slug}/summary",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_workflow_summary",
      "label": "Get metrics and trends for workflows",
      "category": "Insights",
      "description": "Get the metrics and trends for a particular workflow on a single branch or all branches",
      "method": "GET",
      "path": "/insights/{project-slug}/workflows/{workflow-name}/summary",
      "path_params": [
        "project-slug",
        "workflow-name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "cancel_job_by_job_id",
      "label": "Cancel job by job ID",
      "category": "Job",
      "description": "Cancel job with a given job ID.",
      "method": "POST",
      "path": "/jobs/{job-id}/cancel",
      "path_params": [
        "job-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "cancel_job_by_job_number",
      "label": "Cancel job by job number",
      "category": "Job",
      "description": "Cancel job with a given job number.",
      "method": "POST",
      "path": "/project/{project-slug}/job/{job-number}/cancel",
      "path_params": [
        "project-slug",
        "job-number"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_job",
      "label": "Get a job",
      "category": "Job",
      "description": "Gets a job's metadata by its unique ID, including its name, job number, type, status, and associated resource IDs.",
      "method": "GET",
      "path": "/jobs/{job_id}",
      "path_params": [
        "job_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "delete_org_claims",
      "label": "Delete org-level claims",
      "category": "OIDC Token Management",
      "description": "Deletes org-level custom claims of OIDC identity tokens",
      "method": "DELETE",
      "path": "/org/{orgID}/oidc-custom-claims",
      "path_params": [
        "orgID"
      ],
      "required_query": [
        "claims"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "delete_project_claims",
      "label": "Delete project-level claims",
      "category": "OIDC Token Management",
      "description": "Deletes project-level custom claims of OIDC identity tokens",
      "method": "DELETE",
      "path": "/org/{orgID}/project/{projectID}/oidc-custom-claims",
      "path_params": [
        "orgID",
        "projectID"
      ],
      "required_query": [
        "claims"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_org_claims",
      "label": "Get org-level claims",
      "category": "OIDC Token Management",
      "description": "Fetches org-level custom claims of OIDC identity tokens",
      "method": "GET",
      "path": "/org/{orgID}/oidc-custom-claims",
      "path_params": [
        "orgID"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_claims",
      "label": "Get project-level claims",
      "category": "OIDC Token Management",
      "description": "Fetches project-level custom claims of OIDC identity tokens",
      "method": "GET",
      "path": "/org/{orgID}/project/{projectID}/oidc-custom-claims",
      "path_params": [
        "orgID",
        "projectID"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "patch_org_claims",
      "label": "Patch org-level claims",
      "category": "OIDC Token Management",
      "description": "Creates/Updates org-level custom claims of OIDC identity tokens",
      "method": "PATCH",
      "path": "/org/{orgID}/oidc-custom-claims",
      "path_params": [
        "orgID"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "patch_project_claims",
      "label": "Patch project-level claims",
      "category": "OIDC Token Management",
      "description": "Creates/Updates project-level custom claims of OIDC identity tokens",
      "method": "PATCH",
      "path": "/org/{orgID}/project/{projectID}/oidc-custom-claims",
      "path_params": [
        "orgID",
        "projectID"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "create_otel_exporter",
      "label": "🧪 Create an OTLP exporter",
      "category": "OTel",
      "description": "[__EXPERIMENTAL__] Creates a new OTLP exporter configuration for the given organization. A maximum of 5 exporter configurations are allowed per organization.",
      "method": "POST",
      "path": "/otel/exporters",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "endpoint",
        "org_id",
        "protocol"
      ]
    },
    {
      "name": "delete_otel_exporter",
      "label": "🧪 Delete an OTLP exporter",
      "category": "OTel",
      "description": "[__EXPERIMENTAL__] Deletes an OTLP exporter configuration by ID.",
      "method": "DELETE",
      "path": "/otel/exporters/{otel_exporter_id}",
      "path_params": [
        "otel_exporter_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_otel_exporters",
      "label": "🧪 List OTLP exporters",
      "category": "OTel",
      "description": "[__EXPERIMENTAL__] Returns a list of OTLP exporter configurations for the given organization.",
      "method": "GET",
      "path": "/otel/exporters",
      "path_params": [],
      "required_query": [
        "org-id"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "create_organization",
      "label": "Create a new organization",
      "category": "Organization",
      "description": "Create a new organization. For VCS providers (GitHub/Bitbucket), this validates access and syncs org data. For standalone orgs, this creates a new CircleCI organization.",
      "method": "POST",
      "path": "/organization",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "name",
        "vcs_type"
      ]
    },
    {
      "name": "create_url_orb_allow_list_entry",
      "label": "Create a new URL Orb allow-list entry",
      "category": "Organization",
      "description": "Create a new URL Orb allow-list entry",
      "method": "POST",
      "path": "/organization/{org-slug-or-id}/url-orb-allow-list",
      "path_params": [
        "org-slug-or-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "auth",
        "name",
        "prefix"
      ]
    },
    {
      "name": "delete_organization",
      "label": "Delete an organization",
      "category": "Organization",
      "description": "Delete an organization. This action will delete all projects including all build data for the organization.",
      "method": "DELETE",
      "path": "/organization/{org-slug-or-id}",
      "path_params": [
        "org-slug-or-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_organization",
      "label": "Get an organization",
      "category": "Organization",
      "description": "Retrieve an organization by slug or ID",
      "method": "GET",
      "path": "/organization/{org-slug-or-id}",
      "path_params": [
        "org-slug-or-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_url_orb_allow_list_entries",
      "label": "List the entries in the org's URL Orb allow-list",
      "category": "Organization",
      "description": "List the entries in the org's URL Orb allow-list",
      "method": "GET",
      "path": "/organization/{org-slug-or-id}/url-orb-allow-list",
      "path_params": [
        "org-slug-or-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "remove_url_orb_allow_list_entry",
      "label": "Remove an entry from the org's URL orb allow-list",
      "category": "Organization",
      "description": "Remove an entry from the org's URL orb allow-list",
      "method": "DELETE",
      "path": "/organization/{org-slug-or-id}/url-orb-allow-list/{allow-list-entry-id}",
      "path_params": [
        "org-slug-or-id",
        "allow-list-entry-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "continue_pipeline",
      "label": "Continue a pipeline",
      "category": "Pipeline",
      "description": "Continue a pipeline from the setup phase. For information on using pipeline parameters with dynamic configuration, see the [Pipeline values and parameters](https://circleci.com/docs/pipeline-variables/#pipeline-parameters-and-dynamic-configuration) docs.",
      "method": "POST",
      "path": "/pipeline/continue",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "configuration",
        "continuation-key"
      ]
    },
    {
      "name": "get_pipeline_by_id",
      "label": "Get a pipeline by ID",
      "category": "Pipeline",
      "description": "Returns a pipeline by the pipeline ID.",
      "method": "GET",
      "path": "/pipeline/{pipeline-id}",
      "path_params": [
        "pipeline-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_pipeline_by_number",
      "label": "Get a pipeline by pipeline number",
      "category": "Pipeline",
      "description": "Returns a pipeline by the pipeline number.",
      "method": "GET",
      "path": "/project/{project-slug}/pipeline/{pipeline-number}",
      "path_params": [
        "project-slug",
        "pipeline-number"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_pipeline_config_by_id",
      "label": "Get a pipeline's configuration",
      "category": "Pipeline",
      "description": "Returns a pipeline's configuration by ID.",
      "method": "GET",
      "path": "/pipeline/{pipeline-id}/config",
      "path_params": [
        "pipeline-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_pipeline_values_by_id",
      "label": "Get pipeline values for a pipeline",
      "category": "Pipeline",
      "description": "Returns a map of pipeline values by pipeline ID. For more information see the [pipeline values reference page](https://circleci.com/docs/variables/#pipeline-values).",
      "method": "GET",
      "path": "/pipeline/{pipeline_id}/values",
      "path_params": [
        "pipeline_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_my_pipelines",
      "label": "Get your pipelines",
      "category": "Pipeline",
      "description": "Returns a sequence of all pipelines for this project triggered by the user.",
      "method": "GET",
      "path": "/project/{project-slug}/pipeline/mine",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_pipelines",
      "label": "Get a list of pipelines",
      "category": "Pipeline",
      "description": "Returns all pipelines for the most recently built projects (max 250) you follow in an organization.",
      "method": "GET",
      "path": "/pipeline",
      "path_params": [],
      "required_query": [
        "org-slug"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_pipelines_for_project",
      "label": "Get all pipelines",
      "category": "Pipeline",
      "description": "Returns all pipelines for this project.",
      "method": "GET",
      "path": "/project/{project-slug}/pipeline",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_workflows_by_pipeline_id",
      "label": "Get a pipeline's workflows",
      "category": "Pipeline",
      "description": "Returns a paginated list of workflows by pipeline ID.",
      "method": "GET",
      "path": "/pipeline/{pipeline-id}/workflow",
      "path_params": [
        "pipeline-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "trigger_pipeline",
      "label": "Trigger a new pipeline",
      "category": "Pipeline",
      "description": "**[This endpoint is superseded by the [new Trigger Pipeline API](#tag/Pipeline/operation/triggerPipelineRun), which supports all organization and pipeline types except GitLab.]** Triggers a new pipeline on the project. Does not support triggering pipelines integrated with GitLab or GitHub App.",
      "method": "POST",
      "path": "/project/{project-slug}/pipeline",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "trigger_pipeline_run",
      "label": "[Recommended] Trigger a new pipeline",
      "category": "Pipeline",
      "description": "Trigger a pipeline given a pipeline definition ID. Currently only supported for pipeline definitions where `config_source.provider` is `github_app`, `github_server`, `github_oauth`, `bitbucket_dc`, or `bitbucket_oauth`.\n\nThe slash-separated project slug is shown in Project Settings > Overview.\n\nDepending on the organization type, the project slug may have a human-readable format (`vcs_type/org_name/project_name`)\nor be an opaque string (e.g. `circleci/43G3lM5RtfFE7v5sa4nWAU/44n9wujWcTnVZ2b5S8Fna",
      "method": "POST",
      "path": "/project/{provider}/{organization}/{project}/pipeline/run",
      "path_params": [
        "provider",
        "organization",
        "project"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "create_pipeline_definition",
      "label": "Create pipeline definition",
      "category": "Pipeline Definition",
      "description": "Create a pipeline definition for a given project. Currently only supported for pipeline definitions where `config_source.provider` is `github_app` or `github_server`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "POST",
      "path": "/projects/{project_id}/pipeline-definitions",
      "path_params": [
        "project_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "checkout_source",
        "config_source",
        "name"
      ]
    },
    {
      "name": "delete_pipeline_definition",
      "label": "Delete pipeline definition",
      "category": "Pipeline Definition",
      "description": "Delete pipeline definition. Currently only supported for pipeline definitions where `config_source.provider` is `github_app`, `github_server`, or `bitbucket_dc`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "DELETE",
      "path": "/projects/{project_id}/pipeline-definitions/{pipeline_definition_id}",
      "path_params": [
        "project_id",
        "pipeline_definition_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_pipeline_definition",
      "label": "Get pipeline definition",
      "category": "Pipeline Definition",
      "description": "Get details for a pipeline definition. Currently only supported for pipeline definitions where `config_source.provider` is `github_app`, `github_server`, `github_oauth`, `bitbucket_dc`, `bitbucket_oauth` or `gitlab`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "GET",
      "path": "/projects/{project_id}/pipeline-definitions/{pipeline_definition_id}",
      "path_params": [
        "project_id",
        "pipeline_definition_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_pipeline_definitions",
      "label": "List pipeline definitions",
      "category": "Pipeline Definition",
      "description": "List all pipeline definitions for a given project. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "GET",
      "path": "/projects/{project_id}/pipeline-definitions",
      "path_params": [
        "project_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "update_pipeline_definition",
      "label": "Update pipeline definition",
      "category": "Pipeline Definition",
      "description": "Update pipeline definition. Currently only supported for pipeline definitions where `config_source.provider` is `github_app`, `github_server`, or `bitbucket_dc`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "PATCH",
      "path": "/projects/{project_id}/pipeline-definitions/{pipeline_definition_id}",
      "path_params": [
        "project_id",
        "pipeline_definition_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "create_policy_bundle",
      "label": "Creates policy bundle for the context",
      "category": "Policy Management",
      "description": "This endpoint replaces the current policy bundle with the provided policy bundle",
      "method": "POST",
      "path": "/owner/{ownerID}/context/{context}/policy-bundle",
      "path_params": [
        "ownerID",
        "context"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_decision_log",
      "label": "Retrieves the owner's decision audit log by given decisionID",
      "category": "Policy Management",
      "description": "This endpoint will retrieve a decision for a given decision log ID",
      "method": "GET",
      "path": "/owner/{ownerID}/context/{context}/decision/{decisionID}",
      "path_params": [
        "ownerID",
        "context",
        "decisionID"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_decision_log_policy_bundle",
      "label": "Retrieves Policy Bundle for a given decision log ID",
      "category": "Policy Management",
      "description": "This endpoint will retrieve a policy bundle for a given decision log ID",
      "method": "GET",
      "path": "/owner/{ownerID}/context/{context}/decision/{decisionID}/policy-bundle",
      "path_params": [
        "ownerID",
        "context",
        "decisionID"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_decision_logs",
      "label": "Retrieves the owner's decision audit logs.",
      "category": "Policy Management",
      "description": "This endpoint will return a list of decision audit logs that were made using this owner's policies.",
      "method": "GET",
      "path": "/owner/{ownerID}/context/{context}/decision",
      "path_params": [
        "ownerID",
        "context"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_decision_settings",
      "label": "Get the decision settings",
      "category": "Policy Management",
      "description": "This endpoint retrieves the current decision settings (eg enable/disable policy evaluation)",
      "method": "GET",
      "path": "/owner/{ownerID}/context/{context}/decision/settings",
      "path_params": [
        "ownerID",
        "context"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_policy_bundle",
      "label": "Retrieves Policy Bundle",
      "category": "Policy Management",
      "description": "This endpoint will retrieve a policy bundle",
      "method": "GET",
      "path": "/owner/{ownerID}/context/{context}/policy-bundle",
      "path_params": [
        "ownerID",
        "context"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_policy_document",
      "label": "Retrieves a policy document",
      "category": "Policy Management",
      "description": "This endpoint will retrieve a policy document.",
      "method": "GET",
      "path": "/owner/{ownerID}/context/{context}/policy-bundle/{policyName}",
      "path_params": [
        "ownerID",
        "context",
        "policyName"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "make_decision",
      "label": "Makes a decision",
      "category": "Policy Management",
      "description": "This endpoint will evaluate input data (config+metadata) against owner's stored policies and return a decision.",
      "method": "POST",
      "path": "/owner/{ownerID}/context/{context}/decision",
      "path_params": [
        "ownerID",
        "context"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "input"
      ]
    },
    {
      "name": "set_decision_settings",
      "label": "Set the decision settings",
      "category": "Policy Management",
      "description": "This endpoint allows modifying decision settings (eg enable/disable policy evaluation)",
      "method": "PATCH",
      "path": "/owner/{ownerID}/context/{context}/decision/settings",
      "path_params": [
        "ownerID",
        "context"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "create_checkout_key",
      "label": "Create a new checkout key",
      "category": "Project",
      "description": "Not available to projects that use GitLab or GitHub App. Creates a new checkout key. This API request is only usable with a user API token.\n                           Please ensure that you have authorized your account with GitHub before creating user keys.\n                           This is necessary to give CircleCI the permission to create a user key associated with\n                           your GitHub user account. You can find this page by visiting Project Settings > Checkout SSH Keys",
      "method": "POST",
      "path": "/project/{project-slug}/checkout-key",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "type"
      ]
    },
    {
      "name": "create_env_var",
      "label": "Create an environment variable",
      "category": "Project",
      "description": "Creates a new environment variable.",
      "method": "POST",
      "path": "/project/{project-slug}/envvar",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "name",
        "value"
      ]
    },
    {
      "name": "create_project",
      "label": "Create a new project",
      "category": "Project",
      "description": "Create a new project. Works for all organization types.",
      "method": "POST",
      "path": "/organization/{org-slug-or-id}/project",
      "path_params": [
        "org-slug-or-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "name"
      ]
    },
    {
      "name": "delete_checkout_key",
      "label": "Delete a checkout key",
      "category": "Project",
      "description": "Deletes the checkout key via md5 or sha256 fingerprint. sha256 keys should be url-encoded.",
      "method": "DELETE",
      "path": "/project/{project-slug}/checkout-key/{fingerprint}",
      "path_params": [
        "project-slug",
        "fingerprint"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "delete_env_var",
      "label": "Delete an environment variable",
      "category": "Project",
      "description": "Deletes the environment variable named :name.",
      "method": "DELETE",
      "path": "/project/{project-slug}/envvar/{name}",
      "path_params": [
        "project-slug",
        "name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "delete_project_by_slug",
      "label": "Delete a project",
      "category": "Project",
      "description": "Deletes a project by project slug",
      "method": "DELETE",
      "path": "/project/{project-slug}",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_checkout_key",
      "label": "Get a checkout key",
      "category": "Project",
      "description": "Returns an individual checkout key via md5 or sha256 fingerprint. sha256 keys should be url-encoded.",
      "method": "GET",
      "path": "/project/{project-slug}/checkout-key/{fingerprint}",
      "path_params": [
        "project-slug",
        "fingerprint"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_env_var",
      "label": "Get a masked environment variable",
      "category": "Project",
      "description": "Returns the masked value of environment variable :name.",
      "method": "GET",
      "path": "/project/{project-slug}/envvar/{name}",
      "path_params": [
        "project-slug",
        "name"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_by_slug",
      "label": "Get a project",
      "category": "Project",
      "description": "Retrieves a project by project slug.",
      "method": "GET",
      "path": "/project/{project-slug}",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_project_settings",
      "label": "Get project settings",
      "category": "Project",
      "description": "Returns a list of the advanced settings for a CircleCI project, whether enabled (true) or not (false).",
      "method": "GET",
      "path": "/project/{provider}/{organization}/{project}/settings",
      "path_params": [
        "provider",
        "organization",
        "project"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_checkout_keys",
      "label": "Get all checkout keys",
      "category": "Project",
      "description": "Returns a sequence of checkout keys for `:project`.",
      "method": "GET",
      "path": "/project/{project-slug}/checkout-key",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_env_vars",
      "label": "List all environment variables",
      "category": "Project",
      "description": "Returns four 'x' characters, in addition to the last four ASCII characters of the value, consistent with the display of environment variable values on the CircleCI website.",
      "method": "GET",
      "path": "/project/{project-slug}/envvar",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "patch_project_settings",
      "label": "Update project settings",
      "category": "Project",
      "description": "Updates one or more of the advanced settings for a CircleCI project.",
      "method": "PATCH",
      "path": "/project/{provider}/{organization}/{project}/settings",
      "path_params": [
        "provider",
        "organization",
        "project"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "rollback_project",
      "label": "Rollback a project",
      "category": "Rollback",
      "description": "Performs a rollback operation by triggering a rollback pipeline.",
      "method": "POST",
      "path": "/projects/{project_id}/rollback",
      "path_params": [
        "project_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "component_name",
        "current_version",
        "environment_name",
        "target_version"
      ]
    },
    {
      "name": "create_schedule",
      "label": "Create a schedule",
      "category": "Schedule",
      "description": "Creates a schedule and returns the created schedule. Available only on organizations of type `bitbucket` and `github`, and for the latter will exclusively create schedule triggers associated with the GitHub OAuth pipeline definition. For projects of type `circleci`, or to create schedule triggers for GitHub App pipeline definitions, use the [Create trigger](https://circleci.com/docs/api/v2/index.html#tag/Trigger/operation/createTrigger) endpoint.",
      "method": "POST",
      "path": "/project/{project-slug}/schedule",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "attribution-actor",
        "name",
        "parameters",
        "timetable"
      ]
    },
    {
      "name": "delete_schedule_by_id",
      "label": "Delete a schedule",
      "category": "Schedule",
      "description": "Deletes a schedule by ID. Available only on schedules associated with GitHub OAuth or Bitbucket Cloud pipeline definitions.",
      "method": "DELETE",
      "path": "/schedule/{schedule-id}",
      "path_params": [
        "schedule-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_schedule_by_id",
      "label": "Get a schedule by ID. Available only on schedules associated with GitHub OAuth or Bitbucket Cloud pipeline definitions.",
      "category": "Schedule",
      "description": "Get a schedule by id.",
      "method": "GET",
      "path": "/schedule/{schedule-id}",
      "path_params": [
        "schedule-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_schedules_for_project",
      "label": "List schedule triggers",
      "category": "Schedule",
      "description": "For a given project, returns all schedules associated with GitHub OAuth or Bitbucket Cloud pipeline definitions. Does not return schedule triggers associated with GitHub App pipelines. To fetch schedule triggers associated with GitHub App pipelines, use the [List pipeline definition triggers](https://circleci.com/docs/api/v2/index.html#tag/Trigger/operation/listPipelineDefinitionTriggers] endpoint.",
      "method": "GET",
      "path": "/project/{project-slug}/schedule",
      "path_params": [
        "project-slug"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "update_schedule",
      "label": "Update a schedule",
      "category": "Schedule",
      "description": "Updates a schedule and returns the updated schedule. Available only on schedules associated with GitHub OAuth or Bitbucket Cloud pipeline definitions. To update schedule triggers for GitHub App pipeline definitions, use the [Update trigger](https://circleci.com/docs/api/v2/index.html#tag/Trigger/operation/updateTrigger) endpoint.",
      "method": "PATCH",
      "path": "/schedule/{schedule-id}",
      "path_params": [
        "schedule-id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "create_trigger",
      "label": "Create trigger",
      "category": "Trigger",
      "description": "Create a trigger for a given pipeline definition. Currently only supported for pipeline definitions where `config_source.provider` is `github_oauth`, `github_app`, `github_server`, or `schedule`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "POST",
      "path": "/projects/{project_id}/pipeline-definitions/{pipeline_definition_id}/triggers",
      "path_params": [
        "project_id",
        "pipeline_definition_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "event_source"
      ]
    },
    {
      "name": "delete_trigger",
      "label": "Delete trigger",
      "category": "Trigger",
      "description": "Delete a trigger. Currently only supported for triggers where `event_source.provider` is `github_oauth`, `github_app`, `github_server`, `bitbucket_dc`, `webhook`, or `schedule`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "DELETE",
      "path": "/projects/{project_id}/triggers/{trigger_id}",
      "path_params": [
        "project_id",
        "trigger_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_trigger",
      "label": "Get trigger",
      "category": "Trigger",
      "description": "Get details for a trigger. Currently only supported for triggers where `event_source.provider` is `github_oauth`, `github_app`, `github_server`, `bitbucket_dc`, `webhook`, or `schedule`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "GET",
      "path": "/projects/{project_id}/triggers/{trigger_id}",
      "path_params": [
        "project_id",
        "trigger_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_pipeline_definition_triggers",
      "label": "List pipeline definition triggers",
      "category": "Trigger",
      "description": "List all triggers for a given pipeline definition. Currently only supported for pipeline definitions where `config_source.provider` is `github_oauth`, `github_app`, `github_server`, `bitbucket_dc`, or `schedule`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "GET",
      "path": "/projects/{project_id}/pipeline-definitions/{pipeline_definition_id}/triggers",
      "path_params": [
        "project_id",
        "pipeline_definition_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "update_trigger",
      "label": "Update trigger",
      "category": "Trigger",
      "description": "Update a trigger. Currently only supported for triggers where `event_source.provider` is `github_oauth`, `github_app`, `github_server`, `bitbucket_dc`, `webhook`, or `schedule`. [Share feedback](https://circleci.canny.io/cloud-feature-requests/p/project-administration-apis) about our Project Administration APIs.",
      "method": "PATCH",
      "path": "/projects/{project_id}/triggers/{trigger_id}",
      "path_params": [
        "project_id",
        "trigger_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "create_usage_export",
      "label": "Create a usage export",
      "category": "Usage",
      "description": "Submits a request to create a usage export for an organization.",
      "method": "POST",
      "path": "/organizations/{org_id}/usage_export_job",
      "path_params": [
        "org_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "end",
        "start"
      ]
    },
    {
      "name": "get_usage_export",
      "label": "Get a usage export",
      "category": "Usage",
      "description": "Gets a usage export for an organization.",
      "method": "GET",
      "path": "/organizations/{org_id}/usage_export_job/{usage_export_job_id}",
      "path_params": [
        "org_id",
        "usage_export_job_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_collaborations",
      "label": "Collaborations",
      "category": "User",
      "description": "Provides the set of organizations of which a user is a member or a collaborator.\n\nThe set of organizations that a user can collaborate on is composed of:\n\n* Organizations that the current user belongs to across VCS types (e.g. BitBucket, GitHub)\n* The parent organization of repository that the user can collaborate on, but is not necessarily a member of\n* The organization of the current user's account",
      "method": "GET",
      "path": "/me/collaborations",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_current_user",
      "label": "User Information",
      "category": "User",
      "description": "Provides information about the user that is currently signed in.",
      "method": "GET",
      "path": "/me",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_user",
      "label": "User Information",
      "category": "User",
      "description": "Provides information about the user with the given ID.",
      "method": "GET",
      "path": "/user/{id}",
      "path_params": [
        "id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "create_webhook",
      "label": "Create an outbound webhook",
      "category": "Webhook",
      "description": "Creates an outbound webhook for the given scope.",
      "method": "POST",
      "path": "/webhook",
      "path_params": [],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": [
        "events",
        "name",
        "scope",
        "signing-secret",
        "url",
        "verify-tls"
      ]
    },
    {
      "name": "delete_webhook",
      "label": "Delete an outbound webhook",
      "category": "Webhook",
      "description": "Deletes an existing outbound webhook by its unique ID.",
      "method": "DELETE",
      "path": "/webhook/{webhook_id}",
      "path_params": [
        "webhook_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_webhook_by_id",
      "label": "Get a webhook",
      "category": "Webhook",
      "description": "Get an outbound webhook by id.",
      "method": "GET",
      "path": "/webhook/{webhook_id}",
      "path_params": [
        "webhook_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_webhooks",
      "label": "List webhooks",
      "category": "Webhook",
      "description": "Get a list of outbound webhooks that match the given scope-type and scope-id.",
      "method": "GET",
      "path": "/webhook",
      "path_params": [],
      "required_query": [
        "scope-id",
        "scope-type"
      ],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "update_webhook",
      "label": "Update an outbound webhook",
      "category": "Webhook",
      "description": "Updates an existing outbound webhook by its unique ID.",
      "method": "PUT",
      "path": "/webhook/{webhook_id}",
      "path_params": [
        "webhook_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": true,
      "body_required_fields": []
    },
    {
      "name": "approve_pending_approval_job_by_id",
      "label": "Approve a job",
      "category": "Workflow",
      "description": "Approves a pending approval job in a workflow.",
      "method": "POST",
      "path": "/workflow/{id}/approve/{approval_request_id}",
      "path_params": [
        "id",
        "approval_request_id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "cancel_workflow",
      "label": "Cancel a workflow",
      "category": "Workflow",
      "description": "Cancels a running workflow.",
      "method": "POST",
      "path": "/workflow/{id}/cancel",
      "path_params": [
        "id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "get_workflow_by_id",
      "label": "Get a workflow",
      "category": "Workflow",
      "description": "Returns summary fields of a workflow by ID.",
      "method": "GET",
      "path": "/workflow/{id}",
      "path_params": [
        "id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "list_workflow_jobs",
      "label": "Get a workflow's jobs",
      "category": "Workflow",
      "description": "Returns a sequence of jobs for a workflow.",
      "method": "GET",
      "path": "/workflow/{id}/job",
      "path_params": [
        "id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": false,
      "body_required": false,
      "body_required_fields": []
    },
    {
      "name": "rerun_workflow",
      "label": "Rerun a workflow",
      "category": "Workflow",
      "description": "Reruns a workflow.",
      "method": "POST",
      "path": "/workflow/{id}/rerun",
      "path_params": [
        "id"
      ],
      "required_query": [],
      "required_headers": [],
      "body_json": true,
      "body_required": false,
      "body_required_fields": []
    }
  ]
}
''')
OPERATIONS: dict[str, dict[str, Any]] = {row["name"]: row for row in _catalog["operations"]}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate CircleCI actions"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class CircleCIPersonalTokenCredential(BaseModel):
    """A CircleCI personal API token from User Settings > Personal API Tokens."""

    credential_type: Literal["circleci_pat"] = Field(
        "circleci_pat", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ..., title="Personal API Token",
        description="Create a personal API token in CircleCI User Settings. Project tokens do not work with API v2.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="CircleCI Personal API Token", json_schema_extra={
        "x-credential-url": "https://app.circleci.com/settings/user/tokens",
    })


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


# Small request bodies use native typed fields, as other staging nodes do.
# Names, enums and shapes: https://circleci.com/docs/api/v2/index.html
_NATIVE_BODY_FIELDS: dict[str, dict[str, tuple[Any, Any]]] = {
    "patch_org_claims": {
        "audience": (Optional[list[str]], Field(None, description="OIDC token audiences.")),
        "ttl": (Optional[str], Field(None, pattern=r"^([0-9]+(ms|s|m|h|d|w)){1,7}$", description="OIDC token duration, using CircleCI duration units.")),
    },
    "patch_project_claims": {
        "audience": (Optional[list[str]], Field(None, description="OIDC token audiences.")),
        "ttl": (Optional[str], Field(None, pattern=r"^([0-9]+(ms|s|m|h|d|w)){1,7}$", description="OIDC token duration, using CircleCI duration units.")),
    },
    "create_organization": {
        "name": (str, Field(..., description="Organization name.")),
        "vcs_type": (Literal["github", "bitbucket", "circleci"], Field(..., title="VCS Type")),
    },
    "make_decision": {
        "input": (str, Field(..., description="Input for the policy decision.")),
        "metadata": (Optional[dict[str, Any]], Field(None, description="Decision metadata.")),
    },
    "set_decision_settings": {
        "enabled": (bool, Field(..., description="Enable policy decisions.")),
    },
    "create_checkout_key": {
        "type": (Literal["user-key", "deploy-key"], Field(..., title="Checkout Key Type")),
    },
    "create_env_var": {
        "name": (str, Field(..., description="Environment variable name.")),
        "value": (str, Field(..., description="Environment variable value.", json_schema_extra={"ui:widget": "password"})),
    },
    "create_project": {
        "name": (str, Field(..., description="Project name.")),
    },
}


class _CircleCIClaimsUpdate(BaseModel):
    @model_validator(mode="after")
    def require_claim_update(self):
        if self.audience is None and self.ttl is None:
            raise ValueError("Set at least one OIDC claim: audience or ttl")
        return self


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={
                "const": name, "ui:hidden": True, "x-category": op["category"],
                "x-display-name": op["label"], "x-is-trigger": False,
            },
        )),
    }
    for raw in op["path_params"]:
        fields[_field_name("path", raw)] = (
            str, Field(..., title=raw.replace("-", " ").replace("_", " ").title())
        )
    for raw in op["required_query"]:
        fields[_field_name("query", raw)] = (
            str, Field(..., title=raw.replace("-", " ").replace("_", " ").title())
        )
    for raw in op["required_headers"]:
        fields[_field_name("header", raw)] = (
            str, Field(..., title=raw.replace("-", " ").title())
        )
    fields["query_json"] = (
        Optional[str], Field(
            None, title="Other Query Parameters (JSON)",
            description="Optional filters, pagination, and other CircleCI API query parameters.",
            json_schema_extra=_JSON_EDITOR,
        ),
    )
    if name in _NATIVE_BODY_FIELDS:
        fields.update(_NATIVE_BODY_FIELDS[name])
    elif op["body_json"]:
        description = "JSON object matching the CircleCI API reference for this action."
        if op["body_required_fields"]:
            description += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        fields["body_json"] = (
            str if op["body_required"] else Optional[str],
            Field(... if op["body_required"] else None,
                  title="Request Body (JSON)", description=description,
                  json_schema_extra=_JSON_EDITOR),
        )
    return create_model(
        "CircleCI" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__,
        __base__=_CircleCIClaimsUpdate if name in {"patch_org_claims", "patch_project_claims"} else BaseModel,
        **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
CircleCIConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class CircleCINodeConfig(NodeConfig[CircleCIConfig, CircleCIPersonalTokenCredential]):
    model_config = ConfigDict(title="CircleCI Node Configuration", json_schema_extra={"x-agent-tool-provider": True})


def _parse_object(raw: Optional[str], label: str) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


class CircleCINode(WorkflowNode):
    """Run any of the 111 CircleCI API v2 operations."""

    integration_type = "automation-circleci"

    connection_evidence = ConnectionEvidence(operation="get_current_user", noun="user")
    edit_examples = [
        "List CircleCI pipelines", "Get the latest workflow jobs",
        "Trigger a CircleCI pipeline", "List project environment variables",
    ]

    @classmethod
    def get_config_model(cls):
        return CircleCINodeConfig

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            value = values.pop(_field_name("path", raw), None)
            if not value or str(value).strip() in {".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_object(values.pop("query_json", None), "Query Parameters") or {}
        for raw in op["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        for raw in op["required_headers"]:
            headers[raw] = values.pop(_field_name("header", raw))
        request: dict[str, Any] = {}
        if op["body_json"]:
            body = (
                {field: values.pop(field) for field in _NATIVE_BODY_FIELDS[name] if field in values}
                if name in _NATIVE_BODY_FIELDS
                else _parse_object(values.pop("body_json", None), "Request Body")
            )
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required for this action")
            missing = [key for key in op["body_required_fields"]
                       if body is None or key not in body]
            if missing:
                raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                request["json"] = body
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"], API_BASE + path, params=params or None,
                headers=headers, **request,
            )
        if not response.content:
            data: Any = {}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:2000]}
        if response.is_error or response.is_redirect:
            message = data.get("message") or data.get("error") if isinstance(data, dict) else None
            raise ValueError(f"CircleCI API error {response.status_code}: {message or 'request failed'}")
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, CircleCINodeConfig) or not self.config.credentials:
            raise ValueError("Add a CircleCI personal API token before running this action")
        config = self.config.config
        return await self._request(
            self.config.credentials.api_token, config.operation,
            config.model_dump(exclude={"operation"}, exclude_none=True),
        )
