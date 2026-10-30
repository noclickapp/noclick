"""Explicit notification choices for resumed turns, separate from doing work.

The model can finish useful background work silently. Recordings for a direct
request are attached by the delivery layer, never dependent on model phrasing.
"""
from dataclasses import dataclass, field

from utils.prompts import PromptPack

PROMPTS = PromptPack("coordinator")
TOOL_PROMPTS = PromptPack("coordinator_tools")


@dataclass
class FollowupReply:
    text: str
    delivery: dict
    # The turn's tool calls, as a saved chat event keeps them: its note carries them.
    tool_calls: list = field(default_factory=list)


class FollowupDelivery:
    def __init__(self, event, *, parent=None, channel=None, held=None):
        """``channel``: what the turn runs as; ``held``: why a reply meant for the owner's phone isn't texted."""
        self.event = event
        self.channel = channel or event["context"].get("channel")
        self.held = held
        self.background = event["source"] in ("alarm", "signal") or event["context"].get("origin") == "background"
        # Its reply is only a note in the web conversation: a signal's, and background work's or a held text's
        # there, so the turn reaches the owner with its tools only when they need it.
        on_web = (self.channel or "web") == "web"
        self.internal = event["source"] == "signal" or (on_web and (self.background or bool(held)))
        self.artifact_only = event["payload"].get("operation") == "call_recording"
        previous = (parent or {}).get("payload", {}).get("delivery", {})
        self.notify = previous.get("notify", True)
        self.include_recordings = previous.get("include_recordings", not self.background)
        self.reason = ""
        self.notes = []

    @staticmethod
    def tool_param():
        return {"type": "function", "function": {
            "name": "set_followup_delivery",
            "description": TOOL_PROMPTS.DESCRIPTIONS["set_followup_delivery"],
            "parameters": {"type": "object", "properties": {
                "notify": {"type": "boolean"}, "include_recordings": {"type": "boolean"},
                "reason": {"type": "string", "maxLength": 500},
            }, "required": ["notify", "include_recordings", "reason"], "additionalProperties": False},
        }}

    async def choose(self, notify: bool, include_recordings: bool, reason: str):
        if type(notify) is not bool or type(include_recordings) is not bool or not isinstance(reason, str):
            raise ValueError("Provide boolean notification choices and a reason.")
        self.notify, self.include_recordings, self.reason = notify, include_recordings, reason[:500]
        return {"success": True, **self.decision(), "note": self.delivery_instructions()}

    def note(self, text, *, held=None):
        """A message to the web conversation from a turn whose reply is only a note there is that note; ``held``
        says why a text became it."""
        self.notes.append(text)
        note = "Posted as this turn's note in the owner's web conversation, in place of your final reply."
        return {"success": True, "channel": "web", "note": f"{note} Not texted: {held}." if held else note}

    def delivery_instructions(self):
        context = {**self.event["context"], "channel": self.channel} if self.channel else self.event["context"]
        return PROMPTS.followup_delivery(internal=self.internal, context=context, held=self.held)

    def decision(self):
        return {"notify": self.notify, "include_recordings": self.include_recordings, "reason": self.reason}

    def instructions(self):
        return PROMPTS.followup_instructions(self.delivery_instructions(), notify=self.notify,
                                             include_recordings=self.include_recordings,
                                             artifact_only=self.artifact_only)

    def reply(self, text, tool_calls=()):
        tool_calls = list(tool_calls)
        if self.notes:
            # Its closing line would only repeat what it told the owner.
            return FollowupReply("\n\n".join(self.notes), {**self.decision(), "notify": True}, tool_calls)
        payload = self.event["payload"]
        artifacts = [payload] if self.artifact_only else list(payload.get("artifacts", {}).values())
        recordings = [item for item in artifacts if item.get("operation") == "call_recording"]
        if not self.notify:
            return FollowupReply("", self.decision(), tool_calls)
        # Artifact turns cannot produce a second recap, even if the model does.
        if self.artifact_only:
            text = ""
        for item in recordings:
            url = (item.get("recording") or {}).get("download_url")
            # Remove model-authored copies before applying the structured choice.
            if url:
                import re
                text = re.sub(r"!?\[[^\]]*\]\(" + re.escape(url) + r"\)", "", text).replace(url, "").strip()
            if self.include_recordings:
                if item.get("status") == "available" and url:
                    text += ("\n\n" if text else "") + f"![Call recording]({url})"
                elif item.get("status") == "unavailable":
                    text += ("\n\n" if text else "") + "The call recording couldn't be retrieved."
        return FollowupReply(text.strip(), self.decision(), tool_calls)
