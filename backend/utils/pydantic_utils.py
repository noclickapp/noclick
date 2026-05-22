import types
from typing import Type, Any, Dict
from pydantic import BaseModel, ConfigDict
from typing import Any, get_origin, get_args, Union, Any, Dict, List, Type
from pydantic import BaseModel, Field, create_model
from enum import Enum
from pydantic.json_schema import GetJsonSchemaHandler
from typing import get_origin, get_args, Union, Optional
from pydantic import BaseModel, create_model, Field

from pydantic import BaseModel
from typing import Any, Union, Dict

from pydantic import BaseModel, create_model
from typing import Any, Union, Dict, List, get_origin, get_args

from pydantic import BaseModel
from typing import Any, Union, Dict

from typing import Any, List, Type, get_args, get_origin, Union, Annotated


from typing import (
    Type, Dict, Any, get_origin, get_args, Union, Optional, List, Tuple
)
from pydantic import BaseModel, Field, create_model


def load_pydantic_model_from_string(code_string: str, model_name: str) -> Type[BaseModel]:
    """
    Load a Pydantic model from a string of Python code.
    
    Args:
        code_string: String containing Python code with a Pydantic model definition
        model_name: Name of the Pydantic model class to extract
        
    Returns:
        The Pydantic model class (a subclass of BaseModel)
        
    Raises:
        ValueError: If the model_name is not found or is not a Pydantic model
    """
    # Create a temporary module
    module = types.ModuleType("temp_module")
    
    # Execute the code in the module's namespace
    exec(code_string, module.__dict__)
    
    # Try to get the model class
    if not hasattr(module, model_name):
        raise ValueError(f"Model '{model_name}' not found in the provided code")
    
    model_class = getattr(module, model_name)
    
    # Verify it's a Pydantic model
    if not isinstance(model_class, type) or not issubclass(model_class, BaseModel):
        raise ValueError(f"'{model_name}' is not a Pydantic model")
    
    return model_class

def instantiate_pydantic_model(code_string: str, model_name: str, data: Dict[str, Any]) -> BaseModel:
    """
    Load a Pydantic model from a string and instantiate it with the provided data.
    
    Args:
        code_string: String containing Python code with a Pydantic model definition
        model_name: Name of the Pydantic model class to extract
        data: Dictionary of data to instantiate the model with
        
    Returns:
        An instance of the Pydantic model populated with the provided data
    """
    model_class = load_pydantic_model_from_string(code_string, model_name)
    return model_class(**data)

def unwrap_optional(typ: Any) -> tuple[Any, bool]:
    """
    If `typ` is Optional[X] or Union[X, None], return (X, True).
    Otherwise return (typ, False).
    """
    origin = get_origin(typ)
    if origin is Union:
        args = list(get_args(typ))
        if type(None) in args:
            args.remove(type(None))
            # If there's exactly one non-None type, we can treat this as Optional
            if len(args) == 1:
                return args[0], True
            # If multiple types remain, it's a real union (not just optional).
            # We'll consider that out of scope, or treat it as non-optional multi-union.
            return (typ, False)
    return (typ, False)

