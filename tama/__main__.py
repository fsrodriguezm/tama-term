#!/usr/bin/env python3
"""
Terminal Tamagotchi - Main Entry Point

Run:
  python -m tama

Keys:
  f feed     p play     s sleep/wake     c clean
  m med      g minigame t train          r rename
  ? help     q quit (auto-saves)
"""

import argparse
import curses

from .game import run
from .utils import SAVE_PATH


def main() -> int:
    """
    Main entry point with argument parsing.

    Returns:
        Exit code
    """
    parser = argparse.ArgumentParser(description="Cool Tamagotchi in the terminal (no deps).")
    parser.add_argument("--reset", action="store_true", help="ignore existing save and start fresh")
    parser.add_argument("--save", default=SAVE_PATH, help=f"save file path (default: {SAVE_PATH})")
    parser.add_argument("--speed", type=float, default=6.0, help="game time multiplier (default: 6.0)")
    parser.add_argument("--ai", action="store_true", help="enable local Ollama-powered pet chatter (opens setup wizard)")
    parser.add_argument("--ai-model", default="qwen2.5:0.5b", help="preferred Ollama model for --ai (default: qwen2.5:0.5b)")
    args = parser.parse_args()
    speed = max(0.5, min(50.0, float(args.speed)))
    return curses.wrapper(lambda stdscr: run(stdscr, args.save, args.reset, speed, bool(args.ai), str(args.ai_model)))


if __name__ == "__main__":
    raise SystemExit(main())
