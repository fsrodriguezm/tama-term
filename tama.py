#!/usr/bin/env python3
"""
Terminal Tamagotchi (no dependencies).

Run:
  python3 tama.py

Keys:
  f feed     p play     s sleep/wake     c clean
  m med      g minigame t train          r rename
  ? help     q quit (auto-saves)
"""

from __future__ import annotations

import argparse
import curses
import json
import locale
import os
import queue
import random
import re
import subprocess
import textwrap
import threading
import time
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from typing import Deque, Optional
from collections import deque


SAVE_PATH = os.path.join(os.path.expanduser("~"), ".tama_state.json")
locale.setlocale(locale.LC_ALL, "")

STAGES = ("egg", "baby", "child", "teen", "adult")
STAGE_SECONDS = {
    "egg": 60,            # 1m
    "baby": 20 * 60,      # 20m
    "child": 60 * 60,     # 1h
    "teen": 3 * 60 * 60,  # 3h
    "adult": 10**9,
}
NEGLECT_THRESHOLD_S = 15 * 60  # classic-ish "ignored call" proxy (in game-seconds)


def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def now() -> float:
    return time.time()


def fmt_age(seconds: int) -> str:
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


@dataclass
class Pet:
    name: str = "Tama"
    created_at: float = 0.0
    last_tick: float = 0.0
    age_s: int = 0
    age_accum_s: float = 0.0
    sim_s: int = 0
    sim_accum_s: float = 0.0

    hunger: float = 20.0      # 0..100 (higher = hungrier)
    happiness: float = 75.0   # 0..100
    energy: float = 75.0      # 0..100
    hygiene: float = 80.0     # 0..100
    health: float = 90.0      # 0..100

    asleep: bool = False
    poop: int = 0
    coins: int = 10

    stage: str = "egg"
    form: str = "egg"
    care_mistakes: int = 0
    neglect_hunger_s: float = 0.0
    neglect_energy_s: float = 0.0
    neglect_dirty_s: float = 0.0
    neglect_health_s: float = 0.0

    ai_enabled: bool = False
    ai_model: str = ""
    ai_personality: str = "classic"
    ai_next_say_at: float = 0.0
    ai_last_say_at: float = 0.0

    alive: bool = True
    last_event: str = "An egg..."

    def init_if_needed(self) -> None:
        t = now()
        if self.created_at <= 0:
            self.created_at = t
        if self.last_tick <= 0:
            self.last_tick = t

    def mood(self) -> str:
        if not self.alive:
            return "gone"
        if self.asleep:
            return "sleepy"
        danger = 0
        if self.hunger > 80:
            danger += 1
        if self.energy < 20:
            danger += 1
        if self.hygiene < 25 or self.poop >= 2:
            danger += 1
        if self.health < 40:
            danger += 1
        if danger >= 2:
            return "struggling"
        if self.happiness < 35:
            return "bored"
        if self.happiness > 85 and self.health > 80:
            return "sparkly"
        return "okay"

    def stage_index(self) -> int:
        try:
            return STAGES.index(self.stage)
        except ValueError:
            return 0

    def evolve_to(self, stage: str, form: str, event: str) -> None:
        self.stage = stage
        self.form = form
        self.last_event = event

    def maybe_evolve(self) -> Optional[str]:
        if not self.alive:
            return None

        next_stage = None
        sim_age = self.sim_s
        if self.stage == "egg" and sim_age >= STAGE_SECONDS["egg"]:
            next_stage = "baby"
        elif self.stage == "baby" and sim_age >= STAGE_SECONDS["egg"] + STAGE_SECONDS["baby"]:
            next_stage = "child"
        elif self.stage == "child" and sim_age >= STAGE_SECONDS["egg"] + STAGE_SECONDS["baby"] + STAGE_SECONDS["child"]:
            next_stage = "teen"
        elif self.stage == "teen" and sim_age >= (
            STAGE_SECONDS["egg"] + STAGE_SECONDS["baby"] + STAGE_SECONDS["child"] + STAGE_SECONDS["teen"]
        ):
            next_stage = "adult"

        if not next_stage:
            return None

        care_score = (
            (100 - self.hunger)
            + self.happiness
            + self.energy
            + self.hygiene
            + self.health
            - (12 * self.care_mistakes)
            - (8 * self.poop)
        )

        if next_stage == "baby":
            self.asleep = False
            self.evolve_to("baby", "bloblet", "It hatched!")
            return "Evolved: egg -> baby"

        if next_stage == "child":
            if self.care_mistakes <= 0 and self.happiness >= 70 and self.hygiene >= 60:
                form = "sprout"
            elif self.hygiene >= 55 and self.health >= 55:
                form = "shell"
            else:
                form = "spiky"
            self.evolve_to("child", form, "Growing up!")
            return "Evolved: baby -> child"

        if next_stage == "teen":
            if care_score >= 360 and self.health >= 70:
                form = "wing"
            elif self.happiness >= 55 and self.energy >= 35:
                form = "bouncy"
            else:
                form = "grit"
            self.evolve_to("teen", form, "Teen phase!")
            return "Evolved: child -> teen"

        if next_stage == "adult":
            if self.care_mistakes <= 1 and self.health >= 75 and self.happiness >= 70 and self.hygiene >= 55:
                form = "seraph"
            elif self.care_mistakes <= 3 and self.health >= 45:
                form = "classic"
            else:
                form = "gremlin"
            self.evolve_to("adult", form, "Fully grown!")
            return "Evolved: teen -> adult"

        return None

    def update_care_mistakes(self, dt: float) -> Optional[str]:
        if not self.alive:
            return None

        def bump(timer_name: str, active: bool) -> bool:
            current = getattr(self, timer_name)
            current = (current + dt) if active else 0.0
            setattr(self, timer_name, current)
            if current >= NEGLECT_THRESHOLD_S:
                setattr(self, timer_name, 0.0)
                return True
            return False

        mistake = False
        reason = None
        if bump("neglect_hunger_s", self.hunger >= 92 and not self.asleep):
            mistake, reason = True, "Hunger neglected"
        elif bump("neglect_energy_s", self.energy <= 8 and not self.asleep):
            mistake, reason = True, "Exhaustion neglected"
        elif bump("neglect_dirty_s", (self.poop >= 2 or self.hygiene <= 15) and not self.asleep):
            mistake, reason = True, "Mess neglected"
        elif bump("neglect_health_s", self.health <= 35):
            mistake, reason = True, "Health neglected"

        if mistake:
            self.care_mistakes += 1
            self.care_mistakes = int(clamp(self.care_mistakes, 0, 99))
            return f"Care mistake: {reason} (+1)"
        return None

    def tick(self, dt: float) -> None:
        if dt <= 0:
            return
        self.sim_accum_s += float(dt)
        if self.sim_accum_s >= 1.0:
            inc = int(self.sim_accum_s)
            self.sim_s += inc
            self.sim_accum_s -= inc

        if not self.alive:
            return

        minutes = dt / 60.0

        if self.asleep:
            self.energy += 10.0 * minutes
            self.hunger += 1.2 * minutes
            self.happiness -= 0.4 * minutes if self.hunger > 80 else 0.05 * minutes
            self.hygiene -= 0.25 * minutes
        else:
            self.energy -= 4.0 * minutes
            self.hunger += 3.0 * minutes
            self.happiness -= 1.6 * minutes
            self.hygiene -= 1.1 * minutes

        if self.poop > 0:
            self.hygiene -= 0.35 * minutes * min(4, self.poop)

        if self.hunger > 92:
            self.health -= 6.0 * minutes
        if self.energy < 10:
            self.health -= 4.0 * minutes
        if self.hygiene < 15:
            self.health -= 5.0 * minutes
        if self.happiness < 15:
            self.health -= 2.0 * minutes
        if self.hunger < 35 and self.energy > 40 and self.hygiene > 40 and self.happiness > 40:
            self.health += 1.2 * minutes

        self.hunger = clamp(self.hunger, 0, 100)
        self.happiness = clamp(self.happiness, 0, 100)
        self.energy = clamp(self.energy, 0, 100)
        self.hygiene = clamp(self.hygiene, 0, 100)
        self.health = clamp(self.health, 0, 100)

        if self.health <= 0.1:
            self.alive = False
            self.last_event = "..."

    def maybe_poop(self) -> None:
        if not self.alive:
            return
        if random.random() < 0.22:
            self.poop = min(4, self.poop + 1)