def gather_flattened_fields(
    model: Type[BaseModel],
    prefix: str = "",
    parent_is_list: bool = False,
    parent_is_optional: bool = False
) -> Dict[str, dict]:
    """
    Return a dict { flattened_field_name: metadata } for all leaf fields in `model`.
    
    - Submodels are recursively flattened, appending underscores to the prefix.
    - If the submodel field is Optional, all its child fields are also treated as optional.
    - If the field is List[SubModel], that submodel is flattened per-field, but each child annotation 
      becomes List[child_type]. If the list field is optional, then each child is still a list,
      but the entire list field is optional.
    - No bracket notation `[i]`. Instead we just use underscores: e.g. `margin_top`.
    """
    results: Dict[str, dict] = {}

    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        default_value = field_info.default
        description = getattr(field_info, "description", None)

        # Step 1: unwrap optional
        unwrapped_annotation, is_optional = unwrap_optional(annotation)
        # If the parent is optional, or the field is optional, children become optional
        combined_optional = parent_is_optional or is_optional

        # Build the new flattened field name
        flattened_name = prefix + field_name if prefix else field_name

        origin = get_origin(unwrapped_annotation)
        args = get_args(unwrapped_annotation)

        # CASE A: submodel => flatten recursively
        if isinstance(unwrapped_annotation, type) and issubclass(unwrapped_annotation, BaseModel):
            sub_prefix = flattened_name + "_"
            sub_results = gather_flattened_fields(
                unwrapped_annotation,
                prefix=sub_prefix,
                parent_is_list=False,
                parent_is_optional=combined_optional
            )
            results.update(sub_results)

        # CASE B: list
        elif origin is list and len(args) == 1:
            item_type = args[0]
            # unwrap optional at item-level in case it's List[Optional[X]]
            item_unwrapped, item_is_optional = unwrap_optional(item_type)
            # CASE B1: list of submodels
            if isinstance(item_unwrapped, type) and issubclass(item_unwrapped, BaseModel):
                # flatten each child field, but keep them as List[child_type]
                sub_prefix = flattened_name + "_"
                # if the *list itself* is optional or the items are optional,
                # we propagate that info so children remain correct (List[Optional[T]]) or Optional[List[T]]
                sub_results = gather_flattened_fields(
                    item_unwrapped,
                    prefix=sub_prefix,
                    parent_is_list=True,  # we are inside a list
                    parent_is_optional=combined_optional  # if the list itself is optional => subfields are optional
                )
                results.update(sub_results)
            else:
                # CASE B2: list of scalars => single flattened field
                # e.g. "numbers: List[int]" => "numbers"
                # if the parent is optional => annotation is Optional[List[int]]
                # if the items are optional => annotation is List[Optional[int]]
                from typing import Optional

                # If list itself was optional => it's Optional[List[...]]
                if combined_optional:
                    unwrapped_annotation = Optional[unwrapped_annotation]

                # If the items are optional => the list is List[Optional[...]]
                if item_is_optional:
                    # Rebuild the list type as List[Optional[item_unwrapped]]
                    from typing import Optional, List as PyList
                    item_annotation = Union[item_unwrapped, type(None)]
                    # item_annotation = Optional[item_unwrapped]  # same effect
                    unwrapped_annotation = PyList[item_annotation]  # type: ignore

                results[flattened_name] = {
                    "annotation": unwrapped_annotation,
                    "default": default_value,
                    "description": description,
                }
        else:
            # CASE C: scalar or other
            # if parent_is_list => that means we are inside the flattening of a submodel that was in a list
            # => we wrap in a List[...] if not already.
            if parent_is_list:
                from typing import List as PyList

                unwrapped_annotation = PyList[unwrapped_annotation]  # type: ignore

            # If combined_optional => wrap in Optional[...] if not already a union
            if combined_optional:
                from typing import Optional
                unwrapped_annotation = Union[unwrapped_annotation, type(None)]

            results[flattened_name] = {
                "annotation": unwrapped_annotation,
                "default": default_value,
                "description": description,
            }

    return results

def create_flat_model_for_model(
    model: Type[BaseModel],
    *,
    model_name: str = "FlattenedModel",
    arrays_only: bool = False,        # ← new switch
) -> Type[BaseModel]:
    """
    Return a single‑level Pydantic model with one field per flattened leaf
    of *model*.

    Parameters
    ----------
    model :
        Source model to flatten.
    model_name :
        Name of the generated model (default ``FlattenedModel``).
    arrays_only :
        • False – include every leaf (old behaviour).  
        • True  – include *only* leaves whose outermost annotation is a
          list / array.
    """
    def _is_array(tp):
        # Unwrap Optional[...] wrappers, then check if it's a list
        unwrapped, _ = unwrap_optional(tp)
        return get_origin(unwrapped) in (list, List)

    flat_fields = gather_flattened_fields(model)
    field_definitions = {}

    for name, meta in flat_fields.items():
        ann = meta["annotation"] or Any
        if arrays_only and not _is_array(ann):
            continue                      # skip non‑array leaves

        field_definitions[name] = (
            ann,
            Field(
                default=meta["default"],
                description=meta["description"],
            ),
        )

    return create_model(model_name, **field_definitions)

