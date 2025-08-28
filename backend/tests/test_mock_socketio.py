"""
Comprehensive test suite for the simplified MockSocketIO implementation.

Tests cover basic communication, pattern matching, edge cases,
race conditions, and async/await patterns.
"""

import pytest
import asyncio
from typing import List
from tests.utils.mock_socketio import MockSocketIO


class TestMockSocketIO:
    """Tests for the simplified MockSocketIO implementation."""
    
    @pytest.mark.asyncio
    async def test_create_socketio_connection_basic(self):
        """Test basic linked socket pair communication."""
        # Create a linked pair
        client, server = MockSocketIO.create_socketio_connection()
        
        # Register a handler on the server
        @server.on('hello')
        async def handle_hello(sid, data):
            await server.emit('hello_response', {'msg': f"Hello {data['name']}!"}, to=sid)
        
        # Client sends event to server
        await client.emit('hello', {'name': 'Alice'}, to='test-sid')
        
        # Check that server received and responded
        server_events = server.get_emitted_events('hello_response')
        assert len(server_events) == 1
        assert server_events[0][1]['msg'] == "Hello Alice!"
    
    @pytest.mark.asyncio
    async def test_bidirectional_communication(self):
        """Test that both sockets can send and receive."""
        client, server = MockSocketIO.create_socketio_connection()
        
        # Register handlers on both sides
        @client.on('from_server')
        async def client_handler(sid, data):
            await client.emit('client_ack', {'received': data['message']})
        
        @server.on('from_client')
        async def server_handler(sid, data):
            await server.emit('server_ack', {'received': data['message']})
        
        # Send from client to server
        await client.emit('from_client', {'message': 'Hello Server'})
        
        # Send from server to client
        await server.emit('from_server', {'message': 'Hello Client'})
        
        # Verify events were recorded
        assert len(client.get_emitted_events('client_ack')) == 1
        assert len(server.get_emitted_events('server_ack')) == 1
    
    @pytest.mark.asyncio
    async def test_wildcard_handler(self):
        """Test wildcard '*' handler catches all events."""
        client, server = MockSocketIO.create_socketio_connection()
        
        received_events = []
        
        @server.on('*')
        async def catch_all(event, sid, data):
            received_events.append((event, data))
        
        # Send various events
        await client.emit('event1', {'value': 1})
        await client.emit('event2', {'value': 2})
        await client.emit('special_event', {'value': 'special'})
        
        # All events should be caught
        assert len(received_events) == 3
        assert received_events[0] == ('event1', {'value': 1})
        assert received_events[1] == ('event2', {'value': 2})
        assert received_events[2] == ('special_event', {'value': 'special'})
    
    @pytest.mark.asyncio
    async def test_regex_pattern_handler(self):
        """Test regex pattern matching for event handlers."""
        client, server = MockSocketIO.create_socketio_connection()
        
        user_events = []
        admin_events = []
        
        @server.on('regex:user_.*')
        async def handle_user_events(sid, data):
            user_events.append(data)
        
        @server.on('regex:admin_.*')
        async def handle_admin_events(sid, data):
            admin_events.append(data)
        
        # Send various events
        await client.emit('user_login', {'user': 'alice'})
        await client.emit('user_logout', {'user': 'alice'})
        await client.emit('admin_action', {'action': 'delete'})
        await client.emit('other_event', {'data': 'ignored'})
        
        # Check pattern matching worked
        assert len(user_events) == 2
        assert len(admin_events) == 1
        assert user_events[0] == {'user': 'alice'}
        assert admin_events[0] == {'action': 'delete'}
    
    @pytest.mark.asyncio
    async def test_exact_and_wildcard_handlers(self):
        """Test that both exact and wildcard handlers can coexist."""
        client, server = MockSocketIO.create_socketio_connection()
        
        exact_called = []
        wildcard_called = []
        
        @server.on('specific_event')
        async def exact_handler(sid, data):
            exact_called.append(data)
        
        @server.on('*')
        async def wildcard_handler(event, sid, data):
            wildcard_called.append((event, data))
        
        # Send the specific event
        await client.emit('specific_event', {'value': 'test'})
        
        # Both handlers should be called
        assert len(exact_called) == 1
        assert len(wildcard_called) == 1
        assert exact_called[0] == {'value': 'test'}
        assert wildcard_called[0] == ('specific_event', {'value': 'test'})
    
    @pytest.mark.asyncio
    async def test_session_management(self):
        """Test basic session management."""
        client, server = MockSocketIO.create_socketio_connection()
        
        # Create sessions
        client_sid = client.create_session('client-123', user='alice', role='user')
        server_sid = server.create_session('server-456', server_id='main')
        
        # Retrieve sessions
        client_session = await client.get_session('client-123')
        server_session = await server.get_session('server-456')
        
        assert client_session == {'user': 'alice', 'role': 'user'}
        assert server_session == {'server_id': 'main'}
    
    @pytest.mark.asyncio
    async def test_emit_with_target(self):
        """Test targeted emissions with 'to' parameter."""
        client, server = MockSocketIO.create_socketio_connection()
        
        # Emit with specific target
        await client.emit('private_message', {'text': 'secret'}, to='user-123')
        
        # Check event was recorded with target
        events = client.get_emitted_events('private_message', to='user-123')
        assert len(events) == 1
        assert events[0][1] == {'text': 'secret'}
        assert events[0][2] == 'user-123'
    
    @pytest.mark.asyncio
    async def test_clear_emitted_events(self):
        """Test clearing emitted events."""
        client, server = MockSocketIO.create_socketio_connection()
        
        # Emit some events
        await client.emit('event1', {'data': 1})
        await client.emit('event2', {'data': 2})
        
        assert len(client.emitted_events) == 2
        
        # Clear events
        client.clear_emitted_events()
        
        assert len(client.emitted_events) == 0
    
    @pytest.mark.asyncio
    async def test_assert_helpers(self):
        """Test assertion helper methods."""
        client, server = MockSocketIO.create_socketio_connection()
        
        # Emit an event
        await client.emit('test_event', {'value': 42})
        
        # Assert event was emitted
        client.assert_event_emitted('test_event')
        
        # Assert no other event was emitted
        client.assert_no_event('other_event')
        
        # These should raise assertions
        with pytest.raises(AssertionError):
            client.assert_no_event('test_event')
        
        with pytest.raises(AssertionError):
            client.assert_event_emitted('nonexistent')
    
    @pytest.mark.asyncio
    async def test_multiple_handlers_same_event(self):
        """Test multiple handlers for the same event."""
        client, server = MockSocketIO.create_socketio_connection()
        
        handler1_called = []
        handler2_called = []
        
        @server.on('multi')
        async def handler1(sid, data):
            handler1_called.append(data)
        
        @server.on('multi')
        async def handler2(sid, data):
            handler2_called.append(data)
        
        # Send event
        await client.emit('multi', {'value': 'test'})
        
        # Both handlers should be called
        assert handler1_called == [{'value': 'test'}]
        assert handler2_called == [{'value': 'test'}]
    
    @pytest.mark.asyncio
    async def test_handler_with_different_signatures(self):
        """Test handlers with different parameter signatures."""
        client, server = MockSocketIO.create_socketio_connection()
        
        results = []
        
        # Handler with just data parameter
        @server.on('data_only')
        async def handle_data_only(data):
            results.append(('data_only', data))
        
        # Handler with sid and data
        @server.on('sid_data')
        async def handle_sid_data(sid, data):
            results.append(('sid_data', sid, data))
        
        # Handler with event, sid, and data (for wildcards)
        @server.on('*')
        async def handle_all(event, sid, data):
            results.append(('wildcard', event, sid, data))
        
        # Send events
        await client.emit('data_only', {'value': 1})
        await client.emit('sid_data', {'value': 2})
        
        # Check all handlers were called correctly
        assert len(results) == 4  # data_only + wildcard, sid_data + wildcard
        
        # Find and verify each result
        data_only_results = [r for r in results if r[0] == 'data_only']
        assert len(data_only_results) == 1
        assert data_only_results[0] == ('data_only', {'value': 1})
        
        sid_data_results = [r for r in results if r[0] == 'sid_data']
        assert len(sid_data_results) == 1
        assert sid_data_results[0][2] == {'value': 2}
    
    @pytest.mark.asyncio
    async def test_error_handling_in_handler(self):
        """Test that errors in handlers are caught and logged."""
        client, server = MockSocketIO.create_socketio_connection()
        
        successful_calls = []
        
        @server.on('error_event')
        async def faulty_handler(sid, data):
            if data.get('should_error'):
                raise ValueError("Intentional error")
            successful_calls.append(data)
        
        @server.on('error_event')
        async def good_handler(sid, data):
            successful_calls.append({'good': True})
        
        # Send event that triggers error in first handler
        await client.emit('error_event', {'should_error': True})
        
        # Second handler should still be called
        assert len(successful_calls) == 1
        assert successful_calls[0] == {'good': True}
        
        # Send event without error
        successful_calls.clear()
        await client.emit('error_event', {'should_error': False})
        
        # Both handlers should succeed
        assert len(successful_calls) == 2
    
    # Edge Cases and Race Conditions
    
    @pytest.mark.asyncio
    async def test_concurrent_emissions(self):
        """Test handling of concurrent event emissions."""
        client, server = MockSocketIO.create_socketio_connection()
        
        received_events = []
        
        @server.on('concurrent')
        async def handle_concurrent(sid, data):
            # Simulate some async processing
            await asyncio.sleep(0.001)
            received_events.append(data['id'])
        
        # Send multiple events concurrently
        tasks = []
        for i in range(10):
            tasks.append(client.emit('concurrent', {'id': i}))
        
        await asyncio.gather(*tasks)
        
        # Small delay to ensure all handlers complete
        await asyncio.sleep(0.02)
        
        # All events should be received
        assert len(received_events) == 10
        assert set(received_events) == set(range(10))
    
    @pytest.mark.asyncio
    async def test_bidirectional_race_condition(self):
        """Test simultaneous bidirectional communication."""
        client, server = MockSocketIO.create_socketio_connection()
        
        client_received = []
        server_received = []
        
        @client.on('from_server')
        async def client_handler(sid, data):
            client_received.append(data['num'])
        
        @server.on('from_client')
        async def server_handler(sid, data):
            server_received.append(data['num'])
        
        # Send events simultaneously from both sides
        tasks = []
        for i in range(5):
            tasks.append(client.emit('from_client', {'num': i}))
            tasks.append(server.emit('from_server', {'num': i}))
        
        await asyncio.gather(*tasks)
        
        # Both sides should receive all events
        assert len(client_received) == 5
        assert len(server_received) == 5
        assert set(client_received) == set(range(5))
        assert set(server_received) == set(range(5))
    
    @pytest.mark.asyncio
    async def test_handler_execution_order(self):
        """Test that handlers are executed in registration order."""
        client, server = MockSocketIO.create_socketio_connection()
        
        execution_order = []
        
        @server.on('ordered')
        async def first_handler(sid, data):
            execution_order.append('first')
        
        @server.on('ordered')
        async def second_handler(sid, data):
            execution_order.append('second')
        
        @server.on('ordered')
        async def third_handler(sid, data):
            execution_order.append('third')
        
        await client.emit('ordered', {})
        
        assert execution_order == ['first', 'second', 'third']
    
    @pytest.mark.asyncio
    async def test_async_handler_with_delay(self):
        """Test handlers with async operations and delays."""
        client, server = MockSocketIO.create_socketio_connection()
        
        results = []
        
        @server.on('async_op')
        async def slow_handler(sid, data):
            # Simulate async operation
            await asyncio.sleep(data['delay'])
            results.append(data['id'])
            await server.emit('processed', {'id': data['id']})
        
        # Send events with different delays
        await client.emit('async_op', {'id': 1, 'delay': 0.02})
        await client.emit('async_op', {'id': 2, 'delay': 0.01})
        await client.emit('async_op', {'id': 3, 'delay': 0.005})
        
        # Wait for all to complete
        await asyncio.sleep(0.03)
        
        # Despite different delays, all should complete
        assert len(results) == 3
        assert set(results) == {1, 2, 3}
        
        # Check emissions were recorded
        processed_events = server.get_emitted_events('processed')
        assert len(processed_events) == 3
    
    @pytest.mark.asyncio
    async def test_exception_in_concurrent_handlers(self):
        """Test that exceptions in one handler don't affect others running concurrently."""
        client, server = MockSocketIO.create_socketio_connection()
        
        completed = []
        
        @server.on('concurrent_error')
        async def handler1(sid, data):
            await asyncio.sleep(0.001)
            if data['id'] == 5:
                raise RuntimeError("Intentional error")
            completed.append(f"h1-{data['id']}")
        
        @server.on('concurrent_error')
        async def handler2(sid, data):
            await asyncio.sleep(0.001)
            completed.append(f"h2-{data['id']}")
        
        # Send multiple events
        tasks = []
        for i in range(10):
            tasks.append(client.emit('concurrent_error', {'id': i}))
        
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.02)
        
        # Handler 2 should complete all 10, handler 1 should complete 9 (not id=5)
        h2_completed = [c for c in completed if c.startswith('h2-')]
        h1_completed = [c for c in completed if c.startswith('h1-')]
        
        assert len(h2_completed) == 10
        assert len(h1_completed) == 9
        assert 'h1-5' not in completed
    
    @pytest.mark.asyncio
    async def test_no_partner_socket(self):
        """Test behavior when socket has no partner."""
        solo_socket = MockSocketIO()
        
        @solo_socket.on('test')
        async def handler(sid, data):
            # This won't be called since no partner triggers it
            pass
        
        # Emit should work but not trigger any handlers
        await solo_socket.emit('test', {'data': 'value'})
        
        # Event should be recorded
        events = solo_socket.get_emitted_events('test')
        assert len(events) == 1
        assert events[0][1] == {'data': 'value'}
    
    @pytest.mark.asyncio
    async def test_circular_event_chain(self):
        """Test handling of events that trigger each other (potential infinite loop)."""
        client, server = MockSocketIO.create_socketio_connection()
        
        counter = {'count': 0}
        
        @server.on('ping')
        async def handle_ping(sid, data):
            counter['count'] += 1
            if counter['count'] < 5:  # Prevent infinite loop
                await server.emit('pong', {'count': counter['count']})
        
        @client.on('pong')
        async def handle_pong(sid, data):
            if data['count'] < 5:
                await client.emit('ping', {'count': data['count']})
        
        # Start the chain
        await client.emit('ping', {'count': 0})
        
        # Wait for chain to complete
        await asyncio.sleep(0.01)
        
        assert counter['count'] == 5
    
    @pytest.mark.asyncio
    async def test_large_payload(self):
        """Test handling of large data payloads."""
        client, server = MockSocketIO.create_socketio_connection()
        
        received_data = []
        
        @server.on('large_data')
        async def handle_large(sid, data):
            received_data.append(data)
        
        # Create large payload
        large_list = list(range(10000))
        large_dict = {str(i): f"value_{i}" for i in range(1000)}
        
        await client.emit('large_data', {'list': large_list, 'dict': large_dict})
        
        assert len(received_data) == 1
        assert received_data[0]['list'] == large_list
        assert received_data[0]['dict'] == large_dict
    
    @pytest.mark.asyncio
    async def test_empty_and_none_data(self):
        """Test handling of empty and None data values."""
        client, server = MockSocketIO.create_socketio_connection()
        
        received = []
        
        @server.on('empty')
        async def handle_empty(sid, data):
            received.append(('empty', data))
        
        @server.on('none')
        async def handle_none(sid, data):
            received.append(('none', data))
        
        # Send with various empty values
        await client.emit('empty', {})
        await client.emit('empty', [])
        await client.emit('empty', '')
        await client.emit('none', None)
        await client.emit('none')  # No data parameter
        
        assert len(received) == 5
        assert received[0] == ('empty', {})
        assert received[1] == ('empty', [])
        assert received[2] == ('empty', '')
        assert received[3] == ('none', None)
        assert received[4] == ('none', None)
    
    @pytest.mark.asyncio
    async def test_handler_modifying_shared_state(self):
        """Test thread safety with handlers modifying shared state."""
        client, server = MockSocketIO.create_socketio_connection()
        
        shared_list = []
        
        @server.on('modify')
        async def modify_handler(sid, data):
            # Simulate race condition with shared state
            current = len(shared_list)
            await asyncio.sleep(0.001)  # Simulate async work
            shared_list.append(current)
        
        # Send multiple events concurrently
        tasks = [client.emit('modify', {'i': i}) for i in range(20)]
        await asyncio.gather(*tasks)
        
        await asyncio.sleep(0.05)
        
        # Despite concurrent access, all should be added
        assert len(shared_list) == 20
    
    @pytest.mark.asyncio
    async def test_recursive_emit_from_handler(self):
        """Test handler that emits events recursively."""
        client, server = MockSocketIO.create_socketio_connection()
        
        depth_counter = []
        
        @server.on('recursive')
        async def recursive_handler(sid, data):
            depth = data.get('depth', 0)
            depth_counter.append(depth)
            
            if depth < 3:
                # Handler emits back to client
                await server.emit('recursive_response', {'depth': depth + 1})
        
        @client.on('recursive_response')
        async def client_recursive_handler(sid, data):
            # Client responds by sending back to server
            await client.emit('recursive', {'depth': data['depth']})
        
        # Start recursion
        await client.emit('recursive', {'depth': 0})
        
        # Wait for recursion to complete
        await asyncio.sleep(0.02)
        
        assert depth_counter == [0, 1, 2, 3]
    
    @pytest.mark.asyncio
    async def test_pattern_priority(self):
        """Test that exact match takes priority over wildcard/regex."""
        client, server = MockSocketIO.create_socketio_connection()
        
        calls = []
        
        @server.on('specific_event')
        async def exact_handler(sid, data):
            calls.append('exact')
        
        @server.on('*')
        async def wildcard_handler(event, sid, data):
            calls.append('wildcard')
        
        @server.on('regex:specific.*')
        async def regex_handler(sid, data):
            calls.append('regex')
        
        await client.emit('specific_event', {})
        
        # All matching handlers should be called
        assert 'exact' in calls
        assert 'wildcard' in calls
        assert 'regex' in calls
        
        # Exact should be first (registered first and checked first)
        assert calls[0] == 'exact'
    
    @pytest.mark.asyncio
    async def test_emit_without_await(self):
        """Test that forgetting await on emit is handled gracefully."""
        client, server = MockSocketIO.create_socketio_connection()
        
        received = []
        
        @server.on('test')
        async def handler(sid, data):
            received.append(data)
        
        # Create task without await (fire-and-forget pattern)
        asyncio.create_task(client.emit('test', {'value': 1}))
        asyncio.create_task(client.emit('test', {'value': 2}))
        
        # Give tasks time to execute
        await asyncio.sleep(0.01)
        
        assert len(received) == 2
        assert {r['value'] for r in received} == {1, 2}