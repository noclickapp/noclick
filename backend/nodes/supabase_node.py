"""
Supabase REST API automation node.

Provides workflow integration with Supabase APIs including:
- Database (PostgREST): select, insert, update, delete, upsert, rpc operations
- Auth API (GoTrue): user authentication, signup, signin, password reset, user management
- Storage API: bucket and file management, uploads, downloads, signed URLs

Authentication: API Key (anon or service_role)
API Formats:
  - Database: https://<project_ref>.supabase.co/rest/v1/<table>
  - Auth: https://<project_ref>.supabase.co/auth/v1/<endpoint>
  - Storage: https://<project_ref>.supabase.co/storage/v1/<endpoint>
Documentation: https://supabase.com/docs/guides/api
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.supabase_oauth import is_token_expired, refresh_access_token
from nodes.scopes.supabase import SUPABASE_SCOPES
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)


# ============================================================================
# Credential Schema
# ============================================================================


class SupabaseApiKeyCredential(BaseModel):
    """
    API Key credential for Supabase.

    Get your API keys at: https://supabase.com/dashboard/project/_/settings/api
    """

    credential_type: Literal["supabase_api_key"] = Field(
        "supabase_api_key", json_schema_extra={"ui:hidden": True}
    )
    project_url: str = Field(
        ...,
        title="Project URL",
        description="Your Supabase project URL (e.g., https://xxxx.supabase.co)",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Supabase API key (anon key respects RLS, service_role bypasses RLS)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://supabase.com/dashboard/project/_/settings/api"
        }
    )


class SupabaseOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Supabase.

    Obtained via the Supabase Management API OAuth flow. After connecting, the
    project's anon and service_role keys are fetched once and cached here so
    workflow node executions don't require additional Management API calls.

    Register your OAuth app at: https://supabase.com/dashboard/account/tokens
    """

    credential_type: Literal["supabase_oauth"] = Field(
        "supabase_oauth", json_schema_extra={"ui:hidden": True}
    )
    project_url: str = Field(
        ...,
        title="Project URL",
        description="Your Supabase project URL (e.g., https://xxxx.supabase.co)",
        json_schema_extra={"ui:hidden": True},
    )
    access_token: str = Field(
        ..., title="Access Token", description="Supabase Management API OAuth token"
    )
    refresh_token: Optional[str] = Field(
        None, title="Refresh Token", description="OAuth refresh token for renewal"
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    anon_key: Optional[str] = Field(
        None, title="Anon Key", description="Cached project anon key"
    )
    service_role_key: Optional[str] = Field(
        None, title="Service Role Key", description="Cached project service_role key"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "supabase",
            "x-oauth-scopes": [
                "database:read",
                "database:write",
                "auth:read",
                "auth:write",
                "storage:read",
                "storage:write",
                "edge_functions:read",
                "edge_functions:write",
                "secrets:read",
                "projects:read",
            ],
        }
    )


# Union type supporting both API key and OAuth credentials
SupabaseCredential = Union[SupabaseOAuthCredential, SupabaseApiKeyCredential]


# ============================================================================
# Select Operation Config
# ============================================================================


class SupabaseSelectConfig(BaseModel):
    """Select/query rows from a table with filtering, ordering, and pagination"""

    operation: Literal["select_table_rows"] = Field(
        "select_table_rows",
        json_schema_extra={
            "const": "select_table_rows",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Select Table Rows",
            "x-keywords": [
                "query rows",
                "select from table",
                "read records",
                "run select",
                "paginate rows",
                "filter table",
            ],
        },
        title="Select Table Rows",
    )
    table: str = Field(..., title="Table", description="Name of the table to query")
    columns: Optional[str] = Field(
        "*",
        title="Columns",
        description="Columns to select (comma-separated, * for all). Supports relations: 'id,name,posts(id,title)'",
    )
    filters: Optional[List[Dict[str, str]]] = Field(
        None,
        title="Filters",
        description="Array of filter objects: [{column: 'name', operator: 'eq', value: 'John'}]",
    )
    order_by: Optional[str] = Field(
        None,
        title="Order By",
        description="Column to order by (e.g., 'created_at.desc' or 'name.asc')",
    )
    limit: Optional[int] = Field(
        None,
        title="Limit",
        description="Maximum number of rows to return",
        ge=1,
        le=1000,
    )
    offset: Optional[int] = Field(
        None,
        title="Offset",
        description="Number of rows to skip (for pagination)",
        ge=0,
    )
    single: Optional[bool] = Field(
        False,
        title="Single Row",
        description="Return a single object instead of an array (fails if not exactly one row)",
    )
    count: Optional[Literal["exact", "planned", "estimated"]] = Field(
        None, title="Count", description="Include row count in response headers"
    )


class SupabaseInsertConfig(BaseModel):
    """Insert one or more rows into a table"""

    operation: Literal["insert_table_rows"] = Field(
        "insert_table_rows",
        json_schema_extra={
            "const": "insert_table_rows",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Insert Table Rows",
            "x-keywords": [
                "insert rows",
                "add records",
                "create rows",
                "bulk insert",
                "write rows",
            ],
        },
        title="Insert Table Rows",
    )
    table: str = Field(
        ..., title="Table", description="Name of the table to insert into"
    )
    rows: Union[Dict[str, Any], List[Dict[str, Any]]] = Field(
        ...,
        title="Rows",
        description="Single row object or array of row objects to insert",
    )
    return_data: Optional[bool] = Field(
        True, title="Return Data", description="Return the inserted rows"
    )
    on_conflict: Optional[str] = Field(
        None,
        title="On Conflict",
        description="Column(s) for conflict resolution (enables upsert behavior)",
    )
    ignore_duplicates: Optional[bool] = Field(
        False,
        title="Ignore Duplicates",
        description="Skip rows that violate unique constraints instead of erroring",
    )
    default_to_null: Optional[bool] = Field(
        True,
        title="Default to Null",
        description="Use NULL for missing columns (false uses column defaults)",
    )


class SupabaseUpdateConfig(BaseModel):
    """Update rows matching filter conditions"""

    operation: Literal["update_table_rows"] = Field(
        "update_table_rows",
        json_schema_extra={
            "const": "update_table_rows",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Update Table Rows",
            "x-keywords": [
                "update rows",
                "edit records",
                "modify rows",
                "change records",
                "patch rows",
            ],
        },
        title="Update Table Rows",
    )
    table: str = Field(..., title="Table", description="Name of the table to update")
    values: Dict[str, Any] = Field(
        ..., title="Values", description="Object with column-value pairs to update"
    )
    filters: List[Dict[str, str]] = Field(
        ...,
        title="Filters",
        description="Array of filter objects to identify rows: [{column: 'id', operator: 'eq', value: '123'}]",
    )
    return_data: Optional[bool] = Field(
        True, title="Return Data", description="Return the updated rows"
    )


class SupabaseDeleteConfig(BaseModel):
    """Delete rows matching filter conditions"""

    operation: Literal["delete_table_rows"] = Field(
        "delete_table_rows",
        json_schema_extra={
            "const": "delete_table_rows",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Delete Table Rows",
            "x-keywords": [
                "delete rows",
                "remove records",
                "drop rows",
                "delete records",
            ],
        },
        title="Delete Table Rows",
    )
    table: str = Field(
        ..., title="Table", description="Name of the table to delete from"
    )
    filters: List[Dict[str, str]] = Field(
        ...,
        title="Filters",
        description="Array of filter objects to identify rows: [{column: 'id', operator: 'eq', value: '123'}]",
    )
    return_data: Optional[bool] = Field(
        True, title="Return Data", description="Return the deleted rows"
    )


