"""
Terminal Tamagotchi - Persistence

This module handles saving and loading pet state to/from disk.
"""

import json
import os
from dataclasses import asdict
from dataclasses import fields as dataclass_fields
from typing import Optional

from .pet import Pet


def load_pet(path: str) -> Optional[Pet]:
    """
    Load a pet from a JSON save file.

    Args:
        path: Path to the save file

    Returns:
        Pet instance if successful, None otherwise
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return None
        allowed = {f.name for f in dataclass_fields(Pet)}
        data = {k: v for k, v in raw.items() if k in allowed}
        pet = Pet(**data)
        pet.init_if_needed()
        return pet
    except FileNotFoundError:
        return None
    except Exception:
        return None


def save_pet(pet: Pet, path: str) -> None:
    """
    Save a pet to a JSON file atomically.

    Args:
        pet: Pet instance to save
        path: Path to the save file
    """
    tmp = f"{path}.tmp"
    data = asdict(pet)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
