from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from rapidfuzz import fuzz
from yt_dlp import YoutubeDL

import config


# ----------------------------
# 1) YouTube -> (artist, title)
# ----------------------------

@dataclass
class TrackInfo:
    artist: Optional[str]
    title: Optional[str]
    raw_title: str
    video_id: Optional[str] = None


def extract_track_info_from_youtube(url: str) -> TrackInfo:
    """
    Extracts best-effort artist + title from a YouTube link using yt-dlp metadata.
    This is heuristic-based because YouTube titles aren't consistent.
    """
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        # Don't spam stdout; errors will raise exceptions we catch upstream
        "extract_flat": False,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    raw_title = (info.get("title") or "").strip()
    channel = (info.get("channel") or info.get("uploader") or "").strip()
    video_id = info.get("id")

    # Try to parse common patterns: "Artist - Song", "Artist – Song", "Artist | Song"
    artist, title = parse_artist_title_from_text(raw_title)

    # If we couldn't parse artist/title from title, use channel as a fallback for artist.
    # (Not always correct, but better than None.)
    if not artist and channel:
        artist = channel

    # Clean up obvious noise in title
    if title:
        title = clean_title_noise(title)
    if artist:
        artist = clean_artist_noise(artist)

    return TrackInfo(artist=artist, title=title, raw_title=raw_title, video_id=video_id)


def parse_artist_title_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Attempts to split a title into (artist, song title).
    Returns (None, None) if no reliable split is found.
    """
    if not text:
        return None, None

    # Pipe-delimited titles ("295 (Official Audio) | Sidhu Moose Wala | The Kidd |
    # Moosetape") are the norm for Punjabi releases: first segment is the song,
    # second is the artist, the rest is producer/album noise.
    if " | " in text:
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) >= 2:
            return parts[1], parts[0]

    # Dash-style titles are "Artist - Song"
    candidates = [
        " - ",
        " – ",  # en dash
        " — ",  # em dash
        " : ",
    ]

    for sep in candidates:
        if sep in text:
            left, right = text.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right

    return None, text.strip()  # fallback: treat entire text as title


def clean_title_noise(title: str) -> str:
    # Remove common bracketed extras: (Official Video), [Lyrics], etc.
    title = re.sub(r"\[(.*?)\]", "", title).strip()
    title = re.sub(r"\((.*?)\)", "", title).strip()
    # Remove common keywords
    noise = [
        "official video", "official music video", "lyrics", "lyric video",
        "audio", "hd", "4k", "visualizer", "mv", "full song"
    ]
    lowered = title.lower()
    for n in noise:
        if n in lowered:
            # remove the word but keep spacing sane
            pattern = re.compile(re.escape(n), re.IGNORECASE)
            title = pattern.sub("", title)
            lowered = title.lower()
    # Collapse whitespace
    title = re.sub(r"\s{2,}", " ", title).strip(" -|:")
    return title.strip()


def clean_artist_noise(artist: str) -> str:
    # Remove suffixes like "Official" / "VEVO"
    artist = re.sub(r"\b(vevo|official)\b", "", artist, flags=re.IGNORECASE).strip()
    artist = re.sub(r"\s{2,}", " ", artist).strip()
    return artist


# ----------------------------
# 2) Genius Search -> Lyrics URL
# ----------------------------

GENIUS_API_BASE = "https://api.genius.com"


@dataclass
class GeniusHit:
    full_title: str
    artist_names: str
    url: str
    id: int
    score: int  # our fuzzy score


def genius_search_song(
    query: str,
    access_token: str,
    timeout_s: int = 15,
    limit_hits: int = 10
) -> list[GeniusHit]:
    """
    Uses Genius search endpoint and returns ranked hits.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"q": query}

    r = requests.get(
        f"{GENIUS_API_BASE}/search",
        headers=headers,
        params=params,
        timeout=timeout_s,
    )
    r.raise_for_status()
    data = r.json()

    hits = data.get("response", {}).get("hits", [])[:limit_hits]

    results: list[GeniusHit] = []
    for h in hits:
        result = h.get("result") or {}
        full_title = (result.get("full_title") or "").strip()
        url = (result.get("url") or "").strip()
        artist_names = (result.get("artist_names") or "").strip()
        rid = int(result.get("id") or 0)

        results.append(
            GeniusHit(
                full_title=full_title,
                artist_names=artist_names,
                url=url,
                id=rid,
                score=0,
            )
        )

    return results


