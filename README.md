# tama-term

A Tamagotchi-inspired terminal pet (TUI) with classic-style evolution and optional local Ollama “chatter”.

## Run

```bash
python3 tama.py
```

## Controls

- `f` feed
- `p` play
- `s` sleep/wake
- `c` clean
- `m` medicine (costs coins)
- `g` minigame
- `t` train
- `r` rename
- `?` help
- `q` quit

## Evolution (classic-style)

Stages: `egg -> baby -> child -> teen -> adult`.  
Your care influences which form you get (tracked via “care mistakes” from neglect).

The header shows:
- `age`: real time since start
- `life`: simulated time (used for evolution/stats; affected by `--speed`)

## Speed

```bash
python3 tama.py --speed 1
```

## AI mode (Ollama, local)

Starts a setup wizard that checks Ollama, lists available models, and lets you choose a personality.

```bash
python3 tama.py --ai
```

Preferred model can be set:

```bash
python3 tama.py --ai --ai-model qwen2.5:0.5b
```

## Save file

Auto-saves to `~/.tama_state.json`.

To keep saves inside the repo instead:

```bash
python3 tama.py --save .tama_state.json
```
