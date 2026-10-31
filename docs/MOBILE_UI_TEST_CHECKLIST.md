# FINN mobile UI test checklist

Test each viewport at 100% browser zoom: **360 × 844**, **390 × 844**, and
**430 × 844 CSS pixels**. Start with a hard reload. Counts vary with publication
dates and available filings; compare behavior rather than expecting fixed counts.

## Recorded verification

Automated Chromium/Brave mobile emulation passed at all three widths:

| Check | 360px | 390px | 430px |
|---|---|---|---|
| Five bottom tabs and view switching | Pass | Pass | Pass |
| No document overflow or out-of-bounds visible content | Pass | Pass | Pass |
| Interactive targets at least 44 × 44px | Pass | Pass | Pass |
| 24h / 3d / 7d digest requests and selection | Pass | Pass | Pass |
| Priority ordering and routine collapse | Pass | Pass | Pass |
| Source details, research answers and stacked tables | Pass | Pass | Pass |
| Skeletons and recovery from a failed feed request | Pass | Pass | Pass |
| Older requests cannot replace a newer filter result | Pass | Pass | Pass |
| Settings saved and retained after reload | Pass | Pass | Pass |
| Browser backup restores a simulated server reset | Pass | Pass | Pass |
| Invalid thresholds do not submit | Pass | Pass | Pass |
| Uncaught JavaScript errors | None | None | None |

Additional 360px checks passed for existing NTPC quarterly comparisons, long PDF
and XML filenames, expanded import tools, and the add-filing dialog. All **177
pytest tests passed**, including settings validation, persistence, backward
compatibility, filing-alert preferences and exclusion of synthetic demos.

Research responses and secondary company snapshots were mocked for browser
layout tests; these checks did not call a paid model or verify financial figures.
The browser used real local application routes and an isolated copy of the seed
database for filings, settings, documents and existing financial comparisons.

## Brief / digest

- [ ] Open Brief; bottom navigation remains visible and marks Brief active.
- [ ] Tap 24h, 3d and 7d. Exactly one is selected each time.
- [ ] The time label, important-filing count and investor brief update together.
- [ ] Tap Download brief while changing windows; its URL uses the selected hours
      (24, 72 or 168), not the previous selection.
- [ ] Reload; the last selected digest window is remembered in this browser.
- [ ] Under a slow connection, skeletons appear and stale counts are replaced by
      loading status. Reduced-motion mode stops the shimmer.

## Feed and filing cards

- [ ] The time window is visible; Filters & tools opens the other controls.
- [ ] Change company, minimum priority and event type; results match all filters.
- [ ] Main cards descend by priority, with newer events resolving equal scores.
- [ ] Each card shows company/ticker, event chip, score, a one-line reason, source
      label/date, and an original-filing link when a URL exists.
- [ ] Evidence & sources exposes the full reason, excerpt and underlying links.
- [ ] Routine notices begin collapsed under **N routine filings**. N counts
      underlying filings, not grouped cards. Tap to open and close them.
- [ ] Unclassified filings remain visible for review instead of being treated as
      routine solely because their score is low.
- [ ] A source link opens separately; returning to FINN retains the current view.
- [ ] Rapidly change 24h → 3d → 7d. A delayed older response cannot overwrite 7d.
- [ ] On a failed request, skeletons clear, a readable error appears, and Try
      again works after connectivity returns.
- [ ] Automatic update status and optional XML/manual tools remain reachable
      within Filters & tools.

## Alerts and persistence

- [ ] Open Alerts from the bottom bar or the header gear; it is a full screen.
- [ ] Set price to 3.5%, volume to 2.25× and filing priority to 75.
- [ ] Clear event types, select Financial results, and save.
- [ ] Reload and revisit Alerts. Values and selected event types remain saved.
- [ ] Filing alerts contain only selected types above the saved priority. The
      full Feed remains available independently of these alert preferences.
- [ ] Clear all types and save: filing alerts become empty, not “all types”.
- [ ] Try price 0 or volume 0. Native validation prevents submission; the server
      independently rejects invalid values.
- [ ] A failed save displays Not saved; it must not claim success.
- [ ] Market threshold changes apply when EOD market data is next evaluated.

Settings are shared by this FINN workspace and stored in SQLite. A browser stores
its last saved copy and can restore it when a host restart loads a seed with no
settings revision. Another user's newer server settings take precedence while a
server revision exists. If both server data and browser storage are erased, the
seed defaults apply; cross-device durability requires durable server storage.

## Research, portfolio and financial tools

- [ ] Company & source documents expands/collapses without shifting content
      beyond the screen edge. Selecting a portfolio company opens its research.
- [ ] The five research cards, question input, answer skeleton, citations and
      source links remain usable at every width.
- [ ] Long document names, URLs, ticker symbols and replies wrap within the view.
- [ ] Secondary financial tables become labelled rows on mobile; no sideways
      swipe is needed to read the quarters and values.
- [ ] Quarterly forms, comparison cards and original-source links fit at 360px.
- [ ] Verification badges retain their meaning; UI changes never auto-verify
      figures or weaken HTTPS source validation.
- [ ] File pickers, manual filing dialog and XML import controls fit when opened.

## Final checks on physical phones

- [ ] Scroll to the last action in each view; bottom navigation does not cover it.
- [ ] Tap controls near the screen edges and confirm adequate spacing.
- [ ] Check iOS Safari and Android Chrome with the on-screen keyboard open.
- [ ] Check the home indicator / notch safe area in portrait and landscape.
- [ ] Test system large text, 200% zoom, keyboard focus and screen-reader labels.
- [ ] Confirm contrast, native selects and external PDF handling on each OS.

Physical-device Safari/Android checks are manual follow-ups; Chromium emulation
does not establish browser parity for OS keyboards, notches or native controls.