class SupabaseUpsertConfig(BaseModel):
    """Insert rows or update if they already exist (based on primary key or unique constraint)"""

    operation: Literal["upsert_table_rows"] = Field(
        "upsert_table_rows",
        json_schema_extra={
            "const": "upsert_table_rows",
            "ui:hidden": True,
            "x-category": "Table",
            "x-is-trigger": False,
            "x-display-name": "Upsert Table Rows",
            "x-keywords": [
                "upsert rows",
                "insert or update",
                "merge rows",
                "on conflict",
                "upsert records",
            ],
        },
        title="Upsert Table Rows",
    )
    table: str = Field(..., title="Table", description="Name of the table")
    rows: Union[Dict[str, Any], List[Dict[str, Any]]] = Field(
        ...,
        title="Rows",
        description="Single row object or array of row objects to upsert",
    )
    on_conflict: Optional[str] = Field(
        None,
        title="On Conflict Column",
        description="Column(s) to determine conflicts (defaults to primary key)",
    )
    return_data: Optional[bool] = Field(
        True, title="Return Data", description="Return the upserted rows"
    )
    ignore_duplicates: Optional[bool] = Field(
        False,
        title="Ignore Duplicates",
        description="Skip conflicting rows instead of updating them",
    )
    default_to_null: Optional[bool] = Field(
        True,
        title="Default to Null",
        description="Use NULL for missing columns (false uses column defaults)",
    )


class SupabaseRpcConfig(BaseModel):
    """Call a database function (RPC)"""

    operation: Literal["call_database_function"] = Field(
        "call_database_function",
        json_schema_extra={
            "const": "call_database_function",
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "Call Database Function",
            "x-keywords": [
                "call function",
                "run rpc",
                "stored procedure",
                "invoke postgres function",
                "execute function",
            ],
        },
        title="Call Database Function",
    )
    function_name: str = Field(
        ..., title="Function Name", description="Name of the database function to call"
    )
    params: Optional[Dict[str, Any]] = Field(
        None,
        title="Parameters",
        description="Object with parameter names and values for the function",
    )
    return_data: Optional[bool] = Field(
        True, title="Return Data", description="Return the function result"
    )
    single: Optional[bool] = Field(
        False,
        title="Single Row",
        description="Return a single object instead of an array",
    )
    count: Optional[Literal["exact", "planned", "estimated"]] = Field(
        None, title="Count", description="Include row count in response"
    )


# ============================================================================
# Auth API Operation Configs
# ============================================================================


class SupabaseAuthSignUpConfig(BaseModel):
    """Sign up a new user with email and password"""

    operation: Literal["sign_up_user"] = Field(
        "sign_up_user",
        json_schema_extra={
            "const": "sign_up_user",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Sign Up User",
            "x-keywords": [
                "register user",
                "create account",
                "signup",
                "new user",
                "email signup",
            ],
        },
        title="Sign Up User",
    )
    email: str = Field(..., title="Email", description="User's email address")
    password: str = Field(
        ...,
        title="Password",
        description="User's password (min 6 characters)",
        json_schema_extra={"ui:widget": "password"},
    )
    user_metadata: Optional[Dict[str, Any]] = Field(
        None,
        title="User Metadata",
        description="Additional user metadata (name, avatar_url, etc.)",
    )
    email_redirect_to: Optional[str] = Field(
        None,
        title="Email Redirect URL",
        description="URL to redirect to after email confirmation",
    )


class SupabaseAuthSignInPasswordConfig(BaseModel):
    """Sign in with email and password"""

    operation: Literal["sign_in_with_password"] = Field(
        "sign_in_with_password",
        json_schema_extra={
            "const": "sign_in_with_password",
            "ui:hidden": True,
            "x-category": "Auth Session",
            "x-is-trigger": False,
            "x-display-name": "Sign in with Password",
            "x-keywords": [
                "login",
                "log in",
                "sign in",
                "email password login",
                "authenticate user",
            ],
        },
        title="Sign in with Password",
    )
    email: str = Field(..., title="Email", description="User's email address")
    password: str = Field(
        ...,
        title="Password",
        description="User's password",
        json_schema_extra={"ui:widget": "password"},
    )


class SupabaseAuthSignInMagicLinkConfig(BaseModel):
    """Send a magic link to user's email for passwordless signin"""

    operation: Literal["send_magic_link_signin"] = Field(
        "send_magic_link_signin",
        json_schema_extra={
            "const": "send_magic_link_signin",
            "ui:hidden": True,
            "x-category": "Auth Session",
            "x-is-trigger": False,
            "x-display-name": "Send Magic Link Signin",
            "x-keywords": [
                "magic link",
                "passwordless login",
                "email login link",
                "otp link",
                "send login link",
            ],
        },
        title="Send Magic Link Signin",
    )
    email: str = Field(..., title="Email", description="User's email address")
    email_redirect_to: Optional[str] = Field(
        None,
        title="Email Redirect URL",
        description="URL to redirect to after clicking the magic link",
    )


class SupabaseAuthSignOutConfig(BaseModel):
    """Sign out the current user (requires user's access token)"""

    operation: Literal["sign_out_user"] = Field(
        "sign_out_user",
        json_schema_extra={
            "const": "sign_out_user",
            "ui:hidden": True,
            "x-category": "Auth Session",
            "x-is-trigger": False,
            "x-display-name": "Sign Out User",
            "x-keywords": [
                "logout",
                "log out",
                "sign out",
                "end session",
                "revoke session",
            ],
        },
        title="Sign Out User",
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="User's JWT access token from signin response",
        json_schema_extra={"ui:widget": "password"},
    )


class SupabaseAuthGetUserConfig(BaseModel):
    """Get current user details (requires user's access token)"""

    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        json_schema_extra={
            "const": "get_current_user",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
            "x-keywords": [
                "current user",
                "whoami",
                "logged in user",
                "session user",
                "my profile",
            ],
        },
        title="Get Current User",
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="User's JWT access token",
        json_schema_extra={"ui:widget": "password"},
    )


class SupabaseAuthUpdateUserConfig(BaseModel):
    """Update current user's email, password, or metadata"""

    model_config = {"title": "Auth Update User"}

    operation: Literal["update_current_user"] = Field(
        "update_current_user",
        json_schema_extra={
            "const": "update_current_user",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Update Current User",
            "x-keywords": [
                "update profile",
                "change password",
                "update email",
                "edit my account",
                "set user metadata",
            ],
        },
        title="Update Current User",
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="User's JWT access token",
        json_schema_extra={"ui:widget": "password"},
    )
    email: Optional[str] = Field(
        None, title="New Email", description="New email address (requires confirmation)"
    )
    password: Optional[str] = Field(
        None,
        title="New Password",
        description="New password (min 6 characters)",
        json_schema_extra={"ui:widget": "password"},
    )
    user_metadata: Optional[Dict[str, Any]] = Field(
        None, title="User Metadata", description="Updated user metadata"
    )


class SupabaseAuthResetPasswordConfig(BaseModel):
    """Send password reset email to user"""

    model_config = {"title": "Auth Reset Password"}

    operation: Literal["send_password_reset_email"] = Field(
        "send_password_reset_email",
        json_schema_extra={
            "const": "send_password_reset_email",
            "ui:hidden": True,
            "x-category": "Auth",
            "x-is-trigger": False,
            "x-display-name": "Send Password Reset Email",
            "x-keywords": [
                "reset password",
                "forgot password",
                "password recovery",
                "recovery email",
                "reset link",
            ],
        },
        title="Send Password Reset Email",
    )
    email: str = Field(..., title="Email", description="User's email address")
    redirect_to: Optional[str] = Field(
        None,
        title="Redirect URL",
        description="URL to redirect to after password reset",
    )