def create_access_path_model(
    model: Type[BaseModel], 
    enum_name: str = "ValidPaths", 
    model_name: str = "AccessPathModel"
) -> Type[BaseModel]:
    """
    Create a single-field model where `path` is an Enum referencing all valid
    flattened field names in `model`. 
    """
    flat_fields = gather_flattened_fields(model)
    sorted_flat_keys = sorted(flat_fields.keys())

    used_names = set()
    enum_members = {}
    meta_for_path = {}

    for field_name in sorted_flat_keys:
        # Convert any weird chars to underscores to ensure valid Python identifiers
        candidate = "".join(ch if ch.isalnum() else "_" for ch in field_name)
        base_candidate = candidate
        i = 1
        while candidate in used_names:
            i += 1
            candidate = f"{base_candidate}_{i}"
        used_names.add(candidate)

        enum_members[candidate] = field_name
        meta_for_path[field_name] = flat_fields[field_name]

    EnumClass = Enum(enum_name, enum_members)
    EnumClass._meta_for_path = meta_for_path

    # We'll use "anyOf" in the JSON schema for OpenAI compatibility
    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler: GetJsonSchemaHandler) -> dict:
        schema = handler(core_schema)
        schema.pop("enum", None)  # remove default enum

        any_of_entries = []
        for member in cls:
            path_value = member.value
            meta = cls._meta_for_path[path_value]
            entry = {
                "const": path_value,
                "title": path_value,
                "description": meta.get("description"),
            }
            entry = {k: v for k, v in entry.items() if v is not None}
            any_of_entries.append(entry)

        schema["anyOf"] = any_of_entries
        return schema

    EnumClass.__get_pydantic_json_schema__ = __get_pydantic_json_schema__

    # Build the single-field access model
    class _AccessPathModel(BaseModel):
        path: EnumClass = Field(
            ...,
            description="Choose a valid flattened path within the model."
        )

        model_config = ConfigDict(title=model_name)

    return _AccessPathModel

