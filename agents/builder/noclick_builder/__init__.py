"""NoClick's workflow builder: an agent that builds workflows with NoClick's own API.

``definition`` is what the agent is (its name, tools, instructions and the messages it's sent), with no dependency.
``agent`` makes and runs it with the SDK (``pip install noclick``); it's imported only when you use it.
"""

from . import definition

__all__ = ["definition"]
