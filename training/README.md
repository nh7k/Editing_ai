# Train the Hinglish → English translator (free, Google Colab)

The editing brain (rules + 36 pro skills) understands clear English and a lot of Hinglish. For wording it has never
seen, a small model trained on our own data translates the Hinglish into English first. Training needs a GPU for
~30 minutes — Google Colab gives one for free. The trained model then runs on a normal CPU (no GPU bill when live).

## Steps (you, ~45 minutes, free)

1. Open https://colab.research.google.com → **Upload** → choose `training/finetune_translator.ipynb`.
2. Menu **Runtime → Change runtime type → T4 GPU → Save**.
3. Menu **Runtime → Run all**. When the upload button appears, upload these two files from this folder:
   `training/data/train.jsonl` and `training/data/eval.jsonl`.
4. Wait (training ~20–30 min). The notebook prints a score and a few sample translations.
5. At the end `cutmind_translator.zip` downloads. Unzip it into `backend/assets/models/translator/`
   so that `backend/assets/models/translator/onnx/model_q4.onnx` and `.../translator/tokenizer.json` exist.
6. Restart the backend. Check the score (from `backend/`):
   `.venv\Scripts\python.exe -m cutmind.translator_bench trained`

From then on, any part of a prompt the rules don't understand goes through the trained model; its English must still
be understood by the rules (so it can't invent edits). The coach card shows what it translated.

## Data

`python training/make_hinglish_dataset.py` rebuilds `training/data/*.jsonl` (8,580 train / 452 eval) from the phrasings
in that file — add new phrasings there (or teach phrases in the app: `GET /phrasebook` lists what users said that
nobody understood) and train again. The benchmark sentences and a held-out set are never used for training.

## Before training (measured on this laptop, 20 Hinglish requests)

| | right | time per request |
|---|---|---|
| rules alone (before today) | 11/20 | instant |
| Gemma-3-1B, no training | 6/20 | 4.9 s |
| Qwen3-1.7B, no training | 7/20 | 10.3 s |
| Qwen2.5-1.5B, no training | 1/20 | 13.8 s |
| rules + Hinglish added today | 20/20 (new unseen sentences: 11/15) | instant |

## After training (Qwen2.5-1.5B + LoRA on Colab T4, 2 epochs, int4 ONNX, 1.9 GB) — measured 2026-10-07

| | model alone | app (rules first, model for the rest) | time on this laptop |
|---|---|---|---|
| benchmark (20) | 14/20 | **20/20** | 4.7 s / sentence |
| new sentences never trained on (15) | **12/15** | **15/15** | 4.3 s / sentence |

The 4 new sentences the rules alone missed ("ujla", "piche ki taraf", "neeli t-shirt", "kone kale") were all fixed by
the model. Its known weaknesses: it sometimes adds an extra instruction, and once read "rang feeke" as "vivid".
Safety: the model's answer is used only for parts the rules don't understand, and only if every sentence in it is one
it was taught (`translator.is_known`) — a made-up sentence is rejected and the app asks the user instead.
Switch it off with `CUTMIND_TRANSLATOR=off` (tests do this). Needs ~2 GB RAM while loaded; loads on first use (~13 s).

