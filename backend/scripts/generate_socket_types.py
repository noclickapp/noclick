#!/usr/bin/env python3
"""
Generate TypeScript types from Pydantic socket event models.
This script converts backend event definitions to frontend TypeScript interfaces.

Generates TypeScript types from backend Pydantic models for the NoClick frontend.
"""
import sys
import re
import inspect
import argparse
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel
from pydantic2ts import generate_typescript_defs

# Import event modules to introspect them
from nodes.core.base import _mark_sole_option_autofill
import wss.sender.events as events_module
import wss.receiver.client_events as client_events_module
import wss.sender.responses as responses_module

# Global flag for quiet mode
_quiet_mode = False

def qprint(*args, **kwargs):
    """Print only if not in quiet mode"""
    if not _quiet_mode:
        print(*args, **kwargs)

def content_has_changed(file_path: Path, new_content: str, timestamp_pattern: str = None) -> bool:
    """
    Check if the file content has actually changed, ignoring timestamp lines.

    Args:
        file_path: Path to the existing file
        new_content: The new content to compare
        timestamp_pattern: Regex pattern to match timestamp lines to ignore

    Returns:
        True if content has changed (or file doesn't exist), False otherwise
    """
    if not file_path.exists():
        return True

    try:
        with open(file_path, 'r') as f:
            existing_content = f.read()
    except Exception:
        return True

    if timestamp_pattern:
        # Remove timestamp lines from both contents for comparison
        existing_filtered = re.sub(timestamp_pattern, '', existing_content)
        new_filtered = re.sub(timestamp_pattern, '', new_content)
        return existing_filtered != new_filtered

    return existing_content != new_content

def write_if_changed(file_path: Path, content: str, timestamp_pattern: str = None) -> bool:
    """
    Write content to file only if it has actually changed (ignoring timestamps).

    Args:
        file_path: Path to write to
        content: Content to write
        timestamp_pattern: Regex pattern to match timestamp lines to ignore

    Returns:
        True if file was written, False if unchanged
    """
    if content_has_changed(file_path, content, timestamp_pattern):
        with open(file_path, 'w') as f:
            # Exactly one newline at EOF: a trailing blank line fails `git diff --check`.
            f.write(content.rstrip("\n") + "\n")
        return True
    return False

# Pattern to match the timestamp line in generated TypeScript files
TS_TIMESTAMP_PATTERN = r'// Generated at:.*\n'

def parse_object_type(type_str: str):
    """
    Parse a TypeScript object type string to extract parameters.
    E.g., "{ file_id: string; chunk: ArrayBuffer }" -> [("file_id", "string"), ("chunk", "ArrayBuffer")]
    """
    if not type_str or not (type_str.strip().startswith('{') and type_str.strip().endswith('}')):
        return None
    
    # Remove outer braces and whitespace
    content = type_str.strip()[1:-1].strip()
    
    # Split by semicolon or comma (handle both styles)
    parts = re.split(r'[;,]', content)
    
    params = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Split by colon to get name and type
        match = re.match(r'(\w+)\s*:\s*(.+)', part)
        if match:
            param_name = match.group(1)
            param_type = match.group(2).strip()
            params.append((param_name, param_type))
    
    return params if params else None

def should_include_event(obj, target):
    """
    Check if an event should be included based on the target.

    Args:
        obj: Pydantic model class
        target: 'all' or 'template'

    Returns:
        True if the event should be included, False otherwise
    """
    if target == 'all':
        return True

    # For template target, only include events marked as available_in_template
    return getattr(obj, 'available_in_template', False)

