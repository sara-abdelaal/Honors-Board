# -*- coding: utf-8 -*-
"""
محرك رسم لوحات الأسماء.

- الأسماء تُرسم بمحرك تشكيل عربي حقيقي (HarfBuzz/raqm) إن توفر، وإلا نستخدم
  arabic-reshaper + python-bidi تلقائيًا. النتيجة نفسها: حروف متصلة وسليمة.
- لا يوجد أي تعديل على حروف الأسماء.
- توزيع تلقائي: عدد اللوحات، عدد الأعمدة، حجم الخط، اكتشاف حدود الإطار،
  وتجنّب الزخارف (الورود في الأركان) بمسح مناطق الحبر في الخلفية.
"""
from __future__ import annotations

import io
import itertools
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, features
import arabic_reshaper
from arabic_reshaper.ligatures import LIGATURES
from fontTools.ttLib import TTFont

try:  # python-bidi >= 0.5
    from bidi import get_display
except ImportError:  # python-bidi 0.4.x
    from bidi.algorithm import get_display

import textclean as tc

BASE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE, "fonts")
DEFAULT_BG = os.path.join(BASE, "static", "default_bg.png")

# ---------------------------------------------------------------- الخطوط
# (key, الاسم الظاهر, الملف, المجموعة)
FONTS = [
    ("cairo-black", "القاهرة — أسود", "Cairo-Black.ttf", "خطوط واضحة (سانس)"),
    ("cairo-extrabold", "القاهرة — عريض جدًا", "Cairo-ExtraBold.ttf", "خطوط واضحة (سانس)"),
    ("cairo-bold", "القاهرة — عريض", "Cairo-Bold.ttf", "خطوط واضحة (سانس)"),
    ("cairo-semibold", "القاهرة — شبه عريض", "Cairo-SemiBold.ttf", "خطوط واضحة (سانس)"),
    ("cairo-medium", "القاهرة — متوسط", "Cairo-Medium.ttf", "خطوط واضحة (سانس)"),
    ("tajawal-extrabold", "تجوّل — عريض جدًا", "Tajawal-ExtraBold.ttf", "خطوط واضحة (سانس)"),
    ("tajawal-bold", "تجوّل — عريض", "Tajawal-Bold.ttf", "خطوط واضحة (سانس)"),
    ("tajawal-medium", "تجوّل — متوسط", "Tajawal-Medium.ttf", "خطوط واضحة (سانس)"),
    ("almarai-extrabold", "المرعي — عريض جدًا", "Almarai-ExtraBold.ttf", "خطوط واضحة (سانس)"),
    ("almarai-bold", "المرعي — عريض", "Almarai-Bold.ttf", "خطوط واضحة (سانس)"),
    ("plex-bold", "IBM Plex عربي — عريض", "IBMPlexSansArabic-Bold.ttf", "خطوط واضحة (سانس)"),
    ("plex-semibold", "IBM Plex عربي — شبه عريض", "IBMPlexSansArabic-SemiBold.ttf", "خطوط واضحة (سانس)"),
    ("harmattan-bold", "هارماتان — عريض", "Harmattan-Bold.ttf", "خطوط واضحة (سانس)"),
    ("kufi-bold", "نوتو كوفي — عريض", "NotoKufiArabic-Bold.ttf", "كوفي وهندسي"),
    ("kufi-semibold", "نوتو كوفي — شبه عريض", "NotoKufiArabic-SemiBold.ttf", "كوفي وهندسي"),
    ("reem-bold", "ريم كوفي — عريض", "ReemKufi-Bold.ttf", "كوفي وهندسي"),
    ("messiri-bold", "المسيري — عريض", "ElMessiri-Bold.ttf", "كوفي وهندسي"),
    ("lalezar", "لاله زار — عناوين ثقيلة", "Lalezar-Regular.ttf", "كوفي وهندسي"),
    ("amiri-bold", "الأميري — عريض", "Amiri-Bold.ttf", "نسخ وكلاسيكي"),
    ("amiri-regular", "الأميري — عادي", "Amiri-Regular.ttf", "نسخ وكلاسيكي"),
    ("amiri-quran", "الأميري قرآن (تشكيل كامل)", "AmiriQuran-Regular.ttf", "نسخ وكلاسيكي"),
    ("naskh-bold", "نوتو نسخ — عريض", "NotoNaskhArabic-Bold.ttf", "نسخ وكلاسيكي"),
    ("naskh-semibold", "نوتو نسخ — شبه عريض", "NotoNaskhArabic-SemiBold.ttf", "نسخ وكلاسيكي"),
    ("scheherazade-bold", "شهرزاد — عريض", "ScheherazadeNew-Bold.ttf", "نسخ وكلاسيكي"),
    ("scheherazade-regular", "شهرزاد — عادي", "ScheherazadeNew-Regular.ttf", "نسخ وكلاسيكي"),
    ("lateef", "لطيف", "Lateef-Regular.ttf", "نسخ وكلاسيكي"),
    ("aref-bold", "عارف رقعة — عريض", "ArefRuqaa-Bold.ttf", "خط يدوي وزخرفي"),
    ("aref-regular", "عارف رقعة — عادي", "ArefRuqaa-Regular.ttf", "خط يدوي وزخرفي"),
    ("katibeh", "كاتبة", "Katibeh-Regular.ttf", "خط يدوي وزخرفي"),
    ("mirza-bold", "ميرزا — عريض", "Mirza-Bold.ttf", "خط يدوي وزخرفي"),
    ("rakkas", "رقّاص", "Rakkas-Regular.ttf", "خط يدوي وزخرفي"),
]
FONT_MAP = {k: {"key": k, "label": l, "file": f, "group": g} for k, l, f, g in FONTS}
# ترتيب الاحتياط لو الخط المختار لا يدعم حرفًا/رمزًا في النص
FALLBACK_ORDER = ["amiri-bold", "cairo-bold", "naskh-bold", "amiri-regular"]

