"""
Terminal Tamagotchi - Utilities and Constants

This module contains utility functions and constants used throughout the game.
"""

import locale
import os
import time

# Save file location
SAVE_PATH = os.path.join(os.path.expanduser("~"), ".tama_state.json")

# Set locale for better character support
locale.setlocale(locale.LC_ALL, "")

# Evolution stages
STAGES = ("egg", "baby", "child", "teen", "adult")

# Time in seconds for each stage (in game-time)
STAGE_SECONDS = {
    "egg": 60,            # 1m
    "baby": 20 * 60,      # 20m
    "child": 60 * 60,     # 1h
    "teen": 3 * 60 * 60,  # 3h
    "adult": 10**9,
}

# Neglect threshold for care mistakes (in game-seconds)
NEGLECT_THRESHOLD_S = 15 * 60  # classic-ish "ignored call" proxy


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value between lo and hi bounds."""
    return lo if value < lo else hi if value > hi else value


def now() -> float:
    """Get current time in seconds since epoch."""
    return time.time()


def fmt_age(seconds: int) -> str:
    """Format seconds into a human-readable age string (e.g., '5d 12h' or '3h 45m')."""
    if seconds < 0:
        seconds = 0
    minutes, s = divmod(seconds, 60)
    hours, m = divmod(minutes, 60)
    days, h = divmod(hours, 24)
    if days > 0:
        return f"{days}d {h:02d}h"
    if hours > 0:
        return f"{hours}h {m:02d}m"
    return f"{m}m {s:02d}s"