def generate_types(target='all', output_dir=None, quiet=False):
    """
    Generate TypeScript types from Pydantic models.

    Args:
        target: 'all' for all events (only valid option)
        output_dir: Custom output directory (optional)
        quiet: Suppress verbose output (optional)
    """
    backend_dir = Path(__file__).parent.parent

    # Determine output directory
    if output_dir:
        frontend_types_dir = Path(output_dir)
    else:
        frontend_types_dir = backend_dir.parent / "frontend" / "app" / "types"

    # Ensure output directory exists
    frontend_types_dir.mkdir(parents=True, exist_ok=True)

    # Generate header with timestamp
    header = f"""// Auto-generated from backend Pydantic models
// DO NOT EDIT MANUALLY - run 'npm run generate:types' instead
// Generated at: {datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}
// Target: {target}

"""
    
    # Automatically generate event mappings by introspecting the event classes
    server_events = []

    # Find all event classes in the events module
    for name, obj in inspect.getmembers(events_module):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and hasattr(obj, 'event_name') and should_include_event(obj, target):
            event_name = obj.event_name
            
            # Check if the class has a custom model_dump that returns a primitive type
            if hasattr(obj, 'model_dump') and obj.__name__ != 'BaseModel':
                # Introspect the model_dump method to determine return type
                method = getattr(obj, 'model_dump')
                if hasattr(method, '__annotations__') and 'return' in method.__annotations__:
                    return_type = method.__annotations__['return']
                    if return_type == str:
                        server_events.append(f"  '{event_name}': (data: string) => void;  // Special case: returns raw string")
                    elif return_type == bool:
                        server_events.append(f"  '{event_name}': (data: boolean) => void;  // Special case: returns boolean")
                    elif return_type == bytes:
                        server_events.append(f"  '{event_name}': (data: Uint8Array) => void;  // Special case: binary data")
                    elif return_type == list:
                        server_events.append(f"  '{event_name}': (data: number[]) => void;  // Special case: byte array")
                    elif return_type is None or str(return_type) == "<class 'NoneType'>":
                        server_events.append(f"  '{event_name}': () => void;  // Special case: no payload")
                    else:
                        server_events.append(f"  '{event_name}': (data: {name}) => void;")
                else:
                    server_events.append(f"  '{event_name}': (data: {name}) => void;")
            else:
                server_events.append(f"  '{event_name}': (data: {name}) => void;")

    # Also check response models for MCP dual delivery events
    # These have mcp_config ClassVar with frontend_event_name
    for name, obj in inspect.getmembers(responses_module):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and hasattr(obj, 'mcp_config') and should_include_event(obj, target):
            mcp_config = obj.mcp_config
            if isinstance(mcp_config, dict) and 'frontend_event_name' in mcp_config:
                frontend_event_name = mcp_config['frontend_event_name']
                server_events.append(f"  '{frontend_event_name}': (data: {name}) => void;  // MCP dual delivery")

    # Sort events for consistent output
    server_events.sort()

    # Add internal chunking event (used for backend -> frontend large message chunking)
    # This is not a public API event, but needs to be in ServerToClientEvents for type safety
    server_events.append("  '__chunk__': (data: { __chunk_id: string; __chunk_index: number; __chunk_total: number; __chunk_data: string }) => void;  // Internal: chunked message fragment")

    # Automatically generate client event mappings
    client_events = []

    # Find all client event classes
    for name, obj in inspect.getmembers(client_events_module):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and hasattr(obj, 'event_name') and should_include_event(obj, target):
            event_name = obj.event_name
            
            # Check if the class defines a custom TypeScript type
            if hasattr(obj, 'get_typescript_type'):
                custom_type = obj.get_typescript_type()
                if custom_type:
                    # Use the custom type
                    if custom_type == 'any':
                        client_events.append(f"  '{event_name}': (data: {custom_type}) => void;  // Complex structure")
                    elif custom_type == 'string':
                        client_events.append(f"  '{event_name}': (data: {custom_type}) => void;  // Raw string")
                    else:
                        client_events.append(f"  '{event_name}': (data: {custom_type}) => void;")
                else:
                    # Use default interface name
                    client_events.append(f"  '{event_name}': (data: {name}) => void;")
            else:
                # Use default interface name
                client_events.append(f"  '{event_name}': (data: {name}) => void;")
    
    # Sort for consistent output
    client_events.sort()

    # Large frontend -> backend payloads use the same transport-level chunk
    # envelope as backend -> frontend payloads. This event is handled before
    # application routing, so it has no Pydantic request model to discover.
    client_events.append("  '__chunk__': (data: { __chunk_id: string; __chunk_index: number; __chunk_total: number; __chunk_data: string }) => void;  // Internal: chunked message fragment")
    
    # Automatically discover request/response mappings based on naming convention
    # Convention: *Request classes map to *Response classes with the same base name
    # E.g., DatabaseListRequest -> DatabaseListResponse
    request_response_mappings = {}
    
    # Collect all Request classes from client_events_module
    request_classes = {}
    for name, obj in inspect.getmembers(client_events_module):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and name.endswith('Request') and should_include_event(obj, target):
            request_classes[name] = obj

    # Collect all Response classes from responses_module
    response_classes = {}
    for name, obj in inspect.getmembers(responses_module):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and name.endswith('Response') and should_include_event(obj, target):
            response_classes[name] = obj
    
    # Match requests to responses based on naming convention
    # For each *Request, look for corresponding *Response
    for request_name, request_class in request_classes.items():
        # First check if the class has explicit response_type metadata
        if hasattr(request_class, 'response_type'):
            # Use explicit mapping if defined
            response_name = request_class.response_type
            if response_name in response_classes:
                request_response_mappings[request_name] = response_name
                qprint(f"  Mapped (explicit): {request_name} -> {response_name}")
            else:
                qprint(f"  Error: Explicit response type {response_name} not found for {request_name}")
        else:
            # Use naming convention: strip 'Request' suffix and add 'Response' suffix
            base_name = request_name[:-7]  # Remove 'Request'
            response_name = base_name + 'Response'
            
            # Check if corresponding response exists
            if response_name in response_classes:
                request_response_mappings[request_name] = response_name
                qprint(f"  Mapped: {request_name} -> {response_name}")
            else:
                # Check if this request expects a response
                if hasattr(request_class, 'expects_response') and not request_class.expects_response:
                    # This is a one-way event, no response expected
                    qprint(f"  One-way: {request_name} (no response expected)")
                else:
                    # This request expects a response but none was found
                    qprint(f"  Warning: No response found for {request_name} (expects response)")
    
    # Generate request/response type mapping
    request_response_map = []
    request_response_map.append("// Request to Response Type Mapping (auto-discovered)")
    request_response_map.append("export interface RequestResponseMap {")
    
    # Sort mappings for consistent output
    sorted_mappings = sorted(request_response_mappings.items())
    for request_type, response_type in sorted_mappings:
        request_response_map.append(f"  {request_type}: {response_type};")
    
    request_response_map.append("}")
    request_response_map.append("")
    request_response_map.append("// Helper type to infer response type from request")
    request_response_map.append("export type InferResponseType<T> = T extends keyof RequestResponseMap ? RequestResponseMap[T] : any;")
    request_response_map.append("")
    
    # Generate event name mappings, companion objects, and type map for client events
    client_event_map = []
    companion_objects = []
    client_event_type_map = []  # For ClientEventMap interface

    for name, obj in inspect.getmembers(client_events_module):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and hasattr(obj, 'event_name') and should_include_event(obj, target):
            event_name = obj.event_name
            client_event_map.append(f"  {name}: '{event_name}'")
            
            # Generate companion object with event_name and create function
            # This mirrors the Python class with its event_name ClassVar
            if hasattr(obj, 'get_typescript_type'):
                custom_type = obj.get_typescript_type()
                
                # Try to parse as object type
                parsed_params = parse_object_type(custom_type)
                
                if parsed_params:
                    # It's an object type - generate parameters based on parsed structure
                    param_list = ', '.join(f"{p[0]}: {p[1]}" for p in parsed_params)
                    obj_props = ', '.join(f"{p[0]}" for p in parsed_params)
                    companion_objects.append(f"""
export const {name} = {{
  event_name: '{event_name}' as const,
  create: ({param_list}) => ({{ event_name: '{event_name}' as const, {obj_props} }})
}};""")
                    # Add to type map with the custom type
                    client_event_type_map.append(f"  {name}: {custom_type}")
                elif custom_type and custom_type in ['string', 'any', 'Uint8Array | number[]']:
                    # For simple types, create a simpler companion
                    companion_objects.append(f"""
export const {name} = {{
  event_name: '{event_name}' as const,
  create: (data: {custom_type}) => ({{ event_name: '{event_name}' as const, data }})
}};""")
                    # Add to type map
                    client_event_type_map.append(f"  {name}: {custom_type}")
                else:
                    # Standard object companion
                    companion_objects.append(f"""
export const {name} = {{
  event_name: '{event_name}' as const,
  create: (data: {name}) => ({{ event_name: '{event_name}' as const, ...data }})
}};""")
                    # Add to type map
                    client_event_type_map.append(f"  {name}: {name}")
            else:
                # Standard interface companion
                companion_objects.append(f"""
export const {name} = {{
  event_name: '{event_name}' as const,
  create: (data: {name}) => ({{ event_name: '{event_name}' as const, ...data }})
}};""")
                # Add to type map
                client_event_type_map.append(f"  {name}: {name}")
    
    client_event_map.sort()
    client_event_type_map.sort()  # Sort type map for consistency
    
    # Import event routing configuration directly
    from wss.receiver.event_routing import get_all_events, EVENT_ROUTING
    
    event_routing_map = get_all_events()
    
    if not event_routing_map:
        raise RuntimeError("No event routing configuration found")
    
    qprint(f"Loaded event routing for {len(event_routing_map)} events")
    
    # Find events that exist in multiple environments
    multi_env_events = {}
    for event in event_routing_map:
        envs = []
        for env, events in EVENT_ROUTING.items():
            if event in events:
                envs.append(env)
        if len(envs) > 1:
            multi_env_events[event] = envs
    
    # Generate TypeScript EventRouting constant
    # For template target, only include events we're keeping
    if target == 'template':
        # Get event names from kept client event classes
        kept_event_names = set()
        for name, obj in inspect.getmembers(client_events_module):
            if inspect.isclass(obj) and issubclass(obj, BaseModel) and hasattr(obj, 'event_name') and should_include_event(obj, target):
                kept_event_names.add(obj.event_name)

        # Filter event routing to only kept events
        filtered_routing = {event: env for event, env in event_routing_map.items() if event in kept_event_names}
        event_routing_map = filtered_routing

    event_routing_lines = []
    for event, env in sorted(event_routing_map.items()):
        # Add comment for events that exist in multiple environments
        comment = ""
        if event in multi_env_events:
            other_envs = [e for e in multi_env_events[event] if e != env]
            comment = f"  // Primary in {env}, but also available in {', '.join(other_envs)}"
        event_routing_lines.append(f"  '{event}': '{env}',{comment}")
    
    event_routing = f"""
// Event routing configuration (imported from backend's event_routing.py)
export const EventRouting = {{
{chr(10).join(event_routing_lines)}
}} as const;

export type SocketEnvironment = 'API';
"""
    
    event_mappings = f"""
// Event name to type mappings for type-safe socket handling
export interface ServerToClientEvents {{
{chr(10).join(server_events)}
}}

export interface ClientToServerEvents {{
{chr(10).join(client_events)}
}}

// Mapping of request type names to their event names
export const ClientEventNames = {{
{','.join(chr(10) + e for e in client_event_map)}
}} as const;

// Type for events with their names included
export type ClientEventWithName<T extends keyof typeof ClientEventNames> = {{
  event_name: typeof ClientEventNames[T];
  data: T extends keyof ClientEventMap ? ClientEventMap[T] : never;
}};

// Helper type to map event names to their data types (auto-generated)
interface ClientEventMap {{
{chr(10).join(client_event_type_map)}
}}

{chr(10).join(request_response_map)}

// Companion objects for each event type (mirrors Python's event_name ClassVar)
// These allow you to access event_name at runtime and create properly typed events
{''.join(companion_objects)}

{event_routing}
"""
    
    # Generate schema types only for 'all' target, not for 'template'
    # Template only needs database events which don't reference schema types
    schema_interfaces = set()
    if target != 'template':
        schema_output = frontend_types_dir / "socket-schema.generated.ts"
        schema_temp = frontend_types_dir / "socket-schema.temp.ts"
        qprint(f"Generating TypeScript types from wss.sender.schema...")

        try:
            # Generate TypeScript definitions for schema to temp file
            generate_typescript_defs("wss.sender.schema", str(schema_temp))

            # Parse schema to find all exported interfaces
            with open(schema_temp, 'r') as f:
                schema_content = f.read()

            # Remove temp file
            schema_temp.unlink()

            # Extract all interface names from schema
            import re
            schema_interfaces = set(re.findall(r'export interface (\w+)', schema_content))
            qprint(f"Found {len(schema_interfaces)} interfaces in schema: {schema_interfaces}")

            # Add header to schema file (only write if content changed)
            full_schema_content = header + schema_content
            if write_if_changed(schema_output, full_schema_content, TS_TIMESTAMP_PATTERN):
                qprint(f"✓ Generated schema types at: {schema_output}")
            else:
                qprint(f"✓ Schema types unchanged: {schema_output}")
        except Exception as e:
            qprint(f"Error generating schema types: {e}")
            raise
    else:
        qprint(f"Skipping schema generation for template target (not needed for database events)")
    
    # Generate socket events types
    output_file = frontend_types_dir / "socket-events.generated.ts"
    qprint(f"Generating TypeScript types from wss.sender.events and wss.receiver.client_events...")

    try:
        # Generate TypeScript definitions for server events to temp file
        server_temp_file = frontend_types_dir / "socket-server-events.temp.ts"
        generate_typescript_defs("wss.sender.events", str(server_temp_file))

        # Generate TypeScript definitions for client events to temp file
        client_output_file = frontend_types_dir / "socket-client-events.temp.ts"
        generate_typescript_defs("wss.receiver.client_events", str(client_output_file))

        # Generate TypeScript definitions for response types to temp file
        response_output_file = frontend_types_dir / "socket-responses.temp.ts"
        generate_typescript_defs("wss.sender.responses", str(response_output_file))

        # Read server events content
        with open(server_temp_file, 'r') as f:
            server_content = f.read()

        # Read client events content
        with open(client_output_file, 'r') as f:
            client_content = f.read()

        # Read response types content
        with open(response_output_file, 'r') as f:
            response_content = f.read()

        # Remove the temporary files
        server_temp_file.unlink()
        client_output_file.unlink()
        response_output_file.unlink()
        
        # Combine server, client, and response content
        combined_content = server_content + "\n" + client_content + "\n" + response_content
        
        # Remove duplicate numbered interfaces (e.g., AppInfo1, ViteAppInfo1)
        # pydantic2ts creates these duplicates when a model is referenced multiple times
        import re
        
        # Find all numbered interface duplicates (e.g., SomeModel1, SomeModel2)
        numbered_interfaces = re.findall(r'export interface (\w+?)(\d+)[^}]*?\n}', combined_content, flags=re.DOTALL)
        
        # Get unique base names that have numbered duplicates
        base_names_with_duplicates = set()
        for base_name, number in numbered_interfaces:
            base_names_with_duplicates.add(base_name)
        
        # For each base name with duplicates, remove the numbered versions and fix references
        for base_name in base_names_with_duplicates:
            # Remove numbered interface definitions (e.g., AppInfo1, AppInfo2)
            combined_content = re.sub(f'export interface {base_name}\\d+[^}}]*?\\n}}', '', combined_content, flags=re.DOTALL)
            
            # Fix references to numbered versions (e.g., AppInfo1 -> AppInfo)
            combined_content = re.sub(f'{base_name}\\d+', base_name, combined_content)

        # For template target, remove interfaces for events not marked as available_in_template
        if target == 'template':
            # Collect names of all classes we want to keep
            classes_to_keep = set()

            # Add request classes marked as available_in_template
            for name, obj in inspect.getmembers(client_events_module):
                if inspect.isclass(obj) and issubclass(obj, BaseModel) and should_include_event(obj, target):
                    classes_to_keep.add(name)

            # Add response classes marked as available_in_template
            for name, obj in inspect.getmembers(responses_module):
                if inspect.isclass(obj) and issubclass(obj, BaseModel) and should_include_event(obj, target):
                    classes_to_keep.add(name)

            # Add infrastructure server events explicitly marked as available_in_template
            # (e.g., ResponseEvent, ServerDataEvent for generic response handling)
            for name, obj in inspect.getmembers(events_module):
                if inspect.isclass(obj) and issubclass(obj, BaseModel) and should_include_event(obj, target):
                    classes_to_keep.add(name)

            # Automatically discover and keep all types referenced by our kept classes
            # This ensures we don't hardcode dependencies - they're discovered from the Pydantic models
            def extract_referenced_types(model_class, visited=None):
                """Recursively extract all type names referenced by a Pydantic model"""
                if visited is None:
                    visited = set()

                if model_class.__name__ in visited:
                    return set()

                visited.add(model_class.__name__)
                referenced = set()

                try:
                    # Get type hints for all fields
                    from typing import get_type_hints, get_origin, get_args
                    hints = get_type_hints(model_class)

                    for field_name, field_type in hints.items():
                        # Extract type names from the annotation
                        type_names = _extract_type_names_from_annotation(field_type)
                        referenced.update(type_names)

                        # Recursively process referenced models
                        for type_name in type_names:
                            # Try to find the class in our modules
                            for module in [client_events_module, responses_module, events_module]:
                                if hasattr(module, type_name):
                                    ref_class = getattr(module, type_name)
                                    if inspect.isclass(ref_class) and issubclass(ref_class, BaseModel):
                                        referenced.update(extract_referenced_types(ref_class, visited))
                except Exception:
                    # If type hints fail, skip this class
                    pass

                return referenced

            def _extract_type_names_from_annotation(annotation):
                """Extract all type names from a type annotation (handles List, Optional, etc.)"""
                from typing import get_origin, get_args
                type_names = set()

                # Handle the base type
                if hasattr(annotation, '__name__'):
                    type_names.add(annotation.__name__)

                # Handle generic types (List[Foo], Optional[Bar], etc.)
                origin = get_origin(annotation)
                args = get_args(annotation)

                if args:
                    for arg in args:
                        if hasattr(arg, '__name__'):
                            type_names.add(arg.__name__)
                        # Recursively handle nested generics
                        type_names.update(_extract_type_names_from_annotation(arg))

                return type_names

            # Collect all referenced types from our kept classes
            initial_classes = set(classes_to_keep)
            for cls_name in list(classes_to_keep):
                # Find the actual class
                for module in [client_events_module, responses_module]:
                    if hasattr(module, cls_name):
                        cls = getattr(module, cls_name)
                        if inspect.isclass(cls) and issubclass(cls, BaseModel):
                            referenced = extract_referenced_types(cls)
                            classes_to_keep.update(referenced)

            # Filter out primitive types and typing constructs that aren't actual interfaces
            primitive_types = {'str', 'int', 'bool', 'float', 'dict', 'list', 'Any', 'Dict', 'List',
                              'Optional', 'Union', 'Literal', 'NoneType', 'ClassVar', 'Field'}
            classes_to_keep = {cls for cls in classes_to_keep if cls not in primitive_types}

            # Show what was automatically discovered
            auto_discovered = classes_to_keep - initial_classes
            if auto_discovered:
                qprint(f"Auto-discovered {len(auto_discovered)} referenced types: {sorted(auto_discovered)}")

            # Helper function to remove preceding JSDoc comment from filtered_lines
            def _remove_preceding_jsdoc(lines_list):
                """Remove JSDoc comment blocks from the end of lines_list if present.
                Keeps removing until we hit something that's not a JSDoc or blank line."""
                if not lines_list:
                    return

                while True:
                    # Remove any blank lines
                    while lines_list and not lines_list[-1].strip():
                        lines_list.pop()

                    if not lines_list:
                        break

                    # Check if last line is end of JSDoc comment
                    if lines_list[-1].strip() == '*/':
                        lines_list.pop()  # Remove */

                        # Remove comment content lines (lines starting with *)
                        while lines_list and lines_list[-1].strip().startswith('*'):
                            lines_list.pop()

                        # Remove opening /** if present
                        if lines_list and '/**' in lines_list[-1]:
                            lines_list.pop()
                        # Continue loop to check for more JSDoc blocks
                    else:
                        # Not a JSDoc comment, stop
                        break

            # Find all interface and type definitions in the combined content
            all_interfaces = re.findall(r'export (?:interface|type) (\w+)', combined_content)

            # Remove interfaces/types that are not in our keep list
            # Single-pass approach to avoid corruption from iterative reassignment
            interfaces_to_remove = set(name for name in all_interfaces
                                      if name not in classes_to_keep and name not in schema_interfaces)

            lines = combined_content.split('\n')
            filtered_lines = []
            skip_until_close = 0
            skip_type_body = False  # Track if we're skipping a type definition body
            current_interface = None
            removed_count = 0

            for i, line in enumerate(lines):

                # If we're currently inside a removed interface, skip lines
                if skip_until_close > 0:
                    skip_until_close += line.count('{')
                    skip_until_close -= line.count('}')
                    continue  # Skip this line

                # If we're skipping a type definition body (union types, etc.)
                if skip_type_body:
                    # Skip this line first
                    # Then check if we've reached the end of the type definition
                    if ';' in line:
                        skip_type_body = False
                    continue  # Skip this line regardless

                # Not inside removed definition, check if this line starts a new one
                should_skip = False
                for interface_name in interfaces_to_remove:
                    # Check for single-line empty interfaces FIRST (more specific)
                    if f'export interface {interface_name} {{}}' in line or f'export interface {interface_name}{{}}' in line:
                        removed_count += 1
                        should_skip = True
                        # Also remove preceding JSDoc comment if present
                        _remove_preceding_jsdoc(filtered_lines)
                        break
                    # Check for regular interface declarations
                    elif f'export interface {interface_name} {{' in line or f'export interface {interface_name}{{' in line:
                        current_interface = interface_name
                        # Count braces on THIS line (handles single-line interfaces like `interface Foo {}`)
                        brace_count = line.count('{') - line.count('}')
                        if brace_count > 0:
                            skip_until_close = brace_count
                        removed_count += 1
                        should_skip = True
                        # Also remove preceding JSDoc comment if present
                        _remove_preceding_jsdoc(filtered_lines)
                        break
                    # Check for type definitions (with or without spaces around =)
                    elif f'export type {interface_name} ' in line:
                        removed_count += 1
                        should_skip = True
                        # Check if this is a multi-line type definition
                        if '=' in line and ';' not in line:
                            skip_type_body = True  # Skip following lines until semicolon
                        # Also remove preceding JSDoc comment if present
                        _remove_preceding_jsdoc(filtered_lines)
                        break

                # Keep this line if it's not the start of a removed interface
                if not should_skip:
                    filtered_lines.append(line)

            combined_content = '\n'.join(filtered_lines)

            qprint(f"Filtered to {len(classes_to_keep)} interfaces for template target (removed {removed_count} definitions)")

        # Remove ALL interfaces that are defined in schema.py
        # pydantic2ts regenerates them even when imported, so we need to remove duplicates
        # Use line-by-line approach to properly handle JSDoc comments and nested braces
        imports_needed = []

        lines = combined_content.split('\n')
        filtered_lines = []
        skip_until_close = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # If we're inside a schema interface, skip lines
            if skip_until_close > 0:
                skip_until_close += line.count('{')
                skip_until_close -= line.count('}')
                i += 1
                continue

            # Check if this line starts a schema interface
            is_schema_interface = False
            for interface_name in schema_interfaces:
                if f'export interface {interface_name} {{' in line or f'export interface {interface_name}{{' in line:
                    # Remove blank lines first
                    while filtered_lines and not filtered_lines[-1].strip():
                        filtered_lines.pop()

                    # Remove preceding JSDoc comment
                    while filtered_lines and (filtered_lines[-1].strip() == '*/' or
                                             filtered_lines[-1].strip().startswith('*') or
                                             '/**' in filtered_lines[-1]):
                        filtered_lines.pop()

                    # Start skipping this interface
                    brace_count = line.count('{') - line.count('}')
                    if brace_count > 0:
                        skip_until_close = brace_count
                    is_schema_interface = True

                    # Track that this interface is used (for imports)
                    if interface_name not in imports_needed:
                        imports_needed.append(interface_name)
                    break

            if not is_schema_interface:
                filtered_lines.append(line)

            i += 1

        combined_content = '\n'.join(filtered_lines)
        
        # Generate import statement if needed
        if imports_needed:
            import_statement = f"import {{ {', '.join(imports_needed)} }} from './socket-schema.generated';\n\n"
        else:
            import_statement = ""
        
        # Write complete file with header, import, and mappings (only if content changed)
        full_content = header + import_statement + combined_content + event_mappings
        if write_if_changed(output_file, full_content, TS_TIMESTAMP_PATTERN):
            qprint(f"✓ Generated types at: {output_file}")
        else:
            qprint(f"✓ Types unchanged: {output_file}")
    except Exception as e:
        qprint(f"Error generating event types: {e}")
        raise
    
    return True

