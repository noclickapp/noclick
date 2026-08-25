/**
 * Unit tests for DocumentStateManager.
 * Tests the conflict resolution logic that implements Figma-style property-level last-writer-wins.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { DocumentStateManager } from './documentStateManager';

describe('DocumentStateManager', () => {
  let manager: DocumentStateManager;

  beforeEach(() => {
    manager = new DocumentStateManager();
  });

  describe('initializeFromNodes', () => {
    it('should store initial positions for all nodes', () => {
      const nodes = [
        { id: 'node-1', position: { x: 100, y: 200 }, data: {} },
        { id: 'node-2', position: { x: 300, y: 400 }, data: {} },
      ];

      manager.initializeFromNodes(nodes as any);

      expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 200 });
      expect(manager.getNodePosition('node-2')).toEqual({ x: 300, y: 400 });
    });

    it('should return undefined for non-existent nodes', () => {
      expect(manager.getNodePosition('non-existent')).toBeUndefined();
    });
  });

  describe('recordLocalChange', () => {
    it('should record local position changes', () => {
      const position = manager.recordLocalChange('node-1', { x: 150, y: 250 });

      expect(position).toEqual({ x: 150, y: 250 });
      expect(manager.getNodePosition('node-1')).toEqual({ x: 150, y: 250 });
    });

    it('should track pending changes when connected', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      expect(manager.hasPendingChanges()).toBe(true);
    });

    it('should mark offline changes when disconnected', () => {
      manager.setDisconnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      expect(manager.hasPendingChanges()).toBe(true);
    });
  });

  describe('handleRemoteChange - Last Writer Wins', () => {
    it('should apply remote change when no local state exists', () => {
      const result = manager.handleRemoteChange('node-1', { x: 200, y: 300 });

      expect(result.shouldApply).toBe(true);
      expect(result.position).toEqual({ x: 200, y: 300 });
      expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 300 });
    });

    it('should apply remote change with newer timestamp', () => {
      // Local change at time T
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      // Remote change with newer timestamp wins
      const futureTime = Date.now() + 1000;
      const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, futureTime);

      expect(result.shouldApply).toBe(true);
      expect(result.position).toEqual({ x: 200, y: 200 });
    });

    it('should reject remote change with older timestamp', () => {
      // Record local change first
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      // Remote change with older timestamp loses
      const pastTime = Date.now() - 1000;
      const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, pastTime);

      expect(result.shouldApply).toBe(false);
      expect(result.position).toEqual({ x: 100, y: 100 }); // Returns local position
    });

    it('should notify listeners on applied remote changes', () => {
      const listener = vi.fn();
      manager.onRemotePositionUpdate(listener);

      manager.handleRemoteChange('node-1', { x: 300, y: 400 });

      expect(listener).toHaveBeenCalledWith('node-1', expect.objectContaining({
        x: 300,
        y: 400,
      }));
    });

    it('should not notify listeners when remote change is rejected', () => {
      const listener = vi.fn();
      manager.onRemotePositionUpdate(listener);

      // Record local change first
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      // Remote change with older timestamp
      const pastTime = Date.now() - 1000;
      manager.handleRemoteChange('node-1', { x: 200, y: 200 }, pastTime);

      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe('Concurrent Edits - Same Node', () => {
    it('should resolve concurrent edits with last-writer-wins', () => {
      // Simulate two users editing the same node
      // User A edits at T=1000
      manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);

      // User B edits at T=2000 (later, so wins)
      const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 2000);

      expect(result.shouldApply).toBe(true);
      expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });
    });

    it('should handle rapid concurrent updates correctly', () => {
      // Simulate rapid updates from multiple users
      const times = [1000, 1001, 1002, 999, 1003, 998];
      const positions = times.map((t, i) => ({ x: i * 100, y: i * 100 }));

      times.forEach((time, i) => {
        manager.handleRemoteChange('node-1', positions[i], time);
      });

      // The update at T=1003 should win
      expect(manager.getNodePosition('node-1')).toEqual({ x: 400, y: 400 });
    });
  });

  describe('Concurrent Edits - Different Nodes (No Conflict)', () => {
    it('should allow edits to different nodes independently', () => {
      // User A edits node-1
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      // User B edits node-2 (no conflict)
      const result = manager.handleRemoteChange('node-2', { x: 200, y: 200 });

      expect(result.shouldApply).toBe(true);
      expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
      expect(manager.getNodePosition('node-2')).toEqual({ x: 200, y: 200 });
    });

    it('should handle property-level isolation per node', () => {
      // Initialize with two nodes
      manager.initializeFromNodes([
        { id: 'node-1', position: { x: 0, y: 0 }, data: {} },
        { id: 'node-2', position: { x: 0, y: 0 }, data: {} },
      ] as any);

      // Concurrent edits to different nodes should both succeed
      manager.recordLocalChange('node-1', { x: 100, y: 100 });
      manager.handleRemoteChange('node-2', { x: 200, y: 200 });

      expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
      expect(manager.getNodePosition('node-2')).toEqual({ x: 200, y: 200 });
    });
  });

  describe('Offline/Online Reconnection', () => {
    it('should preserve local changes during offline period', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      // Go offline
      manager.setDisconnected();
      manager.recordLocalChange('node-1', { x: 200, y: 200 });

      expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });
      expect(manager.hasPendingChanges()).toBe(true);
    });

    it('should reapply pending changes on reconnect when server differs', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      // Simulate server having different state
      const serverNodes = [
        { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
      ];

      const changesToReapply = manager.onReconnect(serverNodes as any);

      // Should return our pending change to reapply
      expect(changesToReapply).toHaveLength(1);
      expect(changesToReapply[0]).toEqual({
        nodeId: 'node-1',
        position: { x: 100, y: 100 },
      });
    });

    it('should accept server state when no pending changes', () => {
      // No local changes, just server state
      const serverNodes = [
        { id: 'node-1', position: { x: 500, y: 500 }, data: {} },
      ];

      const changesToReapply = manager.onReconnect(serverNodes as any);

      expect(changesToReapply).toHaveLength(0);
      expect(manager.getNodePosition('node-1')).toEqual({ x: 500, y: 500 });
    });

    it('should handle mixed scenario - some nodes with pending changes, some without', () => {
      manager.setConnected();
      
      // Only node-1 has pending changes
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      const serverNodes = [
        { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
        { id: 'node-2', position: { x: 300, y: 300 }, data: {} },
      ];

      const changesToReapply = manager.onReconnect(serverNodes as any);

      // Only node-1 should be reapplied
      expect(changesToReapply).toHaveLength(1);
      expect(changesToReapply[0].nodeId).toBe('node-1');

      // node-2 should have server state
      expect(manager.getNodePosition('node-2')).toEqual({ x: 300, y: 300 });
    });

    it('should keep pending changes after reapplication until acknowledged', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });
      expect(manager.hasPendingChanges()).toBe(true);

      manager.onReconnect([{ id: 'node-1', position: { x: 50, y: 50 }, data: {} }] as any);

      // Pending changes NOT cleared - caller must acknowledge after broadcast
      expect(manager.hasPendingChanges()).toBe(true);

      // After successful broadcast, caller acknowledges
      manager.acknowledgeChange('node-1');
      expect(manager.hasPendingChanges()).toBe(false);
    });
  });

  describe('acknowledgeChange', () => {
    it('should remove acknowledged changes from pending', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });
      expect(manager.hasPendingChanges()).toBe(true);

      manager.acknowledgeChange('node-1');

      expect(manager.hasPendingChanges()).toBe(false);
    });

    it('should only remove changes for the specified node', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });
      manager.recordLocalChange('node-2', { x: 200, y: 200 });

      manager.acknowledgeChange('node-1');

      expect(manager.hasPendingChanges()).toBe(true); // node-2 still pending
    });
  });

  describe('Subscription Management', () => {
    it('should allow subscribing to remote position updates', () => {
      const listener = vi.fn();
      const unsubscribe = manager.onRemotePositionUpdate(listener);

      manager.handleRemoteChange('node-1', { x: 100, y: 100 });

      expect(listener).toHaveBeenCalled();
      
      unsubscribe();
      
      manager.handleRemoteChange('node-1', { x: 200, y: 200 });
      expect(listener).toHaveBeenCalledTimes(1); // Not called again after unsubscribe
    });
  });

  describe('clear', () => {
    it('should reset all state', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });
      const listener = vi.fn();
      manager.onRemotePositionUpdate(listener);

      manager.clear();

      expect(manager.getNodePosition('node-1')).toBeUndefined();
      expect(manager.hasPendingChanges()).toBe(false);
      
      // Listener should be cleared
      manager.handleRemoteChange('node-1', { x: 200, y: 200 });
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe('Edge Cases', () => {
    it('should handle same timestamp (tie-breaker)', () => {
      const sameTime = Date.now();

      // Both changes at exactly the same time
      manager.handleRemoteChange('node-1', { x: 100, y: 100 }, sameTime);
      const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, sameTime);

      // Second one should win (>= comparison)
      expect(result.shouldApply).toBe(true);
    });

    it('should handle deleted nodes on reconnect gracefully', () => {
      manager.setConnected();
      manager.recordLocalChange('node-deleted', { x: 100, y: 100 });

      // Server doesn't have this node anymore
      const serverNodes = [
        { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
      ];

      const changesToReapply = manager.onReconnect(serverNodes as any);

      // Should not crash, and should not try to reapply deleted node
      expect(changesToReapply).toHaveLength(0);
    });

    it('should handle empty server state on reconnect', () => {
      manager.setConnected();
      manager.recordLocalChange('node-1', { x: 100, y: 100 });

      const changesToReapply = manager.onReconnect([]);

      // No nodes to reapply to
      expect(changesToReapply).toHaveLength(0);
    });
  });

  describe('Critical Edge Cases', () => {
    describe('Timestamp Precision', () => {
      it('should handle sub-millisecond rapid changes correctly', () => {
        // Simulate very rapid changes (same millisecond)
        const baseTime = Date.now();

        // 5 changes all at "same" millisecond
        for (let i = 0; i < 5; i++) {
          manager.handleRemoteChange('node-1', { x: i * 10, y: i * 10 }, baseTime);
        }

        // Last applied should be the final one (x: 40, y: 40)
        expect(manager.getNodePosition('node-1')).toEqual({ x: 40, y: 40 });
      });

      it('should handle interleaved local and remote changes in same millisecond', () => {
        // Pin the clock: recordLocalChange stamps Date.now() internally, and on a
        // slow runner a millisecond can elapse after capturing `time`, making the
        // local stamp beat time + 1 and flaking the assertion.
        const time = Date.now();
        const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(time);

        // Local change
        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        nowSpy.mockRestore();

        // Remote change one millisecond later - should apply (>= check)
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, time + 1);

        expect(result.shouldApply).toBe(true);
      });
    });

    describe('Node Deletion During Operations', () => {
      it('should handle pending change for node that gets deleted', () => {
        manager.setConnected();

        // User starts dragging node-1
        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        manager.recordLocalChange('node-1', { x: 150, y: 150 });

        // Node gets deleted by another user (simulated by not being in server state)
        const serverNodes = [
          { id: 'node-2', position: { x: 200, y: 200 }, data: {} },
        ];

        const changesToReapply = manager.onReconnect(serverNodes as any);

        // Should NOT try to reapply changes for deleted node
        expect(changesToReapply).toHaveLength(0);

        // node-1 should be gone from local state
        expect(manager.getNodePosition('node-1')).toBeUndefined();

        // node-2 should be added
        expect(manager.getNodePosition('node-2')).toEqual({ x: 200, y: 200 });
      });

      it('should clear pending changes for deleted nodes after reconnect', () => {
        manager.setConnected();
        manager.recordLocalChange('node-deleted', { x: 100, y: 100 });

        expect(manager.hasPendingChanges()).toBe(true);

        manager.onReconnect([]);

        expect(manager.hasPendingChanges()).toBe(false);
      });
    });

    describe('Three-Way Conflicts', () => {
      it('should resolve three-user conflict with last-writer-wins', () => {
        // User A edits at T=1000
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);

        // User B edits at T=1500
        manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 1500);

        // User C edits at T=1200 (out of order, but older)
        const result = manager.handleRemoteChange('node-1', { x: 300, y: 300 }, 1200);

        // User C's change should be rejected (older than B's)
        expect(result.shouldApply).toBe(false);

        // Position should still be User B's (the latest)
        expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });
      });

      it('should handle out-of-order message arrival', () => {
        // Messages arrive out of order due to network
        // Order received: T=1500, T=1000, T=2000

        manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 1500);
        expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });

        // Older message arrives late - should be rejected
        const result1 = manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);
        expect(result1.shouldApply).toBe(false);
        expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });

        // Newer message arrives - should be applied
        const result2 = manager.handleRemoteChange('node-1', { x: 300, y: 300 }, 2000);
        expect(result2.shouldApply).toBe(true);
        expect(manager.getNodePosition('node-1')).toEqual({ x: 300, y: 300 });
      });
    });

    describe('Reconnection Stress Tests', () => {
      it('should handle multiple rapid reconnections', () => {
        const serverNodes = [
          { id: 'node-1', position: { x: 100, y: 100 }, data: {} },
        ];

        // Simulate rapid connect/disconnect cycles
        for (let i = 0; i < 5; i++) {
          manager.setConnected();
          manager.recordLocalChange('node-1', { x: i * 10, y: i * 10 });
          manager.setDisconnected();
          manager.onReconnect(serverNodes as any);
        }

        // Should not crash and should have valid state
        expect(manager.getNodePosition('node-1')).toBeDefined();
        // Changes preserved until acknowledged (prevents data loss on rapid reconnect)
        expect(manager.hasPendingChanges()).toBe(true);
      });

      it('should preserve changes on rapid disconnect-reconnect before broadcast', () => {
        // This tests the critical bug: if we disconnect again BEFORE broadcasting
        // the reapplied changes, they should not be lost.

        const serverNodes = [
          { id: 'node-1', position: { x: 0, y: 0 }, data: {} },
        ];

        // 1. Connect and make a change
        manager.setConnected();
        manager.recordLocalChange('node-1', { x: 100, y: 100 });

        // 2. Disconnect
        manager.setDisconnected();

        // 3. Reconnect - get changes to reapply
        const changes1 = manager.onReconnect(serverNodes as any);
        expect(changes1).toHaveLength(1);
        expect(changes1[0].position).toEqual({ x: 100, y: 100 });

        // 4. BEFORE broadcasting, we disconnect again!
        manager.setDisconnected();

        // 5. Reconnect again
        const changes2 = manager.onReconnect(serverNodes as any);

        // 6. Changes should STILL be returned (not lost)
        expect(changes2).toHaveLength(1);
        expect(changes2[0].position).toEqual({ x: 100, y: 100 });

        // 7. Only after successful broadcast should caller acknowledge
        manager.acknowledgeChange('node-1');
        expect(manager.hasPendingChanges()).toBe(false);
      });

      it('should handle reconnect with completely different node set', () => {
        manager.setConnected();

        // User has nodes 1, 2, 3
        manager.initializeFromNodes([
          { id: 'node-1', position: { x: 0, y: 0 }, data: {} },
          { id: 'node-2', position: { x: 100, y: 100 }, data: {} },
          { id: 'node-3', position: { x: 200, y: 200 }, data: {} },
        ] as any);

        // Make changes to node-1
        manager.recordLocalChange('node-1', { x: 50, y: 50 });

        // Server now has completely different nodes (4, 5, 6)
        const serverNodes = [
          { id: 'node-4', position: { x: 300, y: 300 }, data: {} },
          { id: 'node-5', position: { x: 400, y: 400 }, data: {} },
          { id: 'node-6', position: { x: 500, y: 500 }, data: {} },
        ];

        const changesToReapply = manager.onReconnect(serverNodes as any);

        // No changes to reapply (node-1 doesn't exist on server)
        expect(changesToReapply).toHaveLength(0);

        // Should have new server nodes
        expect(manager.getNodePosition('node-4')).toEqual({ x: 300, y: 300 });
        expect(manager.getNodePosition('node-5')).toEqual({ x: 400, y: 400 });
        expect(manager.getNodePosition('node-6')).toEqual({ x: 500, y: 500 });
      });

      it('should handle partial overlap of nodes on reconnect', () => {
        manager.setConnected();

        // User has nodes 1, 2, 3
        manager.initializeFromNodes([
          { id: 'node-1', position: { x: 0, y: 0 }, data: {} },
          { id: 'node-2', position: { x: 100, y: 100 }, data: {} },
          { id: 'node-3', position: { x: 200, y: 200 }, data: {} },
        ] as any);

        // Pending change on node-2
        manager.recordLocalChange('node-2', { x: 150, y: 150 });

        // Server has nodes 2, 3, 4 (node-1 deleted, node-4 added)
        const serverNodes = [
          { id: 'node-2', position: { x: 120, y: 120 }, data: {} },
          { id: 'node-3', position: { x: 250, y: 250 }, data: {} },
          { id: 'node-4', position: { x: 300, y: 300 }, data: {} },
        ];

        const changesToReapply = manager.onReconnect(serverNodes as any);

        // Should reapply node-2 change
        expect(changesToReapply).toHaveLength(1);
        expect(changesToReapply[0]).toEqual({ nodeId: 'node-2', position: { x: 150, y: 150 } });

        // node-3 should have server state (no pending change)
        expect(manager.getNodePosition('node-3')).toEqual({ x: 250, y: 250 });

        // node-4 should be added
        expect(manager.getNodePosition('node-4')).toEqual({ x: 300, y: 300 });
      });
    });

    describe('Multiple Pending Changes Same Node', () => {
      it('should handle multiple pending changes for same node correctly', () => {
        manager.setConnected();

        // Multiple drags of same node before server ack
        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        manager.recordLocalChange('node-1', { x: 150, y: 150 });
        manager.recordLocalChange('node-1', { x: 200, y: 200 });

        // Current position should be the latest
        expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });

        // Server has old position
        const serverNodes = [
          { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
        ];

        const changesToReapply = manager.onReconnect(serverNodes as any);

        // Should reapply with latest position
        expect(changesToReapply).toHaveLength(1);
        expect(changesToReapply[0].position).toEqual({ x: 200, y: 200 });
      });

      it('should acknowledge all pending changes for a node at once', () => {
        manager.setConnected();

        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        manager.recordLocalChange('node-1', { x: 150, y: 150 });
        manager.recordLocalChange('node-1', { x: 200, y: 200 });

        expect(manager.hasPendingChanges()).toBe(true);

        // Single acknowledge clears all pending for that node
        manager.acknowledgeChange('node-1');

        expect(manager.hasPendingChanges()).toBe(false);
      });
    });

    describe('State Corruption Prevention', () => {
      it('should maintain consistency after many operations', () => {
        manager.setConnected();

        // Simulate heavy usage
        for (let i = 0; i < 100; i++) {
          const nodeId = `node-${i % 10}`;

          if (i % 3 === 0) {
            manager.recordLocalChange(nodeId, { x: i, y: i });
          } else {
            manager.handleRemoteChange(nodeId, { x: i * 2, y: i * 2 }, Date.now() + i);
          }

          if (i % 7 === 0) {
            manager.acknowledgeChange(nodeId);
          }
        }

        // Should not crash and all positions should be valid numbers
        for (let i = 0; i < 10; i++) {
          const pos = manager.getNodePosition(`node-${i}`);
          expect(pos).toBeDefined();
          expect(typeof pos!.x).toBe('number');
          expect(typeof pos!.y).toBe('number');
          expect(Number.isFinite(pos!.x)).toBe(true);
          expect(Number.isFinite(pos!.y)).toBe(true);
        }
      });

      it('should handle very large position values', () => {
        const largePos = { x: 1e10, y: 1e10 };

        manager.recordLocalChange('node-1', largePos);

        expect(manager.getNodePosition('node-1')).toEqual(largePos);
      });

      it('should handle negative position values', () => {
        const negativePos = { x: -500, y: -300 };

        manager.recordLocalChange('node-1', negativePos);

        expect(manager.getNodePosition('node-1')).toEqual(negativePos);
      });

      it('should handle zero position values', () => {
        const zeroPos = { x: 0, y: 0 };

        manager.recordLocalChange('node-1', zeroPos);

        expect(manager.getNodePosition('node-1')).toEqual(zeroPos);
      });

      it('should handle decimal position values', () => {
        const decimalPos = { x: 123.456789, y: 987.654321 };

        manager.recordLocalChange('node-1', decimalPos);

        expect(manager.getNodePosition('node-1')).toEqual(decimalPos);
      });
    });

    describe('Listener Edge Cases', () => {
      it('should handle listener throwing an error', () => {
        const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        const errorListener = vi.fn(() => {
          throw new Error('Listener error');
        });
        const goodListener = vi.fn();

        manager.onRemotePositionUpdate(errorListener);
        manager.onRemotePositionUpdate(goodListener);

        // Should not crash - error is caught and logged
        expect(() => {
          manager.handleRemoteChange('node-1', { x: 100, y: 100 });
        }).not.toThrow();

        // Both listeners were called, error was logged
        expect(errorListener).toHaveBeenCalled();
        expect(goodListener).toHaveBeenCalled();
        expect(consoleSpy).toHaveBeenCalledWith('Error in position listener:', expect.any(Error));

        consoleSpy.mockRestore();
      });

      it('should handle unsubscribing during iteration', () => {
        let unsubscribe2: (() => void) | null = null;

        const listener1 = vi.fn();
        const listener2 = vi.fn(() => {
          // Unsubscribe self during callback
          unsubscribe2?.();
        });

        manager.onRemotePositionUpdate(listener1);
        unsubscribe2 = manager.onRemotePositionUpdate(listener2);

        // This could cause issues if not handled properly
        manager.handleRemoteChange('node-1', { x: 100, y: 100 });

        // Both should have been called once
        expect(listener1).toHaveBeenCalledTimes(1);
        expect(listener2).toHaveBeenCalledTimes(1);
      });
    });

    describe('Clock Skew and Time Anomalies', () => {
      it('should handle client with clock far in the future', () => {
        // User A's clock is 1 hour ahead - their changes always appear "newer"
        const userATime = Date.now() + 60 * 60 * 1000; // 1 hour ahead
        const userBTime = Date.now();

        // User A makes change with future timestamp
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, userATime);

        // User B makes change with "current" time - should lose despite being "later" in real time
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, userBTime);

        expect(result.shouldApply).toBe(false);
        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
      });

      it('should handle clock going backwards (NTP sync)', () => {
        // Simulate: local change at T=1000, then clock syncs backwards
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);

        // After NTP sync, new "current" time is actually earlier
        // This simulates Date.now() returning a smaller value after clock sync
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 500);

        // Should reject because 500 < 1000
        expect(result.shouldApply).toBe(false);
      });

      it('should handle very large timestamps (year 3000)', () => {
        const farFutureTime = new Date('3000-01-01').getTime();

        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, farFutureTime);

        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });

        // Any normal timestamp should lose
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, Date.now());
        expect(result.shouldApply).toBe(false);
      });

      it('should handle timestamp of 0', () => {
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 0);

        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });

        // Any non-zero timestamp should win
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 1);
        expect(result.shouldApply).toBe(true);
      });

      it('should handle negative timestamp', () => {
        // Shouldn't happen, but let's be defensive
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, -1000);

        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });

        // Positive timestamp should win
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 1);
        expect(result.shouldApply).toBe(true);
      });
    });

    describe('Initialization Edge Cases', () => {
      it('should handle operations before initialization', () => {
        // User starts dragging before canvas fully loads
        manager.recordLocalChange('node-1', { x: 100, y: 100 });

        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
        expect(manager.hasPendingChanges()).toBe(true);

        // Then initialization happens - clears pre-init state
        manager.initializeFromNodes([
          { id: 'node-1', position: { x: 0, y: 0 }, data: {} },
          { id: 'node-2', position: { x: 50, y: 50 }, data: {} },
        ] as any);

        // Positions from initialization, pending changes cleared
        expect(manager.getNodePosition('node-1')).toEqual({ x: 0, y: 0 });
        expect(manager.getNodePosition('node-2')).toEqual({ x: 50, y: 50 });
        expect(manager.hasPendingChanges()).toBe(false);
      });

      it('should handle re-initialization with pending changes', () => {
        manager.setConnected();

        // Initial state
        manager.initializeFromNodes([
          { id: 'node-1', position: { x: 0, y: 0 }, data: {} },
        ] as any);

        // User makes change
        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        expect(manager.hasPendingChanges()).toBe(true);

        // Re-initialization (e.g., workflow reload) clears stale pending changes
        manager.initializeFromNodes([
          { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
        ] as any);

        // Position should be from re-initialization, pending changes cleared
        expect(manager.getNodePosition('node-1')).toEqual({ x: 50, y: 50 });
        expect(manager.hasPendingChanges()).toBe(false); // Stale changes cleared
      });

      it('should handle initialization with empty array', () => {
        manager.initializeFromNodes([]);

        expect(manager.getNodePosition('node-1')).toBeUndefined();
        expect(manager.hasPendingChanges()).toBe(false);
      });

      it('should handle initialization with duplicate node IDs', () => {
        // Shouldn't happen, but let's see what happens
        manager.initializeFromNodes([
          { id: 'node-1', position: { x: 100, y: 100 }, data: {} },
          { id: 'node-1', position: { x: 200, y: 200 }, data: {} }, // Duplicate!
        ] as any);

        // Last one wins (Map behavior)
        expect(manager.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });
      });
    });

    describe('Invalid Position Values', () => {
      it('should handle NaN position values', () => {
        manager.recordLocalChange('node-1', { x: NaN, y: NaN });

        const pos = manager.getNodePosition('node-1');
        expect(pos).toBeDefined();
        // NaN is stored as-is - might want to validate/reject
        expect(Number.isNaN(pos!.x)).toBe(true);
        expect(Number.isNaN(pos!.y)).toBe(true);
      });

      it('should handle Infinity position values', () => {
        manager.recordLocalChange('node-1', { x: Infinity, y: -Infinity });

        const pos = manager.getNodePosition('node-1');
        expect(pos).toEqual({ x: Infinity, y: -Infinity });
      });

      it('should handle mixed valid/invalid positions', () => {
        manager.recordLocalChange('node-1', { x: 100, y: NaN });

        const pos = manager.getNodePosition('node-1');
        expect(pos!.x).toBe(100);
        expect(Number.isNaN(pos!.y)).toBe(true);
      });
    });

    describe('Node ID Edge Cases', () => {
      it('should handle empty string node ID', () => {
        manager.recordLocalChange('', { x: 100, y: 100 });

        expect(manager.getNodePosition('')).toEqual({ x: 100, y: 100 });
      });

      it('should handle node ID with special characters', () => {
        const specialId = 'node-with-special-chars_./\\:@#$%^&*()';
        manager.recordLocalChange(specialId, { x: 100, y: 100 });

        expect(manager.getNodePosition(specialId)).toEqual({ x: 100, y: 100 });
      });

      it('should handle very long node ID', () => {
        const longId = 'a'.repeat(10000);
        manager.recordLocalChange(longId, { x: 100, y: 100 });

        expect(manager.getNodePosition(longId)).toEqual({ x: 100, y: 100 });
      });

      it('should handle node IDs that look like numbers', () => {
        manager.recordLocalChange('123', { x: 100, y: 100 });
        manager.recordLocalChange('0', { x: 200, y: 200 });
        manager.recordLocalChange('-1', { x: 300, y: 300 });

        expect(manager.getNodePosition('123')).toEqual({ x: 100, y: 100 });
        expect(manager.getNodePosition('0')).toEqual({ x: 200, y: 200 });
        expect(manager.getNodePosition('-1')).toEqual({ x: 300, y: 300 });
      });
    });

    describe('Connection State Machine', () => {
      it('should handle multiple setConnected calls', () => {
        manager.setConnected();
        manager.setConnected();
        manager.setConnected();

        // Should not crash, state should be connected
        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        expect(manager.hasPendingChanges()).toBe(true);
      });

      it('should handle multiple setDisconnected calls', () => {
        manager.setDisconnected();
        manager.setDisconnected();
        manager.setDisconnected();

        // Should not crash
        manager.recordLocalChange('node-1', { x: 100, y: 100 });
        expect(manager.hasPendingChanges()).toBe(true); // hasOfflineChanges
      });

      it('should handle onReconnect without ever connecting', () => {
        // Fresh manager, never connected - but offline changes are now tracked
        manager.recordLocalChange('node-1', { x: 100, y: 100 });

        const serverNodes = [
          { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
        ];

        // Offline changes should be reapplied (user intent preserved)
        const changes = manager.onReconnect(serverNodes as any);
        expect(changes).toHaveLength(1);
        expect(changes[0]).toEqual({ nodeId: 'node-1', position: { x: 100, y: 100 } });
      });

      it('should handle rapid connect/disconnect toggling', () => {
        for (let i = 0; i < 20; i++) {
          if (i % 2 === 0) {
            manager.setConnected();
          } else {
            manager.setDisconnected();
          }
          manager.recordLocalChange('node-1', { x: i, y: i });
        }

        // Should not crash
        expect(manager.getNodePosition('node-1')).toBeDefined();
      });
    });

    describe('Listener Re-entrancy', () => {
      it('should handle listener that triggers another remote change', () => {
        const listener = vi.fn(() => {
          // Re-entrant call during listener execution
          manager.handleRemoteChange('node-2', { x: 999, y: 999 });
        });

        manager.onRemotePositionUpdate(listener);

        manager.handleRemoteChange('node-1', { x: 100, y: 100 });

        // Both nodes should be updated (state changes still happen during re-entry)
        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
        expect(manager.getNodePosition('node-2')).toEqual({ x: 999, y: 999 });

        // Listener should only be called once (for node-1) due to re-entrancy protection
        // The re-entrant call to handleRemoteChange for node-2 updates state but doesn't notify
        expect(listener).toHaveBeenCalledTimes(1);
      });

      it('should handle listener that records local change', () => {
        const listener = vi.fn(() => {
          manager.recordLocalChange('node-1', { x: 500, y: 500 });
        });

        manager.onRemotePositionUpdate(listener);
        manager.setConnected();

        // Remote change triggers listener which makes local change
        manager.handleRemoteChange('node-1', { x: 100, y: 100 });

        // Local change happened AFTER remote, so it should be the final state
        expect(manager.getNodePosition('node-1')).toEqual({ x: 500, y: 500 });
      });

      it('should handle listener that clears manager', () => {
        const listener = vi.fn(() => {
          manager.clear();
        });

        manager.onRemotePositionUpdate(listener);

        // This might cause issues
        manager.handleRemoteChange('node-1', { x: 100, y: 100 });

        // State should be cleared
        expect(manager.getNodePosition('node-1')).toBeUndefined();
      });
    });

    describe('Memory and Accumulation', () => {
      it('should accumulate pending changes without bound', () => {
        manager.setConnected();

        // Simulate many changes without acknowledgment
        for (let i = 0; i < 1000; i++) {
          manager.recordLocalChange(`node-${i % 10}`, { x: i, y: i });
        }

        // All should be pending
        expect(manager.hasPendingChanges()).toBe(true);

        // Acknowledging one node clears all its changes
        manager.acknowledgeChange('node-0');

        // Still have pending for other nodes
        expect(manager.hasPendingChanges()).toBe(true);
      });

      it('should keep pending changes on reconnect until acknowledged', () => {
        manager.setConnected();

        for (let i = 0; i < 100; i++) {
          manager.recordLocalChange(`node-${i % 10}`, { x: i, y: i });
        }

        const serverNodes = Array.from({ length: 10 }, (_, i) => ({
          id: `node-${i}`,
          position: { x: 0, y: 0 },
          data: {},
        }));

        manager.onReconnect(serverNodes as any);

        // Pending changes kept until caller acknowledges (after successful broadcast)
        expect(manager.hasPendingChanges()).toBe(true);

        // Acknowledge all nodes
        for (let i = 0; i < 10; i++) {
          manager.acknowledgeChange(`node-${i}`);
        }
        expect(manager.hasPendingChanges()).toBe(false);
      });
    });

    describe('Determinism', () => {
      it('should produce same result regardless of operation order for commutative ops', () => {
        const manager1 = new DocumentStateManager();
        const manager2 = new DocumentStateManager();

        // Same operations, different order (for different nodes)
        manager1.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);
        manager1.handleRemoteChange('node-2', { x: 200, y: 200 }, 2000);

        manager2.handleRemoteChange('node-2', { x: 200, y: 200 }, 2000);
        manager2.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);

        // Should have same final state
        expect(manager1.getNodePosition('node-1')).toEqual(manager2.getNodePosition('node-1'));
        expect(manager1.getNodePosition('node-2')).toEqual(manager2.getNodePosition('node-2'));
      });

      it('should converge to same state with out-of-order delivery', () => {
        const manager1 = new DocumentStateManager();
        const manager2 = new DocumentStateManager();

        // Simulate network delivering in different orders to different clients
        // Manager 1 receives: A(1000), B(2000), C(1500)
        manager1.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);
        manager1.handleRemoteChange('node-1', { x: 200, y: 200 }, 2000);
        manager1.handleRemoteChange('node-1', { x: 150, y: 150 }, 1500);

        // Manager 2 receives: C(1500), A(1000), B(2000)
        manager2.handleRemoteChange('node-1', { x: 150, y: 150 }, 1500);
        manager2.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000);
        manager2.handleRemoteChange('node-1', { x: 200, y: 200 }, 2000);

        // Both should converge to same state (B wins with timestamp 2000)
        expect(manager1.getNodePosition('node-1')).toEqual(manager2.getNodePosition('node-1'));
        expect(manager1.getNodePosition('node-1')).toEqual({ x: 200, y: 200 });
      });
    });

    describe('ABA Problem', () => {
      it('should handle node moving A->B->A', () => {
        // Node moves from position A to B, then back to A
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000); // A
        manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 2000); // B
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 3000); // A again

        // Final position should be A (at timestamp 3000)
        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
      });

      it('should reject stale A after A->B->A sequence', () => {
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 1000); // A
        manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 2000); // B
        manager.handleRemoteChange('node-1', { x: 100, y: 100 }, 3000); // A again

        // Late-arriving message for position B at T=1500 should be rejected
        const result = manager.handleRemoteChange('node-1', { x: 200, y: 200 }, 1500);
        expect(result.shouldApply).toBe(false);
        expect(manager.getNodePosition('node-1')).toEqual({ x: 100, y: 100 });
      });
    });

    describe('Acknowledge Edge Cases', () => {
      it('should handle acknowledging non-existent node', () => {
        manager.setConnected();
        manager.recordLocalChange('node-1', { x: 100, y: 100 });

        // Acknowledge non-existent node - should not crash
        manager.acknowledgeChange('non-existent');

        // Original pending change should still exist
        expect(manager.hasPendingChanges()).toBe(true);
      });

      it('should handle acknowledging node with no pending changes', () => {
        // No pending changes at all
        manager.acknowledgeChange('node-1');

        expect(manager.hasPendingChanges()).toBe(false);
      });

      it('should handle acknowledging during reconnection flow', () => {
        manager.setConnected();
        manager.recordLocalChange('node-1', { x: 100, y: 100 });

        // Acknowledge before reconnect
        manager.acknowledgeChange('node-1');

        const serverNodes = [
          { id: 'node-1', position: { x: 50, y: 50 }, data: {} },
        ];

        const changes = manager.onReconnect(serverNodes as any);

        // No changes to reapply (already acknowledged)
        expect(changes).toHaveLength(0);
      });
    });

    describe('Singleton Behavior', () => {
      it('should return same instance from getDocumentStateManager', async () => {
        const { getDocumentStateManager } = await import('./documentStateManager');

        const instance1 = getDocumentStateManager();
        const instance2 = getDocumentStateManager();

        expect(instance1).toBe(instance2);
      });
    });
  });
});
