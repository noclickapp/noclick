"""Who is on a socket: the user id and the auth email the session carries."""

from typing import Optional, Tuple


async def session_actor(sio, sid: str) -> Optional[Tuple[str, Optional[str]]]:
    session = await sio.get_session(sid)
    user_id = session.get("user_id") if session else None
    if not user_id:
        return None
    user_data = session.get("user_data") or {}
    return user_id, user_data.get("email")
