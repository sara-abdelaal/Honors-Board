# -*- coding: utf-8 -*-
"""
لوحة المجتازات — تطبيق ويب (Flask + Pillow)

تشغيل:
    pip install -r requirements.txt
    python app.py
ثم افتح  http://127.0.0.1:5000
"""
import base64
import io
import logging
import os
import zipfile

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory

import renderer as r
import textclean as tc

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # 40MB
app.config["JSON_AS_ASCII"] = False
log = logging.getLogger("board")

ENGINE = r.Engine(force_basic=os.environ.get("FORCE_BASIC") == "1")
PREVIEW_WIDTH = 1000  # المعاينة بدقة أقل للسرعة؛ التصميم نسبي فيتطابق مع النتيجة النهائية


def _read():
    parsed = tc.parse_names(request.form.get("names", ""))
    opt = r.Options.from_form(request.form)
    f = request.files.get("bg")
    data = f.read() if f and f.filename else None
    return parsed, opt, (data or None)


def _fail(msg, code=400):
    return jsonify({"error": msg}), code


@app.errorhandler(413)
def too_big(_):
    return _fail("حجم الملف كبير جدًا (الحد الأقصى 40 ميجابايت).", 413)


@app.get("/")
def index():
    groups = {}
    for f in r.FONTS:
        key, label, _file, group = f
        groups.setdefault(group, []).append({"key": key, "label": label, "file": _file, "ok": ENGINE.font_ok(key)})
    with open(os.path.join(BASE, "sample_names.txt"), encoding="utf-8") as fh:
        sample = fh.read()
    return render_template(
        "index.html",
        groups=list(groups.items()),
        defaults=r.DEFAULTS,
        sample=sample,
        engine=ENGINE.mode,
    )


@app.get("/fonts/<path:name>")
def fonts(name):
    return send_from_directory(r.FONT_DIR, name, max_age=86400)


@app.post("/api/parse")
def api_parse():
    p = tc.parse_names(request.form.get("names", ""))
    return jsonify(count=len(p["names"]), ignored=p["ignored"][:12], duplicates=p["duplicates"][:12], group=p["group"])


@app.post("/api/render")
def api_render():
    try:
        parsed, opt, bg = _read()
        opt.out_width = PREVIEW_WIDTH
        res = r.render(parsed["names"], opt, bg, ENGINE)
    except ValueError as e:
        return _fail(str(e))
    except Exception:  # noqa: BLE001
        log.exception("render failed")
        return _fail("حدث خطأ غير متوقع أثناء إنشاء اللوحة. جرّب صورة خلفية أخرى أو قلّل عدد الأسماء.", 500)

    pages, start = [], opt.start_number
    for img, cnt in zip(res.pages, res.counts):
        b64 = base64.b64encode(r.to_preview_jpeg(img, PREVIEW_WIDTH)).decode()
        pages.append({"img": "data:image/jpeg;base64," + b64, "count": cnt, "first": start, "last": start + cnt - 1})
        start += cnt

    warnings = list(res.warnings)
    if parsed["duplicates"]:
        warnings.append("يوجد تكرار في: " + "، ".join(parsed["duplicates"][:6]) + " — تُركت كما هي.")
    return jsonify(
        pages=pages, info=res.info, warnings=warnings, count=len(parsed["names"]),
        ignored=parsed["ignored"][:12], engine=ENGINE.mode,
    )


@app.post("/api/export")
def api_export():
    fmt = request.form.get("fmt", "zip")
    try:
        parsed, opt, bg = _read()
        res = r.render(parsed["names"], opt, bg, ENGINE)
    except ValueError as e:
        return _fail(str(e))
    except Exception:  # noqa: BLE001
        log.exception("export failed")
        return _fail("حدث خطأ غير متوقع أثناء التصدير.", 500)

    if fmt == "pdf":
        return send_file(io.BytesIO(r.to_pdf_bytes(res.pages)), mimetype="application/pdf",
                         as_attachment=True, download_name="board.pdf")
    if fmt == "png":
        try:
            i = max(0, min(len(res.pages) - 1, int(request.form.get("page", "1")) - 1))
        except ValueError:
            i = 0
        return send_file(io.BytesIO(r.to_png_bytes(res.pages[i])), mimetype="image/png",
                         as_attachment=True, download_name=f"board_{i + 1}.png")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, img in enumerate(res.pages, 1):
            z.writestr(f"board_{i:02d}.png", r.to_png_bytes(img))
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="boards.zip")


if __name__ == "__main__":
    print(f"محرك النص: {ENGINE.mode}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