DEFAULTS = {
    "font_title": "cairo-extrabold",
    "font_subtitle": "amiri-bold",
    "font_names": "cairo-bold",
}

_IGNORABLE = set("\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u061c\ufeff\u200b")
_SAMPLE = "لأحمد عبدالرحمن جميل"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex(c: str, default: str):
    c = c if isinstance(c, str) and _HEX.match(c) else default
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------- محرك النص
# في وضع الاحتياط (بدون raqm) نُبقي فقط على ربط لام-ألف، ونعطّل بقية الروابط
# الخاصة (مثل ﷲ) لأن كثيرًا من الخطوط لا تحتويها فتظهر مربعات.
_KEEP_LIGS = {
    "ARABIC LIGATURE LAM WITH ALEF",
    "ARABIC LIGATURE LAM WITH ALEF WITH HAMZA ABOVE",
    "ARABIC LIGATURE LAM WITH ALEF WITH HAMZA BELOW",
    "ARABIC LIGATURE LAM WITH ALEF WITH MADDA ABOVE",
}


def get_reshaper():
    cfg = {
        "delete_harakat": False,
        "delete_tatweel": False,
        "support_zwj": True,
        "support_ligatures": True,
        "use_unshaped_instead_of_isolated": True,
    }
    for name, _ in LIGATURES:
        cfg[name.lower()] = name in _KEEP_LIGS
    return arabic_reshaper.ArabicReshaper(configuration=cfg)


_PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">", "\u00ab": "\u00bb"}
_SWAP = str.maketrans("()[]{}<>\u00ab\u00bb", ")(][}{><\u00bb\u00ab")

try:
    # python-bidi 0.5+ (Rust) يعيد الترتيب لكنه لا يعكس شكل الأقواس؛ الإصدارات القديمة تعكسها.
    _LIB_MIRRORS = get_display("(\u062c)", base_dir="R")[:1] == "("