def load_pet(path: str) -> Optional[Pet]:
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


def run_ollama_list(timeout_s: float = 2.0) -> tuple[bool, list[str], str]:
    try:
        cp = subprocess.run(
            ["ollama", "list"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return False, [], "ollama command not found"
    except subprocess.TimeoutExpired:
        return False, [], "ollama list timed out"
    except Exception as e:
        return False, [], f"ollama list failed: {e}"

    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip()[:200]
        return False, [], (err or f"ollama list exited {cp.returncode}")

    lines = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
    if len(lines) <= 1:
        return True, [], "no models found (run: ollama pull qwen2.5:0.5b)"

    models: list[str] = []
    for ln in lines[1:]:
        parts = ln.split()
        if parts:
            models.append(parts[0])
    return True, models, ""


def ollama_generate(model: str, prompt: str, timeout_s: float = 8.0) -> tuple[bool, str]:
    if not model:
        return False, ""
    try:
        cp = subprocess.run(
            ["ollama", "run", model, prompt],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return False, ""
    if cp.returncode != 0:
        return False, ""
    text_out = (cp.stdout or "").strip()
    if not text_out:
        return False, ""
    line = text_out.splitlines()[0].strip()
    return True, line


def build_ai_prompt(pet: Pet) -> str:
    stage = f"{pet.stage}/{pet.form}"
    mood = pet.mood()
    persona = pet.ai_personality or "classic"
    topics = [
        "food",
        "dreams",
        "games",
        "the human",
        "being tiny",
        "stars",
        "time",
        "training",
        "cleanliness",
    ]
    topic = random.choice(topics)
    style = {
        "classic": "simple, cute, 90s virtual pet vibe",
        "sweet": "wholesome and affectionate",
        "chaotic": "hyper, weird, silly",
        "wise": "calm, zen, slightly poetic",
        "snarky": "dry, playful sarcasm (not mean)",
        "shy": "quiet, bashful, gentle",
    }.get(persona, "simple, cute")
    return (
        "You are a tiny Tamagotchi-style virtual pet in a terminal.\n"
        "Respond with exactly ONE short line, max 60 characters. No emojis.\n"
        "Speak ONLY in first person (I/me/my). Never use your name.\n"
        "Never refer to yourself in third person (no '<name> is', 'it is', etc.).\n"
        "Do NOT introduce yourself with 'my name is'.\n"
        "No quotes, no markdown, no extra lines.\n"
        f"Personality: {persona} ({style}).\n"
        f"Current: name={pet.name}, stage={stage}, mood={mood}.\n"
        f"Stats (0-100): hunger={int(pet.hunger)}, happy={int(pet.happiness)}, energy={int(pet.energy)}, "
        f"hygiene={int(pet.hygiene)}, health={int(pet.health)}, poop={pet.poop}, mistakes={pet.care_mistakes}.\n"
        f"Say something about {topic}."
    )


def sanitize_one_liner(text: str, max_len: int = 60) -> str:
    if not text:
        return ""
    s = text.replace("\r", "\n").split("\n")[0].strip()
    if s.startswith(("\"", "“", "”", "'")) and s.endswith(("\"", "“", "”", "'")) and len(s) >= 2:
        s = s[1:-1].strip()
    s = "".join(ch for ch in s if (31 < ord(ch) < 127) or ch in (" ",))
    s = " ".join(s.split())
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def enforce_first_person(pet_name: str, line: str) -> str:
    if not line:
        return ""
    # Drop common "Speaker: ..." prefixes (often produced by models).
    if ":" in line and line.index(":") < 28:
        line = line.split(":", 1)[1].strip()
    name = (pet_name or "").strip()
    if not name:
        return line

    def _strip_name_variant(match: "re.Match[str]") -> str:
        token = match.group(0)
        if token.lower() == "tamagotchi":
            return token
        return ""

    # Replace possessive and common third-person patterns that include the name.
    s = line
    s = re.sub(rf"\b{re.escape(name)}'s\b", "my", s, flags=re.IGNORECASE)
    s = re.sub(rf"^\s*{re.escape(name)}\b", "I", s, flags=re.IGNORECASE)

    replacements = {
        " is ": " am ",
        " was ": " was ",
        " has ": " have ",
        " wants ": " want ",
        " needs ": " need ",
        " feels ": " feel ",
        " likes ": " like ",
        " thinks ": " think ",
        " hopes ": " hope ",
        " can't ": " can't ",
        " cannot ": " cannot ",
    }
    for third, first in replacements.items():
        s = re.sub(rf"\b{re.escape(name)}{re.escape(third)}", f"I{first}", s, flags=re.IGNORECASE)

    # If the model still uses the name elsewhere, drop it (don't replace with I).
    s = re.sub(rf"\b{re.escape(name)}\b", "", s, flags=re.IGNORECASE)
    # Also drop near-name variants like "Tamae" (but keep "Tamagotchi").
    s = re.sub(rf"\b{re.escape(name)}[A-Za-z]{{1,3}}\b", _strip_name_variant, s, flags=re.IGNORECASE)
    # Drop trailing vocative like ", Tama!" or "Tamae!"
    s = re.sub(rf"(,?\s*)\b{re.escape(name)}[A-Za-z]{{0,3}}\b[!?.]?\s*$", "", s, flags=re.IGNORECASE)

    # Strip "my name is ..." introductions.
    s = re.sub(r"\bmy name is\b[^,!.]*[,!.]?\s*", "", s, flags=re.IGNORECASE)

    s = " ".join(s.split())
    s = s.replace("I am am", "I am").replace("I I", "I")
    s = s.replace("a I", "a pet").replace("an I", "a pet")
    s = s.replace("As a I", "As a pet").replace("as a I", "as a pet")
    s = re.sub(r"\bI is\b", "I am", s)
    return s.strip()


class AISpeechWorker:
    def __init__(self) -> None:
        self.requests: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=2)  # (model, prompt)
        self.results: "queue.Queue[str]" = queue.Queue(maxsize=3)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            model, prompt = self.requests.get()
            ok, out = ollama_generate(model, prompt)
            if ok:
                line = sanitize_one_liner(out)
                if line:
                    try:
                        self.results.put_nowait(line)
                    except queue.Full:
                        pass

    def try_request(self, model: str, prompt: str) -> bool:
        try:
            self.requests.put_nowait((model, prompt))
            return True
        except queue.Full:
            return False

    def try_pop(self) -> Optional[str]:
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None


class UI:
    def __init__(self, stdscr: "curses._CursesWindow", pet: Pet, save_path: str, speed: float) -> None:
        self.stdscr = stdscr
        self.pet = pet
        self.save_path = save_path
        self.speed = speed
        self.messages: Deque[str] = deque(maxlen=6)
        self.show_help = False
        self.minigame: Optional[dict] = None

    def log(self, message: str) -> None:
        self.messages.appendleft(message)

    def init_curses(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)    # title
            curses.init_pair(2, curses.COLOR_GREEN, -1)   # good
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # warn
            curses.init_pair(4, curses.COLOR_RED, -1)     # bad
            curses.init_pair(5, curses.COLOR_MAGENTA, -1) # accent

    def color_for_pct(self, pct: float) -> int:
        if not curses.has_colors():
            return 0
        if pct >= 70:
            return curses.color_pair(2)
        if pct >= 35:
            return curses.color_pair(3)
        return curses.color_pair(4)

    def bar(self, label: str, value: float, invert: bool = False, width: int = 22) -> str:
        v = clamp(value, 0, 100)
        pct = 100 - v if invert else v
        filled = int(round((pct / 100.0) * width))
        filled = int(clamp(filled, 0, width))
        return f"{label:<9} " + ("█" * filled) + (" " * (width - filled)) + f" {int(v):>3d}"

    def sprite(self, mood: str) -> list[str]:
        if not self.pet.alive:
            return [
                "   .-''''-.",
                "  /  RIP  \\",
                " |   xx   |",
                "  \\______/",
                "   (____)",
            ]
        if self.pet.stage == "egg":
            return [
                "    .----. ",
                "   / .--.\\ ",
                "  |  '--' |",
                "   \\_____/ ",
                "    (egg)  ",
            ]
        if self.pet.asleep:
            return [
                "   .-''''-.",
                "  /  zZz  \\",
                " |  (-_-) |",
                "  \\______/ ",
                "   /||||\\  ",
            ]
        if self.pet.stage == "baby":
            return [
                "   .-''''-.",
                "  /  o o  \\",
                " |   (.)  |",
                "  \\______/ ",
                "   /||||\\  ",
            ]
        if self.pet.stage == "child":
            if self.pet.form == "sprout":
                return [
                    "   .-''''-.",
                    "  /  \\|/  \\",
                    " |  (o_o) |",
                    "  \\______/ ",
                    "    /||\\   ",
                ]
            if self.pet.form == "shell":
                return [
                    "   .-''''-.",
                    "  /  ___  \\",
                    " |  (o_o) |",
                    "  \\__===_/ ",
                    "    /||\\   ",
                ]
            return [
                "   .-''''-.",
                "  /  ^ ^  \\",
                " |  (o_o) |",
                "  \\__^_^_/ ",
                "    /||\\   ",
            ]
        if self.pet.stage == "teen":
            if self.pet.form == "wing":
                return [
                    "  .-''''-.",
                    " / \\_ _/ \\",
                    "|  (o_o) |",
                    " \\__\\_/__/ ",
                    "   /|||\\   ",
                ]
            if self.pet.form == "bouncy":
                return [
                    "   .-''''-.",
                    "  /  ._.  \\",
                    " |  (o_o) |",
                    "  \\__---_/ ",
                    "    /||\\   ",
                ]
            return [
                "   .-''''-.",
                "  /  x x  \\",
                " |  (o_o) |",
                "  \\__-_-_/ ",
                "    /||\\   ",
            ]
        if self.pet.stage == "adult":
            if self.pet.form == "seraph":
                return [
                    "  .-''''-.",
                    " /  ( )  \\",
                    "|  (o_o) |",
                    " \\__\\_/__/ ",
                    "  _/|||\\_  ",
                ]
            if self.pet.form == "gremlin":
                return [
                    "   .-''''-.",
                    "  /  > <  \\",
                    " |  (o_o) |",
                    "  \\__\\_/^/ ",
                    "    /||\\   ",
                ]
            return [
                "   .-''''-.",
                "  /  o o  \\",
                " |  (o_o) |",
                "  \\__\\_/__/ ",
                "    /||\\   ",
            ]
        if mood == "sparkly":
            return [
                "   .-''''-.",
                "  /  **   \\",
                " |  (^_^) |",
                "  \\______/ ",
                "   /||||\\  ",
            ]
        if mood == "struggling":
            return [
                "   .-''''-.",
                "  /  !!   \\",
                " |  (x_x) |",
                "  \\______/ ",
                "   /||||\\  ",
            ]
        if mood == "bored":
            return [
                "   .-''''-.",
                "  /  ...  \\",
                " |  (-_-) |",
                "  \\______/ ",
                "   /||||\\  ",
            ]
        return [
            "   .-''''-.",
            "  /       \\",
            " |  (o_o) |",
            "  \\______/ ",
            "   /||||\\  ",
        ]

    def draw_box(self, y: int, x: int, h: int, w: int, title: Optional[str] = None) -> None:
        if h < 2 or w < 2:
            return
        try:
            self.stdscr.addstr(y, x, "┌" + "─" * (w - 2) + "┐")
            for i in range(1, h - 1):
                self.stdscr.addstr(y + i, x, "│" + " " * (w - 2) + "│")
            self.stdscr.addstr(y + h - 1, x, "└" + "─" * (w - 2) + "┘")
            if title:
                t = f" {title} "
                t = t[: max(0, w - 4)]
                self.stdscr.addstr(y, x + 2, t, curses.color_pair(5) if curses.has_colors() else 0)
        except curses.error:
            return

    def render(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if h < 19 or w < 70:
            msg = "Resize terminal to at least 70x19"
            try:
                self.stdscr.addstr(0, 0, msg)
                self.stdscr.addstr(2, 0, "Press q to quit.")
            except curses.error:
                pass
            self.stdscr.refresh()
            return

        title = "Terminal Tamagotchi"
        form = f"{self.pet.stage}/{self.pet.form}"
        life = fmt_age(self.pet.sim_s)
        if self.pet.ai_enabled and self.pet.ai_model:
            ai_label = f"ai: {self.pet.ai_model} ({self.pet.ai_personality})"
        else:
            ai_label = "ai: off"
        subtitle = (
            f"{self.pet.name} · {form} · age {fmt_age(self.pet.age_s)} · life {life} · mood: {self.pet.mood()} · "
            f"mistakes: {self.pet.care_mistakes} · coins: {self.pet.coins} · speed: {self.speed:0.1f}x · {ai_label}"
        )
        try:
            self.stdscr.addstr(0, 2, title, curses.color_pair(1) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD)
            self.stdscr.addstr(1, 2, subtitle)
        except curses.error:
            pass

        top = 2
        footer_h = 1
        gap_h = 1
        console_h = 5
        main_h = h - top - gap_h - console_h - footer_h
        main_w = w - 4
        self.draw_box(top, 2, main_h, main_w, "Pet")

        left_x = 4
        left_y = top + 2
        mood = self.pet.mood()
        for i, line in enumerate(self.sprite(mood)):
            try:
                self.stdscr.addstr(left_y + i, left_x, line, curses.color_pair(5) if curses.has_colors() else 0)
            except curses.error:
                pass

        status_x = 28
        status_y = top + 1
        lines = []
        lines.append(self.bar("Hunger", self.pet.hunger, invert=True))
        lines.append(self.bar("Happy", self.pet.happiness))
        lines.append(self.bar("Energy", self.pet.energy))
        lines.append(self.bar("Hygiene", self.pet.hygiene))
        lines.append(self.bar("Health", self.pet.health))
        lines.append(f"{'Poop':<9} " + ("#" * self.pet.poop) if self.pet.poop else f"{'Poop':<9} none")
        lines.append(f"{'State':<9} " + ("asleep" if self.pet.asleep else "awake"))
        lines.append(f"{'Last':<9} {self.pet.last_event}")

        for i, line in enumerate(lines):
            try:
                attr = 0
                if line.startswith("Health"):
                    attr = self.color_for_pct(self.pet.health)
                elif line.startswith("Hygiene"):
                    attr = self.color_for_pct(self.pet.hygiene)
                elif line.startswith("Energy"):
                    attr = self.color_for_pct(self.pet.energy)
                elif line.startswith("Happy"):
                    attr = self.color_for_pct(self.pet.happiness)
                elif line.startswith("Hunger"):
                    attr = self.color_for_pct(100 - self.pet.hunger)
                self.stdscr.addstr(status_y + i, status_x, line[: (w - status_x - 2)], attr)
            except curses.error:
                pass

        msg_box_y = top + main_h + gap_h
        self.draw_box(msg_box_y, 2, console_h, main_w, "Console")

        help_line = "f feed  p play  s sleep/wake  c clean  m med  g minigame  t train  r rename  ? help  q quit"
        try:
            self.stdscr.addstr(h - 1, 2, help_line[: (w - 4)], curses.A_DIM)
        except curses.error:
            pass

        max_msgs = max(1, console_h - 2)
        for i, message in enumerate(list(self.messages)[:max_msgs]):
            try:
                self.stdscr.addstr(msg_box_y + 1 + i, 4, f"• {message}"[: (w - 8)])
            except curses.error:
                pass

        if self.show_help:
            self.render_help()

        if self.minigame:
            self.render_minigame()

        self.stdscr.refresh()

    def render_help(self) -> None:
        h, w = self.stdscr.getmaxyx()
        box_w = min(62, w - 10)
        box_h = min(13, h - 4)
        y = max(1, (h - box_h) // 2)
        x = (w - box_w) // 2
        self.draw_box(y, x, box_h, box_w, "Help")
        body = [
            "Keep stats healthy. Hunger rises over time; hygiene drops faster if poop piles up.",
            "Classic-style evolution: egg -> baby -> child -> teen -> adult.",
            "Your care influences the character. Neglect (high hunger, low energy, mess, low health) can add care mistakes.",
            "Actions:",
            "  f feed: reduces hunger; may cause poop",
            "  p play: boosts happiness; costs energy",
            "  s sleep: restores energy; slows life a bit",
            "  c clean: removes poop; restores hygiene",
            "  m med: restores health (costs coins)",
            "  g minigame: reaction game for coins/happiness",
            "  t train: small happiness + coin chance",
            "  r rename: type a new name",
            "",
            "Tip: adjust evolution speed with --speed (example: python3 tama.py --speed 10).",
            "Tip: enable AI chatter with --ai (uses local Ollama).",
            "Press ? to close this window.",
        ]
        yy = y + 1
        for line in body:
            for wrapped in textwrap.wrap(line, width=box_w - 4) or [""]:
                if yy >= y + box_h - 1:
                    break
                try:
                    self.stdscr.addstr(yy, x + 2, wrapped[: box_w - 4])
                except curses.error:
                    pass
                yy += 1

    def render_minigame(self) -> None:
        h, w = self.stdscr.getmaxyx()
        box_w = min(52, w - 10)
        box_h = min(9, h - 4)
        y = max(1, (h - box_h) // 2)
        x = (w - box_w) // 2
        self.draw_box(y, x, box_h, box_w, "Minigame")

        state = self.minigame or {}
        phase = state.get("phase", "wait")
        prompt = state.get("prompt", "Get ready...")
        timer = state.get("timer", 0.0)
        best = state.get("best_ms")

        lines = []
        if phase == "wait":
            lines.append("Wait for the signal, then press SPACE.")
            lines.append("Early press = fail.")
        elif phase == "go":
            lines.append("NOW! Press SPACE!")
        else:
            lines.append("Press g to start again.")

        lines.append("")
        lines.append(prompt)
        lines.append(f"Timer: {timer:0.3f}s")
        if best is not None:
            lines.append(f"Best: {best}ms")

        yy = y + 2
        for line in lines[: (box_h - 3)]:
            try:
                attr = curses.A_BOLD if ("NOW!" in line and curses.has_colors()) else 0
                if "NOW!" in line and curses.has_colors():
                    attr |= curses.color_pair(2)
                self.stdscr.addstr(yy, x + 2, line[: box_w - 4], attr)
            except curses.error:
                pass
            yy += 1


def prompt_text(stdscr: "curses._CursesWindow", label: str, initial: str = "") -> str:
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.keypad(True)
    h, w = stdscr.getmaxyx()
    box_w = min(60, w - 8)
    box_h = 7
    y = max(2, (h - box_h) // 2)
    x = (w - box_w) // 2
    try:
        stdscr.addstr(y, x, "┌" + "─" * (box_w - 2) + "┐")
        for i in range(1, box_h - 1):
            stdscr.addstr(y + i, x, "│" + " " * (box_w - 2) + "│")
        stdscr.addstr(y + box_h - 1, x, "└" + "─" * (box_w - 2) + "┘")
        stdscr.addstr(y + 1, x + 2, label[: box_w - 4])
        stdscr.addstr(y + 3, x + 2, "> " + initial[: box_w - 6])
        stdscr.refresh()
    except curses.error:
        pass

    buf = list(initial)
    while True:
        ch = stdscr.getch()
        if ch in (10, 13):  # enter
            break
        if ch in (27,):  # esc
            buf = list(initial)
            break
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= ch <= 126:
            if len(buf) < 20:
                buf.append(chr(ch))
        try:
            stdscr.addstr(y + 3, x + 2, " " * (box_w - 4))
            stdscr.addstr(y + 3, x + 2, "> " + "".join(buf)[: box_w - 6])
            stdscr.refresh()
        except curses.error:
            pass

    stdscr.nodelay(True)
    curses.curs_set(0)
    return "".join(buf).strip() or initial


def choose_from_list(
    stdscr: "curses._CursesWindow",
    title: str,
    items: list[str],
    subtitle: str = "",
    help_line: str = "↑/↓ move  Enter select  Esc cancel",
) -> Optional[str]:
    stdscr.nodelay(False)
    curses.curs_set(0)
    selected = 0
    top = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        box_w = min(max(50, len(title) + 10), w - 4)
        box_h = min(h - 2, max(10, min(18, len(items) + 6)))
        y = max(1, (h - box_h) // 2)
        x = (w - box_w) // 2

        try:
            stdscr.addstr(y, x, "┌" + "─" * (box_w - 2) + "┐")
            for i in range(1, box_h - 1):
                stdscr.addstr(y + i, x, "│" + " " * (box_w - 2) + "│")
            stdscr.addstr(y + box_h - 1, x, "└" + "─" * (box_w - 2) + "┘")
            stdscr.addstr(y + 1, x + 2, title[: box_w - 4], curses.A_BOLD)
            if subtitle:
                stdscr.addstr(y + 2, x + 2, subtitle[: box_w - 4])
            stdscr.addstr(y + box_h - 2, x + 2, help_line[: box_w - 4], curses.A_DIM)
        except curses.error:
            pass

        list_y = y + (3 if subtitle else 2)
        list_h = box_h - (5 if subtitle else 4)
        if list_h < 1:
            list_h = 1

        if selected < top:
            top = selected
        if selected >= top + list_h:
            top = selected - list_h + 1
        top = int(clamp(top, 0, max(0, len(items) - list_h)))

        for i in range(list_h):
            idx = top + i
            if idx >= len(items):
                break
            item = items[idx]
            prefix = "➤ " if idx == selected else "  "
            attr = curses.A_REVERSE if idx == selected else 0
            try:
                stdscr.addstr(list_y + i, x + 2, (prefix + item)[: box_w - 4], attr)
            except curses.error:
                pass

        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):  # esc
            return None
        if ch in (10, 13):  # enter
            if not items:
                return None
            return items[selected]
        if ch in (curses.KEY_UP, ord("k"), ord("K")):
            selected = max(0, selected - 1)
        elif ch in (curses.KEY_DOWN, ord("j"), ord("J")):
            selected = min(len(items) - 1, selected + 1)


def ai_setup_wizard(stdscr: "curses._CursesWindow", preferred_model: str = "") -> tuple[bool, str, str]:
    ok, models, err = run_ollama_list()
    if not ok:
        msg = f"Ollama check failed: {err}"
        _ = prompt_text(stdscr, msg + "  (Enter to continue without AI)", "")
        return False, "", "classic"

    if preferred_model and preferred_model not in models:
        models = [preferred_model] + models

    if not models:
        _ = prompt_text(stdscr, "No models found. (Enter to continue without AI)", "")
        return False, "", "classic"

    model = choose_from_list(
        stdscr,
        "AI Mode Setup: Select Model",
        models,
        subtitle="Uses your local Ollama models (offline).",
    )
    if not model:
        return False, "", "classic"

    personalities = [
        "classic",
        "sweet",
        "chaotic",
        "wise",
        "snarky",
        "shy",
    ]
    personality = choose_from_list(
        stdscr,
        "AI Mode Setup: Select Personality",
        personalities,
        subtitle="Affects the pet's voice and vibe.",
    )
    if not personality:
        personality = "classic"

    return True, model, personality


def run(stdscr: "curses._CursesWindow", save_path: str, reset: bool, speed: float, ai: bool, ai_model: str) -> int:
    pet = None if reset else load_pet(save_path)
    if pet is None:
        pet = Pet()
    pet.init_if_needed()

    if ai:
        enabled, model, personality = ai_setup_wizard(stdscr, preferred_model=ai_model)
        pet.ai_enabled = enabled
        pet.ai_model = model
        pet.ai_personality = personality
        pet.ai_next_say_at = 0.0
        pet.ai_last_say_at = 0.0

    ui = UI(stdscr, pet, save_path, speed)
    ui.init_curses()
    ui.log("Press ? for help.")
    if pet.ai_enabled and pet.ai_model:
        ui.log(f"AI enabled: {pet.ai_model} ({pet.ai_personality}).")
    ai_worker = AISpeechWorker() if pet.ai_enabled and pet.ai_model else None

    last_render = now()
    last_save = now()

    try:
        while True:
            t = now()
            dt = t - pet.last_tick
            pet.last_tick = t
            pet.age_accum_s += float(dt)
            if pet.age_accum_s >= 1.0:
                inc = int(pet.age_accum_s)
                pet.age_s += inc
                pet.age_accum_s -= inc

            game_dt = dt * speed
            pet.tick(game_dt)
            mistake_msg = pet.update_care_mistakes(game_dt)
            if mistake_msg:
                ui.log(mistake_msg)
            evo_msg = pet.maybe_evolve()
            if evo_msg:
                ui.log(evo_msg)

            if ai_worker:
                line = ai_worker.try_pop()
                if line:
                    line2 = enforce_first_person(pet.name, line)
                    ui.log(f"{pet.name}: {line2}")

                if pet.alive and not pet.asleep and pet.stage != "egg":
                    if pet.ai_next_say_at <= 0:
                        pet.ai_next_say_at = t + random.uniform(2.0, 6.0)
                    if t >= pet.ai_next_say_at and (t - pet.ai_last_say_at) >= 8.0:
                        prompt = build_ai_prompt(pet)
                        if ai_worker.try_request(pet.ai_model, prompt):
                            pet.ai_last_say_at = t
                            pet.ai_next_say_at = t + random.uniform(18.0, 40.0)

            if ui.minigame:
                mg = ui.minigame
                phase = mg.get("phase", "wait")
                if phase == "wait":
                    if t >= mg["go_at"]:
                        mg["phase"] = "go"
                        mg["go_time"] = t
                        mg["prompt"] = "Signal!"
                elif phase == "go":
                    mg["timer"] = t - mg.get("go_time", t)

            ch = stdscr.getch()
            if ch != -1:
                if ch in (ord("q"), ord("Q")):
                    save_pet(pet, save_path)
                    return 0
                if ch in (ord("?"),):
                    ui.show_help = not ui.show_help
                if not pet.alive:
                    if ch in (ord("r"), ord("R")):
                        pet = Pet()
                        pet.init_if_needed()
                        ui.pet = pet
                        ui.messages.clear()
                        ui.log("New egg hatched.")
                    continue

                if ui.minigame and ch == ord(" "):
                    mg = ui.minigame
                    phase = mg.get("phase", "wait")
                    if phase == "wait":
                        ui.log("Too early! No reward.")
                        ui.minigame = None
                    elif phase == "go":
                        reaction_ms = int(1000 * (now() - mg.get("go_time", now())))
                        mg["phase"] = "done"
                        mg["prompt"] = f"Reaction: {reaction_ms}ms"
                        best = mg.get("best_ms")
                        if best is None or reaction_ms < best:
                            mg["best_ms"] = reaction_ms
                            ui.log(f"New best: {reaction_ms}ms!")
                        reward = 5 if reaction_ms < 250 else 3 if reaction_ms < 450 else 1
                        pet.coins += reward
                        pet.happiness = clamp(pet.happiness + 6 + reward, 0, 100)
                        pet.energy = clamp(pet.energy - 4, 0, 100)
                        ui.log(f"Minigame win: +{reward} coins, +happiness.")
                        ui.minigame = None

                if ch in (ord("f"), ord("F")):
                    if pet.asleep:
                        ui.log("Shh... wake them first (s).")
                    else:
                        if pet.stage == "egg":
                            ui.log("It hasn't hatched yet.")
                            continue
                        pet.hunger = clamp(pet.hunger - 22, 0, 100)
                        pet.happiness = clamp(pet.happiness + 2, 0, 100)
                        pet.last_event = "Nom nom."
                        pet.maybe_poop()
                        ui.log("Fed.")
                elif ch in (ord("p"), ord("P")):
                    if pet.asleep:
                        ui.log("Can't play while asleep.")
                    else:
                        if pet.stage == "egg":
                            ui.log("Wait for it to hatch.")
                            continue
                        pet.happiness = clamp(pet.happiness + 16, 0, 100)
                        pet.energy = clamp(pet.energy - 12, 0, 100)
                        pet.hunger = clamp(pet.hunger + 6, 0, 100)
                        pet.last_event = "Played!"
                        ui.log("Played together.")
                elif ch in (ord("s"), ord("S")):
                    if pet.stage == "egg":
                        ui.log("The egg doesn't sleep.")
                        continue
                    pet.asleep = not pet.asleep
                    pet.last_event = "Zzz..." if pet.asleep else "Awake!"
                    ui.log("Sleep mode: on." if pet.asleep else "Sleep mode: off.")
                elif ch in (ord("c"), ord("C")):
                    if pet.stage == "egg":
                        ui.log("Nothing to clean yet.")
                        continue
                    if pet.poop <= 0 and pet.hygiene >= 95:
                        ui.log("Already clean.")
                    else:
                        pet.poop = 0
                        pet.hygiene = clamp(pet.hygiene + 35, 0, 100)
                        pet.last_event = "Cleaned."
                        ui.log("Cleaned up.")
                elif ch in (ord("m"), ord("M")):
                    if pet.stage == "egg":
                        ui.log("Not yet.")
                        continue
                    if pet.coins < 4:
                        ui.log("Not enough coins (need 4).")
                    else:
                        pet.coins -= 4
                        pet.health = clamp(pet.health + 30, 0, 100)
                        pet.happiness = clamp(pet.happiness - 1, 0, 100)
                        pet.last_event = "Medicine."
                        ui.log("Gave medicine (-4 coins).")
                elif ch in (ord("t"), ord("T")):
                    if pet.asleep:
                        ui.log("Training can wait.")
                    else:
                        if pet.stage == "egg":
                            ui.log("Not until it hatches.")
                            continue
                        pet.happiness = clamp(pet.happiness + 6, 0, 100)
                        pet.energy = clamp(pet.energy - 6, 0, 100)
                        if random.random() < 0.35:
                            pet.coins += 1
                            ui.log("Training paid off: +1 coin.")
                        else:
                            ui.log("Training complete.")
                        pet.last_event = "Trained."
                elif ch in (ord("g"), ord("G")):
                    if pet.asleep:
                        ui.log("Wake up first (s).")
                    else:
                        if pet.stage == "egg":
                            ui.log("Minigames after hatch.")
                            continue
                        delay = random.uniform(1.2, 3.8)
                        ui.minigame = {"phase": "wait", "go_at": now() + delay, "timer": 0.0, "prompt": "Get ready..."}
                        ui.log("Minigame started.")
                elif ch in (ord("r"), ord("R")):
                    new_name = prompt_text(stdscr, "Rename your pet (Enter=ok, Esc=cancel):", pet.name)
                    if new_name != pet.name:
                        pet.name = new_name
                        ui.log(f"Renamed to {pet.name}.")

            if pet.alive:
                if pet.hunger > 90 and random.random() < 0.03:
                    ui.log("Your pet looks hungry.")
                if pet.energy < 12 and random.random() < 0.03:
                    ui.log("Your pet is exhausted.")
                if (pet.poop >= 2 or pet.hygiene < 20) and random.random() < 0.03:
                    ui.log("Clean-up needed.")

            if t - last_save > 12:
                save_pet(pet, save_path)
                last_save = t

            if t - last_render > 0.05:
                ui.render()
                last_render = t

            time.sleep(0.02)
    finally:
        save_pet(pet, save_path)


def main() -> int:
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