class SupabaseAuthVerifyOTPConfig(BaseModel):
    """Verify OTP code sent via email or SMS"""

    model_config = {"title": "Auth Verify OTP"}

    operation: Literal["verify_otp_code"] = Field(
        "verify_otp_code",
        json_schema_extra={
            "const": "verify_otp_code",
            "ui:hidden": True,
            "x-category": "Auth",
            "x-is-trigger": False,
            "x-display-name": "Verify Otp Code",
            "x-keywords": [
                "verify otp",
                "confirm code",
                "verify code",
                "validate otp",
                "sms code",
            ],
        },
        title="Verify Otp Code",
    )
    email: Optional[str] = Field(
        None, title="Email", description="User's email (for email OTP)"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="User's phone number (for SMS OTP)"
    )
    token: str = Field(..., title="OTP Token", description="6-digit OTP code")
    type: Literal["signup", "magiclink", "recovery", "email_change", "sms"] = Field(
        ..., title="OTP Type", description="Type of OTP verification"
    )


class SupabaseAuthRefreshTokenConfig(BaseModel):
    """Refresh an expired access token using refresh token"""

    model_config = {"title": "Auth Refresh Token"}

    operation: Literal["refresh_access_token"] = Field(
        "refresh_access_token",
        json_schema_extra={
            "const": "refresh_access_token",
            "ui:hidden": True,
            "x-category": "Auth",
            "x-is-trigger": False,
            "x-display-name": "Refresh Access Token",
            "x-keywords": [
                "refresh token",
                "renew token",
                "refresh session",
                "new access token",
                "rotate token",
            ],
        },
        title="Refresh Access Token",
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="Refresh token from signin response",
        json_schema_extra={"ui:widget": "password"},
    )


class SupabaseAuthAdminListUsersConfig(BaseModel):
    """List all users (requires service_role API key)"""

    operation: Literal["admin_list_users"] = Field(
        "admin_list_users",
        json_schema_extra={
            "const": "admin_list_users",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Admin List Users",
            "x-keywords": [
                "list all users",
                "admin users",
                "service role users",
                "all accounts",
                "user directory",
            ],
        },
        title="Admin List Users",
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        50, title="Per Page", description="Number of users per page", ge=1, le=1000
    )


class SupabaseAuthAdminCreateUserConfig(BaseModel):
    """Create a new user (admin operation, requires service_role API key)"""

    operation: Literal["admin_create_user"] = Field(
        "admin_create_user",
        json_schema_extra={
            "const": "admin_create_user",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Admin Create User",
            "x-keywords": [
                "admin create account",
                "provision user",
                "service role create user",
                "admin new user",
            ],
        },
        title="Admin Create User",
    )
    email: str = Field(..., title="Email", description="User's email address")
    password: Optional[str] = Field(
        None,
        title="Password",
        description="User's password (if not set, send confirmation email)",
        json_schema_extra={"ui:widget": "password"},
    )
    email_confirm: Optional[bool] = Field(
        False, title="Auto-confirm Email", description="Skip email confirmation"
    )
    user_metadata: Optional[Dict[str, Any]] = Field(
        None, title="User Metadata", description="User metadata"
    )


class SupabaseAuthAdminDeleteUserConfig(BaseModel):
    """Delete a user by ID (admin operation, requires service_role API key)"""

    operation: Literal["admin_delete_user"] = Field(
        "admin_delete_user",
        json_schema_extra={
            "const": "admin_delete_user",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Admin Delete User",
            "x-keywords": [
                "admin delete account",
                "remove user",
                "service role delete user",
                "ban user",
            ],
        },
        title="Admin Delete User",
    )
    user_id: str = Field(..., title="User ID", description="UUID of the user to delete")


class SupabaseAuthAdminUpdateUserConfig(BaseModel):
    """Update a user by ID (admin operation, requires service_role API key)"""

    operation: Literal["admin_update_user"] = Field(
        "admin_update_user",
        json_schema_extra={
            "const": "admin_update_user",
            "ui:hidden": True,
            "x-category": "Auth User",
            "x-is-trigger": False,
            "x-display-name": "Admin Update User",
            "x-keywords": [
                "admin update account",
                "service role edit user",
                "set user role",
                "admin modify user",
            ],
        },
        title="Admin Update User",
    )
    user_id: str = Field(..., title="User ID", description="UUID of the user to update")
    email: Optional[str] = Field(None, title="Email", description="New email address")
    password: Optional[str] = Field(
        None,
        title="Password",
        description="New password",
        json_schema_extra={"ui:widget": "password"},
    )
    email_confirm: Optional[bool] = Field(
        None, title="Email Confirmed", description="Mark email as confirmed"
    )
    user_metadata: Optional[Dict[str, Any]] = Field(
        None, title="User Metadata", description="Updated user metadata"
    )
    app_metadata: Optional[Dict[str, Any]] = Field(
        None,
        title="App Metadata",
        description="Updated app metadata (provider, providers, etc.)",
    )


# ============================================================================
# Storage API Operation Configs
# ============================================================================


class SupabaseStorageCreateBucketConfig(BaseModel):
    """Create a new storage bucket"""

    operation: Literal["create_storage_bucket"] = Field(
        "create_storage_bucket",
        json_schema_extra={
            "const": "create_storage_bucket",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Create Storage Bucket",
            "x-keywords": [
                "create bucket",
                "new bucket",
                "make storage bucket",
                "add bucket",
            ],
        },
        title="Create Storage Bucket",
    )
    bucket_name: str = Field(
        ...,
        title="Bucket Name",
        description="Name of the bucket (lowercase, no spaces)",
    )
    public: Optional[bool] = Field(
        False, title="Public", description="Make bucket publicly accessible"
    )
    file_size_limit: Optional[int] = Field(
        None,
        title="File Size Limit",
        description="Max file size in bytes (null for unlimited)",
    )
    allowed_mime_types: Optional[List[str]] = Field(
        None,
        title="Allowed MIME Types",
        description="List of allowed MIME types (null for all types)",
    )


class SupabaseStorageListBucketsConfig(BaseModel):
    """List all storage buckets"""

    operation: Literal["list_storage_buckets"] = Field(
        "list_storage_buckets",
        json_schema_extra={
            "const": "list_storage_buckets",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "List Storage Buckets",
            "x-keywords": [
                "list buckets",
                "all buckets",
                "show buckets",
                "get buckets",
            ],
        },
        title="List Storage Buckets",
    )