def _assert_no_incoherent_constraints(schema_name: str, schema: dict) -> None:
    """Reject schemas where a field has both `minLength >= 1` and a non-null
    default. Such a field looks optional (the default kicks in if omitted) but
    invalid when the user clears it to "" — an unreachable error state by
    intent that surfaces in the UI as a misleading "is required" alert. Force
    authors to pick one: drop the default to make it truly required, or drop
    `min_length` to let the default cover the empty case.
    """
    def walk(node: dict, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key, prop in (node.get('properties') or {}).items():
            if not isinstance(prop, dict):
                continue
            has_default = 'default' in prop and prop['default'] is not None
            min_len = prop.get('minLength')
            if has_default and isinstance(min_len, int) and min_len >= 1:
                raise AssertionError(
                    f"Schema '{schema_name}' field '{path}{key}' combines "
                    f"min_length={min_len} with default={prop['default']!r}. "
                    f"Pick one — see _assert_no_incoherent_constraints."
                )
            if 'properties' in prop:
                walk(prop, f"{path}{key}.")
        for variant in node.get('oneOf', []) or node.get('anyOf', []) or []:
            walk(variant, path)
    walk(schema, '')
    for def_name, def_schema in (schema.get('$defs') or {}).items():
        walk(def_schema, f"$defs.{def_name}.")


def _trigger_operations(schema: dict) -> list:
    """Operation names stamped `x-is-trigger`, walking the same
    config → $defs refs the frontend's isTriggerSource walks."""
    config = (schema.get('properties') or {}).get('config') or {}
    defs = schema.get('$defs') or {}
    refs = (
        config.get('oneOf')
        or config.get('anyOf')
        or ([{'$ref': config['$ref']}] if config.get('$ref') else [])
    )
    ops = []
    for ref in refs:
        key = (ref.get('$ref') or '').split('/')[-1]
        op = ((defs.get(key) or {}).get('properties') or {}).get('operation') or {}
        name = op.get('const') or (op.get('enum') or [None])[0]
        if name and op.get('x-is-trigger'):
            ops.append(name)
    return ops


def generate_node_schemas():
    """Generate JSON schemas from Pydantic config models and export to frontend"""
    import json
    from pathlib import Path
    from pydantic import TypeAdapter

    try:
        # Derive NODE_CLASSES dynamically from the authoritative NODE_REGISTRY
        from nodes.core.registry import NODE_REGISTRY

        # Schema filename = registry key with 'automation-' prefix stripped
        SKIP_NODES = {'test-dummy'}
        NODE_CLASSES = {}
        SCHEMA_TO_TYPE = {}
        for key, cls in NODE_REGISTRY.items():
            if key in SKIP_NODES:
                continue
            schema_name = key.removeprefix('automation-')
            NODE_CLASSES[schema_name] = cls
            SCHEMA_TO_TYPE[schema_name] = key

        # Define output path - schemas are imported directly in frontend code
        frontend_schemas = Path(__file__).parent.parent.parent / 'frontend' / 'app' / 'schemas' / 'nodes'

        # Create frontend schemas directory if it doesn't exist
        frontend_schemas.mkdir(parents=True, exist_ok=True)

        # Generate schema for each node type
        processed_count = 0
        updated_count = 0
        # Slim per-type facts (provider flag, trigger ops) for utils/nodeMeta.ts —
        # lets light surfaces (marketing previews, fork canvas, edge components)
        # answer type predicates without bundling the full ~9MB schema registry.
        node_meta = {}
        for schema_name, node_class in NODE_CLASSES.items():
            try:
                # Use get_config_schema() which includes credentials metadata
                schema = node_class.get_config_schema()
                # Re-stamp after the class is done editing. The base pass runs
                # inside the cached schema build, so it cannot see fields a node
                # adds in its own get_config_schema override (Zendesk, Discord,
                # PagerDuty and Google Translate all add pickers there). The pass
                # is idempotent, so running it twice cannot diverge.
                _mark_sole_option_autofill(schema)
                if not schema:
                    qprint(f"  ⚠ Skipping {schema_name} - no config model defined")
                    continue

                output_file = frontend_schemas / f"{schema_name}.json"

                # Add metadata
                schema['$schema'] = "https://json-schema.org/draft/2020-12/schema"
                schema['title'] = f"{schema_name.capitalize()} Node Configuration"
                if getattr(node_class, 'connectionless', False):
                    schema['x-connectionless'] = True

                # Mark nodes whose operations can be exposed as agent tools
                # (node_op) — the frontend uses this to render the top
                # provider handle and gate agent-bottom connections.
                from nodes.agent.node_op_tools import node_supports_op_tools
                if node_supports_op_tools(SCHEMA_TO_TYPE[schema_name]):
                    schema['x-agent-tool-provider'] = True

                _assert_no_incoherent_constraints(schema_name, schema)

                meta_entry = {}
                if schema.get('x-agent-tool-provider'):
                    meta_entry['agentToolProvider'] = True
                trigger_ops = _trigger_operations(schema)
                if trigger_ops:
                    meta_entry['triggerOperations'] = trigger_ops
                if meta_entry:
                    # Keyed by the FULL registry type (automation-slack), matching
                    # the frontend's NODE_SCHEMAS keys and canvas node.type values.
                    node_meta[SCHEMA_TO_TYPE[schema_name]] = meta_entry

                # Write to file with pretty formatting (only if content changed)
                json_content = json.dumps(schema, indent=2)
                if write_if_changed(output_file, json_content):
                    qprint(f"  ✓ Generated {schema_name}.json")
                    updated_count += 1
                else:
                    qprint(f"  ✓ Unchanged {schema_name}.json")
                processed_count += 1

            except Exception as e:
                qprint(f"  ✗ Failed to generate schema for {schema_name}: {e}")
                import traceback
                traceback.print_exc()

        meta_file = frontend_schemas.parent / 'nodeMeta.json'
        meta_content = json.dumps(
            {
                '$comment': 'Auto-generated by backend/scripts/generate_socket_types.py — do not edit. '
                            'Slim per-type facts consumed by frontend/app/utils/nodeMeta.ts.',
                'types': dict(sorted(node_meta.items())),
            },
            indent=2,
        )
        if write_if_changed(meta_file, meta_content):
            qprint("  ✓ Generated nodeMeta.json")

        if updated_count > 0:
            qprint(f"✓ Successfully processed {processed_count} schema files ({updated_count} updated)")
        else:
            qprint(f"✓ All {processed_count} schema files up to date")

        # Mirror the CLI model pin list into the frontend tree so app code
        # never imports across the repo root (vite fs.allow stays scoped to
        # frontend/).
        cli_models_src = Path(__file__).parent.parent / 'nodes' / 'agent' / 'config' / '_cli_models.json'
        cli_models_dest = frontend_schemas.parent / 'cli-models.json'
        cli_models_content = cli_models_src.read_text()
        if not cli_models_dest.exists() or cli_models_dest.read_text() != cli_models_content:
            cli_models_dest.write_text(cli_models_content)
            qprint("  ✓ Synced cli-models.json")

        return processed_count > 0

    except Exception as e:
        qprint(f"✗ Error generating node schemas: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Generate TypeScript types from Pydantic socket event models',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Generate all types (default)
  python generate_socket_types.py

  # Generate with custom output directory
  python generate_socket_types.py --output=/custom/path
'''
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Custom output directory (optional, defaults to frontend/app/types/)'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress verbose output (only show errors and final summary)'
    )

    args = parser.parse_args()

    # Set quiet mode flag (module-level variable)
    _quiet_mode = args.quiet

    qprint("Generating TypeScript types...")
    qprint("\n" + "="*60)
    qprint("Target 1/2: Socket event types (NoClick frontend)")
    qprint("="*60)
    success1 = generate_types(target='all', output_dir=args.output)

    qprint("\n" + "="*60)
    qprint("Target 2/2: Node JSON Schemas (from Pydantic models)")
    qprint("="*60)
    success2 = generate_node_schemas()

    if success1 and success2:
        qprint("\n" + "="*60)
        qprint("✓ Successfully generated types")
        qprint("  • Socket types: frontend/app/types/")
        qprint("  • Node schemas: frontend/app/schemas/nodes/")
        qprint("="*60)
        sys.exit(0)
    else:
        qprint("\n✗ Failed to generate types")
        sys.exit(1)
