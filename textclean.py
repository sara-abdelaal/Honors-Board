# -*- coding: utf-8 -*-
"""
تنظيف وتحليل قائمة الأسماء.

القاعدة الذهبية: لا نغيّر حرفًا واحدًا داخل الاسم.
نحذف فقط ما ليس جزءًا من الاسم: الإيموجي، الترقيم في بداية السطر،
رموز التنسيق (* ~ `)، وعلامات الاتجاه غير المرئية.
"""
import re
import unicodedata

# علامات اتجاه/تحكم غير مرئية (لا نلمس ZWJ / ZWNJ لأنها قد تكون جزءًا من الكتابة)
_BIDI_CONTROLS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c\ufeff\u200b\u2060\u00ad]")

# إيموجي ورموز (مع محدد الشكل FE0F وتسلسلات ZWJ بين الإيموجي)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF\u25A0-\u25FF"
    "\u2600-\u27BF\u2900-\u297F\u2B00-\u2BFF\u3030\u303D\u3297\u3299\u2122\u00A9\u00AE"
    "\uFE0E\uFE0F\u20E3\U000E0020-\U000E007F]"
    "(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF])*"
)
_MD_MARKS = re.compile(r"[*~`]")
_DIGITS = "0-9\u0660-\u0669\u06F0-\u06F9"
# رقم في أول السطر: "12." "12-" "(12)" "12)" "١٢ـ" "12:" ...
_NUMBERING = re.compile(
    r"^[\s\(\[\{]*([" + _DIGITS + r"]+)[\s]*[\.\-\)\]\}\u066B\u06D4:،,ـ\u2013\u2014]*[\s]*"
)
_BULLET = re.compile(r"^[\s\-\u2013\u2014\u2022\u00b7\u25cf\u25aa\u25e6\u2043\u2219\u30fb]+")
_SPACES = re.compile(r"[ \t\u00a0\u2000-\u200a\u202f\u205f\u3000]+")
_PRES_FORMS = re.compile(r"[\ufb50-\ufdff\ufe70-\ufefc]")
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_line(s: str) -> str:
    """تنظيف عام للسطر بدون المساس بالحروف."""
    if _PRES_FORMS.search(s):
        # نص منسوخ من PDF/صورة بأشكال عرض جاهزة → نرجعه لحروفه الأصلية
        s = unicodedata.normalize("NFKC", s)
    s = _BIDI_CONTROLS.sub("", s)
    s = _EMOJI.sub(" ", s)
    s = _MD_MARKS.sub("", s)
    s = _SPACES.sub(" ", s)
    return s.strip().strip("_").strip()


def clean_single(s: str) -> str:
    """تنظيف حقل واحد (عنوان مثلًا) مع الحفاظ على الحروف والأرقام."""
    s = normalize_line(s)
    return s.strip(" _")


_GROUP = re.compile(r"المجموعة\s*[:：]?\s*[\(\[\{]?\s*([^\s\)\]\}\(\[\{]{1,12})\s*[\)\]\}]?")


def clean_group(g: str) -> str:
    """'(ج)' أو ' ج ' → 'ج' (نحذف الأقواس وعلامات التنسيق فقط)."""
    g = clean_single(g or "")
    return g.strip("()[]{}<> \u200c\u200d").strip()


def parse_names(raw: str):
    """
    يرجع dict:
      names      : قائمة الأسماء بالترتيب
      ignored    : أسطر تم تجاهلها لأنها ليست أسماء (عناوين مثلًا)
      duplicates : أسماء مكررة (تُترك كما هي وتُنبَّه فقط)
      numbered   : هل كان الإدخال مرقّمًا
    """
    if raw is None:
        raw = ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in raw.split("\n")]

    cleaned = []
    for ln in lines:
        c = normalize_line(ln)
        if c:
            cleaned.append(c)

    # إدخال في سطر واحد مفصول بفواصل
    if len(cleaned) == 1 and re.search(r"[،,;؛]", cleaned[0]):
        cleaned = [p.strip() for p in re.split(r"[،,;؛]", cleaned[0]) if p.strip()]

    numbered_lines = [c for c in cleaned if _NUMBERING.match(c)]
    has_numbering = len(numbered_lines) >= 2 or (len(numbered_lines) == 1 and len(cleaned) == 1)

    names, ignored = [], []
    for c in cleaned:
        m = _NUMBERING.match(c)
        if has_numbering:
            if not m:
                ignored.append(c)
                continue
            name = c[m.end():]
        else:
            name = _BULLET.sub("", c)
        name = _SPACES.sub(" ", name).strip(" _\u200c\u200d")
        # سطر رقم فقط أو رموز فقط
        if not name or not re.search(r"\w", name, re.UNICODE):
            if name:
                ignored.append(c)
            continue
        names.append(name)

    seen, dups = set(), []
    for n in names:
        key = unicodedata.normalize("NFC", n)
        if key in seen and key not in dups:
            dups.append(key)
        seen.add(key)

    group = ""
    for ln in ignored:
        m = _GROUP.search(ln)
        if m:
            group = clean_group(m.group(1))
            break
    return {"names": names, "ignored": ignored, "duplicates": dups, "numbered": has_numbering, "group": group}


def to_indic_digits(s: str) -> str:
    return s.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def to_western_digits(s: str) -> str:
    return s.translate(_ARABIC_INDIC)


def format_number(n: int, style: str) -> str:
    s = str(n)
    return to_indic_digits(s) if style == "indic" else s
