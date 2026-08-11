# OMEN: Punjabi → English lyric translator

Paste a YouTube link to a Punjabi song and OMEN returns the lyrics line by
line: Romanized Punjabi with an English translation underneath each line,
tuned to preserve idiom and poetic intent rather than word-for-word output.

## How it works

1. **Identify**: `yt-dlp` pulls the video's metadata; heuristics split messy,
   inconsistent YouTube titles into a clean *(artist, title)* pair, stripping
   noise like "(Official Video)" and "VEVO".
2. **Verify**: the cleaned pair is searched on the Genius API and hits are
   ranked with RapidFuzz fuzzy matching to confirm the track.
3. **Fetch**: the lyrics text is pulled from the matched Genius page and
   cleaned (section markers stripped, spacing normalized).
4. **Translate**: the cleaned lyrics (never the raw user input) go to an
   OpenAI model with a strict alternating-pair prompt at low temperature; the
   response is parsed into `(punjabi, english)` line pairs so the output
   structure is identical run to run.
5. **Display**: a Tkinter interface renders the pairs and stays responsive by
   running the pipeline on a worker thread.

## Run it

```
cd translateMusic
pip install -r requirements.txt
copy .env.example .env    # then fill in your keys
python main.py
```

You need two keys in `.env`:

- `OPENAI_API_KEY`: from platform.openai.com
- `GENIUS_ACCESS_TOKEN`: from genius.com/api-clients

## Stack

Python 3 · Tkinter · OpenAI Responses API · Genius API · yt-dlp · RapidFuzz
