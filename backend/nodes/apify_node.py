"""
Apify REST API automation node.

This node provides Apify operations in workflows via direct REST API calls.
Uses httpx for high-performance async HTTP requests.

Apify is a platform for web scraping and automation. This node enables users to:
- Run Actors (pre-built scrapers and automation tools)
- Manage Actor Tasks (saved Actor configurations)
- Access Datasets (structured results from Actor runs)
- Use Key-Value Stores (flexible data storage)
- Configure Schedules (automated Actor/Task execution)
- Set up Webhooks (event notifications)

API Reference: https://docs.apify.com/api/v2
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Union, Literal, List, Annotated

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

APIFY_API_BASE = "https://api.apify.com/v2"


# ============================================================================
# Apify Credential Schema
# ============================================================================


class ApifyApiTokenCredential(BaseModel):
    """API Token credential for Apify.

    Get your API token at: https://console.apify.com/settings/integrations
    """

    credential_type: Literal["apify_api_token"] = Field(
        "apify_api_token", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.apify.com/settings/integrations"
        }
    )

    api_token: str = Field(
        ...,
        title="API Token",
        description="Your Apify API token from console.apify.com/settings/integrations",
        json_schema_extra={
            "ui:widget": "password",
        },
    )


# Single credential type for Apify
ApifyCredential = ApifyApiTokenCredential


# ============================================================================
# Actor Operations
# ============================================================================


class ApifyListActorsConfig(BaseModel):
    """List Actors available to the user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_actors"] = Field(
        default="list_actors",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "List Actors",
        },
        title="List Actors",
    )
    my: Optional[bool] = Field(
        default=True,
        title="My Actors Only",
        description="Only list Actors created by you",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of records to return (max 1000)",
    )


class ApifyGetActorConfig(BaseModel):
    """Get information about a specific Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor"] = Field(
        default="get_actor",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Get Actor",
        },
        title="Get Actor",
    )
    actor_id: str = Field(
        ...,
        title="Actor ID",
        description="Actor ID or username~actor-name (e.g., 'apify~web-scraper')",
    )


class ApifyRunActorConfig(BaseModel):
    """Run an Actor asynchronously"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["run_actor_asynchronously"] = Field(
        default="run_actor_asynchronously",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Run Actor Asynchronously",
        },
        title="Run Actor Asynchronously",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name to run"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input (JSON)",
        description="JSON input to pass to the Actor",
        json_schema_extra={"ui:widget": "textarea"},
    )
    memory_mbytes: Optional[int] = Field(
        default=None,
        title="Memory (MB)",
        description="Memory limit in megabytes (128-32768)",
    )
    timeout_secs: Optional[int] = Field(
        default=None, title="Timeout (seconds)", description="Timeout in seconds"
    )
    build: Optional[str] = Field(
        default=None,
        title="Build",
        description="Build tag or number to use (default: latest)",
    )


class ApifyRunActorSyncConfig(BaseModel):
    """Run an Actor synchronously and wait for results (max 300 seconds)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["run_actor_synchronously"] = Field(
        default="run_actor_synchronously",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Run Actor Synchronously",
        },
        title="Run Actor Synchronously",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name to run"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input (JSON)",
        description="JSON input to pass to the Actor",
        json_schema_extra={"ui:widget": "textarea"},
    )
    memory_mbytes: Optional[int] = Field(
        default=None, title="Memory (MB)", description="Memory limit in megabytes"
    )
    timeout_secs: Optional[int] = Field(
        default=300,
        title="Timeout (seconds)",
        description="Timeout in seconds (max 300 for sync runs)",
    )


class ApifyRunActorSyncGetDatasetItemsConfig(BaseModel):
    """Run an Actor synchronously and get dataset items directly"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["run_actor_sync_and_get_dataset_items"] = Field(
        default="run_actor_sync_and_get_dataset_items",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Run Actor Sync and Get Dataset Items",
        },
        title="Run Actor Sync and Get Dataset Items",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name to run"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input (JSON)",
        description="JSON input to pass to the Actor",
        json_schema_extra={"ui:widget": "textarea"},
    )
    memory_mbytes: Optional[int] = Field(
        default=None, title="Memory (MB)", description="Memory limit in megabytes"
    )
    timeout_secs: Optional[int] = Field(
        default=300,
        title="Timeout (seconds)",
        description="Timeout in seconds (max 300 for sync runs)",
    )


# ============================================================================
# Actor Run Operations
# ============================================================================


class ApifyListActorRunsConfig(BaseModel):
    """List runs for a specific Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_actor_runs"] = Field(
        default="list_actor_runs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "List Actor Runs",
        },
        title="List Actor Runs",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum number of records to return"
    )
    status: Optional[
        Literal[
            "READY",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "TIMING-OUT",
            "TIMED-OUT",
            "ABORTING",
            "ABORTED",
        ]
    ] = Field(default=None, title="Status", description="Filter by run status")


class ApifyGetRunConfig(BaseModel):
    """Get details of a specific Actor run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_run"] = Field(
        default="get_actor_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Run",
        },
        title="Get Actor Run",
    )
    run_id: str = Field(..., title="Run ID", description="The ID of the Actor run")
    wait_for_finish: Optional[int] = Field(
        default=None,
        title="Wait for Finish (seconds)",
        description="Wait up to this many seconds for run to finish (max 300)",
    )


class ApifyGetRunLastConfig(BaseModel):
    """Get the last run of an Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_last_run"] = Field(
        default="get_actor_last_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Last Run",
        },
        title="Get Actor Last Run",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    status: Optional[Literal["SUCCEEDED", "FAILED"]] = Field(
        default=None, title="Status Filter", description="Filter by last run status"
    )


class ApifyAbortRunConfig(BaseModel):
    """Abort a running Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["abort_actor_run"] = Field(
        default="abort_actor_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Abort Actor Run",
        },
        title="Abort Actor Run",
    )
    run_id: str = Field(
        ..., title="Run ID", description="The ID of the Actor run to abort"
    )
    gracefully: Optional[bool] = Field(
        default=True,
        title="Gracefully",
        description="If true, Actor will have some time to finish current task",
    )


class ApifyResurrectRunConfig(BaseModel):
    """Resurrect a finished Actor run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["resurrect_actor_run"] = Field(
        default="resurrect_actor_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Resurrect Actor Run",
        },
        title="Resurrect Actor Run",
    )
    run_id: str = Field(
        ..., title="Run ID", description="The ID of the Actor run to resurrect"
    )


class ApifyGetRunLogConfig(BaseModel):
    """Get the log of an Actor run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_run_log"] = Field(
        default="get_actor_run_log",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Run Log",
        },
        title="Get Actor Run Log",
    )
    run_id: str = Field(..., title="Run ID", description="The ID of the Actor run")


# ============================================================================
# Actor Task Operations
# ============================================================================


class ApifyListTasksConfig(BaseModel):
    """List Actor Tasks"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_actor_tasks"] = Field(
        default="list_actor_tasks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "List Actor Tasks",
        },
        title="List Actor Tasks",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of records to return (max 1000)",
    )


class ApifyGetTaskConfig(BaseModel):
    """Get details of a specific Actor Task"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_task"] = Field(
        default="get_actor_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Task",
        },
        title="Get Actor Task",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name"
    )


class ApifyRunTaskConfig(BaseModel):
    """Run an Actor Task asynchronously"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["run_actor_task_asynchronously"] = Field(
        default="run_actor_task_asynchronously",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Run Actor Task Asynchronously",
        },
        title="Run Actor Task Asynchronously",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name to run"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input Override (JSON)",
        description="JSON input to override task defaults",
        json_schema_extra={"ui:widget": "textarea"},
    )
    memory_mbytes: Optional[int] = Field(
        default=None,
        title="Memory (MB)",
        description="Memory limit override in megabytes",
    )
    timeout_secs: Optional[int] = Field(
        default=None,
        title="Timeout (seconds)",
        description="Timeout override in seconds",
    )


class ApifyRunTaskSyncConfig(BaseModel):
    """Run an Actor Task synchronously and wait for results"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["run_actor_task_synchronously"] = Field(
        default="run_actor_task_synchronously",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Run Actor Task Synchronously",
        },
        title="Run Actor Task Synchronously",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name to run"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input Override (JSON)",
        description="JSON input to override task defaults",
        json_schema_extra={"ui:widget": "textarea"},
    )
    timeout_secs: Optional[int] = Field(
        default=300,
        title="Timeout (seconds)",
        description="Timeout in seconds (max 300 for sync runs)",
    )


class ApifyListTaskRunsConfig(BaseModel):
    """List runs for a specific Task"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_task_runs"] = Field(
        default="list_task_runs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "List Task Runs",
        },
        title="List Task Runs",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name"
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum number of records to return"
    )


class ApifyGetTaskLastRunConfig(BaseModel):
    """Get the last run of a Task"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_task_last_run"] = Field(
        default="get_task_last_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Get Task Last Run",
        },
        title="Get Task Last Run",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name"
    )
    status: Optional[Literal["SUCCEEDED", "FAILED"]] = Field(
        default=None, title="Status Filter", description="Filter by last run status"
    )


# ============================================================================
# Dataset Operations
# ============================================================================


class ApifyListDatasetsConfig(BaseModel):
    """List datasets"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_datasets"] = Field(
        default="list_datasets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "List Datasets",
        },
        title="List Datasets",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of records to return (max 1000)",
    )
    unnamed: Optional[bool] = Field(
        default=None, title="Include Unnamed", description="Include unnamed datasets"
    )


class ApifyGetDatasetConfig(BaseModel):
    """Get dataset metadata"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_dataset"] = Field(
        default="get_dataset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "Get Dataset",
        },
        title="Get Dataset",
    )
    dataset_id: str = Field(
        ..., title="Dataset ID", description="Dataset ID or username~dataset-name"
    )


