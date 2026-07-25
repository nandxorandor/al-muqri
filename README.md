# 📖 المقرئ · Al‑Muqri’

## 🎬 Demo · عرض توضيحي

<!-- Replace the link below with your video. Easiest: edit this README on
     github.com and DRAG-AND-DROP the mp4 here (auto-hosts + inline player, ≤10 MB).
     Or commit it to docs/demo.mp4 and keep the raw URL line below. -->

https://www.youtube.com/watch?v=qnHhzcH6kX8
---

<div dir="rtl">

## 🇸🇦 بالعربية

تطبيق ويب يعمل محليًا يساعدك على **تلاوة القرآن الكريم مع تصحيح فوري على مستوى
الحروف والصوتيات** لنُطقك وتجويدك، بالاعتماد على نموذج
[`quran-muaalem`](https://arxiv.org/abs/2509.00094). اقرأ من صفحة تشبه المصحف،
اختر كلمة أو عدّة كلمات بالسحب (حتى عبر أكثر من آية)، استمع إلى التلاوة المرجعية،
ثم اقرأ لترى كل كلمة تتحوّل إلى الأخضر (صحيح) أو الأحمر (خطأ) مع شرحٍ مبسّط للخطأ.

### ✨ المزايا

- **جميع السور الـ114**، مرتّبة حسب **أرقام صفحات المصحف** (مثل «صفحة ١ · آية ١–٧»).
- **تصحيح مباشر** للتلاوة (أخضر = صحيح، أحمر = خطأ) مع بيان الحرف أو الحركة أو
  طول المدّ محلّ الخطأ.
- **تحديد الكلمات** — انقر أو اسحب لاختيار كلمة أو عدّة كلمات أو مقطع **يمتدّ عبر
  عدّة آيات**، ثم استمع إليه أو اختبر نطقك عليه.
- **نمطان للاستماع:** تجويد (تلاوة الحصري بالترتيل) أو قراءة عادية (كلمة‑بكلمة بنطق واضح).
- **لوحة الأخطاء** مع إحصاء مستمر وتفاصيل صوتية لكل كلمة.
- **حجم خط قابل للتعديل**، خط عربي أصيل، وواجهة ثنائية اللغة.
- **يعمل دون إنترنت** بعد التهيئة، ويمكن **مشاركته على شبكة المنزل** ليعمل الميكروفون
  على بقية الأجهزة.

### 🧩 المتطلّبات والتشغيل

1. أنشئ بيئة **Python 3.11** وثبّت الحزم: `pip install -r requirements.txt`
   (سيُنزّل المحرّك نموذجه من الإنترنت عند أول تشغيل).
2. **الصوت كلمة‑بكلمة** مُضمَّن في المستودع داخل `reference_audio/mujawwad/`
   (صوت التجويد للحصري يُنزَّل تلقائيًا).
3. للتشغيل على جهازك: `python run.py`
4. للمشاركة على شبكة المنزل مع عمل الميكروفون: نفّذ `set HTTPS=1` ثم `python run.py`،
   أو انقر نقرًا مزدوجًا على **`share.bat`**، وافتح على بقية الأجهزة العنوان المطبوع
   مثل `https://192.168.x.x:7070` (اقبل تحذير الشهادة مرّة واحدة).

### 🙏 شكر وتراخيص

- نموذج النطق `quran-muaalem` ([arXiv:2509.00094](https://arxiv.org/abs/2509.00094)).
- نصّ ومعالجة صوتيات القرآن `quran-transcript`.
- صوت كلمة‑بكلمة: «Quran Word‑By‑Word Audio Dataset» (رخصة Apache‑2.0).
- صوت التجويد: تلاوة الحصري عبر خدمة **QUL / Tarteel**.
- الخط: *Amiri Quran*، واختياريًا *خط مجمع الملك فهد (حفص)*.

> **يُرجى استخدام التطبيق باحترامٍ** لقدسية القرآن الكريم، والتحقّق من تلاوتك مع
> **مُعلّمٍ مُتقن** — فالتصحيح الآليّ عونٌ لا بديل.

</div>

---
---

## 🇬🇧 In English

An offline‑friendly web app that helps you **recite the Qur’an and get instant,
phoneme‑level feedback** on your pronunciation and tajwīd — powered by the
[`quran-muaalem`](https://arxiv.org/abs/2509.00094) model. Read from an
authentic mushaf‑style page, tap or drag to select words (across ayahs),
listen to a reference recitation, then recite and see each word turn green or
red with a plain‑language explanation of the mistake.

> Runs locally on your PC, and can be shared with other devices on your home
> Wi‑Fi from a single browser link.

### ✨ Features

- **All 114 surahs**, laid out by real **Mushaf page numbers** (e.g. `صفحة 1 · آية 1–7`).
- **Live recitation** feedback (green = correct, red = mistake) with a clear
  reason: the exact letter (*makhraj*), harakah, or madd length at fault.
- **Word selection** — click/drag to pick one word, several, or a run that
  **spans multiple ayahs**, then listen or test just that selection.
- **Two listening styles:**
  - **تجويد · Tajweed** — Al‑Ḥuṣarī tarteel (flowing recitation with cross‑word rules).
  - **قراءة عادية · Normal Reading** — clean, independent word‑by‑word recordings.
- **Mistakes panel** with a running tally and per‑word phonetic detail.
- **Adjustable text size**, authentic Arabic font, bilingual UI (Arabic + English).
- **Works offline** once set up (reference audio caches locally).
- **Share on your home network** over HTTPS so the microphone works on other PCs.

### 🧩 Requirements

- **Python 3.11** (a conda environment is recommended).
- Enough disk/RAM for the ML engine (**PyTorch**; the model downloads on first run).
- A microphone.

### 🚀 Installation

```bash
conda create -n quran_teacher python=3.11
conda activate quran_teacher
pip install -r requirements.txt
```

The pronunciation engine (`quran-muaalem`) pulls in PyTorch and downloads its
model weights from Hugging Face **on first launch**, so the first run needs
internet and may take a few minutes.

**Audio:** the word‑by‑word recordings used by *Normal Reading* mode are
**included** under `reference_audio/mujawwad/` (~416 MB), from the Apache‑2.0
[Quran Word‑By‑Word Audio Dataset](https://huggingface.co/datasets/zaibihassan/Quranic-Word-By-Word-Audio-Data).
The **Tajweed / Al‑Ḥuṣarī** audio is fetched and cached automatically at runtime.

### ▶️ Running

**On your PC only:**
```bash
python run.py
```
Then open the printed address (e.g. `http://127.0.0.1:7070`).

**Share on your home Wi‑Fi** (so the mic works on other devices):
```bash
# Windows (cmd):
set HTTPS=1
python run.py
```
…or just double‑click **`share.bat`**. It prints an address like
`https://192.168.x.x:7070` to open on the family PCs. Allow the port through
Windows Firewall once:
```
netsh advfirewall firewall add rule name="Al-Muqri" dir=in action=allow protocol=TCP localport=7070
```
Each browser shows a one‑time “not private” warning for the self‑signed
certificate — click **Advanced → Proceed**, then allow the microphone.

**Ports:** UI `7070` · ML engine `8000` (internal, localhost only).

### 🙏 Credits & Licenses

This project stands on the work of others — huge thanks to them. Please
respect each one's license:

- **Pronunciation model & phonetic script:** `quran-muaalem` by Abdullah
  ([github.com/obadx/quran-muaalem](https://github.com/obadx/quran-muaalem),
  [arXiv:2509.00094](https://arxiv.org/abs/2509.00094)).
- **Quran text & phonetics:** `quran-transcript` by Abdullah
  ([github.com/obadx/quran-transcript](https://github.com/obadx/quran-transcript)).
- **Word‑by‑word audio** (Normal Reading): *Quran Word‑By‑Word Audio Dataset
  (Muallim & Mujawwad)* — Apache‑2.0
  ([huggingface.co/datasets/zaibihassan/Quranic-Word-By-Word-Audio-Data](https://huggingface.co/datasets/zaibihassan/Quranic-Word-By-Word-Audio-Data)).
- **Tajweed audio:** Al‑Ḥuṣarī recitation via the **QUL / Tarteel** API
  ([qul.tarteel.ai](https://qul.tarteel.ai)).
- **Verse fonts:** *Amiri Quran* ([github.com/aliftype/amiri](https://github.com/aliftype/amiri));
  optional *KFGQPC Uthmanic Script HAFS* (King Fahd Glorious Qur’an Printing Complex).
- Built with **Flask**, **PyTorch**, **NumPy**, and **cryptography**.

This project's own application code is released under the **MIT License** — see
[`LICENSE`](LICENSE). You are free to use, copy, modify, and share it, for any
purpose, at no cost. The third‑party assets above keep their own licenses.

> **Please use this respectfully**, given the sanctity of the Qur’an, and
> verify your recitation with a qualified teacher — the automated feedback is
> an aid, not a substitute.
