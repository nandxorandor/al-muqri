# Al‑Muqri — Play Store publishing pack

Everything you need to create the listing is in this folder.

## Files here
- `play-icon-512.png` — the **app icon** (512×512). Upload under Store listing → App icon.
- `feature-graphic-1024x500.png` — the **feature graphic**. Upload under Store listing → Feature graphic.
- `listing.md` — the **app name, short description, full description** to paste in.
- `privacy-policy.html` — your **privacy policy** page (host it, see below).

## The AAB to upload
`mobile/android/app/build/outputs/bundle/release/app-release.aab`
(Production → Create release → upload this .aab)

---

## Step‑by‑step
1. **Create a Google Play Developer account** — https://play.google.com/console ($25 one‑time).
2. **Create app** → name "Al‑Muqri · المقرئ", Free, App.
3. **Host the privacy policy:**
   - Easiest free option: create a public GitHub repo, add `privacy-policy.html`, enable
     **Settings → Pages** (deploy from branch). You'll get a URL like
     `https://<you>.github.io/<repo>/privacy-policy.html`.
   - Before hosting, edit `privacy-policy.html`: replace `[DATE]` and `[YOUR CONTACT EMAIL]`.
   - Put that URL in Play Console → App content → Privacy policy (and in `listing.md`).
4. **Store listing:** paste name / short / full description from `listing.md`; upload
   `play-icon-512.png` and `feature-graphic-1024x500.png`.
5. **Screenshots** (2–8, phone): on your phone, take screenshots of:
   - the mushaf page with some words green/red after reciting,
   - a word selected with the Listen button,
   - the Mistakes panel,
   - the surah/page picker.
   Upload them under Phone screenshots.
6. **App content forms:** Privacy policy URL, Data safety (declare: *no data collected*;
   microphone used *on device only, not shared*), Content rating (fill the questionnaire —
   this is an educational/reference app), Target audience, Ads = No.
7. **Production → Create release:** upload `app-release.aab`, add release notes, roll out.
   - Recommended first: use **Internal testing** track to try it from the Play Store
     yourself and with your friend before going to Production.

## Notes
- Google will use **Play App Signing**; keep your upload keystore
  (`mobile/android/al-muqri-release.jks`) + password backed up regardless.
- Make sure you're comfortable that you may distribute the Husary/mujawwad recitation
  audio (licensing) before going to Production.