class ApifyGetDatasetItemsConfig(BaseModel):
    """Get items from a dataset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_dataset_items"] = Field(
        default="get_dataset_items",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "Get Dataset Items",
        },
        title="Get Dataset Items",
    )
    dataset_id: str = Field(
        ..., title="Dataset ID", description="Dataset ID or username~dataset-name"
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of items to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of items to return (max 250000)",
    )
    clean: Optional[bool] = Field(
        default=False,
        title="Clean",
        description="Return only non-empty items without hidden fields",
    )
    fields: Optional[str] = Field(
        default=None,
        title="Fields",
        description="Comma-separated list of fields to include",
    )


class ApifyCreateDatasetConfig(BaseModel):
    """Create a named dataset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_dataset"] = Field(
        default="create_dataset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "Create Dataset",
        },
        title="Create Dataset",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Name for the dataset (only lowercase letters, numbers, dashes)",
    )


class ApifyPushDatasetItemsConfig(BaseModel):
    """Push items to a dataset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["push_items_to_dataset"] = Field(
        default="push_items_to_dataset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "Push Items to Dataset",
        },
        title="Push Items to Dataset",
    )
    dataset_id: str = Field(
        ..., title="Dataset ID", description="Dataset ID or username~dataset-name"
    )
    items: str = Field(
        ...,
        title="Items (JSON)",
        description="JSON array of items to push",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyDeleteDatasetConfig(BaseModel):
    """Delete a dataset"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_dataset"] = Field(
        default="delete_dataset",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "Delete Dataset",
        },
        title="Delete Dataset",
    )
    dataset_id: str = Field(
        ..., title="Dataset ID", description="Dataset ID or username~dataset-name"
    )


# ============================================================================
# Key-Value Store Operations
# ============================================================================


class ApifyListKeyValueStoresConfig(BaseModel):
    """List key-value stores"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_key_value_stores"] = Field(
        default="list_key_value_stores",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "List Key Value Stores",
        },
        title="List Key Value Stores",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of records to return (max 1000)",
    )
    unnamed: Optional[bool] = Field(
        default=None, title="Include Unnamed", description="Include unnamed stores"
    )


class ApifyGetKeyValueStoreConfig(BaseModel):
    """Get key-value store metadata"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_key_value_store"] = Field(
        default="get_key_value_store",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "Get Key Value Store",
        },
        title="Get Key Value Store",
    )
    store_id: str = Field(
        ..., title="Store ID", description="Store ID or username~store-name"
    )


class ApifyListKeysConfig(BaseModel):
    """List keys in a key-value store"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_key_value_store_keys"] = Field(
        default="list_key_value_store_keys",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "List Key Value Store Keys",
        },
        title="List Key Value Store Keys",
    )
    store_id: str = Field(
        ..., title="Store ID", description="Store ID or username~store-name"
    )
    exclusive_start_key: Optional[str] = Field(
        default=None,
        title="Start After Key",
        description="Start listing after this key (for pagination)",
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of keys to return (max 1000)",
    )


class ApifyGetRecordConfig(BaseModel):
    """Get a record from a key-value store"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_key_value_record"] = Field(
        default="get_key_value_record",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "Get Key Value Record",
        },
        title="Get Key Value Record",
    )
    store_id: str = Field(
        ..., title="Store ID", description="Store ID or username~store-name"
    )
    key: str = Field(..., title="Key", description="The record key")


class ApifyPutRecordConfig(BaseModel):
    """Put a record in a key-value store"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["put_key_value_record"] = Field(
        default="put_key_value_record",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "Put Key Value Record",
        },
        title="Put Key Value Record",
    )
    store_id: str = Field(
        ..., title="Store ID", description="Store ID or username~store-name"
    )
    key: str = Field(..., title="Key", description="The record key")
    value: str = Field(
        ...,
        title="Value (JSON)",
        description="JSON value to store",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_type: Optional[str] = Field(
        default="application/json",
        title="Content Type",
        description="MIME type of the record",
    )


class ApifyDeleteRecordConfig(BaseModel):
    """Delete a record from a key-value store"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_key_value_record"] = Field(
        default="delete_key_value_record",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "Delete Key Value Record",
        },
        title="Delete Key Value Record",
    )
    store_id: str = Field(
        ..., title="Store ID", description="Store ID or username~store-name"
    )
    key: str = Field(..., title="Key", description="The record key to delete")


class ApifyCreateKeyValueStoreConfig(BaseModel):
    """Create a named key-value store"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_key_value_store"] = Field(
        default="create_key_value_store",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "Create Key Value Store",
        },
        title="Create Key Value Store",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Name for the store (only lowercase letters, numbers, dashes)",
    )


class ApifyDeleteKeyValueStoreConfig(BaseModel):
    """Delete a key-value store"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_key_value_store"] = Field(
        default="delete_key_value_store",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Key-Value Store",
            "x-is-trigger": False,
            "x-display-name": "Delete Key Value Store",
        },
        title="Delete Key Value Store",
    )
    store_id: str = Field(
        ..., title="Store ID", description="Store ID or username~store-name"
    )


# ============================================================================
# Schedule Operations
# ============================================================================


class ApifyListSchedulesConfig(BaseModel):
    """List schedules"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_schedules"] = Field(
        default="list_schedules",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Schedule",
            "x-is-trigger": False,
            "x-display-name": "List Schedules",
        },
        title="List Schedules",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of records to return (max 1000)",
    )


class ApifyGetScheduleConfig(BaseModel):
    """Get schedule details"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_schedule"] = Field(
        default="get_schedule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Schedule",
            "x-is-trigger": False,
            "x-display-name": "Get Schedule",
        },
        title="Get Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID", description="The schedule ID")


class ApifyCreateScheduleConfig(BaseModel):
    """Create a new schedule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_schedule"] = Field(
        default="create_schedule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Schedule",
            "x-is-trigger": False,
            "x-display-name": "Create Schedule",
        },
        title="Create Schedule",
    )
    name: str = Field(..., title="Name", description="Schedule name")
    cron_expression: str = Field(
        ...,
        title="Cron Expression",
        description="Cron expression for schedule timing (e.g., '0 0 * * *' for daily at midnight)",
    )
    is_enabled: Optional[bool] = Field(
        default=True, title="Enabled", description="Whether the schedule is active"
    )
    is_exclusive: Optional[bool] = Field(
        default=False,
        title="Exclusive",
        description="Don't start new run if previous is still running",
    )
    timezone: Optional[str] = Field(
        default="UTC",
        title="Timezone",
        description="Timezone for the cron expression (e.g., 'America/New_York')",
    )
    actions: str = Field(
        ...,
        title="Actions (JSON)",
        description="JSON array of actions (type: RUN_ACTOR or RUN_ACTOR_TASK, actorId/actorTaskId required)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyUpdateScheduleConfig(BaseModel):
    """Update an existing schedule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_schedule"] = Field(
        default="update_schedule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Schedule",
            "x-is-trigger": False,
            "x-display-name": "Update Schedule",
        },
        title="Update Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID", description="The schedule ID")
    name: Optional[str] = Field(
        default=None, title="Name", description="New schedule name"
    )
    cron_expression: Optional[str] = Field(
        default=None, title="Cron Expression", description="New cron expression"
    )
    is_enabled: Optional[bool] = Field(
        default=None, title="Enabled", description="Enable or disable the schedule"
    )
    timezone: Optional[str] = Field(
        default=None, title="Timezone", description="New timezone"
    )


class ApifyDeleteScheduleConfig(BaseModel):
    """Delete a schedule"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_schedule"] = Field(
        default="delete_schedule",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Schedule",
            "x-is-trigger": False,
            "x-display-name": "Delete Schedule",
        },
        title="Delete Schedule",
    )
    schedule_id: str = Field(
        ..., title="Schedule ID", description="The schedule ID to delete"
    )


# ============================================================================
# Webhook Operations
# ============================================================================


class ApifyListWebhooksConfig(BaseModel):
    """List webhooks"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_webhooks"] = Field(
        default="list_webhooks",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum number of records to return"
    )


class ApifyGetWebhookConfig(BaseModel):
    """Get webhook details"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_webhook"] = Field(
        default="get_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook",
        },
        title="Get Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook ID")


class ApifyCreateWebhookConfig(BaseModel):
    """Create a new webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_webhook"] = Field(
        default="create_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    event_types: List[
        Literal[
            "ACTOR.RUN.CREATED",
            "ACTOR.RUN.SUCCEEDED",
            "ACTOR.RUN.FAILED",
            "ACTOR.RUN.TIMED_OUT",
            "ACTOR.RUN.ABORTED",
            "ACTOR.RUN.RESURRECTED",
        ]
    ] = Field(..., title="Event Types", description="Events that trigger the webhook")
    request_url: str = Field(
        ..., title="Request URL", description="URL to send webhook requests to"
    )
    condition: Optional[str] = Field(
        default=None,
        title="Condition (JSON)",
        description='JSON condition for filtering (e.g., {"actorId": "xxx"})',
        json_schema_extra={"ui:widget": "textarea"},
    )
    is_ad_hoc: Optional[bool] = Field(
        default=False,
        title="Ad Hoc",
        description="Whether this is an ad-hoc webhook (auto-deleted after triggering)",
    )


class ApifyUpdateWebhookConfig(BaseModel):
    """Update an existing webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_webhook"] = Field(
        default="update_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook",
        },
        title="Update Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook ID")
    event_types: Optional[List[str]] = Field(
        default=None, title="Event Types", description="New event types"
    )
    request_url: Optional[str] = Field(
        default=None, title="Request URL", description="New request URL"
    )
    is_ad_hoc: Optional[bool] = Field(
        default=None, title="Ad Hoc", description="Update ad-hoc setting"
    )


class ApifyDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_webhook"] = Field(
        default="delete_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The webhook ID to delete"
    )


class ApifyTestWebhookConfig(BaseModel):
    """Test a webhook by sending a sample request"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["test_webhook"] = Field(
        default="test_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Test Webhook",
        },
        title="Test Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The webhook ID to test"
    )


# ============================================================================
# User Operations
# ============================================================================


class ApifyGetUserConfig(BaseModel):
    """Get current user information"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_current_user"] = Field(
        default="get_current_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class ApifyGetPublicUserConfig(BaseModel):
    """Get public information about a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_public_user_info"] = Field(
        default="get_public_user_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Public User Info",
        },
        title="Get Public User Info",
    )
    user_id: str = Field(..., title="User ID", description="User ID or username")


