#!/usr/bin/env python3
"""
Terminal Tamagotchi - Entry Point

Run:
  python tama.py
  or
  python -m tama

Keys:
  f feed     p play     s sleep/wake     c clean
  m med      g minigame t train          r rename
  ? help     q quit (auto-saves)
"""

from tama import main

if __name__ == "__main__":
    raise SystemExit(main())
