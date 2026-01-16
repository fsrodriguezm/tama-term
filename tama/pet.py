"""
Terminal Tamagotchi - Pet Model

This module contains the Pet dataclass and all related game logic for the virtual pet.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .utils import STAGES, STAGE_SECONDS, NEGLECT_THRESHOLD_S, clamp, now


@dataclass
class Pet:
    """Represents the virtual pet with all its stats and state."""

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
        """Initialize timestamps if they haven't been set."""
        t = now()
        if self.created_at <= 0:
            self.created_at = t
        if self.last_tick <= 0:
            self.last_tick = t

    def mood(self) -> str:
        """Determine the pet's current mood based on stats."""
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
        """Get the numeric index of the current stage."""
        try:
            return STAGES.index(self.stage)
        except ValueError:
            return 0

    def evolve_to(self, stage: str, form: str, event: str) -> None:
        """Evolve the pet to a new stage and form."""
        self.stage = stage
        self.form = form
        self.last_event = event

    def maybe_evolve(self) -> Optional[str]:
        """Check if the pet should evolve and handle evolution logic."""
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
        """Update care mistake timers and add mistakes if neglect thresholds are reached."""
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
        """Update pet stats based on elapsed time."""
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
        """Randomly generate poop with a probability."""
        if not self.alive:
            return
        if random.random() < 0.22:
            self.poop = min(4, self.poop + 1)
