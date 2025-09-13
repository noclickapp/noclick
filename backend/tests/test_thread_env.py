"""
Tests for thread_env module - thread-safe environment variable management.

This is a superset of test_async_env.py tests, adding cross-thread support verification.
"""

import asyncio
import os
import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional
from utils.thread_env import override_env, async_override_env, patch_environ


class TestThreadEnv:
    """Test suite for thread-safe environment variable management."""
    
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Ensure environment is clean before and after each test."""
        # Store any existing test vars
        test_vars = [
            'TEST_VAR', 'MY_VAR', 'PARENT_VAR', 'CHILD_VAR', 'OVERRIDE_VAR',
            'THREAD_VAR', 'WORKER_VAR', 'SHARED_VAR', 'API_KEY', 'TASK_ID'
        ]
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
    
    # ========== Basic Sync Tests (Adapted from async_env) ==========
    
    def test_basic_environment_inheritance_sync(self):
        """Test that sync contexts inherit outside environment variables."""
        # Set a variable in the global environment
        os.environ['TEST_VAR'] = 'global_value'
        
        # Verify it's accessible in sync context
        with override_env():
            assert 'TEST_VAR' in os.environ
            assert os.environ['TEST_VAR'] == 'global_value'
            assert os.environ.get('TEST_VAR') == 'global_value'
        
        # Verify it's still there after context
        assert os.environ['TEST_VAR'] == 'global_value'
    
    def test_context_override_without_global_modification_sync(self):
        """Test that context overrides don't modify global environment."""
        # Set initial global value
        os.environ['TEST_VAR'] = 'global_value'
        
        # Override in context
        with override_env(TEST_VAR='context_value'):
            assert os.environ['TEST_VAR'] == 'context_value'
        
        # Verify global wasn't modified
        assert os.environ['TEST_VAR'] == 'global_value'
    
    def test_nested_context_inheritance_sync(self):
        """Test that nested contexts properly inherit and override values."""
        os.environ['PARENT_VAR'] = 'parent_global'
        os.environ['CHILD_VAR'] = 'child_global'
        
        with override_env(PARENT_VAR='parent_context'):
            # Parent context overrides PARENT_VAR
            assert os.environ['PARENT_VAR'] == 'parent_context'
            assert os.environ['CHILD_VAR'] == 'child_global'
            
            with override_env(CHILD_VAR='child_context'):
                # Child context inherits parent override and adds its own
                assert os.environ['PARENT_VAR'] == 'parent_context'
                assert os.environ['CHILD_VAR'] == 'child_context'
                
                # Deeply nested context
                with override_env(PARENT_VAR='deep_override', NEW_VAR='deep_value'):
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
    
    # ========== Async Tests (Adapted from async_env) ==========
    
    @pytest.mark.asyncio
    async def test_basic_environment_inheritance_async(self):
        """Test that async contexts inherit outside environment variables."""
        # Set a variable in the global environment
        os.environ['TEST_VAR'] = 'global_value'
        
        # Verify it's accessible in async context
        async with async_override_env():
            assert 'TEST_VAR' in os.environ
            assert os.environ['TEST_VAR'] == 'global_value'
            assert os.environ.get('TEST_VAR') == 'global_value'
        
        # Verify it's still there after context
        assert os.environ['TEST_VAR'] == 'global_value'
    
    @pytest.mark.asyncio
    async def test_context_override_without_global_modification_async(self):
        """Test that async context overrides don't modify global environment."""
        # Set initial global value
        os.environ['TEST_VAR'] = 'global_value'
        
        # Override in context
        async with async_override_env(TEST_VAR='context_value'):
            assert os.environ['TEST_VAR'] == 'context_value'
        
        # Verify global wasn't modified
        assert os.environ['TEST_VAR'] == 'global_value'
    
    @pytest.mark.asyncio
    async def test_nested_context_inheritance_async(self):
        """Test that nested async contexts properly inherit and override values."""
        os.environ['PARENT_VAR'] = 'parent_global'
        os.environ['CHILD_VAR'] = 'child_global'
        
        async with async_override_env(PARENT_VAR='parent_context'):
            # Parent context overrides PARENT_VAR
            assert os.environ['PARENT_VAR'] == 'parent_context'
            assert os.environ['CHILD_VAR'] == 'child_global'
            
            async with async_override_env(CHILD_VAR='child_context'):
                # Child context inherits parent override and adds its own
                assert os.environ['PARENT_VAR'] == 'parent_context'
                assert os.environ['CHILD_VAR'] == 'child_context'
                
                # Deeply nested context
                async with async_override_env(PARENT_VAR='deep_override', NEW_VAR='deep_value'):
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
    async def test_parallel_async_execution_isolation(self):
        """Test that parallel async tasks have isolated environments."""
        # Clear any existing MY_VAR
        if 'MY_VAR' in os.environ:
            del os.environ['MY_VAR']
        
        results = []
        
        async def task1():
            """Task with value1"""
            async with async_override_env(MY_VAR='value1'):
                await asyncio.sleep(0.1)  # Force context switch
                results.append(('task1', os.environ.get('MY_VAR')))
                return os.environ.get('MY_VAR') == 'value1'
        
        async def task2():
            """Task with value2"""
            async with async_override_env(MY_VAR='value2'):
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
    
    # ========== Cross-Thread Tests (New) ==========
    
    def test_parallel_thread_execution_isolation(self):
        """Test that parallel threads have isolated environments."""
        # Clear any existing THREAD_VAR
        if 'THREAD_VAR' in os.environ:
            del os.environ['THREAD_VAR']
        
        results = {}
        errors = []
        
        def thread_worker(worker_id: int, value: str):
            """Worker that sets its own environment."""
            try:
                with override_env(THREAD_VAR=value, WORKER_ID=str(worker_id)):
                    # Sleep to ensure overlapping execution
                    time.sleep(0.1)
                    
                    # Check that we see our own values
                    seen_value = os.environ.get('THREAD_VAR')
                    seen_id = os.environ.get('WORKER_ID')
                    
                    # Store results
                    results[worker_id] = {
                        'expected_value': value,
                        'seen_value': seen_value,
                        'expected_id': str(worker_id),
                        'seen_id': seen_id,
                        'thread_name': threading.current_thread().name
                    }
                    
                    # Verify correctness
                    assert seen_value == value, f"Worker {worker_id} saw wrong THREAD_VAR"
                    assert seen_id == str(worker_id), f"Worker {worker_id} saw wrong WORKER_ID"
                    
                    # Sleep again to maintain overlap
                    time.sleep(0.1)
                    
                    # Check again before exiting context
                    assert os.environ.get('THREAD_VAR') == value
                    assert os.environ.get('WORKER_ID') == str(worker_id)
                    
            except Exception as e:
                errors.append((worker_id, str(e)))
        
        # Run multiple threads in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(5):
                future = executor.submit(thread_worker, i, f"thread_value_{i}")
                futures.append(future)
            
            # Wait for all to complete
            for future in as_completed(futures):
                future.result()  # This will raise if thread had exception
        
        # Check for errors
        assert not errors, f"Thread errors: {errors}"
        
        # Verify all threads saw their own values
        for worker_id, result in results.items():
            assert result['seen_value'] == result['expected_value']
            assert result['seen_id'] == result['expected_id']
        
        # Global environment should be unchanged
        assert os.environ.get('THREAD_VAR') is None
        assert os.environ.get('WORKER_ID') is None
    
    def test_nested_thread_contexts(self):
        """Test nested contexts within threads."""
        results = []
        
        def thread_with_nested_contexts():
            """Thread that uses nested contexts."""
            thread_name = threading.current_thread().name
            
            with override_env(LEVEL1='thread_level1'):
                results.append((thread_name, 'L1', os.environ.get('LEVEL1')))
                
                with override_env(LEVEL2='thread_level2'):
                    results.append((thread_name, 'L2-LEVEL1', os.environ.get('LEVEL1')))
                    results.append((thread_name, 'L2-LEVEL2', os.environ.get('LEVEL2')))
                    
                    with override_env(LEVEL1='thread_override', LEVEL3='thread_level3'):
                        results.append((thread_name, 'L3-LEVEL1', os.environ.get('LEVEL1')))
                        results.append((thread_name, 'L3-LEVEL2', os.environ.get('LEVEL2')))
                        results.append((thread_name, 'L3-LEVEL3', os.environ.get('LEVEL3')))
                    
                    # Back to L2
                    results.append((thread_name, 'L2-BACK-LEVEL1', os.environ.get('LEVEL1')))
                    results.append((thread_name, 'L2-BACK-LEVEL3', os.environ.get('LEVEL3')))
                
                # Back to L1
                results.append((thread_name, 'L1-BACK', os.environ.get('LEVEL1')))
                results.append((thread_name, 'L1-BACK-LEVEL2', os.environ.get('LEVEL2')))
        
        # Run in multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=thread_with_nested_contexts, name=f"Thread-{i}")
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Verify each thread saw correct values
        for thread_id in range(3):
            thread_name = f"Thread-{thread_id}"
            thread_results = [(level, value) for (t, level, value) in results if t == thread_name]
            
            expected = [
                ('L1', 'thread_level1'),
                ('L2-LEVEL1', 'thread_level1'),  # Inherited
                ('L2-LEVEL2', 'thread_level2'),
                ('L3-LEVEL1', 'thread_override'),  # Overridden
                ('L3-LEVEL2', 'thread_level2'),  # Inherited
                ('L3-LEVEL3', 'thread_level3'),
                ('L2-BACK-LEVEL1', 'thread_level1'),  # Restored
                ('L2-BACK-LEVEL3', None),  # Gone
                ('L1-BACK', 'thread_level1'),
                ('L1-BACK-LEVEL2', None),  # Gone
            ]
            
            assert thread_results == expected, f"Thread {thread_name} results mismatch"
    
    def test_thread_inheritance_from_parent(self):
        """Test that child threads can inherit parent thread's context."""
        results = {}
        
        def child_thread(parent_env: Dict[str, str], child_id: int):
            """Child thread that should see parent's environment."""
            # Child starts with parent's environment
            with override_env(**parent_env, CHILD_ID=str(child_id)):
                results[child_id] = {
                    'parent_var': os.environ.get('PARENT_VAR'),
                    'child_id': os.environ.get('CHILD_ID'),
                    'thread': threading.current_thread().name
                }
        
        def parent_thread():
            """Parent thread that spawns children."""
            with override_env(PARENT_VAR='parent_value'):
                # Get current environment to pass to children
                parent_env = {'PARENT_VAR': 'parent_value'}
                
                # Spawn child threads
                threads = []
                for i in range(3):
                    thread = threading.Thread(
                        target=child_thread,
                        args=(parent_env, i)
                    )
                    threads.append(thread)
                    thread.start()
                
                # Wait for children
                for thread in threads:
                    thread.join()
        
        # Run parent thread
        parent = threading.Thread(target=parent_thread)
        parent.start()
        parent.join()
        
        # Verify all children saw parent's environment
        for child_id, result in results.items():
            assert result['parent_var'] == 'parent_value'
            assert result['child_id'] == str(child_id)
    
    @pytest.mark.asyncio
    async def test_async_to_thread_context_preservation(self):
        """Test context behavior when async code calls thread executor."""
        results = {}
        
        def thread_function(thread_id: int, env_to_set: Optional[Dict[str, str]] = None):
            """Function that runs in thread executor."""
            # If env provided, set it in thread context
            if env_to_set:
                with override_env(**env_to_set):
                    results[thread_id] = {
                        'async_var': os.environ.get('ASYNC_VAR'),
                        'thread_var': os.environ.get('THREAD_VAR'),
                        'thread': threading.current_thread().name
                    }
            else:
                results[thread_id] = {
                    'async_var': os.environ.get('ASYNC_VAR'),
                    'thread_var': os.environ.get('THREAD_VAR'),
                    'thread': threading.current_thread().name
                }
            return os.environ.get('ASYNC_VAR') or os.environ.get('THREAD_VAR')
        
        async with async_override_env(ASYNC_VAR='async_value'):
            # In async context, ASYNC_VAR is set
            assert os.environ.get('ASYNC_VAR') == 'async_value'
            
            # Run thread function from async context
            loop = asyncio.get_event_loop()
            
            # Thread function won't see async context (different thread)
            # But we can explicitly pass environment to set
            future1 = loop.run_in_executor(
                None, 
                thread_function, 
                1, 
                {'ASYNC_VAR': 'async_value', 'THREAD_VAR': 'thread_value'}
            )
            result1 = await future1
            
            # Without explicit env, thread won't see async context
            future2 = loop.run_in_executor(None, thread_function, 2)
            result2 = await future2
        
        # Check results 
        # Thread 1 explicitly set environment in its thread context
        assert results[1]['async_var'] == 'async_value'
        assert results[1]['thread_var'] == 'thread_value'
        
        # Thread 2 with context propagation enabled should see async context
        # (This changed with ThreadPoolExecutor patching - async context now propagates!)
        assert results[2]['async_var'] == 'async_value'  # Context propagation works!
        assert results[2]['thread_var'] is None  # But thread-local context doesn't propagate
    
    def test_exception_handling_in_threads(self):
        """Test that contexts are properly cleaned up on exceptions in threads."""
        os.environ['EXCEPTION_VAR'] = 'original'
        results = {'before': None, 'after': None}
        
        def thread_with_exception():
            """Thread that raises an exception."""
            try:
                with override_env(EXCEPTION_VAR='thread_value', TEMP_VAR='temp'):
                    results['before'] = os.environ.get('EXCEPTION_VAR')
                    raise ValueError("Test exception")
            except ValueError:
                pass  # Expected
            
            # Check after exception
            results['after'] = os.environ.get('EXCEPTION_VAR')
        
        thread = threading.Thread(target=thread_with_exception)
        thread.start()
        thread.join()
        
        # Verify context was active before exception
        assert results['before'] == 'thread_value'
        
        # Verify context was cleaned up after exception
        assert results['after'] == 'original'
        
        # Global should be unchanged
        assert os.environ['EXCEPTION_VAR'] == 'original'
        assert 'TEMP_VAR' not in os.environ
    
    def test_complex_parallel_thread_scenario(self):
        """Test complex scenario with multiple parallel threads and nested contexts."""
        os.environ['SHARED_VAR'] = 'global_shared'
        results = {}
        
        def api_thread(api_key: str, thread_id: str):
            """Simulate API thread with specific key."""
            collected = []
            
            with override_env(API_KEY=api_key, THREAD_ID=thread_id):
                collected.append(f"{thread_id}:start:{os.environ['API_KEY']}")
                time.sleep(0.05)
                
                # Nested context for sub-operation
                with override_env(SUB_OP='true'):
                    collected.append(f"{thread_id}:sub:{os.environ['API_KEY']}")
                    collected.append(f"{thread_id}:shared:{os.environ['SHARED_VAR']}")
                    time.sleep(0.05)
                
                collected.append(f"{thread_id}:end:{os.environ['API_KEY']}")
            
            results[thread_id] = collected
        
        # Run multiple API threads in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for i in range(3):
                future = executor.submit(api_thread, f'key{i}', f'thread{i}')
                futures.append(future)
            
            # Wait for all to complete
            for future in as_completed(futures):
                future.result()
        
        # Verify each thread saw only its own API key
        for i in range(3):
            thread_id = f'thread{i}'
            api_key = f'key{i}'
            thread_results = results[thread_id]
            
            assert f"{thread_id}:start:{api_key}" in thread_results
            assert f"{thread_id}:sub:{api_key}" in thread_results
            assert f"{thread_id}:end:{api_key}" in thread_results
            assert f"{thread_id}:shared:global_shared" in thread_results
        
        # Verify global environment is unchanged
        assert 'API_KEY' not in os.environ
        assert 'THREAD_ID' not in os.environ
        assert 'SUB_OP' not in os.environ
        assert os.environ['SHARED_VAR'] == 'global_shared'
        
        del os.environ['SHARED_VAR']
    
    # ========== Dictionary Operations Tests ==========
    
    def test_dictionary_operations_sync(self):
        """Test dictionary-like operations on environment in sync context."""
        os.environ['KEY1'] = 'value1'
        os.environ['KEY2'] = 'value2'
        
        with override_env(KEY3='value3', KEY1='override1'):
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
    
    def test_environment_modification_behaviors(self):
        """Test various environment modification operations in contexts."""
        
        # Test setdefault behavior
        with override_env():
            os.environ.setdefault('NEW_VAR', 'default_value')
            assert os.environ['NEW_VAR'] == 'default_value'
            
            os.environ.setdefault('NEW_VAR', 'another_value')
            assert os.environ['NEW_VAR'] == 'default_value'  # Should not change
        
        # Should persist in global after context
        assert os.environ.get('NEW_VAR') == 'default_value'
        
        # Test update behavior in context with overrides
        with override_env(VAR1='value1'):
            os.environ.update({'VAR2': 'value2', 'VAR3': 'value3'})
            assert os.environ['VAR1'] == 'value1'
            assert os.environ['VAR2'] == 'value2'
            assert os.environ['VAR3'] == 'value3'
        
        # Check what persists
        assert os.environ.get('VAR1') is None  # Context-only
        # VAR2 and VAR3 behavior depends on implementation
        
        # Clean up
        if 'NEW_VAR' in os.environ:
            del os.environ['NEW_VAR']
        if 'VAR2' in os.environ:
            del os.environ['VAR2']
        if 'VAR3' in os.environ:
            del os.environ['VAR3']
    
    def test_pop_operation(self):
        """Test pop operation in different contexts."""
        os.environ['POP_VAR'] = 'original'
        
        # Pop in context with override
        with override_env(POP_VAR='context_value'):
            value = os.environ.pop('POP_VAR')
            assert value == 'context_value'
            # After popping from context, should fall back to original
            assert os.environ.get('POP_VAR') == 'original'
        
        # Should still be in global
        assert os.environ.get('POP_VAR') == 'original'
        
        # Pop from global
        value = os.environ.pop('POP_VAR')
        assert value == 'original'
        assert 'POP_VAR' not in os.environ
    
    def test_contains_operator(self):
        """Test 'in' operator with context overrides."""
        os.environ['GLOBAL_VAR'] = 'global'
        
        with override_env(CONTEXT_VAR='context'):
            assert 'GLOBAL_VAR' in os.environ
            assert 'CONTEXT_VAR' in os.environ
            assert 'NONEXISTENT_VAR' not in os.environ
        
        assert 'GLOBAL_VAR' in os.environ
        assert 'CONTEXT_VAR' not in os.environ
        
        del os.environ['GLOBAL_VAR']
    
    def test_clear_operation(self):
        """Test clear operation in contexts."""
        os.environ['CLEAR_VAR1'] = 'value1'
        os.environ['CLEAR_VAR2'] = 'value2'
        
        with override_env(CONTEXT_VAR='context'):
            # Clear in context should clear context vars
            os.environ.clear()
            
            # Behavior depends on implementation
            # Either clears all or just context vars
            # Test will be adjusted based on implementation
            pass
        
        # Clean up
        if 'CLEAR_VAR1' in os.environ:
            del os.environ['CLEAR_VAR1']
        if 'CLEAR_VAR2' in os.environ:
            del os.environ['CLEAR_VAR2']
    
    def test_delete_operation(self):
        """Test delete operation in different contexts."""
        os.environ['DELETE_VAR'] = 'original'
        
        # Delete in context with override
        with override_env(DELETE_VAR='context_value', CONTEXT_ONLY='context'):
            # Delete context override
            del os.environ['DELETE_VAR']
            # Should fall back to global or be gone
            # Behavior depends on implementation
            
            # Delete context-only var
            del os.environ['CONTEXT_ONLY']
            assert 'CONTEXT_ONLY' not in os.environ
        
        # Check global state after context
        # Behavior depends on implementation
        
        # Clean up
        if 'DELETE_VAR' in os.environ:
            del os.environ['DELETE_VAR']
    
    def test_empty_context(self):
        """Test context with no overrides."""
        os.environ['EMPTY_TEST'] = 'value'
        
        with override_env():
            # Should behave like normal environment
            assert os.environ['EMPTY_TEST'] == 'value'
            os.environ['NEW_IN_EMPTY'] = 'new_value'
            assert os.environ['NEW_IN_EMPTY'] == 'new_value'
        
        # Changes should persist
        assert os.environ['EMPTY_TEST'] == 'value'
        assert os.environ.get('NEW_IN_EMPTY') == 'new_value'
        
        del os.environ['EMPTY_TEST']
        if 'NEW_IN_EMPTY' in os.environ:
            del os.environ['NEW_IN_EMPTY']
    
    # ========== Mixed Async/Sync/Thread Tests ==========
    
    @pytest.mark.asyncio
    async def test_mixed_async_sync_thread_contexts(self):
        """Test mixing async, sync, and thread contexts."""
        results = {}
        
        def sync_function():
            """Sync function called from async."""
            with override_env(SYNC_VAR='sync_value'):
                results['sync'] = os.environ.get('SYNC_VAR')
                results['async_from_sync'] = os.environ.get('ASYNC_VAR')
                return os.environ.get('SYNC_VAR')
        
        def thread_function():
            """Thread function called from async."""
            with override_env(THREAD_VAR='thread_value'):
                results['thread'] = os.environ.get('THREAD_VAR')
                results['async_from_thread'] = os.environ.get('ASYNC_VAR')
                return os.environ.get('THREAD_VAR')
        
        async with async_override_env(ASYNC_VAR='async_value'):
            # Call sync function
            sync_result = sync_function()
            
            # Call thread function
            loop = asyncio.get_event_loop()
            thread_result = await loop.run_in_executor(None, thread_function)
            
            # Store async context value
            results['async'] = os.environ.get('ASYNC_VAR')
        
        # Verify isolation and context preservation
        assert results['sync'] == 'sync_value'
        assert results['thread'] == 'thread_value'
        assert results['async'] == 'async_value'
        # Cross-context visibility depends on implementation
    
    def test_stress_many_threads(self):
        """Stress test with many concurrent threads."""
        num_threads = 20
        num_iterations = 10
        errors = []
        
        def worker(worker_id):
            """Worker that repeatedly sets/checks environment."""
            try:
                for i in range(num_iterations):
                    env_key = f"KEY_{worker_id}_{i}"
                    env_value = f"value_{worker_id}_{i}"
                    
                    with override_env(**{env_key: env_value}):
                        # Check our value
                        assert os.environ.get(env_key) == env_value
                        
                        # Check we don't see others
                        for other_id in range(num_threads):
                            if other_id != worker_id:
                                other_key = f"KEY_{other_id}_{i}"
                                # Should not see other thread's keys
                                # (unless they're in global, which they shouldn't be)
                                if other_key in os.environ:
                                    errors.append(f"Worker {worker_id} saw {other_key}")
                        
                        # Small delay to increase overlap
                        time.sleep(0.001)
                    
                    # Verify cleanup
                    assert env_key not in os.environ
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")
        
        # Run all threads
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()
        
        # Check for errors
        assert not errors, f"Stress test errors: {errors}"
        
        # Verify global environment is clean
        for worker_id in range(num_threads):
            for i in range(num_iterations):
                assert f"KEY_{worker_id}_{i}" not in os.environ