except Exception:  # noqa: BLE001
    _LIB_MIRRORS = True


def _pre_mirror(text: str) -> str:
    """يعكس الأقواس المتقابلة داخل النص العربي قبل get_display حين لا تفعل المكتبة ذلك."""
    if _LIB_MIRRORS or not any(c in text for c in "()[]{}<>\u00ab\u00bb"):
        return text
    chars = list(text)
    stack = []
    for i, ch in enumerate(text):
        if ch in _PAIRS:
            stack.append((ch, i))
        elif ch in _PAIRS.values():
            for k in range(len(stack) - 1, -1, -1):
                if _PAIRS[stack[k][0]] == ch:
                    j = stack[k][1]
                    del stack[k:]
                    chars[j], chars[i] = chars[j].translate(_SWAP), chars[i].translate(_SWAP)
                    break
    return "".join(chars)


class Engine:
    def __init__(self, force_basic: bool = False):
        self.reshaper = get_reshaper()
        self.mode = "basic" if force_basic else ("raqm" if self._raqm_ok() else "basic")
        self._fonts, self._cmaps, self._m100, self._ratio = {}, {}, {}, {}

    @staticmethod
    def _raqm_ok() -> bool:
        try:
            if not (features.check("raqm") and features.check("fribidi") and features.check("harfbuzz")):
                return False
            path = os.path.join(FONT_DIR, FONT_MAP["cairo-bold"]["file"])
            f = ImageFont.truetype(path, 40, layout_engine=ImageFont.Layout.RAQM)
            f.getlength("محمد (٣)", direction="rtl", language="ar")
            return True
        except Exception:
            return False

    # -- خطوط
    def font(self, key: str, size: float):
        size = max(1, int(round(size)))
        k = (key, size)
        if k not in self._fonts:
            path = os.path.join(FONT_DIR, FONT_MAP[key]["file"])
            layout = ImageFont.Layout.RAQM if self.mode == "raqm" else ImageFont.Layout.BASIC
            self._fonts[k] = ImageFont.truetype(path, size, layout_engine=layout)
        return self._fonts[k]

    def cmap(self, key: str):
        if key not in self._cmaps:
            tt = TTFont(os.path.join(FONT_DIR, FONT_MAP[key]["file"]), lazy=True)
            self._cmaps[key] = set(tt.getBestCmap().keys())
            tt.close()
        return self._cmaps[key]

    # -- تشكيل
    def prep(self, text: str):
        if self.mode == "raqm":
            return text, {"direction": "rtl", "language": "ar"}
        shaped = get_display(self.reshaper.reshape(_pre_mirror(text)), base_dir="R")
        return shaped, {}

    def supports(self, key: str, text: str) -> bool:
        probe = text if self.mode == "raqm" else self.prep(text)[0]
        cm = self.cmap(key)
        for ch in probe:
            if ch in _IGNORABLE or ch.isspace():
                continue
            if ord(ch) not in cm:
                return False
        return True

    def font_ok(self, key: str) -> bool:
        """هل الخط قابل للاستخدام في هذا الوضع؟ (بعض الخطوط تحتاج raqm)."""
        return self.supports(key, "أبتثجحخدذرزسشصضطظعغفقكلمنهويىةءؤئإآ لا لأ لإ لآ ٠١٢٣٤٥٦٧٨٩ 0123456789 ().")

    def resolve(self, key: str, text: str, warnings: set, where: str = ""):
        if self.supports(key, text):
            return key
        for fb in FALLBACK_ORDER:
            if fb != key and self.supports(fb, text):
                warnings.add(
                    f"الخط «{FONT_MAP[key]['label']}» لا يدعم بعض رموز {where or 'النص'}، "
                    f"فتم استخدام «{FONT_MAP[fb]['label']}» لها."
                )
                return fb
        warnings.add(f"لا يوجد خط يدعم كل رموز {where or 'النص'}؛ قد تظهر مربعات.")
        return key

    # -- قياس ورسم
    def m100(self, key: str, text: str) -> float:
        k = (key, text)
        if k not in self._m100:
            shaped, kw = self.prep(text)
            self._m100[k] = float(self.font(key, 100).getlength(shaped, **kw))
        return self._m100[k]

    def center_ratio(self, key: str) -> float:
        """مركز الحبر الرأسي نسبةً إلى خط الأساس (لمحاذاة الصفوف)."""
        if key not in self._ratio:
            shaped, kw = self.prep(_SAMPLE)
            l, t, r, b = self.font(key, 100).getbbox(shaped, anchor="ls", **kw)
            self._ratio[key] = ((t + b) / 2.0) / 100.0
        return self._ratio[key]

    def draw(self, draw: ImageDraw.ImageDraw, x: float, cy: float, text: str, key: str, size: float, fill, anchor: str):
        """يرسم النص بحيث يقع مركزه الرأسي عند cy. anchor: 'r' أو 'm' أفقيًا."""
        shaped, kw = self.prep(text)
        baseline = cy - self.center_ratio(key) * size
        draw.text((x, baseline), shaped, font=self.font(key, size), fill=fill, anchor=anchor + "s", **kw)


