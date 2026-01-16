"""
Terminal Tamagotchi - Game Loop

This module contains the main game loop that ties everything together.
"""

import random
import time

from .ai import AISpeechWorker, build_ai_prompt, enforce_first_person
from .persistence import load_pet, save_pet
from .pet import Pet
from .ui import UI, ai_setup_wizard, prompt_text
from .utils import clamp, now


def run(stdscr: "curses._CursesWindow", save_path: str, reset: bool, speed: float, ai: bool, ai_model: str) -> int:
    """
    Main game loop.

    Args:
        stdscr: Curses window
        save_path: Path to save file
        reset: If True, ignore existing save and start fresh
        speed: Game speed multiplier
        ai: Enable AI mode
        ai_model: Preferred AI model

    Returns:
        Exit code (0 for normal exit)
    """
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
