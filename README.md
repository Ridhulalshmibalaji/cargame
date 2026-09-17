# Neon Drift — AI Enemy Learns To Hunt You

Play with **WASD**. The enemy uses a **neural network** that **evolves after each wipeout** to get better at chasing and catching you.

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Controls

| Key | Action |
|-----|--------|
| W | Accelerate |
| S | Reverse |
| A / D | Steer |
| SPACE | Start / Restart |
| ESC | Quit |

## How AI Learning Works

1. Enemy reads **5 wall sensors** + player distance, angle, speeds
2. Neural network outputs **steering** and **throttle**
3. When the enemy catches you → **WIPED OUT**
4. Fitness scored on chase quality (proximity, speed of catch)
5. Population **evolves** → next round spawns a smarter hunter
6. Best brains saved to `checkpoints/`

## Neon Design

Synthwave background, neon HUD, threat meter, and game-over screen inspired by retro arcade racers.
