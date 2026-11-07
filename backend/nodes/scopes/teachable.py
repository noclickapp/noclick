from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

ADMIN = ("list_courses", "get_course", "list_course_sections", "list_course_lectures", "list_course_enrollments", "get_user_enrollments", "get_course_progress", "get_lecture_completion", "list_users", "get_user", "create_student", "update_user_name", "enroll_user", "unenroll_user")
USER = ("get_current_user", "list_my_courses", "get_my_course", "get_my_progress", "get_my_course_completion")
TEACHABLE_SCOPES = ScopeRegistry(provider="teachable", requirements={
    "test_connection": ScopeRequirement(credential_types=("teachable_api_key", "teachable_supplied_oauth"), note="Protected Admin list or actual OAuth user read; school identity and plan are not inferred."),
    **{operation: ScopeRequirement(credential_types=("teachable_api_key",), note="Existing school Admin apiKey and provider permission/plan are required. Management writes must also be explicitly enabled on the saved credential.") for operation in ADMIN},
    **{operation: ScopeRequirement(scopes=("profile:read",) if operation == "get_current_user" else ("profile:read", "courses:read"), credential_types=("teachable_supplied_oauth",), note="Existing end-user OAuth only. Actual v2 products:read/courses:read and profile scope/plan permissions are enforced by Teachable; supplied scopes remain unknown, not requested or invented.") for operation in USER},
}, enforcement="strict")