def pydantic_to_structured_api_schema(
    model_or_schema: Union[type[BaseModel], Dict[str, Any]],
    function_name: str | None = "Schema"
) -> Dict[str, Any]:
    """
    Generate an OpenAI-compatible "json_schema" from a Pydantic model or raw schema dict.
    This function:
      1) Gets a Pydantic JSON schema (if given a BaseModel).
      2) Removes all 'default' keys (OpenAI disallows them).
      3) Eliminates or transforms any 'allOf' usage (OpenAI disallows it).
      4) Recursively sets 'additionalProperties': false for all objects.
      5) Forces each object's 'required' to include all property names
         (OpenAI requires that every property is in 'required').
      6) Wraps it under {"type": "json_schema", "json_schema": {...}, ...} for function calling.
    """

    # ------------------ Helpers ------------------ #
    def _remove_defaults(obj: Any) -> None:
        """Recursively remove 'default' keys."""
        if isinstance(obj, dict):
            obj.pop("default", None)
            for val in obj.values():
                _remove_defaults(val)
        elif isinstance(obj, list):
            for item in obj:
                _remove_defaults(item)

    def _strip_or_transform_all_of(schema: dict) -> None:
        """
        Recursively remove or transform 'allOf'.
        - If allOf=[{"$ref": "..."}], flatten to just {"$ref": "..."}.
        - Otherwise, forcibly convert allOf -> anyOf. (This changes meaning from intersection to union.)
        """
        if not isinstance(schema, dict):
            return

        # Recurse into $defs first (submodels):
        if "$defs" in schema:
            for def_schema in schema["$defs"].values():
                _strip_or_transform_all_of(def_schema)

        # If it's an object or array, we also need to check 'properties', 'items', etc.
        if schema.get("type") == "object":
            for prop in schema.get("properties", {}).values():
                _strip_or_transform_all_of(prop)
            for composition_key in ("anyOf", "oneOf", "allOf"):
                if composition_key in schema:
                    for subschema in schema[composition_key]:
                        _strip_or_transform_all_of(subschema)

        elif schema.get("type") == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                _strip_or_transform_all_of(items)
            elif isinstance(items, list):
                for subschema in items:
                    _strip_or_transform_all_of(subschema)

        # Now handle the local 'allOf'
        if "allOf" in schema:
            all_of_list = schema["allOf"]
            if len(all_of_list) == 1:
                # If it's a single item referencing something, 
                # we can flatten or transform it
                single = all_of_list[0]
                # If it's exactly {"$ref": "..."}, replace this entire schema with that
                if isinstance(single, dict) and list(single.keys()) == ["$ref"]:
                    # We remove 'allOf' and just keep $ref
                    ref_val = single["$ref"]
                    # first copy existing keys we might want to preserve (like 'description')
                    old_keys = {k: v for k, v in schema.items() if k not in ["allOf"]}
                    # now empty the schema and replace with that single ref
                    schema.clear()
                    schema.update(old_keys)
                    # if old_keys had its own type/description/properties, we might need to carefully merge
                    # but for now let's assume we want a simple $ref
                    schema["$ref"] = ref_val
                else:
                    # else we do naive approach: replace 'allOf' with 'anyOf'
                    schema["anyOf"] = [single]
                    del schema["allOf"]
            else:
                # If there's more than 1 item in allOf, just replace with anyOf
                # This is not logically the same, but we avoid the error
                schema["anyOf"] = all_of_list
                del schema["allOf"]

    def _enforce_no_additional_properties(schema: dict) -> None:
        """Set additionalProperties=false in every object; descend into $defs, anyOf/oneOf, items, etc."""
        if not isinstance(schema, dict):
            return
        if "$defs" in schema:
            for def_schema in schema["$defs"].values():
                _enforce_no_additional_properties(def_schema)

        schema_type = schema.get("type")
        if schema_type == "object":
            schema.setdefault("additionalProperties", False)
            for prop_schema in schema.get("properties", {}).values():
                _enforce_no_additional_properties(prop_schema)
            for composition_key in ("anyOf", "oneOf"):
                if composition_key in schema:
                    for subschema in schema[composition_key]:
                        _enforce_no_additional_properties(subschema)
        elif schema_type == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                _enforce_no_additional_properties(items)
            elif isinstance(items, list):
                for subschema in items:
                    _enforce_no_additional_properties(subschema)

    def _force_all_properties_required(schema: dict) -> None:
        """
        For each object, set required = list(properties.keys()).
        This ensures OpenAI sees no missing required fields.
        """
        if not isinstance(schema, dict):
            return
        if "$defs" in schema:
            for def_schema in schema["$defs"].values():
                _force_all_properties_required(def_schema)

        if schema.get("type") == "object":
            props = schema.get("properties", {})
            schema["required"] = sorted(props.keys())
            for prop_schema in props.values():
                _force_all_properties_required(prop_schema)
            for composition_key in ("anyOf", "oneOf"):
                if composition_key in schema:
                    for subschema in schema[composition_key]:
                        _force_all_properties_required(subschema)
        elif schema.get("type") == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                _force_all_properties_required(items)
            elif isinstance(items, list):
                for subschema in items:
                    _force_all_properties_required(subschema)
    
    def _transform_ref_with_local_keywords(schema: dict) -> None:
        """
        Recursively find any object that has `$ref` plus local keywords 
        (like 'description', 'title', 'type'), and turn it into:

        {
        "anyOf": [
            { "$ref": "..." },
            ...existing union items if any...
        ],
        // local keywords remain here at the top
        }

        This prevents mixing $ref with local constraints in the same object,
        which OpenAI disallows, but it preserves local docstrings or other info.
        """

        if not isinstance(schema, dict):
            return

        # Recurse into $defs
        if "$defs" in schema:
            for def_schema in schema["$defs"].values():
                _transform_ref_with_local_keywords(def_schema)

        # If object has properties, transform them
        if schema.get("type") == "object":
            for prop_schema in schema.get("properties", {}).values():
                _transform_ref_with_local_keywords(prop_schema)
            for comp_key in ("anyOf", "oneOf"):
                if comp_key in schema:
                    for subschema in schema[comp_key]:
                        _transform_ref_with_local_keywords(subschema)

        elif schema.get("type") == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                _transform_ref_with_local_keywords(items)
            elif isinstance(items, list):
                for subschema in items:
                    _transform_ref_with_local_keywords(subschema)

        # Now handle local `$ref` + keywords at this level
        if "$ref" in schema:
            # Gather local fields excluding "$ref"
            local_fields = {
                k: v for k, v in schema.items()
                if k != "$ref"
            }
            ref_value = schema["$ref"]

            # If we already have "anyOf" or "oneOf" here, 
            # we'll inject the $ref into that array. 
            # Otherwise we create a new "anyOf".
            existing_any_of = []
            if "anyOf" in local_fields:
                # Grab existing anyOf array
                existing_any_of = local_fields["anyOf"]
                # Remove it from local_fields so we can re-add it after
                del local_fields["anyOf"]
            elif "oneOf" in local_fields:
                existing_any_of = local_fields["oneOf"]
                del local_fields["oneOf"]

            # Insert the $ref as the FIRST sub-schema in anyOf
            # Because we want "match #/MyRef" or ...
            new_any_of = [{"$ref": ref_value}] + existing_any_of

            # Replace schema in-place:
            # 1) Clear all existing keys
            schema.clear()
            # 2) Put "anyOf": [ { "$ref": ... }, ...]
            schema["anyOf"] = new_any_of
            # 3) Add back local fields (like "description", "title", etc.)
            schema.update(local_fields)

    # ------------------ Main logic ------------------ #
    # 1) Generate or get the schema
    if isinstance(model_or_schema, type) and issubclass(model_or_schema, BaseModel):
        schema_dict = model_or_schema.model_json_schema()
        function_name = function_name or model_or_schema.__name__
    else:
        schema_dict = model_or_schema
        function_name = function_name or "Schema"

    # 2) Remove 'default'
    _remove_defaults(schema_dict)

    # 3) Transform or strip out 'allOf'
    _strip_or_transform_all_of(schema_dict)

    # 4) Set additionalProperties=false
    _enforce_no_additional_properties(schema_dict)

    # 5) Force every property into 'required'
    _force_all_properties_required(schema_dict)
    
    # 6) Force every property into 'required'
    _transform_ref_with_local_keywords(schema_dict)

    # 7) Wrap up
    return {
        "type": "json_schema",
        "json_schema": {
            "name": function_name,
            "schema": schema_dict,
            "strict": True
        }
    }