class ApifyGetUserLimitsConfig(BaseModel):
    """Get account limits and current usage"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_account_limits_and_usage"] = Field(
        default="get_account_limits_and_usage",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Account Limits and Usage",
        },
        title="Get Account Limits and Usage",
    )


class ApifyUpdateUserLimitsConfig(BaseModel):
    """Update account limits"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_account_limits"] = Field(
        default="update_account_limits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Update Account Limits",
        },
        title="Update Account Limits",
    )
    user_id: str = Field(
        ..., title="User ID", description="The user ID to update limits for"
    )
    max_monthly_usage_usd: Optional[float] = Field(
        default=None,
        title="Max Monthly Usage (USD)",
        description="Maximum monthly usage in USD",
    )
    max_actors_per_user: Optional[int] = Field(
        default=None,
        title="Max Actors Per User",
        description="Maximum number of actors per user",
    )


class ApifyGetMonthlyUsageConfig(BaseModel):
    """Get monthly usage statistics"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_monthly_usage_stats"] = Field(
        default="get_monthly_usage_stats",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Monthly Usage Stats",
        },
        title="Get Monthly Usage Stats",
    )


# ============================================================================
# Additional Resource Operations
# ============================================================================


class ApifyGetDatasetStatisticsConfig(BaseModel):
    """Get dataset statistics"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_dataset_statistics"] = Field(
        default="get_dataset_statistics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dataset",
            "x-is-trigger": False,
            "x-display-name": "Get Dataset Statistics",
        },
        title="Get Dataset Statistics",
    )
    dataset_id: str = Field(
        ..., title="Dataset ID", description="Dataset ID or username~dataset-name"
    )


class ApifyGetBuildLogConfig(BaseModel):
    """Get Actor build log"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_build_log"] = Field(
        default="get_actor_build_log",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Build Log",
        },
        title="Get Actor Build Log",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    build_id: str = Field(..., title="Build ID", description="The build ID")


# ============================================================================
# Actor Management Operations (CREATE/UPDATE/DELETE)
# ============================================================================


class ApifyCreateActorConfig(BaseModel):
    """Create a new Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_actor"] = Field(
        default="create_actor",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Create Actor",
        },
        title="Create Actor",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Actor name (lowercase letters, numbers, dashes only)",
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="Display title for the Actor"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Actor description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    versions: Optional[str] = Field(
        default=None,
        title="Versions (JSON)",
        description="JSON array of version configurations",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyUpdateActorConfig(BaseModel):
    """Update an existing Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_actor"] = Field(
        default="update_actor",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Update Actor",
        },
        title="Update Actor",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="New Actor name"
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="New display title"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    is_public: Optional[bool] = Field(
        default=None, title="Public", description="Make Actor public"
    )


class ApifyDeleteActorConfig(BaseModel):
    """Delete an Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_actor"] = Field(
        default="delete_actor",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Delete Actor",
        },
        title="Delete Actor",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name to delete"
    )


# ============================================================================
# Actor Build Operations
# ============================================================================


class ApifyListActorBuildsConfig(BaseModel):
    """List builds for an Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_actor_builds"] = Field(
        default="list_actor_builds",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "List Actor Builds",
        },
        title="List Actor Builds",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum number of records to return"
    )


class ApifyBuildActorConfig(BaseModel):
    """Start a new Actor build"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["start_actor_build"] = Field(
        default="start_actor_build",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Start Actor Build",
        },
        title="Start Actor Build",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name to build"
    )
    version_number: Optional[str] = Field(
        default=None,
        title="Version Number",
        description="Version to build (e.g., '0.1', 'latest')",
    )
    beta_packages: Optional[bool] = Field(
        default=False, title="Beta Packages", description="Use beta NPM packages"
    )
    tag: Optional[str] = Field(
        default=None, title="Build Tag", description="Tag for the build"
    )
    use_cache: Optional[bool] = Field(
        default=True, title="Use Cache", description="Use build cache for faster builds"
    )
    wait_for_finish: Optional[int] = Field(
        default=None,
        title="Wait for Finish (seconds)",
        description="Wait up to this many seconds for build to finish (max 300)",
    )


class ApifyGetActorBuildConfig(BaseModel):
    """Get details of a specific Actor build"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_build"] = Field(
        default="get_actor_build",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Build",
        },
        title="Get Actor Build",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    build_id: str = Field(..., title="Build ID", description="The build ID")
    wait_for_finish: Optional[int] = Field(
        default=None,
        title="Wait for Finish (seconds)",
        description="Wait up to this many seconds for build to finish (max 60)",
    )


class ApifyAbortBuildConfig(BaseModel):
    """Abort a running Actor build"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["abort_actor_build"] = Field(
        default="abort_actor_build",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Abort Actor Build",
        },
        title="Abort Actor Build",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    build_id: str = Field(..., title="Build ID", description="The build ID to abort")


# ============================================================================
# Actor Version Operations
# ============================================================================


class ApifyListActorVersionsConfig(BaseModel):
    """List versions of an Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_actor_versions"] = Field(
        default="list_actor_versions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor Version",
            "x-is-trigger": False,
            "x-display-name": "List Actor Versions",
        },
        title="List Actor Versions",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )


class ApifyGetActorVersionConfig(BaseModel):
    """Get a specific Actor version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_actor_version"] = Field(
        default="get_actor_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor Version",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Version",
        },
        title="Get Actor Version",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number (e.g., '0.1', '1.0')"
    )


class ApifyCreateActorVersionConfig(BaseModel):
    """Create a new Actor version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_actor_version"] = Field(
        default="create_actor_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor Version",
            "x-is-trigger": False,
            "x-display-name": "Create Actor Version",
        },
        title="Create Actor Version",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number (e.g., '0.1', '1.0')"
    )
    build_tag: Optional[str] = Field(
        default="latest", title="Build Tag", description="Build tag to use"
    )
    env_vars: Optional[str] = Field(
        default=None,
        title="Environment Variables (JSON)",
        description="JSON array of environment variables",
        json_schema_extra={"ui:widget": "textarea"},
    )
    apply_env_vars_to_build: Optional[bool] = Field(
        default=False,
        title="Apply Env Vars to Build",
        description="Apply environment variables to the build process",
    )
    source_type: Optional[
        Literal["SOURCE_FILES", "GIT_REPO", "TARBALL", "GITHUB_GIST"]
    ] = Field(
        default="SOURCE_FILES", title="Source Type", description="Type of source code"
    )


class ApifyUpdateActorVersionConfig(BaseModel):
    """Update an existing Actor version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_actor_version"] = Field(
        default="update_actor_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor Version",
            "x-is-trigger": False,
            "x-display-name": "Update Actor Version",
        },
        title="Update Actor Version",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number to update"
    )
    build_tag: Optional[str] = Field(
        default=None, title="Build Tag", description="New build tag"
    )
    env_vars: Optional[str] = Field(
        default=None,
        title="Environment Variables (JSON)",
        description="JSON array of environment variables",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyDeleteActorVersionConfig(BaseModel):
    """Delete an Actor version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_actor_version"] = Field(
        default="delete_actor_version",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor Version",
            "x-is-trigger": False,
            "x-display-name": "Delete Actor Version",
        },
        title="Delete Actor Version",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number to delete"
    )


# ============================================================================
# Environment Variables Operations
# ============================================================================


class ApifyListEnvVarsConfig(BaseModel):
    """List environment variables for an Actor version"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_environment_variables"] = Field(
        default="list_environment_variables",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Variable",
            "x-is-trigger": False,
            "x-display-name": "List Environment Variables",
        },
        title="List Environment Variables",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number (e.g., '0.1', '1.0')"
    )


class ApifyGetEnvVarConfig(BaseModel):
    """Get a specific environment variable"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_environment_variable"] = Field(
        default="get_environment_variable",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Variable",
            "x-is-trigger": False,
            "x-display-name": "Get Environment Variable",
        },
        title="Get Environment Variable",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number"
    )
    env_var_name: str = Field(
        ..., title="Variable Name", description="Environment variable name"
    )


class ApifyCreateEnvVarConfig(BaseModel):
    """Create a new environment variable"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_environment_variable"] = Field(
        default="create_environment_variable",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Variable",
            "x-is-trigger": False,
            "x-display-name": "Create Environment Variable",
        },
        title="Create Environment Variable",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number"
    )
    name: str = Field(
        ..., title="Variable Name", description="Environment variable name"
    )
    value: str = Field(..., title="Value", description="Variable value")
    is_secret: Optional[bool] = Field(
        default=False,
        title="Is Secret",
        description="Whether the variable is secret (will be encrypted)",
    )


class ApifyUpdateEnvVarConfig(BaseModel):
    """Update an environment variable"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_environment_variable"] = Field(
        default="update_environment_variable",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Variable",
            "x-is-trigger": False,
            "x-display-name": "Update Environment Variable",
        },
        title="Update Environment Variable",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number"
    )
    env_var_name: str = Field(
        ..., title="Variable Name", description="Environment variable name"
    )
    value: Optional[str] = Field(
        default=None, title="Value", description="New variable value"
    )
    is_secret: Optional[bool] = Field(
        default=None, title="Is Secret", description="Whether the variable is secret"
    )


class ApifyDeleteEnvVarConfig(BaseModel):
    """Delete an environment variable"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_environment_variable"] = Field(
        default="delete_environment_variable",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Environment Variable",
            "x-is-trigger": False,
            "x-display-name": "Delete Environment Variable",
        },
        title="Delete Environment Variable",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    version_number: str = Field(
        ..., title="Version Number", description="Version number"
    )
    env_var_name: str = Field(
        ..., title="Variable Name", description="Environment variable name to delete"
    )


# ============================================================================
# Extended Actor Run Operations
# ============================================================================


class ApifyMetamorphoseRunConfig(BaseModel):
    """Metamorphose (transform) an Actor run into another Actor"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["metamorphose_actor_run"] = Field(
        default="metamorphose_actor_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Metamorphose Actor Run",
        },
        title="Metamorphose Actor Run",
    )
    run_id: str = Field(
        ..., title="Run ID", description="The ID of the Actor run to metamorphose"
    )
    target_actor_id: str = Field(
        ..., title="Target Actor ID", description="Actor ID to transform into"
    )
    target_actor_build: Optional[str] = Field(
        default=None,
        title="Target Actor Build",
        description="Build tag or ID of target Actor",
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input (JSON)",
        description="JSON input for the target Actor",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyRebootRunConfig(BaseModel):
    """Reboot an Actor run"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["reboot_actor_run"] = Field(
        default="reboot_actor_run",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Actor",
            "x-is-trigger": False,
            "x-display-name": "Reboot Actor Run",
        },
        title="Reboot Actor Run",
    )
    run_id: str = Field(
        ..., title="Run ID", description="The ID of the Actor run to reboot"
    )