# ---------------------------------------------------------------- الخلفية
def load_background(data: bytes | None, out_width: int) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(data)) if data else Image.open(DEFAULT_BG)
        im.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError("تعذر قراءة صورة الخلفية. جرّب صورة PNG أو JPG سليمة.") from e
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        base = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(base, im)
    im = im.convert("RGB")
    w, h = im.size
    if out_width and out_width > 0:
        tw = int(out_width)
    else:
        tw = min(w, 4000)
    th = int(round(h * tw / w))
    if th > 8000:
        tw = int(tw * 8000 / th)
        th = 8000
    if (tw, th) != (w, h):
        im = im.resize((tw, th), Image.LANCZOS)
    return im


@dataclass
class BgInfo:
    ref: tuple
    lum: float
    ink: np.ndarray
    ii: np.ndarray
    k: int
    box: tuple
    box_detected: bool


def _detect_box(ink: np.ndarray):
    h, w = ink.shape
    cx, cy = w // 2, h // 2
    rows = slice(int(h * .30), int(h * .70))
    cols = slice(int(w * .30), int(w * .70))
    seg = ink[rows, :cx][:, ::-1]
    left = np.median(np.where(seg.any(1), cx - seg.argmax(1), 0))
    seg = ink[rows, cx:]
    right = np.median(np.where(seg.any(1), cx + seg.argmax(1), w))
    seg = ink[:cy, cols][::-1, :]
    top = np.median(np.where(seg.any(0), cy - seg.argmax(0), 0))
    seg = ink[cy:, cols]
    bottom = np.median(np.where(seg.any(0), cy + seg.argmax(0), h))
    return left, top, right, bottom


