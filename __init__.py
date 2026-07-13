"""Anki add-on entrypoint for Contextual Spaced Repetition."""

try:
    from .contextual_review import setup
except ImportError:  # pragma: no cover - direct import during local test discovery
    from contextual_review import setup

setup(__name__)
