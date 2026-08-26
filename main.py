from pyscript import document, window, when
from PIL import Image, ImageDraw, ImageFont, ImageOps
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import base64, calendar

W, H = 1200, 1780
PHOTO_W = W - 100
PHOTO_H = 900
PHOTO_X = 50
PHOTO_Y = 38
CAL_TOP = 995

def get_font(size, bold=False):
    try:
        return ImageFont.truetype(
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            size
        )
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

FONT_TITLE = get_font(62, True)
FONT_WEEK = get_font(34, True)
FONT_DAY = get_font(38, True)
FONT_EVENT = get_font(18, True)

# PC一括ダウンロード用：直近に生成した12か月分のJPEG bytes
GENERATED_JPEGS = {}


CAT_DAYS = {
    (2, 17): "ヨーロッパの猫の日",
    (2, 22): "日本の猫の日",
    (3, 1): "ロシアの猫の日",
    (8, 8): "世界猫の日",
    (8, 17): "黒猫感謝の日",
    (9, 29): "招き猫の日",
    (10, 27): "全国黒猫の日",
    (10, 29): "アメリカの猫の日",
    (11, 17): "イタリアの黒猫の日",
}



OFFICIAL_HOLIDAYS = {
    2026: {
        (1, 1): "元日",
        (1, 12): "成人の日",
        (2, 11): "建国記念の日",
        (2, 23): "天皇誕生日",
        (3, 20): "春分の日",
        (4, 29): "昭和の日",
        (5, 3): "憲法記念日",
        (5, 4): "みどりの日",
        (5, 5): "こどもの日",
        (5, 6): "振替休日",
        (7, 20): "海の日",
        (8, 11): "山の日",
        (9, 21): "敬老の日",
        (9, 22): "国民の休日",
        (9, 23): "秋分の日",
        (10, 12): "スポーツの日",
        (11, 3): "文化の日",
        (11, 23): "勤労感謝の日",
    },
    2027: {
        (1, 1): "元日",
        (1, 11): "成人の日",
        (2, 11): "建国記念の日",
        (2, 23): "天皇誕生日",
        (3, 21): "春分の日",
        (3, 22): "振替休日",
        (4, 29): "昭和の日",
        (5, 3): "憲法記念日",
        (5, 4): "みどりの日",
        (5, 5): "こどもの日",
        (7, 19): "海の日",
        (8, 11): "山の日",
        (9, 20): "敬老の日",
        (9, 23): "秋分の日",
        (10, 11): "スポーツの日",
        (11, 3): "文化の日",
        (11, 23): "勤労感謝の日",
    },
}



def nth_weekday(year, month, weekday, nth):
    first = calendar.monthrange(year, month)[0]
    return 1 + ((weekday - first) % 7) + (nth - 1) * 7

