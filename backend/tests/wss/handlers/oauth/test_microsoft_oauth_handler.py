from unittest.mock import AsyncMock

from wss.handlers.oauth.microsoft_oauth_handler import MicrosoftOAuthHandler

OUTLOOK_MERGED_SCOPES = [
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/Contacts.ReadWrite",
]


def _handler():
    return MicrosoftOAuthHandler(AsyncMock())


def test_mail_plus_calendar_scopes_map_to_outlook():
    # The Outlook node owns Mail + Calendar + Contacts after the calendar merge;
    # a credential carrying calendar scopes must NOT resolve to the orphaned
    # microsoft_calendar_oauth type (which no node lists), or the credential
    # silently disappears from the Outlook node's credential picker.
    assert _handler()._get_credential_type_from_scopes(OUTLOOK_MERGED_SCOPES) == "microsoft_outlook_oauth"


def test_calendar_only_scopes_map_to_outlook():
    assert _handler()._get_credential_type_from_scopes(
        ["https://graph.microsoft.com/Calendars.ReadWrite"]
    ) == "microsoft_outlook_oauth"


def test_generic_microsoft_name_with_calendar_scopes_maps_to_outlook():
    # The OAuthConnectForm sends the provider display name ("Microsoft - <date>"),
    # which has no service keyword, so resolution falls back to scopes.
    assert _handler()._get_credential_type_from_name(
        "Microsoft - 7/10/2026", OUTLOOK_MERGED_SCOPES
    ) == "microsoft_outlook_oauth"


def test_outlook_name_maps_to_outlook():
    assert _handler()._get_credential_type_from_name("OutlookOAuth - 7/10/2026", []) == "microsoft_outlook_oauth"


def test_calendar_name_maps_to_outlook():
    assert _handler()._get_credential_type_from_name("CalendarOAuth - 7/10/2026", []) == "microsoft_outlook_oauth"


def test_excel_scopes_unaffected():
    assert _handler()._get_credential_type_from_scopes(
        ["https://graph.microsoft.com/Files.ReadWrite"]
    ) == "microsoft_excel_oauth"


def test_teams_scopes_unaffected():
    assert _handler()._get_credential_type_from_scopes(
        ["https://graph.microsoft.com/Channel.ReadBasic.All"]
    ) == "microsoft_teams_oauth"


# Regression (2026-07-27): Word/Excel/OneDrive request IDENTICAL scopes
# (Files.ReadWrite.All), so the credential NAME is the only discriminator. A
# humanized label inserts spaces ("One Drive OAuth"), which must still match
# the compound keyword — otherwise OneDrive/OneLake fell through to the excel
# scope-match and collided with an existing credential ("limit reached").
_FILES = ["https://graph.microsoft.com/Files.ReadWrite.All"]


def test_word_name_beats_identical_files_scope():
    assert _handler()._get_credential_type_from_name(
        "Word OAuth - 7/27/2026", _FILES
    ) == "microsoft_word_oauth"


def test_humanized_onedrive_name_maps_to_onedrive_not_excel():
    assert _handler()._get_credential_type_from_name(
        "One Drive OAuth - 7/27/2026", _FILES
    ) == "microsoft_onedrive_oauth"


def test_humanized_onelake_name_maps_to_onelake():
    assert _handler()._get_credential_type_from_name(
        "One Lake OAuth - 7/27/2026", []
    ) == "microsoft_onelake_oauth"


def test_humanized_todo_name_maps_to_todo():
    assert _handler()._get_credential_type_from_name(
        "Microsoft Todo OAuth - 7/27/2026", []
    ) == "microsoft_todo_oauth"


def test_onelake_not_shadowed_by_onedrive():
    # 'onedrive' and 'onelake' share no substring, but pin the ordering anyway.
    assert _handler()._get_credential_type_from_name("OneLakeOAuth", []) == "microsoft_onelake_oauth"
    assert _handler()._get_credential_type_from_name("OneDriveOAuth", []) == "microsoft_onedrive_oauth"