def make_all_fields_optional(
    model: type[BaseModel],
    new_model_name: str | None = None
) -> type[BaseModel]:
    """
    Create a new Pydantic model subclass with all fields of `model` made optional.

    - Preserves the original model's validators, class methods, and config by inheriting from `model`.
    - If a field is already optional, it remains that way.
    - Otherwise it is wrapped in Union[field_type, None].
    """

    if new_model_name is None:
        new_model_name = f"AllOptional{model.__name__}"

    field_definitions = {}
    for field_name, field_info in model.model_fields.items():
        # Original annotation
        original_annotation = field_info.annotation

        # Check if it's already Optional[...] or a union with None
        origin = get_origin(original_annotation)
        args = get_args(original_annotation)
        is_already_optional = (
            origin is Union 
            and type(None) in args
        )

        # If not optional, wrap it
        if not is_already_optional:
            new_annotation = Union[original_annotation, None]
        else:
            new_annotation = original_annotation

        field_definitions[field_name] = (
            new_annotation,
            Field(
                default=field_info.default,
                description=getattr(field_info, "description", None)
            ),
        )

    # Create a new model that inherits from the original one:
    NewModel = create_model(
        new_model_name,
        __base__=model,
        **field_definitions,
    )
    return NewModel


def get_primitive_type(tp: Any) -> Any:
    """
    Strip Optional/Union/List […] wrappers and return the
    *inner* primitive type, not a hard‑coded default.
    """
    origin = get_origin(tp)

    # Optional[T]  → peel off None
    if origin is Union:
        non_none = [t for t in get_args(tp) if t is not type(None)]
        return get_primitive_type(non_none[0]) if len(non_none) == 1 else tp

    # List[T]      → look at the element type
    if origin in (list, List):
        args = get_args(tp)
        return get_primitive_type(args[0]) if args else list   # fall back to plain list

    return tp

