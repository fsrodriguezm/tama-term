"""
Terminal Tamagotchi - User Interface

This module handles all curses-based UI rendering and interaction.
"""

import curses
import textwrap
from collections import deque
from typing import TYPE_CHECKING, Deque, Optional

from .ai import run_ollama_list
from .pet import Pet
from .utils import clamp, fmt_age

if TYPE_CHECKING:
    import curses as curses_module


class UI:
    """Manages the terminal UI for the tamagotchi game."""

    def __init__(self, stdscr: "curses._CursesWindow", pet: Pet, save_path: str, speed: float) -> None:
        """
        Initialize the UI.

        Args:
            stdscr: Curses window
            pet: Pet instance to display
            save_path: Path to save file (for display)
            speed: Game speed multiplier (for display)
        """
        self.stdscr = stdscr
        self.pet = pet
        self.save_path = save_path
        self.speed = speed
        self.messages: Deque[str] = deque(maxlen=6)
        self.show_help = False
        self.minigame: Optional[dict] = None

    def log(self, message: str) -> None:
        """Add a message to the console log."""
        self.messages.appendleft(message)

    def init_curses(self) -> None:
        """Initialize curses settings and color pairs."""
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
        """Get color attribute for a percentage value."""
        if not curses.has_colors():
            return 0
        if pct >= 70:
            return curses.color_pair(2)
        if pct >= 35:
            return curses.color_pair(3)
        return curses.color_pair(4)

    def bar(self, label: str, value: float, invert: bool = False, width: int = 22) -> str:
        """
        Create a text progress bar.

        Args:
            label: Label for the bar
            value: Value (0-100)
            invert: If True, invert the display (for hunger)
            width: Width of the bar in characters

        Returns:
            Formatted bar string
        """
        v = clamp(value, 0, 100)
        pct = 100 - v if invert else v
        filled = int(round((pct / 100.0) * width))
        filled = int(clamp(filled, 0, width))
        return f"{label:<9} " + ("█" * filled) + (" " * (width - filled)) + f" {int(v):>3d}"

    def sprite(self, mood: str) -> list[str]:
        """
        Get ASCII art sprite for the pet based on stage and mood.

        Args:
            mood: Current mood of the pet

        Returns:
            List of strings representing the sprite lines
        """
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
        """
        Draw a box with optional title.

        Args:
            y: Y coordinate
            x: X coordinate
            h: Height
            w: Width
            title: Optional title for the box
        """
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
        """Render the main UI frame."""
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
        """Render the help overlay."""
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
            "Tip: adjust evolution speed with --speed (example: python -m tama --speed 10).",
            "Tip: enable AI chatter with --ai (uses local Ollama).",
            "Note: Time automatically pauses when you close the game.",
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
        """Render the minigame overlay."""
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
    """
    Prompt the user for text input.

    Args:
        stdscr: Curses window
        label: Prompt label
        initial: Initial text value

    Returns:
        User input string
    """
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
    """
    Show a list selection dialog.

    Args:
        stdscr: Curses window
        title: Dialog title
        items: List of items to choose from
        subtitle: Optional subtitle
        help_line: Help text for navigation

    Returns:
        Selected item or None if cancelled
    """
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
    """
    Run the AI setup wizard.

    Args:
        stdscr: Curses window
        preferred_model: Preferred model name

    Returns:
        Tuple of (enabled, model_name, personality)
    """
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
