"""
Verified phone identity: the rules in utils/phone_identity.py, the E.164
normalizer, the feature gate, and the shared Twilio Verify client.

The service is exercised against an in-memory repository and a scripted
Verify service, so every branch — approval, wrong code, expiry, attempt caps,
send caps, a number another account holds live, rebinding — is judged on
what the service persists and returns, never on a mock being called.
"""

from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import pytest
import respx

from utils import feature_gates
from utils.feature_gates import FeatureNotAvailable, is_feature_enabled, require_feature
from utils.phone_identity import (
    CHALLENGE_TTL, MAX_CHECKS, MAX_PHONES_PER_ACCOUNT, MAX_STARTS_PER_NUMBER, MAX_STARTS_PER_USER,
    PhoneIdentity, PhoneLinkError,
)
from utils.phone_numbers import mask_e164, normalize_e164
from utils.twilio_verify import (
    PlatformVerify, TwilioVerifyError, check_verification, start_verification,
)

USER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
PHONE = "+14242421064"


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeRepo:
    """The two tables as dicts, with the same contracts as PhoneRepo."""

    def __init__(self):
        self.challenges = {}
        self.phones = {}  # (user_id, phone) -> row
        self.emails = {USER: "user@example.com", OTHER: "other@example.com"}
        self._seq = 0

    async def create_challenge(self, *, user_id, phone_e164, provider_sid, expires_at):
        for row in self.challenges.values():
            if row["user_id"] == user_id and row["status"] == "pending":
                row["status"] = "superseded"
        self._seq += 1
        row = {
            "id": f"ch-{self._seq}", "user_id": user_id, "phone_e164": phone_e164,
            "provider_sid": provider_sid, "status": "pending", "attempts": 0,
            "expires_at": expires_at, "created_at": datetime.now(timezone.utc),
            "consumed_at": None,
        }
        self.challenges[row["id"]] = row
        return dict(row)

    async def get_challenge(self, challenge_id, *, user_id):
        row = self.challenges.get(challenge_id)
        return dict(row) if row and row["user_id"] == user_id else None

    async def record_check(self, challenge_id, *, status, attempted=True, consumed=False):
        row = self.challenges[challenge_id]
        row["status"] = status
        row["attempts"] += 1 if attempted else 0
        if consumed:
            row["consumed_at"] = datetime.now(timezone.utc)

    async def count_starts(self, *, since, user_id=None, phone_e164=None):
        key, value = ("user_id", user_id) if user_id else ("phone_e164", phone_e164)
        return sum(1 for r in self.challenges.values() if r[key] == value and r["created_at"] >= since)

    def _live(self, user_id=None, phone_e164=None):
        return [r for r in self.phones.values() if r["unlinked_at"] is None
                and (user_id is None or r["user_id"] == user_id)
                and (phone_e164 is None or r["phone_e164"] == phone_e164)]

    async def list_active_phones(self, user_id):
        return [dict(r) for r in sorted(self._live(user_id=user_id), key=lambda r: r["verified_at"])]

    async def get_user_by_phone(self, phone_e164, conn=None):
        for row in self._live(phone_e164=phone_e164):
            return {"user_id": row["user_id"], "verified_at": row["verified_at"],
                    "link_version": row["link_version"], "source": row["source"]}
        return None

    async def consume_and_link(self, *, user_id, phone_e164, challenge_id):
        holder = await self.get_user_by_phone(phone_e164)
        if holder and holder["user_id"] != user_id:
            raise asyncpg.UniqueViolationError("user_phones_active_phone_idx")
        challenge = self.challenges[challenge_id]
        challenge.update(status="approved", attempts=challenge["attempts"] + 1,
                         consumed_at=datetime.now(timezone.utc))
        existing = self.phones.get((user_id, phone_e164))
        row = {
            "user_id": user_id, "phone_e164": phone_e164, "verified_at": datetime.now(timezone.utc),
            "unlinked_at": None, "challenge_id": challenge_id, "source": "verify", "last_seen_at": None,
            "link_version": (existing["link_version"] + 1) if existing else 1,
        }
        self.phones[(user_id, phone_e164)] = row
        return {k: row[k] for k in ("phone_e164", "verified_at", "link_version", "source")}

    async def account_email(self, user_id):
        return self.emails.get(user_id)

    async def unlink(self, user_id, phone_e164):
        row = self.phones.get((user_id, phone_e164))
        if not row or row["unlinked_at"] is not None:
            return False
        row["unlinked_at"] = datetime.now(timezone.utc)
        return True


