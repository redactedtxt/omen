"""Language-model layer for OMEN.

Takes the *cleaned* track metadata produced by core_lyrics (never the raw
YouTube link the user typed) and asks the model for a line-by-line
Romanized-Punjabi / English translation, then parses the response into a
stable list of line pairs so the GUI renders the same structure every run.
"""

from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set — see .env.example.")
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


@dataclass
class LinePair:
    punjabi: str
    english: str


def _build_prompt(artist: str, title: str, lyrics: str) -> str:
    return f"""You are translating a Punjabi song for a listener who reads Romanized Punjabi.

Song: "{title}"
Artist: {artist}

Here are the song's lyrics:

{lyrics}

For EVERY line of the lyrics above, output the line in Romanized Punjabi
(transliterate it if it is written in Gurmukhi script) followed by an English
translation that preserves meaning, idioms, and poetic intent rather than
word-for-word literalism.

Format the output EXACTLY as follows, with one blank line between pairs:

Romanized Punjabi line
English translation of that line

Romanized Punjabi line
English translation of that line

Rules:
- ONLY the alternating pairs. No headings, commentary, notes, or analysis.
- Keep the lines in their original order and do not skip any line.
- End immediately after the final translated line.
"""


def translate_lyrics(artist: str, title: str, lyrics: str) -> list[LinePair]:
    """Translate the provided lyrics text and parse it into line pairs.

    Raises RuntimeError with a readable message if the model can't help.
    """
    if not lyrics.strip():
        raise RuntimeError(
            f'Found the song "{title}" by {artist}, but its lyrics page was empty.'
        )

    response = _get_client().responses.create(
        model=config.OPENAI_MODEL,
        input=_build_prompt(artist, title, lyrics),
        temperature=0.2,
        max_output_tokens=8192,
    )
    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("The model returned an empty response. Try again.")

    pairs = parse_pairs(text)
    if not pairs:
        raise RuntimeError("The model returned an unexpected format. Try again.")
    return pairs


def parse_pairs(text: str) -> list[LinePair]:
    """Parse alternating Punjabi/English lines into pairs.

    Tolerates messy model output: stray blank lines, a missing final English
    line, or blocks with an odd number of lines.
    """
    pairs: list[LinePair] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for i in range(0, len(lines) - 1, 2):
        pairs.append(LinePair(punjabi=lines[i], english=lines[i + 1]))
    if len(lines) % 2 == 1:
        pairs.append(LinePair(punjabi=lines[-1], english=""))

    return pairs
