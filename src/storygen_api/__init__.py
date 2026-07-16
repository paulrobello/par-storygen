"""FastAPI second composition root over the ``storygen`` pipeline/storage/llm layers.

Installs as the ``storygen-api`` console script (``[api]`` extra); binds
loopback by default and gates state-changing routes behind a bearer token.
"""

from __future__ import annotations