class FakeVerify:
    """Scripted Twilio Verify: the code that approves, or an error to raise."""

    def __init__(self, good_code="123456", start_error=None, check_error=None):
        self.good_code = good_code
        self.start_error = start_error
        self.check_error = check_error
        self.started = []
        self.checked = []

    async def start(self, to):
        if self.start_error:
            raise self.start_error
        self.started.append(to)
        return f"VE{len(self.started):030d}"

    async def check(self, verification_sid, code):
        self.checked.append((verification_sid, code))
        if self.check_error:
            raise self.check_error
        return "approved" if code == self.good_code else "pending"


def service(verify=None, repo=None):
    return PhoneIdentity(repo or FakeRepo(), FakeVerify() if verify is None else verify)


async def link(svc, user=USER, phone=PHONE, code="123456"):
    started = await svc.start_link(user, phone)
    return await svc.check_link(user, started["challenge_id"], code)


# ── numbers and gate ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("+14242421064", "+14242421064"),
    ("+1 (424) 242-1064", "+14242421064"),
    ("0044 20 7946 0958", "+442079460958"),
    ("4242421064", None),          # no country code
    ("+0 123 4567", None),         # country codes never start with 0
    ("+1234", None),               # too short
    ("+1234567890123456", None),   # too long
    ("", None),
    (None, None),
])
def test_normalize_e164(raw, expected):
    assert normalize_e164(raw) == expected


def test_mask_keeps_country_and_last_four():
    assert mask_e164("+14242421064") == "+1••••••1064"
    assert mask_e164("+1234") == "+1234"


def test_feature_gate_internal_then_everyone(monkeypatch):
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_channel", feature_gates.INTERNAL)
    monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: email == "staff@example.com")
    assert is_feature_enabled("phone_channel", email="staff@example.com")
    assert not is_feature_enabled("phone_channel", email="customer@example.com")
    assert not is_feature_enabled("phone_channel", email=None)
    with pytest.raises(FeatureNotAvailable):
        require_feature("phone_channel", email="customer@example.com")
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_channel", feature_gates.EVERYONE)
    assert is_feature_enabled("phone_channel", email="customer@example.com")
    with pytest.raises(KeyError):
        is_feature_enabled("no_such_feature", email="staff@example.com")


# ── linking ──────────────────────────────────────────────────────────────────

