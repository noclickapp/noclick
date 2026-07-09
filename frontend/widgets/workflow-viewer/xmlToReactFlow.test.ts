import { describe, it, expect } from 'vitest';
import { parseWorkflowXml, toReactFlowData } from './xmlToReactFlow';

// The widget consumes _workflow_to_xml output. These pin the two ways it must match
// the app canvas: provider→agent edges wire top→bottom, and config fields live under
// data.config (so config-nested node UI like the tools-count badge renders).
describe('xmlToReactFlow', () => {
    it('resolves type="tools" edges to top→bottom handles (provider→agent)', () => {
        const xml = `
            <node id="agent-1" type="agent" x="0" y="0" />
            <node id="slack-1" type="automation-slack" x="200" y="0" operation="send_message" />
            <edge from="slack-1" to="agent-1" type="tools" />
        `;
        const { edges } = toReactFlowData(parseWorkflowXml(xml));
        expect(edges).toHaveLength(1);
        expect(edges[0].source).toBe('slack-1');
        expect(edges[0].target).toBe('agent-1');
        expect(edges[0].sourceHandle).toBe('top');
        expect(edges[0].targetHandle).toBe('bottom');
        expect(edges[0].type).toBe('animated'); // renders via AnimatedWorkflowEdge
    });

    it('treats a legacy handle="top" edge as a provider edge too', () => {
        const xml = `
            <node id="a" type="automation-slack" x="0" y="0" />
            <node id="agent-1" type="agent" x="200" y="0" />
            <edge from="a" to="agent-1" handle="top" />
        `;
        const { edges } = toReactFlowData(parseWorkflowXml(xml));
        expect(edges[0].sourceHandle).toBe('top');
        expect(edges[0].targetHandle).toBe('bottom');
    });

    it('leaves a normal dataflow edge on default handles', () => {
        const xml = `
            <node id="a" type="automation-rss" x="0" y="0" />
            <node id="b" type="automation-slack" x="200" y="0" />
            <edge from="a" to="b" />
        `;
        const { edges } = toReactFlowData(parseWorkflowXml(xml));
        expect(edges[0].sourceHandle).toBeUndefined();
        expect(edges[0].targetHandle).toBeUndefined();
    });

    it('preserves an explicit source handle for multi-output nodes', () => {
        const xml = `
            <node id="sw" type="automation-switch" x="0" y="0" />
            <node id="b" type="automation-slack" x="200" y="0" />
            <edge from="sw" to="b" handle="case-1" />
        `;
        const { edges } = toReactFlowData(parseWorkflowXml(xml));
        expect(edges[0].sourceHandle).toBe('case-1');
        expect(edges[0].targetHandle).toBeUndefined();
    });

    it('populates data.config so config-nested reads work (the tools-count badge)', () => {
        const xml = `<node id="slack-1" type="automation-slack" x="0" y="0" operation="send_message" agent_tool_operations="[&quot;a&quot;,&quot;b&quot;,&quot;c&quot;]" />`;
        const { nodes } = toReactFlowData(parseWorkflowXml(xml));
        const data = nodes[0].data as Record<string, any>;
        // metadata read (top-level, flat) still works
        expect(data.operation).toBe('send_message');
        // config-nested read now works — this is what the badge counts
        expect(data.config.agent_tool_operations).toEqual(['a', 'b', 'c']);
    });
});
