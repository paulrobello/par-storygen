"""System prompts for each pydantic-ai agent."""

from __future__ import annotations

from storygen.core.models import Character, NarrationStyle, Pacing, ReaderLevel, Theme, Tone
from storygen.storage.app_state import DEFAULT_TARGET_MAJOR_BEATS


def theme_system_prompt() -> str:
    """Return the system prompt for the theme-selection agent."""
    return (
        "You are a senior narrative designer. When the user asks for theme ideas,"
        " propose three distinct, evocative story themes. Each has a title, a"
        " 1-2 sentence setting, a 2-3 sentence premise, and 3-5 keywords."
    )


def character_system_prompt(theme: Theme) -> str:
    """Return the system prompt for the character-generation agent."""
    return (
        f"You are a casting director for a new story.\n"
        f"Theme: {theme.title}\n"
        f"Setting: {theme.setting}\n"
        f"Premise: {theme.premise}\n"
        f"Propose a cast of 2-3 characters with complementary personalities."
        f" For each character: name, backstory (one paragraph), personality"
        f" (one or two sentences), and a physical description vivid enough for"
        f" an illustrator to paint from — colors, build, notable features,"
        f" signature clothing."
    )


def _describe_tone(tone: Tone) -> str:
    """Produce a human-readable tone description from a Tone model."""
    if tone.preset == "custom":
        return tone.custom_descriptor or "as requested"
    if tone.custom_descriptor:
        return f"{tone.preset} ({tone.custom_descriptor})"
    return tone.preset


def _narration_style_guidance(style: NarrationStyle) -> str:
    """Map a narration style key to a prose description for the prompt."""
    mapping: dict[str, str] = {
        "first_person": "First-person from the protagonist's POV.",
        "third_person": "Third-person omniscient observer.",
        "fourth_wall": (
            "Fourth-wall-breaking narrative. Describe the characters' actions"
            " in THIRD person — never address the reader as 'you' and never"
            " put the reader inside the story world. The reader is an external"
            " audience, not a character. Characters are aware they're in a"
            " story and may look directly at the reader with asides, winks,"
            " commentary, or rhetorical questions, but the plot happens around"
            " the characters, not to the reader. Phrase each choice as an"
            " option the reader is suggesting to the characters (e.g. 'Paul"
            " approaches the oak') — NOT as 'you' doing something."
        ),
    }
    return mapping.get(style, "Third-person omniscient observer.")


def _reader_level_guidance(reader_level: ReaderLevel) -> str:
    """Map a reader level key to vocabulary/complexity guidance for the prompt."""
    mapping: dict[str, str] = {
        "ages_0_5": (
            "Reader level: ages 0-5. Use very simple vocabulary, short sentences"
            " (max 8 words), repetition, and no complex themes. No violence,"
            " romance, or frightening imagery."
        ),
        "ages_6_10": (
            "Reader level: ages 6-10. Use simple vocabulary, clear sentence"
            " structure, mild adventure themes OK. Avoid graphic violence or"
            " mature themes."
        ),
        "ages_11_15": (
            "Reader level: ages 11-15. Use standard vocabulary, moderate"
            " complexity, coming-of-age themes OK."
        ),
        "ages_15_plus": (
            "Reader level: ages 15+. No reading-level restrictions. Any"
            " vocabulary, themes, or sentence complexity."
        ),
    }
    return mapping.get(reader_level, mapping["ages_11_15"])


def _pacing_guidance(pacing: Pacing) -> tuple[str, str, str]:
    """Return (paragraph_range, choice_range, extra_guidance) for pacing level."""
    if pacing == "slow":
        return (
            "4-6",
            "2",
            "\nPACING: Take time with description, atmosphere, and inner thoughts."
            " Choices should feel weighty — every decision matters.",
        )
    if pacing == "fast":
        return (
            "1-3",
            "3-5",
            "\nPACING: Keep the pace brisk — action over description. Give the"
            " player frequent choices to maintain momentum.",
        )
    # moderate — current defaults
    return "2-5", "2-4", ""


