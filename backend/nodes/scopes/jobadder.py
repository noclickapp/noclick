"""Endpoint scope requirements from JobAdder's published v2 contract.

https://api.jobadder.com/v2/openapi.json (security and Getting Started/Scopes).
Each requirement preserves the complete security-scope set in the pinned contract.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

JOBADDER_SCOPES = ScopeRegistry(
    provider="jobadder",
    requirements={
        "get_current_user": ScopeRequirement(scopes=('read', 'read_user')),
        "list_candidates": ScopeRequirement(scopes=('read', 'read_candidate')),
        "get_candidate": ScopeRequirement(scopes=('read', 'read_candidate')),
        "create_candidate": ScopeRequirement(scopes=('write', 'write_candidate')),
        "update_candidate": ScopeRequirement(scopes=('write', 'write_candidate')),
        "list_companies": ScopeRequirement(scopes=('read', 'read_company')),
        "get_company": ScopeRequirement(scopes=('read', 'read_company')),
        "create_company": ScopeRequirement(scopes=('write', 'write_company')),
        "update_company": ScopeRequirement(scopes=('write', 'write_company')),
        "list_contacts": ScopeRequirement(scopes=('read', 'read_contact')),
        "get_contact": ScopeRequirement(scopes=('read', 'read_contact')),
        "create_contact": ScopeRequirement(scopes=('write', 'write_contact')),
        "update_contact": ScopeRequirement(scopes=('write', 'write_contact')),
        "list_jobs": ScopeRequirement(scopes=('read', 'read_job')),
        "get_job": ScopeRequirement(scopes=('read', 'read_job')),
        "create_job": ScopeRequirement(scopes=('write', 'write_job')),
        "update_job": ScopeRequirement(scopes=('write', 'write_job')),
        "list_placements": ScopeRequirement(scopes=('read', 'read_placement')),
        "get_placement": ScopeRequirement(scopes=('read', 'read_placement')),
        "list_candidate_notes": ScopeRequirement(scopes=('read', 'read_note', 'read_candidate_note')),
        "create_candidate_note": ScopeRequirement(scopes=('write', 'write_note', 'write_candidate_note')),
        "list_job_applications": ScopeRequirement(scopes=('read', 'read_jobapplication')),
        "add_candidates_to_job": ScopeRequirement(scopes=('write', 'write_jobapplication')),
    },
    extra_scopes={"default": ("offline_access",)},
)
