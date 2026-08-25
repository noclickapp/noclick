// Side panel shown next to auth forms when arriving from a hosted-cloud
// agent landing page. Those pages don't exist in this build, so this renders
// nothing (login/register pass agentName only when the query param is set).

export function AgentScaffoldAuthPanel(_props: { agentName: string }) {
    return null;
}