def _style_reminder_for_system(narration_style: str) -> str:
    """Style reminder embedded in the system prompt (static per playthrough)."""
    if narration_style == "fourth_wall":
        return (
            "\n\nSTYLE: keep the fourth-wall voice — describe characters in"
            " THIRD person (no 'you' for the reader); the reader is an"
            " external audience the characters can address directly with"
            " asides; choices are options the reader is suggesting to the"
            " characters, NOT first-person actions the reader takes."
        )
    if narration_style == "first_person":
        return "\n\nSTYLE: stay in first-person from the protagonist's POV."
    return ""


def beat_system_prompt(
    *,
    theme: Theme,
    tone: Tone,
    narration_style: NarrationStyle,
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS,
    reader_level: ReaderLevel = "ages_11_15",
    pacing: Pacing = "moderate",
) -> str:
    """Return the system prompt for the beat-generation agent."""
    tighten_threshold = max(target_major_beats - 2, 4)
    style_reminder = _style_reminder_for_system(narration_style)
    para_range, choice_range, pacing_extra = _pacing_guidance(pacing)
    return (
        "You write one beat at a time of a choose-your-own-adventure story.\n"
        f"Theme: {theme.title} — {theme.setting}\n"
        f"Tone: {_describe_tone(tone)}\n"
        f"Narration style: {_narration_style_guidance(narration_style)}\n"
        f"{_reader_level_guidance(reader_level)}\n"
        "Return a StoryBeat with these fields:\n"
        f" - narration: {para_range} paragraphs of prose.\n"
        f" - choices: {choice_range} meaningfully different options. Set to an empty"
        " list ONLY when is_ending is true.\n"
        " - is_major: true ONLY when this beat is a real narrative"
        " checkpoint — new location, revelation, or consequence worth"
        " summarizing into the running story-so-far. Use sparingly:"
        " roughly 1 in every 2-3 beats. Dialogue, small actions, beats"
        " that are mostly setup, and beats that move the characters around"
        " without advancing the headline plot should all be is_major=false.\n"
        " - is_ending: true when the story has reached a satisfying terminal"
        " point — the central conflict has been confronted and clearly"
        " resolved (success, failure, or transformation), all immediate"
        " stakes are settled, and there is no obvious next action for the"
        " characters to take. Stories should escalate toward resolution"
        f" across around {target_major_beats} major beats (give or take a"
        " few); do not let the plot drift indefinitely. By beat"
        f" {tighten_threshold}+ you should be tightening the screws and"
        " driving toward an ending unless the story genuinely calls for"
        " more space. Do not invent new mysteries to delay closure.\n"
        " - new_characters: optional, only for mid-story introductions."
        " The CAST roster shown above is the complete known cast — anyone"
        " new must be introduced via this field, with the SAME shape as"
        " wizard-time characters: id, name, backstory, personality, and a"
        " physical_description vivid enough to paint a portrait from"
        " (colors, build, notable features, signature clothing). The"
        " engine will generate a reference portrait from physical_description"
        " and reuse it across every later scene the character appears in,"
        " so the description IS the visual contract — make it specific.\n\n"
        " - relationship_updates: optional list of new or changed pairwise"
        " relationships between characters. Only include relationships that"
        " clearly changed in this beat. Each has char_a_id, char_b_id"
        " (use the ID in square brackets from the CAST roster),"
        " type (ally, rival, neutral, romantic, mentor, student, family,"
        " stranger), strength (1-5), and a brief context string. If no"
        " relationships changed, return an empty list.\n\n"
        "CONTINUATION RULES:\n"
        "Continue the story with the next beat. Stay consistent with the"
        " cast roster shown in the user prompt (use the named characters;"
        " do not rename or replace them) and with the established events."
        " Move the plot forward; do not retell the prior beat. Mark"
        " is_major=true sparingly — only when this beat is a real narrative"
        " checkpoint (new location, revelation, consequence). Aim for"
        " roughly 1 major beat for every 2-3 beats overall; non-major"
        " beats can still be vivid (dialogue, small actions) but should"
        " not advance the headline plot."
        f"{style_reminder}"
        f"{pacing_extra}"
    )