# ============================================================================
# Task Management Operations (CREATE/UPDATE/DELETE)
# ============================================================================


class ApifyCreateTaskConfig(BaseModel):
    """Create a new Actor Task"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_actor_task"] = Field(
        default="create_actor_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Create Actor Task",
        },
        title="Create Actor Task",
    )
    actor_id: str = Field(
        ..., title="Actor ID", description="Actor ID or username~actor-name"
    )
    name: str = Field(
        ...,
        title="Task Name",
        description="Name for the task (lowercase letters, numbers, dashes)",
    )
    title: Optional[str] = Field(
        default=None, title="Task Title", description="Display title for the task"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input (JSON)",
        description="JSON input for the task",
        json_schema_extra={"ui:widget": "textarea"},
    )
    memory_mbytes: Optional[int] = Field(
        default=None, title="Memory (MB)", description="Memory limit in megabytes"
    )
    timeout_secs: Optional[int] = Field(
        default=None, title="Timeout (seconds)", description="Timeout in seconds"
    )


class ApifyUpdateTaskConfig(BaseModel):
    """Update an existing Actor Task"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_actor_task"] = Field(
        default="update_actor_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Update Actor Task",
        },
        title="Update Actor Task",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name"
    )
    name: Optional[str] = Field(
        default=None, title="Task Name", description="New task name"
    )
    title: Optional[str] = Field(
        default=None, title="Task Title", description="New display title"
    )
    input_body: Optional[str] = Field(
        default=None,
        title="Input (JSON)",
        description="JSON input for the task",
        json_schema_extra={"ui:widget": "textarea"},
    )
    memory_mbytes: Optional[int] = Field(
        default=None, title="Memory (MB)", description="Memory limit in megabytes"
    )
    timeout_secs: Optional[int] = Field(
        default=None, title="Timeout (seconds)", description="Timeout in seconds"
    )


class ApifyDeleteTaskConfig(BaseModel):
    """Delete an Actor Task"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_actor_task"] = Field(
        default="delete_actor_task",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Task",
            "x-is-trigger": False,
            "x-display-name": "Delete Actor Task",
        },
        title="Delete Actor Task",
    )
    task_id: str = Field(
        ..., title="Task ID", description="Task ID or username~task-name to delete"
    )


# ============================================================================
# Request Queue Management Operations
# ============================================================================


class ApifyCreateRequestQueueConfig(BaseModel):
    """Create a named request queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_request_queue"] = Field(
        default="create_request_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Create Request Queue",
        },
        title="Create Request Queue",
    )
    name: str = Field(
        ...,
        title="Name",
        description="Name for the queue (lowercase letters, numbers, dashes)",
    )


class ApifyDeleteRequestQueueConfig(BaseModel):
    """Delete a request queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_request_queue"] = Field(
        default="delete_request_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Delete Request Queue",
        },
        title="Delete Request Queue",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )


class ApifyListQueueRequestsConfig(BaseModel):
    """List requests in a queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_queue_requests"] = Field(
        default="list_queue_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "List Queue Requests",
        },
        title="List Queue Requests",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum number of records to return"
    )


class ApifyAddQueueRequestConfig(BaseModel):
    """Add a request to a queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_request_to_queue"] = Field(
        default="add_request_to_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Add Request to Queue",
        },
        title="Add Request to Queue",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )
    url: str = Field(..., title="URL", description="Request URL")
    unique_key: Optional[str] = Field(
        default=None,
        title="Unique Key",
        description="Unique identifier for deduplication",
    )
    method: Optional[Literal["GET", "POST", "PUT", "DELETE", "PATCH"]] = Field(
        default="GET", title="HTTP Method", description="HTTP method for the request"
    )
    user_data: Optional[str] = Field(
        default=None,
        title="User Data (JSON)",
        description="Custom JSON data associated with the request",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyGetQueueRequestConfig(BaseModel):
    """Get a specific request from a queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_request_from_queue"] = Field(
        default="get_request_from_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Get Request from Queue",
        },
        title="Get Request from Queue",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )
    request_id: str = Field(..., title="Request ID", description="The request ID")


class ApifyUpdateQueueRequestConfig(BaseModel):
    """Update a request in a queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_request_in_queue"] = Field(
        default="update_request_in_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Update Request in Queue",
        },
        title="Update Request in Queue",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )
    request_id: str = Field(..., title="Request ID", description="The request ID")
    user_data: Optional[str] = Field(
        default=None,
        title="User Data (JSON)",
        description="Updated custom JSON data",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ApifyDeleteQueueRequestConfig(BaseModel):
    """Delete a request from a queue"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_request_from_queue"] = Field(
        default="delete_request_from_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Delete Request from Queue",
        },
        title="Delete Request from Queue",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )
    request_id: str = Field(
        ..., title="Request ID", description="The request ID to delete"
    )


# ============================================================================
# Webhook Dispatch Operations
# ============================================================================


class ApifyListWebhookDispatchesConfig(BaseModel):
    """List webhook dispatch history"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_webhook_dispatches"] = Field(
        default="list_webhook_dispatches",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhook Dispatches",
        },
        title="List Webhook Dispatches",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook ID")
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100, title="Limit", description="Maximum number of records to return"
    )


class ApifyGetWebhookDispatchConfig(BaseModel):
    """Get details of a specific webhook dispatch"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_webhook_dispatch"] = Field(
        default="get_webhook_dispatch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook Dispatch",
        },
        title="Get Webhook Dispatch",
    )
    dispatch_id: str = Field(
        ..., title="Dispatch ID", description="The webhook dispatch ID"
    )


# ============================================================================
# Request Queue Operations
# ============================================================================


class ApifyListRequestQueuesConfig(BaseModel):
    """List request queues"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_request_queues"] = Field(
        default="list_request_queues",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "List Request Queues",
        },
        title="List Request Queues",
    )
    offset: Optional[int] = Field(
        default=0, title="Offset", description="Number of records to skip"
    )
    limit: Optional[int] = Field(
        default=100,
        title="Limit",
        description="Maximum number of records to return (max 1000)",
    )
    unnamed: Optional[bool] = Field(
        default=None, title="Include Unnamed", description="Include unnamed queues"
    )


class ApifyGetRequestQueueConfig(BaseModel):
    """Get request queue metadata"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_request_queue"] = Field(
        default="get_request_queue",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Request Queue",
            "x-is-trigger": False,
            "x-display-name": "Get Request Queue",
        },
        title="Get Request Queue",
    )
    queue_id: str = Field(
        ..., title="Queue ID", description="Queue ID or username~queue-name"
    )


# ============================================================================
# Discriminated Union for All Configs
# ============================================================================

ApifyConfig = Annotated[
    Union[
        # Actor operations
        ApifyListActorsConfig,
        ApifyGetActorConfig,
        ApifyRunActorConfig,
        ApifyRunActorSyncConfig,
        ApifyRunActorSyncGetDatasetItemsConfig,
        ApifyCreateActorConfig,
        ApifyUpdateActorConfig,
        ApifyDeleteActorConfig,
        # Actor build operations
        ApifyListActorBuildsConfig,
        ApifyBuildActorConfig,
        ApifyGetActorBuildConfig,
        ApifyAbortBuildConfig,
        # Actor version operations
        ApifyListActorVersionsConfig,
        ApifyGetActorVersionConfig,
        ApifyCreateActorVersionConfig,
        ApifyUpdateActorVersionConfig,
        ApifyDeleteActorVersionConfig,
        # Environment variables operations
        ApifyListEnvVarsConfig,
        ApifyGetEnvVarConfig,
        ApifyCreateEnvVarConfig,
        ApifyUpdateEnvVarConfig,
        ApifyDeleteEnvVarConfig,
        # Actor run operations
        ApifyListActorRunsConfig,
        ApifyGetRunConfig,
        ApifyGetRunLastConfig,
        ApifyAbortRunConfig,
        ApifyResurrectRunConfig,
        ApifyGetRunLogConfig,
        ApifyMetamorphoseRunConfig,
        ApifyRebootRunConfig,
        # Actor task operations
        ApifyListTasksConfig,
        ApifyGetTaskConfig,
        ApifyRunTaskConfig,
        ApifyRunTaskSyncConfig,
        ApifyListTaskRunsConfig,
        ApifyGetTaskLastRunConfig,
        ApifyCreateTaskConfig,
        ApifyUpdateTaskConfig,
        ApifyDeleteTaskConfig,
        # Dataset operations
        ApifyListDatasetsConfig,
        ApifyGetDatasetConfig,
        ApifyGetDatasetItemsConfig,
        ApifyCreateDatasetConfig,
        ApifyPushDatasetItemsConfig,
        ApifyDeleteDatasetConfig,
        # Key-value store operations
        ApifyListKeyValueStoresConfig,
        ApifyGetKeyValueStoreConfig,
        ApifyListKeysConfig,
        ApifyGetRecordConfig,
        ApifyPutRecordConfig,
        ApifyDeleteRecordConfig,
        ApifyCreateKeyValueStoreConfig,
        ApifyDeleteKeyValueStoreConfig,
        # Schedule operations
        ApifyListSchedulesConfig,
        ApifyGetScheduleConfig,
        ApifyCreateScheduleConfig,
        ApifyUpdateScheduleConfig,
        ApifyDeleteScheduleConfig,
        # Webhook operations
        ApifyListWebhooksConfig,
        ApifyGetWebhookConfig,
        ApifyCreateWebhookConfig,
        ApifyUpdateWebhookConfig,
        ApifyDeleteWebhookConfig,
        ApifyTestWebhookConfig,
        ApifyListWebhookDispatchesConfig,
        ApifyGetWebhookDispatchConfig,
        # User operations
        ApifyGetUserConfig,
        ApifyGetPublicUserConfig,
        ApifyGetUserLimitsConfig,
        ApifyUpdateUserLimitsConfig,
        ApifyGetMonthlyUsageConfig,
        # Additional resource operations
        ApifyGetDatasetStatisticsConfig,
        ApifyGetBuildLogConfig,
        # Request queue operations
        ApifyListRequestQueuesConfig,
        ApifyGetRequestQueueConfig,
        ApifyCreateRequestQueueConfig,
        ApifyDeleteRequestQueueConfig,
        ApifyListQueueRequestsConfig,
        ApifyAddQueueRequestConfig,
        ApifyGetQueueRequestConfig,
        ApifyUpdateQueueRequestConfig,
        ApifyDeleteQueueRequestConfig,
    ],
    Discriminator("operation"),
]


