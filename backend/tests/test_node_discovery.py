"""Node discovery is opt-in, deterministic, lazy, and refuses duplicate types.

Fixtures use a real importable package to catch import-time failures and caching.
"""
import sys
import uuid

import pytest

from nodes.core import discovery
from nodes.core.discovery import Declaration, declare_nodes, merge_node_entries
from nodes.core.registry import DISCOVERED_NODE_ENTRIES, NODE_REGISTRY, _NODE_REGISTRY_ENTRIES, _NodeRegistry

pytestmark = pytest.mark.every_integration


def discover_nodes(root, name):
    """Declare, then load every declaration, as a lookup of each type would."""
    return {
        node_type: entry.load() if isinstance(entry, Declaration) else entry
        for node_type, entry in declare_nodes(root, name).items()
    }


@pytest.fixture
def package(tmp_path, monkeypatch):
    name = f'discovery_{uuid.uuid4().hex}'
    root = tmp_path / name
    root.mkdir()
    (root / '__init__.py').write_text('')
    monkeypatch.syspath_prepend(str(tmp_path))
    yield root, name
    for key in list(sys.modules):
        if key == name or key.startswith(name + '.'):
            sys.modules.pop(key)


def write_node(root, file, integration_type):
    (root / file).write_text(
        'from nodes.core.base import WorkflowNode\n'
        f'class Example(WorkflowNode):\n    integration_type = {integration_type!r}\n'
        '    async def execute(self, inputs): return {}\n'
    )


def test_only_declaring_node_modules_import_once(package):
    root, name = package
    (root / 'legacy_node.py').write_text('raise RuntimeError("must not import")')
    (root / 'other.py').write_text('raise RuntimeError("must not import")')
    write_node(root, 'example_node.py', 'automation-example')
    first = discover_nodes(root, name)
    second = discover_nodes(root, name)
    assert list(first) == ['automation-example']
    assert first['automation-example'] is second['automation-example']


def test_declaring_imports_nothing_until_the_type_is_looked_up(package):
    root, name = package
    write_node(root, 'example_node.py', 'automation-example')
    write_node(root, 'other_node.py', 'automation-other')
    registry = _NodeRegistry(declare_nodes(root, name))
    assert list(registry) == ['automation-example', 'automation-other']
    assert 'automation-other' in registry
    assert name + '.example_node' not in sys.modules
    assert name + '.other_node' not in sys.modules

    cls = registry['automation-example']
    assert cls.__module__ == name + '.example_node'
    assert registry.get('automation-example') is cls
    assert registry.type_of(cls) == 'automation-example'
    assert name + '.other_node' not in sys.modules


def test_type_of_finds_a_class_imported_before_its_lookup(package):
    root, name = package
    write_node(root, 'example_node.py', 'automation-example')
    registry = _NodeRegistry(declare_nodes(root, name))
    cls = __import__(name + '.example_node', fromlist=['Example']).Example
    assert registry.type_of(cls) == 'automation-example'
    assert registry['automation-example'] is cls


def test_module_constant_declarations_are_read_without_importing(package):
    root, name = package
    (root / 'constant_node.py').write_text(
        'raise RuntimeError("must not import while declaring")\n'
        'NODE_TYPE = "automation-constant"\n'
        'class Example:\n    integration_type = NODE_TYPE\n'
    )
    assert declare_nodes(root, name) == {
        'automation-constant': Declaration('automation-constant', name + '.constant_node', 'Example'),
    }


def test_import_errors_are_not_hidden(package):
    root, name = package
    (root / 'broken_node.py').write_text('class Broken:\n    integration_type = "automation-broken"\nraise RuntimeError("broken import")')
    registry = _NodeRegistry(declare_nodes(root, name))
    with pytest.raises(RuntimeError, match='broken import'):
        registry['automation-broken']


def test_a_declaration_that_is_not_a_node_fails_its_lookup(package):
    root, name = package
    (root / 'model_node.py').write_text(
        'from pydantic import BaseModel\n'
        'class Config(BaseModel):\n    integration_type: str = "automation-model"\n'
    )
    registry = _NodeRegistry(declare_nodes(root, name))
    with pytest.raises(ValueError, match='Invalid integration class'):
        registry['automation-model']