class SupabaseStorageGetBucketConfig(BaseModel):
    """Get bucket details"""

    operation: Literal["get_storage_bucket"] = Field(
        "get_storage_bucket",
        json_schema_extra={
            "const": "get_storage_bucket",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Get Storage Bucket",
            "x-keywords": [
                "bucket details",
                "get bucket",
                "bucket info",
                "inspect bucket",
            ],
        },
        title="Get Storage Bucket",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Name of the bucket")


class SupabaseStorageDeleteBucketConfig(BaseModel):
    """Delete a storage bucket"""

    operation: Literal["delete_storage_bucket"] = Field(
        "delete_storage_bucket",
        json_schema_extra={
            "const": "delete_storage_bucket",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Delete Storage Bucket",
            "x-keywords": ["delete bucket", "remove bucket", "drop bucket"],
        },
        title="Delete Storage Bucket",
    )
    bucket_name: str = Field(
        ..., title="Bucket Name", description="Name of the bucket to delete"
    )


class SupabaseStorageEmptyBucketConfig(BaseModel):
    """Empty a storage bucket (delete all files)"""

    operation: Literal["empty_storage_bucket"] = Field(
        "empty_storage_bucket",
        json_schema_extra={
            "const": "empty_storage_bucket",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Empty Storage Bucket",
            "x-keywords": [
                "empty bucket",
                "clear bucket",
                "wipe bucket",
                "delete all files",
            ],
        },
        title="Empty Storage Bucket",
    )
    bucket_name: str = Field(
        ..., title="Bucket Name", description="Name of the bucket to empty"
    )


class SupabaseStorageUploadFileConfig(BaseModel):
    """Upload a file to storage"""

    operation: Literal["upload_storage_file"] = Field(
        "upload_storage_file",
        json_schema_extra={
            "const": "upload_storage_file",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Upload Storage File",
            "x-keywords": ["upload file", "put file", "store file", "save to storage"],
        },
        title="Upload Storage File",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Name of the bucket")
    file_path: str = Field(
        ...,
        title="File Path",
        description="Path within bucket (e.g., 'folder/file.jpg')",
    )
    file_content: str = Field(
        ...,
        title="File Content",
        description="The file to upload — plain text, or for binary: upload a file, paste a URL, reference an upstream file (e.g. {{http-1.response.url}}), a data: URI, or base64.",
    )
    content_type: Optional[str] = Field(
        None,
        title="Content Type",
        description="MIME type (e.g., 'image/jpeg', 'text/plain')",
    )
    upsert: Optional[bool] = Field(
        False, title="Upsert", description="Overwrite file if it exists"
    )


class SupabaseStorageDownloadFileConfig(BaseModel):
    """Download a file from storage"""

    operation: Literal["download_storage_file"] = Field(
        "download_storage_file",
        json_schema_extra={
            "const": "download_storage_file",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Download Storage File",
            "x-keywords": [
                "download file",
                "fetch file",
                "get file bytes",
                "retrieve file",
            ],
        },
        title="Download Storage File",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Name of the bucket")
    file_path: str = Field(..., title="File Path", description="Path within bucket")


class SupabaseStorageListFilesConfig(BaseModel):
    """List files in a storage bucket folder"""

    operation: Literal["list_bucket_files"] = Field(
        "list_bucket_files",
        json_schema_extra={
            "const": "list_bucket_files",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "List Bucket Files",
            "x-keywords": [
                "list files",
                "browse folder",
                "files in bucket",
                "list objects",
                "folder contents",
            ],
        },
        title="List Bucket Files",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Name of the bucket")
    folder_path: Optional[str] = Field(
        "",
        title="Folder Path",
        description="Folder path within bucket (empty for root)",
    )
    limit: Optional[int] = Field(
        100,
        title="Limit",
        description="Maximum number of files to return",
        ge=1,
        le=1000,
    )
    offset: Optional[int] = Field(
        0, title="Offset", description="Number of files to skip", ge=0
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search query to filter files"
    )


class SupabaseStorageDeleteFileConfig(BaseModel):
    """Delete a file from storage"""

    operation: Literal["delete_storage_file"] = Field(
        "delete_storage_file",
        json_schema_extra={
            "const": "delete_storage_file",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Delete Storage File",
            "x-keywords": ["delete file", "remove file", "erase file"],
        },
        title="Delete Storage File",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Name of the bucket")
    file_paths: Union[str, List[str]] = Field(
        ...,
        title="File Paths",
        description="File path(s) to delete (string or array of strings)",
    )


class SupabaseStorageMoveFileConfig(BaseModel):
    """Move a file within or between buckets"""

    operation: Literal["move_storage_file"] = Field(
        "move_storage_file",
        json_schema_extra={
            "const": "move_storage_file",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Move Storage File",
            "x-keywords": ["move file", "rename file", "relocate file"],
        },
        title="Move Storage File",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Source bucket name")
    from_path: str = Field(..., title="From Path", description="Current file path")
    to_path: str = Field(..., title="To Path", description="New file path")


class SupabaseStorageCopyFileConfig(BaseModel):
    """Copy a file within or between buckets"""

    operation: Literal["copy_storage_file"] = Field(
        "copy_storage_file",
        json_schema_extra={
            "const": "copy_storage_file",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Copy Storage File",
            "x-keywords": ["copy file", "duplicate file", "clone file"],
        },
        title="Copy Storage File",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Source bucket name")
    from_path: str = Field(..., title="From Path", description="Source file path")
    to_path: str = Field(..., title="To Path", description="Destination file path")


class SupabaseStorageCreateSignedURLConfig(BaseModel):
    """Create a signed URL for temporary file access"""

    operation: Literal["create_file_signed_url"] = Field(
        "create_file_signed_url",
        json_schema_extra={
            "const": "create_file_signed_url",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Create File Signed Url",
            "x-keywords": [
                "signed url",
                "temporary link",
                "presigned url",
                "private file link",
                "expiring url",
            ],
        },
        title="Create File Signed Url",
    )
    bucket_name: str = Field(..., title="Bucket Name", description="Name of the bucket")
    file_path: str = Field(..., title="File Path", description="Path to the file")
    expires_in: int = Field(
        3600,
        title="Expires In (seconds)",
        description="Number of seconds until URL expires",
        ge=1,
        le=604800,  # 7 days max
    )


class SupabaseStorageGetPublicURLConfig(BaseModel):
    """Get public URL for a file in a public bucket"""

    operation: Literal["get_file_public_url"] = Field(
        "get_file_public_url",
        json_schema_extra={
            "const": "get_file_public_url",
            "ui:hidden": True,
            "x-category": "Storage",
            "x-is-trigger": False,
            "x-display-name": "Get File Public Url",
            "x-keywords": ["public url", "public link", "file url", "shareable link"],
        },
        title="Get File Public Url",
    )
    bucket_name: str = Field(
        ..., title="Bucket Name", description="Name of the public bucket"
    )
    file_path: str = Field(..., title="File Path", description="Path to the file")


# ============================================================================
# Realtime API Operation Configs
# ============================================================================


class SupabaseRealtimeBroadcastConfig(BaseModel):
    """Send broadcast messages to a Realtime channel"""

    operation: Literal["broadcast_realtime_message"] = Field(
        "broadcast_realtime_message",
        json_schema_extra={
            "const": "broadcast_realtime_message",
            "ui:hidden": True,
            "x-category": "Realtime",
            "x-is-trigger": False,
            "x-display-name": "Broadcast Realtime Message",
            "x-keywords": [
                "broadcast message",
                "realtime channel",
                "send to subscribers",
                "publish realtime",
                "pubsub broadcast",
            ],
        },
        title="Broadcast Realtime Message",
    )
    channel: str = Field(
        ..., title="Channel", description="Channel name/topic to broadcast to"
    )
    event: str = Field(
        ..., title="Event", description="Event name for the broadcast message"
    )
    payload: Dict[str, Any] = Field(
        ..., title="Payload", description="Message payload to broadcast"
    )


# ============================================================================
# Edge Functions API Operation Configs
# ============================================================================


class SupabaseEdgeFunctionInvokeConfig(BaseModel):
    """Invoke a Supabase Edge Function"""

    operation: Literal["invoke_edge_function"] = Field(
        "invoke_edge_function",
        json_schema_extra={
            "const": "invoke_edge_function",
            "ui:hidden": True,
            "x-category": "Function",
            "x-is-trigger": False,
            "x-display-name": "Invoke Edge Function",
            "x-keywords": [
                "invoke edge function",
                "run edge function",
                "call serverless",
                "trigger function",
                "deno function",
            ],
        },
        title="Invoke Edge Function",
    )
    function_name: str = Field(
        ..., title="Function Name", description="Name of the edge function to invoke"
    )
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(
        "POST",
        title="HTTP Method",
        description="HTTP method for the function invocation",
    )
    body: Optional[Dict[str, Any]] = Field(
        None, title="Request Body", description="JSON body to send to the function"
    )
    headers: Optional[Dict[str, str]] = Field(
        None,
        title="Custom Headers",
        description="Additional headers to send with the request",
    )


# ============================================================================
# Discriminated Union
# ============================================================================

SupabaseConfig = Annotated[
    Union[
        # Database operations (PostgREST)
        SupabaseSelectConfig,
        SupabaseInsertConfig,
        SupabaseUpdateConfig,
        SupabaseDeleteConfig,
        SupabaseUpsertConfig,
        SupabaseRpcConfig,
        # Auth operations
        SupabaseAuthSignUpConfig,
        SupabaseAuthSignInPasswordConfig,
        SupabaseAuthSignInMagicLinkConfig,
        SupabaseAuthSignOutConfig,
        SupabaseAuthGetUserConfig,
        SupabaseAuthUpdateUserConfig,
        SupabaseAuthResetPasswordConfig,
        SupabaseAuthVerifyOTPConfig,
        SupabaseAuthRefreshTokenConfig,
        SupabaseAuthAdminListUsersConfig,
        SupabaseAuthAdminCreateUserConfig,
        SupabaseAuthAdminDeleteUserConfig,
        SupabaseAuthAdminUpdateUserConfig,
        # Storage operations
        SupabaseStorageCreateBucketConfig,
        SupabaseStorageListBucketsConfig,
        SupabaseStorageGetBucketConfig,
        SupabaseStorageDeleteBucketConfig,
        SupabaseStorageEmptyBucketConfig,
        SupabaseStorageUploadFileConfig,
        SupabaseStorageDownloadFileConfig,
        SupabaseStorageListFilesConfig,
        SupabaseStorageDeleteFileConfig,
        SupabaseStorageMoveFileConfig,
        SupabaseStorageCopyFileConfig,
        SupabaseStorageCreateSignedURLConfig,
        SupabaseStorageGetPublicURLConfig,
        # Realtime operations
        SupabaseRealtimeBroadcastConfig,
        # Edge Functions operations
        SupabaseEdgeFunctionInvokeConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class SupabaseNodeConfig(NodeConfig[SupabaseConfig, SupabaseCredential]):
    """Full configuration for Supabase node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class SupabaseNode(WorkflowNode):
    """
    Supabase automation node.

    Executes Supabase API operations for database, auth, storage, realtime, and edge functions.
    Supports 35 operations across 5 APIs:
    - Database (6): select, insert, update, delete, upsert, rpc
    - Auth (13): signup, signin, signout, user management, admin operations
    - Storage (14): bucket and file management, uploads, downloads, signed URLs
    - Realtime (1): broadcast messages to channels
    - Edge Functions (1): invoke serverless functions
    """

    edit_examples = [
        "Query the users table and filter by email",
        "Insert a new record into the products table with SKU and price",
        "Update user profile photo in storage bucket",
        "Sign up a new user with email and password",
        "Delete expired sessions from the auth_sessions table",
        "Download a file from the documents storage bucket",
        "Create a signed URL for a private PDF file",
    ]

    # PostgREST filter operators mapping
    FILTER_OPERATORS = {
        "eq": "eq",
        "neq": "neq",
        "gt": "gt",
        "gte": "gte",
        "lt": "lt",
        "lte": "lte",
        "like": "like",
        "ilike": "ilike",
        "is": "is",
        "in": "in",
        "cs": "cs",  # contains (for arrays/ranges)
        "cd": "cd",  # contained by
        "sl": "sl",  # strictly left of (ranges)
        "sr": "sr",  # strictly right of (ranges)
        "nxl": "nxl",  # not extends left
        "nxr": "nxr",  # not extends right
        "adj": "adj",  # adjacent (ranges)
        "ov": "ov",  # overlap
        "fts": "fts",  # full text search
        "plfts": "plfts",  # phrase full text search
        "phfts": "phfts",  # plain + phrase full text search
        "wfts": "wfts",  # websearch full text search
        "not.eq": "not.eq",
        "not.is": "not.is",
        "not.in": "not.in",
    }

    scope_registry = SUPABASE_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_storage_buckets",
        noun="storage buckets",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return SupabaseNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.supabase_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="supabase",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, SupabaseNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Supabase Project URL and API Key."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Database operations
            "select_table_rows": self._handle_select,
            "insert_table_rows": self._handle_insert,
            "update_table_rows": self._handle_update,
            "delete_table_rows": self._handle_delete,
            "upsert_table_rows": self._handle_upsert,
            "call_database_function": self._handle_rpc,
            # Auth operations
            "sign_up_user": self._handle_auth_signup,
            "sign_in_with_password": self._handle_auth_signin_password,
            "send_magic_link_signin": self._handle_auth_signin_magiclink,
            "sign_out_user": self._handle_auth_signout,
            "get_current_user": self._handle_auth_get_user,
            "update_current_user": self._handle_auth_update_user,
            "send_password_reset_email": self._handle_auth_reset_password,
            "verify_otp_code": self._handle_auth_verify_otp,
            "refresh_access_token": self._handle_auth_refresh_token,
            "admin_list_users": self._handle_auth_admin_list_users,
            "admin_create_user": self._handle_auth_admin_create_user,
            "admin_delete_user": self._handle_auth_admin_delete_user,
            "admin_update_user": self._handle_auth_admin_update_user,
            # Storage operations
            "create_storage_bucket": self._handle_storage_create_bucket,
            "list_storage_buckets": self._handle_storage_list_buckets,
            "get_storage_bucket": self._handle_storage_get_bucket,
            "delete_storage_bucket": self._handle_storage_delete_bucket,
            "empty_storage_bucket": self._handle_storage_empty_bucket,
            "upload_storage_file": self._handle_storage_upload_file,
            "download_storage_file": self._handle_storage_download_file,
            "list_bucket_files": self._handle_storage_list_files,
            "delete_storage_file": self._handle_storage_delete_file,
            "move_storage_file": self._handle_storage_move_file,
            "copy_storage_file": self._handle_storage_copy_file,
            "create_file_signed_url": self._handle_storage_create_signed_url,
            "get_file_public_url": self._handle_storage_get_public_url,
            # Realtime operations
            "broadcast_realtime_message": self._handle_realtime_broadcast,
            # Edge Functions operations
            "invoke_edge_function": self._handle_edge_function_invoke,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    def _get_api_key(self, credentials: SupabaseCredential) -> str:
        """
        Return the API key to use for Supabase REST API calls.

        - API key credential: returns the configured api_key directly.
        - OAuth credential: prefers service_role_key (admin ops), falls back to anon_key.
          Both are fetched from the Management API once during OAuth token exchange and
          cached in the credential so no extra round-trips are needed at execution time.
        """
        if isinstance(credentials, SupabaseOAuthCredential):
            key = credentials.service_role_key or credentials.anon_key
            if not key:
                raise ValueError(
                    "OAuth credential is missing project API keys. "
                    "Please reconnect your Supabase account to refresh them."
                )
            return key
        return credentials.api_key

    async def _ensure_fresh_oauth_token(self, credentials: SupabaseCredential) -> None:
        """
        If credentials are OAuth and the Management API access_token is expired,
        refresh it in-place. This is only needed if the caller wants to make
        Management API calls — REST API calls use the cached anon/service_role keys
        which don't expire and don't require a valid access_token.

        Currently called proactively to keep the stored token fresh, though node
        operations use cached keys and don't require a valid access_token at runtime.
        """
        if not isinstance(credentials, SupabaseOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="supabase",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    def _get_base_url(self, credentials: SupabaseCredential) -> str:
        """Get the REST API base URL from project URL."""
        project_url = credentials.project_url.rstrip("/")
        return f"{project_url}/rest/v1"

    def _get_auth_url(self, credentials: SupabaseCredential) -> str:
        """Get the Auth API base URL from project URL."""
        project_url = credentials.project_url.rstrip("/")
        return f"{project_url}/auth/v1"

    def _get_storage_url(self, credentials: SupabaseCredential) -> str:
        """Get the Storage API base URL from project URL."""
        project_url = credentials.project_url.rstrip("/")
        return f"{project_url}/storage/v1"

    def _get_realtime_url(self, credentials: SupabaseCredential) -> str:
        """Get the Realtime API base URL from project URL."""
        project_url = credentials.project_url.rstrip("/")
        return f"{project_url}/realtime/v1"

    def _get_functions_url(self, credentials: SupabaseCredential) -> str:
        """Get the Edge Functions API base URL from project URL."""
        project_url = credentials.project_url.rstrip("/")
        return f"{project_url}/functions/v1"

    def _build_filter_params(
        self, filters: Optional[List[Dict[str, str]]]
    ) -> Dict[str, str]:
        """
        Build PostgREST filter query parameters from filter list.

        Args:
            filters: List of filter dicts with column, operator, value

        Returns:
            Dict of query parameters
        """
        params = {}
        if not filters:
            return params

        for f in filters:
            column = f.get("column", "")
            operator = f.get("operator", "eq")
            value = f.get("value", "")

            # Validate operator
            if operator not in self.FILTER_OPERATORS:
                logger.warning(
                    f"[SupabaseNode] Unknown operator '{operator}', using 'eq'"
                )
                operator = "eq"

            # Build filter string
            params[column] = f"{operator}.{value}"

        return params

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: SupabaseCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Supabase REST API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint (table name or /rpc/function_name)
            credentials: Supabase API credentials
            params: Query parameters
            json_body: JSON request body
            headers: Additional headers
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        base_url = self._get_base_url(credentials)
        url = f"{base_url}{endpoint}"

        # Build headers - Supabase requires both apikey and Authorization headers
        api_key = self._get_api_key(credentials)
        request_headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = (
                            error_data.get("message")
                            or error_data.get("error")
                            or str(error_data)
                        )
                        if error_data.get("hint"):
                            error_message += f" (Hint: {error_data.get('hint')})"
                    except Exception:
                        error_message = error_text

                    logger.error(f"[SupabaseNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                # Extract count from headers if available
                result = {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

                # Add count if present in headers
                content_range = response.headers.get("content-range")
                if content_range and "/" in content_range:
                    try:
                        count_str = content_range.split("/")[1]
                        if count_str != "*":
                            result["count"] = int(count_str)
                    except (ValueError, IndexError):
                        pass

                return result

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[SupabaseNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Operation Handlers
    # =========================================================================

    async def _handle_select(
        self, config: SupabaseSelectConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Select rows from a table."""
        # Build query parameters
        params: Dict[str, Any] = {}

        # Select columns
        if config.columns:
            params["select"] = config.columns

        # Add filters
        filter_params = self._build_filter_params(config.filters)
        params.update(filter_params)

        # Ordering
        if config.order_by:
            params["order"] = config.order_by

        # Pagination
        if config.limit is not None:
            params["limit"] = config.limit
        if config.offset is not None:
            params["offset"] = config.offset

        # Headers for special options
        headers = {}
        if config.single:
            headers["Accept"] = "application/vnd.pgrst.object+json"
        if config.count:
            headers["Prefer"] = f"count={config.count}"

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.table}",
            credentials=credentials,
            params=params if params else None,
            headers=headers if headers else None,
            action_name="select_table_rows",
        )

    async def _handle_insert(
        self, config: SupabaseInsertConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Insert rows into a table."""
        # Build headers
        headers = {}
        prefer_parts = []

        if config.return_data:
            prefer_parts.append("return=representation")
        else:
            prefer_parts.append("return=minimal")

        if config.on_conflict:
            prefer_parts.append("resolution=merge-duplicates")
        elif config.ignore_duplicates:
            prefer_parts.append("resolution=ignore-duplicates")

        if not config.default_to_null:
            prefer_parts.append("missing=default")

        if prefer_parts:
            headers["Prefer"] = ",".join(prefer_parts)

        # Query params for on_conflict column
        params = {}
        if config.on_conflict:
            params["on_conflict"] = config.on_conflict

        return await self._make_request(
            method="POST",
            endpoint=f"/{config.table}",
            credentials=credentials,
            params=params if params else None,
            json_body=config.rows,
            headers=headers if headers else None,
            action_name="insert_table_rows",
        )

    async def _handle_update(
        self, config: SupabaseUpdateConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Update rows in a table."""
        # Build filter params
        params = self._build_filter_params(config.filters)

        # Headers
        headers = {}
        if config.return_data:
            headers["Prefer"] = "return=representation"
        else:
            headers["Prefer"] = "return=minimal"

        return await self._make_request(
            method="PATCH",
            endpoint=f"/{config.table}",
            credentials=credentials,
            params=params if params else None,
            json_body=config.values,
            headers=headers if headers else None,
            action_name="update_table_rows",
        )

    async def _handle_delete(
        self, config: SupabaseDeleteConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Delete rows from a table."""
        # Build filter params
        params = self._build_filter_params(config.filters)

        # Headers
        headers = {}
        if config.return_data:
            headers["Prefer"] = "return=representation"
        else:
            headers["Prefer"] = "return=minimal"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/{config.table}",
            credentials=credentials,
            params=params if params else None,
            headers=headers if headers else None,
            action_name="delete_table_rows",
        )

    async def _handle_upsert(
        self, config: SupabaseUpsertConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Upsert (insert or update) rows in a table."""
        # Build headers
        headers = {}
        prefer_parts = []

        if config.return_data:
            prefer_parts.append("return=representation")
        else:
            prefer_parts.append("return=minimal")

        if config.ignore_duplicates:
            prefer_parts.append("resolution=ignore-duplicates")
        else:
            prefer_parts.append("resolution=merge-duplicates")

        if not config.default_to_null:
            prefer_parts.append("missing=default")

        if prefer_parts:
            headers["Prefer"] = ",".join(prefer_parts)

        # Query params for on_conflict column
        params = {}
        if config.on_conflict:
            params["on_conflict"] = config.on_conflict

        return await self._make_request(
            method="POST",
            endpoint=f"/{config.table}",
            credentials=credentials,
            params=params if params else None,
            json_body=config.rows,
            headers=headers if headers else None,
            action_name="upsert_table_rows",
        )

    async def _handle_rpc(
        self, config: SupabaseRpcConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Call a database function (RPC)."""
        # Headers
        headers = {}
        prefer_parts = []

        if config.return_data:
            prefer_parts.append("return=representation")
        else:
            prefer_parts.append("return=minimal")

        if config.single:
            headers["Accept"] = "application/vnd.pgrst.object+json"

        if config.count:
            prefer_parts.append(f"count={config.count}")

        if prefer_parts:
            headers["Prefer"] = ",".join(prefer_parts)

        return await self._make_request(
            method="POST",
            endpoint=f"/rpc/{config.function_name}",
            credentials=credentials,
            json_body=config.params if config.params else {},
            headers=headers if headers else None,
            action_name="call_database_function",
        )

    # =========================================================================
    # Auth API Handlers
    # =========================================================================

    async def _make_auth_request(
        self,
        endpoint: str,
        credentials: SupabaseCredential,
        method: str = "POST",
        json_body: Optional[Dict[str, Any]] = None,
        access_token: Optional[str] = None,
        action_name: str = "auth",
    ) -> Dict[str, Any]:
        """Make a request to the Auth API."""
        auth_url = self._get_auth_url(credentials)
        url = f"{auth_url}{endpoint}"

        api_key = self._get_api_key(credentials)
        headers = {
            "apikey": api_key,
            "Content-Type": "application/json",
        }

        # Add Authorization header if access_token is provided
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method, url=url, headers=headers, json=json_body
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = (
                            error_data.get("msg")
                            or error_data.get("message")
                            or error_data.get("error_description")
                            or str(error_data)
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[SupabaseNode] Auth API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[SupabaseNode] Auth request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def _handle_auth_signup(
        self, config: SupabaseAuthSignUpConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Sign up a new user."""
        body = {"email": config.email, "password": config.password}

        if config.user_metadata:
            body["data"] = config.user_metadata
        if config.email_redirect_to:
            body["gotrue_meta_security"] = {"redirectTo": config.email_redirect_to}

        return await self._make_auth_request(
            endpoint="/signup",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="sign_up_user",
        )

    async def _handle_auth_signin_password(
        self, config: SupabaseAuthSignInPasswordConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Sign in with email and password."""
        body = {
            "email": config.email,
            "password": config.password,
            "gotrue_meta_security": {},
        }

        return await self._make_auth_request(
            endpoint="/token?grant_type=password",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="sign_in_with_password",
        )

    async def _handle_auth_signin_magiclink(
        self, config: SupabaseAuthSignInMagicLinkConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Send a magic link for passwordless signin."""
        body = {"email": config.email}

        if config.email_redirect_to:
            body["gotrue_meta_security"] = {"redirectTo": config.email_redirect_to}

        return await self._make_auth_request(
            endpoint="/otp",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="send_magic_link_signin",
        )

    async def _handle_auth_signout(
        self, config: SupabaseAuthSignOutConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Sign out the current user."""
        return await self._make_auth_request(
            endpoint="/logout",
            credentials=credentials,
            method="POST",
            json_body={},
            access_token=config.access_token,
            action_name="sign_out_user",
        )

    async def _handle_auth_get_user(
        self, config: SupabaseAuthGetUserConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Get current user details."""
        return await self._make_auth_request(
            endpoint="/user",
            credentials=credentials,
            method="GET",
            access_token=config.access_token,
            action_name="get_current_user",
        )

    async def _handle_auth_update_user(
        self, config: SupabaseAuthUpdateUserConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Update current user."""
        body = {}

        if config.email:
            body["email"] = config.email
        if config.password:
            body["password"] = config.password
        if config.user_metadata:
            body["data"] = config.user_metadata

        return await self._make_auth_request(
            endpoint="/user",
            credentials=credentials,
            method="PUT",
            json_body=body,
            access_token=config.access_token,
            action_name="update_current_user",
        )

    async def _handle_auth_reset_password(
        self, config: SupabaseAuthResetPasswordConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Send password reset email."""
        body = {"email": config.email}

        if config.redirect_to:
            body["gotrue_meta_security"] = {"redirectTo": config.redirect_to}

        return await self._make_auth_request(
            endpoint="/recover",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="send_password_reset_email",
        )

    async def _handle_auth_verify_otp(
        self, config: SupabaseAuthVerifyOTPConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Verify OTP code."""
        body = {"token": config.token, "type": config.type}

        if config.email:
            body["email"] = config.email
        if config.phone:
            body["phone"] = config.phone

        return await self._make_auth_request(
            endpoint="/verify",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="verify_otp_code",
        )

    async def _handle_auth_refresh_token(
        self, config: SupabaseAuthRefreshTokenConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Refresh an expired access token."""
        body = {"refresh_token": config.refresh_token}

        return await self._make_auth_request(
            endpoint="/token?grant_type=refresh_token",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="refresh_access_token",
        )

    async def _handle_auth_admin_list_users(
        self, config: SupabaseAuthAdminListUsersConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """List all users (admin operation)."""
        params = {"page": config.page, "per_page": config.per_page}

        auth_url = self._get_auth_url(credentials)
        url = f"{auth_url}/admin/users"

        api_key = self._get_api_key(credentials)
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",  # service_role key required
            "Content-Type": "application/json",
        }

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=headers, params=params)
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_data = response.json() if response.text else {}
                    error_message = (
                        error_data.get("msg")
                        or error_data.get("error")
                        or response.text
                    )
                    return {
                        "status": "error",
                        "action": "admin_list_users",
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                data = response.json()
                return {
                    "status": "success",
                    "action": "admin_list_users",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except Exception as e:
                logger.exception(f"[SupabaseNode] Admin list users failed: {e}")
                return {
                    "status": "error",
                    "action": "admin_list_users",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def _handle_auth_admin_create_user(
        self, config: SupabaseAuthAdminCreateUserConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Create a new user (admin operation)."""
        body = {"email": config.email, "email_confirm": config.email_confirm or False}

        if config.password:
            body["password"] = config.password
        if config.user_metadata:
            body["user_metadata"] = config.user_metadata

        return await self._make_auth_request(
            endpoint="/admin/users",
            credentials=credentials,
            method="POST",
            json_body=body,
            access_token=self._get_api_key(credentials),  # service_role key
            action_name="admin_create_user",
        )

    async def _handle_auth_admin_delete_user(
        self, config: SupabaseAuthAdminDeleteUserConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Delete a user (admin operation)."""
        return await self._make_auth_request(
            endpoint=f"/admin/users/{config.user_id}",
            credentials=credentials,
            method="DELETE",
            access_token=self._get_api_key(credentials),  # service_role key
            action_name="admin_delete_user",
        )

    async def _handle_auth_admin_update_user(
        self, config: SupabaseAuthAdminUpdateUserConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Update a user (admin operation)."""
        body = {}

        if config.email:
            body["email"] = config.email
        if config.password:
            body["password"] = config.password
        if config.email_confirm is not None:
            body["email_confirm"] = config.email_confirm
        if config.user_metadata:
            body["user_metadata"] = config.user_metadata
        if config.app_metadata:
            body["app_metadata"] = config.app_metadata

        return await self._make_auth_request(
            endpoint=f"/admin/users/{config.user_id}",
            credentials=credentials,
            method="PUT",
            json_body=body,
            access_token=self._get_api_key(credentials),  # service_role key
            action_name="admin_update_user",
        )

    # =========================================================================
    # Storage API Handlers
    # =========================================================================

    async def _make_storage_request(
        self,
        endpoint: str,
        credentials: SupabaseCredential,
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
        body_bytes: Optional[bytes] = None,
        content_type: Optional[str] = None,
        action_name: str = "storage",
    ) -> Dict[str, Any]:
        """Make a request to the Storage API."""
        storage_url = self._get_storage_url(credentials)
        url = f"{storage_url}{endpoint}"

        api_key = self._get_api_key(credentials)
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
        }

        if content_type:
            headers["Content-Type"] = content_type
        elif json_body is not None:
            headers["Content-Type"] = "application/json"

        start_time = time.time()

        async with guarded_async_client(
            timeout=60.0
        ) as client:  # Longer timeout for file uploads
            try:
                kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers,
                }

                if json_body is not None:
                    kwargs["json"] = json_body
                elif body_bytes is not None:
                    kwargs["content"] = body_bytes

                response = await client.request(**kwargs)

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = (
                            error_data.get("message")
                            or error_data.get("error")
                            or str(error_data)
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[SupabaseNode] Storage API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        # For file downloads, return raw bytes
                        if method == "GET" and "download" in endpoint:
                            from nodes.core.binary_output import BinaryOutput

                            mime = (
                                response.headers.get("content-type")
                                or "application/octet-stream"
                            )
                            filename = endpoint.rstrip("/").rsplit("/", 1)[-1] or "download"
                            data = {
                                "content": BinaryOutput(
                                    data=response.content,
                                    content_type=mime,
                                    filename=filename,
                                ),
                            }
                        else:
                            data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[SupabaseNode] Storage request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def _handle_storage_create_bucket(
        self, config: SupabaseStorageCreateBucketConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Create a new storage bucket."""
        body = {
            "id": config.bucket_name,
            "name": config.bucket_name,
            "public": config.public or False,
        }

        if config.file_size_limit is not None:
            body["file_size_limit"] = config.file_size_limit
        if config.allowed_mime_types:
            body["allowed_mime_types"] = config.allowed_mime_types

        return await self._make_storage_request(
            endpoint="/bucket",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="create_storage_bucket",
        )

    async def _handle_storage_list_buckets(
        self, config: SupabaseStorageListBucketsConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """List all storage buckets."""
        return await self._make_storage_request(
            endpoint="/bucket",
            credentials=credentials,
            method="GET",
            action_name="list_storage_buckets",
        )

    async def _handle_storage_get_bucket(
        self, config: SupabaseStorageGetBucketConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Get bucket details."""
        return await self._make_storage_request(
            endpoint=f"/bucket/{config.bucket_name}",
            credentials=credentials,
            method="GET",
            action_name="get_storage_bucket",
        )

    async def _handle_storage_delete_bucket(
        self, config: SupabaseStorageDeleteBucketConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Delete a storage bucket."""
        return await self._make_storage_request(
            endpoint=f"/bucket/{config.bucket_name}",
            credentials=credentials,
            method="DELETE",
            action_name="delete_storage_bucket",
        )

    async def _handle_storage_empty_bucket(
        self, config: SupabaseStorageEmptyBucketConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Empty a storage bucket."""
        return await self._make_storage_request(
            endpoint=f"/bucket/{config.bucket_name}/empty",
            credentials=credentials,
            method="POST",
            json_body={},
            action_name="empty_storage_bucket",
        )

    async def _handle_storage_upload_file(
        self, config: SupabaseStorageUploadFileConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Upload a file to storage."""
        import base64

        from nodes.core.media_resolver import looks_like_media_ref, resolve_media_input

        resolved_mime = None
        # A media reference (uploaded file, URL, data: URI, or upstream resource id)
        # resolves to the file's bytes. Plain text / base64 keeps the existing path.
        if looks_like_media_ref(config.file_content):
            resolved = await resolve_media_input(config.file_content)
            file_bytes = resolved.data
            resolved_mime = resolved.mime_type
        else:
            try:
                file_bytes = base64.b64decode(config.file_content)
            except Exception:
                # If not base64, treat as plain text
                file_bytes = config.file_content.encode("utf-8")

        # Build URL with upsert parameter
        endpoint = f"/object/{config.bucket_name}/{config.file_path}"
        if config.upsert:
            endpoint += "?upsert=true"

        return await self._make_storage_request(
            endpoint=endpoint,
            credentials=credentials,
            method="POST",
            body_bytes=file_bytes,
            content_type=config.content_type
            or resolved_mime
            or "application/octet-stream",
            action_name="upload_storage_file",
        )

    async def _handle_storage_download_file(
        self, config: SupabaseStorageDownloadFileConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Download a file from storage."""
        return await self._make_storage_request(
            endpoint=f"/object/{config.bucket_name}/{config.file_path}",
            credentials=credentials,
            method="GET",
            action_name="download_storage_file",
        )

    async def _handle_storage_list_files(
        self, config: SupabaseStorageListFilesConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """List files in a storage bucket folder."""
        body = {
            "prefix": config.folder_path or "",
            "limit": config.limit or 100,
            "offset": config.offset or 0,
        }

        if config.search:
            body["search"] = config.search

        return await self._make_storage_request(
            endpoint=f"/object/list/{config.bucket_name}",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="list_bucket_files",
        )

    async def _handle_storage_delete_file(
        self, config: SupabaseStorageDeleteFileConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Delete a file from storage."""
        # Convert single path to array if needed
        file_paths = (
            [config.file_paths]
            if isinstance(config.file_paths, str)
            else config.file_paths
        )

        body = {"prefixes": file_paths}

        return await self._make_storage_request(
            endpoint=f"/object/{config.bucket_name}",
            credentials=credentials,
            method="DELETE",
            json_body=body,
            action_name="delete_storage_file",
        )

    async def _handle_storage_move_file(
        self, config: SupabaseStorageMoveFileConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Move a file within or between buckets."""
        body = {
            "bucketId": config.bucket_name,
            "sourceKey": config.from_path,
            "destinationKey": config.to_path,
        }

        return await self._make_storage_request(
            endpoint=f"/object/move",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="move_storage_file",
        )

    async def _handle_storage_copy_file(
        self, config: SupabaseStorageCopyFileConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Copy a file within or between buckets."""
        body = {
            "bucketId": config.bucket_name,
            "sourceKey": config.from_path,
            "destinationKey": config.to_path,
        }

        return await self._make_storage_request(
            endpoint=f"/object/copy",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="copy_storage_file",
        )

    async def _handle_storage_create_signed_url(
        self,
        config: SupabaseStorageCreateSignedURLConfig,
        credentials: SupabaseCredential,
    ) -> Dict[str, Any]:
        """Create a signed URL for temporary file access."""
        body = {"expiresIn": config.expires_in}

        return await self._make_storage_request(
            endpoint=f"/object/sign/{config.bucket_name}/{config.file_path}",
            credentials=credentials,
            method="POST",
            json_body=body,
            action_name="create_file_signed_url",
        )

    async def _handle_storage_get_public_url(
        self, config: SupabaseStorageGetPublicURLConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Get public URL for a file in a public bucket."""
        # Public URLs are constructed client-side, not an API call
        storage_url = self._get_storage_url(credentials)
        public_url = (
            f"{storage_url}/object/public/{config.bucket_name}/{config.file_path}"
        )

        return {
            "status": "success",
            "action": "get_file_public_url",
            "data": {"public_url": public_url},
            "status_code": 200,
            "timing_ms": {"api_request": 0},
        }

    # =========================================================================
    # Realtime API Handlers
    # =========================================================================

    async def _handle_realtime_broadcast(
        self, config: SupabaseRealtimeBroadcastConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Broadcast a message to a Realtime channel."""
        realtime_url = self._get_realtime_url(credentials)
        url = f"{realtime_url}/api/broadcast"

        api_key = self._get_api_key(credentials)
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "messages": [
                {
                    "topic": config.channel,
                    "event": config.event,
                    "payload": config.payload,
                }
            ]
        }

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=body)
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = (
                            error_data.get("message")
                            or error_data.get("error")
                            or str(error_data)
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(
                        f"[SupabaseNode] Realtime broadcast error: {error_message}"
                    )
                    return {
                        "status": "error",
                        "action": "broadcast_realtime_message",
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                try:
                    data = response.json()
                except Exception:
                    data = {"success": True}

                return {
                    "status": "success",
                    "action": "broadcast_realtime_message",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": "broadcast_realtime_message",
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[SupabaseNode] Realtime broadcast failed: {e}")
                return {
                    "status": "error",
                    "action": "broadcast_realtime_message",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Edge Functions API Handlers
    # =========================================================================

    async def _handle_edge_function_invoke(
        self, config: SupabaseEdgeFunctionInvokeConfig, credentials: SupabaseCredential
    ) -> Dict[str, Any]:
        """Invoke a Supabase Edge Function."""
        functions_url = self._get_functions_url(credentials)
        url = f"{functions_url}/{config.function_name}"

        api_key = self._get_api_key(credentials)
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Add custom headers if provided
        if config.headers:
            headers.update(config.headers)

        start_time = time.time()

        async with guarded_async_client(
            timeout=60.0
        ) as client:  # Longer timeout for functions
            try:
                response = await client.request(
                    method=config.method,
                    url=url,
                    headers=headers,
                    json=config.body if config.body else None,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = (
                            error_data.get("message")
                            or error_data.get("error")
                            or str(error_data)
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[SupabaseNode] Edge function error: {error_message}")
                    return {
                        "status": "error",
                        "action": "invoke_edge_function",
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                try:
                    data = response.json()
                except Exception:
                    # Function might return non-JSON (text, HTML, etc.)
                    data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": "invoke_edge_function",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": "invoke_edge_function",
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[SupabaseNode] Edge function invocation failed: {e}")
                return {
                    "status": "error",
                    "action": "invoke_edge_function",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
