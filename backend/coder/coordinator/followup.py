"""Explicit notification choices for resumed turns, separate from doing work.

The model can finish useful background work silently. Recordings for a direct
request are attached by the delivery layer, never dependent on model phrasing.
"""
from dataclasses import dataclass


@dataclass
class FollowupReply:
    text: str
    delivery: dict


class FollowupDelivery:
    def __init__(self, event, *, parent=None):
        self.event = event
        self.internal = event["source"] == "signal"
        self.background = event["source"] in ("alarm", "signal") or event["context"].get("origin") == "background"
        self.artifact_only = event["payload"].get("operation") == "call_recording"
        previous = (parent or {}).get("payload", {}).get("delivery", {})
        self.notify = previous.get("notify", True)
        self.include_recordings = previous.get("include_recordings", not self.background)
        self.reason = ""

    @staticmethod
    def tool_param():
        return {"type": "function", "function": {
            "name": "set_followup_delivery",
            "description": "Choose delivery for this completion only; does not cancel work or change future preferences. "
                "For routine scheduled, bulk or delegated work, set notify=false when the owner needs no update. "
                "Direct one-off call requests default to sending the outcome and recording. "
                "Use include_recordings=false to omit audio, or true to attach available recordings automatically. "
                "A late recording sends only audio, never another call summary. Honor the owner's latest preferences.",
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

    def delivery_instructions(self):
        if self.internal:
            return (
                "Your final reply is only a note in the coordinator's web conversation. To deliver a message "
                "elsewhere or take another action, use your available tools according to the owner's "
                "instructions and the preferences in the incoming message. Mentioning a destination in your "
                "final reply does not send it there. set_followup_delivery controls only the web note."
            )
        channel = self.event["context"].get("channel", "the requesting channel")
        return (f"Your final reply is automatically delivered to {channel}; "
                "do not use message_owner to send a duplicate to that channel. Use your available tools "
                "for any separately requested delivery or action.")

    def decision(self):
        return {"notify": self.notify, "include_recordings": self.include_recordings, "reason": self.reason}

    def instructions(self):
        text = self.delivery_instructions() + (" Delivery is separate from completing work: set_followup_delivery can omit a notification "
                "without cancelling actions or future alarms. For scheduled, bulk or subagent work, decide whether "
                "the owner needs a summary or audio; routine success may stay silent. For a direct one-off call, "
                "give one concise outcome; the runtime attaches its recording by default when available. "
                "Do not embed the call recording yourself or promise another summary when it arrives. "
                "These are defaults; respect newer user instructions and memories.")
        text += f" Current defaults: notify={self.notify}, include_recordings={self.include_recordings}."
        if self.artifact_only:
            text += (" This event adds only a recording to an already handled call. Do not summarize the call again "
                     "or say you already reported it. Delivery can contain only the recording (or its unavailability), "
                     "and may be omitted. The parent call's delivery choice is the default for this event.")
        return text

    def reply(self, text):
        payload = self.event["payload"]
        artifacts = [payload] if self.artifact_only else list(payload.get("artifacts", {}).values())
        recordings = [item for item in artifacts if item.get("operation") == "call_recording"]
        if not self.notify:
            return FollowupReply("", self.decision())
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
        return FollowupReply(text.strip(), self.decision())