def split_model_by_type_groups(
    model: Type[BaseModel],
    type_groups: list[tuple[Type, ...]],
    *,
    flatten_types: bool = False,
) -> Dict[Tuple[Type, ...], Type[BaseModel]]:
    """
    Splits the fields of `model` into multiple Pydantic models,
    each containing only the fields whose annotation
    matches one of the types in the given type tuple.

    :param model: The original Pydantic model class.
    :param type_groups: A list of type tuples. For each tuple,
                        we'll build a new model containing
                        only the matching fields.
    :param flatten_types: If True, call `get_primitive_type(...)`
                    before membership checking. This helps
                    catch complex types using their 'core' type.
    :return: A dictionary keyed by each type tuple with a corresponding
             new Pydantic model that has only fields matching those types.
    """

    results = {}

    for type_tuple in type_groups:
        field_definitions = {}
        
        # Create a name based on the types in the tuple
        type_names = []
        for t in type_tuple:
            # Get the type name, handling special cases
            if hasattr(t, "__name__"):
                type_name = t.__name__
            elif hasattr(t, "_name"):  # For some generic types
                type_name = t._name
            else:
                # Fallback for types without clear names
                type_name = str(t).replace("typing.", "").replace("<class '", "").replace("'>", "")
            
            # Clean the name to be a valid Python identifier
            type_name = ''.join(c for c in type_name if c.isalnum())
            type_names.append(type_name)
        
        # Join the type names and ensure it's not too long
        type_suffix = 'With'.join(type_names)
        if len(type_suffix) > 50:  # Reasonable limit for name length
            type_suffix = type_suffix[:47] + "Etc"
            
        subset_model_name = f"{model.__name__}{type_suffix}"

        for field_name, field_info in model.model_fields.items():
            # If flatten=True, reduce annotation to its primitive (core) type
            annotation = (
                get_primitive_type(field_info.annotation) 
                if flatten_types 
                else field_info.annotation
            )

            # Check if the (possibly flattened) annotation is in our tuple
            if annotation in type_tuple:
                field_definitions[field_name] = (
                    field_info.annotation,  # store original annotation
                    Field(
                        default=field_info.default,
                        description=getattr(field_info, "description", None),
                    ),
                )

        # Create a new model with only matching fields
        SubsetModel = create_model(
            subset_model_name,
            __base__=BaseModel,  # or __base__=model if you want to inherit config/validators
            **field_definitions
        )

        # Map the type tuple -> newly created model
        results[type_tuple] = SubsetModel

    return results

def override_all_field_types(
    model: type[BaseModel],
    override_type: type,
    new_model_name: str | None = "SchemaMapperModel"
) -> type[BaseModel]:
    """
    Create a new Pydantic model subclass with the same fields as `model`,
    but every field's annotation is replaced by `override_type`.
    
    - Preserves validators, methods, config by inheriting from `model`.
    - Field names, defaults, descriptions remain the same, only the type is changed.
    """

    if new_model_name is None:
        new_model_name = f"OverrideTypes{model.__name__}"

    field_definitions = {}
    for field_name, field_info in model.model_fields.items():
        field_definitions[field_name] = (
            override_type,
            Field(
                default=field_info.default,
                description=getattr(field_info, "description", None)
            ),
        )

    NewModel = create_model(
        new_model_name,
        __base__=model,
        **field_definitions,
    )
    return NewModel