def pick_best_genius_hit(
    hits: list[GeniusHit],
    artist: Optional[str],
    title: Optional[str]
) -> Optional[GeniusHit]:
    """
    Rank Genius hits using fuzzy matching against artist/title.
    """
    if not hits:
        return None

    # If we have nothing to compare, return the first hit.
    if not artist and not title:
        best = hits[0]
        best.score = 0
        return best

    best_hit = None
    best_score = -1

    for hit in hits:
        # Compare title-to-title and artist-to-artist separately. A combined
        # token_set comparison lets spam pages that merely contain the artist's
        # name outrank the actual song page.
        s_title = fuzz.token_set_ratio(title or "", hit.full_title) if title else 0
        s_artist = fuzz.token_set_ratio(artist or "", hit.artist_names) if artist else 0
        score = int(0.6 * s_title + 0.4 * s_artist)
        if score > best_score:
            best_score = score
            best_hit = hit

    if best_hit:
        best_hit.score = best_score
    return best_hit


def find_genius_lyrics_page_from_youtube(
    youtube_url: str,
    genius_access_token: str
) -> Tuple[TrackInfo, Optional[GeniusHit]]:
    """
    Full pipeline:
    YouTube URL -> TrackInfo -> Genius Search -> best lyrics page URL
    Returns (track_info, best_hit or None).
    """
    
    track = extract_track_info_from_youtube(youtube_url)

    # Build a search query. If artist missing, query just title.
    if track.artist and track.title:
        query = f"{track.artist} {track.title}"
    else:
        query = track.raw_title

    hits = genius_search_song(query=query, access_token=genius_access_token)
    if not hits and track.title:
        # Retry with the bare title — artist strings from YouTube are often noisy
        hits = genius_search_song(query=track.title, access_token=genius_access_token)
    best = pick_best_genius_hit(hits, artist=track.artist, title=track.title)

    return track, best


# ----------------------------
# 3) Lyrics page -> lyrics text
# ----------------------------

def fetch_lyrics_text(lyrics_url: str, timeout_s: int = 15) -> str:
    """
    Fetch the Romanized lyrics text from a Genius lyrics page.
    Genius renders lyrics in divs marked data-lyrics-container.
    """
    from bs4 import BeautifulSoup

    r = requests.get(
        lyrics_url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        timeout=timeout_s,
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    containers = soup.select("div[data-lyrics-container='true']")

    lines: list[str] = []
    for container in containers:
        for br in container.find_all("br"):
            br.replace_with("\n")
        lines.append(container.get_text())

    text = "\n".join(lines)
    # Drop section markers like [Chorus] / [Verse 1] and collapse blank runs
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def resolve_track(youtube_url: str) -> Tuple[TrackInfo, Optional[GeniusHit]]:
    """
    Public entry point used by the GUI:
    YouTube URL -> cleaned (artist, title) -> best Genius lyrics-page match.
    Raises RuntimeError with a readable message on failure.
    """
    if not config.GENIUS_ACCESS_TOKEN:
        raise RuntimeError("GENIUS_ACCESS_TOKEN is not set — see .env.example.")

    try:
        return find_genius_lyrics_page_from_youtube(
            youtube_url, config.GENIUS_ACCESS_TOKEN
        )
    except Exception as exc:
        raise RuntimeError(f"Could not resolve the track: {exc}") from exc


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else input("YouTube URL: ").strip()
    track_info, hit = resolve_track(url)

    print("YouTube title:", track_info.raw_title)
    print("Parsed artist:", track_info.artist)
    print("Parsed song  :", track_info.title)

    if hit:
        print("\nBest Genius match:")
        print("  full_title:", hit.full_title)
        print("  artists   :", hit.artist_names)
        print("  score     :", hit.score)
        print("  lyrics url:", hit.url)
    else:
        print("\nNo Genius match found.")