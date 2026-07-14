# Practice Makes Perfect

Static English conversation site for GitHub Pages.

## Local

```bash
npm start
```

## GitHub Pages

1. Repo Settings → Pages → Source: **Deploy from a branch**
2. Branch: `main` / root (`/`)
3. Site URL: `https://yhmist.github.io/english/`

## Structure

- `index.html` / `404.html` — page shell (404 enables deep links on Pages)
- `css/style.css` — styles
- `js/app.js` — catalogue, word lookup, audio seek
- `data/` — corpus + sentence timings
- `pmp_audios/` — audio files