def analyze(img: Image.Image, auto_frame: bool) -> BgInfo:
    arr = np.asarray(img, dtype=np.int16)
    h, w, _ = arr.shape
    center = arr[int(h * .42):int(h * .58), int(w * .42):int(w * .58)].reshape(-1, 3)
    ref = np.round(np.median(center, axis=0)).astype(np.int16)
    diff = np.abs(arr - ref).max(axis=2).astype(np.uint8)
    k = max(1, math.ceil(w / 700))
    hh, ww = (h // k) * k, (w // k) * k
    pooled = diff[:hh, :ww].reshape(hh // k, k, ww // k, k).max(axis=(1, 3))
    ink = pooled > 24
    ii = np.pad(ink.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    lum = float(0.299 * ref[0] + 0.587 * ref[1] + 0.114 * ref[2])

    fallback = (0.08 * w, 0.06 * h, 0.92 * w, 0.94 * h)
    box, detected = fallback, False
    if auto_frame:
        l, t, r, b = _detect_box(ink)
        L, T, R, B = l * k, t * k, r * k, b * k
        if (R - L) >= 0.55 * w and (B - T) >= 0.55 * h and L > 0.005 * w and T > 0.005 * h:
            box, detected = (L, T, R, B), True
    return BgInfo(tuple(int(v) for v in ref), lum, ink, ii, k, box, detected)


def ink_in_rect(info: BgInfo, x0, y0, x1, y1, margin=0.0) -> int:
    k = info.k
    h, w = info.ink.shape
    X0 = max(0, int((x0 - margin) // k))
    Y0 = max(0, int((y0 - margin) // k))
    X1 = min(w, int(math.ceil((x1 + margin) / k)))
    Y1 = min(h, int(math.ceil((y1 + margin) / k)))
    if X1 <= X0 or Y1 <= Y0:
        return 0
    ii = info.ii
    return int(ii[Y1, X1] - ii[Y0, X1] - ii[Y1, X0] + ii[Y0, X0])


# ---------------------------------------------------------------- خيارات
@dataclass
class Options:
    title: str = ""
    group: str = ""
    subtitle: str = ""
    extra: str = ""
    font_title: str = DEFAULTS["font_title"]
    font_subtitle: str = DEFAULTS["font_subtitle"]
    font_names: str = DEFAULTS["font_names"]
    color_title: str = "#6d1e2b"
    color_subtitle: str = "#6d1e2b"
    color_names: str = "#221c1c"
    color_numbers: str = "#221c1c"
    auto_contrast: bool = True
    max_per_page: int = 34
    columns: int = 0          # 0 = تلقائي
    equal_split: bool = True
    start_number: int = 1
    digits: str = "western"   # western | indic
    show_numbers: bool = True
    out_width: int = 1600
    tint: bool = False
    panel: bool = False
    auto_frame: bool = True
    extra_pad: float = 0.0    # نسبة مئوية من العرض

    @staticmethod
    def _int(v, default, lo, hi):
        try:
            return max(lo, min(hi, int(float(v))))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _float(v, default, lo, hi):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bool(v, default=False):
        if v is None:
            return default
        return str(v).lower() in ("1", "true", "on", "yes")

    @classmethod
    def from_form(cls, f) -> "Options":
        o = cls()
        o.title = tc.clean_single(f.get("title", ""))
        o.group = tc.clean_group(f.get("group", ""))
        o.subtitle = tc.clean_single(f.get("subtitle", ""))
        o.extra = tc.clean_single(f.get("extra", ""))
        for fld in ("font_title", "font_subtitle", "font_names"):
            v = f.get(fld, DEFAULTS[fld])
            setattr(o, fld, v if v in FONT_MAP else DEFAULTS[fld])
        for fld in ("color_title", "color_subtitle", "color_names", "color_numbers"):
            v = f.get(fld)
            if isinstance(v, str) and _HEX.match(v):
                setattr(o, fld, v)
        o.auto_contrast = cls._bool(f.get("auto_contrast"), True)
        o.max_per_page = cls._int(f.get("max_per_page"), 34, 2, 120)
        o.columns = cls._int(f.get("columns"), 0, 0, 5)
        o.equal_split = cls._bool(f.get("equal_split"), True)
        o.start_number = cls._int(f.get("start_number"), 1, 0, 100000)
        o.digits = "indic" if f.get("digits") == "indic" else "western"
        o.show_numbers = cls._bool(f.get("show_numbers"), True)
        o.out_width = cls._int(f.get("out_width"), 1600, 0, 4000)
        if 0 < o.out_width < 600:
            o.out_width = 600
        o.tint = cls._bool(f.get("tint"), False)
        o.panel = cls._bool(f.get("panel"), False)
        o.auto_frame = cls._bool(f.get("auto_frame"), True)
        o.extra_pad = cls._float(f.get("extra_pad"), 0.0, 0.0, 15.0)
        return o


# ---------------------------------------------------------------- توزيع
def paginate(n: int, max_per: int, equal: bool):
    pages = max(1, math.ceil(n / max_per))
    if equal:
        base, rem = divmod(n, pages)
        return [base + 1 if i < rem else base for i in range(pages)]
    return [max_per] * (pages - 1) + [n - max_per * (pages - 1)]


def _fit_text(eng: Engine, key: str, text: str, base: float, max_w: float, min_frac=0.62):
    """يرجع (أسطر، حجم). يصغّر الخط أولًا ثم يقسم على أسطر عند الحاجة."""
    w100 = eng.m100(key, text)
    s_fit = max_w / w100 * 100
    if s_fit >= base * min_frac:
        return [text], min(base, s_fit)
    words = text.split()
    best = None
    for k in range(2, min(len(words), 4) + 1):
        cand = None
        for cuts in itertools.combinations(range(1, len(words)), k - 1):
            parts = [" ".join(words[a:b]) for a, b in zip((0,) + cuts, cuts + (len(words),))]
            mw = max(eng.m100(key, p) for p in parts)
            if cand is None or mw < cand[0]:
                cand = (mw, parts)
        if cand:
            s = max_w / cand[0] * 100
            best = (cand[1], min(base, s))
            if s >= base * min_frac * 0.9:
                return best
    if best:
        return best
    return [text], s_fit


@dataclass
class Result:
    pages: list = field(default_factory=list)
    counts: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def render(names: list, opt: Options, bg_bytes: bytes | None, eng: Engine) -> Result:
    if not names:
        raise ValueError("لم يتم العثور على أي اسم. اكتب اسمًا في كل سطر.")
    if len(names) > 2000:
        raise ValueError("عدد الأسماء كبير جدًا (الحد الأقصى 2000).")

    warnings: set = set()
    bg = load_background(bg_bytes, opt.out_width)
    W, H = bg.size
    info = analyze(bg, opt.auto_frame)
    L, T, R, B = info.box
    if opt.auto_frame and not info.box_detected:
        warnings.add("لم يُكتشف إطار واضح في الخلفية، فتم استخدام هوامش افتراضية. يمكنك ضبط «هامش إضافي».")
    Wi, Hi = R - L, B - T
    cx = (L + R) / 2

    # لون الورق الدافئ للخلفيات البيضاء فقط
    ref = np.array(info.ref)
    if opt.tint and info.lum > 232 and int(ref.max() - ref.min()) < 14:
        tint = np.array([251, 240, 218], dtype=np.float32) / 255.0
        arr = np.asarray(bg, dtype=np.float32) * tint
        bg = Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), "RGB")

    # ألوان
    c_title, c_sub = _hex(opt.color_title, "#6d1e2b"), _hex(opt.color_subtitle, "#6d1e2b")
    c_names, c_num = _hex(opt.color_names, "#221c1c"), _hex(opt.color_numbers, "#221c1c")
    dark_bg = info.lum < 110
    if opt.auto_contrast and dark_bg:
        c_title = c_sub = c_num = (243, 207, 122)
        c_names = (255, 246, 227)

    # ------------------------------------------------ الرأس
    y = T + 0.055 * Hi
    blocks = []  # (lines, key, size, lineh, color, y_top)
    title_text = f"{opt.title} ({opt.group})" if (opt.title and opt.group) else opt.title
    specs = [
        (title_text, opt.font_title, 0.064 * W, 0.72 * Wi, 1.32, c_title, "العنوان الرئيسي"),
        (opt.subtitle, opt.font_subtitle, 0.056 * W, 0.72 * Wi, 1.55, c_sub, "العنوان الفرعي"),
        (opt.extra, opt.font_subtitle, 0.036 * W, 0.72 * Wi, 1.5, c_sub, "السطر الإضافي"),
    ]
    header_top = y
    for text, fkey, base, max_w, lh, color, label in specs:
        if not text:
            continue
        key = eng.resolve(fkey, text, warnings, label)
        lines, size = _fit_text(eng, key, text, base, max_w)
        if size < 0.02 * W:
            warnings.add(f"{label} طويل جدًا؛ صار خطه صغيرًا. جرّب تقصيره.")
        blocks.append((lines, key, size, lh, color, y))
        y += len(lines) * size * lh + 0.16 * size
    header_bottom = y if blocks else header_top - 0.03 * Hi

    # ------------------------------------------------ أسماء
    n = len(names)
    sizes = paginate(n, opt.max_per_page, opt.equal_split)
    if len(sizes) > 60:
        raise ValueError("عدد اللوحات كبير جدًا. زِد «الحد الأقصى للأسماء في اللوحة».")
    max_m = max(sizes)

    keys = []
    for nm in names:
        keys.append(eng.resolve(opt.font_names, nm, warnings, "بعض الأسماء"))
    digits_probe = "0123456789." if opt.digits == "western" else "٠١٢٣٤٥٦٧٨٩."
    num_key = eng.resolve(opt.font_names, digits_probe, warnings, "الأرقام")
    nums = [tc.format_number(opt.start_number + i, opt.digits) + "." for i in range(n)]
    w100 = [eng.m100(k, nm) for k, nm in zip(keys, names)]
    name_w100 = max(w100)
    if opt.show_numbers:
        num_w100 = max(eng.m100(num_key, s) for s in nums)
        gap100 = 34.0
    else:
        num_w100, gap100 = 0.0, 0.0
    bw100 = num_w100 + gap100 + name_w100

    names_top = header_bottom + 0.035 * Hi
    names_bottom = B - 0.06 * Hi
    area_h = names_bottom - names_top
    if area_h < 0.15 * Hi:
        raise ValueError("العناوين طويلة جدًا ولم يبقَ مكان كافٍ للأسماء. قصّر العناوين أو قلّل حجمها.")

    padx = 0.045 * W + opt.extra_pad / 100.0 * W
    Wc0 = max(0.3 * W, Wi - 2 * padx)
    mingap = 0.05 * W
    fs_cap = 0.046 * W

    def plan(cols: int, Wc: float):
        rows = math.ceil(max_m / cols)
        fs_w = (Wc - (cols - 1) * mingap) / (cols * bw100) * 100
        fs_h = (area_h / rows) / 1.5
        return rows, max(4.0, min(fs_w, fs_h, fs_cap))

    def choose_cols(Wc: float):
        if opt.columns:
            return min(opt.columns, max_m)
        cands = {c: plan(c, Wc)[1] for c in range(1, min(4, max_m) + 1)}
        best = max(cands.values())
        for c in sorted(cands):
            if cands[c] >= 0.95 * best:
                return c
        return 1

    def layout(Wc: float):
        cols = choose_cols(Wc)
        rows, fs = plan(cols, Wc)
        row_h = min(area_h / rows, fs * 1.9)
        block_h = rows * row_h
        # لو الأسماء قليلة: نحرّك العناوين والقائمة معًا لتتوسط اللوحة بدل ترك فراغ كبير
        shift = min(max(0.0, (area_h - block_h) / 2), 0.14 * Hi)
        y0 = names_top + shift
        bw = bw100 * fs / 100
        if cols > 1:
            colgap = max(mingap, min((Wc - cols * bw) / (cols - 1), 0.12 * W))
        else:
            colgap = 0
        total = cols * bw + (cols - 1) * colgap
        x_first = cx + total / 2
        return dict(cols=cols, rows=rows, fs=fs, row_h=row_h, y0=y0, bw=bw, colgap=colgap, x_first=x_first, shift=shift)

    def rects_for(lay):
        fs = lay["fs"]
        numw = num_w100 * fs / 100
        gap = gap100 * fs / 100
        out = []
        idx = 0
        for m in sizes:
            for j in range(m):
                col, row = divmod(j, lay["rows"])
                xr = lay["x_first"] - col * (lay["bw"] + lay["colgap"])
                cy = lay["y0"] + row * lay["row_h"] + lay["row_h"] / 2
                wname = w100[idx + j] * fs / 100
                out.append((xr - (numw + gap + wname), cy - 0.55 * fs, xr, cy + 0.55 * fs))
            idx += m
        return out

    best = None
    steps = [0.0] if opt.panel else [i * 0.02 for i in range(0, 13)]
    for s in steps:
        lay = layout(Wc0 * (1 - s))
        coll = sum(1 for r in rects_for(lay) if ink_in_rect(info, *r, margin=0.006 * W) > 2)
        if best is None or coll < best[0]:
            best = (coll, s, lay)
        if coll == 0:
            break
    coll, shrink, lay = best
    if coll:
        warnings.add("الخلفية مزدحمة بالزخارف؛ قد يلامس بعض النص الزخرفة. فعّل «لوح خلف النص» أو زِد الهامش.")
    fs = lay["fs"]
    if fs < 0.02 * W:
        warnings.add("خط الأسماء صار صغيرًا لكثرة الأسماء في اللوحة. قلّل «الحد الأقصى للأسماء» لتحصل على لوحات أكثر وأوضح.")

    # ------------------------------------------------ الرسم
    pages, counts = [], []
    numw = num_w100 * fs / 100
    gap = gap100 * fs / 100
    start = 0
    for m in sizes:
        canvas = bg.copy()
        if opt.panel:
            ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            fill = (18, 14, 14, 175) if dark_bg else (255, 255, 255, 190)
            ImageDraw.Draw(ov).rounded_rectangle(
                (L + 0.02 * W, header_top + lay["shift"] - 0.02 * H, R - 0.02 * W,
                 min(B - 0.01 * H, lay["y0"] + lay["rows"] * lay["row_h"] + 0.03 * H)),
                radius=0.03 * W, fill=fill)
            canvas = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(canvas)

        for lines, key, size, lh, color, ytop in blocks:
            for i, line in enumerate(lines):
                cy = ytop + lay["shift"] + (i + 0.5) * size * lh
                eng.draw(d, cx, cy, line, key, size, color, "m")

        for j in range(m):
            gi = start + j
            col, row = divmod(j, lay["rows"])
            xr = lay["x_first"] - col * (lay["bw"] + lay["colgap"])
            cy = lay["y0"] + row * lay["row_h"] + lay["row_h"] / 2
            if opt.show_numbers:
                eng.draw(d, xr, cy, nums[gi], num_key, fs, c_num, "r")
                eng.draw(d, xr - numw - gap, cy, names[gi], keys[gi], fs, c_names, "r")
            else:
                eng.draw(d, xr, cy, names[gi], keys[gi], fs, c_names, "r")
        start += m
        pages.append(canvas)
        counts.append(m)

    res = Result(pages=pages, counts=counts, warnings=sorted(warnings))
    res.info = dict(
        size=[W, H], cols=lay["cols"], rows=lay["rows"], font_px=round(fs, 1),
        frame_detected=info.box_detected, engine=eng.mode, shrink=round(shrink, 2),
        box=[int(v) for v in info.box],
    )
    return res


# ---------------------------------------------------------------- إخراج
def to_png_bytes(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "PNG", optimize=True)
    return b.getvalue()


def to_preview_jpeg(img: Image.Image, width: int = 900) -> bytes:
    w, h = img.size
    if w > width:
        img = img.resize((width, int(h * width / w)), Image.LANCZOS)
    b = io.BytesIO()
    img.save(b, "JPEG", quality=88, optimize=True)
    return b.getvalue()


def to_pdf_bytes(pages: list) -> bytes:
    b = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(b, "PDF", resolution=150.0, save_all=True, append_images=rest)
    return b.getvalue()
