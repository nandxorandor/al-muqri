package com.almuqri.app;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import android.util.Base64;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

import com.google.android.play.core.assetpacks.AssetPackLocation;
import com.google.android.play.core.assetpacks.AssetPackManager;
import com.google.android.play.core.assetpacks.AssetPackManagerFactory;
import com.google.android.play.core.assetpacks.AssetPackState;
import com.google.android.play.core.assetpacks.AssetPackStateUpdateListener;
import com.google.android.play.core.assetpacks.model.AssetPackStatus;

/**
 * Native ONNX Runtime bridge for the recitation model. Runs on all CPU cores
 * with optimized int8 kernels (XNNPACK when available) — far faster than the
 * single-thread WASM engine used before. The model is memory-mapped from a
 * file (copied once out of assets) so the 611 MB weights never sit in the Java
 * heap. Scoring/decoding stays in JS; this returns the collapsed phoneme ids.
 */
@CapacitorPlugin(name = "MuqriNative")
public class MuqriNativePlugin extends Plugin {

    // Model ships in the install-time asset pack "model_pack" -> its assets are
    // merged into the normal AssetManager namespace at assets/model/...
    private static final String ASSET_MODEL = "model/muaalem.onnx";
    private static final String AUDIO_PACK = "audio_pack";  // on-demand (word-by-word)
    // Fixed audio window the model expects (samples @ 16 kHz). 4s window.
    private static final int N = 64000;

    private OrtEnvironment env;
    private OrtSession session;

    private synchronized void ensureSession() throws Exception {
        if (session != null) return;
        env = OrtEnvironment.getEnvironment();

        File out = new File(getContext().getFilesDir(), "muaalem.onnx");
        long assetLen = assetLength(ASSET_MODEL);
        if (!out.exists() || out.length() != assetLen) {
            copyAsset(ASSET_MODEL, out);
        }

        OrtSession.SessionOptions opts = new OrtSession.SessionOptions();
        int cores = Math.max(2, Runtime.getRuntime().availableProcessors());
        opts.setIntraOpNumThreads(cores);
        opts.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
        // NOTE: XNNPACK EP cannot run this model's ConvInteger (dynamic-int8)
        // nodes, so we use the standard multi-threaded CPU EP, which implements
        // them. Still a big win over the single-thread WASM engine.

        // createSession(path, ...) memory-maps the weights -> low RAM footprint.
        session = env.createSession(out.getAbsolutePath(), opts);
    }

    private long assetLength(String name) throws Exception {
        try (android.content.res.AssetFileDescriptor fd =
                     getContext().getAssets().openFd(name)) {
            return fd.getLength();
        } catch (Exception e) {
            // openFd fails on compressed assets; fall back to streaming count.
            try (InputStream is = getContext().getAssets().open(name)) {
                long total = 0; byte[] b = new byte[1 << 16]; int r;
                while ((r = is.read(b)) > 0) total += r;
                return total;
            }
        }
    }

    private void copyAsset(String name, File dst) throws Exception {
        try (InputStream is = getContext().getAssets().open(name);
             OutputStream os = new FileOutputStream(dst)) {
            byte[] buf = new byte[1 << 16]; int r;
            while ((r = is.read(buf)) > 0) os.write(buf, 0, r);
            os.flush();
        }
    }

