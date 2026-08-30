"""Instance provider keys: the allowlist, env-first precedence, and rotation.

The store exists so the builder can ask for its key inline and have it take
effect immediately. Two things must therefore hold: a saved key never shadows
an operator's environment, and a re-saved key replaces the value this process
applied earlier rather than waiting for a restart.
"""

import os

import pytest

from utils import instance_provider_keys as keys


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(os.environ):
        if name in keys.SUPPORTED_ENV_VARS or name.startswith(keys._TAG_PREFIX):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NOCLICK_LOCAL", "1")


class FakePool:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []

    async def fetch(self, *_a, **_k):
        return self.rows

    async def execute(self, *args, **_k):
        self.executed.append(args)
        return "OK"


class PlainCrypto:
    def encrypt_credential(self, data):
        return "enc:" + data["value"]

    def decrypt_credential(self, blob):
        return {"value": blob[len("enc:"):]}


@pytest.fixture(autouse=True)
def plain_crypto(monkeypatch):
    monkeypatch.setattr(keys, "get_encryption", lambda: PlainCrypto())


@pytest.fixture(autouse=True)
def no_live_probe(monkeypatch):
    async def allow(env_var, key):
        return None
    monkeypatch.setattr(keys, "validate_provider_key", allow)


@pytest.mark.asyncio
async def test_a_key_the_provider_rejects_is_never_stored(monkeypatch):
    from nodes.agent.key_validation import Rejection

    async def reject(env_var, key):
        return Rejection("openrouter", "invalid_key", '{"error":{"message":"User not found.","code":401}}')
    monkeypatch.setattr(keys, "validate_provider_key", reject)
    pool = FakePool()
    with pytest.raises(ValueError, match=r"OpenRouter rejected this key\. Check it or create a new one at https://openrouter\.ai") as err:
        await keys.set_key(pool, "OPENROUTER_API_KEY", "sk-or-dead", "user-1")
    assert "agent" not in str(err.value), "the settings form is not an agent node"
    assert "User not found." in str(err.value) and '{"error"' not in str(err.value), "the provider's sentence, not its JSON"
    assert pool.executed == [], "the provider's verdict lands in the form; nothing is written"


def test_allowlist_is_the_runtimes_provider_keys():
    assert "OPENROUTER_API_KEY" in keys.SUPPORTED_ENV_VARS
    assert "OPENAI_API_KEY" in keys.SUPPORTED_ENV_VARS
    assert "PATH" not in keys.SUPPORTED_ENV_VARS


@pytest.mark.asyncio
async def test_set_rejects_names_outside_the_allowlist_before_touching_the_store():
    pool = FakePool()
    with pytest.raises(ValueError):
        await keys.set_key(pool, "PATH", "/tmp", None)
    with pytest.raises(ValueError):
        await keys.set_key(pool, "OPENROUTER_API_KEY", "   ", None)
    assert pool.executed == []


@pytest.mark.asyncio
async def test_set_stores_encrypted_and_applies_immediately():
    pool = FakePool()

    async def fetch(*_a, **_k):
        return [{"env_var": "OPENROUTER_API_KEY", "value_encrypted": "enc:sk-or-1"}]

    pool.fetch = fetch
    await keys.set_key(pool, "OPENROUTER_API_KEY", " sk-or-1 ", "user-1")

    assert pool.executed[0][2] == "enc:sk-or-1", "the value is written encrypted, stripped"
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-1"
    assert os.environ[f"{keys._TAG_PREFIX}OPENROUTER_API_KEY"] == "1"


