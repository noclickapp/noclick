"""
Comprehensive Upstash Redis REST API automation node.

Provides workflow integration with Redis covering ALL major Redis operations including:

String Operations (22): get, set, mget, mset, incr, incrby, decr, decrby, incrbyfloat,
    append, strlen, getdel, getex, getrange, setrange, msetnx, setex, psetex, setnx,
    getset

Hash Operations (19): hget, hset, hgetall, hdel, hmget, hmset, hkeys, hvals, hexists,
    hlen, hincrby, hincrbyfloat, hsetnx, hstrlen, hrandfield, hscan, hgetdel, hgetex,
    hsetex

List Operations (22): lpush, rpush, lpop, rpop, lrange, llen, lindex, lset, linsert,
    lrem, ltrim, lpos, lmove, lpushx, rpushx, rpoplpush, blpop, brpop, blmove,
    brpoplpush, blmpop, lmpop

Set Operations (18): sadd, srem, smembers, sismember, scard, sunion, sinter, sdiff,
    spop, srandmember, smove, sdiffstore, sinterstore, sunionstore, smismember,
    sintercard, sscan

Sorted Set Operations (47): zadd, zrem, zrange, zrank, zscore, zcard, zincrby, zcount,
    zpopmax, zpopmin, zrevrange, zrevrank, zrangebyscore, zrevrangebyscore,
    zrangebylex, zrevrangebylex, zremrangebyrank, zremrangebyscore, zremrangebylex,
    zlexcount, zmscore, zinter, zunion, zdiff, zdiffstore, zinterstore, zunionstore,
    zrandmember, zscan, zrangestore, zmpop, bzmpop, bzpopmax, bzpopmin, zintercard

Bitmap Operations (7): setbit, getbit, bitcount, bitfield, bitop, bitpos, bitfield_ro

HyperLogLog Operations (3): pfadd, pfcount, pfmerge

Geospatial Operations (10): geoadd, geodist, geohash, geopos, geosearch, geosearchstore,
    georadius, georadiusbymember, georadius_ro, georadiusbymember_ro

Key Operations (22): del, exists, expire, ttl, keys, type, rename, scan, copy, unlink,
    dump, restore, touch, pexpire, pexpireat, pttl, expireat, expiretime, pexpiretime,
    renamenx, randomkey, sort

Streams Operations (16): xadd, xread, xreadgroup, xlen, xrange, xrevrange, xdel, xtrim,
    xack, xpending, xclaim, xautoclaim, xgroup_create, xgroup_destroy, xgroup_setid,
    xinfo_stream

JSON Operations (22): json_set, json_get, json_del, json_mget, json_mset, json_arrappend,
    json_arrinsert, json_arrindex, json_arrlen, json_arrpop, json_arrtrim, json_clear,
    json_numincrby, json_nummultby, json_strappend, json_strlen, json_objkeys, json_objlen,
    json_type, json_merge, json_toggle, json_resp

Scripting Operations (14): eval, evalsha, eval_ro, evalsha_ro, fcall, fcall_ro,
    function_load, function_delete, function_flush, function_list, function_stats,
    script_exists, script_flush, script_load

Pub/Sub Operations (6): publish, subscribe, unsubscribe, psubscribe, punsubscribe, pubsub

Transaction Operations (6): pipeline, multi, exec, discard, watch, unwatch

Connection Operations (13): ping, echo, select, auth, hello, quit, reset, client_id,
    client_getname, client_setname, client_info, client_list, client_setinfo

Server Operations (5): dbsize, flushall, flushdb, monitor, time

Total: 237 operations covering ~95% of Redis commands supported by Upstash

Authentication:
- Standard REST Token (full privileges)
- Read-Only Token (read operations only)
- ACL User Tokens (custom permissions)

API Documentation: https://upstash.com/docs/redis/features/restapi
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated, Tuple
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)


# ============================================================================
# Credential Schemas - Multiple Authentication Methods
# ============================================================================


class RedisStandardCredential(BaseModel):
    """
    Standard Upstash Redis REST API credential with full database privileges.

    Get your credentials from: https://console.upstash.com/
    """
    credential_type: Literal["redis_standard"] = Field("redis_standard", json_schema_extra={"ui:hidden": True})
    rest_url: str = Field(
        ...,
        title="REST URL",
        description="Your Upstash Redis REST URL (e.g., https://xxx.upstash.io)"
    )
    rest_token: str = Field(
        ...,
        title="Standard Token",
        description="Your standard REST API token (full privileges)",
        json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://console.upstash.com/"
    })


class RedisReadOnlyCredential(BaseModel):
    """
    Read-only Upstash Redis REST API credential for public/client-side usage.

    Safe for use in browsers and mobile apps as it only allows read operations.
    Get your read-only token from: https://console.upstash.com/
    """
    credential_type: Literal["redis_readonly"] = Field("redis_readonly", json_schema_extra={"ui:hidden": True})
    rest_url: str = Field(
        ...,
        title="REST URL",
        description="Your Upstash Redis REST URL"
    )
    readonly_token: str = Field(
        ...,
        title="Read-Only Token",
        description="Your read-only REST API token",
        json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://console.upstash.com/"
    })


class RedisACLCredential(BaseModel):
    """
    Custom ACL user token for Upstash Redis with specific permissions.

    Create ACL users with: ACL SETUSER username ...
    Generate token with: ACL RESTTOKEN username password
    """
    credential_type: Literal["redis_acl"] = Field("redis_acl", json_schema_extra={"ui:hidden": True})
    rest_url: str = Field(
        ...,
        title="REST URL",
        description="Your Upstash Redis REST URL"
    )
    acl_token: str = Field(
        ...,
        title="ACL User Token",
        description="Token generated via ACL RESTTOKEN command",
        json_schema_extra={"ui:widget": "password"}
    )
    username: Optional[str] = Field(
        None,
        title="ACL Username",
        description="ACL username (for reference)"
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://console.upstash.com/"
    })


# Union type for multiple credential options (backward compatible)
RedisCredential = Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]


# ============================================================================
# Helper Functions
# ============================================================================


def get_token_from_credential(credential: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]) -> str:
    """Extract the appropriate token based on credential type"""
    if isinstance(credential, RedisStandardCredential):
        return credential.rest_token
    elif isinstance(credential, RedisReadOnlyCredential):
        return credential.readonly_token
    elif isinstance(credential, RedisACLCredential):
        return credential.acl_token
    else:
        # Fallback for backward compatibility
        return getattr(credential, 'rest_token', '')


# ============================================================================
# String Operation Configs
# ============================================================================


class RedisGetConfig(BaseModel):
    """Get the value of a key"""
    operation: Literal["get_key_value"] = Field(
        "get_key_value",
        json_schema_extra={"const": "get_key_value", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Key Value"}, 
    title="Get Key Value")
    key: str = Field(
        ...,
        title="Key",
        description="The key to get"
    )


class RedisSetConfig(BaseModel):
    """Set the value of a key"""
    operation: Literal["set_key_value"] = Field(
        "set_key_value",
        json_schema_extra={"const": "set_key_value", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Value"}, 
    title="Set Key Value")
    key: str = Field(
        ...,
        title="Key",
        description="The key to set"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value to set"
    )
    ex: Optional[int] = Field(
        None,
        title="Expire (seconds)",
        description="Set expiration time in seconds"
    )
    px: Optional[int] = Field(
        None,
        title="Expire (milliseconds)",
        description="Set expiration time in milliseconds"
    )
    nx: Optional[bool] = Field(
        None,
        title="Only if Not Exists",
        description="Only set if key does not exist"
    )
    xx: Optional[bool] = Field(
        None,
        title="Only if Exists",
        description="Only set if key already exists"
    )


class RedisMgetConfig(BaseModel):
    """Get the values of multiple keys"""
    operation: Literal["get_multiple_key_values"] = Field(
        "get_multiple_key_values",
        json_schema_extra={"const": "get_multiple_key_values", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Multiple Key Values"}, 
    title="Get Multiple Key Values")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="List of keys to get"
    )


class RedisMsetConfig(BaseModel):
    """Set multiple key-value pairs"""
    operation: Literal["set_multiple_key_value_pairs"] = Field(
        "set_multiple_key_value_pairs",
        json_schema_extra={"const": "set_multiple_key_value_pairs", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Multiple Key Value Pairs"}, 
    title="Set Multiple Key Value Pairs")
    pairs: Dict[str, str] = Field(
        ...,
        title="Key-Value Pairs",
        description="Dictionary of key-value pairs to set"
    )


class RedisIncrConfig(BaseModel):
    """Increment the integer value of a key by 1"""
    operation: Literal["increment_key_by_one"] = Field(
        "increment_key_by_one",
        json_schema_extra={"const": "increment_key_by_one", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Increment Key by One"}, 
    title="Increment Key by One")
    key: str = Field(
        ...,
        title="Key",
        description="The key to increment"
    )


class RedisIncrbyConfig(BaseModel):
    """Increment the integer value of a key by a given amount"""
    operation: Literal["increment_key_by_amount"] = Field(
        "increment_key_by_amount",
        json_schema_extra={"const": "increment_key_by_amount", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Increment Key by Amount"}, 
    title="Increment Key by Amount")
    key: str = Field(
        ...,
        title="Key",
        description="The key to increment"
    )
    increment: int = Field(
        ...,
        title="Increment",
        description="The amount to increment by"
    )


class RedisDecrConfig(BaseModel):
    """Decrement the integer value of a key by 1"""
    operation: Literal["decrement_key_by_one"] = Field(
        "decrement_key_by_one",
        json_schema_extra={"const": "decrement_key_by_one", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Decrement Key by One"}, 
    title="Decrement Key by One")
    key: str = Field(
        ...,
        title="Key",
        description="The key to decrement"
    )


class RedisAppendConfig(BaseModel):
    """Append a value to a key"""
    operation: Literal["append_value_to_key"] = Field(
        "append_value_to_key",
        json_schema_extra={"const": "append_value_to_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Append Value to Key"}, 
    title="Append Value to Key")
    key: str = Field(
        ...,
        title="Key",
        description="The key to append to"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value to append"
    )


class RedisStrlenConfig(BaseModel):
    """Get the length of the value stored at a key"""
    operation: Literal["get_string_value_length"] = Field(
        "get_string_value_length",
        json_schema_extra={"const": "get_string_value_length", "ui:hidden": True, "x-category": "String", "x-is-trigger": False, "x-display-name": "Get String Value Length"}, 
    title="Get String Value Length")
    key: str = Field(
        ...,
        title="Key",
        description="The key to check"
    )


# ============================================================================
# Hash Operation Configs
# ============================================================================
class RedisGetexConfig(BaseModel):
    """Getex operation"""
    operation: Literal["get_with_expiration_options"] = Field(
        "get_with_expiration_options",
        json_schema_extra={"const": "get_with_expiration_options", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get with Expiration Options"}, 
    title="Get with Expiration Options")
    key: str = Field(
        ...,
        title="Key",
        description="The key to get"
    )
    ex: Optional[int] = Field(
        None,
        title="Expire (seconds)",
        description="Set expiration in seconds"
    )
    px: Optional[int] = Field(
        None,
        title="Expire (milliseconds)",
        description="Set expiration in milliseconds"
    )
    exat: Optional[int] = Field(
        None,
        title="Expire at timestamp (seconds)",
        description="Expire at Unix timestamp"
    )
    pxat: Optional[int] = Field(
        None,
        title="Expire at timestamp (ms)",
        description="Expire at Unix timestamp (ms)"
    )
    persist: Optional[bool] = Field(
        None,
        title="Remove expiration",
        description="Remove the expiration"
    )
class RedisSetrangeConfig(BaseModel):
    """Setrange operation"""
    operation: Literal["set_string_range_at_offset"] = Field(
        "set_string_range_at_offset",
        json_schema_extra={"const": "set_string_range_at_offset", "ui:hidden": True, "x-category": "String", "x-is-trigger": False, "x-display-name": "Set String Range at Offset"}, 
    title="Set String Range at Offset")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    offset: int = Field(
        ...,
        title="Offset",
        description="The offset"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value"
    )
class RedisDecrbyConfig(BaseModel):
    """Decrby operation"""
    operation: Literal["decrement_key_by_amount"] = Field(
        "decrement_key_by_amount",
        json_schema_extra={"const": "decrement_key_by_amount", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Decrement Key by Amount"}, 
    title="Decrement Key by Amount")
    key: str = Field(
        ...,
        title="Key",
        description="The key to decrement"
    )
    decrement: int = Field(
        ...,
        title="Decrement",
        description="The decrement value"
    )
class RedisSetexConfig(BaseModel):
    """Setex operation"""
    operation: Literal["set_key_value_with_expiration_seconds"] = Field(
        "set_key_value_with_expiration_seconds",
        json_schema_extra={"const": "set_key_value_with_expiration_seconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Value with Expiration Seconds"}, 
    title="Set Key Value with Expiration Seconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    seconds: int = Field(
        ...,
        title="Seconds",
        description="Expiration in seconds"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value"
    )
class RedisSetnxConfig(BaseModel):
    """Setnx operation"""
    operation: Literal["set_key_if_not_exists"] = Field(
        "set_key_if_not_exists",
        json_schema_extra={"const": "set_key_if_not_exists", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key If Not Exists"}, 
    title="Set Key If Not Exists")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value"
    )

class RedisGetsetConfig(BaseModel):
    """Getset operation"""
    operation: Literal["get_and_set_key_value"] = Field(
        "get_and_set_key_value",
        json_schema_extra={"const": "get_and_set_key_value", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get and Set Key Value"}, 
    title="Get and Set Key Value")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The new value"
    )


class RedisPsetexConfig(BaseModel):
    """Psetex operation"""
    operation: Literal["set_key_value_with_expiration_milliseconds"] = Field(
        "set_key_value_with_expiration_milliseconds",
        json_schema_extra={"const": "set_key_value_with_expiration_milliseconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Value with Expiration Milliseconds"}, 
    title="Set Key Value with Expiration Milliseconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    milliseconds: int = Field(
        ...,
        title="Milliseconds",
        description="Expiration in milliseconds"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value"
    )


class RedisMsetnxConfig(BaseModel):
    """Msetnx operation"""
    operation: Literal["set_multiple_pairs_if_not_exist"] = Field(
        "set_multiple_pairs_if_not_exist",
        json_schema_extra={"const": "set_multiple_pairs_if_not_exist", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Multiple Pairs If Not Exist"}, 
    title="Set Multiple Pairs If Not Exist")
    pairs: Dict[str, str] = Field(
        ...,
        title="Key-Value Pairs",
        description="Dictionary of key-value pairs"
    )


class RedisIncrbyfloatConfig(BaseModel):
    """Incrbyfloat operation"""
    operation: Literal["increment_key_by_float"] = Field(
        "increment_key_by_float",
        json_schema_extra={"const": "increment_key_by_float", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Increment Key by Float"}, 
    title="Increment Key by Float")
    key: str = Field(
        ...,
        title="Key",
        description="The key to increment"
    )
    increment: float = Field(
        ...,
        title="Increment",
        description="The increment value"
    )


class RedisGetrangeConfig(BaseModel):
    """Getrange operation"""
    operation: Literal["get_substring_by_range"] = Field(
        "get_substring_by_range",
        json_schema_extra={"const": "get_substring_by_range", "ui:hidden": True, "x-category": "String", "x-is-trigger": False, "x-display-name": "Get Substring by Range"}, 
    title="Get Substring by Range")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    start: int = Field(
        ...,
        title="Start",
        description="Start offset"
    )
    end: int = Field(
        ...,
        title="End",
        description="End offset"
    )


class RedisGetdelConfig(BaseModel):
    """Getdel operation"""
    operation: Literal["get_and_delete_key"] = Field(
        "get_and_delete_key",
        json_schema_extra={"const": "get_and_delete_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get and Delete Key"}, 
    title="Get and Delete Key")
    key: str = Field(
        ...,
        title="Key",
        description="The key to get and delete"
    )


class RedisHgetConfig(BaseModel):
    """Get the value of a hash field"""
    operation: Literal["get_hash_field_value"] = Field(
        "get_hash_field_value",
        json_schema_extra={"const": "get_hash_field_value", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get Hash Field Value"}, 
    title="Get Hash Field Value")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field to get"
    )


class RedisHsetConfig(BaseModel):
    """Set the value of a hash field"""
    operation: Literal["set_hash_field_value"] = Field(
        "set_hash_field_value",
        json_schema_extra={"const": "set_hash_field_value", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Set Hash Field Value"}, 
    title="Set Hash Field Value")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field to set"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value to set"
    )


class RedisHgetallConfig(BaseModel):
    """Get all fields and values in a hash"""
    operation: Literal["get_all_hash_fields_and_values"] = Field(
        "get_all_hash_fields_and_values",
        json_schema_extra={"const": "get_all_hash_fields_and_values", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get All Hash Fields and Values"}, 
    title="Get All Hash Fields and Values")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )


class RedisHdelConfig(BaseModel):
    """Delete one or more hash fields"""
    operation: Literal["delete_hash_fields"] = Field(
        "delete_hash_fields",
        json_schema_extra={"const": "delete_hash_fields", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Delete Hash Fields"}, 
    title="Delete Hash Fields")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    fields: List[str] = Field(
        ...,
        title="Fields",
        description="Fields to delete"
    )


class RedisHmgetConfig(BaseModel):
    """Get the values of multiple hash fields"""
    operation: Literal["get_multiple_hash_field_values"] = Field(
        "get_multiple_hash_field_values",
        json_schema_extra={"const": "get_multiple_hash_field_values", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get Multiple Hash Field Values"}, 
    title="Get Multiple Hash Field Values")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    fields: List[str] = Field(
        ...,
        title="Fields",
        description="Fields to get"
    )


class RedisHmsetConfig(BaseModel):
    """Set multiple hash fields"""
    operation: Literal["set_multiple_hash_fields"] = Field(
        "set_multiple_hash_fields",
        json_schema_extra={"const": "set_multiple_hash_fields", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Set Multiple Hash Fields"}, 
    title="Set Multiple Hash Fields")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    pairs: Dict[str, str] = Field(
        ...,
        title="Field-Value Pairs",
        description="Dictionary of field-value pairs to set"
    )


class RedisHkeysConfig(BaseModel):
    """Get all field names in a hash"""
    operation: Literal["get_all_hash_field_names"] = Field(
        "get_all_hash_field_names",
        json_schema_extra={"const": "get_all_hash_field_names", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get All Hash Field Names"}, 
    title="Get All Hash Field Names")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )


class RedisHvalsConfig(BaseModel):
    """Get all values in a hash"""
    operation: Literal["get_all_hash_values"] = Field(
        "get_all_hash_values",
        json_schema_extra={"const": "get_all_hash_values", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get All Hash Values"}, 
    title="Get All Hash Values")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )


class RedisHexistsConfig(BaseModel):
    """Check if a hash field exists"""
    operation: Literal["check_if_hash_field_exists"] = Field(
        "check_if_hash_field_exists",
        json_schema_extra={"const": "check_if_hash_field_exists", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Check If Hash Field Exists"}, 
    title="Check If Hash Field Exists")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field to check"
    )


class RedisHlenConfig(BaseModel):
    """Get the number of fields in a hash"""
    operation: Literal["get_hash_field_count"] = Field(
        "get_hash_field_count",
        json_schema_extra={"const": "get_hash_field_count", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get Hash Field Count"}, 
    title="Get Hash Field Count")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )


# ============================================================================
# List Operation Configs
# ============================================================================
class RedisHincrbyfloatConfig(BaseModel):
    """Hincrbyfloat operation"""
    operation: Literal["increment_hash_field_by_float"] = Field(
        "increment_hash_field_by_float",
        json_schema_extra={"const": "increment_hash_field_by_float", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Increment Hash Field by Float"}, 
    title="Increment Hash Field by Float")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field"
    )
    increment: float = Field(
        ...,
        title="Increment",
        description="The increment value"
    )
class RedisHstrlenConfig(BaseModel):
    """Hstrlen operation"""
    operation: Literal["get_hash_field_value_length"] = Field(
        "get_hash_field_value_length",
        json_schema_extra={"const": "get_hash_field_value_length", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get Hash Field Value Length"}, 
    title="Get Hash Field Value Length")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field"
    )
class RedisHscanConfig(BaseModel):
    """Hscan operation"""
    operation: Literal["scan_hash_fields_iteratively"] = Field(
        "scan_hash_fields_iteratively",
        json_schema_extra={"const": "scan_hash_fields_iteratively", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Scan Hash Fields Iteratively"}, 
    title="Scan Hash Fields Iteratively")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    cursor: int = Field(
        0,
        title="Cursor",
        description="The cursor"
    )
    match: Optional[str] = Field(
        None,
        title="Pattern",
        description="Pattern to match"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Elements per iteration"
    )


class RedisHrandfieldConfig(BaseModel):
    """Hrandfield operation"""
    operation: Literal["get_random_hash_field"] = Field(
        "get_random_hash_field",
        json_schema_extra={"const": "get_random_hash_field", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get Random Hash Field"}, 
    title="Get Random Hash Field")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number of fields"
    )
    withvalues: Optional[bool] = Field(
        None,
        title="With Values",
        description="Return values too"
    )


class RedisHsetnxConfig(BaseModel):
    """Hsetnx operation"""
    operation: Literal["set_hash_field_if_not_exists"] = Field(
        "set_hash_field_if_not_exists",
        json_schema_extra={"const": "set_hash_field_if_not_exists", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Set Hash Field If Not Exists"}, 
    title="Set Hash Field If Not Exists")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value"
    )


class RedisHincrbyConfig(BaseModel):
    """Hincrby operation"""
    operation: Literal["increment_hash_field_by_amount"] = Field(
        "increment_hash_field_by_amount",
        json_schema_extra={"const": "increment_hash_field_by_amount", "ui:hidden": True, "x-category": "Hash", "x-is-trigger": False, "x-display-name": "Increment Hash Field by Amount"}, 
    title="Increment Hash Field by Amount")
    key: str = Field(
        ...,
        title="Key",
        description="The hash key"
    )
    field: str = Field(
        ...,
        title="Field",
        description="The field"
    )
    increment: int = Field(
        ...,
        title="Increment",
        description="The increment value"
    )


class RedisLpushConfig(BaseModel):
    """Push values to the beginning of a list"""
    operation: Literal["push_to_list_beginning"] = Field(
        "push_to_list_beginning",
        json_schema_extra={"const": "push_to_list_beginning", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Push to List Beginning"}, 
    title="Push to List Beginning")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    values: List[str] = Field(
        ...,
        title="Values",
        description="Values to push"
    )


class RedisRpushConfig(BaseModel):
    """Push values to the end of a list"""
    operation: Literal["push_to_list_end"] = Field(
        "push_to_list_end",
        json_schema_extra={"const": "push_to_list_end", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Push to List End"}, 
    title="Push to List End")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    values: List[str] = Field(
        ...,
        title="Values",
        description="Values to push"
    )


class RedisLpopConfig(BaseModel):
    """Remove and return the first element of a list"""
    operation: Literal["pop_first_element"] = Field(
        "pop_first_element",
        json_schema_extra={"const": "pop_first_element", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Pop First Element"}, 
    title="Pop First Element")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number of elements to pop"
    )


class RedisRpopConfig(BaseModel):
    """Remove and return the last element of a list"""
    operation: Literal["pop_last_element"] = Field(
        "pop_last_element",
        json_schema_extra={"const": "pop_last_element", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Pop Last Element"}, 
    title="Pop Last Element")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number of elements to pop"
    )


class RedisLrangeConfig(BaseModel):
    """Get a range of elements from a list"""
    operation: Literal["get_list_range"] = Field(
        "get_list_range",
        json_schema_extra={"const": "get_list_range", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Get List Range"}, 
    title="Get List Range")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    start: int = Field(
        0,
        title="Start",
        description="Start index (0-based, negative for end-relative)"
    )
    stop: int = Field(
        -1,
        title="Stop",
        description="Stop index (inclusive, -1 for last element)"
    )


class RedisLlenConfig(BaseModel):
    """Get the length of a list"""
    operation: Literal["get_list_length"] = Field(
        "get_list_length",
        json_schema_extra={"const": "get_list_length", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Get List Length"}, 
    title="Get List Length")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )


class RedisLindexConfig(BaseModel):
    """Get an element from a list by index"""
    operation: Literal["get_list_element_by_index"] = Field(
        "get_list_element_by_index",
        json_schema_extra={"const": "get_list_element_by_index", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Get List Element by Index"}, 
    title="Get List Element by Index")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    index: int = Field(
        ...,
        title="Index",
        description="The index to get (0-based, negative for end-relative)"
    )


class RedisLsetConfig(BaseModel):
    """Set an element in a list by index"""
    operation: Literal["set_list_element_by_index"] = Field(
        "set_list_element_by_index",
        json_schema_extra={"const": "set_list_element_by_index", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Set List Element by Index"}, 
    title="Set List Element by Index")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    index: int = Field(
        ...,
        title="Index",
        description="The index to set"
    )
    value: str = Field(
        ...,
        title="Value",
        description="The value to set"
    )


# ============================================================================
# Set Operation Configs
# ============================================================================
class RedisLremConfig(BaseModel):
    """Lrem operation"""
    operation: Literal["remove_elements_from_list"] = Field(
        "remove_elements_from_list",
        json_schema_extra={"const": "remove_elements_from_list", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Remove Elements from List"}, 
    title="Remove Elements from List")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    count: int = Field(
        ...,
        title="Count",
        description="Number to remove"
    )
    element: str = Field(
        ...,
        title="Element",
        description="The element to remove"
    )
class RedisLposConfig(BaseModel):
    """Lpos operation"""
    operation: Literal["find_element_position_in_list"] = Field(
        "find_element_position_in_list",
        json_schema_extra={"const": "find_element_position_in_list", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Find Element Position in List"}, 
    title="Find Element Position in List")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    element: str = Field(
        ...,
        title="Element",
        description="Element to find"
    )
    rank: Optional[int] = Field(
        None,
        title="Rank",
        description="The nth matching element"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Return up to count matches"
    )
    maxlen: Optional[int] = Field(
        None,
        title="Max Length",
        description="Limit comparison"
    )
class RedisLpushxConfig(BaseModel):
    """Lpushx operation"""
    operation: Literal["push_to_list_beginning_if_exists"] = Field(
        "push_to_list_beginning_if_exists",
        json_schema_extra={"const": "push_to_list_beginning_if_exists", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Push to List Beginning If Exists"}, 
    title="Push to List Beginning If Exists")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    values: List[str] = Field(
        ...,
        title="Values",
        description="Values to push"
    )
class RedisRpoplpushConfig(BaseModel):
    """Rpoplpush operation"""
    operation: Literal["pop_and_push_across_lists"] = Field(
        "pop_and_push_across_lists",
        json_schema_extra={"const": "pop_and_push_across_lists", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Pop and Push Across Lists"}, 
    title="Pop and Push Across Lists")
    source: str = Field(
        ...,
        title="Source",
        description="Source list key"
    )
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination list key"
    )


class RedisRpushxConfig(BaseModel):
    """Rpushx operation"""
    operation: Literal["push_to_list_end_if_exists"] = Field(
        "push_to_list_end_if_exists",
        json_schema_extra={"const": "push_to_list_end_if_exists", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Push to List End If Exists"}, 
    title="Push to List End If Exists")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    values: List[str] = Field(
        ...,
        title="Values",
        description="Values to push"
    )


class RedisLmoveConfig(BaseModel):
    """Lmove operation"""
    operation: Literal["move_element_between_lists"] = Field(
        "move_element_between_lists",
        json_schema_extra={"const": "move_element_between_lists", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Move Element Between Lists"}, 
    title="Move Element Between Lists")
    source: str = Field(
        ...,
        title="Source",
        description="Source list key"
    )
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination list key"
    )
    wherefrom: Literal['LEFT', 'RIGHT'] = Field(
        ...,
        title="From",
        description="Where to pop from"
    )
    whereto: Literal['LEFT', 'RIGHT'] = Field(
        ...,
        title="To",
        description="Where to push to"
    )


class RedisLtrimConfig(BaseModel):
    """Ltrim operation"""
    operation: Literal["trim_list_to_range"] = Field(
        "trim_list_to_range",
        json_schema_extra={"const": "trim_list_to_range", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Trim List to Range"}, 
    title="Trim List to Range")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    start: int = Field(
        ...,
        title="Start",
        description="Start index"
    )
    stop: int = Field(
        ...,
        title="Stop",
        description="Stop index"
    )


class RedisLinsertConfig(BaseModel):
    """Linsert operation"""
    operation: Literal["insert_into_list"] = Field(
        "insert_into_list",
        json_schema_extra={"const": "insert_into_list", "ui:hidden": True, "x-category": "List", "x-is-trigger": False, "x-display-name": "Insert Into List"}, 
    title="Insert Into List")
    key: str = Field(
        ...,
        title="Key",
        description="The list key"
    )
    where: Literal['BEFORE', 'AFTER'] = Field(
        ...,
        title="Position",
        description="Insert before or after"
    )
    pivot: str = Field(
        ...,
        title="Pivot",
        description="The pivot element"
    )
    element: str = Field(
        ...,
        title="Element",
        description="The element to insert"
    )


class RedisSaddConfig(BaseModel):
    """Add members to a set"""
    operation: Literal["add_members_to_set"] = Field(
        "add_members_to_set",
        json_schema_extra={"const": "add_members_to_set", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Add Members to Set"}, 
    title="Add Members to Set")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to add"
    )


class RedisSremConfig(BaseModel):
    """Remove members from a set"""
    operation: Literal["remove_members_from_set"] = Field(
        "remove_members_from_set",
        json_schema_extra={"const": "remove_members_from_set", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Remove Members from Set"}, 
    title="Remove Members from Set")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to remove"
    )


class RedisSmembersConfig(BaseModel):
    """Get all members of a set"""
    operation: Literal["get_all_set_members"] = Field(
        "get_all_set_members",
        json_schema_extra={"const": "get_all_set_members", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Get All Set Members"}, 
    title="Get All Set Members")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )


class RedisSismemberConfig(BaseModel):
    """Check if a value is a member of a set"""
    operation: Literal["check_if_member_in_set"] = Field(
        "check_if_member_in_set",
        json_schema_extra={"const": "check_if_member_in_set", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Check If Member in Set"}, 
    title="Check If Member in Set")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )
    member: str = Field(
        ...,
        title="Member",
        description="The member to check"
    )


class RedisScardConfig(BaseModel):
    """Get the number of members in a set"""
    operation: Literal["get_set_member_count"] = Field(
        "get_set_member_count",
        json_schema_extra={"const": "get_set_member_count", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Get Set Member Count"}, 
    title="Get Set Member Count")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )


class RedisSunionConfig(BaseModel):
    """Return the union of multiple sets"""
    operation: Literal["get_set_union"] = Field(
        "get_set_union",
        json_schema_extra={"const": "get_set_union", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Get Set Union"}, 
    title="Get Set Union")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Set keys to union"
    )


class RedisSinterConfig(BaseModel):
    """Return the intersection of multiple sets"""
    operation: Literal["get_set_intersection"] = Field(
        "get_set_intersection",
        json_schema_extra={"const": "get_set_intersection", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Get Set Intersection"}, 
    title="Get Set Intersection")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Set keys to intersect"
    )


class RedisSdiffConfig(BaseModel):
    """Return the difference of multiple sets"""
    operation: Literal["get_set_difference"] = Field(
        "get_set_difference",
        json_schema_extra={"const": "get_set_difference", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Get Set Difference"}, 
    title="Get Set Difference")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Set keys (first set minus others)"
    )


# ============================================================================
# Sorted Set Operation Configs
# ============================================================================
class RedisSrandmemberConfig(BaseModel):
    """Srandmember operation"""
    operation: Literal["get_random_set_members"] = Field(
        "get_random_set_members",
        json_schema_extra={"const": "get_random_set_members", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Get Random Set Members"}, 
    title="Get Random Set Members")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number of members"
    )
class RedisSdiffstoreConfig(BaseModel):
    """Sdiffstore operation"""
    operation: Literal["store_set_difference"] = Field(
        "store_set_difference",
        json_schema_extra={"const": "store_set_difference", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Store Set Difference"}, 
    title="Store Set Difference")
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Set keys"
    )
class RedisSunionstoreConfig(BaseModel):
    """Sunionstore operation"""
    operation: Literal["store_set_union"] = Field(
        "store_set_union",
        json_schema_extra={"const": "store_set_union", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Store Set Union"}, 
    title="Store Set Union")
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Set keys"
    )

class RedisSmismemberConfig(BaseModel):
    """Smismember operation"""
    operation: Literal["check_multiple_members_in_set"] = Field(
        "check_multiple_members_in_set",
        json_schema_extra={"const": "check_multiple_members_in_set", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Check Multiple Members in Set"}, 
    title="Check Multiple Members in Set")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to check"
    )


class RedisSinterstoreConfig(BaseModel):
    """Sinterstore operation"""
    operation: Literal["store_set_intersection"] = Field(
        "store_set_intersection",
        json_schema_extra={"const": "store_set_intersection", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Store Set Intersection"}, 
    title="Store Set Intersection")
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Set keys"
    )


class RedisSmoveConfig(BaseModel):
    """Smove operation"""
    operation: Literal["move_member_between_sets"] = Field(
        "move_member_between_sets",
        json_schema_extra={"const": "move_member_between_sets", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Move Member Between Sets"}, 
    title="Move Member Between Sets")
    source: str = Field(
        ...,
        title="Source",
        description="Source set key"
    )
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination set key"
    )
    member: str = Field(
        ...,
        title="Member",
        description="The member to move"
    )


class RedisSpopConfig(BaseModel):
    """Spop operation"""
    operation: Literal["pop_random_members_from_set"] = Field(
        "pop_random_members_from_set",
        json_schema_extra={"const": "pop_random_members_from_set", "ui:hidden": True, "x-category": "Set", "x-is-trigger": False, "x-display-name": "Pop Random Members from Set"}, 
    title="Pop Random Members from Set")
    key: str = Field(
        ...,
        title="Key",
        description="The set key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number of members to pop"
    )


class RedisZaddConfig(BaseModel):
    """Add members to a sorted set with scores"""
    operation: Literal["add_members_to_sorted_set"] = Field(
        "add_members_to_sorted_set",
        json_schema_extra={"const": "add_members_to_sorted_set", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Add Members to Sorted Set"}, 
    title="Add Members to Sorted Set")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    members: List[Dict[str, Any]] = Field(
        ...,
        title="Members",
        description="List of {score: number, member: string} objects"
    )
    nx: Optional[bool] = Field(
        None,
        title="Only Add New",
        description="Only add new elements, don't update existing"
    )
    xx: Optional[bool] = Field(
        None,
        title="Only Update",
        description="Only update existing elements, don't add new"
    )


class RedisZremConfig(BaseModel):
    """Remove members from a sorted set"""
    operation: Literal["remove_members_from_sorted_set"] = Field(
        "remove_members_from_sorted_set",
        json_schema_extra={"const": "remove_members_from_sorted_set", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Remove Members from Sorted Set"}, 
    title="Remove Members from Sorted Set")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to remove"
    )


class RedisZrangeConfig(BaseModel):
    """Get a range of members from a sorted set"""
    operation: Literal["get_sorted_set_member_range"] = Field(
        "get_sorted_set_member_range",
        json_schema_extra={"const": "get_sorted_set_member_range", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Member Range"}, 
    title="Get Sorted Set Member Range")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    start: int = Field(
        0,
        title="Start",
        description="Start index"
    )
    stop: int = Field(
        -1,
        title="Stop",
        description="Stop index (-1 for all)"
    )
    withscores: Optional[bool] = Field(
        None,
        title="With Scores",
        description="Include scores in output"
    )


class RedisZrankConfig(BaseModel):
    """Get the rank of a member in a sorted set"""
    operation: Literal["get_sorted_set_member_rank"] = Field(
        "get_sorted_set_member_rank",
        json_schema_extra={"const": "get_sorted_set_member_rank", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Member Rank"}, 
    title="Get Sorted Set Member Rank")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    member: str = Field(
        ...,
        title="Member",
        description="The member to get rank for"
    )


class RedisZscoreConfig(BaseModel):
    """Get the score of a member in a sorted set"""
    operation: Literal["get_sorted_set_member_score"] = Field(
        "get_sorted_set_member_score",
        json_schema_extra={"const": "get_sorted_set_member_score", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Member Score"}, 
    title="Get Sorted Set Member Score")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    member: str = Field(
        ...,
        title="Member",
        description="The member to get score for"
    )


class RedisZcardConfig(BaseModel):
    """Get the number of members in a sorted set"""
    operation: Literal["get_sorted_set_member_count"] = Field(
        "get_sorted_set_member_count",
        json_schema_extra={"const": "get_sorted_set_member_count", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Member Count"}, 
    title="Get Sorted Set Member Count")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )


# ============================================================================
# Key Operation Configs
# ============================================================================
class RedisZcountConfig(BaseModel):
    """Zcount operation"""
    operation: Literal["count_sorted_set_members_in_score_range"] = Field(
        "count_sorted_set_members_in_score_range",
        json_schema_extra={"const": "count_sorted_set_members_in_score_range", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Count Sorted Set Members in Score Range"}, 
    title="Count Sorted Set Members in Score Range")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Minimum score"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Maximum score"
    )
class RedisZpopminConfig(BaseModel):
    """Zpopmin operation"""
    operation: Literal["pop_lowest_score_member"] = Field(
        "pop_lowest_score_member",
        json_schema_extra={"const": "pop_lowest_score_member", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Pop Lowest Score Member"}, 
    title="Pop Lowest Score Member")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number to pop"
    )
class RedisZrevrankConfig(BaseModel):
    """Zrevrank operation"""
    operation: Literal["get_sorted_set_member_rank_reverse"] = Field(
        "get_sorted_set_member_rank_reverse",
        json_schema_extra={"const": "get_sorted_set_member_rank_reverse", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Member Rank Reverse"}, 
    title="Get Sorted Set Member Rank Reverse")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    member: str = Field(
        ...,
        title="Member",
        description="The member"
    )
class RedisZrevrangebyscoreConfig(BaseModel):
    """Zrevrangebyscore operation"""
    operation: Literal["get_sorted_set_range_by_score_reverse"] = Field(
        "get_sorted_set_range_by_score_reverse",
        json_schema_extra={"const": "get_sorted_set_range_by_score_reverse", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Range by Score Reverse"}, 
    title="Get Sorted Set Range by Score Reverse")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Maximum score"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Minimum score"
    )
    withscores: Optional[bool] = Field(
        None,
        title="With Scores",
        description="Include scores"
    )
    limit_offset: Optional[int] = Field(
        None,
        title="Offset",
        description="Limit offset"
    )
    limit_count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit count"
    )
class RedisZrevrangebylexConfig(BaseModel):
    """Zrevrangebylex operation"""
    operation: Literal["get_sorted_set_range_by_lexical_order_reverse"] = Field(
        "get_sorted_set_range_by_lexical_order_reverse",
        json_schema_extra={"const": "get_sorted_set_range_by_lexical_order_reverse", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Range by Lexical Order Reverse"}, 
    title="Get Sorted Set Range by Lexical Order Reverse")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Max lex value"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Min lex value"
    )
    limit_offset: Optional[int] = Field(
        None,
        title="Offset",
        description="Limit offset"
    )
    limit_count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit count"
    )
class RedisZremrangebyscoreConfig(BaseModel):
    """Zremrangebyscore operation"""
    operation: Literal["remove_sorted_set_members_by_score_range"] = Field(
        "remove_sorted_set_members_by_score_range",
        json_schema_extra={"const": "remove_sorted_set_members_by_score_range", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Remove Sorted Set Members by Score Range"}, 
    title="Remove Sorted Set Members by Score Range")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Minimum score"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Maximum score"
    )
class RedisZlexcountConfig(BaseModel):
    """Zlexcount operation"""
    operation: Literal["count_sorted_set_members_in_lexical_range"] = Field(
        "count_sorted_set_members_in_lexical_range",
        json_schema_extra={"const": "count_sorted_set_members_in_lexical_range", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Count Sorted Set Members in Lexical Range"}, 
    title="Count Sorted Set Members in Lexical Range")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Min lex value"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Max lex value"
    )
class RedisZscanConfig(BaseModel):
    """Zscan operation"""
    operation: Literal["scan_sorted_set_members_iteratively"] = Field(
        "scan_sorted_set_members_iteratively",
        json_schema_extra={"const": "scan_sorted_set_members_iteratively", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Scan Sorted Set Members Iteratively"}, 
    title="Scan Sorted Set Members Iteratively")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    cursor: int = Field(
        0,
        title="Cursor",
        description="The cursor"
    )
    match: Optional[str] = Field(
        None,
        title="Pattern",
        description="Pattern to match"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Elements per iteration"
    )

class RedisZrandmemberConfig(BaseModel):
    """Zrandmember operation"""
    operation: Literal["get_random_sorted_set_members"] = Field(
        "get_random_sorted_set_members",
        json_schema_extra={"const": "get_random_sorted_set_members", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Random Sorted Set Members"}, 
    title="Get Random Sorted Set Members")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number of members"
    )
    withscores: Optional[bool] = Field(
        None,
        title="With Scores",
        description="Include scores"
    )


class RedisZmscoreConfig(BaseModel):
    """Zmscore operation"""
    operation: Literal["get_multiple_sorted_set_member_scores"] = Field(
        "get_multiple_sorted_set_member_scores",
        json_schema_extra={"const": "get_multiple_sorted_set_member_scores", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Multiple Sorted Set Member Scores"}, 
    title="Get Multiple Sorted Set Member Scores")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to get scores for"
    )


class RedisZremrangebylexConfig(BaseModel):
    """Zremrangebylex operation"""
    operation: Literal["remove_sorted_set_members_by_lexical_range"] = Field(
        "remove_sorted_set_members_by_lexical_range",
        json_schema_extra={"const": "remove_sorted_set_members_by_lexical_range", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Remove Sorted Set Members by Lexical Range"}, 
    title="Remove Sorted Set Members by Lexical Range")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Min lex value"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Max lex value"
    )


class RedisZremrangebyrankConfig(BaseModel):
    """Zremrangebyrank operation"""
    operation: Literal["remove_sorted_set_members_by_rank_range"] = Field(
        "remove_sorted_set_members_by_rank_range",
        json_schema_extra={"const": "remove_sorted_set_members_by_rank_range", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Remove Sorted Set Members by Rank Range"}, 
    title="Remove Sorted Set Members by Rank Range")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    start: int = Field(
        ...,
        title="Start",
        description="Start rank"
    )
    stop: int = Field(
        ...,
        title="Stop",
        description="Stop rank"
    )


class RedisZrangebylexConfig(BaseModel):
    """Zrangebylex operation"""
    operation: Literal["get_sorted_set_range_by_lexical_order"] = Field(
        "get_sorted_set_range_by_lexical_order",
        json_schema_extra={"const": "get_sorted_set_range_by_lexical_order", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Range by Lexical Order"}, 
    title="Get Sorted Set Range by Lexical Order")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Min lex value"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Max lex value"
    )
    limit_offset: Optional[int] = Field(
        None,
        title="Offset",
        description="Limit offset"
    )
    limit_count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit count"
    )


class RedisZrangebyscoreConfig(BaseModel):
    """Zrangebyscore operation"""
    operation: Literal["get_sorted_set_range_by_score"] = Field(
        "get_sorted_set_range_by_score",
        json_schema_extra={"const": "get_sorted_set_range_by_score", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Range by Score"}, 
    title="Get Sorted Set Range by Score")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    min: str = Field(
        ...,
        title="Min",
        description="Minimum score"
    )
    max: str = Field(
        ...,
        title="Max",
        description="Maximum score"
    )
    withscores: Optional[bool] = Field(
        None,
        title="With Scores",
        description="Include scores"
    )
    limit_offset: Optional[int] = Field(
        None,
        title="Offset",
        description="Limit offset"
    )
    limit_count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit count"
    )


class RedisZrevrangeConfig(BaseModel):
    """Zrevrange operation"""
    operation: Literal["get_sorted_set_member_range_reverse"] = Field(
        "get_sorted_set_member_range_reverse",
        json_schema_extra={"const": "get_sorted_set_member_range_reverse", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Member Range Reverse"}, 
    title="Get Sorted Set Member Range Reverse")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    start: int = Field(
        ...,
        title="Start",
        description="Start index"
    )
class RedisGetbitConfig(BaseModel):
    """Getbit operation"""
    operation: Literal["get_bit_at_offset"] = Field(
        "get_bit_at_offset",
        json_schema_extra={"const": "get_bit_at_offset", "ui:hidden": True, "x-category": "String", "x-is-trigger": False, "x-display-name": "Get Bit at Offset"}, 
    title="Get Bit at Offset")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    offset: int = Field(
        ...,
        title="Offset",
        description="Bit offset"
    )
class RedisBitposConfig(BaseModel):
    """Bitpos operation"""
    operation: Literal["find_first_bit_position"] = Field(
        "find_first_bit_position",
        json_schema_extra={"const": "find_first_bit_position", "ui:hidden": True, "x-category": "Bit", "x-is-trigger": False, "x-display-name": "Find First Bit Position"}, 
    title="Find First Bit Position")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    bit: int = Field(
        ...,
        title="Bit",
        description="Bit value to find (0 or 1)"
    )
    start: Optional[int] = Field(
        None,
        title="Start",
        description="Start byte"
    )
    end: Optional[int] = Field(
        None,
        title="End",
        description="End byte"
    )
class RedisBitfieldConfig(BaseModel):
    """Bitfield operation"""
    operation: Literal["perform_bitfield_operation"] = Field(
        "perform_bitfield_operation",
        json_schema_extra={"const": "perform_bitfield_operation", "ui:hidden": True, "x-category": "Bit", "x-is-trigger": False, "x-display-name": "Perform Bitfield Operation"}, 
    title="Perform Bitfield Operation")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    operations: List[str] = Field(
        ...,
        title="Operations",
        description="Bitfield operations"
    )
class RedisPfcountConfig(BaseModel):
    """Pfcount operation"""
    operation: Literal["count_hyperloglog_cardinality"] = Field(
        "count_hyperloglog_cardinality",
        json_schema_extra={"const": "count_hyperloglog_cardinality", "ui:hidden": True, "x-category": "HyperLogLog", "x-is-trigger": False, "x-display-name": "Count Hyperloglog Cardinality"}, 
    title="Count Hyperloglog Cardinality")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="HyperLogLog keys"
    )
class RedisGeoaddConfig(BaseModel):
    """Geoadd operation"""
    operation: Literal["add_geospatial_members"] = Field(
        "add_geospatial_members",
        json_schema_extra={"const": "add_geospatial_members", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Add Geospatial Members"}, 
    title="Add Geospatial Members")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    members: List[Dict[str, Any]] = Field(
        ...,
        title="Members",
        description="List of {longitude, latitude, name}"
    )
    nx: Optional[bool] = Field(
        None,
        title="Only Add New",
        description="Only add new elements"
    )
    xx: Optional[bool] = Field(
        None,
        title="Only Update",
        description="Only update existing"
    )
class RedisGeohashConfig(BaseModel):
    """Geohash operation"""
    operation: Literal["get_geohash_for_members"] = Field(
        "get_geohash_for_members",
        json_schema_extra={"const": "get_geohash_for_members", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Get Geohash for Members"}, 
    title="Get Geohash for Members")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to get hashes for"
    )
class RedisGeosearchConfig(BaseModel):
    """Geosearch operation"""
    operation: Literal["search_geospatial_members"] = Field(
        "search_geospatial_members",
        json_schema_extra={"const": "search_geospatial_members", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Search Geospatial Members"}, 
    title="Search Geospatial Members")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    frommember: Optional[str] = Field(
        None,
        title="From Member",
        description="Center on member"
    )
    fromlonlat: Optional[Tuple[float, float]] = Field(
        None,
        title="From Coordinates",
        description="Center coordinates"
    )
    byradius: Optional[float] = Field(
        None,
        title="By Radius",
        description="Search radius"
    )
    bybox: Optional[Tuple[float, float]] = Field(
        None,
        title="By Box",
        description="Search box (width, height)"
    )
    unit: Optional[Literal['m', 'km', 'mi', 'ft']] = Field(
        None,
        title="Unit",
        description="Distance unit"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit results"
    )
class RedisGeoradiusConfig(BaseModel):
    """Georadius operation"""
    operation: Literal["find_members_in_radius"] = Field(
        "find_members_in_radius",
        json_schema_extra={"const": "find_members_in_radius", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Find Members in Radius"}, 
    title="Find Members in Radius")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    longitude: float = Field(
        ...,
        title="Longitude",
        description="Center longitude"
    )
    latitude: float = Field(
        ...,
        title="Latitude",
        description="Center latitude"
    )
    radius: float = Field(
        ...,
        title="Radius",
        description="Search radius"
    )
    unit: Literal['m', 'km', 'mi', 'ft'] = Field(
        ...,
        title="Unit",
        description="Distance unit"
    )
    withcoord: Optional[bool] = Field(
        None,
        title="With Coordinates",
        description="Include coordinates"
    )
    withdist: Optional[bool] = Field(
        None,
        title="With Distance",
        description="Include distance"
    )
    withhash: Optional[bool] = Field(
        None,
        title="With Hash",
        description="Include geohash"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit results"
    )

class RedisGeoradiusbymemberConfig(BaseModel):
    """Georadiusbymember operation"""
    operation: Literal["find_members_in_radius_from_member"] = Field(
        "find_members_in_radius_from_member",
        json_schema_extra={"const": "find_members_in_radius_from_member", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Find Members in Radius from Member"}, 
    title="Find Members in Radius from Member")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    member: str = Field(
        ...,
        title="Member",
        description="Center on member"
    )
    radius: float = Field(
        ...,
        title="Radius",
        description="Search radius"
    )
    unit: Literal['m', 'km', 'mi', 'ft'] = Field(
        ...,
        title="Unit",
        description="Distance unit"
    )
    withcoord: Optional[bool] = Field(
        None,
        title="With Coordinates",
        description="Include coordinates"
    )
    withdist: Optional[bool] = Field(
        None,
        title="With Distance",
        description="Include distance"
    )
    withhash: Optional[bool] = Field(
        None,
        title="With Hash",
        description="Include geohash"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit results"
    )

class RedisGeosearchstoreConfig(BaseModel):
    """Geosearchstore operation"""
    operation: Literal["search_and_store_geospatial_members"] = Field(
        "search_and_store_geospatial_members",
        json_schema_extra={"const": "search_and_store_geospatial_members", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Search and Store Geospatial Members"}, 
    title="Search and Store Geospatial Members")
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    source: str = Field(
        ...,
        title="Source",
        description="Source geo key"
    )
    frommember: Optional[str] = Field(
        None,
        title="From Member",
        description="Center on member"
    )
    fromlonlat: Optional[Tuple[float, float]] = Field(
        None,
        title="From Coordinates",
        description="Center coordinates"
    )
    byradius: Optional[float] = Field(
        None,
        title="By Radius",
        description="Search radius"
    )
    bybox: Optional[Tuple[float, float]] = Field(
        None,
        title="By Box",
        description="Search box (width, height)"
    )
    unit: Optional[Literal['m', 'km', 'mi', 'ft']] = Field(
        None,
        title="Unit",
        description="Distance unit"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit results"
    )

class RedisGeoposConfig(BaseModel):
    """Geopos operation"""
    operation: Literal["get_position_of_members"] = Field(
        "get_position_of_members",
        json_schema_extra={"const": "get_position_of_members", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Get Position of Members"}, 
    title="Get Position of Members")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    members: List[str] = Field(
        ...,
        title="Members",
        description="Members to get positions for"
    )

class RedisGeodistConfig(BaseModel):
    """Geodist operation"""
    operation: Literal["get_distance_between_geospatial_members"] = Field(
        "get_distance_between_geospatial_members",
        json_schema_extra={"const": "get_distance_between_geospatial_members", "ui:hidden": True, "x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Get Distance Between Geospatial Members"}, 
    title="Get Distance Between Geospatial Members")
    key: str = Field(
        ...,
        title="Key",
        description="The geo key"
    )
    member1: str = Field(
        ...,
        title="Member 1",
        description="First member"
    )
    member2: str = Field(
        ...,
        title="Member 2",
        description="Second member"
    )
    unit: Optional[Literal['m', 'km', 'mi', 'ft']] = Field(
        None,
        title="Unit",
        description="Distance unit"
    )

class RedisPfmergeConfig(BaseModel):
    """Pfmerge operation"""
    operation: Literal["merge_hyperloglog_sets"] = Field(
        "merge_hyperloglog_sets",
        json_schema_extra={"const": "merge_hyperloglog_sets", "ui:hidden": True, "x-category": "HyperLogLog", "x-is-trigger": False, "x-display-name": "Merge Hyperloglog Sets"}, 
    title="Merge Hyperloglog Sets")
    destkey: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    sourcekeys: List[str] = Field(
        ...,
        title="Source Keys",
        description="Source HyperLogLog keys"
    )

class RedisPfaddConfig(BaseModel):
    """Pfadd operation"""
    operation: Literal["add_to_hyperloglog"] = Field(
        "add_to_hyperloglog",
        json_schema_extra={"const": "add_to_hyperloglog", "ui:hidden": True, "x-category": "HyperLogLog", "x-is-trigger": False, "x-display-name": "Add to Hyperloglog"}, 
    title="Add to Hyperloglog")
    key: str = Field(
        ...,
        title="Key",
        description="The HyperLogLog key"
    )
    elements: List[str] = Field(
        ...,
        title="Elements",
        description="Elements to add"
    )

class RedisBitopConfig(BaseModel):
    """Bitop operation"""
    operation: Literal["perform_bitwise_operation"] = Field(
        "perform_bitwise_operation",
        json_schema_extra={"const": "perform_bitwise_operation", "ui:hidden": True, "x-category": "Bit", "x-is-trigger": False, "x-display-name": "Perform Bitwise Operation"}, 
    title="Perform Bitwise Operation")
    bitop_type: Literal['AND', 'OR', 'XOR', 'NOT'] = Field(
        ...,
        title="Bitwise Operation",
        description="Bitwise operation type"
    )
    destkey: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Source keys"
    )

class RedisBitcountConfig(BaseModel):
    """Bitcount operation"""
    operation: Literal["count_set_bits"] = Field(
        "count_set_bits",
        json_schema_extra={"const": "count_set_bits", "ui:hidden": True, "x-category": "Bit", "x-is-trigger": False, "x-display-name": "Count Set Bits"}, 
    title="Count Set Bits")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    start: Optional[int] = Field(
        None,
        title="Start",
        description="Start byte"
    )
    end: Optional[int] = Field(
        None,
        title="End",
        description="End byte"
    )

class RedisSetbitConfig(BaseModel):
    """Setbit operation"""
    operation: Literal["set_bit_at_offset"] = Field(
        "set_bit_at_offset",
        json_schema_extra={"const": "set_bit_at_offset", "ui:hidden": True, "x-category": "String", "x-is-trigger": False, "x-display-name": "Set Bit at Offset"}, 
    title="Set Bit at Offset")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    offset: int = Field(
        ...,
        title="Offset",
        description="Bit offset"
    )
    value: int = Field(
        ...,
        title="Value",
        description="Bit value (0 or 1)"
    )


    stop: int = Field(
        ...,
        title="Stop",
        description="Stop index"
    )
    withscores: Optional[bool] = Field(
        None,
        title="With Scores",
        description="Include scores"
    )


class RedisZpopmaxConfig(BaseModel):
    """Zpopmax operation"""
    operation: Literal["pop_highest_score_member"] = Field(
        "pop_highest_score_member",
        json_schema_extra={"const": "pop_highest_score_member", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Pop Highest Score Member"}, 
    title="Pop Highest Score Member")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Number to pop"
    )


class RedisZincrbyConfig(BaseModel):
    """Zincrby operation"""
    operation: Literal["increment_sorted_set_member_score"] = Field(
        "increment_sorted_set_member_score",
        json_schema_extra={"const": "increment_sorted_set_member_score", "ui:hidden": True, "x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Increment Sorted Set Member Score"}, 
    title="Increment Sorted Set Member Score")
    key: str = Field(
        ...,
        title="Key",
        description="The sorted set key"
    )
    increment: float = Field(
        ...,
        title="Increment",
        description="Score increment"
    )
    member: str = Field(
        ...,
        title="Member",
        description="The member"
    )


class RedisDelConfig(BaseModel):
    """Delete one or more keys"""
    operation: Literal["delete_keys"] = Field(
        "delete_keys",
        json_schema_extra={"const": "delete_keys", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Delete Keys"}, 
    title="Delete Keys")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Keys to delete"
    )


class RedisExistsConfig(BaseModel):
    """Check if one or more keys exist"""
    operation: Literal["check_if_keys_exist"] = Field(
        "check_if_keys_exist",
        json_schema_extra={"const": "check_if_keys_exist", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Check If Keys Exist"}, 
    title="Check If Keys Exist")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Keys to check"
    )


class RedisExpireConfig(BaseModel):
    """Set a timeout on a key"""
    operation: Literal["set_key_expiration_seconds"] = Field(
        "set_key_expiration_seconds",
        json_schema_extra={"const": "set_key_expiration_seconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Expiration Seconds"}, 
    title="Set Key Expiration Seconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key to set expiration on"
    )
    seconds: int = Field(
        ...,
        title="Seconds",
        description="Expiration time in seconds"
    )


class RedisTtlConfig(BaseModel):
    """Get the time to live for a key"""
    operation: Literal["get_key_time_to_live"] = Field(
        "get_key_time_to_live",
        json_schema_extra={"const": "get_key_time_to_live", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Key Time to Live"}, 
    title="Get Key Time to Live")
    key: str = Field(
        ...,
        title="Key",
        description="The key to check"
    )


class RedisKeysConfig(BaseModel):
    """Find all keys matching a pattern"""
    operation: Literal["find_keys_matching_pattern"] = Field(
        "find_keys_matching_pattern",
        json_schema_extra={"const": "find_keys_matching_pattern", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Find Keys Matching Pattern"}, 
    title="Find Keys Matching Pattern")
    pattern: str = Field(
        "*",
        title="Pattern",
        description="Pattern to match (e.g., 'user:*', '*session*')"
    )


class RedisTypeConfig(BaseModel):
    """Get the type of a key"""
    operation: Literal["get_key_value_type"] = Field(
        "get_key_value_type",
        json_schema_extra={"const": "get_key_value_type", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Key Value Type"}, 
    title="Get Key Value Type")
    key: str = Field(
        ...,
        title="Key",
        description="The key to check"
    )


class RedisRenameConfig(BaseModel):
    """Rename a key"""
    operation: Literal["rename_key"] = Field(
        "rename_key",
        json_schema_extra={"const": "rename_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Rename Key"}, 
    title="Rename Key")
    key: str = Field(
        ...,
        title="Key",
        description="The key to rename"
    )
    newkey: str = Field(
        ...,
        title="New Key",
        description="The new key name"
    )


# ============================================================================
# Pipeline Operation Config
# ============================================================================
class RedisCopyConfig(BaseModel):
    """Copy operation"""
    operation: Literal["copy_key"] = Field(
        "copy_key",
        json_schema_extra={"const": "copy_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Copy Key"}, 
    title="Copy Key")
    source: str = Field(
        ...,
        title="Source",
        description="Source key"
    )
    destination: str = Field(
        ...,
        title="Destination",
        description="Destination key"
    )
    replace: Optional[bool] = Field(
        None,
        title="Replace",
        description="Replace destination"
    )
class RedisDumpConfig(BaseModel):
    """Dump operation"""
    operation: Literal["dump_serialized_key"] = Field(
        "dump_serialized_key",
        json_schema_extra={"const": "dump_serialized_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Dump Serialized Key"}, 
    title="Dump Serialized Key")
    key: str = Field(
        ...,
        title="Key",
        description="The key to dump"
    )
class RedisTouchConfig(BaseModel):
    """Touch operation"""
    operation: Literal["touch_keys_to_update_access_time"] = Field(
        "touch_keys_to_update_access_time",
        json_schema_extra={"const": "touch_keys_to_update_access_time", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Touch Keys to Update Access Time"}, 
    title="Touch Keys to Update Access Time")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Keys to touch"
    )
class RedisPexpireatConfig(BaseModel):
    """Pexpireat operation"""
    operation: Literal["set_key_expiration_at_unix_timestamp_milliseconds"] = Field(
        "set_key_expiration_at_unix_timestamp_milliseconds",
        json_schema_extra={"const": "set_key_expiration_at_unix_timestamp_milliseconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Expiration at Unix Timestamp Milliseconds"}, 
    title="Set Key Expiration at Unix Timestamp Milliseconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    timestamp: int = Field(
        ...,
        title="Timestamp",
        description="Unix timestamp in milliseconds"
    )
class RedisExpireatConfig(BaseModel):
    """Expireat operation"""
    operation: Literal["set_key_expiration_at_unix_timestamp"] = Field(
        "set_key_expiration_at_unix_timestamp",
        json_schema_extra={"const": "set_key_expiration_at_unix_timestamp", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Expiration at Unix Timestamp"}, 
    title="Set Key Expiration at Unix Timestamp")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    timestamp: int = Field(
        ...,
        title="Timestamp",
        description="Unix timestamp in seconds"
    )
class RedisPexpiretimeConfig(BaseModel):
    """Pexpiretime operation"""
    operation: Literal["get_key_expiration_unix_timestamp_milliseconds"] = Field(
        "get_key_expiration_unix_timestamp_milliseconds",
        json_schema_extra={"const": "get_key_expiration_unix_timestamp_milliseconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Key Expiration Unix Timestamp Milliseconds"}, 
    title="Get Key Expiration Unix Timestamp Milliseconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
class RedisRandomkeyConfig(BaseModel):
    """Randomkey operation"""
    operation: Literal["get_random_key"] = Field(
        "get_random_key",
        json_schema_extra={"const": "get_random_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Random Key"}, 
    title="Get Random Key")

class RedisSortConfig(BaseModel):
    """Sort operation"""
    operation: Literal["sort_list_set_or_sorted_set"] = Field(
        "sort_list_set_or_sorted_set",
        json_schema_extra={"const": "sort_list_set_or_sorted_set", "ui:hidden": True, "x-category": "Server", "x-is-trigger": False, "x-display-name": "Sort List Set or Sorted Set"}, 
    title="Sort List Set or Sorted Set")
    key: str = Field(
        ...,
        title="Key",
        description="The key to sort"
    )
    by: Optional[str] = Field(
        None,
        title="By Pattern",
        description="Sort by pattern"
    )
    limit_offset: Optional[int] = Field(
        None,
        title="Offset",
        description="Limit offset"
    )
    limit_count: Optional[int] = Field(
        None,
        title="Count",
        description="Limit count"
    )
    get: Optional[List[str]] = Field(
        None,
        title="Get Patterns",
        description="Get patterns"
    )
    order: Optional[Literal['ASC', 'DESC']] = Field(
        None,
        title="Order",
        description="Sort order"
    )
    alpha: Optional[bool] = Field(
        None,
        title="Alpha",
        description="Sort alphabetically"
    )


class RedisRenamenxConfig(BaseModel):
    """Renamenx operation"""
    operation: Literal["rename_key_if_new_not_exists"] = Field(
        "rename_key_if_new_not_exists",
        json_schema_extra={"const": "rename_key_if_new_not_exists", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Rename Key If New Not Exists"}, 
    title="Rename Key If New Not Exists")
    key: str = Field(
        ...,
        title="Key",
        description="The key to rename"
    )
    newkey: str = Field(
        ...,
        title="New Key",
        description="The new key name"
    )


class RedisExpiretimeConfig(BaseModel):
    """Expiretime operation"""
    operation: Literal["get_key_expiration_unix_timestamp"] = Field(
        "get_key_expiration_unix_timestamp",
        json_schema_extra={"const": "get_key_expiration_unix_timestamp", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Key Expiration Unix Timestamp"}, 
    title="Get Key Expiration Unix Timestamp")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )


class RedisPttlConfig(BaseModel):
    """Pttl operation"""
    operation: Literal["get_key_time_to_live_milliseconds"] = Field(
        "get_key_time_to_live_milliseconds",
        json_schema_extra={"const": "get_key_time_to_live_milliseconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Key Time to Live Milliseconds"}, 
    title="Get Key Time to Live Milliseconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )


class RedisPexpireConfig(BaseModel):
    """Pexpire operation"""
    operation: Literal["set_key_expiration_milliseconds"] = Field(
        "set_key_expiration_milliseconds",
        json_schema_extra={"const": "set_key_expiration_milliseconds", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Set Key Expiration Milliseconds"}, 
    title="Set Key Expiration Milliseconds")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    milliseconds: int = Field(
        ...,
        title="Milliseconds",
        description="Expiration in milliseconds"
    )


class RedisRestoreConfig(BaseModel):
    """Restore operation"""
    operation: Literal["restore_serialized_key"] = Field(
        "restore_serialized_key",
        json_schema_extra={"const": "restore_serialized_key", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Restore Serialized Key"}, 
    title="Restore Serialized Key")
    key: str = Field(
        ...,
        title="Key",
        description="The key"
    )
    ttl: int = Field(
        ...,
        title="TTL",
        description="TTL in milliseconds"
    )
    serialized_value: str = Field(
        ...,
        title="Serialized Value",
        description="Serialized value"
    )
    replace: Optional[bool] = Field(
        None,
        title="Replace",
        description="Replace existing key"
    )


class RedisUnlinkConfig(BaseModel):
    """Unlink operation"""
    operation: Literal["unlink_keys_async"] = Field(
        "unlink_keys_async",
        json_schema_extra={"const": "unlink_keys_async", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Unlink Keys Async"}, 
    title="Unlink Keys Async")
    keys: List[str] = Field(
        ...,
        title="Keys",
        description="Keys to unlink"
    )


class RedisScanConfig(BaseModel):
    """Scan operation"""
    operation: Literal["scan_keys_iteratively"] = Field(
        "scan_keys_iteratively",
        json_schema_extra={"const": "scan_keys_iteratively", "ui:hidden": True, "x-category": "Key", "x-is-trigger": False, "x-display-name": "Scan Keys Iteratively"}, 
    title="Scan Keys Iteratively")
    cursor: int = Field(
        0,
        title="Cursor",
        description="The cursor"
    )
    match: Optional[str] = Field(
        None,
        title="Pattern",
        description="Pattern to match"
    )
    count: Optional[int] = Field(
        None,
        title="Count",
        description="Elements per iteration"
    )
    type: Optional[str] = Field(
        None,
        title="Type",
        description="Key type filter"
    )


class RedisPipelineConfig(BaseModel):
    """Execute multiple commands in a single request"""
    operation: Literal["execute_commands_in_pipeline"] = Field(
        "execute_commands_in_pipeline",
        json_schema_extra={"const": "execute_commands_in_pipeline", "ui:hidden": True, "x-category": "Server", "x-is-trigger": False, "x-display-name": "Execute Commands in Pipeline"}, 
    title="Execute Commands in Pipeline")
    commands: List[List[str]] = Field(
        ...,
        title="Commands",
        description="List of commands, each as an array [command, ...args]"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


class RedisXaddConfig(BaseModel):
    """
    Append a new entry to a stream
    """
    operation: Literal["append_to_stream"] = Field(default="append_to_stream", title="Append to Stream", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Append to Stream"})
    key: str = ...
    fields: Dict[str, str] = ...
    id: Optional[str] = '*'
    maxlen: Optional[int] = None
    approximate: Optional[bool] = None

class RedisXreadConfig(BaseModel):
    """
    Read data from one or more streams
    """
    operation: Literal["read_from_streams"] = Field(default="read_from_streams", title="Read from Streams", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Read from Streams"})
    streams: Dict[str, str] = ...
    count: Optional[int] = None
    block: Optional[int] = None

class RedisXreadgroupConfig(BaseModel):
    """
    Read data from stream consumer group
    """
    operation: Literal["read_from_consumer_group"] = Field(default="read_from_consumer_group", title="Read from Consumer Group", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Read from Consumer Group"})
    group: str = ...
    consumer: str = ...
    streams: Dict[str, str] = ...
    count: Optional[int] = None
    block: Optional[int] = None
    noack: Optional[bool] = None

class RedisXlenConfig(BaseModel):
    """
    Get the number of entries in a stream
    """
    operation: Literal["get_stream_entry_count"] = Field(default="get_stream_entry_count", title="Get Stream Entry Count", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Get Stream Entry Count"})
    key: str = ...

class RedisXrangeConfig(BaseModel):
    """
    Return a range of entries from a stream
    """
    operation: Literal["get_stream_entry_range"] = Field(default="get_stream_entry_range", title="Get Stream Entry Range", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Get Stream Entry Range"})
    key: str = ...
    start: str = ...
    end: str = ...
    count: Optional[int] = None

class RedisXrevrangeConfig(BaseModel):
    """
    Return a range of entries in reverse order
    """
    operation: Literal["get_stream_entry_range_reverse"] = Field(default="get_stream_entry_range_reverse", title="Get Stream Entry Range Reverse", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Get Stream Entry Range Reverse"})
    key: str = ...
    end: str = ...
    start: str = ...
    count: Optional[int] = None

class RedisXdelConfig(BaseModel):
    """
    Remove entries from a stream
    """
    operation: Literal["delete_stream_entries"] = Field(default="delete_stream_entries", title="Delete Stream Entries", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Delete Stream Entries"})
    key: str = ...
    ids: List[str] = Field(..., description="List of IDs")

class RedisXtrimConfig(BaseModel):
    """
    Trim stream to a given length
    """
    operation: Literal["trim_stream_to_length"] = Field(default="trim_stream_to_length", title="Trim Stream to Length", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Trim Stream to Length"})
    key: str = ...
    maxlen: int = ...
    approximate: Optional[bool] = None

class RedisXackConfig(BaseModel):
    """
    Acknowledge stream messages
    """
    operation: Literal["acknowledge_stream_messages"] = Field(default="acknowledge_stream_messages", title="Acknowledge Stream Messages", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Acknowledge Stream Messages"})
    key: str = ...
    group: str = ...
    ids: List[str] = Field(..., description="List of IDs")

class RedisXpendingConfig(BaseModel):
    """
    Get information about pending messages
    """
    operation: Literal["get_pending_stream_messages"] = Field(default="get_pending_stream_messages", title="Get Pending Stream Messages", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Get Pending Stream Messages"})
    key: str = ...
    group: str = ...
    start: Optional[str] = None
    end: Optional[str] = None
    count: Optional[int] = None
    consumer: Optional[str] = None

class RedisXclaimConfig(BaseModel):
    """
    Claim pending messages from another consumer
    """
    operation: Literal["claim_pending_stream_messages"] = Field(default="claim_pending_stream_messages", title="Claim Pending Stream Messages", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Claim Pending Stream Messages"})
    key: str = ...
    group: str = ...
    consumer: str = ...
    min_idle_time: int = ...
    ids: List[str] = Field(..., description="List of IDs")

class RedisXautoclaimConfig(BaseModel):
    """
    Automatically claim pending messages
    """
    operation: Literal["auto_claim_pending_stream_messages"] = Field(default="auto_claim_pending_stream_messages", title="Auto Claim Pending Stream Messages", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Auto Claim Pending Stream Messages"})
    key: str = ...
    group: str = ...
    consumer: str = ...
    min_idle_time: int = ...
    start: str = ...
    count: Optional[int] = None

class RedisXgroupCreateConfig(BaseModel):
    """
    Create a consumer group
    """
    operation: Literal["create_stream_consumer_group"] = Field(default="create_stream_consumer_group", title="Create Stream Consumer Group", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Create Stream Consumer Group"})
    key: str = ...
    group: str = ...
    id: str = '$'
    mkstream: Optional[bool] = None

class RedisXgroupDestroyConfig(BaseModel):
    """
    Destroy a consumer group
    """
    operation: Literal["destroy_stream_consumer_group"] = Field(default="destroy_stream_consumer_group", title="Destroy Stream Consumer Group", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Destroy Stream Consumer Group"})
    key: str = ...
    group: str = ...

class RedisXgroupSetidConfig(BaseModel):
    """
    Set the consumer group last delivered ID
    """
    operation: Literal["set_consumer_group_last_delivered_id"] = Field(default="set_consumer_group_last_delivered_id", title="Set Consumer Group Last Delivered Id", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Set Consumer Group Last Delivered Id"})
    key: str = ...
    group: str = ...
    id: str = ...

class RedisXinfoStreamConfig(BaseModel):
    """
    Get information about a stream
    """
    operation: Literal["get_stream_information"] = Field(default="get_stream_information", title="Get Stream Information", json_schema_extra={"x-category": "Stream", "x-is-trigger": False, "x-display-name": "Get Stream Information"})
    key: str = ...

class RedisJsonSetConfig(BaseModel):
    """
    
    Set JSON value at path
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["set_json_value"] = Field(default="set_json_value", title="Set Json Value", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Set Json Value"})
    key: str = ...
    path: str = ...
    value: str = ...
    nx: Optional[bool] = None
    xx: Optional[bool] = None

class RedisJsonGetConfig(BaseModel):
    """
    
    Get JSON value from path
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_value"] = Field(default="get_json_value", title="Get Json Value", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json Value"})
    key: str = ...
    paths: Optional[List[str]] = Field(None, description="List of JSON paths")

class RedisJsonDelConfig(BaseModel):
    """
    
    Delete JSON value at path
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["delete_json_value"] = Field(default="delete_json_value", title="Delete Json Value", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Delete Json Value"})
    key: str = ...
    path: str = '$'

class RedisJsonMgetConfig(BaseModel):
    """
    
    Get JSON values from multiple keys
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_from_multiple_keys"] = Field(default="get_json_from_multiple_keys", title="Get Json from Multiple Keys", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json from Multiple Keys"})
    keys: List[str] = Field(..., description="List of keys")
    path: str = ...

class RedisJsonMsetConfig(BaseModel):
    """
    
    Set JSON values in multiple keys atomically
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["set_json_in_multiple_keys"] = Field(default="set_json_in_multiple_keys", title="Set Json in Multiple Keys", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Set Json in Multiple Keys"})
    triplets: List[Tuple[str, str, str]] = Field(..., description="List of (key, path, value) triplets")

class RedisJsonArrappendConfig(BaseModel):
    """
    
    Append values to JSON array
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["append_to_json_array"] = Field(default="append_to_json_array", title="Append to Json Array", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Append to Json Array"})
    key: str = ...
    path: str = ...
    values: List[str] = Field(..., description="List of values")

class RedisJsonArrinsertConfig(BaseModel):
    """
    
    Insert values into JSON array at index
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["insert_into_json_array"] = Field(default="insert_into_json_array", title="Insert Into Json Array", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Insert Into Json Array"})
    key: str = ...
    path: str = ...
    index: int = ...
    values: List[str] = Field(..., description="List of values")

class RedisJsonArrindexConfig(BaseModel):
    """
    
    Find index of value in JSON array
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["find_index_in_json_array"] = Field(default="find_index_in_json_array", title="Find Index in Json Array", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Find Index in Json Array"})
    key: str = ...
    path: str = ...
    value: str = ...
    start: Optional[int] = None
    stop: Optional[int] = None

class RedisJsonArrlenConfig(BaseModel):
    """
    
    Get length of JSON array
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_array_length"] = Field(default="get_json_array_length", title="Get Json Array Length", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json Array Length"})
    key: str = ...
    path: str = '$'

class RedisJsonArrpopConfig(BaseModel):
    """
    
    Remove and return element from JSON array
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["pop_from_json_array"] = Field(default="pop_from_json_array", title="Pop from Json Array", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Pop from Json Array"})
    key: str = ...
    path: str = '$'
    index: Optional[int] = None

class RedisJsonArrtrimConfig(BaseModel):
    """
    
    Trim JSON array to specified range
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["trim_json_array"] = Field(default="trim_json_array", title="Trim Json Array", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Trim Json Array"})
    key: str = ...
    path: str = ...
    start: int = ...
    stop: int = ...

class RedisJsonClearConfig(BaseModel):
    """
    
    Clear container values (arrays/objects)
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["clear_json_container"] = Field(default="clear_json_container", title="Clear Json Container", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Clear Json Container"})
    key: str = ...
    path: str = '$'

class RedisJsonNumincrbyConfig(BaseModel):
    """
    
    Increment JSON number by value
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["increment_json_number"] = Field(default="increment_json_number", title="Increment Json Number", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Increment Json Number"})
    key: str = ...
    path: str = ...
    value: float = ...

class RedisJsonNummultbyConfig(BaseModel):
    """
    
    Multiply JSON number by value
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["multiply_json_number"] = Field(default="multiply_json_number", title="Multiply Json Number", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Multiply Json Number"})
    key: str = ...
    path: str = ...
    value: float = ...

class RedisJsonStrappendConfig(BaseModel):
    """
    
    Append string to JSON string value
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["append_to_json_string"] = Field(default="append_to_json_string", title="Append to Json String", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Append to Json String"})
    key: str = ...
    path: str = ...
    value: str = ...

class RedisJsonStrlenConfig(BaseModel):
    """
    
    Get length of JSON string
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_string_length"] = Field(default="get_json_string_length", title="Get Json String Length", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json String Length"})
    key: str = ...
    path: str = '$'

class RedisJsonObjkeysConfig(BaseModel):
    """
    
    Get keys of JSON object
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_object_keys"] = Field(default="get_json_object_keys", title="Get Json Object Keys", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json Object Keys"})
    key: str = ...
    path: str = '$'

class RedisJsonObjlenConfig(BaseModel):
    """
    
    Get number of keys in JSON object
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_object_key_count"] = Field(default="get_json_object_key_count", title="Get Json Object Key Count", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json Object Key Count"})
    key: str = ...
    path: str = '$'

class RedisJsonTypeConfig(BaseModel):
    """
    
    Get type of JSON value
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_value_type"] = Field(default="get_json_value_type", title="Get Json Value Type", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json Value Type"})
    key: str = ...
    path: str = '$'

class RedisJsonMergeConfig(BaseModel):
    """
    
    Merge JSON values
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["merge_json_values"] = Field(default="merge_json_values", title="Merge Json Values", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Merge Json Values"})
    key: str = ...
    path: str = ...
    value: str = ...

class RedisJsonToggleConfig(BaseModel):
    """
    
    Toggle JSON boolean value
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["toggle_json_boolean"] = Field(default="toggle_json_boolean", title="Toggle Json Boolean", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Toggle Json Boolean"})
    key: str = ...
    path: str = ...

class RedisJsonRespConfig(BaseModel):
    """
    
    Return JSON value in RESP form
    
    
    **Requires:** RedisJSON module
    """
    operation: Literal["get_json_in_resp_format"] = Field(default="get_json_in_resp_format", title="Get Json in Resp Format", json_schema_extra={"x-category": "JSON", "x-is-trigger": False, "x-display-name": "Get Json in Resp Format"})
    key: str = ...
    path: str = '$'

class RedisEvalConfig(BaseModel):
    """
    Execute Lua script
    """
    operation: Literal["execute_lua_script"] = Field(default="execute_lua_script", title="Execute Lua Script", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Execute Lua Script"})
    script: str = ...
    keys: List[str] = Field(..., description="List of keys")
    args: Optional[List[str]] = None

class RedisEvalshaConfig(BaseModel):
    """
    Execute Lua script by SHA1 digest
    """
    operation: Literal["execute_lua_script_by_sha"] = Field(default="execute_lua_script_by_sha", title="Execute Lua Script by Sha", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Execute Lua Script by Sha"})
    sha1: str = ...
    keys: List[str] = Field(..., description="List of keys")
    args: Optional[List[str]] = None

class RedisEvalRoConfig(BaseModel):
    """
    Execute read-only Lua script
    """
    operation: Literal["execute_readonly_lua_script"] = Field(default="execute_readonly_lua_script", title="Execute Readonly Lua Script", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Execute Readonly Lua Script"})
    script: str = ...
    keys: List[str] = Field(..., description="List of keys")
    args: Optional[List[str]] = None

class RedisEvalshaRoConfig(BaseModel):
    """
    Execute read-only Lua script by SHA1
    """
    operation: Literal["execute_readonly_lua_script_by_sha"] = Field(default="execute_readonly_lua_script_by_sha", title="Execute Readonly Lua Script by Sha", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Execute Readonly Lua Script by Sha"})
    sha1: str = ...
    keys: List[str] = Field(..., description="List of keys")
    args: Optional[List[str]] = None

class RedisFcallConfig(BaseModel):
    """
    Call Redis function
    """
    operation: Literal["call_redis_function"] = Field(default="call_redis_function", title="Call Redis Function", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "Call Redis Function"})
    function: str = ...
    keys: List[str] = Field(..., description="List of keys")
    args: Optional[List[str]] = None

class RedisFcallRoConfig(BaseModel):
    """
    Call read-only Redis function
    """
    operation: Literal["call_readonly_redis_function"] = Field(default="call_readonly_redis_function", title="Call Readonly Redis Function", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "Call Readonly Redis Function"})
    function: str = ...
    keys: List[str] = Field(..., description="List of keys")
    args: Optional[List[str]] = None


# ============================================================================
# Function Operations (Redis 7.0+)
# These operations require Redis 7.0+ for function library support
# ============================================================================

class RedisFunctionLoadConfig(BaseModel):
    """
    Load Redis function library
    """
    operation: Literal["load_function_library"] = Field(default="load_function_library", title="Load Function Library", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "Load Function Library"})
    library_code: str = ...
    replace: Optional[bool] = None

class RedisFunctionDeleteConfig(BaseModel):
    """
    Delete Redis function library
    """
    operation: Literal["delete_function_library"] = Field(default="delete_function_library", title="Delete Function Library", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "Delete Function Library"})
    library_name: str = ...

class RedisFunctionFlushConfig(BaseModel):
    """
    Delete all function libraries
    """
    operation: Literal["delete_all_function_libraries"] = Field(default="delete_all_function_libraries", title="Delete All Function Libraries", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "Delete All Function Libraries"})
    mode: Optional[str] = None

class RedisFunctionListConfig(BaseModel):
    """
    List all function libraries
    """
    operation: Literal["list_function_libraries"] = Field(default="list_function_libraries", title="List Function Libraries", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "List Function Libraries"})
    library_name: Optional[str] = None