def vernal_equinox_day(year):
    return int(20.8431 + 0.242194 * (year - 1980) - ((year - 1980) // 4))

def autumn_equinox_day(year):
    return int(23.2488 + 0.242194 * (year - 1980) - ((year - 1980) // 4))

def japanese_holidays(year):
    """
    {(month, day): 日本語祝日名} を返す。
    2026/2027は公表済み固定データ。
    それ以外は現行ルールから計算。
    """
    import datetime

    if year in OFFICIAL_HOLIDAYS:
        return dict(OFFICIAL_HOLIDAYS[year])

    holidays = {
        (1, 1): "元日",
        (1, nth_weekday(year, 1, 0, 2)): "成人の日",
        (2, 11): "建国記念の日",
        (2, 23): "天皇誕生日",
        (3, vernal_equinox_day(year)): "春分の日",
        (4, 29): "昭和の日",
        (5, 3): "憲法記念日",
        (5, 4): "みどりの日",
        (5, 5): "こどもの日",
        (7, nth_weekday(year, 7, 0, 3)): "海の日",
        (8, 11): "山の日",
        (9, nth_weekday(year, 9, 0, 3)): "敬老の日",
        (9, autumn_equinox_day(year)): "秋分の日",
        (10, nth_weekday(year, 10, 0, 2)): "スポーツの日",
        (11, 3): "文化の日",
        (11, 23): "勤労感謝の日",
    }

    # 国民の休日
    changed = True
    while changed:
        changed = False
        for m in range(1, 13):
            dim = calendar.monthrange(year, m)[1]
            for day in range(2, dim):
                key = (m, day)
                if key in holidays:
                    continue
                if (m, day - 1) in holidays and (m, day + 1) in holidays:
                    holidays[key] = "国民の休日"
                    changed = True

    # 振替休日
    original = list(holidays.keys())
    for m, day in original:
        dt = datetime.date(year, m, day)
        if dt.weekday() == 6:
            sub = dt + datetime.timedelta(days=1)
            while (sub.month, sub.day) in holidays:
                sub += datetime.timedelta(days=1)
            holidays[(sub.month, sub.day)] = "振替休日"

    return holidays


async def js_file_to_image(file_obj):
    data_url = str(await window.readFileDataURL(file_obj))
    raw = base64.b64decode(data_url.split(",", 1)[1])
    img = Image.open(BytesIO(raw))
    return ImageOps.exif_transpose(img).convert("RGB")

def crop_with_adjustment(img, target_w, target_h, x_adj=0, y_adj=0, zoom=100):
    """
    写真をフレームへ配置する。
    x_adj / y_adj : -200..200（0が中央）
    zoom          : 50..200（100が従来の「全面を埋める」基準）

    50〜99%では写真全体をより多く見せられる代わりに余白が出る場合がある。
    大きく上下左右へ動かした場合も同様。
    """
    iw, ih = img.size

    # 100% = フレームを完全に埋める cover 基準
    cover_scale = max(target_w / iw, target_h / ih)
    scale = cover_scale * (zoom / 100.0)

    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA")

    # フレーム本体。縮小・大移動時に出る余白はカレンダー背景色に合わせる。
    frame = Image.new("RGBA", (target_w, target_h), (250, 248, 244, 255))

    # 中央配置を基準に、-200..200 をフレーム半分相当まで移動可能にする。
    base_x = (target_w - nw) / 2
    base_y = (target_h - nh) / 2
    shift_x = (x_adj / 200.0) * (target_w * 0.50)
    shift_y = -(y_adj / 200.0) * (target_h * 0.50)

    paste_x = int(round(base_x + shift_x))
    paste_y = int(round(base_y + shift_y))

    frame.alpha_composite(resized, (paste_x, paste_y))
    return frame

def prepare_photo(img, x_adj=0, y_adj=0, zoom=100):
    img = crop_with_adjustment(img, PHOTO_W, PHOTO_H, x_adj, y_adj, zoom)
    rgba = img.convert("RGBA")

    mask = Image.new("L", rgba.size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, rgba.width, rgba.height), radius=34, fill=255)
    rgba.putalpha(mask)
    return rgba

def center_text(draw, y, text, font, fill):
    b = draw.textbbox((0, 0), text, font=font)
    draw.text(((W - (b[2]-b[0])) / 2, y), text, font=font, fill=fill)

def make_calendar(img, year, month, x_adj=0, y_adj=0, zoom=100, logo=None, cat_icon=None, cat_labels=None, holiday_labels=None, anniversaries=None, anniversary_labels=None, anniversary_heart=None):
    canvas = Image.new("RGBA", (W, H), (250, 248, 244, 255))
    d = ImageDraw.Draw(canvas)

    photo = prepare_photo(img, x_adj, y_adj, zoom)
    canvas.alpha_composite(photo, (PHOTO_X, PHOTO_Y))

    center_text(d, CAL_TOP, f"{year}  /  {month:02d}", FONT_TITLE, (45,45,45,255))

    names = ["SUN","MON","TUE","WED","THU","FRI","SAT"]
    left, right = 70, W - 70
    top = CAL_TOP + 92
    cw = (right-left) / 7

    # 曜日見出し
    weekday_h = 56
    for c, name in enumerate(names):
        color = (185,45,45,255) if c == 0 else ((45,80,165,255) if c == 6 else (30,30,30,255))
        b = d.textbbox((0,0), name, font=FONT_WEEK)
        d.text(
            (left + c*cw + (cw-(b[2]-b[0]))/2, top),
            name, font=FONT_WEEK, fill=color
        )

    # 日別書き込み用グリッド
    # 実際に日付が存在する週だけ描画する。
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    week_count = len(weeks)

    grid_top = top + weekday_h
    available_grid_h = 456
    cell_h = available_grid_h / week_count
    grid_bottom = grid_top + cell_h * week_count
    line_color = (125, 120, 112, 255)
    line_width = 3

    for c in range(8):
        x = int(round(left + c * cw))
        d.line((x, int(round(grid_top)), x, int(round(grid_bottom))), fill=line_color, width=line_width)

    for r in range(week_count + 1):
        y = int(round(grid_top + r * cell_h))
        d.line((left, y, right, y), fill=line_color, width=line_width)

    pad_x = 10
    pad_y = 7
    holiday_map = japanese_holidays(year)

    for r, wk in enumerate(weeks):
        for c, day in enumerate(wk):
            if not day:
                continue
            s = str(day)
            is_holiday = (month, day) in holiday_map
            if c == 0 or is_holiday:
                color = (185,45,45,255)
            elif c == 6:
                color = (45,80,165,255)
            else:
                color = (20,20,20,255)

            x = int(round(left + c * cw + pad_x))
            y = int(round(grid_top + r * cell_h + pad_y))
            d.text((x, y), s, font=FONT_DAY, fill=color)

            cell_left = int(round(left + c * cw))
            cell_top = int(round(grid_top + r * cell_h))
            cell_right = int(round(left + (c + 1) * cw))
            cell_bottom = int(round(grid_top + (r + 1) * cell_h))

            matching_anniversaries = []
            if anniversaries:
                matching_anniversaries = [
                    a for a in anniversaries
                    if (month, day) == (a["month"], a["day"])
                ]

            # 祝日名
            holiday_name = holiday_map.get((month, day))
            holiday_label_img = None
            holiday_label_y = None

            if holiday_name and holiday_labels:
                holiday_label_img = holiday_labels.get(holiday_name)

                if holiday_label_img is not None:
                    if matching_anniversaries:
                        # 祝日 + うちのこ記念日が同日の場合:
                        # 祝日名を日付数字の右側に小さく置き、
                        # セル下部をうちのこ記念日のために空ける。
                        max_w = max(54, int((cell_right - cell_left) - 58))
                        max_h = 16

                        scale = min(
                            max_w / holiday_label_img.width,
                            max_h / holiday_label_img.height,
                            1.0
                        )
                        hw = max(1, int(round(holiday_label_img.width * scale)))
                        hh = max(1, int(round(holiday_label_img.height * scale)))
                        compact_holiday = holiday_label_img.resize(
                            (hw, hh), Image.Resampling.LANCZOS
                        )

                        lx = cell_left + 50
                        holiday_label_y = cell_top + 14
                        canvas.alpha_composite(
                            compact_holiday,
                            (lx, holiday_label_y)
                        )
                        holiday_label_img = compact_holiday

                    else:
                        # 通常の祝日は従来どおり
                        lx = cell_left + 6
                        holiday_label_y = cell_top + 46
                        canvas.alpha_composite(
                            holiday_label_img,
                            (lx, holiday_label_y)
                        )

            cat_event = CAT_DAYS.get((month, day))
            if cat_event:
                if cat_icon is not None:
                    icon_w = int(cw * 0.42)
                    icon_h = int(cat_icon.height * icon_w / cat_icon.width)
                    max_h = int(cell_h * 0.50)
                    if icon_h > max_h:
                        icon_h = max_h
                        icon_w = int(cat_icon.width * icon_h / cat_icon.height)

                    icon = cat_icon.resize((icon_w, icon_h), Image.Resampling.LANCZOS)
                    alpha = icon.getchannel("A").point(lambda v: int(v * 0.14))
                    ghost = Image.new("RGBA", icon.size, (90, 90, 90, 0))
                    ghost.putalpha(alpha)

                    ix = cell_left + (cell_right - cell_left - icon_w) // 2
                    iy = cell_top + (cell_bottom - cell_top - icon_h) // 2 + 2
                    canvas.alpha_composite(ghost, (ix, iy))

                if cat_labels:
                    label_img = cat_labels.get(cat_event)
                    if label_img is not None:
                        lx = cell_left + ((cell_right - cell_left) - label_img.width) // 2
                        ly = cell_bottom - label_img.height - 4
                        canvas.alpha_composite(label_img, (lx, ly))

            # うちのこ記念日（ユーザー指定・最大3件）
            if matching_anniversaries:
                if anniversary_heart is not None:
                    # ハートは右上。日付数字は左上なので干渉しにくい。
                    hx = cell_right - anniversary_heart.width - 7
                    hy = cell_top + 5
                    canvas.alpha_composite(anniversary_heart, (hx, hy))

                # 同じ日付に複数ある場合は1行にまとめる。
                date_key = (month, day)
                label_img = anniversary_labels.get(date_key) if anniversary_labels else None
                if label_img is not None:
                    # 6週表示などセルが低い月でも収まるよう、
                    # 必要に応じて記念日文字を自動縮小する。
                    available_w = max(70, int((cell_right - cell_left) - 8))
                    max_anniv_h = 18 if cell_h < 85 else 22

                    scale = min(
                        available_w / label_img.width,
                        max_anniv_h / label_img.height,
                        1.0
                    )
                    aw = max(1, int(round(label_img.width * scale)))
                    ah = max(1, int(round(label_img.height * scale)))
                    compact_anniv = label_img.resize(
                        (aw, ah), Image.Resampling.LANCZOS
                    )

                    ax = cell_left + ((cell_right - cell_left) - compact_anniv.width) // 2

                    # 基本はセル下部に配置。
                    ay = cell_bottom - compact_anniv.height - 3

                    # 猫記念日と同じ日は、猫記念日名の上へ。
                    if cat_event:
                        ay -= 25

                    # 祝日と同じ日は、祝日名を日付横へ逃がしているため
                    # うちのこ記念日は下部をそのまま使う。
                    canvas.alpha_composite(compact_anniv, (ax, ay))

    if logo:
        # 日付領域から離して、最下部中央に小さく配置
        lw = 112
        lh = int(logo.height * lw / logo.width)
        lg = logo.resize((lw, lh), Image.Resampling.LANCZOS)
        logo_x = (W - lw) // 2
        logo_y = H - lh - 22
        canvas.alpha_composite(lg, (logo_x, logo_y))

    return canvas.convert("RGB")



async def render_browser_label(text, width, height, font_px, color):
    data_url = await window.renderCalendarLabel(
        text, width, height, font_px, color
    )
    raw = base64.b64decode(str(data_url).split(",", 1)[1])
    return Image.open(BytesIO(raw)).convert("RGBA")

async def load_cat_day_icon():
    try:
        r = await window.fetch("./cat_day.png")
        ab = await r.arrayBuffer()
        arr = window.Uint8Array.new(ab)
        raw = bytes(arr.to_py())
        return Image.open(BytesIO(raw)).convert("RGBA")
    except Exception:
        return None

async def load_logo():
    try:
        r = await window.fetch("./logo.png")
        ab = await r.arrayBuffer()
        arr = window.Uint8Array.new(ab)
        raw = bytes(arr.to_py())
        return Image.open(BytesIO(raw)).convert("RGBA")
    except Exception:
        return None

def image_to_data_url(img):
    buf = BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    buf.close()
    return "data:image/jpeg;base64," + b64


def image_to_jpeg_bytes(img):
    buf = BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True)
    data = buf.getvalue()
    buf.close()
    return data

def pybytes_to_uint8(raw):
    arr = window.Uint8Array.new(len(raw))
    for i, b in enumerate(raw):
        arr[i] = b
    return arr

def add_result_card(month, data_url):
    results = document.getElementById("results")

    card = document.createElement("div")
    card.className = "result-card"

    img = document.createElement("img")
    img.src = data_url
    img.alt = f"{month}月カレンダー"
    img.loading = "lazy"

    title = document.createElement("div")
    title.className = "result-title"
    title.innerText = f"{month}月"

    card.appendChild(img)
    card.appendChild(title)
    results.appendChild(card)

@when("click", "#make_btn")
async def make_all(event):
    status = document.getElementById("status")
    progress = document.getElementById("progress")
    btn = document.getElementById("make_btn")

    year = int(document.getElementById("year").value)

    # 任意の「うちのこ記念日」：最大3件
    anniversaries = []

    for slot in (1, 2, 3):
        anniv_month_raw = str(document.getElementById(f"anniv_month_{slot}").value).strip()
        anniv_day_raw = str(document.getElementById(f"anniv_day_{slot}").value).strip()
        anniv_text = str(document.getElementById(f"anniv_text_{slot}").value).strip()

        if not anniv_month_raw:
            continue

        if not anniv_day_raw:
            status.innerText = f"うちのこ記念日 {slot} の日付を選んでください。"
            return

        if not anniv_text:
            status.innerText = f"うちのこ記念日 {slot} の内容を入力してください。"
            return

        anniv_month = int(anniv_month_raw)
        anniv_day = int(anniv_day_raw)
        max_day = calendar.monthrange(year, anniv_month)[1]

        if not (1 <= anniv_day <= max_day):
            status.innerText = f"うちのこ記念日 {slot} の日付が正しくありません。"
            return

        anniversaries.append({
            "month": anniv_month,
            "day": anniv_day,
            "text": anniv_text[:15],
        })

    # 同じ日付に複数の記念日を設定した場合、
    # 「・」を含めて1マス合計15文字まで。
    anniv_by_date = {}
    for anniv in anniversaries:
        key = (anniv["month"], anniv["day"])
        anniv_by_date.setdefault(key, []).append(anniv["text"])

    for (m, d), texts in anniv_by_date.items():
        combined = "・".join(texts)
        if len(combined) > 15:
            status.innerText = (
                f"{m}月{d}日のうちのこ記念日は、"
                f"「・」を含めて15文字以内にしてください。"
                f"（現在 {len(combined)}文字）"
            )
            return

    photos = window.selectedPhotos
    adjustments = window.photoAdjustments

    for i in range(12):
        if photos[i] is None:
            status.innerText = f"{i+1}月の写真がありません。"
            return

    btn.disabled = True
    progress.style.display = "block"
    progress.value = 0
    document.getElementById("results").innerHTML = ""
    document.getElementById("results_panel").classList.add("hidden")
    document.getElementById("desktop_download_btn").classList.add("hidden")

    GENERATED_JPEGS.clear()

    logo = await load_logo()
    cat_icon = await load_cat_day_icon()

    # 日本語ラベルはブラウザの日本語フォントで描画してPNG化
    cat_labels = {}
    for label in set(CAT_DAYS.values()):
        cat_labels[label] = await render_browser_label(
            label, 142, 24, 16, "#555555"
        )

    holiday_map_for_year = japanese_holidays(year)
    holiday_labels = {}
    for label in set(holiday_map_for_year.values()):
        holiday_labels[label] = await render_browser_label(
            label, 138, 22, 15, "#b92d2d"
        )

    anniversary_labels = {}
    anniversary_heart = None

    if anniversaries:
        # 同じ日付に複数ある場合は「・」でまとめる。
        by_date = {}
        for anniv in anniversaries:
            key = (anniv["month"], anniv["day"])
            by_date.setdefault(key, []).append(anniv["text"])

        for key, texts in by_date.items():
            combined = "・".join(texts)[:15]
            anniversary_labels[key] = await render_browser_label(
                combined, 142, 22, 15, "#b64f68"
            )

        anniversary_heart = await render_browser_label(
            "♥", 38, 38, 32, "#d85f7b"
        )

    try:
        for month in range(1, 13):
            status.innerText = f"{month}月を作成中… ({month}/12)"
            progress.value = month - 1
            await window.pauseFrame()

            photo = await js_file_to_image(photos[month-1])
            adj = adjustments[month-1]

            result = make_calendar(
                photo,
                year,
                month,
                x_adj=float(adj.x),
                y_adj=float(adj.y),
                zoom=float(adj.zoom),
                logo=logo,
                cat_icon=cat_icon,
                cat_labels=cat_labels,
                holiday_labels=holiday_labels,
                anniversaries=anniversaries,
                anniversary_labels=anniversary_labels,
                anniversary_heart=anniversary_heart
            )

            jpeg_bytes = image_to_jpeg_bytes(result)
            GENERATED_JPEGS[month] = jpeg_bytes
            data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
            add_result_card(month, data_url)

            del result, photo
            progress.value = month
            await window.pauseFrame()

        status.innerText = "12か月分が完成しました。下の画像を保存してください。"
        document.getElementById("results_panel").classList.remove("hidden")

        if window.isDesktopLike():
            document.getElementById("desktop_download_btn").classList.remove("hidden")

        document.getElementById("results_panel").scrollIntoView({"behavior":"smooth"})

    except Exception as e:
        status.innerText = f"エラー: {e}"
        raise
    finally:
        btn.disabled = False


@when("pydownload", "#desktop_download_btn")
async def download_all_pc(event):
    status = document.getElementById("status")

    if len(GENERATED_JPEGS) != 12:
        status.innerText = "12か月分の画像がまだ完成していません。"
        return

    year = int(document.getElementById("year").value)
    status.innerText = "12か月分をZIPにまとめています…"

    zbuf = BytesIO()
    with ZipFile(zbuf, "w", ZIP_DEFLATED) as zf:
        for month in range(1, 13):
            zf.writestr(
                f"nekofukuro_calendar_{year}_{month:02d}.jpg",
                GENERATED_JPEGS[month]
            )

    raw = zbuf.getvalue()
    zbuf.close()

    window.downloadBytes(
        f"nekofukuro_calendar_{year}.zip",
        pybytes_to_uint8(raw),
        "application/zip"
    )
    status.innerText = "12か月分のZIPをダウンロードしました。"