async def test_link_requires_twilios_approval_and_binds_once():
    repo, verify = FakeRepo(), FakeVerify()
    svc = PhoneIdentity(repo, verify)
    assert await svc.status(USER) == {"configured": True, "max_phones": MAX_PHONES_PER_ACCOUNT, "phones": []}

    started = await svc.start_link(USER, "+1 (424) 242-1064")
    assert started["phone"] == PHONE and verify.started == [PHONE]
    expires = datetime.fromisoformat(started["expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(timezone.utc) <= CHALLENGE_TTL

    with pytest.raises(PhoneLinkError) as wrong:
        await svc.check_link(USER, started["challenge_id"], "000000")
    assert wrong.value.kind == "invalid_code"
    assert (await svc.status(USER))["phones"] == []
    assert repo.challenges[started["challenge_id"]]["attempts"] == 1

    linked = await svc.check_link(USER, started["challenge_id"], "123456")
    assert linked["phone"] == PHONE and linked["link_version"] == 1
    # The check is bound to the exact verification that was started.
    assert verify.checked[-1] == (f"VE{1:030d}", "123456")
    row = repo.phones[(USER, PHONE)]
    assert (await svc.status(USER))["phones"] == [
        {"phone": PHONE, "verified_at": row["verified_at"].isoformat(), "source": "verify"},
    ]
    assert await repo.get_user_by_phone(PHONE) == {
        "user_id": USER, "verified_at": row["verified_at"], "link_version": 1, "source": "verify",
    }

    # A consumed challenge cannot approve again.
    with pytest.raises(PhoneLinkError) as again:
        await svc.check_link(USER, started["challenge_id"], "123456")
    assert again.value.kind == "expired"


async def test_pending_result_and_bad_code_shapes_never_link():
    svc = service()
    started = await svc.start_link(USER, PHONE)
    for code in ("", "12", "abc123", "1234567890123"):
        with pytest.raises(PhoneLinkError) as exc:
            await svc.check_link(USER, started["challenge_id"], code)
        assert exc.value.kind == "invalid_code"
    assert (await svc.status(USER))["phones"] == []
    # Nothing malformed ever reached the provider.
    assert svc.verify.checked == []


async def test_challenge_is_bound_to_its_user():
    repo = FakeRepo()
    svc = PhoneIdentity(repo, FakeVerify())
    started = await svc.start_link(USER, PHONE)
    with pytest.raises(PhoneLinkError) as exc:
        await svc.check_link(OTHER, started["challenge_id"], "123456")
    assert exc.value.kind == "expired"
    assert repo.phones == {}


async def test_expired_challenge_is_refused_without_a_provider_call():
    repo, verify = FakeRepo(), FakeVerify()
    svc = PhoneIdentity(repo, verify)
    started = await svc.start_link(USER, PHONE)
    repo.challenges[started["challenge_id"]]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(PhoneLinkError) as exc:
        await svc.check_link(USER, started["challenge_id"], "123456")
    assert exc.value.kind == "expired"
    assert repo.challenges[started["challenge_id"]]["status"] == "expired"
    assert verify.checked == []


async def test_provider_says_expired_or_exhausted():
    for code, kind, status in ((20404, "expired", "expired"), (60202, "too_many_checks", "failed")):
        repo = FakeRepo()
        svc = PhoneIdentity(repo, FakeVerify(check_error=TwilioVerifyError("nope", code=code, status=404)))
        started = await svc.start_link(USER, PHONE)
        with pytest.raises(PhoneLinkError) as exc:
            await svc.check_link(USER, started["challenge_id"], "123456")
        assert exc.value.kind == kind
        assert repo.challenges[started["challenge_id"]]["status"] == status


async def test_check_attempts_are_capped_before_the_provider_is():
    repo, verify = FakeRepo(), FakeVerify()
    svc = PhoneIdentity(repo, verify)
    started = await svc.start_link(USER, PHONE)
    for _ in range(MAX_CHECKS):
        with pytest.raises(PhoneLinkError):
            await svc.check_link(USER, started["challenge_id"], "000000")
    with pytest.raises(PhoneLinkError) as exc:
        await svc.check_link(USER, started["challenge_id"], "123456")
    assert exc.value.kind == "too_many_checks"
    assert len(verify.checked) == MAX_CHECKS
    assert repo.challenges[started["challenge_id"]]["status"] == "failed"


async def test_send_caps_per_user_and_per_number():
    repo = FakeRepo()
    svc = PhoneIdentity(repo, FakeVerify())
    for _ in range(MAX_STARTS_PER_USER):
        await svc.start_link(USER, PHONE)
    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link(USER, "+14242421065")
    assert exc.value.kind == "too_many_sends"
    # Only the newest challenge stays pending.
    pending = [c for c in repo.challenges.values() if c["status"] == "pending"]
    assert len(pending) == 1

    # The same number from other accounts is capped too.
    for i in range(MAX_STARTS_PER_NUMBER - MAX_STARTS_PER_USER):
        await svc.start_link(f"user-{i}", PHONE)
    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link("user-fresh", PHONE)
    assert exc.value.kind == "too_many_sends"
    assert (await svc.start_link("user-fresh", "+14242421066"))["phone"] == "+14242421066"


async def test_number_held_by_another_account_is_disclosed_only_after_possession():
    repo = FakeRepo()
    svc = PhoneIdentity(repo, FakeVerify())
    await link(svc, user=OTHER)
    started = await svc.start_link(USER, PHONE)  # starting never reveals the holder
    with pytest.raises(PhoneLinkError) as exc:
        await svc.check_link(USER, started["challenge_id"], "123456")
    assert exc.value.kind == "linked_elsewhere"
    assert repo.challenges[started["challenge_id"]]["status"] == "conflict"
    assert (await svc.status(USER))["phones"] == []
    assert (await repo.get_user_by_phone(PHONE))["user_id"] == OTHER


async def test_unlink_frees_the_number_and_relink_bumps_the_version():
    repo = FakeRepo()
    svc = PhoneIdentity(repo, FakeVerify())
    await link(svc)
    assert await svc.unlink(USER, PHONE) is True
    with pytest.raises(PhoneLinkError) as exc:
        await svc.unlink(USER, PHONE)
    assert exc.value.kind == "not_linked"
    assert (await svc.status(USER))["phones"] == []
    assert await repo.get_user_by_phone(PHONE) is None

    # Another account can now take it; the first relinking it later bumps its row.
    other = await link(svc, user=OTHER)
    assert other["link_version"] == 1
    await svc.unlink(OTHER, PHONE)
    relinked = await link(svc)
    assert relinked["link_version"] == 2
    assert (await repo.get_user_by_phone(PHONE))["user_id"] == USER


async def test_an_account_holds_several_numbers_each_reaching_it():
    repo = FakeRepo()
    svc = PhoneIdentity(repo, FakeVerify())
    numbers = [f"+1424242{1000 + i}" for i in range(MAX_PHONES_PER_ACCOUNT)]
    for number in numbers:
        # One more challenge than the per-user send cap allows in a window.
        for row in repo.challenges.values():
            row["created_at"] -= CHALLENGE_TTL
        await link(svc, phone=number)
    assert [p["phone"] for p in (await svc.status(USER))["phones"]] == numbers
    assert {(await repo.get_user_by_phone(n))["user_id"] for n in numbers} == {USER}

    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link(USER, "+14242429999")
    assert exc.value.kind == "too_many_phones"
    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link(USER, numbers[0])
    assert exc.value.kind == "already_linked"

    # Unlinking one leaves the others working.
    await svc.unlink(USER, numbers[0])
    assert await repo.get_user_by_phone(numbers[0]) is None
    assert (await repo.get_user_by_phone(numbers[1]))["user_id"] == USER


async def test_a_phone_only_account_keeps_its_last_way_in():
    repo = FakeRepo()
    repo.emails.pop(USER)
    svc = PhoneIdentity(repo, FakeVerify())
    await link(svc)
    await link(svc, phone="+14242421099")
    assert await svc.unlink(USER, "+14242421099") is True
    with pytest.raises(PhoneLinkError) as exc:
        await svc.unlink(USER, PHONE)
    assert exc.value.kind == "last_way_in"
    assert (await repo.get_user_by_phone(PHONE))["user_id"] == USER


async def test_unconfigured_instance_and_bad_numbers_fail_before_the_provider():
    svc = PhoneIdentity(FakeRepo(), None)
    assert (await svc.status(USER))["configured"] is False
    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link(USER, PHONE)
    assert exc.value.kind == "not_configured"

    verify = FakeVerify()
    svc = PhoneIdentity(FakeRepo(), verify)
    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link(USER, "4242421064")
    assert exc.value.kind == "invalid_number" and verify.started == []


async def test_provider_errors_map_to_user_facing_kinds():
    for code, kind in ((60200, "invalid_number"), (60203, "too_many_sends"), (20429, "rate_limited")):
        svc = PhoneIdentity(FakeRepo(), FakeVerify(start_error=TwilioVerifyError("x", code=code, status=400)))
        with pytest.raises(PhoneLinkError) as exc:
            await svc.start_link(USER, PHONE)
        assert exc.value.kind == kind
    svc = PhoneIdentity(FakeRepo(), FakeVerify(start_error=TwilioVerifyError("Twilio Verify error: boom", status=500)))
    with pytest.raises(PhoneLinkError) as exc:
        await svc.start_link(USER, PHONE)
    assert exc.value.kind == "provider" and "boom" in str(exc.value)


# ── the shared Twilio Verify client ──────────────────────────────────────────

@respx.mock
async def test_verify_client_sends_the_documented_requests_and_surfaces_errors():
    auth = ("ACxxxxxxxx", "token")
    start = respx.post("https://verify.twilio.com/v2/Services/VAsvc/Verifications").mock(
        return_value=httpx.Response(201, json={"sid": "VE1", "status": "pending"}))
    check = respx.post("https://verify.twilio.com/v2/Services/VAsvc/VerificationCheck").mock(
        return_value=httpx.Response(200, json={"sid": "VE1", "status": "approved", "valid": True}))

    assert (await start_verification(auth, "VAsvc", to=PHONE, locale="en"))["sid"] == "VE1"
    sent = start.calls.last.request
    assert sent.headers["authorization"].startswith("Basic ")
    assert dict(httpx.QueryParams(sent.content.decode())) == {"To": PHONE, "Channel": "sms", "Locale": "en"}

    result = await check_verification(auth, "VAsvc", code="123456", verification_sid="VE1")
    assert result["status"] == "approved"
    assert dict(httpx.QueryParams(check.calls.last.request.content.decode())) == {"Code": "123456", "VerificationSid": "VE1"}
    with pytest.raises(ValueError):
        await check_verification(auth, "VAsvc", code="123456")

    start.mock(return_value=httpx.Response(429, json={"code": 20429, "message": "Too many requests", "status": 429}))
    with pytest.raises(TwilioVerifyError) as exc:
        await start_verification(auth, "VAsvc", to=PHONE)
    assert exc.value.kind == "rate_limited" and exc.value.code == 20429 and "Too many requests" in str(exc.value)

    start.mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(TwilioVerifyError) as exc:
        await start_verification(auth, "VAsvc", to=PHONE)
    assert exc.value.kind == "provider" and "unreachable" in str(exc.value)


def test_platform_verify_needs_all_three_env_vars(monkeypatch):
    for name in PlatformVerify.ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert PlatformVerify.from_env() is None and not PlatformVerify.is_configured()
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    assert PlatformVerify.from_env() is None
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA1")
    assert PlatformVerify.is_configured()