    // ---- Husary reference-audio downloads (native HTTP bypasses WebView CORS) ----
    private File husaryDir() {
        File d = new File(getContext().getFilesDir(), "husary");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    /** Report the folder downloaded Husary mp3s live in (for convertFileSrc). */
    @PluginMethod
    public void getHusaryDir(PluginCall call) {
        call.resolve(new JSObject().put("dir", husaryDir().getAbsolutePath()));
    }

    /** How many ayat of a surah are already downloaded. */
    @PluginMethod
    public void husaryStatus(PluginCall call) {
        int sura = call.getInt("sura", 0), total = call.getInt("count", 0);
        File d = husaryDir(); int have = 0;
        for (int a = 1; a <= total; a++)
            if (new File(d, String.format("%03d%03d.mp3", sura, a)).length() > 0) have++;
        call.resolve(new JSObject().put("have", have).put("total", total)
                .put("dir", d.getAbsolutePath()).put("done", total > 0 && have >= total));
    }

    /** Download one ayah's Husary mp3 from the CDN to internal storage. */
    @PluginMethod
    public void downloadHusaryAyah(PluginCall call) {
        int sura = call.getInt("sura", 0), aya = call.getInt("aya", 0);
        File f = new File(husaryDir(), String.format("%03d%03d.mp3", sura, aya));
        if (f.length() > 0) { call.resolve(new JSObject().put("ok", true).put("cached", true)); return; }
        java.net.HttpURLConnection c = null;
        try {
            String url = "https://audio-cdn.tarteel.ai/quran/husary/"
                    + String.format("%03d%03d.mp3", sura, aya);
            c = (java.net.HttpURLConnection) new java.net.URL(url).openConnection();
            c.setConnectTimeout(15000); c.setReadTimeout(30000);
            int code = c.getResponseCode();
            if (code != 200) { call.reject("http " + code); return; }
            File tmp = new File(f.getParentFile(), f.getName() + ".part");
            try (InputStream is = c.getInputStream(); OutputStream os = new FileOutputStream(tmp)) {
                byte[] b = new byte[1 << 15]; int r;
                while ((r = is.read(b)) > 0) os.write(b, 0, r);
            }
            if (!tmp.renameTo(f)) { tmp.delete(); call.reject("save failed"); return; }
            call.resolve(new JSObject().put("ok", true));
        } catch (Exception e) {
            call.reject("dl failed: " + e.getMessage());
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ---- Play Asset Delivery: on-demand word-by-word audio pack ----
    private AssetPackManager apm() { return AssetPackManagerFactory.getInstance(getContext()); }

    /** If the audio pack is already downloaded, return its assets folder path. */
    @PluginMethod
    public void audioPackLocation(PluginCall call) {
        AssetPackLocation loc = apm().getPackLocation(AUDIO_PACK);
        JSObject o = new JSObject();
        if (loc != null && loc.assetsPath() != null) o.put("ready", true).put("path", loc.assetsPath());
        else o.put("ready", false);
        call.resolve(o);
    }

    /** Download the on-demand audio pack (if needed), emitting 'assetProgress'. */
    @PluginMethod
    public void ensureAudioPack(final PluginCall call) {
        final AssetPackManager m = apm();
        AssetPackLocation loc = m.getPackLocation(AUDIO_PACK);
        if (loc != null && loc.assetsPath() != null) {
            call.resolve(new JSObject().put("ready", true).put("path", loc.assetsPath()));
            return;
        }
        final boolean[] done = {false};
        AssetPackStateUpdateListener listener = new AssetPackStateUpdateListener() {
            @Override public void onStateUpdate(AssetPackState state) {
                if (!AUDIO_PACK.equals(state.name())) return;
                switch (state.status()) {
                    case AssetPackStatus.COMPLETED:
                        if (done[0]) return; done[0] = true;
                        m.unregisterListener(this);
                        AssetPackLocation l = m.getPackLocation(AUDIO_PACK);
                        call.resolve(new JSObject().put("ready", true)
                                .put("path", l != null ? l.assetsPath() : ""));
                        break;
                    case AssetPackStatus.FAILED:
                        if (done[0]) return; done[0] = true;
                        m.unregisterListener(this);
                        call.reject("audio pack failed: " + state.errorCode());
                        break;
                    case AssetPackStatus.REQUIRES_USER_CONFIRMATION:
                        if (getActivity() != null) m.showConfirmationDialog(getActivity());
                        break;
                    case AssetPackStatus.DOWNLOADING:
                    case AssetPackStatus.TRANSFERRING:
                        notifyListeners("assetProgress", new JSObject()
                                .put("done", state.bytesDownloaded())
                                .put("total", state.totalBytesToDownload()));
                        break;
                    default:
                        break;
                }
            }
        };
        m.registerListener(listener);
        m.fetch(Collections.singletonList(AUDIO_PACK));
    }

    /** Load/warm the model so the first recitation isn't slowed by init. */
    @PluginMethod
    public void load(PluginCall call) {
        try {
            ensureSession();
            call.resolve(new JSObject().put("ready", true));
        } catch (Exception e) {
            call.reject("load failed: " + e.getMessage(), e);
        }
    }

    /**
     * Run inference. Input: { audio: base64(Float32 little-endian PCM @16k) }.
     * Output: { ids: [int,...] } — CTC-collapsed non-blank phoneme ids.
     */
    @PluginMethod
    public void infer(PluginCall call) {
        OnnxTensor tensor = null;
        OrtSession.Result res = null;
        try {
            ensureSession();
            byte[] raw = Base64.decode(call.getString("audio", ""), Base64.DEFAULT);
            FloatBuffer src = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
            float[] in = new float[N];
            int n = Math.min(src.remaining(), N);
            src.get(in, 0, n);                       // rest stays zero-padded

            tensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(in), new long[]{ N });
            Map<String, OnnxTensor> inputs = Collections.singletonMap("audio", tensor);
            res = session.run(inputs);

            float[][][] logits = (float[][][]) res.get("logits_phonemes").get().getValue();
            float[][] frames = logits[0];            // [frames][classes]
            int total = frames.length;

            // Decode ONLY the frames covering the real audio; the zero-padding
            // frames otherwise decode into trailing garbage phonemes that wreck
            // the edit-distance scoring. valid = real samples before padding.
            int valid = call.getInt("valid", N);
            int vf = Math.round(valid * (float) total / (float) N);
            if (vf < 1) vf = 1;
            if (vf > total) vf = total;

            JSArray ids = new JSArray();
            int prev = 0;
            for (int fi = 0; fi < vf; fi++) {
                float[] row = frames[fi];
                int best = 0; float bv = row[0];
                for (int c = 1; c < row.length; c++) if (row[c] > bv) { bv = row[c]; best = c; }
                if (best == 0) { prev = 0; continue; } // blank
                if (best == prev) continue;            // collapse repeats
                ids.put(best);
                prev = best;
            }
            call.resolve(new JSObject().put("ids", ids));
        } catch (Exception e) {
            call.reject("infer failed: " + e.getMessage(), e);
        } finally {
            if (res != null) res.close();
            if (tensor != null) tensor.close();
        }
    }
}