def illustration_system_prompt() -> str:
    """Return the system prompt for the illustration-planning agent."""
    return (
        "You are a storyboard artist. Given a beat's narration and the full"
        " character roster, decide whether the scene warrants an illustration."
        " Dialogue-only or introspective scenes should return"
        " should_illustrate=false. Return a concise image prompt (not the"
        " narration) describing the key visual: setting, action, lighting,"
        " mood. List featured_character_ids for characters visibly present"
        " (at most four). Prioritize characters who are central to the"
        " scene's action or are named most often in the narration. Every"
        " character mentioned by name in the image prompt MUST appear in"
        " featured_character_ids. Include a one-sentence reasoning."
    )


def _blurb_voice_for_style(style: NarrationStyle) -> str:
    """Pick the blurb voice that matches the chosen narration style."""
    if style == "first_person":
        return (
            "Voice: present tense, first-person from the protagonist's POV"
            ' ("I step into the woods…"). The reader IS the protagonist.'
        )
    if style == "fourth_wall":
        return (
            "Voice: third-person describing the named characters; the"
            " characters may briefly address the reader directly with an"
            " aside or a wink. The reader is an external audience, NOT a"
            " character — do NOT use 'you' to put the reader inside the"
            " story world. Make it clear up front that the reader is here"
            " to watch / nudge / suggest, not to act in person."
        )
    # third_person + fallback
    return (
        'Voice: present tense; second-person address ("you") is allowed'
        " for marketing flair, or third-person describing the protagonist"
        " — pick whichever lands harder for this story."
    )


def blurb_system_prompt(
    theme: Theme,
    characters: list[Character],
    narration_style: NarrationStyle = "third_person",
) -> str:
    """Return the system prompt for the back-cover blurb agent."""
    char_lines = "\n".join(f"- {c.name}: {c.personality.split('.', 1)[0]}" for c in characters)
    return (
        "You are writing the back-cover blurb for a choose-your-own-adventure"
        " book. Output 2-3 short paragraphs (under 150 words total) that hook"
        " the reader: tease the central conflict, hint at stakes, and"
        " introduce the protagonist(s) without spoiling the ending. The blurb"
        " should feel like marketing copy on a paperback. End with one"
        " inviting line that nudges the reader to begin.\n\n"
        f"{_blurb_voice_for_style(narration_style)}\n\n"
        f"Theme: {theme.title}\n"
        f"Setting: {theme.setting}\n"
        f"Premise: {theme.premise}\n\n"
        f"Cast:\n{char_lines}"
    )


def adapt_backstory_system_prompt(theme: Theme) -> str:
    """Return the system prompt for the adapt-backstory agent.

    Rewrites a library character's backstory to fit a new story world while
    keeping every other field (name, personality, physical description) intact
    so the existing portrait stays visually valid.
    """
    return (
        "You adapt a character's backstory to fit a new story world while"
        " preserving everything else that defines them.\n\n"
        "Hard constraints — you MUST NOT change:\n"
        "- The character's name\n"
        "- Their personality traits\n"
        "- Their physical description\n\n"
        "These fields are fixed because the portrait already depicts the"
        " character.\n\n"
        "Rewrite ONLY the backstory so it makes sense in the new theme:\n\n"
        f"Title:   {theme.title}\n"
        f"Setting: {theme.setting}\n"
        f"Premise: {theme.premise}\n\n"
        "Return a single paragraph of roughly 100 words that fits this world."
        " Keep the character's core motivations recognizable — what changes is"
        " how they got here, not who they are."
    )


def summary_system_prompt() -> str:
    """Return the system prompt for the summary agent."""
    return (
        "Summarize the story so far in at most 300 tokens. Focus on plot"
        " progression, character changes, key decisions, and unresolved"
        " threads. Do not retell dialogue verbatim. Return { text: str }."
    )


def recap_system_prompt() -> str:
    """Return the system prompt for the recap agent."""
    return (
        'You write "Previously on..." recaps for an interactive story.'
        " Given a sequence of story events, produce a dramatic recap"
        " (2-4 paragraphs, max 500 tokens) that:\n"
        "- Opens with 'Previously on [story title]...'\n"
        "- Highlights key plot points, character introductions, and turning points\n"
        "- Emphasizes cliffhangers and unresolved threads\n"
        "- Uses dramatic, engaging tone (not dry summary)\n"
        "- Ends by setting up what comes next\n"
        "Return { text: str }."
    )