@pytest.mark.asyncio
async def test_apply_never_overwrites_a_real_env_var(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-the-environment")
    await keys.apply_to_environment(FakePool([{"env_var": "OPENROUTER_API_KEY", "value_encrypted": "enc:from-db"}]))
    assert os.environ["OPENROUTER_API_KEY"] == "from-the-environment"
    assert keys.env_configured() == ["OPENROUTER_API_KEY"]


@pytest.mark.asyncio
async def test_a_rotated_key_replaces_the_value_this_process_applied():
    await keys.apply_to_environment(FakePool([{"env_var": "OPENAI_API_KEY", "value_encrypted": "enc:old"}]))
    assert os.environ["OPENAI_API_KEY"] == "old"

    await keys.apply_to_environment(FakePool([{"env_var": "OPENAI_API_KEY", "value_encrypted": "enc:new"}]))
    assert os.environ["OPENAI_API_KEY"] == "new", "a saved key must take effect without a restart"
    assert keys.env_configured() == [], "a database-applied value is not environment-configured"


@pytest.mark.asyncio
async def test_delete_reclaims_only_what_it_applied(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-the-environment")
    await keys.apply_to_environment(FakePool([{"env_var": "OPENROUTER_API_KEY", "value_encrypted": "enc:db"}]))

    await keys.delete_key(FakePool(), "OPENROUTER_API_KEY")
    await keys.delete_key(FakePool(), "OPENAI_API_KEY")

    assert "OPENROUTER_API_KEY" not in os.environ
    assert os.environ["OPENAI_API_KEY"] == "from-the-environment"


@pytest.mark.asyncio
async def test_apply_is_inert_on_hosted(monkeypatch):
    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
    assert await keys.apply_to_environment(FakePool([{"env_var": "OPENROUTER_API_KEY", "value_encrypted": "enc:db"}])) == 0
    assert "OPENROUTER_API_KEY" not in os.environ


def test_the_instance_also_holds_service_keys():
    assert "WAHOOKS_API_KEY" in keys.SUPPORTED_ENV_VARS


@pytest.mark.asyncio
async def test_a_wahooks_key_is_probed_with_the_sdk(monkeypatch):
    from nodes.agent import key_validation as kv
    from wahooks import WAHooksError

    def rejected(key):
        raise WAHooksError("Unauthorized", 401)

    monkeypatch.setattr(kv, "_wahooks_list_connections", rejected)
    verdict = await kv.validate_provider_key("WAHOOKS_API_KEY", "wah-dead")
    assert verdict and verdict.provider == "wahooks" and verdict.kind == "invalid_key"
    assert "WAHooks rejected this key" in verdict.message("instance")

    def outage(key):
        raise WAHooksError("Bad gateway", 502)

    monkeypatch.setattr(kv, "_wahooks_list_connections", outage)
    assert await kv.validate_provider_key("WAHOOKS_API_KEY", "wah-maybe") is None, "an outage is not a verdict"


class FakeSmtpServer:
    """Accepts one login; every other credential is refused with the server's words."""

    def __init__(self, host, port, timeout=None, context=None):
        if host != "smtp.example.com":
            raise OSError("Name or service not known")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return False

    def login(self, user, password):
        import smtplib

        if (user, password) != ("mailer", "hunter2"):
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication credentials invalid")


@pytest.fixture
def smtp_server(monkeypatch):
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtpServer)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtpServer)


@pytest.mark.asyncio
async def test_smtp_settings_are_stored_only_after_the_server_accepts_the_login(smtp_server):
    pool = FakePool()
    await keys.set_smtp(pool, keys.SmtpSettings("smtp.example.com", 587, "mailer", "hunter2", "NoClick <noclick@example.com>"), "u1")
    stored = {arg for args in pool.executed for arg in args if isinstance(arg, str)}
    assert {"SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "FROM_EMAIL"} <= stored
    # The port is stored as the string the environment will carry.
    assert "enc:587" in stored


@pytest.mark.asyncio
async def test_smtp_rejections_carry_the_servers_words(smtp_server):
    pool = FakePool()
    with pytest.raises(ValueError, match="rejected the login: 5.7.8 Authentication credentials invalid"):
        await keys.set_smtp(pool, keys.SmtpSettings("smtp.example.com", 587, "mailer", "wrong", "a@b.co"), "u1")
    with pytest.raises(ValueError, match="Could not connect to smtp.nowhere.test:587"):
        await keys.set_smtp(pool, keys.SmtpSettings("smtp.nowhere.test", 587, "", "", "a@b.co"), "u1")
    with pytest.raises(ValueError, match="Enter the sender as an address"):
        await keys.set_smtp(pool, keys.SmtpSettings("smtp.example.com", 587, "", "", "not-an-address"), "u1")
    assert "SMTP_HOST" not in os.environ and pool.executed == []
