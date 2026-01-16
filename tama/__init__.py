"""
Terminal Tamagotchi

A terminal-based Tamagotchi-inspired virtual pet with classic evolution mechanics,
stat management, and optional AI personality powered by local Ollama models.
"""

__version__ = "1.0.0"

from .pet import Pet
from .ui import UI
from .__main__ import main

__all__ = ["Pet", "UI", "main", "__version__"]
