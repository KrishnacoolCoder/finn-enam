# Updating your currently running FINN V3 (Windows / VS Code)

You already have working data (BSE announcements, custom filings, indexed research). **Protect it.**

1. In VS Code, stop V3 with `Ctrl+C`.
2. Copy the **entire old project folder** to `FINN_ENAM_V3_BACKUP` in Windows Explorer.
3. Extract this archive. Open the *inner* `FINN_ENAM_RELEASE` folder.
4. Copy these **folders from Release 4** into your existing project and accept file replacement: `app`, `static`, `tests`, `docs`, `sample_data`, `sample_documents`.
5. Replace these individual files: `README.md`, `requirements.txt`, `.env.example`, `Dockerfile`, `Procfile` if you want the current versions.
6. **Do not replace your existing `data` folder** or `.venv`. Your saved SQLite database is in `data/finn.sqlite3`. Release 4 migrates new columns on startup.
7. In the existing VS Code terminal (with `.venv` activated):

```powershell
python -m pip install --no-compile --no-cache-dir -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload
```

8. Visit `http://127.0.0.1:8000` and hard refresh: `Ctrl+Shift+R`.
9. In **Intelligence feed**, use **Last 7 days** and verify NTPC and L&T are still there. **Do not import the BSE snapshot again unless you want to test duplicate rejection**. In **AI research**, verify previously indexed documents still appear.

If V4 fails, stop the server and restore the backup folder. Your previous data remains untouched.

**If you're starting fresh**, use the entire Release 4 folder instead of copying files; it generates an empty SQLite database automatically. Click *Load verified BSE sample* to populate it with the included historical primary exchange filings.
