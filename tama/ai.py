"""
Terminal Tamagotchi - AI Integration

This module handles AI personality via Ollama for pet chat/interaction.
"""

import queue
import random
import re
import subprocess
import threading
from typing import Optional

from .pet import Pet


def run_ollama_list(timeout_s: float = 2.0) -> tuple[bool, list[str], str]:
    """
    Check if Ollama is available and list installed models.

    Args:
        timeout_s: Timeout for the command

    Returns:
        Tuple of (success, model_list, error_message)
    """
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
    """
    Generate text using an Ollama model.

    Args:
        model: Ollama model name
        prompt: Text prompt for generation
        timeout_s: Timeout for generation

    Returns:
        Tuple of (success, generated_text)
    """
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
    """
    Build a prompt for AI text generation based on pet state.

    Args:
        pet: Pet instance

    Returns:
        Formatted prompt string
    """
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
    """
    Clean and sanitize AI output to a single line.

    Args:
        text: Raw AI output
        max_len: Maximum length for output

    Returns:
        Cleaned single-line text
    """
    if not text:
        return ""
    s = text.replace("\r", "\n").split("\n")[0].strip()
    if s.startswith(("\"", """, """, "'")) and s.endswith(("\"", """, """, "'")) and len(s) >= 2:
        s = s[1:-1].strip()
    s = "".join(ch for ch in s if (31 < ord(ch) < 127) or ch in (" ",))
    s = " ".join(s.split())
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def enforce_first_person(pet_name: str, line: str) -> str:
    """
    Convert third-person references to first person in AI output.

    Args:
        pet_name: Name of the pet
        line: Text to convert

    Returns:
        Converted text in first person
    """
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
    """Background worker thread for asynchronous AI text generation."""

    def __init__(self) -> None:
        """Initialize the AI worker with request/result queues."""
        self.requests: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=2)  # (model, prompt)
        self.results: "queue.Queue[str]" = queue.Queue(maxsize=3)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Worker thread main loop."""
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
        """
        Try to queue an AI generation request.

        Args:
            model: Ollama model name
            prompt: Text prompt

        Returns:
            True if request was queued, False if queue is full
        """
        try:
            self.requests.put_nowait((model, prompt))
            return True
        except queue.Full:
            return False

    def try_pop(self) -> Optional[str]:
        """
        Try to get a completed AI result.

        Returns:
            Generated text if available, None otherwise
        """
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None
