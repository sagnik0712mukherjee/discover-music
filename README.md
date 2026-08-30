# Music Discovery App

A single-page music discovery tool: drag a circle onto a genre/mood map,
get 10 matching songs as bubbles, hit PLAY on one to hear the full song
and see similar tracks replace the rest — all live, nothing stored.

## Core interaction

1. User drags a circle anywhere on a 2D map labelled with genres
   (rock, pop, Sufi, ...) and moods (dark, romantic, happy, melancholy, ...).
2. On drop, the nearest anchor tag(s) to that position are resolved.
3. 10 song bubbles appear, sourced live from Last.fm by those tags.
   Songs with thin/no mood-tag data (new releases, niche genres) are
   still shown, placed by genre only.
4. Clicking PLAY on a bubble plays the **full song** (not a preview)
   inline, no page redirect. The other 9 bubbles disappear.
5. Last.fm's similar-tracks data resolves 10 new songs related to the
   one playing, which replace the bubbles that disappeared.

## Tech stack

| Concern                     | Choice                                   | Cost |
|------------------------------|-------------------------------------------|------|
| UI framework                 | Streamlit                                 | Free |
| Draggable map widget          | `streamlit-drawable-canvas`               | Free |
| Genre + mood tagging          | Last.fm API (`tag.getTopTracks`, `track.getTopTags`) | Free |
| "More like this"              | Last.fm API (`track.getSimilar`)          | Free |
| Full-song playback            | YouTube embedded player (IFrame, via HTML embed) | Free |
| Video ID resolution            | YouTube Data API v3 search (lazy, cached per session) | Free (quota-limited) |
| Canonical metadata / new releases | Spotify Search (Client Credentials flow) | Free |
| Hosting                        | Streamlit Community Cloud                | Free |

No song data, tags, or embeddings are stored persistently. Every
lookup happens live, per request; only a session-local cache is used
to avoid re-querying the same song twice in one browser session.

## Repo structure

```
music_discovery_app/
├── app.py                     # Streamlit entrypoint — page layout, session state, wiring
├── config.py                  # env var / API key loading, anchor tag→coordinate map, constants
├── requirements.txt
├── .streamlit/
│   └── config.toml            # theme, server settings
├── models/
│   ├── __init__.py
│   └── song.py                 # Song dataclass: title, artist, tags, video_id, source
├── services/
│   ├── __init__.py
│   ├── lastfm_client.py        # tag.getTopTracks, track.getTopTags, track.getSimilar
│   ├── youtube_client.py       # lazy, cached video_id resolution (search only on PLAY click)
│   └── spotify_client.py       # client-credentials search, for canonical metadata / new releases
├── core/
│   ├── __init__.py
│   ├── mood_map.py             # position → nearest anchor tag(s)
│   ├── recommender.py          # orchestrates tag lookup → candidate merge/dedupe → Song objects
│   └── cache.py                # session-level cache: song → video_id, tag → track list
├── ui/
│   ├── __init__.py
│   ├── map_widget.py           # streamlit-drawable-canvas map + drag position capture
│   └── bubble_grid.py          # 10 song bubbles, PLAY buttons, audio embed
└── README.md
```

## Prerequisites

- Python 3.10+
- Free API keys (all no-cost, sign-up required):
  - **Last.fm API key** — https://www.last.fm/api/account/create
  - **YouTube Data API v3 key** — via Google Cloud Console (free tier: 10,000 quota units/day; a search costs 100 units)
  - **Spotify Client ID + Secret** — via Spotify Developer Dashboard (Client Credentials flow, no user login needed)

## Local setup

```bash
git clone <your-repo-url>
cd music_discovery_app
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in your API keys
streamlit run app.py
```

## Environment variables (`.env`)

```
LASTFM_API_KEY=your_lastfm_key
YOUTUBE_API_KEY=your_youtube_key
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
```

## Deployment (Streamlit Community Cloud — free)

1. Push this repo to a **public** GitHub repository.
2. Go to https://share.streamlit.io → "New app" → connect the repo.
3. Add the same keys from `.env` under the app's **Secrets** settings
   (Streamlit Cloud injects these as environment variables — never
   commit `.env` itself; it's git-ignored).
4. Deploy. You get a public URL: `https://<your-app-name>.streamlit.app`
   — this is what you share with the client. Works on iPad Safari/Chrome
   like any web page.

**Known free-tier behavior:** the app sleeps after ~12 hours with no
traffic. The next visitor sees a "waking up" screen for ~20-30 seconds
before it loads normally — not a bug, just how the free tier works.

## Known constraints

- **YouTube quota (100 free searches/day):** video IDs are resolved
  lazily (only when a song is actually played) and cached for the
  session, to keep lookups well under the daily limit for normal use.
- **Thin tag data:** brand-new releases and niche world-music genres
  may have few/no mood tags on Last.fm yet. These are shown anyway,
  placed by genre alone until mood tags accumulate.
- **Playback is via YouTube's official embedded player** — full song,
  no redirect, but it's a compact video element under the hood, not
  raw audio-only streaming (that would require stream extraction,
  which breaks YouTube's terms and isn't something this app does).

## Roadmap (post-MVP)

- Filters: release year, region/language
- Persistent per-user history/favorites (would introduce minimal storage)
- Custom domain / always-on hosting if client traffic grows