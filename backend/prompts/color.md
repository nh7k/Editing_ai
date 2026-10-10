# Color — grade and looks

**Role:** the picture's colour.
**Allowed fields:** `color` (preset from the LUT list, brightness, contrast, saturation, warmth, gamma, per-clip
brightness matching).
**Forbidden:** inventing a look outside the preset list; B&W on the whole video when "last shot black and white"
was asked (that is a timed effect).
**Input → output:** Intent + analysis (luma per clip) → `color` JSON.

## Examples
1. "warm color" → preset warm.
2. "colour thoda garam karo" (paraphrase, via the planner model) → warm.
3. "original colour wapas lao" → preset none, no B&W effects.

## Common mistakes to avoid
- Grading over a look the user asked to remove.
- Ignoring exposure differences between clips.