def test_duplicate_discovered_types_fail(package):
    root, name = package
    write_node(root, 'a_node.py', 'automation-example')
    write_node(root, 'b_node.py', 'automation-example')
    with pytest.raises(ValueError, match='Duplicate node type'):
        discover_nodes(root, name)


def test_explicit_collision_fails_even_for_same_class():
    entries = {'automation-example': object()}
    with pytest.raises(ValueError, match='Duplicate node types'):
        merge_node_entries(entries, entries)


def test_imported_or_inherited_classes_do_not_register_twice(package):
    root, name = package
    write_node(root, 'a_node.py', 'automation-example')
    (root / 'b_node.py').write_text(
        f'from {name}.a_node import Example\n'
        'class Child(Example): pass\n'
        'class Own(Example): integration_type = "automation-own"\n'
    )
    assert set(discover_nodes(root, name)) == {'automation-example', 'automation-own'}


def test_registry_retains_explicit_types_and_resolves_aliases():
    assert set(NODE_REGISTRY) == set(_NODE_REGISTRY_ENTRIES) | set(DISCOVERED_NODE_ENTRIES)
    assert not _NODE_REGISTRY_ENTRIES.keys() & DISCOVERED_NODE_ENTRIES.keys()
    assert NODE_REGISTRY['interface-image'] is NODE_REGISTRY['interface-file']
    assert 'interface-image' not in list(NODE_REGISTRY)


@pytest.mark.parametrize('body', [
    'class Bad(WorkflowNode): integration_type: str',
    'class Bad(WorkflowNode): integration_type = 123',
    'class Bad(WorkflowNode): integration_type = "not a type"',
])
def test_invalid_declarations_fail_instead_of_disappearing(package, body):
    root, name = package
    (root / 'bad_node.py').write_text('from nodes.core.base import WorkflowNode\n' + body + '\n')
    with pytest.raises(ValueError, match='Invalid integration'):
        discover_nodes(root, name)


def test_config_fields_are_not_node_registration(package):
    root, name = package
    (root / 'config_node.py').write_text(
        'from pydantic import BaseModel\n'
        'class Config(BaseModel): integration_type: str\n'
    )
    assert discover_nodes(root, name) == {}


def test_files_without_marker_are_never_parsed_or_imported(package, monkeypatch):
    root, name = package
    path = root / 'legacy_node.py'
    path.write_text('this is deliberately invalid Python!')
    def unexpected(*args, **kwargs):
        pytest.fail('Unmarked node must not be parsed or imported')
    monkeypatch.setattr(discovery.ast, 'parse', unexpected)
    monkeypatch.setattr(discovery.importlib, 'import_module', unexpected)
    assert discover_nodes(root, name) == {}
    assert name + '.legacy_node' not in sys.modules


def test_every_declared_integration_loads_under_its_type():
    """Lookups import an integration on first use, so its import errors surface here, not at startup."""
    for node_type, entry in DISCOVERED_NODE_ENTRIES.items():
        cls = NODE_REGISTRY[node_type]
        assert vars(cls)['integration_type'] == node_type
        if isinstance(entry, Declaration):
            assert (cls.__module__, cls.__name__) == (entry.module, entry.class_name)


def test_every_hand_registered_node_loads_from_its_module():
    for node_type, (module, name) in _NODE_REGISTRY_ENTRIES.items():
        cls = NODE_REGISTRY[node_type]
        assert (cls.__module__, cls.__name__) == (module, name)


def test_a_hand_registered_entry_imports_at_its_first_lookup(package):
    root, name = package
    (root / 'step_node.py').write_text(
        'from nodes.core.base import WorkflowNode\n'
        'class Step(WorkflowNode):\n    async def execute(self, inputs): return {}\n'
    )
    registry = _NodeRegistry({'step': Declaration('step', name + '.step_node', 'Step', self_declared=False)})
    assert name + '.step_node' not in sys.modules
    assert registry['step'].__name__ == 'Step'
    with pytest.raises(ValueError, match='Invalid integration class'):
        _NodeRegistry({'x': Declaration('x', name + '.step_node', 'Missing', self_declared=False)})['x']