class RedisFunctionStatsConfig(BaseModel):
    """
    Get function execution statistics
    """
    operation: Literal["get_function_execution_stats"] = Field(default="get_function_execution_stats", title="Get Function Execution Stats", json_schema_extra={"x-category": "Function", "x-is-trigger": False, "x-display-name": "Get Function Execution Stats"})

class RedisScriptExistsConfig(BaseModel):
    """
    Check if scripts exist
    """
    operation: Literal["check_if_scripts_exist"] = Field(default="check_if_scripts_exist", title="Check If Scripts Exist", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Check If Scripts Exist"})
    sha1s: List[str] = Field(..., description="List of SHA1 hashes")

class RedisScriptFlushConfig(BaseModel):
    """
    Remove all scripts from script cache
    """
    operation: Literal["remove_all_cached_scripts"] = Field(default="remove_all_cached_scripts", title="Remove All Cached Scripts", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Remove All Cached Scripts"})
    mode: Optional[str] = None

class RedisScriptLoadConfig(BaseModel):
    """
    Load script into cache
    """
    operation: Literal["load_script_into_cache"] = Field(default="load_script_into_cache", title="Load Script Into Cache", json_schema_extra={"x-category": "Script", "x-is-trigger": False, "x-display-name": "Load Script Into Cache"})
    script: str = ...

class RedisPublishConfig(BaseModel):
    """
    Post a message to a channel
    """
    operation: Literal["publish_message_to_channel"] = Field(default="publish_message_to_channel", title="Publish Message to Channel", json_schema_extra={"x-category": "PubSub", "x-is-trigger": False, "x-display-name": "Publish Message to Channel"})
    channel: str = ...
    message: str = ...

class RedisSubscribeConfig(BaseModel):
    """
    Subscribe to channels
    """
    operation: Literal["subscribe_to_channels"] = Field(default="subscribe_to_channels", title="Subscribe to Channels", json_schema_extra={"x-category": None, "x-is-trigger": True, "x-display-name": "Subscribe to Channels"})
    channels: List[str] = Field(..., description="List of channel names")

class RedisUnsubscribeConfig(BaseModel):
    """
    Unsubscribe from channels
    """
    operation: Literal["unsubscribe_from_channels"] = Field(default="unsubscribe_from_channels", title="Unsubscribe from Channels", json_schema_extra={"x-category": "PubSub", "x-is-trigger": False, "x-display-name": "Unsubscribe from Channels"})
    channels: Optional[List[str]] = None

class RedisPsubscribeConfig(BaseModel):
    """
    Subscribe to channels matching patterns
    """
    operation: Literal["subscribe_to_channel_patterns"] = Field(default="subscribe_to_channel_patterns", title="Subscribe to Channel Patterns", json_schema_extra={"x-category": None, "x-is-trigger": True, "x-display-name": "Subscribe to Channel Patterns"})
    patterns: List[str] = Field(..., description="List of patterns")

class RedisPunsubscribeConfig(BaseModel):
    """
    Unsubscribe from channel patterns
    """
    operation: Literal["unsubscribe_from_channel_patterns"] = Field(default="unsubscribe_from_channel_patterns", title="Unsubscribe from Channel Patterns", json_schema_extra={"x-category": "PubSub", "x-is-trigger": False, "x-display-name": "Unsubscribe from Channel Patterns"})
    patterns: Optional[List[str]] = None

class RedisPubsubConfig(BaseModel):
    """
    Get pub/sub system state
    """
    operation: Literal["get_pubsub_system_state"] = Field(default="get_pubsub_system_state", title="Get Pubsub System State", json_schema_extra={"x-category": "PubSub", "x-is-trigger": False, "x-display-name": "Get Pubsub System State"})
    subcommand: str = ...
    args: Optional[List[str]] = None

class RedisMultiConfig(BaseModel):
    """
    Mark the start of a transaction block
    """
    operation: Literal["start_transaction"] = Field(default="start_transaction", title="Start Transaction", json_schema_extra={"x-category": "Transaction", "x-is-trigger": False, "x-display-name": "Start Transaction"})

class RedisExecConfig(BaseModel):
    """
    Execute all commands in transaction
    """
    operation: Literal["execute_transaction"] = Field(default="execute_transaction", title="Execute Transaction", json_schema_extra={"x-category": "Transaction", "x-is-trigger": False, "x-display-name": "Execute Transaction"})

class RedisDiscardConfig(BaseModel):
    """
    Discard all commands in transaction
    """
    operation: Literal["discard_transaction_commands"] = Field(default="discard_transaction_commands", title="Discard Transaction Commands", json_schema_extra={"x-category": "Transaction", "x-is-trigger": False, "x-display-name": "Discard Transaction Commands"})

class RedisWatchConfig(BaseModel):
    """
    Watch keys for conditional execution
    """
    operation: Literal["watch_keys_for_transaction"] = Field(default="watch_keys_for_transaction", title="Watch Keys for Transaction", json_schema_extra={"x-category": "Transaction", "x-is-trigger": False, "x-display-name": "Watch Keys for Transaction"})
    keys: List[str] = Field(..., description="List of keys")

class RedisUnwatchConfig(BaseModel):
    """
    Unwatch all keys
    """
    operation: Literal["stop_watching_keys"] = Field(default="stop_watching_keys", title="Stop Watching Keys", json_schema_extra={"x-category": "Transaction", "x-is-trigger": False, "x-display-name": "Stop Watching Keys"})

class RedisPingConfig(BaseModel):
    """
    Ping the server
    """
    operation: Literal["ping_server"] = Field(default="ping_server", title="Ping Server", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Ping Server"})
    message: Optional[str] = None

class RedisEchoConfig(BaseModel):
    """
    Echo the given string
    """
    operation: Literal["echo_message"] = Field(default="echo_message", title="Echo Message", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Echo Message"})
    message: str = ...

class RedisSelectConfig(BaseModel):
    """
    Select the database
    """
    operation: Literal["select_database"] = Field(default="select_database", title="Select Database", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Select Database"})
    index: int = ...

class RedisAuthConfig(BaseModel):
    """
    Authenticate to the server
    """
    operation: Literal["authenticate_to_server"] = Field(default="authenticate_to_server", title="Authenticate to Server", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Authenticate to Server"})
    password: str = ...
    username: Optional[str] = None

class RedisHelloConfig(BaseModel):
    """
    Handshake with server
    """
    operation: Literal["handshake_with_server"] = Field(default="handshake_with_server", title="Handshake with Server", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Handshake with Server"})
    protover: Optional[int] = None
    auth_user: Optional[str] = None
    auth_pass: Optional[str] = None

class RedisQuitConfig(BaseModel):
    """
    Close the connection
    """
    operation: Literal["close_connection"] = Field(default="close_connection", title="Close Connection", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Close Connection"})

class RedisResetConfig(BaseModel):
    """
    Reset the connection state
    """
    operation: Literal["reset_connection_state"] = Field(default="reset_connection_state", title="Reset Connection State", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Reset Connection State"})

class RedisClientIdConfig(BaseModel):
    """
    Get client connection ID
    """
    operation: Literal["get_client_connection_id"] = Field(default="get_client_connection_id", title="Get Client Connection Id", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Get Client Connection Id"})

class RedisClientGetnameConfig(BaseModel):
    """
    Get the connection name
    """
    operation: Literal["get_client_connection_name"] = Field(default="get_client_connection_name", title="Get Client Connection Name", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Get Client Connection Name"})

class RedisClientSetnameConfig(BaseModel):
    """
    Set the connection name
    """
    operation: Literal["set_client_connection_name"] = Field(default="set_client_connection_name", title="Set Client Connection Name", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Set Client Connection Name"})
    name: str = ...

class RedisClientInfoConfig(BaseModel):
    """
    Get client connection info
    """
    operation: Literal["get_client_connection_info"] = Field(default="get_client_connection_info", title="Get Client Connection Info", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Get Client Connection Info"})

class RedisClientListConfig(BaseModel):
    """
    List all client connections
    """
    operation: Literal["list_all_client_connections"] = Field(default="list_all_client_connections", title="List All Client Connections", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "List All Client Connections"})
    client_type: Optional[str] = None

class RedisClientSetinfoConfig(BaseModel):
    """
    Set client connection attributes
    """
    operation: Literal["set_client_connection_attributes"] = Field(default="set_client_connection_attributes", title="Set Client Connection Attributes", json_schema_extra={"x-category": "Connection", "x-is-trigger": False, "x-display-name": "Set Client Connection Attributes"})
    attr: str = ...
    value: str = ...

class RedisDbsizeConfig(BaseModel):
    """
    Get the number of keys in database
    """
    operation: Literal["get_database_key_count"] = Field(default="get_database_key_count", title="Get Database Key Count", json_schema_extra={"x-category": "Key", "x-is-trigger": False, "x-display-name": "Get Database Key Count"})

class RedisFlushallConfig(BaseModel):
    """
    Remove all keys from all databases
    """
    operation: Literal["delete_all_keys_all_databases"] = Field(default="delete_all_keys_all_databases", title="Delete All Keys All Databases", json_schema_extra={"x-category": "Key", "x-is-trigger": False, "x-display-name": "Delete All Keys All Databases"})
    mode: Optional[str] = None

class RedisFlushdbConfig(BaseModel):
    """
    Remove all keys from current database
    """
    operation: Literal["delete_all_keys_current_database"] = Field(default="delete_all_keys_current_database", title="Delete All Keys Current Database", json_schema_extra={"x-category": "Key", "x-is-trigger": False, "x-display-name": "Delete All Keys Current Database"})
    mode: Optional[str] = None

class RedisMonitorConfig(BaseModel):
    """
    Listen for all requests received by server
    """
    operation: Literal["listen_for_server_requests"] = Field(default="listen_for_server_requests", title="Listen for Server Requests", json_schema_extra={"x-category": "Server", "x-is-trigger": False, "x-display-name": "Listen for Server Requests"})

class RedisTimeConfig(BaseModel):
    """
    Get server time
    """
    operation: Literal["get_server_time"] = Field(default="get_server_time", title="Get Server Time", json_schema_extra={"x-category": "Server", "x-is-trigger": False, "x-display-name": "Get Server Time"})

class RedisBlpopConfig(BaseModel):
    """
    Remove and get the first element, block if empty
    """
    operation: Literal["pop_first_element_blocking"] = Field(default="pop_first_element_blocking", title="Pop First Element Blocking", json_schema_extra={"x-category": "List", "x-is-trigger": False, "x-display-name": "Pop First Element Blocking"})
    keys: List[str] = Field(..., description="List of keys")
    timeout: int = ...

class RedisBrpopConfig(BaseModel):
    """
    Remove and get the last element, block if empty
    """
    operation: Literal["pop_last_element_blocking"] = Field(default="pop_last_element_blocking", title="Pop Last Element Blocking", json_schema_extra={"x-category": "List", "x-is-trigger": False, "x-display-name": "Pop Last Element Blocking"})
    keys: List[str] = Field(..., description="List of keys")
    timeout: int = ...

class RedisBlmoveConfig(BaseModel):
    """
    Pop element from source, push to dest, block if empty
    """
    operation: Literal["pop_and_push_between_lists_blocking"] = Field(default="pop_and_push_between_lists_blocking", title="Pop and Push Between Lists Blocking", json_schema_extra={"x-category": "List", "x-is-trigger": False, "x-display-name": "Pop and Push Between Lists Blocking"})
    source: str = ...
    destination: str = ...
    wherefrom: str = ...
    whereto: str = ...
    timeout: int = ...

class RedisBrpoplpushConfig(BaseModel):
    """
    Pop from source, push to dest, block if empty
    """
    operation: Literal["pop_and_push_across_lists_blocking"] = Field(default="pop_and_push_across_lists_blocking", title="Pop and Push Across Lists Blocking", json_schema_extra={"x-category": "List", "x-is-trigger": False, "x-display-name": "Pop and Push Across Lists Blocking"})
    source: str = ...
    destination: str = ...
    timeout: int = ...

class RedisBlmpopConfig(BaseModel):
    """
    Pop elements from lists, block if empty
    """
    operation: Literal["pop_from_multiple_lists_blocking"] = Field(default="pop_from_multiple_lists_blocking", title="Pop from Multiple Lists Blocking", json_schema_extra={"x-category": "List", "x-is-trigger": False, "x-display-name": "Pop from Multiple Lists Blocking"})
    timeout: int = ...
    keys: List[str] = Field(..., description="List of keys")
    direction: str = ...
    count: Optional[int] = None

class RedisLmpopConfig(BaseModel):
    """
    Pop elements from multiple lists
    """
    operation: Literal["pop_from_multiple_lists"] = Field(default="pop_from_multiple_lists", title="Pop from Multiple Lists", json_schema_extra={"x-category": "List", "x-is-trigger": False, "x-display-name": "Pop from Multiple Lists"})
    keys: List[str] = Field(..., description="List of keys")
    direction: str = ...
    count: Optional[int] = None

class RedisSintercardConfig(BaseModel):
    """
    Get cardinality of intersection between sets
    """
    operation: Literal["get_set_intersection_cardinality"] = Field(default="get_set_intersection_cardinality", title="Get Set Intersection Cardinality", json_schema_extra={"x-category": "Set", "x-is-trigger": False, "x-display-name": "Get Set Intersection Cardinality"})
    keys: List[str] = Field(..., description="List of keys")
    limit: Optional[int] = None

class RedisSscanConfig(BaseModel):
    """
    Incrementally iterate set members
    """
    operation: Literal["scan_set_members_iteratively"] = Field(default="scan_set_members_iteratively", title="Scan Set Members Iteratively", json_schema_extra={"x-category": "Set", "x-is-trigger": False, "x-display-name": "Scan Set Members Iteratively"})
    key: str = ...
    cursor: int = ...
    match: Optional[str] = None
    count: Optional[int] = None

class RedisBzmpopConfig(BaseModel):
    """
    Pop elements from sorted sets, block if empty
    """
    operation: Literal["pop_from_sorted_sets_blocking"] = Field(default="pop_from_sorted_sets_blocking", title="Pop from Sorted Sets Blocking", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Pop from Sorted Sets Blocking"})
    timeout: int = ...
    keys: List[str] = Field(..., description="List of keys")
    modifier: str = ...
    count: Optional[int] = None

class RedisBzpopmaxConfig(BaseModel):
    """
    Remove and return highest scored member, block if empty
    """
    operation: Literal["pop_highest_score_member_blocking"] = Field(default="pop_highest_score_member_blocking", title="Pop Highest Score Member Blocking", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Pop Highest Score Member Blocking"})
    keys: List[str] = Field(..., description="List of keys")
    timeout: int = ...

class RedisBzpopminConfig(BaseModel):
    """
    Remove and return lowest scored member, block if empty
    """
    operation: Literal["pop_lowest_score_member_blocking"] = Field(default="pop_lowest_score_member_blocking", title="Pop Lowest Score Member Blocking", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Pop Lowest Score Member Blocking"})
    keys: List[str] = Field(..., description="List of keys")
    timeout: int = ...

class RedisZdiffConfig(BaseModel):
    """
    Get difference between sorted sets
    """
    operation: Literal["get_sorted_set_difference"] = Field(default="get_sorted_set_difference", title="Get Sorted Set Difference", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Difference"})
    keys: List[str] = Field(..., description="List of keys")
    withscores: Optional[bool] = None

class RedisZdiffstoreConfig(BaseModel):
    """
    Store difference of sorted sets
    """
    operation: Literal["store_sorted_set_difference"] = Field(default="store_sorted_set_difference", title="Store Sorted Set Difference", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Store Sorted Set Difference"})
    destination: str = ...
    keys: List[str] = Field(..., description="List of keys")

class RedisZinterConfig(BaseModel):
    """
    Get intersection of sorted sets
    """
    operation: Literal["get_sorted_set_intersection"] = Field(default="get_sorted_set_intersection", title="Get Sorted Set Intersection", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Intersection"})
    keys: List[str] = Field(..., description="List of keys")
    weights: Optional[List[float]] = Field(None, description="List of weight multipliers")
    aggregate: Optional[str] = None
    withscores: Optional[bool] = None

class RedisZintercardConfig(BaseModel):
    """
    Get cardinality of sorted set intersection
    """
    operation: Literal["get_sorted_set_intersection_cardinality"] = Field(default="get_sorted_set_intersection_cardinality", title="Get Sorted Set Intersection Cardinality", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Intersection Cardinality"})
    keys: List[str] = Field(..., description="List of keys")
    limit: Optional[int] = None

class RedisZinterstoreConfig(BaseModel):
    """
    Store intersection of sorted sets
    """
    operation: Literal["store_sorted_set_intersection"] = Field(default="store_sorted_set_intersection", title="Store Sorted Set Intersection", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Store Sorted Set Intersection"})
    destination: str = ...
    keys: List[str] = Field(..., description="List of keys")
    weights: Optional[List[float]] = Field(None, description="List of weight multipliers")
    aggregate: Optional[str] = None

class RedisZmpopConfig(BaseModel):
    """
    Pop elements from sorted sets
    """
    operation: Literal["pop_from_sorted_sets"] = Field(default="pop_from_sorted_sets", title="Pop from Sorted Sets", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Pop from Sorted Sets"})
    keys: List[str] = Field(..., description="List of keys")
    modifier: str = ...
    count: Optional[int] = None

class RedisZrangestoreConfig(BaseModel):
    """
    Store range from sorted set
    """
    operation: Literal["store_sorted_set_range"] = Field(default="store_sorted_set_range", title="Store Sorted Set Range", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Store Sorted Set Range"})
    destination: str = ...
    source: str = ...
    start: str = ...
    stop: str = ...
    by: Optional[str] = None
    rev: Optional[bool] = None
    limit: Optional[Tuple[int, int]] = None

class RedisZunionConfig(BaseModel):
    """
    Get union of sorted sets
    """
    operation: Literal["get_sorted_set_union"] = Field(default="get_sorted_set_union", title="Get Sorted Set Union", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Get Sorted Set Union"})
    keys: List[str] = Field(..., description="List of keys")
    weights: Optional[List[float]] = Field(None, description="List of weight multipliers")
    aggregate: Optional[str] = None
    withscores: Optional[bool] = None

class RedisZunionstoreConfig(BaseModel):
    """
    Store union of sorted sets
    """
    operation: Literal["store_sorted_set_union"] = Field(default="store_sorted_set_union", title="Store Sorted Set Union", json_schema_extra={"x-category": "Sorted Set", "x-is-trigger": False, "x-display-name": "Store Sorted Set Union"})
    destination: str = ...
    keys: List[str] = Field(..., description="List of keys")
    weights: Optional[List[float]] = Field(None, description="List of weight multipliers")
    aggregate: Optional[str] = None

class RedisBitfieldRoConfig(BaseModel):
    """
    Read-only bitfield operations
    """
    operation: Literal["perform_bitfield_operation_readonly"] = Field(default="perform_bitfield_operation_readonly", title="Perform Bitfield Operation Readonly", json_schema_extra={"x-category": "Bit", "x-is-trigger": False, "x-display-name": "Perform Bitfield Operation Readonly"})
    key: str = ...
    operations: List[str] = ...

class RedisHgetdelConfig(BaseModel):
    """
    Get hash field value and delete it
    """
    operation: Literal["get_and_delete_hash_field"] = Field(default="get_and_delete_hash_field", title="Get and Delete Hash Field", json_schema_extra={"x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get and Delete Hash Field"})
    key: str = ...
    field: str = ...

class RedisHgetexConfig(BaseModel):
    """
    Get hash field with expiration
    """
    operation: Literal["get_hash_field_with_expiration"] = Field(default="get_hash_field_with_expiration", title="Get Hash Field with Expiration", json_schema_extra={"x-category": "Hash", "x-is-trigger": False, "x-display-name": "Get Hash Field with Expiration"})
    key: str = ...
    field: str = ...
    ex: Optional[int] = None
    px: Optional[int] = None

class RedisHsetexConfig(BaseModel):
    """
    Set hash field with expiration
    """
    operation: Literal["set_hash_field_with_expiration"] = Field(default="set_hash_field_with_expiration", title="Set Hash Field with Expiration", json_schema_extra={"x-category": "Hash", "x-is-trigger": False, "x-display-name": "Set Hash Field with Expiration"})
    key: str = ...
    field: str = ...
    value: str = ...
    ex: Optional[int] = None
    px: Optional[int] = None

class RedisGeoradiusRoConfig(BaseModel):
    """
    Read-only query radius with center coordinates
    """
    operation: Literal["find_members_in_radius_readonly"] = Field(default="find_members_in_radius_readonly", title="Find Members in Radius Readonly", json_schema_extra={"x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Find Members in Radius Readonly"})
    key: str = ...
    longitude: float = ...
    latitude: float = ...
    radius: float = ...
    unit: str = ...
    withcoord: Optional[bool] = None
    withdist: Optional[bool] = None
    withhash: Optional[bool] = None
    count: Optional[int] = None
    sort: Optional[str] = None

class RedisGeoradiusbymemberRoConfig(BaseModel):
    """
    Read-only query radius with center member
    """
    operation: Literal["find_members_in_radius_from_member_readonly"] = Field(default="find_members_in_radius_from_member_readonly", title="Find Members in Radius from Member Readonly", json_schema_extra={"x-category": "Geospatial", "x-is-trigger": False, "x-display-name": "Find Members in Radius from Member Readonly"})
    key: str = ...
    member: str = ...
    radius: float = ...
    unit: str = ...
    withcoord: Optional[bool] = None
    withdist: Optional[bool] = None
    withhash: Optional[bool] = None
    count: Optional[int] = None
    sort: Optional[str] = None

RedisConfig = Annotated[
    Union[
        # String operations (9)
        RedisGetConfig,
        RedisSetConfig,
        RedisMgetConfig,
        RedisMsetConfig,
        RedisIncrConfig,
        RedisIncrbyConfig,
        RedisDecrConfig,
        RedisAppendConfig,
        RedisStrlenConfig,
        # Hash operations (10)
        RedisHgetConfig,
        RedisHsetConfig,
        RedisHgetallConfig,
        RedisHdelConfig,
        RedisHmgetConfig,
        RedisHmsetConfig,
        RedisHkeysConfig,
        RedisHvalsConfig,
        RedisHexistsConfig,
        RedisHlenConfig,
        # List operations (8)
        RedisLpushConfig,
        RedisRpushConfig,
        RedisLpopConfig,
        RedisRpopConfig,
        RedisLrangeConfig,
        RedisLlenConfig,
        RedisLindexConfig,
        RedisLsetConfig,
        # Set operations (8)
        RedisSaddConfig,
        RedisSremConfig,
        RedisSmembersConfig,
        RedisSismemberConfig,
        RedisScardConfig,
        RedisSunionConfig,
        RedisSinterConfig,
        RedisSdiffConfig,
        # Sorted set operations (6)
        RedisZaddConfig,
        RedisZremConfig,
        RedisZrangeConfig,
        RedisZrankConfig,
        RedisZscoreConfig,
        RedisZcardConfig,
        # Key operations (7)
        RedisDelConfig,
        RedisExistsConfig,
        RedisExpireConfig,
        RedisTtlConfig,
        RedisKeysConfig,
        RedisTypeConfig,
        RedisRenameConfig,
        RedisGetdelConfig,
        RedisGetexConfig,
        RedisGetrangeConfig,
        RedisSetrangeConfig,
        RedisIncrbyfloatConfig,
        RedisDecrbyConfig,
        RedisMsetnxConfig,
        RedisSetexConfig,
        RedisPsetexConfig,
        RedisSetnxConfig,
        RedisGetsetConfig,
        RedisHincrbyConfig,
        RedisHincrbyfloatConfig,
        RedisHsetnxConfig,
        RedisHstrlenConfig,
        RedisHrandfieldConfig,
        RedisHscanConfig,
        RedisLinsertConfig,
        RedisLremConfig,
        RedisLtrimConfig,
        RedisLposConfig,
        RedisLmoveConfig,
        RedisLpushxConfig,
        RedisRpushxConfig,
        RedisRpoplpushConfig,
        RedisSpopConfig,
        RedisSrandmemberConfig,
        RedisSmoveConfig,
        RedisSdiffstoreConfig,
        RedisSinterstoreConfig,
        RedisSunionstoreConfig,
        RedisSmismemberConfig,
        RedisZincrbyConfig,
        RedisZcountConfig,
        RedisZpopmaxConfig,
        RedisZpopminConfig,
        RedisZrevrangeConfig,
        RedisZrevrankConfig,
        RedisZrangebyscoreConfig,
        RedisZrevrangebyscoreConfig,
        RedisZrangebylexConfig,
        RedisZrevrangebylexConfig,
        RedisZremrangebyrankConfig,
        RedisZremrangebyscoreConfig,
        RedisZremrangebylexConfig,
        RedisZlexcountConfig,
        RedisZmscoreConfig,
        RedisZscanConfig,
        RedisZrandmemberConfig,
        RedisSetbitConfig,
        RedisGetbitConfig,
        RedisBitcountConfig,
        RedisBitposConfig,
        RedisBitopConfig,
        RedisBitfieldConfig,
        RedisPfaddConfig,
        RedisPfcountConfig,
        RedisPfmergeConfig,
        RedisGeoaddConfig,
        RedisGeodistConfig,
        RedisGeohashConfig,
        RedisGeoposConfig,
        RedisGeosearchConfig,
        RedisGeosearchstoreConfig,
        RedisGeoradiusConfig,
        RedisGeoradiusbymemberConfig,
        RedisScanConfig,
        RedisCopyConfig,
        RedisUnlinkConfig,
        RedisDumpConfig,
        RedisRestoreConfig,
        RedisTouchConfig,
        RedisPexpireConfig,
        RedisPexpireatConfig,
        RedisPttlConfig,
        RedisExpireatConfig,
        RedisExpiretimeConfig,
        RedisPexpiretimeConfig,
        RedisRenamenxConfig,
        RedisRandomkeyConfig,
        RedisSortConfig,
                # Pipeline (1)
        RedisPipelineConfig,
        RedisXaddConfig,
        RedisXreadConfig,
        RedisXreadgroupConfig,
        RedisXlenConfig,
        RedisXrangeConfig,
        RedisXrevrangeConfig,
        RedisXdelConfig,
        RedisXtrimConfig,
        RedisXackConfig,
        RedisXpendingConfig,
        RedisXclaimConfig,
        RedisXautoclaimConfig,
        RedisXgroupCreateConfig,
        RedisXgroupDestroyConfig,
        RedisXgroupSetidConfig,
        RedisXinfoStreamConfig,
        RedisJsonSetConfig,
        RedisJsonGetConfig,
        RedisJsonDelConfig,
        RedisJsonMgetConfig,
        RedisJsonMsetConfig,
        RedisJsonArrappendConfig,
        RedisJsonArrinsertConfig,
        RedisJsonArrindexConfig,
        RedisJsonArrlenConfig,
        RedisJsonArrpopConfig,
        RedisJsonArrtrimConfig,
        RedisJsonClearConfig,
        RedisJsonNumincrbyConfig,
        RedisJsonNummultbyConfig,
        RedisJsonStrappendConfig,
        RedisJsonStrlenConfig,
        RedisJsonObjkeysConfig,
        RedisJsonObjlenConfig,
        RedisJsonTypeConfig,
        RedisJsonMergeConfig,
        RedisJsonToggleConfig,
        RedisJsonRespConfig,
        RedisEvalConfig,
        RedisEvalshaConfig,
        RedisEvalRoConfig,
        RedisEvalshaRoConfig,
        RedisFcallConfig,
        RedisFcallRoConfig,
        RedisFunctionLoadConfig,
        RedisFunctionDeleteConfig,
        RedisFunctionFlushConfig,
        RedisFunctionListConfig,
        RedisFunctionStatsConfig,
        RedisScriptExistsConfig,
        RedisScriptFlushConfig,
        RedisScriptLoadConfig,
        RedisPublishConfig,
        RedisSubscribeConfig,
        RedisUnsubscribeConfig,
        RedisPsubscribeConfig,
        RedisPunsubscribeConfig,
        RedisPubsubConfig,
        RedisMultiConfig,
        RedisExecConfig,
        RedisDiscardConfig,
        RedisWatchConfig,
        RedisUnwatchConfig,
        RedisPingConfig,
        RedisEchoConfig,
        RedisSelectConfig,
        RedisAuthConfig,
        RedisHelloConfig,
        RedisQuitConfig,
        RedisResetConfig,
        RedisClientIdConfig,
        RedisClientGetnameConfig,
        RedisClientSetnameConfig,
        RedisClientInfoConfig,
        RedisClientListConfig,
        RedisClientSetinfoConfig,
        RedisDbsizeConfig,
        RedisFlushallConfig,
        RedisFlushdbConfig,
        RedisMonitorConfig,
        RedisTimeConfig,
        RedisBlpopConfig,
        RedisBrpopConfig,
        RedisBlmoveConfig,
        RedisBrpoplpushConfig,
        RedisBlmpopConfig,
        RedisLmpopConfig,
        RedisSintercardConfig,
        RedisSscanConfig,
        RedisBzmpopConfig,
        RedisBzpopmaxConfig,
        RedisBzpopminConfig,
        RedisZdiffConfig,
        RedisZdiffstoreConfig,
        RedisZinterConfig,
        RedisZintercardConfig,
        RedisZinterstoreConfig,
        RedisZmpopConfig,
        RedisZrangestoreConfig,
        RedisZunionConfig,
        RedisZunionstoreConfig,
        RedisBitfieldRoConfig,
        RedisHgetdelConfig,
        RedisHgetexConfig,
        RedisHsetexConfig,
        RedisGeoradiusRoConfig,
        RedisGeoradiusbymemberRoConfig
    ],
    Discriminator('operation')
]


# ============================================================================
# Full Node Configuration
# ============================================================================









class RedisNodeConfig(NodeConfig[RedisConfig, RedisCredential]):
    """Full configuration for Redis node including credentials"""
    pass


# ============================================================================
# Node Implementation
# ============================================================================


class RedisNode(WorkflowNode):
    """
    Upstash Redis automation node.

    Executes Redis commands via REST API for workflow automation.
    Supports 49 operations across strings, hashes, lists, sets, sorted sets, and keys.
    """

    edit_examples = [
        "Store user session tokens in Redis with 1 hour expiration",
        "Get cached product data from Redis by key product_id_123",
        "Increment view counter for a blog post and set TTL to 7 days",
        "Store a sorted list of trending topics by score",
        "Hash user profiles with fields like name, email, signup_date",
        "Get all keys matching pattern user:* and delete expired ones",
        "Publish notification to Redis subscriber for real-time updates",
    ]

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return RedisNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured Redis operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, RedisNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Upstash Redis REST URL and Token."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # String operations
            "get_key_value": self._handle_get,
            "set_key_value": self._handle_set,
            "get_multiple_key_values": self._handle_mget,
            "set_multiple_key_value_pairs": self._handle_mset,
            "increment_key_by_one": self._handle_incr,
            "increment_key_by_amount": self._handle_incrby,
            "decrement_key_by_one": self._handle_decr,
            "append_value_to_key": self._handle_append,
            "get_string_value_length": self._handle_strlen,
            # Hash operations
            "get_hash_field_value": self._handle_hget,
            "set_hash_field_value": self._handle_hset,
            "get_all_hash_fields_and_values": self._handle_hgetall,
            "delete_hash_fields": self._handle_hdel,
            "get_multiple_hash_field_values": self._handle_hmget,
            "set_multiple_hash_fields": self._handle_hmset,
            "get_all_hash_field_names": self._handle_hkeys,
            "get_all_hash_values": self._handle_hvals,
            "check_if_hash_field_exists": self._handle_hexists,
            "get_hash_field_count": self._handle_hlen,
            # List operations
            "push_to_list_beginning": self._handle_lpush,
            "push_to_list_end": self._handle_rpush,
            "pop_first_element": self._handle_lpop,
            "pop_last_element": self._handle_rpop,
            "get_list_range": self._handle_lrange,
            "get_list_length": self._handle_llen,
            "get_list_element_by_index": self._handle_lindex,
            "set_list_element_by_index": self._handle_lset,
            # Set operations
            "add_members_to_set": self._handle_sadd,
            "remove_members_from_set": self._handle_srem,
            "get_all_set_members": self._handle_smembers,
            "check_if_member_in_set": self._handle_sismember,
            "get_set_member_count": self._handle_scard,
            "get_set_union": self._handle_sunion,
            "get_set_intersection": self._handle_sinter,
            "get_set_difference": self._handle_sdiff,
            # Sorted set operations
            "add_members_to_sorted_set": self._handle_zadd,
            "remove_members_from_sorted_set": self._handle_zrem,
            "get_sorted_set_member_range": self._handle_zrange,
            "get_sorted_set_member_rank": self._handle_zrank,
            "get_sorted_set_member_score": self._handle_zscore,
            "get_sorted_set_member_count": self._handle_zcard,
            # Key operations
            "delete_keys": self._handle_del,
            "check_if_keys_exist": self._handle_exists,
            "set_key_expiration_seconds": self._handle_expire,
            "get_key_time_to_live": self._handle_ttl,
            "find_keys_matching_pattern": self._handle_keys,
            "get_key_value_type": self._handle_type,
            "rename_key": self._handle_rename,
            # Pipeline
            "get_and_delete_key": self._handle_getdel,
            "get_with_expiration_options": self._handle_getex,
            "get_substring_by_range": self._handle_getrange,
            "set_string_range_at_offset": self._handle_setrange,
            "increment_key_by_float": self._handle_incrbyfloat,
            "decrement_key_by_amount": self._handle_decrby,
            "set_multiple_pairs_if_not_exist": self._handle_msetnx,
            "set_key_value_with_expiration_seconds": self._handle_setex,
            "set_key_value_with_expiration_milliseconds": self._handle_psetex,
            "set_key_if_not_exists": self._handle_setnx,
            "get_and_set_key_value": self._handle_getset,
            "increment_hash_field_by_amount": self._handle_hincrby,
            "increment_hash_field_by_float": self._handle_hincrbyfloat,
            "set_hash_field_if_not_exists": self._handle_hsetnx,
            "get_hash_field_value_length": self._handle_hstrlen,
            "get_random_hash_field": self._handle_hrandfield,
            "scan_hash_fields_iteratively": self._handle_hscan,
            "insert_into_list": self._handle_linsert,
            "remove_elements_from_list": self._handle_lrem,
            "trim_list_to_range": self._handle_ltrim,
            "find_element_position_in_list": self._handle_lpos,
            "move_element_between_lists": self._handle_lmove,
            "push_to_list_beginning_if_exists": self._handle_lpushx,
            "push_to_list_end_if_exists": self._handle_rpushx,
            "pop_and_push_across_lists": self._handle_rpoplpush,
            "pop_random_members_from_set": self._handle_spop,
            "get_random_set_members": self._handle_srandmember,
            "move_member_between_sets": self._handle_smove,
            "store_set_difference": self._handle_sdiffstore,
            "store_set_intersection": self._handle_sinterstore,
            "store_set_union": self._handle_sunionstore,
            "check_multiple_members_in_set": self._handle_smismember,
            "increment_sorted_set_member_score": self._handle_zincrby,
            "count_sorted_set_members_in_score_range": self._handle_zcount,
            "pop_highest_score_member": self._handle_zpopmax,
            "pop_lowest_score_member": self._handle_zpopmin,
            "get_sorted_set_member_range_reverse": self._handle_zrevrange,
            "get_sorted_set_member_rank_reverse": self._handle_zrevrank,
            "get_sorted_set_range_by_score": self._handle_zrangebyscore,
            "get_sorted_set_range_by_score_reverse": self._handle_zrevrangebyscore,
            "get_sorted_set_range_by_lexical_order": self._handle_zrangebylex,
            "get_sorted_set_range_by_lexical_order_reverse": self._handle_zrevrangebylex,
            "remove_sorted_set_members_by_rank_range": self._handle_zremrangebyrank,
            "remove_sorted_set_members_by_score_range": self._handle_zremrangebyscore,
            "remove_sorted_set_members_by_lexical_range": self._handle_zremrangebylex,
            "count_sorted_set_members_in_lexical_range": self._handle_zlexcount,
            "get_multiple_sorted_set_member_scores": self._handle_zmscore,
            "scan_sorted_set_members_iteratively": self._handle_zscan,
            "get_random_sorted_set_members": self._handle_zrandmember,
            "set_bit_at_offset": self._handle_setbit,
            "get_bit_at_offset": self._handle_getbit,
            "count_set_bits": self._handle_bitcount,
            "find_first_bit_position": self._handle_bitpos,
            "perform_bitwise_operation": self._handle_bitop,
            "perform_bitfield_operation": self._handle_bitfield,
            "add_to_hyperloglog": self._handle_pfadd,
            "count_hyperloglog_cardinality": self._handle_pfcount,
            "merge_hyperloglog_sets": self._handle_pfmerge,
            "add_geospatial_members": self._handle_geoadd,
            "get_distance_between_geospatial_members": self._handle_geodist,
            "get_geohash_for_members": self._handle_geohash,
            "get_position_of_members": self._handle_geopos,
            "search_geospatial_members": self._handle_geosearch,
            "search_and_store_geospatial_members": self._handle_geosearchstore,
            "find_members_in_radius": self._handle_georadius,
            "find_members_in_radius_from_member": self._handle_georadiusbymember,
            "scan_keys_iteratively": self._handle_scan,
            "copy_key": self._handle_copy,
            "unlink_keys_async": self._handle_unlink,
            "dump_serialized_key": self._handle_dump,
            "restore_serialized_key": self._handle_restore,
            "touch_keys_to_update_access_time": self._handle_touch,
            "set_key_expiration_milliseconds": self._handle_pexpire,
            "set_key_expiration_at_unix_timestamp_milliseconds": self._handle_pexpireat,
            "get_key_time_to_live_milliseconds": self._handle_pttl,
            "set_key_expiration_at_unix_timestamp": self._handle_expireat,
            "get_key_expiration_unix_timestamp": self._handle_expiretime,
            "get_key_expiration_unix_timestamp_milliseconds": self._handle_pexpiretime,
            "rename_key_if_new_not_exists": self._handle_renamenx,
            "get_random_key": self._handle_randomkey,
            "sort_list_set_or_sorted_set": self._handle_sort,
                        "execute_commands_in_pipeline": self._handle_pipeline,
            "append_to_stream": self._handle_xadd,
            "read_from_streams": self._handle_xread,
            "read_from_consumer_group": self._handle_xreadgroup,
            "get_stream_entry_count": self._handle_xlen,
            "get_stream_entry_range": self._handle_xrange,
            "get_stream_entry_range_reverse": self._handle_xrevrange,
            "delete_stream_entries": self._handle_xdel,
            "trim_stream_to_length": self._handle_xtrim,
            "acknowledge_stream_messages": self._handle_xack,
            "get_pending_stream_messages": self._handle_xpending,
            "claim_pending_stream_messages": self._handle_xclaim,
            "auto_claim_pending_stream_messages": self._handle_xautoclaim,
            "create_stream_consumer_group": self._handle_xgroup_create,
            "destroy_stream_consumer_group": self._handle_xgroup_destroy,
            "set_consumer_group_last_delivered_id": self._handle_xgroup_setid,
            "get_stream_information": self._handle_xinfo_stream,
            "set_json_value": self._handle_json_set,
            "get_json_value": self._handle_json_get,
            "delete_json_value": self._handle_json_del,
            "get_json_from_multiple_keys": self._handle_json_mget,
            "set_json_in_multiple_keys": self._handle_json_mset,
            "append_to_json_array": self._handle_json_arrappend,
            "insert_into_json_array": self._handle_json_arrinsert,
            "find_index_in_json_array": self._handle_json_arrindex,
            "get_json_array_length": self._handle_json_arrlen,
            "pop_from_json_array": self._handle_json_arrpop,
            "trim_json_array": self._handle_json_arrtrim,
            "clear_json_container": self._handle_json_clear,
            "increment_json_number": self._handle_json_numincrby,
            "multiply_json_number": self._handle_json_nummultby,
            "append_to_json_string": self._handle_json_strappend,
            "get_json_string_length": self._handle_json_strlen,
            "get_json_object_keys": self._handle_json_objkeys,
            "get_json_object_key_count": self._handle_json_objlen,
            "get_json_value_type": self._handle_json_type,
            "merge_json_values": self._handle_json_merge,
            "toggle_json_boolean": self._handle_json_toggle,
            "get_json_in_resp_format": self._handle_json_resp,
            "execute_lua_script": self._handle_eval,
            "execute_lua_script_by_sha": self._handle_evalsha,
            "execute_readonly_lua_script": self._handle_eval_ro,
            "execute_readonly_lua_script_by_sha": self._handle_evalsha_ro,
            "call_redis_function": self._handle_fcall,
            "call_readonly_redis_function": self._handle_fcall_ro,
            "load_function_library": self._handle_function_load,
            "delete_function_library": self._handle_function_delete,
            "delete_all_function_libraries": self._handle_function_flush,
            "list_function_libraries": self._handle_function_list,
            "get_function_execution_stats": self._handle_function_stats,
            "check_if_scripts_exist": self._handle_script_exists,
            "remove_all_cached_scripts": self._handle_script_flush,
            "load_script_into_cache": self._handle_script_load,
            "publish_message_to_channel": self._handle_publish,
            "subscribe_to_channels": self._handle_subscribe,
            "unsubscribe_from_channels": self._handle_unsubscribe,
            "subscribe_to_channel_patterns": self._handle_psubscribe,
            "unsubscribe_from_channel_patterns": self._handle_punsubscribe,
            "get_pubsub_system_state": self._handle_pubsub,
            "start_transaction": self._handle_multi,
            "execute_transaction": self._handle_exec,
            "discard_transaction_commands": self._handle_discard,
            "watch_keys_for_transaction": self._handle_watch,
            "stop_watching_keys": self._handle_unwatch,
            "ping_server": self._handle_ping,
            "echo_message": self._handle_echo,
            "select_database": self._handle_select,
            "authenticate_to_server": self._handle_auth,
            "handshake_with_server": self._handle_hello,
            "close_connection": self._handle_quit,
            "reset_connection_state": self._handle_reset,
            "get_client_connection_id": self._handle_client_id,
            "get_client_connection_name": self._handle_client_getname,
            "set_client_connection_name": self._handle_client_setname,
            "get_client_connection_info": self._handle_client_info,
            "list_all_client_connections": self._handle_client_list,
            "set_client_connection_attributes": self._handle_client_setinfo,
            "get_database_key_count": self._handle_dbsize,
            "delete_all_keys_all_databases": self._handle_flushall,
            "delete_all_keys_current_database": self._handle_flushdb,
            "listen_for_server_requests": self._handle_monitor,
            "get_server_time": self._handle_time,
            "pop_first_element_blocking": self._handle_blpop,
            "pop_last_element_blocking": self._handle_brpop,
            "pop_and_push_between_lists_blocking": self._handle_blmove,
            "pop_and_push_across_lists_blocking": self._handle_brpoplpush,
            "pop_from_multiple_lists_blocking": self._handle_blmpop,
            "pop_from_multiple_lists": self._handle_lmpop,
            "get_set_intersection_cardinality": self._handle_sintercard,
            "scan_set_members_iteratively": self._handle_sscan,
            "pop_from_sorted_sets_blocking": self._handle_bzmpop,
            "pop_highest_score_member_blocking": self._handle_bzpopmax,
            "pop_lowest_score_member_blocking": self._handle_bzpopmin,
            "get_sorted_set_difference": self._handle_zdiff,
            "store_sorted_set_difference": self._handle_zdiffstore,
            "get_sorted_set_intersection": self._handle_zinter,
            "get_sorted_set_intersection_cardinality": self._handle_zintercard,
            "store_sorted_set_intersection": self._handle_zinterstore,
            "pop_from_sorted_sets": self._handle_zmpop,
            "store_sorted_set_range": self._handle_zrangestore,
            "get_sorted_set_union": self._handle_zunion,
            "store_sorted_set_union": self._handle_zunionstore,
            "perform_bitfield_operation_readonly": self._handle_bitfield_ro,
            "get_and_delete_hash_field": self._handle_hgetdel,
            "get_hash_field_with_expiration": self._handle_hgetex,
            "set_hash_field_with_expiration": self._handle_hsetex,
            "find_members_in_radius_readonly": self._handle_georadius_ro,
            "find_members_in_radius_from_member_readonly": self._handle_georadiusbymember_ro
        
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
            "total": round(total_time, 2)
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _make_request(
        self,
        credentials: RedisCredential,
        command_path: str,
        action_name: str = "request"
    ) -> Dict[str, Any]:
        """
        Make a GET request to the Upstash Redis REST API.

        Args:
            credentials: API credentials
            command_path: Command path (e.g., /get/mykey)
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        # Ensure URL doesn't have trailing slash
        base_url = credentials.rest_url.rstrip('/')
        url = f"{base_url}{command_path}"

        headers = {
            "Authorization": f"Bearer {get_token_from_credential(credentials)}",
        }

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=headers)

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get("error", error_text)
                    except Exception:
                        error_message = error_text

                    logger.error(f"[RedisNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)}
                    }

                # Parse response
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data.get("result") if isinstance(data, dict) else data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)}
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}
                }
            except Exception as e:
                logger.exception(f"[RedisNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}
                }

    async def _make_post_request(
        self,
        credentials: RedisCredential,
        endpoint: str,
        json_body: Any,
        action_name: str = "request"
    ) -> Dict[str, Any]:
        """
        Make a POST request to the Upstash Redis REST API (for pipeline/complex commands).

        Args:
            credentials: API credentials
            endpoint: Endpoint path
            json_body: JSON request body
            action_name: Name of the action

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        base_url = credentials.rest_url.rstrip('/')
        url = f"{base_url}{endpoint}"

        headers = {
            "Authorization": f"Bearer {get_token_from_credential(credentials)}",
            "Content-Type": "application/json",
        }

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=json_body)

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = await response.json()
                        error_message = error_data.get("error", error_text)
                    except Exception:
                        error_message = error_text

                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)}
                    }

                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data.get("result") if isinstance(data, dict) else data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)}
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}
                }
            except Exception as e:
                logger.exception(f"[RedisNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}
                }

    def _encode_value(self, value: str) -> str:
        """URL-encode a value for the REST API path."""
        import urllib.parse
        return urllib.parse.quote(value, safe='')

    # =========================================================================
    # String Operation Handlers
    # =========================================================================

    async def _handle_get(
        self,
        config: RedisGetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get the value of a key."""
        path = f"/get/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get")

    async def _handle_set(
        self,
        config: RedisSetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Set the value of a key."""
        path = f"/set/{self._encode_value(config.key)}/{self._encode_value(config.value)}"

        # Add optional parameters
        if config.ex is not None:
            path += f"/ex/{config.ex}"
        elif config.px is not None:
            path += f"/px/{config.px}"

        if config.nx:
            path += "/nx"
        elif config.xx:
            path += "/xx"

        return await self._make_request(credentials, path, "set_key_value")

    async def _handle_mget(
        self,
        config: RedisMgetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get multiple keys."""
        keys_path = "/".join(self._encode_value(k) for k in config.keys)
        path = f"/mget/{keys_path}"
        return await self._make_request(credentials, path, "get_multiple_key_values")

    async def _handle_mset(
        self,
        config: RedisMsetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Set multiple key-value pairs."""
        pairs_path = "/".join(
            f"{self._encode_value(k)}/{self._encode_value(v)}"
            for k, v in config.pairs.items()
        )
        path = f"/mset/{pairs_path}"
        return await self._make_request(credentials, path, "set_multiple_key_value_pairs")

    async def _handle_incr(
        self,
        config: RedisIncrConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Increment a key by 1."""
        path = f"/incr/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "increment_key_by_one")

    async def _handle_incrby(
        self,
        config: RedisIncrbyConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Increment a key by amount."""
        path = f"/incrby/{self._encode_value(config.key)}/{config.increment}"
        return await self._make_request(credentials, path, "increment_key_by_amount")

    async def _handle_decr(
        self,
        config: RedisDecrConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Decrement a key by 1."""
        path = f"/decr/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "decrement_key_by_one")

    async def _handle_append(
        self,
        config: RedisAppendConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Append to a key."""
        path = f"/append/{self._encode_value(config.key)}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "append")

    async def _handle_strlen(
        self,
        config: RedisStrlenConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get string length."""
        path = f"/strlen/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_string_value_length")

    # =========================================================================
    # Hash Operation Handlers
    # =========================================================================

    async def _handle_hget(
        self,
        config: RedisHgetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get a hash field."""
        path = f"/hget/{self._encode_value(config.key)}/{self._encode_value(config.field)}"
        return await self._make_request(credentials, path, "get_hash_field_value")

    async def _handle_hset(
        self,
        config: RedisHsetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Set a hash field."""
        path = f"/hset/{self._encode_value(config.key)}/{self._encode_value(config.field)}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_hash_field_value")

    async def _handle_hgetall(
        self,
        config: RedisHgetallConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get all hash fields."""
        path = f"/hgetall/{self._encode_value(config.key)}"
        result = await self._make_request(credentials, path, "get_all_hash_fields_and_values")

        # Convert flat array to dict for convenience
        if result["status"] == "success" and isinstance(result["data"], list):
            data = result["data"]
            if len(data) % 2 == 0:
                result["data"] = dict(zip(data[::2], data[1::2]))

        return result

    async def _handle_hdel(
        self,
        config: RedisHdelConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Delete hash fields."""
        fields_path = "/".join(self._encode_value(f) for f in config.fields)
        path = f"/hdel/{self._encode_value(config.key)}/{fields_path}"
        return await self._make_request(credentials, path, "delete_hash_fields")

    async def _handle_hmget(
        self,
        config: RedisHmgetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get multiple hash fields."""
        fields_path = "/".join(self._encode_value(f) for f in config.fields)
        path = f"/hmget/{self._encode_value(config.key)}/{fields_path}"
        return await self._make_request(credentials, path, "get_multiple_hash_field_values")

    async def _handle_hmset(
        self,
        config: RedisHmsetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Set multiple hash fields."""
        pairs_path = "/".join(
            f"{self._encode_value(k)}/{self._encode_value(v)}"
            for k, v in config.pairs.items()
        )
        path = f"/hmset/{self._encode_value(config.key)}/{pairs_path}"
        return await self._make_request(credentials, path, "set_multiple_hash_fields")

    async def _handle_hkeys(
        self,
        config: RedisHkeysConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get all hash keys."""
        path = f"/hkeys/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_all_hash_field_names")

    async def _handle_hvals(
        self,
        config: RedisHvalsConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get all hash values."""
        path = f"/hvals/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_all_hash_values")

    async def _handle_hexists(
        self,
        config: RedisHexistsConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Check if hash field exists."""
        path = f"/hexists/{self._encode_value(config.key)}/{self._encode_value(config.field)}"
        result = await self._make_request(credentials, path, "check_if_hash_field_exists")

        # Convert 0/1 to boolean
        if result["status"] == "success":
            result["data"] = result["data"] == 1

        return result

    async def _handle_hlen(
        self,
        config: RedisHlenConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get hash length."""
        path = f"/hlen/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_hash_field_count")

    # =========================================================================
    # List Operation Handlers
    # =========================================================================

    async def _handle_lpush(
        self,
        config: RedisLpushConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Push to list head."""
        values_path = "/".join(self._encode_value(v) for v in config.values)
        path = f"/lpush/{self._encode_value(config.key)}/{values_path}"
        return await self._make_request(credentials, path, "push_to_list_beginning")

    async def _handle_rpush(
        self,
        config: RedisRpushConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Push to list tail."""
        values_path = "/".join(self._encode_value(v) for v in config.values)
        path = f"/rpush/{self._encode_value(config.key)}/{values_path}"
        return await self._make_request(credentials, path, "push_to_list_end")

    async def _handle_lpop(
        self,
        config: RedisLpopConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Pop from list head."""
        path = f"/lpop/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/{config.count}"
        return await self._make_request(credentials, path, "pop_first_element")

    async def _handle_rpop(
        self,
        config: RedisRpopConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Pop from list tail."""
        path = f"/rpop/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/{config.count}"
        return await self._make_request(credentials, path, "pop_last_element")

    async def _handle_lrange(
        self,
        config: RedisLrangeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get list range."""
        path = f"/lrange/{self._encode_value(config.key)}/{config.start}/{config.stop}"
        return await self._make_request(credentials, path, "get_list_range")

    async def _handle_llen(
        self,
        config: RedisLlenConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get list length."""
        path = f"/llen/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_list_length")

    async def _handle_lindex(
        self,
        config: RedisLindexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get list element by index."""
        path = f"/lindex/{self._encode_value(config.key)}/{config.index}"
        return await self._make_request(credentials, path, "get_list_element_by_index")

    async def _handle_lset(
        self,
        config: RedisLsetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Set list element by index."""
        path = f"/lset/{self._encode_value(config.key)}/{config.index}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_list_element_by_index")

    # =========================================================================
    # Set Operation Handlers
    # =========================================================================

    async def _handle_sadd(
        self,
        config: RedisSaddConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Add to set."""
        members_path = "/".join(self._encode_value(m) for m in config.members)
        path = f"/sadd/{self._encode_value(config.key)}/{members_path}"
        return await self._make_request(credentials, path, "add_members_to_set")

    async def _handle_srem(
        self,
        config: RedisSremConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Remove from set."""
        members_path = "/".join(self._encode_value(m) for m in config.members)
        path = f"/srem/{self._encode_value(config.key)}/{members_path}"
        return await self._make_request(credentials, path, "remove_members_from_set")

    async def _handle_smembers(
        self,
        config: RedisSmembersConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get all set members."""
        path = f"/smembers/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_all_set_members")

    async def _handle_sismember(
        self,
        config: RedisSismemberConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Check set membership."""
        path = f"/sismember/{self._encode_value(config.key)}/{self._encode_value(config.member)}"
        result = await self._make_request(credentials, path, "check_if_member_in_set")

        # Convert 0/1 to boolean
        if result["status"] == "success":
            result["data"] = result["data"] == 1

        return result

    async def _handle_scard(
        self,
        config: RedisScardConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get set cardinality."""
        path = f"/scard/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_set_member_count")

    async def _handle_sunion(
        self,
        config: RedisSunionConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Union of sets."""
        keys_path = "/".join(self._encode_value(k) for k in config.keys)
        path = f"/sunion/{keys_path}"
        return await self._make_request(credentials, path, "get_set_union")

    async def _handle_sinter(
        self,
        config: RedisSinterConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Intersection of sets."""
        keys_path = "/".join(self._encode_value(k) for k in config.keys)
        path = f"/sinter/{keys_path}"
        return await self._make_request(credentials, path, "get_set_intersection")

    async def _handle_sdiff(
        self,
        config: RedisSdiffConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Difference of sets."""
        keys_path = "/".join(self._encode_value(k) for k in config.keys)
        path = f"/sdiff/{keys_path}"
        return await self._make_request(credentials, path, "get_set_difference")

    # =========================================================================
    # Sorted Set Operation Handlers
    # =========================================================================

    async def _handle_zadd(
        self,
        config: RedisZaddConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Add to sorted set."""
        # Build command for pipeline since ZADD has complex syntax
        cmd = ["ZADD", config.key]
        if config.nx:
            cmd.append("NX")
        if config.xx:
            cmd.append("XX")

        for item in config.members:
            cmd.append(str(item.get("score", 0)))
            cmd.append(str(item.get("member", "")))

        return await self._make_post_request(
            credentials, "/pipeline", [cmd], "add_members_to_sorted_set"
        )

    async def _handle_zrem(
        self,
        config: RedisZremConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Remove from sorted set."""
        members_path = "/".join(self._encode_value(m) for m in config.members)
        path = f"/zrem/{self._encode_value(config.key)}/{members_path}"
        return await self._make_request(credentials, path, "remove_members_from_sorted_set")

    async def _handle_zrange(
        self,
        config: RedisZrangeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get sorted set range."""
        path = f"/zrange/{self._encode_value(config.key)}/{config.start}/{config.stop}"
        if config.withscores:
            path += "/withscores"
        return await self._make_request(credentials, path, "get_sorted_set_member_range")

    async def _handle_zrank(
        self,
        config: RedisZrankConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get sorted set rank."""
        path = f"/zrank/{self._encode_value(config.key)}/{self._encode_value(config.member)}"
        return await self._make_request(credentials, path, "get_sorted_set_member_rank")

    async def _handle_zscore(
        self,
        config: RedisZscoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get sorted set score."""
        path = f"/zscore/{self._encode_value(config.key)}/{self._encode_value(config.member)}"
        return await self._make_request(credentials, path, "get_sorted_set_member_score")

    async def _handle_zcard(
        self,
        config: RedisZcardConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get sorted set cardinality."""
        path = f"/zcard/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_sorted_set_member_count")

    # =========================================================================
    # Key Operation Handlers
    # =========================================================================

    async def _handle_del(
        self,
        config: RedisDelConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Delete keys."""
        keys_path = "/".join(self._encode_value(k) for k in config.keys)
        path = f"/del/{keys_path}"
        return await self._make_request(credentials, path, "delete_keys")

    async def _handle_exists(
        self,
        config: RedisExistsConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Check if keys exist."""
        keys_path = "/".join(self._encode_value(k) for k in config.keys)
        path = f"/exists/{keys_path}"
        result = await self._make_request(credentials, path, "check_if_keys_exist")

        # If checking single key, convert to boolean
        if result["status"] == "success" and len(config.keys) == 1:
            result["data"] = result["data"] > 0

        return result

    async def _handle_expire(
        self,
        config: RedisExpireConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Set key expiration."""
        path = f"/expire/{self._encode_value(config.key)}/{config.seconds}"
        result = await self._make_request(credentials, path, "set_key_expiration_seconds")

        # Convert 0/1 to boolean
        if result["status"] == "success":
            result["data"] = result["data"] == 1

        return result

    async def _handle_ttl(
        self,
        config: RedisTtlConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get key TTL."""
        path = f"/ttl/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_key_time_to_live")

    async def _handle_keys(
        self,
        config: RedisKeysConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Find keys by pattern."""
        path = f"/keys/{self._encode_value(config.pattern)}"
        return await self._make_request(credentials, path, "keys")

    async def _handle_type(
        self,
        config: RedisTypeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Get key type."""
        path = f"/type/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "type")

    async def _handle_rename(
        self,
        config: RedisRenameConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Rename a key."""
        path = f"/rename/{self._encode_value(config.key)}/{self._encode_value(config.newkey)}"
        return await self._make_request(credentials, path, "rename_key")

    # =========================================================================
    # Pipeline Handler
    # =========================================================================


    async def _handle_getdel(
        self,
        config: RedisGetdelConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle getdel operation"""
        path = f"/getdel/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_and_delete_key")


    async def _handle_getex(
        self,
        config: RedisGetexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle getex operation"""
        path = f"/getex/{self._encode_value(config.key)}"
        if config.ex is not None:
            path += f"/ex/{config.ex}"
        if config.px is not None:
            path += f"/px/{config.px}"
        if config.exat is not None:
            path += f"/exat/{config.exat}"
        if config.pxat is not None:
            path += f"/pxat/{config.pxat}"
        if config.persist is not None:
            path += f"/persist/{config.persist}"
        return await self._make_request(credentials, path, "get_with_expiration_options")


    async def _handle_getrange(
        self,
        config: RedisGetrangeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle getrange operation"""
        path = f"/getrange/{self._encode_value(config.key)}/{config.start}/{config.end}"
        return await self._make_request(credentials, path, "get_substring_by_range")


    async def _handle_setrange(
        self,
        config: RedisSetrangeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle setrange operation"""
        path = f"/setrange/{self._encode_value(config.key)}/{config.offset}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_string_range_at_offset")


    async def _handle_incrbyfloat(
        self,
        config: RedisIncrbyfloatConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle incrbyfloat operation"""
        path = f"/incrbyfloat/{self._encode_value(config.key)}/{config.increment}"
        return await self._make_request(credentials, path, "increment_key_by_float")


    async def _handle_decrby(
        self,
        config: RedisDecrbyConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle decrby operation"""
        path = f"/decrby/{self._encode_value(config.key)}/{config.decrement}"
        return await self._make_request(credentials, path, "decrement_key_by_amount")


    async def _handle_msetnx(
        self,
        config: RedisMsetnxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle msetnx operation"""
        path = f"/msetnx/{"/".join(f"{self._encode_value(k)}/{self._encode_value(v)}" for k, v in config.pairs.items())}"
        return await self._make_request(credentials, path, "set_multiple_pairs_if_not_exist")


    async def _handle_setex(
        self,
        config: RedisSetexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle setex operation"""
        path = f"/setex/{self._encode_value(config.key)}/{config.seconds}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_key_value_with_expiration_seconds")


    async def _handle_psetex(
        self,
        config: RedisPsetexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle psetex operation"""
        path = f"/psetex/{self._encode_value(config.key)}/{config.milliseconds}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_key_value_with_expiration_milliseconds")


    async def _handle_setnx(
        self,
        config: RedisSetnxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle setnx operation"""
        path = f"/setnx/{self._encode_value(config.key)}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_key_if_not_exists")


    async def _handle_getset(
        self,
        config: RedisGetsetConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle getset operation"""
        path = f"/getset/{self._encode_value(config.key)}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "get_and_set_key_value")


    async def _handle_hincrby(
        self,
        config: RedisHincrbyConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle hincrby operation"""
        path = f"/hincrby/{self._encode_value(config.key)}/{self._encode_value(config.field)}/{config.increment}"
        return await self._make_request(credentials, path, "increment_hash_field_by_amount")


    async def _handle_hincrbyfloat(
        self,
        config: RedisHincrbyfloatConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle hincrbyfloat operation"""
        path = f"/hincrbyfloat/{self._encode_value(config.key)}/{self._encode_value(config.field)}/{config.increment}"
        return await self._make_request(credentials, path, "increment_hash_field_by_float")


    async def _handle_hsetnx(
        self,
        config: RedisHsetnxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle hsetnx operation"""
        path = f"/hsetnx/{self._encode_value(config.key)}/{self._encode_value(config.field)}/{self._encode_value(config.value)}"
        return await self._make_request(credentials, path, "set_hash_field_if_not_exists")


    async def _handle_hstrlen(
        self,
        config: RedisHstrlenConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle hstrlen operation"""
        path = f"/hstrlen/{self._encode_value(config.key)}/{self._encode_value(config.field)}"
        return await self._make_request(credentials, path, "get_hash_field_value_length")


    async def _handle_hrandfield(
        self,
        config: RedisHrandfieldConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle hrandfield operation"""
        path = f"/hrandfield/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/count/{config.count}"
        if config.withvalues is not None:
            path += f"/withvalues/{config.withvalues}"
        return await self._make_request(credentials, path, "get_random_hash_field")


    async def _handle_hscan(
        self,
        config: RedisHscanConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle hscan operation"""
        path = f"/hscan/{self._encode_value(config.key)}"
        if config.cursor is not None:
            path += f"/cursor/{config.cursor}"
        if config.match is not None:
            path += f"/match/{config.match}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "scan_hash_fields_iteratively")


    async def _handle_linsert(
        self,
        config: RedisLinsertConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle linsert operation"""
        path = f"/linsert/{self._encode_value(config.key)}/{config.where}/{self._encode_value(config.pivot)}/{self._encode_value(config.element)}"
        return await self._make_request(credentials, path, "insert_into_list")


    async def _handle_lrem(
        self,
        config: RedisLremConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle lrem operation"""
        path = f"/lrem/{self._encode_value(config.key)}/{config.count}/{self._encode_value(config.element)}"
        return await self._make_request(credentials, path, "remove_elements_from_list")


    async def _handle_ltrim(
        self,
        config: RedisLtrimConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle ltrim operation"""
        path = f"/ltrim/{self._encode_value(config.key)}/{config.start}/{config.stop}"
        return await self._make_request(credentials, path, "trim_list_to_range")


    async def _handle_lpos(
        self,
        config: RedisLposConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle lpos operation"""
        path = f"/lpos/{self._encode_value(config.key)}/{self._encode_value(config.element)}"
        if config.rank is not None:
            path += f"/rank/{config.rank}"
        if config.count is not None:
            path += f"/count/{config.count}"
        if config.maxlen is not None:
            path += f"/maxlen/{config.maxlen}"
        return await self._make_request(credentials, path, "find_element_position_in_list")


    async def _handle_lmove(
        self,
        config: RedisLmoveConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle lmove operation"""
        path = f"/lmove/{self._encode_value(config.source)}/{self._encode_value(config.destination)}/{config.wherefrom}/{config.whereto}"
        return await self._make_request(credentials, path, "move_element_between_lists")


    async def _handle_lpushx(
        self,
        config: RedisLpushxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle lpushx operation"""
        path = f"/lpushx/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.values)}"
        return await self._make_request(credentials, path, "push_to_list_beginning_if_exists")


    async def _handle_rpushx(
        self,
        config: RedisRpushxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle rpushx operation"""
        path = f"/rpushx/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.values)}"
        return await self._make_request(credentials, path, "push_to_list_end_if_exists")


    async def _handle_rpoplpush(
        self,
        config: RedisRpoplpushConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle rpoplpush operation"""
        path = f"/rpoplpush/{self._encode_value(config.source)}/{self._encode_value(config.destination)}"
        return await self._make_request(credentials, path, "pop_and_push_across_lists")


    async def _handle_spop(
        self,
        config: RedisSpopConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle spop operation"""
        path = f"/spop/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "pop_random_members_from_set")


    async def _handle_srandmember(
        self,
        config: RedisSrandmemberConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle srandmember operation"""
        path = f"/srandmember/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "get_random_set_members")


    async def _handle_smove(
        self,
        config: RedisSmoveConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle smove operation"""
        path = f"/smove/{self._encode_value(config.source)}/{self._encode_value(config.destination)}/{self._encode_value(config.member)}"
        return await self._make_request(credentials, path, "move_member_between_sets")


    async def _handle_sdiffstore(
        self,
        config: RedisSdiffstoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle sdiffstore operation"""
        path = f"/sdiffstore/{self._encode_value(config.destination)}/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "store_set_difference")


    async def _handle_sinterstore(
        self,
        config: RedisSinterstoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle sinterstore operation"""
        path = f"/sinterstore/{self._encode_value(config.destination)}/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "store_set_intersection")


    async def _handle_sunionstore(
        self,
        config: RedisSunionstoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle sunionstore operation"""
        path = f"/sunionstore/{self._encode_value(config.destination)}/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "store_set_union")


    async def _handle_smismember(
        self,
        config: RedisSmismemberConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle smismember operation"""
        path = f"/smismember/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.members)}"
        return await self._make_request(credentials, path, "check_multiple_members_in_set")


    async def _handle_zincrby(
        self,
        config: RedisZincrbyConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zincrby operation"""
        path = f"/zincrby/{self._encode_value(config.key)}/{config.increment}/{self._encode_value(config.member)}"
        return await self._make_request(credentials, path, "increment_sorted_set_member_score")


    async def _handle_zcount(
        self,
        config: RedisZcountConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zcount operation"""
        path = f"/zcount/{self._encode_value(config.key)}/{self._encode_value(config.min)}/{self._encode_value(config.max)}"
        return await self._make_request(credentials, path, "count_sorted_set_members_in_score_range")


    async def _handle_zpopmax(
        self,
        config: RedisZpopmaxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zpopmax operation"""
        path = f"/zpopmax/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "pop_highest_score_member")


    async def _handle_zpopmin(
        self,
        config: RedisZpopminConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zpopmin operation"""
        path = f"/zpopmin/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "pop_lowest_score_member")


    async def _handle_zrevrange(
        self,
        config: RedisZrevrangeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrevrange operation"""
        path = f"/zrevrange/{self._encode_value(config.key)}/{config.start}/{config.stop}"
        if config.withscores is not None:
            path += f"/withscores/{config.withscores}"
        return await self._make_request(credentials, path, "get_sorted_set_member_range_reverse")


    async def _handle_zrevrank(
        self,
        config: RedisZrevrankConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrevrank operation"""
        path = f"/zrevrank/{self._encode_value(config.key)}/{self._encode_value(config.member)}"
        return await self._make_request(credentials, path, "get_sorted_set_member_rank_reverse")


    async def _handle_zrangebyscore(
        self,
        config: RedisZrangebyscoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrangebyscore operation"""
        path = f"/zrangebyscore/{self._encode_value(config.key)}/{self._encode_value(config.min)}/{self._encode_value(config.max)}"
        if config.withscores is not None:
            path += f"/withscores/{config.withscores}"
        if config.limit_offset is not None:
            path += f"/limit_offset/{config.limit_offset}"
        if config.limit_count is not None:
            path += f"/limit_count/{config.limit_count}"
        return await self._make_request(credentials, path, "get_sorted_set_range_by_score")


    async def _handle_zrevrangebyscore(
        self,
        config: RedisZrevrangebyscoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrevrangebyscore operation"""
        path = f"/zrevrangebyscore/{self._encode_value(config.key)}/{self._encode_value(config.max)}/{self._encode_value(config.min)}"
        if config.withscores is not None:
            path += f"/withscores/{config.withscores}"
        if config.limit_offset is not None:
            path += f"/limit_offset/{config.limit_offset}"
        if config.limit_count is not None:
            path += f"/limit_count/{config.limit_count}"
        return await self._make_request(credentials, path, "get_sorted_set_range_by_score_reverse")


    async def _handle_zrangebylex(
        self,
        config: RedisZrangebylexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrangebylex operation"""
        path = f"/zrangebylex/{self._encode_value(config.key)}/{self._encode_value(config.min)}/{self._encode_value(config.max)}"
        if config.limit_offset is not None:
            path += f"/limit_offset/{config.limit_offset}"
        if config.limit_count is not None:
            path += f"/limit_count/{config.limit_count}"
        return await self._make_request(credentials, path, "get_sorted_set_range_by_lexical_order")


    async def _handle_zrevrangebylex(
        self,
        config: RedisZrevrangebylexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrevrangebylex operation"""
        path = f"/zrevrangebylex/{self._encode_value(config.key)}/{self._encode_value(config.max)}/{self._encode_value(config.min)}"
        if config.limit_offset is not None:
            path += f"/limit_offset/{config.limit_offset}"
        if config.limit_count is not None:
            path += f"/limit_count/{config.limit_count}"
        return await self._make_request(credentials, path, "get_sorted_set_range_by_lexical_order_reverse")


    async def _handle_zremrangebyrank(
        self,
        config: RedisZremrangebyrankConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zremrangebyrank operation"""
        path = f"/zremrangebyrank/{self._encode_value(config.key)}/{config.start}/{config.stop}"
        return await self._make_request(credentials, path, "remove_sorted_set_members_by_rank_range")


    async def _handle_zremrangebyscore(
        self,
        config: RedisZremrangebyscoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zremrangebyscore operation"""
        path = f"/zremrangebyscore/{self._encode_value(config.key)}/{self._encode_value(config.min)}/{self._encode_value(config.max)}"
        return await self._make_request(credentials, path, "remove_sorted_set_members_by_score_range")


    async def _handle_zremrangebylex(
        self,
        config: RedisZremrangebylexConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zremrangebylex operation"""
        path = f"/zremrangebylex/{self._encode_value(config.key)}/{self._encode_value(config.min)}/{self._encode_value(config.max)}"
        return await self._make_request(credentials, path, "remove_sorted_set_members_by_lexical_range")


    async def _handle_zlexcount(
        self,
        config: RedisZlexcountConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zlexcount operation"""
        path = f"/zlexcount/{self._encode_value(config.key)}/{self._encode_value(config.min)}/{self._encode_value(config.max)}"
        return await self._make_request(credentials, path, "count_sorted_set_members_in_lexical_range")


    async def _handle_zmscore(
        self,
        config: RedisZmscoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zmscore operation"""
        path = f"/zmscore/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.members)}"
        return await self._make_request(credentials, path, "get_multiple_sorted_set_member_scores")


    async def _handle_zscan(
        self,
        config: RedisZscanConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zscan operation"""
        path = f"/zscan/{self._encode_value(config.key)}"
        if config.cursor is not None:
            path += f"/cursor/{config.cursor}"
        if config.match is not None:
            path += f"/match/{config.match}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "scan_sorted_set_members_iteratively")


    async def _handle_zrandmember(
        self,
        config: RedisZrandmemberConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle zrandmember operation"""
        path = f"/zrandmember/{self._encode_value(config.key)}"
        if config.count is not None:
            path += f"/count/{config.count}"
        if config.withscores is not None:
            path += f"/withscores/{config.withscores}"
        return await self._make_request(credentials, path, "get_random_sorted_set_members")


    async def _handle_setbit(
        self,
        config: RedisSetbitConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle setbit operation"""
        path = f"/setbit/{self._encode_value(config.key)}/{config.offset}/{config.value}"
        return await self._make_request(credentials, path, "set_bit_at_offset")


    async def _handle_getbit(
        self,
        config: RedisGetbitConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle getbit operation"""
        path = f"/getbit/{self._encode_value(config.key)}/{config.offset}"
        return await self._make_request(credentials, path, "get_bit_at_offset")


    async def _handle_bitcount(
        self,
        config: RedisBitcountConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle bitcount operation"""
        path = f"/bitcount/{self._encode_value(config.key)}"
        if config.start is not None:
            path += f"/start/{config.start}"
        if config.end is not None:
            path += f"/end/{config.end}"
        return await self._make_request(credentials, path, "count_set_bits")


    async def _handle_bitpos(
        self,
        config: RedisBitposConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle bitpos operation"""
        path = f"/bitpos/{self._encode_value(config.key)}/{config.bit}"
        if config.start is not None:
            path += f"/start/{config.start}"
        if config.end is not None:
            path += f"/end/{config.end}"
        return await self._make_request(credentials, path, "find_first_bit_position")


    async def _handle_bitop(
        self,
        config: RedisBitopConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle bitop operation"""
        path = f"/bitop/{config.bitop_type}/{self._encode_value(config.destkey)}/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "perform_bitwise_operation")


    async def _handle_bitfield(
        self,
        config: RedisBitfieldConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle bitfield operation"""
        path = f"/bitfield/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.operations)}"
        return await self._make_request(credentials, path, "perform_bitfield_operation")


    async def _handle_pfadd(
        self,
        config: RedisPfaddConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pfadd operation"""
        path = f"/pfadd/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.elements)}"
        return await self._make_request(credentials, path, "add_to_hyperloglog")


    async def _handle_pfcount(
        self,
        config: RedisPfcountConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pfcount operation"""
        path = f"/pfcount/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "count_hyperloglog_cardinality")


    async def _handle_pfmerge(
        self,
        config: RedisPfmergeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pfmerge operation"""
        path = f"/pfmerge/{self._encode_value(config.destkey)}/{"/".join(self._encode_value(str(v)) for v in config.sourcekeys)}"
        return await self._make_request(credentials, path, "merge_hyperloglog_sets")


    async def _handle_geoadd(
        self,
        config: RedisGeoaddConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle geoadd operation"""
        path = f"/geoadd/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.members)}"
        if config.nx is not None:
            path += f"/nx/{config.nx}"
        if config.xx is not None:
            path += f"/xx/{config.xx}"
        return await self._make_request(credentials, path, "add_geospatial_members")


    async def _handle_geodist(
        self,
        config: RedisGeodistConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle geodist operation"""
        path = f"/geodist/{self._encode_value(config.key)}/{self._encode_value(config.member1)}/{self._encode_value(config.member2)}"
        if config.unit is not None:
            path += f"/unit/{config.unit}"
        return await self._make_request(credentials, path, "get_distance_between_geospatial_members")


    async def _handle_geohash(
        self,
        config: RedisGeohashConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle geohash operation"""
        path = f"/geohash/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.members)}"
        return await self._make_request(credentials, path, "get_geohash_for_members")


    async def _handle_geopos(
        self,
        config: RedisGeoposConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle geopos operation"""
        path = f"/geopos/{self._encode_value(config.key)}/{"/".join(self._encode_value(str(v)) for v in config.members)}"
        return await self._make_request(credentials, path, "get_position_of_members")


    async def _handle_geosearch(
        self,
        config: RedisGeosearchConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle geosearch operation"""
        path = f"/geosearch/{self._encode_value(config.key)}"
        if config.frommember is not None:
            path += f"/frommember/{config.frommember}"
        if config.fromlonlat is not None:
            path += f"/fromlonlat/{config.fromlonlat}"
        if config.byradius is not None:
            path += f"/byradius/{config.byradius}"
        if config.bybox is not None:
            path += f"/bybox/{config.bybox}"
        if config.unit is not None:
            path += f"/unit/{config.unit}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "search_geospatial_members")


    async def _handle_geosearchstore(
        self,
        config: RedisGeosearchstoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle geosearchstore operation"""
        path = f"/geosearchstore/{self._encode_value(config.destination)}/{self._encode_value(config.source)}"
        if config.frommember is not None:
            path += f"/frommember/{config.frommember}"
        if config.fromlonlat is not None:
            path += f"/fromlonlat/{config.fromlonlat}"
        if config.byradius is not None:
            path += f"/byradius/{config.byradius}"
        if config.bybox is not None:
            path += f"/bybox/{config.bybox}"
        if config.unit is not None:
            path += f"/unit/{config.unit}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "search_and_store_geospatial_members")


    async def _handle_georadius(
        self,
        config: RedisGeoradiusConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle georadius operation"""
        path = f"/georadius/{self._encode_value(config.key)}/{config.longitude}/{config.latitude}/{config.radius}/{config.unit}"
        if config.withcoord is not None:
            path += f"/withcoord/{config.withcoord}"
        if config.withdist is not None:
            path += f"/withdist/{config.withdist}"
        if config.withhash is not None:
            path += f"/withhash/{config.withhash}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "find_members_in_radius")


    async def _handle_georadiusbymember(
        self,
        config: RedisGeoradiusbymemberConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle georadiusbymember operation"""
        path = f"/georadiusbymember/{self._encode_value(config.key)}/{self._encode_value(config.member)}/{config.radius}/{config.unit}"
        if config.withcoord is not None:
            path += f"/withcoord/{config.withcoord}"
        if config.withdist is not None:
            path += f"/withdist/{config.withdist}"
        if config.withhash is not None:
            path += f"/withhash/{config.withhash}"
        if config.count is not None:
            path += f"/count/{config.count}"
        return await self._make_request(credentials, path, "find_members_in_radius_from_member")


    async def _handle_scan(
        self,
        config: RedisScanConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle scan operation"""
        path = f"/scan"
        if config.cursor is not None:
            path += f"/cursor/{config.cursor}"
        if config.match is not None:
            path += f"/match/{config.match}"
        if config.count is not None:
            path += f"/count/{config.count}"
        if config.type is not None:
            path += f"/type/{config.type}"
        return await self._make_request(credentials, path, "scan_keys_iteratively")


    async def _handle_copy(
        self,
        config: RedisCopyConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle copy operation"""
        path = f"/copy/{self._encode_value(config.source)}/{self._encode_value(config.destination)}"
        if config.replace is not None:
            path += f"/replace/{config.replace}"
        return await self._make_request(credentials, path, "copy_key")


    async def _handle_unlink(
        self,
        config: RedisUnlinkConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle unlink operation"""
        path = f"/unlink/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "unlink_keys_async")


    async def _handle_dump(
        self,
        config: RedisDumpConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle dump operation"""
        path = f"/dump/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "dump_serialized_key")


    async def _handle_restore(
        self,
        config: RedisRestoreConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle restore operation"""
        path = f"/restore/{self._encode_value(config.key)}/{config.ttl}/{self._encode_value(config.serialized_value)}"
        if config.replace is not None:
            path += f"/replace/{config.replace}"
        return await self._make_request(credentials, path, "restore_serialized_key")


    async def _handle_touch(
        self,
        config: RedisTouchConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle touch operation"""
        path = f"/touch/{"/".join(self._encode_value(str(v)) for v in config.keys)}"
        return await self._make_request(credentials, path, "touch_keys_to_update_access_time")


    async def _handle_pexpire(
        self,
        config: RedisPexpireConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pexpire operation"""
        path = f"/pexpire/{self._encode_value(config.key)}/{config.milliseconds}"
        return await self._make_request(credentials, path, "set_key_expiration_milliseconds")


    async def _handle_pexpireat(
        self,
        config: RedisPexpireatConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pexpireat operation"""
        path = f"/pexpireat/{self._encode_value(config.key)}/{config.timestamp}"
        return await self._make_request(credentials, path, "set_key_expiration_at_unix_timestamp_milliseconds")


    async def _handle_pttl(
        self,
        config: RedisPttlConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pttl operation"""
        path = f"/pttl/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_key_time_to_live_milliseconds")


    async def _handle_expireat(
        self,
        config: RedisExpireatConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle expireat operation"""
        path = f"/expireat/{self._encode_value(config.key)}/{config.timestamp}"
        return await self._make_request(credentials, path, "set_key_expiration_at_unix_timestamp")


    async def _handle_expiretime(
        self,
        config: RedisExpiretimeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle expiretime operation"""
        path = f"/expiretime/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_key_expiration_unix_timestamp")


    async def _handle_pexpiretime(
        self,
        config: RedisPexpiretimeConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle pexpiretime operation"""
        path = f"/pexpiretime/{self._encode_value(config.key)}"
        return await self._make_request(credentials, path, "get_key_expiration_unix_timestamp_milliseconds")


    async def _handle_renamenx(
        self,
        config: RedisRenamenxConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle renamenx operation"""
        path = f"/renamenx/{self._encode_value(config.key)}/{self._encode_value(config.newkey)}"
        return await self._make_request(credentials, path, "rename_key_if_new_not_exists")


    async def _handle_randomkey(
        self,
        config: RedisRandomkeyConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle randomkey operation"""
        path = f"/randomkey"
        return await self._make_request(credentials, path, "get_random_key")


    async def _handle_sort(
        self,
        config: RedisSortConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Handle sort operation"""
        path = f"/sort/{self._encode_value(config.key)}"
        if config.by is not None:
            path += f"/by/{config.by}"
        if config.limit_offset is not None:
            path += f"/limit_offset/{config.limit_offset}"
        if config.limit_count is not None:
            path += f"/limit_count/{config.limit_count}"
        if config.get is not None:
            path += f"/get/{'/'.join(str(v) for v in config.get)}"
        if config.order is not None:
            path += f"/order/{config.order}"
        if config.alpha is not None:
            path += f"/alpha/{config.alpha}"
        return await self._make_request(credentials, path, "sort")

    async def _handle_pipeline(
        self,
        config: RedisPipelineConfig,
        credentials: RedisCredential
    ) -> Dict[str, Any]:
        """Execute multiple commands in a pipeline."""
        return await self._make_post_request(
            credentials, "/pipeline", config.commands, "execute_commands_in_pipeline"
        )


    async def _handle_xadd(
        self,
        config: RedisXaddConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Append a new entry to a stream
        """
        # Build command: XADD key [MAXLEN [~] length] id field value [field value ...]
        command = ["XADD", str(config.key)]

        # Add MAXLEN options if specified
        if config.maxlen is not None:
            command.append("MAXLEN")
            if config.approximate:
                command.append("~")
            command.append(str(config.maxlen))

        # Add ID (default is *)
        command.append(str(config.id) if config.id else "*")

        # Add field-value pairs
        for field, value in config.fields.items():
            command.append(str(field))
            command.append(str(value))

        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xread(
        self,
        config: RedisXreadConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Read data from one or more streams
        """
        command = ["XREAD", *[str(k) for pair in config.streams.items() for k in pair], *([] if config.count is None else [str(config.count)]), *([] if config.block is None else [str(config.block)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xreadgroup(
        self,
        config: RedisXreadgroupConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Read data from stream consumer group
        """
        command = ["XREADGROUP", str(config.group), str(config.consumer), *[str(k) for pair in config.streams.items() for k in pair], *([] if config.count is None else [str(config.count)]), *([] if config.block is None else [str(config.block)]), *([] if config.noack is None else [str(config.noack)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xlen(
        self,
        config: RedisXlenConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get the number of entries in a stream
        """
        command = ["XLEN", str(config.key)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xrange(
        self,
        config: RedisXrangeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Return a range of entries from a stream
        """
        command = ["XRANGE", str(config.key), str(config.start), str(config.end), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xrevrange(
        self,
        config: RedisXrevrangeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Return a range of entries in reverse order
        """
        command = ["XREVRANGE", str(config.key), str(config.end), str(config.start), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xdel(
        self,
        config: RedisXdelConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove entries from a stream
        """
        command = ["XDEL", str(config.key), *config.ids]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xtrim(
        self,
        config: RedisXtrimConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Trim stream to a given length
        """
        command = ["XTRIM", str(config.key), str(config.maxlen), *([] if config.approximate is None else [str(config.approximate)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xack(
        self,
        config: RedisXackConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Acknowledge stream messages
        """
        command = ["XACK", str(config.key), str(config.group), *config.ids]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xpending(
        self,
        config: RedisXpendingConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get information about pending messages
        """
        command = ["XPENDING", str(config.key), str(config.group), *([] if config.start is None else [str(config.start)]), *([] if config.end is None else [str(config.end)]), *([] if config.count is None else [str(config.count)]), *([] if config.consumer is None else [str(config.consumer)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xclaim(
        self,
        config: RedisXclaimConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Claim pending messages from another consumer
        """
        command = ["XCLAIM", str(config.key), str(config.group), str(config.consumer), str(config.min_idle_time), *config.ids]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xautoclaim(
        self,
        config: RedisXautoclaimConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Automatically claim pending messages
        """
        command = ["XAUTOCLAIM", str(config.key), str(config.group), str(config.consumer), str(config.min_idle_time), str(config.start), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xgroup_create(
        self,
        config: RedisXgroupCreateConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Create a consumer group
        """
        command = ["XGROUP_CREATE", str(config.key), str(config.group), str(config.id), *([] if config.mkstream is None else [str(config.mkstream)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xgroup_destroy(
        self,
        config: RedisXgroupDestroyConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Destroy a consumer group
        """
        command = ["XGROUP_DESTROY", str(config.key), str(config.group)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xgroup_setid(
        self,
        config: RedisXgroupSetidConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Set the consumer group last delivered ID
        """
        command = ["XGROUP_SETID", str(config.key), str(config.group), str(config.id)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_xinfo_stream(
        self,
        config: RedisXinfoStreamConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get information about a stream
        """
        command = ["XINFO_STREAM", str(config.key)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_set(
        self,
        config: RedisJsonSetConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Set JSON value at path
        """
        command = ["JSON_SET", str(config.key), str(config.path), str(config.value), *([] if config.nx is None else [str(config.nx)]), *([] if config.xx is None else [str(config.xx)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_get(
        self,
        config: RedisJsonGetConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get JSON value from path
        """
        command = ["JSON_GET", str(config.key), *(config.paths if config.paths else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_del(
        self,
        config: RedisJsonDelConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Delete JSON value at path
        """
        command = ["JSON_DEL", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_mget(
        self,
        config: RedisJsonMgetConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get JSON values from multiple keys
        """
        command = ["JSON_MGET", *config.keys, str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_mset(
        self,
        config: RedisJsonMsetConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Set JSON values in multiple keys atomically
        """
        command = ["JSON_MSET", *config.triplets]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_arrappend(
        self,
        config: RedisJsonArrappendConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Append values to JSON array
        """
        command = ["JSON_ARRAPPEND", str(config.key), str(config.path), *config.values]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_arrinsert(
        self,
        config: RedisJsonArrinsertConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Insert values into JSON array at index
        """
        command = ["JSON_ARRINSERT", str(config.key), str(config.path), str(config.index), *config.values]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_arrindex(
        self,
        config: RedisJsonArrindexConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Find index of value in JSON array
        """
        command = ["JSON_ARRINDEX", str(config.key), str(config.path), str(config.value), *([] if config.start is None else [str(config.start)]), *([] if config.stop is None else [str(config.stop)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_arrlen(
        self,
        config: RedisJsonArrlenConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get length of JSON array
        """
        command = ["JSON_ARRLEN", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_arrpop(
        self,
        config: RedisJsonArrpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove and return element from JSON array
        """
        command = ["JSON_ARRPOP", str(config.key), str(config.path), *([] if config.index is None else [str(config.index)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_arrtrim(
        self,
        config: RedisJsonArrtrimConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Trim JSON array to specified range
        """
        command = ["JSON_ARRTRIM", str(config.key), str(config.path), str(config.start), str(config.stop)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_clear(
        self,
        config: RedisJsonClearConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Clear container values (arrays/objects)
        """
        command = ["JSON_CLEAR", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_numincrby(
        self,
        config: RedisJsonNumincrbyConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Increment JSON number by value
        """
        command = ["JSON_NUMINCRBY", str(config.key), str(config.path), str(config.value)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_nummultby(
        self,
        config: RedisJsonNummultbyConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Multiply JSON number by value
        """
        command = ["JSON_NUMMULTBY", str(config.key), str(config.path), str(config.value)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_strappend(
        self,
        config: RedisJsonStrappendConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Append string to JSON string value
        """
        command = ["JSON_STRAPPEND", str(config.key), str(config.path), str(config.value)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_strlen(
        self,
        config: RedisJsonStrlenConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get length of JSON string
        """
        command = ["JSON_STRLEN", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_objkeys(
        self,
        config: RedisJsonObjkeysConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get keys of JSON object
        """
        command = ["JSON_OBJKEYS", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_objlen(
        self,
        config: RedisJsonObjlenConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get number of keys in JSON object
        """
        command = ["JSON_OBJLEN", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_type(
        self,
        config: RedisJsonTypeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get type of JSON value
        """
        command = ["JSON_TYPE", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_merge(
        self,
        config: RedisJsonMergeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Merge JSON values
        """
        command = ["JSON_MERGE", str(config.key), str(config.path), str(config.value)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_toggle(
        self,
        config: RedisJsonToggleConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Toggle JSON boolean value
        """
        command = ["JSON_TOGGLE", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_json_resp(
        self,
        config: RedisJsonRespConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Return JSON value in RESP form
        """
        command = ["JSON_RESP", str(config.key), str(config.path)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_eval(
        self,
        config: RedisEvalConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Execute Lua script
        """
        command = ["EVAL", str(config.script), *config.keys, *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_evalsha(
        self,
        config: RedisEvalshaConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Execute Lua script by SHA1 digest
        """
        command = ["EVALSHA", str(config.sha1), *config.keys, *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_eval_ro(
        self,
        config: RedisEvalRoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Execute read-only Lua script
        """
        command = ["EVAL_RO", str(config.script), *config.keys, *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_evalsha_ro(
        self,
        config: RedisEvalshaRoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Execute read-only Lua script by SHA1
        """
        command = ["EVALSHA_RO", str(config.sha1), *config.keys, *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_fcall(
        self,
        config: RedisFcallConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Call Redis function
        """
        command = ["FCALL", str(config.function), *config.keys, *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_fcall_ro(
        self,
        config: RedisFcallRoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Call read-only Redis function
        """
        command = ["FCALL_RO", str(config.function), *config.keys, *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_function_load(
        self,
        config: RedisFunctionLoadConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Load Redis function library
        """
        command = ["FUNCTION_LOAD", str(config.library_code), *([] if config.replace is None else [str(config.replace)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_function_delete(
        self,
        config: RedisFunctionDeleteConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Delete Redis function library
        """
        command = ["FUNCTION_DELETE", str(config.library_name)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_function_flush(
        self,
        config: RedisFunctionFlushConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Delete all function libraries
        """
        command = ["FUNCTION_FLUSH", *([] if config.mode is None else [str(config.mode)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_function_list(
        self,
        config: RedisFunctionListConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        List all function libraries
        """
        command = ["FUNCTION_LIST", *([] if config.library_name is None else [str(config.library_name)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_function_stats(
        self,
        config: RedisFunctionStatsConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get function execution statistics
        """
        command = ["FUNCTION_STATS"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_script_exists(
        self,
        config: RedisScriptExistsConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Check if scripts exist
        """
        command = ["SCRIPT_EXISTS", *config.sha1s]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_script_flush(
        self,
        config: RedisScriptFlushConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove all scripts from script cache
        """
        command = ["SCRIPT_FLUSH", *([] if config.mode is None else [str(config.mode)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_script_load(
        self,
        config: RedisScriptLoadConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Load script into cache
        """
        command = ["SCRIPT_LOAD", str(config.script)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_publish(
        self,
        config: RedisPublishConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Post a message to a channel
        """
        command = ["PUBLISH", str(config.channel), str(config.message)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_subscribe(
        self,
        config: RedisSubscribeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Subscribe to channels
        """
        command = ["SUBSCRIBE", *config.channels]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_unsubscribe(
        self,
        config: RedisUnsubscribeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Unsubscribe from channels
        """
        command = ["UNSUBSCRIBE", *(config.channels if config.channels else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_psubscribe(
        self,
        config: RedisPsubscribeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Subscribe to channels matching patterns
        """
        command = ["PSUBSCRIBE", *config.patterns]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_punsubscribe(
        self,
        config: RedisPunsubscribeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Unsubscribe from channel patterns
        """
        command = ["PUNSUBSCRIBE", *(config.patterns if config.patterns else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_pubsub(
        self,
        config: RedisPubsubConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get pub/sub system state
        """
        command = ["PUBSUB", str(config.subcommand), *(config.args if config.args else [])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_multi(
        self,
        config: RedisMultiConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Mark the start of a transaction block
        """
        command = ["MULTI"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_exec(
        self,
        config: RedisExecConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Execute all commands in transaction
        """
        command = ["EXEC"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_discard(
        self,
        config: RedisDiscardConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Discard all commands in transaction
        """
        command = ["DISCARD"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_watch(
        self,
        config: RedisWatchConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Watch keys for conditional execution
        """
        command = ["WATCH", *config.keys]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_unwatch(
        self,
        config: RedisUnwatchConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Unwatch all keys
        """
        command = ["UNWATCH"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_ping(
        self,
        config: RedisPingConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Ping the server
        """
        command = ["PING", *([] if config.message is None else [str(config.message)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_echo(
        self,
        config: RedisEchoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Echo the given string
        """
        command = ["ECHO", str(config.message)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_select(
        self,
        config: RedisSelectConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Select the database
        """
        command = ["SELECT", str(config.index)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_auth(
        self,
        config: RedisAuthConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Authenticate to the server
        """
        command = ["AUTH", str(config.password), *([] if config.username is None else [str(config.username)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_hello(
        self,
        config: RedisHelloConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Handshake with server
        """
        command = ["HELLO", *([] if config.protover is None else [str(config.protover)]), *([] if config.auth_user is None else [str(config.auth_user)]), *([] if config.auth_pass is None else [str(config.auth_pass)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_quit(
        self,
        config: RedisQuitConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Close the connection
        """
        command = ["QUIT"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_reset(
        self,
        config: RedisResetConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Reset the connection state
        """
        command = ["RESET"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_client_id(
        self,
        config: RedisClientIdConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get client connection ID
        """
        command = ["CLIENT_ID"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_client_getname(
        self,
        config: RedisClientGetnameConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get the connection name
        """
        command = ["CLIENT_GETNAME"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_client_setname(
        self,
        config: RedisClientSetnameConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Set the connection name
        """
        command = ["CLIENT_SETNAME", str(config.name)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_client_info(
        self,
        config: RedisClientInfoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get client connection info
        """
        command = ["CLIENT_INFO"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_client_list(
        self,
        config: RedisClientListConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        List all client connections
        """
        command = ["CLIENT_LIST", *([] if config.client_type is None else [str(config.client_type)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_client_setinfo(
        self,
        config: RedisClientSetinfoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Set client connection attributes
        """
        command = ["CLIENT_SETINFO", str(config.attr), str(config.value)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_dbsize(
        self,
        config: RedisDbsizeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get the number of keys in database
        """
        command = ["DBSIZE"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_flushall(
        self,
        config: RedisFlushallConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove all keys from all databases
        """
        command = ["FLUSHALL", *([] if config.mode is None else [str(config.mode)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_flushdb(
        self,
        config: RedisFlushdbConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove all keys from current database
        """
        command = ["FLUSHDB", *([] if config.mode is None else [str(config.mode)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_monitor(
        self,
        config: RedisMonitorConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Listen for all requests received by server
        """
        command = ["MONITOR"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_time(
        self,
        config: RedisTimeConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get server time
        """
        command = ["TIME"]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_blpop(
        self,
        config: RedisBlpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove and get the first element, block if empty
        """
        command = ["BLPOP", *config.keys, str(config.timeout)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_brpop(
        self,
        config: RedisBrpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove and get the last element, block if empty
        """
        command = ["BRPOP", *config.keys, str(config.timeout)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_blmove(
        self,
        config: RedisBlmoveConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Pop element from source, push to dest, block if empty
        """
        command = ["BLMOVE", str(config.source), str(config.destination), str(config.wherefrom), str(config.whereto), str(config.timeout)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_brpoplpush(
        self,
        config: RedisBrpoplpushConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Pop from source, push to dest, block if empty
        """
        command = ["BRPOPLPUSH", str(config.source), str(config.destination), str(config.timeout)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_blmpop(
        self,
        config: RedisBlmpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Pop elements from lists, block if empty
        """
        command = ["BLMPOP", str(config.timeout), *config.keys, str(config.direction), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_lmpop(
        self,
        config: RedisLmpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Pop elements from multiple lists
        """
        command = ["LMPOP", *config.keys, str(config.direction), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_sintercard(
        self,
        config: RedisSintercardConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get cardinality of intersection between sets
        """
        command = ["SINTERCARD", *config.keys, *([] if config.limit is None else [str(config.limit)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_sscan(
        self,
        config: RedisSscanConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Incrementally iterate set members
        """
        command = ["SSCAN", str(config.key), str(config.cursor), *([] if config.match is None else [str(config.match)]), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_bzmpop(
        self,
        config: RedisBzmpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Pop elements from sorted sets, block if empty
        """
        command = ["BZMPOP", str(config.timeout), *config.keys, str(config.modifier), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_bzpopmax(
        self,
        config: RedisBzpopmaxConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove and return highest scored member, block if empty
        """
        command = ["BZPOPMAX", *config.keys, str(config.timeout)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_bzpopmin(
        self,
        config: RedisBzpopminConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Remove and return lowest scored member, block if empty
        """
        command = ["BZPOPMIN", *config.keys, str(config.timeout)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zdiff(
        self,
        config: RedisZdiffConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get difference between sorted sets
        """
        command = ["ZDIFF", *config.keys, *([] if config.withscores is None else [str(config.withscores)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zdiffstore(
        self,
        config: RedisZdiffstoreConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Store difference of sorted sets
        """
        command = ["ZDIFFSTORE", str(config.destination), *config.keys]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zinter(
        self,
        config: RedisZinterConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get intersection of sorted sets
        """
        command = ["ZINTER", *config.keys, *(config.weights if config.weights else []), *([] if config.aggregate is None else [str(config.aggregate)]), *([] if config.withscores is None else [str(config.withscores)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zintercard(
        self,
        config: RedisZintercardConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get cardinality of sorted set intersection
        """
        command = ["ZINTERCARD", *config.keys, *([] if config.limit is None else [str(config.limit)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zinterstore(
        self,
        config: RedisZinterstoreConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Store intersection of sorted sets
        """
        command = ["ZINTERSTORE", str(config.destination), *config.keys, *(config.weights if config.weights else []), *([] if config.aggregate is None else [str(config.aggregate)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zmpop(
        self,
        config: RedisZmpopConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Pop elements from sorted sets
        """
        command = ["ZMPOP", *config.keys, str(config.modifier), *([] if config.count is None else [str(config.count)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zrangestore(
        self,
        config: RedisZrangestoreConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Store range from sorted set
        """
        command = ["ZRANGESTORE", str(config.destination), str(config.source), str(config.start), str(config.stop), *([] if config.by is None else [str(config.by)]), *([] if config.rev is None else [str(config.rev)]), *([] if config.limit is None else [str(config.limit)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zunion(
        self,
        config: RedisZunionConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get union of sorted sets
        """
        command = ["ZUNION", *config.keys, *(config.weights if config.weights else []), *([] if config.aggregate is None else [str(config.aggregate)]), *([] if config.withscores is None else [str(config.withscores)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_zunionstore(
        self,
        config: RedisZunionstoreConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Store union of sorted sets
        """
        command = ["ZUNIONSTORE", str(config.destination), *config.keys, *(config.weights if config.weights else []), *([] if config.aggregate is None else [str(config.aggregate)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_bitfield_ro(
        self,
        config: RedisBitfieldRoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Read-only bitfield operations
        """
        command = ["BITFIELD_RO", str(config.key), *config.operations]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_hgetdel(
        self,
        config: RedisHgetdelConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get hash field value and delete it
        """
        command = ["HGETDEL", str(config.key), str(config.field)]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_hgetex(
        self,
        config: RedisHgetexConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Get hash field with expiration
        """
        command = ["HGETEX", str(config.key), str(config.field), *([] if config.ex is None else [str(config.ex)]), *([] if config.px is None else [str(config.px)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_hsetex(
        self,
        config: RedisHsetexConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Set hash field with expiration
        """
        command = ["HSETEX", str(config.key), str(config.field), str(config.value), *([] if config.ex is None else [str(config.ex)]), *([] if config.px is None else [str(config.px)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_georadius_ro(
        self,
        config: RedisGeoradiusRoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Read-only query radius with center coordinates
        """
        command = ["GEORADIUS_RO", str(config.key), str(config.longitude), str(config.latitude), str(config.radius), str(config.unit), *([] if config.withcoord is None else [str(config.withcoord)]), *([] if config.withdist is None else [str(config.withdist)]), *([] if config.withhash is None else [str(config.withhash)]), *([] if config.count is None else [str(config.count)]), *([] if config.sort is None else [str(config.sort)])]
        return await self._make_post_request(credentials, "/", command, config.operation)

    async def _handle_georadiusbymember_ro(
        self,
        config: RedisGeoradiusbymemberRoConfig,
        credentials: Union[RedisStandardCredential, RedisReadOnlyCredential, RedisACLCredential]
    ) -> Dict[str, Any]:
        """
        Read-only query radius with center member
        """
        command = ["GEORADIUSBYMEMBER_RO", str(config.key), str(config.member), str(config.radius), str(config.unit), *([] if config.withcoord is None else [str(config.withcoord)]), *([] if config.withdist is None else [str(config.withdist)]), *([] if config.withhash is None else [str(config.withhash)]), *([] if config.count is None else [str(config.count)]), *([] if config.sort is None else [str(config.sort)])]
        return await self._make_post_request(credentials, "/", command, config.operation)