class ApifyNodeConfig(NodeConfig[ApifyConfig, ApifyCredential]):
    """Full configuration for Apify node including credentials"""

    pass


# ============================================================================
# Apify Node Implementation
# ============================================================================


class ApifyNode(WorkflowNode):
    """
    Apify REST API automation node.

    Executes Apify operations via direct REST API calls for optimal performance.
    Supports multiple actions - user selects one in the config.
    """

    edit_examples = [
        "Run a web scraper actor and wait for results with a timeout",
        "List all available actors in my account with pagination",
        "Create a new dataset and push items from a scraping run",
        "Run a scheduled task at specific times and get job status",
        "Get items from a dataset and filter by price range",
        "Create a webhook to notify on actor run completion",
        "Build an actor to crawl competitor prices daily",
    ]

    @classmethod
    def get_config_model(cls):
        return ApifyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Apify action via REST API."""
        logger.info(f"[ApifyNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, ApifyNodeConfig):
            raise ValueError("ApifyNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[ApifyNode] Credentials are required. "
                "Please add your API token in the node's credentials tab."
            )

        # Route to appropriate handler based on config type
        action_handlers = {
            # Actor operations
            ApifyListActorsConfig: self._list_actors,
            ApifyGetActorConfig: self._get_actor,
            ApifyRunActorConfig: self._run_actor,
            ApifyRunActorSyncConfig: self._run_actor_sync,
            ApifyRunActorSyncGetDatasetItemsConfig: self._run_actor_sync_get_dataset_items,
            ApifyCreateActorConfig: self._create_actor,
            ApifyUpdateActorConfig: self._update_actor,
            ApifyDeleteActorConfig: self._delete_actor,
            # Actor build operations
            ApifyListActorBuildsConfig: self._list_actor_builds,
            ApifyBuildActorConfig: self._build_actor,
            ApifyGetActorBuildConfig: self._get_actor_build,
            ApifyAbortBuildConfig: self._abort_build,
            # Actor version operations
            ApifyListActorVersionsConfig: self._list_actor_versions,
            ApifyGetActorVersionConfig: self._get_actor_version,
            ApifyCreateActorVersionConfig: self._create_actor_version,
            ApifyUpdateActorVersionConfig: self._update_actor_version,
            ApifyDeleteActorVersionConfig: self._delete_actor_version,
            # Environment variables operations
            ApifyListEnvVarsConfig: self._list_env_vars,
            ApifyGetEnvVarConfig: self._get_env_var,
            ApifyCreateEnvVarConfig: self._create_env_var,
            ApifyUpdateEnvVarConfig: self._update_env_var,
            ApifyDeleteEnvVarConfig: self._delete_env_var,
            # Actor run operations
            ApifyListActorRunsConfig: self._list_actor_runs,
            ApifyGetRunConfig: self._get_run,
            ApifyGetRunLastConfig: self._get_run_last,
            ApifyAbortRunConfig: self._abort_run,
            ApifyResurrectRunConfig: self._resurrect_run,
            ApifyGetRunLogConfig: self._get_run_log,
            ApifyMetamorphoseRunConfig: self._metamorphose_run,
            ApifyRebootRunConfig: self._reboot_run,
            # Actor task operations
            ApifyListTasksConfig: self._list_tasks,
            ApifyGetTaskConfig: self._get_task,
            ApifyRunTaskConfig: self._run_task,
            ApifyRunTaskSyncConfig: self._run_task_sync,
            ApifyListTaskRunsConfig: self._list_task_runs,
            ApifyGetTaskLastRunConfig: self._get_task_last_run,
            ApifyCreateTaskConfig: self._create_task,
            ApifyUpdateTaskConfig: self._update_task,
            ApifyDeleteTaskConfig: self._delete_task,
            # Dataset operations
            ApifyListDatasetsConfig: self._list_datasets,
            ApifyGetDatasetConfig: self._get_dataset,
            ApifyGetDatasetItemsConfig: self._get_dataset_items,
            ApifyCreateDatasetConfig: self._create_dataset,
            ApifyPushDatasetItemsConfig: self._push_dataset_items,
            ApifyDeleteDatasetConfig: self._delete_dataset,
            # Key-value store operations
            ApifyListKeyValueStoresConfig: self._list_key_value_stores,
            ApifyGetKeyValueStoreConfig: self._get_key_value_store,
            ApifyListKeysConfig: self._list_keys,
            ApifyGetRecordConfig: self._get_record,
            ApifyPutRecordConfig: self._put_record,
            ApifyDeleteRecordConfig: self._delete_record,
            ApifyCreateKeyValueStoreConfig: self._create_key_value_store,
            ApifyDeleteKeyValueStoreConfig: self._delete_key_value_store,
            # Schedule operations
            ApifyListSchedulesConfig: self._list_schedules,
            ApifyGetScheduleConfig: self._get_schedule,
            ApifyCreateScheduleConfig: self._create_schedule,
            ApifyUpdateScheduleConfig: self._update_schedule,
            ApifyDeleteScheduleConfig: self._delete_schedule,
            # Webhook operations
            ApifyListWebhooksConfig: self._list_webhooks,
            ApifyGetWebhookConfig: self._get_webhook,
            ApifyCreateWebhookConfig: self._create_webhook,
            ApifyUpdateWebhookConfig: self._update_webhook,
            ApifyDeleteWebhookConfig: self._delete_webhook,
            ApifyTestWebhookConfig: self._test_webhook,
            ApifyListWebhookDispatchesConfig: self._list_webhook_dispatches,
            ApifyGetWebhookDispatchConfig: self._get_webhook_dispatch,
            # User operations
            ApifyGetUserConfig: self._get_user,
            ApifyGetPublicUserConfig: self._get_public_user,
            ApifyGetUserLimitsConfig: self._get_user_limits,
            ApifyUpdateUserLimitsConfig: self._update_user_limits,
            ApifyGetMonthlyUsageConfig: self._get_monthly_usage,
            # Additional resource operations
            ApifyGetDatasetStatisticsConfig: self._get_dataset_statistics,
            ApifyGetBuildLogConfig: self._get_build_log,
            # Request queue operations
            ApifyListRequestQueuesConfig: self._list_request_queues,
            ApifyGetRequestQueueConfig: self._get_request_queue,
            ApifyCreateRequestQueueConfig: self._create_request_queue,
            ApifyDeleteRequestQueueConfig: self._delete_request_queue,
            ApifyListQueueRequestsConfig: self._list_queue_requests,
            ApifyAddQueueRequestConfig: self._add_queue_request,
            ApifyGetQueueRequestConfig: self._get_queue_request,
            ApifyUpdateQueueRequestConfig: self._update_queue_request,
            ApifyDeleteQueueRequestConfig: self._delete_queue_request,
        }

        handler = action_handlers.get(type(config))
        if not handler:
            raise ValueError(f"Unknown config type: {type(config)}")

        return await handler(config, credentials)

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: ApifyCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        timeout: float = 30.0,
        raw_body: Optional[str] = None,
        content_type: str = "application/json",
    ) -> Dict[str, Any]:
        """Make an authenticated Apify API request with timing."""
        total_start = time.time()

        headers = {
            "Authorization": f"Bearer {credentials.api_token}",
            "Accept": "application/json",
        }

        if raw_body is not None:
            headers["Content-Type"] = content_type

        url = f"{APIFY_API_BASE}{endpoint}"

        # Filter out None params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            # API request timing
            api_start = time.time()
            logger.info(f"[ApifyNode] 🔌 {method} {endpoint}")

            try:
                if raw_body is not None:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        content=raw_body,
                        timeout=timeout,
                    )
                else:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        json=json_body,
                        timeout=timeout,
                    )
            except httpx.TimeoutException:
                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "apify",
                    "action": action_name,
                    "status": "error",
                    "error": "Request timed out",
                    "status_code": 408,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {"total": round(total_time, 1)},
                }
                await self.emit(output)
                return output

            api_time = (time.time() - api_start) * 1000
            logger.info(
                f"[ApifyNode] ⏱️ API request: {api_time:.1f}ms (status: {response.status_code})"
            )

            # Response parsing timing
            parse_start = time.time()

            if response.status_code >= 400:
                try:
                    error_data = response.json() if response.content else {}
                    error_msg = (
                        error_data.get("error", {}).get("message")
                        or error_data.get("message")
                        or response.text
                    )
                except:
                    error_msg = response.text
                logger.error(f"[ApifyNode] API error: {error_msg}")

                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "apify",
                    "action": action_name,
                    "status": "error",
                    "error": error_msg,
                    "status_code": response.status_code,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {
                        "api_request": round(api_time, 1),
                        "total": round(total_time, 1),
                    },
                }
                await self.emit(output)
                return output

            # Parse successful response
            if response.status_code == 204:
                data = {"success": True}
            else:
                try:
                    data = response.json() if response.content else None
                except:
                    # For non-JSON responses (like logs)
                    data = {"content": response.text}

            parse_time = (time.time() - parse_start) * 1000
            logger.info(f"[ApifyNode] ⏱️ Response parsing: {parse_time:.1f}ms")

            total_time = (time.time() - total_start) * 1000
            logger.info(f"[ApifyNode] ⏱️ TOTAL time: {total_time:.1f}ms")

            output = {
                "type": "apify",
                "action": action_name,
                "status": "success",
                "data": data.get("data", data)
                if isinstance(data, dict) and "data" in data
                else data,
                "timestamp": time.time(),
                "timing_ms": {
                    "api_request": round(api_time, 1),
                    "response_parsing": round(parse_time, 1),
                    "total": round(total_time, 1),
                },
            }

            await self.emit(output)
            return output

    # ============================================================================
    # Actor Operations
    # ============================================================================

    async def _list_actors(
        self, config: ApifyListActorsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List Actors."""
        params = {
            "my": 1 if config.my else None,
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET", "/acts", credentials, params=params, action_name="list_actors"
        )

    async def _get_actor(
        self, config: ApifyGetActorConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get Actor details."""
        return await self._make_request(
            "GET", f"/acts/{config.actor_id}", credentials, action_name="get_actor"
        )

    async def _run_actor(
        self, config: ApifyRunActorConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Run an Actor asynchronously."""
        params = {
            "memory": config.memory_mbytes,
            "timeout": config.timeout_secs,
            "build": config.build,
        }

        json_body = None
        if config.input_body:
            try:
                json_body = json.loads(config.input_body)
            except json.JSONDecodeError:
                return {
                    "type": "apify",
                    "action": "run_actor_asynchronously",
                    "status": "error",
                    "error": "Invalid JSON in input_body",
                    "status_code": 400,
                    "data": None,
                    "timestamp": time.time(),
                }

        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/runs",
            credentials,
            params=params,
            json_body=json_body,
            action_name="run_actor_asynchronously",
        )

    async def _run_actor_sync(
        self, config: ApifyRunActorSyncConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Run an Actor synchronously."""
        params = {
            "memory": config.memory_mbytes,
            "timeout": config.timeout_secs,
        }

        json_body = None
        if config.input_body:
            try:
                json_body = json.loads(config.input_body)
            except json.JSONDecodeError:
                return {
                    "type": "apify",
                    "action": "run_actor_synchronously",
                    "status": "error",
                    "error": "Invalid JSON in input_body",
                    "status_code": 400,
                    "data": None,
                    "timestamp": time.time(),
                }

        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/run-sync",
            credentials,
            params=params,
            json_body=json_body,
            action_name="run_actor_synchronously",
            timeout=max(config.timeout_secs or 300, 300) + 10,
        )

    async def _run_actor_sync_get_dataset_items(
        self,
        config: ApifyRunActorSyncGetDatasetItemsConfig,
        credentials: ApifyCredential,
    ) -> Dict[str, Any]:
        """Run an Actor synchronously and get dataset items."""
        params = {
            "memory": config.memory_mbytes,
            "timeout": config.timeout_secs,
        }

        json_body = None
        if config.input_body:
            try:
                json_body = json.loads(config.input_body)
            except json.JSONDecodeError:
                return {
                    "type": "apify",
                    "action": "run_actor_sync_and_get_dataset_items",
                    "status": "error",
                    "error": "Invalid JSON in input_body",
                    "status_code": 400,
                    "data": None,
                    "timestamp": time.time(),
                }

        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/run-sync-get-dataset-items",
            credentials,
            params=params,
            json_body=json_body,
            action_name="run_actor_sync_and_get_dataset_items",
            timeout=max(config.timeout_secs or 300, 300) + 10,
        )

    # ============================================================================
    # Actor Run Operations
    # ============================================================================

    async def _list_actor_runs(
        self, config: ApifyListActorRunsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List runs for an Actor."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
            "status": config.status,
        }
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/runs",
            credentials,
            params=params,
            action_name="list_actor_runs",
        )

    async def _get_run(
        self, config: ApifyGetRunConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get run details."""
        params = {}
        if config.wait_for_finish:
            params["waitForFinish"] = config.wait_for_finish
        return await self._make_request(
            "GET",
            f"/actor-runs/{config.run_id}",
            credentials,
            params=params if params else None,
            action_name="get_actor_run",
            timeout=max(config.wait_for_finish or 30, 30) + 10,
        )

    async def _get_run_last(
        self, config: ApifyGetRunLastConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get the last run of an Actor."""
        params = {"status": config.status} if config.status else None
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/runs/last",
            credentials,
            params=params,
            action_name="get_actor_last_run",
        )

    async def _abort_run(
        self, config: ApifyAbortRunConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Abort a running Actor."""
        params = {"gracefully": config.gracefully} if config.gracefully else None
        return await self._make_request(
            "POST",
            f"/actor-runs/{config.run_id}/abort",
            credentials,
            params=params,
            action_name="abort_actor_run",
        )

    async def _resurrect_run(
        self, config: ApifyResurrectRunConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Resurrect a finished run."""
        return await self._make_request(
            "POST",
            f"/actor-runs/{config.run_id}/resurrect",
            credentials,
            action_name="resurrect_actor_run",
        )

    async def _get_run_log(
        self, config: ApifyGetRunLogConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get run log."""
        return await self._make_request(
            "GET",
            f"/actor-runs/{config.run_id}/log",
            credentials,
            action_name="get_actor_run_log",
        )

    # ============================================================================
    # Actor Task Operations
    # ============================================================================

    async def _list_tasks(
        self, config: ApifyListTasksConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List Actor Tasks."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET", "/actor-tasks", credentials, params=params, action_name="list_actor_tasks"
        )

    async def _get_task(
        self, config: ApifyGetTaskConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get Task details."""
        return await self._make_request(
            "GET", f"/actor-tasks/{config.task_id}", credentials, action_name="get_actor_task"
        )

    async def _run_task(
        self, config: ApifyRunTaskConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Run a Task asynchronously."""
        params = {
            "memory": config.memory_mbytes,
            "timeout": config.timeout_secs,
        }

        json_body = None
        if config.input_body:
            try:
                json_body = json.loads(config.input_body)
            except json.JSONDecodeError:
                return {
                    "type": "apify",
                    "action": "run_actor_task_asynchronously",
                    "status": "error",
                    "error": "Invalid JSON in input_body",
                    "status_code": 400,
                    "data": None,
                    "timestamp": time.time(),
                }

        return await self._make_request(
            "POST",
            f"/actor-tasks/{config.task_id}/runs",
            credentials,
            params=params,
            json_body=json_body,
            action_name="run_actor_task_asynchronously",
        )

    async def _run_task_sync(
        self, config: ApifyRunTaskSyncConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Run a Task synchronously."""
        params = {
            "timeout": config.timeout_secs,
        }

        json_body = None
        if config.input_body:
            try:
                json_body = json.loads(config.input_body)
            except json.JSONDecodeError:
                return {
                    "type": "apify",
                    "action": "run_actor_task_synchronously",
                    "status": "error",
                    "error": "Invalid JSON in input_body",
                    "status_code": 400,
                    "data": None,
                    "timestamp": time.time(),
                }

        return await self._make_request(
            "POST",
            f"/actor-tasks/{config.task_id}/run-sync",
            credentials,
            params=params,
            json_body=json_body,
            action_name="run_actor_task_synchronously",
            timeout=max(config.timeout_secs or 300, 300) + 10,
        )

    async def _list_task_runs(
        self, config: ApifyListTaskRunsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List runs for a Task."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            f"/actor-tasks/{config.task_id}/runs",
            credentials,
            params=params,
            action_name="list_task_runs",
        )

    async def _get_task_last_run(
        self, config: ApifyGetTaskLastRunConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get the last run of a Task."""
        params = {"status": config.status} if config.status else None
        return await self._make_request(
            "GET",
            f"/actor-tasks/{config.task_id}/runs/last",
            credentials,
            params=params,
            action_name="get_task_last_run",
        )

    # ============================================================================
    # Dataset Operations
    # ============================================================================

    async def _list_datasets(
        self, config: ApifyListDatasetsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List datasets."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
            "unnamed": config.unnamed,
        }
        return await self._make_request(
            "GET", "/datasets", credentials, params=params, action_name="list_datasets"
        )

    async def _get_dataset(
        self, config: ApifyGetDatasetConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get dataset metadata."""
        return await self._make_request(
            "GET",
            f"/datasets/{config.dataset_id}",
            credentials,
            action_name="get_dataset",
        )

    async def _get_dataset_items(
        self, config: ApifyGetDatasetItemsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get items from a dataset."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
            "clean": config.clean,
            "fields": config.fields,
        }
        return await self._make_request(
            "GET",
            f"/datasets/{config.dataset_id}/items",
            credentials,
            params=params,
            action_name="get_dataset_items",
        )

    async def _create_dataset(
        self, config: ApifyCreateDatasetConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a named dataset."""
        params = {"name": config.name}
        return await self._make_request(
            "POST",
            "/datasets",
            credentials,
            params=params,
            action_name="create_dataset",
        )

    async def _push_dataset_items(
        self, config: ApifyPushDatasetItemsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Push items to a dataset."""
        try:
            items = json.loads(config.items)
        except json.JSONDecodeError:
            return {
                "type": "apify",
                "action": "push_items_to_dataset",
                "status": "error",
                "error": "Invalid JSON in items",
                "status_code": 400,
                "data": None,
                "timestamp": time.time(),
            }

        return await self._make_request(
            "POST",
            f"/datasets/{config.dataset_id}/items",
            credentials,
            json_body=items if isinstance(items, list) else [items],
            action_name="push_items_to_dataset",
        )

    async def _delete_dataset(
        self, config: ApifyDeleteDatasetConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a dataset."""
        return await self._make_request(
            "DELETE",
            f"/datasets/{config.dataset_id}",
            credentials,
            action_name="delete_dataset",
        )

    # ============================================================================
    # Key-Value Store Operations
    # ============================================================================

    async def _list_key_value_stores(
        self, config: ApifyListKeyValueStoresConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List key-value stores."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
            "unnamed": config.unnamed,
        }
        return await self._make_request(
            "GET",
            "/key-value-stores",
            credentials,
            params=params,
            action_name="list_key_value_stores",
        )

    async def _get_key_value_store(
        self, config: ApifyGetKeyValueStoreConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get key-value store metadata."""
        return await self._make_request(
            "GET",
            f"/key-value-stores/{config.store_id}",
            credentials,
            action_name="get_key_value_store",
        )

    async def _list_keys(
        self, config: ApifyListKeysConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List keys in a store."""
        params = {
            "exclusiveStartKey": config.exclusive_start_key,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            f"/key-value-stores/{config.store_id}/keys",
            credentials,
            params=params,
            action_name="list_key_value_store_keys",
        )

    async def _get_record(
        self, config: ApifyGetRecordConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get a record from a store."""
        return await self._make_request(
            "GET",
            f"/key-value-stores/{config.store_id}/records/{config.key}",
            credentials,
            action_name="get_key_value_record",
        )

    async def _put_record(
        self, config: ApifyPutRecordConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Put a record in a store."""
        return await self._make_request(
            "PUT",
            f"/key-value-stores/{config.store_id}/records/{config.key}",
            credentials,
            raw_body=config.value,
            content_type=config.content_type or "application/json",
            action_name="put_key_value_record",
        )

    async def _delete_record(
        self, config: ApifyDeleteRecordConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a record from a store."""
        return await self._make_request(
            "DELETE",
            f"/key-value-stores/{config.store_id}/records/{config.key}",
            credentials,
            action_name="delete_key_value_record",
        )

    async def _create_key_value_store(
        self, config: ApifyCreateKeyValueStoreConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a named key-value store."""
        params = {"name": config.name}
        return await self._make_request(
            "POST",
            "/key-value-stores",
            credentials,
            params=params,
            action_name="create_key_value_store",
        )

    async def _delete_key_value_store(
        self, config: ApifyDeleteKeyValueStoreConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a key-value store."""
        return await self._make_request(
            "DELETE",
            f"/key-value-stores/{config.store_id}",
            credentials,
            action_name="delete_key_value_store",
        )

    # ============================================================================
    # Schedule Operations
    # ============================================================================

    async def _list_schedules(
        self, config: ApifyListSchedulesConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List schedules."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            "/schedules",
            credentials,
            params=params,
            action_name="list_schedules",
        )

    async def _get_schedule(
        self, config: ApifyGetScheduleConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get schedule details."""
        return await self._make_request(
            "GET",
            f"/schedules/{config.schedule_id}",
            credentials,
            action_name="get_schedule",
        )

    async def _create_schedule(
        self, config: ApifyCreateScheduleConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a schedule."""
        try:
            actions = json.loads(config.actions)
        except json.JSONDecodeError:
            return {
                "type": "apify",
                "action": "create_schedule",
                "status": "error",
                "error": "Invalid JSON in actions",
                "status_code": 400,
                "data": None,
                "timestamp": time.time(),
            }

        body = {
            "name": config.name,
            "cronExpression": config.cron_expression,
            "isEnabled": config.is_enabled,
            "isExclusive": config.is_exclusive,
            "timezone": config.timezone,
            "actions": actions,
        }
        return await self._make_request(
            "POST",
            "/schedules",
            credentials,
            json_body=body,
            action_name="create_schedule",
        )

    async def _update_schedule(
        self, config: ApifyUpdateScheduleConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update a schedule."""
        body = {}
        if config.name is not None:
            body["name"] = config.name
        if config.cron_expression is not None:
            body["cronExpression"] = config.cron_expression
        if config.is_enabled is not None:
            body["isEnabled"] = config.is_enabled
        if config.timezone is not None:
            body["timezone"] = config.timezone

        return await self._make_request(
            "PUT",
            f"/schedules/{config.schedule_id}",
            credentials,
            json_body=body,
            action_name="update_schedule",
        )

    async def _delete_schedule(
        self, config: ApifyDeleteScheduleConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a schedule."""
        return await self._make_request(
            "DELETE",
            f"/schedules/{config.schedule_id}",
            credentials,
            action_name="delete_schedule",
        )

    # ============================================================================
    # Webhook Operations
    # ============================================================================

    async def _list_webhooks(
        self, config: ApifyListWebhooksConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List webhooks."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET", "/webhooks", credentials, params=params, action_name="list_webhooks"
        )

    async def _get_webhook(
        self, config: ApifyGetWebhookConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get webhook details."""
        return await self._make_request(
            "GET",
            f"/webhooks/{config.webhook_id}",
            credentials,
            action_name="get_webhook",
        )

    async def _create_webhook(
        self, config: ApifyCreateWebhookConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a webhook."""
        body = {
            "eventTypes": config.event_types,
            "requestUrl": config.request_url,
            "isAdHoc": config.is_ad_hoc,
        }
        if config.condition:
            try:
                body["condition"] = json.loads(config.condition)
            except json.JSONDecodeError:
                return {
                    "type": "apify",
                    "action": "create_webhook",
                    "status": "error",
                    "error": "Invalid JSON in condition",
                    "status_code": 400,
                    "data": None,
                    "timestamp": time.time(),
                }

        return await self._make_request(
            "POST",
            "/webhooks",
            credentials,
            json_body=body,
            action_name="create_webhook",
        )

    async def _update_webhook(
        self, config: ApifyUpdateWebhookConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update a webhook."""
        body = {}
        if config.event_types is not None:
            body["eventTypes"] = config.event_types
        if config.request_url is not None:
            body["requestUrl"] = config.request_url
        if config.is_ad_hoc is not None:
            body["isAdHoc"] = config.is_ad_hoc

        return await self._make_request(
            "PUT",
            f"/webhooks/{config.webhook_id}",
            credentials,
            json_body=body,
            action_name="update_webhook",
        )

    async def _delete_webhook(
        self, config: ApifyDeleteWebhookConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a webhook."""
        return await self._make_request(
            "DELETE",
            f"/webhooks/{config.webhook_id}",
            credentials,
            action_name="delete_webhook",
        )

    async def _test_webhook(
        self, config: ApifyTestWebhookConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Test a webhook."""
        return await self._make_request(
            "POST",
            f"/webhooks/{config.webhook_id}/test",
            credentials,
            action_name="test_webhook",
        )

    # ============================================================================
    # User Operations
    # ============================================================================

    async def _get_user(
        self, config: ApifyGetUserConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get current user."""
        return await self._make_request(
            "GET", "/users/me", credentials, action_name="get_current_user"
        )

    # ============================================================================
    # Request Queue Operations
    # ============================================================================

    async def _list_request_queues(
        self, config: ApifyListRequestQueuesConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List request queues."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
            "unnamed": config.unnamed,
        }
        return await self._make_request(
            "GET",
            "/request-queues",
            credentials,
            params=params,
            action_name="list_request_queues",
        )

    async def _get_request_queue(
        self, config: ApifyGetRequestQueueConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get request queue metadata."""
        return await self._make_request(
            "GET",
            f"/request-queues/{config.queue_id}",
            credentials,
            action_name="get_request_queue",
        )

    # ============================================================================
    # Actor Management Operations
    # ============================================================================

    async def _create_actor(
        self, config: ApifyCreateActorConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a new Actor."""
        json_body = {
            "name": config.name,
        }
        if config.title:
            json_body["title"] = config.title
        if config.description:
            json_body["description"] = config.description
        if config.versions:
            json_body["versions"] = json.loads(config.versions)

        return await self._make_request(
            "POST",
            "/acts",
            credentials,
            json_body=json_body,
            action_name="create_actor",
        )

    async def _update_actor(
        self, config: ApifyUpdateActorConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update an existing Actor."""
        json_body = {}
        if config.name is not None:
            json_body["name"] = config.name
        if config.title is not None:
            json_body["title"] = config.title
        if config.description is not None:
            json_body["description"] = config.description
        if config.is_public is not None:
            json_body["isPublic"] = config.is_public

        return await self._make_request(
            "PUT",
            f"/acts/{config.actor_id}",
            credentials,
            json_body=json_body,
            action_name="update_actor",
        )

    async def _delete_actor(
        self, config: ApifyDeleteActorConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete an Actor."""
        return await self._make_request(
            "DELETE",
            f"/acts/{config.actor_id}",
            credentials,
            action_name="delete_actor",
        )

    # ============================================================================
    # Actor Build Operations
    # ============================================================================

    async def _list_actor_builds(
        self, config: ApifyListActorBuildsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List builds for an Actor."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/builds",
            credentials,
            params=params,
            action_name="list_actor_builds",
        )

    async def _build_actor(
        self, config: ApifyBuildActorConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Start a new Actor build."""
        json_body = {}
        if config.version_number:
            json_body["versionNumber"] = config.version_number
        if config.beta_packages is not None:
            json_body["betaPackages"] = config.beta_packages
        if config.tag:
            json_body["tag"] = config.tag
        if config.use_cache is not None:
            json_body["useCache"] = config.use_cache

        params = {}
        if config.wait_for_finish is not None:
            params["waitForFinish"] = min(config.wait_for_finish, 300)

        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/builds",
            credentials,
            params=params,
            json_body=json_body,
            action_name="start_actor_build",
            timeout=config.wait_for_finish + 10 if config.wait_for_finish else 30,
        )

    async def _get_actor_build(
        self, config: ApifyGetActorBuildConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get details of a specific Actor build."""
        params = {}
        if config.wait_for_finish is not None:
            params["waitForFinish"] = min(config.wait_for_finish, 60)

        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/builds/{config.build_id}",
            credentials,
            params=params,
            action_name="get_actor_build",
            timeout=config.wait_for_finish + 10 if config.wait_for_finish else 30,
        )

    async def _abort_build(
        self, config: ApifyAbortBuildConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Abort a running Actor build."""
        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/builds/{config.build_id}/abort",
            credentials,
            action_name="abort_actor_build",
        )

    # ============================================================================
    # Actor Version Operations
    # ============================================================================

    async def _list_actor_versions(
        self, config: ApifyListActorVersionsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List versions of an Actor."""
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/versions",
            credentials,
            action_name="list_actor_versions",
        )

    async def _get_actor_version(
        self, config: ApifyGetActorVersionConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get a specific Actor version."""
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/versions/{config.version_number}",
            credentials,
            action_name="get_actor_version",
        )

    async def _create_actor_version(
        self, config: ApifyCreateActorVersionConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a new Actor version."""
        json_body = {
            "versionNumber": config.version_number,
        }
        if config.build_tag:
            json_body["buildTag"] = config.build_tag
        if config.env_vars:
            json_body["envVars"] = json.loads(config.env_vars)
        if config.apply_env_vars_to_build is not None:
            json_body["applyEnvVarsToBuild"] = config.apply_env_vars_to_build
        if config.source_type:
            json_body["sourceType"] = config.source_type

        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/versions",
            credentials,
            json_body=json_body,
            action_name="create_actor_version",
        )

    async def _update_actor_version(
        self, config: ApifyUpdateActorVersionConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update an existing Actor version."""
        json_body = {}
        if config.build_tag is not None:
            json_body["buildTag"] = config.build_tag
        if config.env_vars is not None:
            json_body["envVars"] = json.loads(config.env_vars)

        return await self._make_request(
            "PUT",
            f"/acts/{config.actor_id}/versions/{config.version_number}",
            credentials,
            json_body=json_body,
            action_name="update_actor_version",
        )

    async def _delete_actor_version(
        self, config: ApifyDeleteActorVersionConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete an Actor version."""
        return await self._make_request(
            "DELETE",
            f"/acts/{config.actor_id}/versions/{config.version_number}",
            credentials,
            action_name="delete_actor_version",
        )

    # ============================================================================
    # Extended Run Operations
    # ============================================================================

    async def _metamorphose_run(
        self, config: ApifyMetamorphoseRunConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Metamorphose (transform) an Actor run into another Actor."""
        json_body = {
            "targetActorId": config.target_actor_id,
        }
        if config.target_actor_build:
            json_body["build"] = config.target_actor_build
        if config.input_body:
            json_body["input"] = json.loads(config.input_body)

        return await self._make_request(
            "POST",
            f"/actor-runs/{config.run_id}/metamorphose",
            credentials,
            json_body=json_body,
            action_name="metamorphose_actor_run",
        )

    async def _reboot_run(
        self, config: ApifyRebootRunConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Reboot an Actor run."""
        return await self._make_request(
            "POST",
            f"/actor-runs/{config.run_id}/reboot",
            credentials,
            action_name="reboot_actor_run",
        )

    # ============================================================================
    # Task Management Operations
    # ============================================================================

    async def _create_task(
        self, config: ApifyCreateTaskConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a new Actor Task."""
        json_body = {
            "actId": config.actor_id,
            "name": config.name,
        }
        if config.title:
            json_body["title"] = config.title
        if config.input_body:
            json_body["input"] = json.loads(config.input_body)
        if config.memory_mbytes is not None:
            json_body["options"] = json_body.get("options", {})
            json_body["options"]["memoryMbytes"] = config.memory_mbytes
        if config.timeout_secs is not None:
            json_body["options"] = json_body.get("options", {})
            json_body["options"]["timeoutSecs"] = config.timeout_secs

        return await self._make_request(
            "POST",
            "/actor-tasks",
            credentials,
            json_body=json_body,
            action_name="create_actor_task",
        )

    async def _update_task(
        self, config: ApifyUpdateTaskConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update an existing Actor Task."""
        json_body = {}
        if config.name is not None:
            json_body["name"] = config.name
        if config.title is not None:
            json_body["title"] = config.title
        if config.input_body is not None:
            json_body["input"] = json.loads(config.input_body)
        if config.memory_mbytes is not None or config.timeout_secs is not None:
            json_body["options"] = {}
            if config.memory_mbytes is not None:
                json_body["options"]["memoryMbytes"] = config.memory_mbytes
            if config.timeout_secs is not None:
                json_body["options"]["timeoutSecs"] = config.timeout_secs

        return await self._make_request(
            "PUT",
            f"/actor-tasks/{config.task_id}",
            credentials,
            json_body=json_body,
            action_name="update_actor_task",
        )

    async def _delete_task(
        self, config: ApifyDeleteTaskConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete an Actor Task."""
        return await self._make_request(
            "DELETE",
            f"/actor-tasks/{config.task_id}",
            credentials,
            action_name="delete_actor_task",
        )

    # ============================================================================
    # Request Queue Management Operations
    # ============================================================================

    async def _create_request_queue(
        self, config: ApifyCreateRequestQueueConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a named request queue."""
        json_body = {
            "name": config.name,
        }
        return await self._make_request(
            "POST",
            "/request-queues",
            credentials,
            json_body=json_body,
            action_name="create_request_queue",
        )

    async def _delete_request_queue(
        self, config: ApifyDeleteRequestQueueConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a request queue."""
        return await self._make_request(
            "DELETE",
            f"/request-queues/{config.queue_id}",
            credentials,
            action_name="delete_request_queue",
        )

    async def _list_queue_requests(
        self, config: ApifyListQueueRequestsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List requests in a queue."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            f"/request-queues/{config.queue_id}/requests",
            credentials,
            params=params,
            action_name="list_queue_requests",
        )

    async def _add_queue_request(
        self, config: ApifyAddQueueRequestConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Add a request to a queue."""
        json_body = {
            "url": config.url,
            "method": config.method,
        }
        if config.unique_key:
            json_body["uniqueKey"] = config.unique_key
        if config.user_data:
            json_body["userData"] = json.loads(config.user_data)

        return await self._make_request(
            "POST",
            f"/request-queues/{config.queue_id}/requests",
            credentials,
            json_body=json_body,
            action_name="add_request_to_queue",
        )

    async def _get_queue_request(
        self, config: ApifyGetQueueRequestConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get a specific request from a queue."""
        return await self._make_request(
            "GET",
            f"/request-queues/{config.queue_id}/requests/{config.request_id}",
            credentials,
            action_name="get_request_from_queue",
        )

    async def _update_queue_request(
        self, config: ApifyUpdateQueueRequestConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update a request in a queue."""
        json_body = {}
        if config.user_data is not None:
            json_body["userData"] = json.loads(config.user_data)

        return await self._make_request(
            "PUT",
            f"/request-queues/{config.queue_id}/requests/{config.request_id}",
            credentials,
            json_body=json_body,
            action_name="update_request_in_queue",
        )

    async def _delete_queue_request(
        self, config: ApifyDeleteQueueRequestConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete a request from a queue."""
        return await self._make_request(
            "DELETE",
            f"/request-queues/{config.queue_id}/requests/{config.request_id}",
            credentials,
            action_name="delete_request_from_queue",
        )

    # ============================================================================
    # Webhook Dispatch Operations
    # ============================================================================

    async def _list_webhook_dispatches(
        self, config: ApifyListWebhookDispatchesConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List webhook dispatch history."""
        params = {
            "offset": config.offset,
            "limit": config.limit,
        }
        return await self._make_request(
            "GET",
            f"/webhooks/{config.webhook_id}/dispatches",
            credentials,
            params=params,
            action_name="list_webhook_dispatches",
        )

    async def _get_webhook_dispatch(
        self, config: ApifyGetWebhookDispatchConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get details of a specific webhook dispatch."""
        return await self._make_request(
            "GET",
            f"/webhook-dispatches/{config.dispatch_id}",
            credentials,
            action_name="get_webhook_dispatch",
        )

    # ==================== Environment Variables Operations ====================

    async def _list_env_vars(
        self, config: ApifyListEnvVarsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """List environment variables for an Actor version."""
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/versions/{config.version_number}/env-vars",
            credentials,
            action_name="list_environment_variables",
        )

    async def _get_env_var(
        self, config: ApifyGetEnvVarConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get a specific environment variable."""
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/versions/{config.version_number}/env-vars/{config.env_var_name}",
            credentials,
            action_name="get_environment_variable",
        )

    async def _create_env_var(
        self, config: ApifyCreateEnvVarConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Create a new environment variable."""
        body = {
            "name": config.name,
            "value": config.value,
            "isSecret": config.is_secret,
        }
        return await self._make_request(
            "POST",
            f"/acts/{config.actor_id}/versions/{config.version_number}/env-vars",
            credentials,
            json_body=body,
            action_name="create_environment_variable",
        )

    async def _update_env_var(
        self, config: ApifyUpdateEnvVarConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update an environment variable."""
        body = {}
        if config.value is not None:
            body["value"] = config.value
        if config.is_secret is not None:
            body["isSecret"] = config.is_secret

        return await self._make_request(
            "PUT",
            f"/acts/{config.actor_id}/versions/{config.version_number}/env-vars/{config.env_var_name}",
            credentials,
            json_body=body,
            action_name="update_environment_variable",
        )

    async def _delete_env_var(
        self, config: ApifyDeleteEnvVarConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Delete an environment variable."""
        return await self._make_request(
            "DELETE",
            f"/acts/{config.actor_id}/versions/{config.version_number}/env-vars/{config.env_var_name}",
            credentials,
            action_name="delete_environment_variable",
        )

    # ==================== User/Account Operations ====================

    async def _get_public_user(
        self, config: ApifyGetPublicUserConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get public information about a user."""
        return await self._make_request(
            "GET",
            f"/users/{config.user_id}",
            credentials,
            action_name="get_public_user_info",
        )

    async def _get_user_limits(
        self, config: ApifyGetUserLimitsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get limits for the current user."""
        return await self._make_request(
            "GET", "/users/me/limits", credentials, action_name="get_account_limits_and_usage"
        )

    async def _update_user_limits(
        self, config: ApifyUpdateUserLimitsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Update limits for a user (requires admin)."""
        body = {}
        if config.max_monthly_usage_usd is not None:
            body["maxMonthlyUsageUsd"] = config.max_monthly_usage_usd
        if config.max_actors_per_user is not None:
            body["maxActorsPerUser"] = config.max_actors_per_user

        return await self._make_request(
            "PUT",
            f"/users/{config.user_id}/limits",
            credentials,
            json_body=body,
            action_name="update_account_limits",
        )

    async def _get_monthly_usage(
        self, config: ApifyGetMonthlyUsageConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get monthly usage statistics for the current user."""
        return await self._make_request(
            "GET",
            "/users/me/usage/monthly",
            credentials,
            action_name="get_monthly_usage_stats",
        )

    # ==================== Additional Resource Operations ====================

    async def _get_dataset_statistics(
        self, config: ApifyGetDatasetStatisticsConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get statistics about a dataset (item count, size, etc.)."""
        return await self._make_request(
            "GET",
            f"/datasets/{config.dataset_id}/stats",
            credentials,
            action_name="get_dataset_statistics",
        )

    async def _get_build_log(
        self, config: ApifyGetBuildLogConfig, credentials: ApifyCredential
    ) -> Dict[str, Any]:
        """Get the log from an actor build."""
        return await self._make_request(
            "GET",
            f"/acts/{config.actor_id}/builds/{config.build_id}/log",
            credentials,
            action_name="get_actor_build_log",
        )
