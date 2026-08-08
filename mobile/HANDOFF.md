# Al‑Muqri (المقرئ) — developer handoff

A **Capacitor** Android app that runs an on‑device Qur'an‑recitation feedback model.
Everything needed to build, test, and publish is in this `mobile/` folder.

## What it does
Select word(s)/verses → recite → on‑device AI marks each word green/red (vowels, madd,
articulation). Plus live mode, word‑by‑word audio, and Husary "Listen". Fully offline for
the core; some reference audio is downloaded on demand.

## Architecture
- **Capacitor** web app in `www/` (single `index.html` + `engine.js`; a fetch‑shim serves
  `quran_data.json` / `quran_targets.json` and routes /selection, /chunk, /reference_audio).
- **Native plugin** `android/app/src/main/java/com/almuqri/app/MuqriNativePlugin.java`:
  runs the ONNX model via `com.microsoft.onnxruntime:onnxruntime-android` (int8, 4‑second
  window, multi‑core CPU), does CTC decode; also handles Husary per‑chapter CDN download
  and the on‑demand audio asset pack.
- **Play Asset Delivery** (keeps base < 200 MB):
  - `android/model_pack` — **install‑time** pack, 838 MB model (`assets/model/muaalem.onnx`),
    read by the plugin via `getAssets()`.
  - `android/audio_pack` — **on‑demand** pack, ~382 MB word‑by‑word audio
    (`assets/audio/wbw/`), fetched with `AssetPackManager`.
  - Base app: Qur'an text, phoneme targets, Husary word‑timings (`www/audio/husary_timings`),
    fonts, code. Husary mp3s download per‑chapter from `audio-cdn.tarteel.ai`.

## Prerequisites
- Node 18+ and npm
- Android SDK (compileSdk 34, build‑tools 34/35), JDK 17+ (project tested with JDK 21)
- (For testing PAD) `bundletool` — https://github.com/google/bundletool/releases

## Build
```bash
cd mobile
npm install
npx cap sync android
cd android
# signed build needs your own key.properties + keystore (see Signing)
./gradlew bundleRelease     # -> app/build/outputs/bundle/release/app-release.aab  (upload to Play)
./gradlew assembleRelease   # -> app/build/outputs/apk/release/app-release.apk     (NOTE: no asset packs)
```

## Signing
`app/build.gradle` reads `android/key.properties` (git‑ignored, NOT included in this handoff):
```
storeFile=my-release.jks
storePassword=...
keyAlias=...
keyPassword=...
```
Generate your own upload key:
```bash
keytool -genkeypair -v -keystore my-release.jks -alias upload \
  -keyalg RSA -keysize 2048 -validity 10000
```
Publish with **Google Play App Signing** (recommended). Keep the keystore + passwords backed up.

## Testing Play Asset Delivery (IMPORTANT)
A plain `adb install app-release.apk` will crash/misbehave — asset packs are NOT in a bare
APK. Test the bundle with bundletool local testing:
```bash
java -jar bundletool.jar build-apks --bundle=app/build/outputs/bundle/release/app-release.aab \
  --output=app.apks --local-testing \
  --ks=my-release.jks --ks-pass=pass:... --ks-key-alias=upload --key-pass=pass:...
# uninstall any existing com.almuqri.app first if signatures differ
java -jar bundletool.jar install-apks --apks=app.apks
```
On Play, upload the **.aab**; Google delivers the packs.

## Store listing assets
In `store/`: `play-icon-512.png`, `feature-graphic-1024x500.png`, `listing.md`
(name/short/full description), `privacy-policy.html`, and `README-publishing.md`
(full Play Console walkthrough).

## Notes / to confirm
- **Audio licensing:** confirm rights to distribute the Husary (via QUL/Tarteel CDN) and the
  word‑by‑word mujawwad recitations before Production.
- **Model:** "quran‑muaalem" Wav2Vec2‑BERT multi‑level CTC (arXiv:2509.00094), exported to
  ONNX and int8‑quantized (4 s / 64000‑sample fixed window). The built model file is included
  in `android/model_pack`; no retraining needed to build the app.
- App id: `com.almuqri.app`; versionCode 1 / versionName "1.0" in `app/build.gradle`.
```
