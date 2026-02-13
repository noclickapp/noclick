"""
Tests for async_env module - async-safe environment variable management.
"""

import asyncio
import os
import pytest
from typing import List
from utils.async_env import async_env, patch_environ


class TestAsyncEnv:
    """Test suite for async environment variable management."""
    
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Ensure environment is clean before and after each test."""
        # Save the current os.environ so we can restore it after the test
        saved_environ = os.environ

        # Store any existing test vars
        test_vars = ['TEST_VAR', 'MY_VAR', 'PARENT_VAR', 'CHILD_VAR', 'OVERRIDE_VAR']
        original_values = {var: os.environ.get(var) for var in test_vars}

        # Clean environment before test
        for var in test_vars:
            if var in os.environ:
                del os.environ[var]

        # Ensure patching is active
        patch_environ()

        yield

        # Restore original values after test
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value
            elif var in os.environ:
                del os.environ[var]

        # Restore the original os.environ to avoid polluting other test files
        os.environ = saved_environ
    
    @pytest.mark.asyncio
    async def test_basic_environment_inheritance(self):
        """Test that async contexts inherit outside environment variables."""
        # Set a variable in the global environment
        os.environ['TEST_VAR'] = 'global_value'
        
        # Verify it's accessible in async context
        async with async_env():
            assert 'TEST_VAR' in os.environ
            assert os.environ['TEST_VAR'] == 'global_value'
            assert os.environ.get('TEST_VAR') == 'global_value'
        
        # Verify it's still there after context
        assert os.environ['TEST_VAR'] == 'global_value'
    
    @pytest.mark.asyncio
    async def test_context_override_without_global_modification(self):
        """Test that context overrides don't modify global environment."""
        # Set initial global value
        os.environ['TEST_VAR'] = 'global_value'
        
        # Override in context
        async with async_env(TEST_VAR='context_value'):
            assert os.environ['TEST_VAR'] == 'context_value'
        
        # Verify global wasn't modified
        assert os.environ['TEST_VAR'] == 'global_value'
    
    @pytest.mark.asyncio
    async def test_nested_context_inheritance(self):
        """Test that nested contexts properly inherit and override values."""
        os.environ['PARENT_VAR'] = 'parent_global'
        os.environ['CHILD_VAR'] = 'child_global'
        
        async with async_env(PARENT_VAR='parent_context'):
            # Parent context overrides PARENT_VAR
            assert os.environ['PARENT_VAR'] == 'parent_context'
            assert os.environ['CHILD_VAR'] == 'child_global'
            
            async with async_env(CHILD_VAR='child_context'):
                # Child context inherits parent override and adds its own
                assert os.environ['PARENT_VAR'] == 'parent_context'
                assert os.environ['CHILD_VAR'] == 'child_context'
                
                # Deeply nested context
                async with async_env(PARENT_VAR='deep_override', NEW_VAR='deep_value'):
                    assert os.environ['PARENT_VAR'] == 'deep_override'
                    assert os.environ['CHILD_VAR'] == 'child_context'
                    assert os.environ['NEW_VAR'] == 'deep_value'
                
                # Back to child context
                assert os.environ['PARENT_VAR'] == 'parent_context'
                assert os.environ['CHILD_VAR'] == 'child_context'
                assert os.environ.get('NEW_VAR') is None
            
            # Back to parent context
            assert os.environ['PARENT_VAR'] == 'parent_context'
            assert os.environ['CHILD_VAR'] == 'child_global'
        
        # Back to global
        assert os.environ['PARENT_VAR'] == 'parent_global'
        assert os.environ['CHILD_VAR'] == 'child_global'
    
    @pytest.mark.asyncio
    async def test_parallel_execution_isolation(self):
        """Test that parallel async tasks have isolated environments."""
        # Clear any existing MY_VAR
        if 'MY_VAR' in os.environ:
            del os.environ['MY_VAR']
        
        results = []
        
        async def task1():
            """Task with value1"""
            async with async_env(MY_VAR='value1'):
                await asyncio.sleep(0.1)  # Force context switch
                results.append(('task1', os.environ.get('MY_VAR')))
                return os.environ.get('MY_VAR') == 'value1'
        
        async def task2():
            """Task with value2"""
            async with async_env(MY_VAR='value2'):
                await asyncio.sleep(0.05)  # Different timing
                results.append(('task2', os.environ.get('MY_VAR')))
                return os.environ.get('MY_VAR') == 'value2'
        
        async def task3():
            """Task with no override"""
            await asyncio.sleep(0.075)  # Run in middle
            value = os.environ.get('MY_VAR')
            results.append(('task3', value))
            return value is None
        
        # Run all tasks in parallel
        task_results = await asyncio.gather(task1(), task2(), task3())
        
        # All tasks should see their own environment
        assert all(task_results), f"Some tasks failed. Results: {results}"
        
        # Verify each task saw the correct value
        task_values = dict(results)
        assert task_values['task1'] == 'value1'
        assert task_values['task2'] == 'value2'
        assert task_values['task3'] is None
        
        # Global environment should be unchanged
        assert os.environ.get('MY_VAR') is None
    
    @pytest.mark.asyncio
    async def test_environment_modification_behaviors(self):
        """Test various environment modification operations in contexts."""
        
        # Test setdefault behavior - always sets in original if not exists
        async with async_env():
            os.environ.setdefault('NEW_VAR', 'default_value')
            assert os.environ['NEW_VAR'] == 'default_value'
            
            os.environ.setdefault('NEW_VAR', 'another_value')
            assert os.environ['NEW_VAR'] == 'default_value'  # Should not change
        
        # Should persist in global after context
        assert os.environ.get('NEW_VAR') == 'default_value'
        
        # Test update behavior in context with overrides
        async with async_env(VAR1='value1'):
            os.environ.update({'VAR2': 'value2', 'VAR3': 'value3'})
            assert os.environ['VAR1'] == 'value1'
            assert os.environ['VAR2'] == 'value2'
            assert os.environ['VAR3'] == 'value3'
        
        # All were context-only, none should persist
        assert os.environ.get('VAR1') is None
        assert os.environ.get('VAR2') is None
        assert os.environ.get('VAR3') is None
        
        # Test update outside context - affects global
        os.environ.update({'VAR2': 'global2', 'VAR3': 'global3'})
        assert os.environ['VAR2'] == 'global2'
        assert os.environ['VAR3'] == 'global3'
        
        # Verify they persist
        assert os.environ.get('VAR2') == 'global2'
        assert os.environ.get('VAR3') == 'global3'
        
        # Clean up
        del os.environ['NEW_VAR']
        del os.environ['VAR2']
        del os.environ['VAR3']
    
    @pytest.mark.asyncio
    async def test_pop_operation(self):
        """Test pop operation in different contexts."""
        os.environ['POP_VAR'] = 'original'
        
        # Pop in context with override
        async with async_env(POP_VAR='context_value'):
            value = os.environ.pop('POP_VAR')
            assert value == 'context_value'
            # After popping from context, should fall back to original
            assert os.environ['POP_VAR'] == 'original'
        
        # Should still be in global
        assert os.environ['POP_VAR'] == 'original'
        
        # Pop from global
        value = os.environ.pop('POP_VAR')
        assert value == 'original'
        assert 'POP_VAR' not in os.environ
    
    @pytest.mark.asyncio
    async def test_dictionary_operations(self):
        """Test dictionary-like operations on environment."""
        os.environ['KEY1'] = 'value1'
        os.environ['KEY2'] = 'value2'
        
        async with async_env(KEY3='value3', KEY1='override1'):
            # Test keys()
            keys = list(os.environ.keys())
            assert 'KEY1' in keys
            assert 'KEY2' in keys
            assert 'KEY3' in keys
            
            # Test values()
            values = list(os.environ.values())
            assert 'override1' in values
            assert 'value2' in values
            assert 'value3' in values
            
            # Test items()
            items = dict(os.environ.items())
            assert items['KEY1'] == 'override1'
            assert items['KEY2'] == 'value2'
            assert items['KEY3'] == 'value3'
            
            # Test copy()
            env_copy = os.environ.copy()
            assert env_copy['KEY1'] == 'override1'
            assert env_copy['KEY3'] == 'value3'
        
        # Outside context
        assert os.environ['KEY1'] == 'value1'
        assert 'KEY3' not in os.environ
        
        # Clean up
        del os.environ['KEY1']
        del os.environ['KEY2']
    
    @pytest.mark.asyncio
    async def test_contains_operator(self):
        """Test 'in' operator with context overrides."""
        os.environ['GLOBAL_VAR'] = 'global'
        
        async with async_env(CONTEXT_VAR='context'):
            assert 'GLOBAL_VAR' in os.environ
            assert 'CONTEXT_VAR' in os.environ
            assert 'NONEXISTENT_VAR' not in os.environ
        
        assert 'GLOBAL_VAR' in os.environ
        assert 'CONTEXT_VAR' not in os.environ
        
        del os.environ['GLOBAL_VAR']
    
    @pytest.mark.asyncio
    async def test_clear_operation(self):
        """Test clear operation in contexts."""
        os.environ['CLEAR_VAR1'] = 'value1'
        os.environ['CLEAR_VAR2'] = 'value2'
        
        async with async_env(CONTEXT_VAR='context'):
            # Clear in context should clear context vars
            os.environ.clear()
            
            # Global vars should still be accessible
            assert os.environ.get('CLEAR_VAR1') == 'value1'
            assert os.environ.get('CLEAR_VAR2') == 'value2'
            # Context var should be cleared
            assert os.environ.get('CONTEXT_VAR') is None
        
        # Global vars should still exist
        assert os.environ['CLEAR_VAR1'] == 'value1'
        assert os.environ['CLEAR_VAR2'] == 'value2'
        
        # Clean up
        del os.environ['CLEAR_VAR1']
        del os.environ['CLEAR_VAR2']
    
    @pytest.mark.asyncio
    async def test_complex_parallel_scenario(self):
        """Test complex scenario with multiple parallel tasks and nested contexts."""
        os.environ['SHARED_VAR'] = 'global_shared'
        
        async def api_task(api_key: str, task_id: str) -> List[str]:
            """Simulate API task with specific key"""
            collected = []
            
            async with async_env(API_KEY=api_key, TASK_ID=task_id):
                collected.append(f"{task_id}:start:{os.environ['API_KEY']}")
                await asyncio.sleep(0.05)
                
                # Nested context for sub-operation
                async with async_env(SUB_OP='true'):
                    collected.append(f"{task_id}:sub:{os.environ['API_KEY']}")
                    collected.append(f"{task_id}:shared:{os.environ['SHARED_VAR']}")
                    await asyncio.sleep(0.05)
                
                collected.append(f"{task_id}:end:{os.environ['API_KEY']}")
            
            return collected
        
        # Run multiple API tasks in parallel
        results = await asyncio.gather(
            api_task('key1', 'task1'),
            api_task('key2', 'task2'),
            api_task('key3', 'task3'),
        )
        
        # Verify each task saw only its own API key
        for i, task_results in enumerate(results, 1):
            task_id = f'task{i}'
            api_key = f'key{i}'
            
            assert f"{task_id}:start:{api_key}" in task_results
            assert f"{task_id}:sub:{api_key}" in task_results
            assert f"{task_id}:end:{api_key}" in task_results
            assert f"{task_id}:shared:global_shared" in task_results
        
        # Verify global environment is unchanged
        assert 'API_KEY' not in os.environ
        assert 'TASK_ID' not in os.environ
        assert 'SUB_OP' not in os.environ
        assert os.environ['SHARED_VAR'] == 'global_shared'
        
        del os.environ['SHARED_VAR']
    
    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Test that contexts are properly cleaned up on exceptions."""
        os.environ['EXCEPTION_VAR'] = 'original'
        
        with pytest.raises(ValueError):
            async with async_env(EXCEPTION_VAR='context_value', TEMP_VAR='temp'):
                assert os.environ['EXCEPTION_VAR'] == 'context_value'
                assert os.environ['TEMP_VAR'] == 'temp'
                raise ValueError("Test exception")
        
        # Environment should be restored after exception
        assert os.environ['EXCEPTION_VAR'] == 'original'
        assert 'TEMP_VAR' not in os.environ
        
        del os.environ['EXCEPTION_VAR']
    
    @pytest.mark.asyncio
    async def test_empty_context(self):
        """Test context with no overrides."""
        os.environ['EMPTY_TEST'] = 'value'
        
        async with async_env():
            # Should behave like normal environment
            assert os.environ['EMPTY_TEST'] == 'value'
            os.environ['NEW_IN_EMPTY'] = 'new_value'
            assert os.environ['NEW_IN_EMPTY'] == 'new_value'
        
        # Changes should persist
        assert os.environ['EMPTY_TEST'] == 'value'
        assert os.environ['NEW_IN_EMPTY'] == 'new_value'
        
        del os.environ['EMPTY_TEST']
        del os.environ['NEW_IN_EMPTY']
    
    @pytest.mark.asyncio 
    async def test_delete_operation(self):
        """Test delete operation in different contexts."""
        os.environ['DELETE_VAR'] = 'original'
        
        # Delete in context with override
        async with async_env(DELETE_VAR='context_value', CONTEXT_ONLY='context'):
            # Delete context override
            del os.environ['DELETE_VAR']
            # Should fall back to global
            assert os.environ['DELETE_VAR'] == 'original'
            
            # Delete context-only var
            del os.environ['CONTEXT_ONLY']
            assert 'CONTEXT_ONLY' not in os.environ
        
        # Global should be unchanged
        assert os.environ['DELETE_VAR'] == 'original'
        assert 'CONTEXT_ONLY' not in os.environ
        
        # Delete from global
        del os.environ['DELETE_VAR']
        assert 'DELETE_VAR' not in os.environ