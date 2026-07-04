"""Voice selection: map story characters to TTS voices automatically.

step2 records each character's gender (and the protagonist id) in scenes.json;
this module turns that into concrete voice names for the narrator and the
protagonist's inner monologue, so any story gets sensible voices without
hardcoding.

Rosters are per-model because the TTS fallback chain spans APIs with different
voice catalogs. Override via env (comma-separated) after running
scripts/smoke_test.py: TTS_VOICES_FEMALE / TTS_VOICES_MALE / TTS_NARRATOR.
"""

import os

from . import config

_ROSTERS = {
    # Qwen Model Studio intl cosyvoice voices (verify with scripts/smoke_test.py)
    "cosyvoice-v3-plus": {
        "female": ["loongstella", "longxiaochun_v2"],
        "male": ["longcheng_v2", "longshu_v2"],
        "narrator": ["loongbella", "loongstella"],
    },
    # qwen3-tts voices (proven with the original pipeline)
    "qwen3-tts-flash": {
        "female": ["Cherry", "Serena"],
        "male": ["Kai", "Ethan"],
        "narrator": ["Cherry", "Ethan"],
    },
}


def _roster(model=None):
    model = model or config.TTS_MODEL
    r = dict(_ROSTERS.get(model) or _ROSTERS[config.TTS_FALLBACK_MODEL])
    for key, env in (("female", "TTS_VOICES_FEMALE"), ("male", "TTS_VOICES_MALE"),
                     ("narrator", "TTS_NARRATOR")):
        raw = os.getenv(env, "")
        vals = [v.strip() for v in raw.split(",") if v.strip()]
        if vals:
            r[key] = vals
    return r


def protagonist_of(graph):
    """The protagonist character dict (falls back to the first character)."""
    chars = graph.get("characters", [])
    if not chars:
        return None
    pid = graph.get("protagonist")
    for c in chars:
        if c.get("id") == pid:
            return c
    return chars[0]


def select_voices(graph, model=None):
    """Pick {"narrator": voice, "protagonist": voice} for this story.

    Protagonist speaks in a voice matching their gender; the narrator gets a
    distinct voice (never the same one) so intro and monologue are clearly
    different speakers.
    """
    r = _roster(model)
    protag = protagonist_of(graph)
    gender = (protag or {}).get("gender", "").lower()
    if gender not in ("female", "male"):
        gender = "male"  # neutral/unknown: arbitrary but stable
    protagonist_voice = r[gender][0]

    narrator_voice = next((v for v in r["narrator"] + r["female"] + r["male"]
                           if v != protagonist_voice), r["narrator"][0])
    return {"narrator": narrator_voice, "protagonist": protagonist_voice}