def override_field_types_by_type(
    model: Type[BaseModel],
    overrides: Dict[Type, Type],
    new_model_name: str | None = None
) -> Type[BaseModel]:
    """
    Create a new Pydantic model subclass with the same fields as `model`,
    but override each field's annotation according to a dictionary of
    {original_type: override_type}. If a match isn't found, peel off
    Optional/Union/List until we can match or finally fallback.
    """
    if new_model_name is None:
        new_model_name = f"OverrideTypes{model.__name__}"

    field_definitions = {}
    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation

        # 1) Direct override?
        override_type = overrides.get(annotation)

        # 2) If no direct match, strip Optional[...] or look at list origin, etc.
        if not override_type:
            fallback_ann = get_primitive_type(annotation)
            override_type = overrides.get(fallback_ann, fallback_ann)

        field_definitions[field_name] = (
            override_type,
            Field(
                default=field_info.default,
                description=getattr(field_info, "description", None)
            ),
        )

    NewModel = create_model(
        new_model_name,
        __base__=model,
        **field_definitions,
    )

    return NewModel

def flatten_tuple_dict(tuple_dict):
    flattened = {}
    for tuple_key, value in tuple_dict.items():
        for key in tuple_key:
            flattened[key] = value
    return flattened


def update_unflattened_data(
    *,
    model: Type[BaseModel],
    data: dict,
    flat_name: str,
    value: Any,
    delimiter: str = "_",
    extend: bool = False,
) -> None:
    """
    Mutate *data* so that, after flattening *model*, *flat_name* would equal
    *value*.  Works with optional fields, nested models and lists of models.
    """
    def _unwrap(tp):
        """
        Strip away typing.Annotated and typing.Optional layers until a concrete
        origin / class remains. Returns the *outer* origin as well.
        """
        while True:
            origin = get_origin(tp)

            # Annotated[T, …]  → keep unwrapping
            if origin is Annotated:
                tp = get_args(tp)[0]
                continue

            # Union[…] that is exactly Optional[T]  → unwrap
            if origin is Union:
                args = [a for a in get_args(tp) if a is not type(None)]
                if len(args) == 1:
                    tp = args[0]
                    continue

            return tp, origin

    def _is_basemodel(tp) -> bool:
        return isinstance(tp, type) and issubclass(tp, BaseModel)
    
    parts = flat_name.split(delimiter)

    def recurse(cls: Type[BaseModel], d: dict, segments: list[str], val: Any):
        seg = segments[0]
        field = cls.model_fields[seg]

        # ─── leaf ────────────────────────────────────────────────────────
        if len(segments) == 1:
            d[seg] = val
            return

        # ─── decide where to go next ─────────────────────────────────────
        tp, origin = _unwrap(field.annotation)

        # ----- list[...] -------------------------------------------------
        if origin in (list, List):
            inner_tp, _ = _unwrap(get_args(tp)[0])
            if not _is_basemodel(inner_tp):
                raise ValueError(
                    f"Field '{seg}' is a list but does not contain a Pydantic "
                    "model, cannot continue flattening."
                )

            if not isinstance(val, list):
                raise TypeError(
                    f"To set '{flat_name}' you must supply a list, not "
                    f"{type(val).__name__}."
                )

            lst = d.setdefault(seg, [])
            if len(lst) < len(val):
                if not extend:
                    raise ValueError(
                        f"List '{seg}' is shorter than the value supplied "
                        f"({len(lst)} < {len(val)}).  Use extend=True."
                    )
                lst.extend({} for _ in range(len(val) - len(lst)))

            for i, v in enumerate(val):
                item_dict = lst[i] if isinstance(lst[i], dict) else {}
                lst[i] = item_dict
                recurse(inner_tp, item_dict, segments[1:], v)
            return

        # ----- nested BaseModel -----------------------------------------
        if _is_basemodel(tp):
            sub_dict = d.setdefault(seg, {})
            recurse(tp, sub_dict, segments[1:], val)
            return

        # ----- dead end --------------------------------------------------
        raise ValueError(
            f"Cannot descend into field '{seg}' (type {field.annotation}) while "
            f"resolving flattened name '{flat_name}'."
        )

    recurse(model, data, parts, value)