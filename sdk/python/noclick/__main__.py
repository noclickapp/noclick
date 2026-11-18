"""``python -m noclick``: the same as the ``noclick`` command."""

import sys

from .cli import main

sys.exit(main())
