"""Image-provider package.

Defines the shared :class:`ImageProvider` protocol (``images/base.py``) and
the concrete providers that implement it: OpenAI (``gpt-image-2``,
reference-portrait aware), Gemini (ref-aware for scenes), Z.AI (text-to-image
only), and Ollama (local, no refs). :mod:`images.provider_factory` builds and
routes them (with optional fallback) and :mod:`images.split_provider` splits
the scene/cover provider from the character-portrait provider. Cost lookup
lives in :mod:`images.pricing`.
"""
