import csv
import html
from datetime import datetime
from pathlib import Path

from .email_step import GROUP_LABELS, EmailReport
from .funnel import Transition
from .segments import Segment

# (substring in "dim=value" lowercased, hint). First match wins; checked in order.
HINTS = [
    ("iab", "Вбудований браузер Meta: перевірте автозаповнення, чи клавіатура не перекриває кнопку, поведінку viewport. Відтворіть на реальному пристрої."),
    ("in-app", "Вбудований браузер: перевірте автозаповнення та перекриття кнопки клавіатурою."),
    ("creative_id", "Креатив приводить менш намірений трафік або обіцяє не те, що показує квіз. Звірте обіцянку креативу з першим екраном, розгляньте окремий вхід або вимкнення."),
    ("browser=safari", "Safari/iOS: перевірте валідацію полів і автозаповнення (iCloud Keychain)."),
    ("os=ios", "iOS: перевірте поведінку клавіатури та автозаповнення."),
    ("os=android", "Android: перевірте клавіатуру та розміри viewport на типових пристроях."),
    ("device=mobile", "Мобільні: перевірте розмір полів, клавіатуру, видимість кнопки."),
    ("country", "Країна: перевірте мову, формат телефону/адреси та довіру до форми збору email."),
]
GENERIC_HINT = "Відтворіть крок у цьому сегменті та подивіться записи сесій."

ERROR_HINTS = {
    "typo_domain": "Додайте підказку «Ви мали на увазі gmail.com?» замість жорсткої помилки.",
    "plus_sign_rejected": "Валідатор відхиляє адреси з «+» — це валідні email. Послабте правило.",
    "invalid_format": "Покажіть, що саме не так, і не очищайте поле після помилки.",
}


def hint_for(seg: Segment) -> str:
    text = seg.label.lower()
    return next((h for key, h in HINTS if key in text), GENERIC_HINT)


DIM_NAMES = {"os": "ОС", "device": "пристрій", "browser": "браузер", "country": "країна", "utm_source": "джерело трафіку",
             "creative_id": "креатив", "weekday": "день тижня", "daypart": "час доби",
             # Amplitude (web SDK): os_name holds the browser, device_family the operating system
             "os_name": "браузер (os_name)", "device_family": "ОС (device_family)", "device_type": "пристрій (device_type)",
             "platform": "платформа", "city": "місто", "language": "мова", "os_version": "версія", "utm_campaign": "кампанія"}
VALUE_NAMES = {"daypart": {"night": "ніч (00–06)", "morning": "ранок (06–12)", "afternoon": "день (12–18)", "evening": "вечір (18–24)"},
               "weekday": {"Mon": "понеділок", "Tue": "вівторок", "Wed": "середа", "Thu": "четвер", "Fri": "пʼятниця",
                           "Sat": "субота", "Sun": "неділя"}}


def human_label(seg: Segment) -> str:
    """'daypart=evening' -> 'час доби: вечір (18–24)'; several conditions are joined with ' і '."""
    return " і ".join(f"{DIM_NAMES.get(d, d)}: {VALUE_NAMES.get(d, {}).get(v, v)}" for d, v in seg.parts)


def explain(seg: Segment, step: str) -> str:
    n = f"{seg.n:,}".replace(",", " ")
    return (f"З {n} людей із групи «{human_label(seg)}», що дійшли до кроку `{step}`, далі пішли {pct(seg.rate)}, "
            f"а з усіх інших — {pct(seg.rest_rate)}. Якби ця група проходила так само, як усі інші, це було б приблизно "
            f"{usd(seg.egp_month)} на місяць (максимум, не прогноз).")


def pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def usd(x: float) -> str:
    return f"${x:,.0f}".replace(",", " ")


def write_segments_csv(path: Path, segs: list[Segment]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["segment", "sessions", "rate", "rest_rate", "gap_pp", "q_value", "extra_purchases_month", "egp_month", "hint"])
        for s in segs:
            w.writerow([s.label, s.n, f"{s.rate:.4f}", f"{s.rest_rate:.4f}", f"{s.gap_pp:.2f}", f"{s.q:.2g}",
                        f"{s.extra_purchases_month:.1f}", f"{s.egp_month:.0f}", hint_for(s)])



def example_sentence(seg, step: str) -> str:
    """One concrete sentence that explains the two columns using the first found group."""
    n = format(seg.n, ",").replace(",", " ")
    return (f"Група: «{human_label(seg)}», це {n} людей. Усі вони дійшли до кроку {step}; далі пішли {pct(seg.rate)} з них. "
            f"Решта: усі інші люди, що теж дійшли до кроку {step}, але до цієї групи не належать (мають інший браузер, пристрій чи креатив); "
            f"з них далі пішли {pct(seg.rest_rate)}.")


def build_markdown(*, src: str, n_sessions: int, trs: list[Transition], focus: Transition, focus_note: str,
                   segs: list[Segment], n_tests: int, email: EmailReport | None, clean_dims: list[str],
                   skipped_dims: list[str], sample_n: int, sample_days: float, target_lift: float,
                   monthly_clicks: int, ltv: float, min_n: int, users: list[dict] | None = None,
                   by_step: list[dict] | None = None) -> str:
    L = []
    L.append(f"# QuizLeak: звіт про витік у квізі\n")
    L.append(f"**Перевірена таблиця:** `{src}`\n")
    L.append(f"Сесій: {n_sessions:,} · перевірено: {datetime.now():%Y-%m-%d %H:%M} · масштаб до місяця: {monthly_clicks:,} кліків · LTV ${ltv:.0f}\n".replace(",", " "))
    L.append(f"**Головний витік:** `{focus.src}` → `{focus.dst}`: проходять {pct(focus.rate)}, "
             f"втрачаємо {focus.lost_pct_of_start:.1f} п.п. від усіх кліків. {focus_note}\n")

    L.append("## Воронка\n")
    L.append("| Крок → крок | Дійшли | Пройшли далі | Конверсія кроку | Втрата, п.п. від старту |")
    L.append("|---|---:|---:|---:|---:|")
    for t in trs:
        mark = " ⬅" if t.src == focus.src else ""
        L.append(f"| {t.src} → {t.dst}{mark} | {t.n_src} | {t.n_dst} | {pct(t.rate)} | {t.lost_pct_of_start:.1f} |")

    if email:
        L.append(f"\n## Що відбувається всередині кроку `{focus.src}` (email)\n")
        L.append(f"З {email.n} сесій, що дійшли до кроку:\n")
        L.append("| Група | Сесій | Частка |")
        L.append("|---|---:|---:|")
        for key, label in GROUP_LABELS.items():
            c, sh = email.groups[key]
            L.append(f"| {label} | {c} | {pct(sh)} |")
        if email.errors:
            L.append("\n**Помилки валідації** (скільки сесій і яка частка пішла після неї):\n")
            L.append("| Помилка | Сесій | Пішли | EGP/міс (стеля) | Що робити |")
            L.append("|---|---:|---:|---:|---|")
            for code, n, q, e in email.errors:
                L.append(f"| `{code}` | {n} | {pct(q, 0)} | {usd(e)} | {ERROR_HINTS.get(code, '')} |")
            L.append(f"\nРазом, якби сесії з помилкою проходили так само, як без помилки: **{usd(email.egp_all_errors)}/міс** (стеля). "
                     "Ці сесії частково входять і в сегменти нижче, тому з ними цю суму не додавайте.")
        if email.bad_domains:
            doms = ", ".join(f"`{d}` ({n})" for d, n, _ in email.bad_domains)
            L.append(f"\nДомени в помилках: {doms}")

    L.append(f"\n## Сегменти, що витікають сильніше за решту\n")
    L.append(f"У першому проході перевірено {n_tests} сегментів (одиничні та пари атрибутів, ≥{min_n} сесій). "
             f"Лишились ті, що значущо гірші після поправки на множинні порівняння (FDR 5%) і відстають мінімум на 2 п.п.\n")
    if segs:
        L.append(f"Нижче — групи людей, які крок `{focus.src}` проходять помітно гірше, ніж усі інші. "
                 "Читати так: «Ця група: пішли далі» — яка частка людей групи, що дійшли до кроку, пішла далі; «Усі інші люди: пішли далі» — те саме для людей, що в цю групу не входять.\n")
        L.append("**Приклад з цього звіту.** " + example_sentence(segs[0], focus.src) + "\n\n")
        L.append("| # | Група людей | Скільки людей у групі | Ця група: пішли далі | Усі інші люди: пішли далі | Різниця | Втрачаємо на місяць (максимум) | Що перевірити |")
        L.append("|---:|---|---:|---:|---:|---:|---:|---|")
        for i, s in enumerate(segs, 1):
            L.append(f"| {i} | {human_label(s)} (`{s.label}`) | {s.n} | {pct(s.rate)} | {pct(s.rest_rate)} | −{s.gap_pp:.1f} п.п. | "
                     f"{usd(s.egp_month)} | {hint_for(s)} |")
        L.append("\nПростими словами:\n")
        for i, s in enumerate(segs, 1):
            L.append(f"{i}. {explain(s, focus.src)}")
        L.append(f"\nСегменти не перетинаються (кожен наступний шукали серед сесій, що лишились), тому суми можна додавати: "
                 f"**{usd(sum(s.egp_month for s in segs))} на місяць** (максимум: стільки було б, якби всі ці групи проходили крок так само, як усі інші; це не прогноз).")
    elif n_tests == 0:
        L.append(f"**Замало даних для висновків:** жодного сегмента з ≥{min_n} сесій на цьому кроці. "
                 "Візьміть довший період або знизьте --min-n (тоді висновки менш надійні).")
    else:
        L.append("Значущих сегментів не знайдено: витік рівномірний, шукайте причину в самому кроці (копірайт, поле, довіра), а не в пристроях.")
    if clean_dims and n_tests:
        L.append(f"\nЗначущого впливу **не знайдено** в: {', '.join(clean_dims)}.")
    if skipped_dims:
        L.append(f"Пропущено через забагато унікальних значень: {', '.join(skipped_dims)}.")

    if users:
        L.append(f"\n## Хто саме відпав\n")
        total = f"{len(users):,}".replace(",", " ")
        L.append(f"На кроці `{focus.src}` відпали **{total}** людей. Повний список (хто, коли, де зупинився, з якого пристрою і браузера, "
                 "яку помилку бачив) лежить у файлі `dropped_users.csv`: відкрийте в Excel або Numbers, відфільтруйте й відсортуйте. "
                 "Угорі списку ті, хто потрапив у знайдені групи вище. Перші 15:\n")
        L.append("| Користувач | Коли відпав | Де зупинився | Що сталося | Помилка | Група |")
        L.append("|---|---|---|---|---|---|")
        for r in users[:15]:
            L.append(f"| `{r['Користувач (session_id)']}` | {r['Коли відпав']} | {r['Де зупинився']} | {r['Що сталося']} | "
                     f"{r['Помилка']} | {r['Група, до якої належить']} |")
    if by_step:
        L.append("\n## Завантажити тих, хто відпав на будь-якому кроці\n")
        L.append("Для кожного переходу є окремий файл: усі, хто дійшов до кроку, але далі не пішов. Відкривається в Excel або Numbers.\n")
        L.append("| Перехід | Людей відпало | Файл |")
        L.append("|---|---:|---|")
        for b in by_step:
            L.append(f"| `{b['src']}` → `{b['dst']}` | {format(b['n'], ',').replace(',', ' ')} | `{b['file']}` |")
    L.append("\n## Як підтвердити виправлення\n")
    L.append(f"Щоб надійно побачити зростання конверсії кроку `{focus.src}` на {target_lift * 100:.0f} п.п. "
             f"(з {pct(focus.rate)} до {pct(focus.rate + target_lift)}) в A/B-тесті, потрібно **~{sample_n} сесій на кожну гілку** "
             f"(альфа 5%, потужність 80%). За поточного трафіку це ≈ {sample_days:.1f} дня на тест.")
    L.append("\n## Обмеження\n")
    L.append("- Це кореляція в даних, а не доказ причини: сегмент натякає, де дивитися, підтверджує A/B-тест.\n"
             "- Переміщення з кроку на крок рахується за наявністю подій, а не за порядком у часі.\n"
             "- Оцінка EGP припускає, що втрачені в сегменті сесії конвертуються далі, як усі інші (на практиці гірше).")
    if trs[0].src not in ("session_start", "landing_viewed", "page_viewed"):
        L.append(f"- Воронка починається з події `{trs[0].src}`. Якщо до неї є кліки, що не дійшли до квізу, масштаб до місяця "
                 "(кліки ÷ сесії) і гроші можуть бути завищені. Додайте подію першого візиту або вкажіть --monthly-clicks під реальну кількість стартів.")
    return "\n".join(L) + "\n"


USER_COLS = ["Користувач (session_id)", "Коли відпав", "Де зупинився", "Що сталося", "Помилка", "Домен у помилці",
             "Секунд на кроці", "Група, до якої належить"]
USERS_JS = r"""
(function(){
var el=document.getElementById('ud');if(!el)return;
var D=JSON.parse(el.textContent),cols=D.cols,all=D.rows,view=all.slice(),page=0,size=50,sortK=-1,asc=true;
var t=document.getElementById('u'),f=document.getElementById('uf'),info=document.getElementById('ui'),sel=document.getElementById('us');
var prev=document.getElementById('up'),next=document.getElementById('un'),dl=document.getElementById('udl'),pg=document.getElementById('upg');
t.tHead.innerHTML='<tr>'+cols.map(function(c){return '<th>'+c.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</th>';}).join('')+'</tr>';
function esc(v){return String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function pages(){return Math.max(1,Math.ceil(view.length/size));}
function draw(){
  if(page>=pages())page=pages()-1;
  var rows=view.slice(page*size,page*size+size);
  t.tBodies[0].innerHTML=rows.map(function(r){return '<tr>'+r.map(function(v){return '<td>'+esc(v)+'</td>';}).join('')+'</tr>';}).join('');
  info.textContent='знайдено '+view.length.toLocaleString('uk')+' з '+all.length.toLocaleString('uk');
  pg.textContent='Сторінка '+(page+1)+' з '+pages();
  prev.disabled=page===0;next.disabled=page>=pages()-1;
}
function filt(){var q=f.value.toLowerCase();view=q?all.filter(function(r){return r.join(' ').toLowerCase().indexOf(q)>=0;}):all.slice();
  if(sortK>=0)doSort();page=0;draw();}
function doSort(){var k=sortK;view.sort(function(x,y){var a=String(x[k]),z=String(y[k]),na=parseFloat(a),nz=parseFloat(z);
  var r=(/^-?[0-9.]+$/.test(a)&&/^-?[0-9.]+$/.test(z))?na-nz:a.localeCompare(z);return asc?r:-r;});}
t.tHead.addEventListener('click',function(e){var th=e.target.closest('th');if(!th)return;var k=th.cellIndex;
  if(k===sortK)asc=!asc;else{sortK=k;asc=true;}doSort();page=0;draw();});
f.addEventListener('input',filt);
sel.addEventListener('change',function(){size=parseInt(sel.value,10);page=0;draw();});
prev.addEventListener('click',function(){if(page>0){page--;draw();}});
next.addEventListener('click',function(){if(page<pages()-1){page++;draw();}});
dl.addEventListener('click',function(){
  function q(v){v=String(v);return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;}
  var txt='\ufeff'+[cols].concat(view).map(function(r){return r.map(q).join(',');}).join('\n');
  var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([txt],{type:'text/csv;charset=utf-8'}));
  a.download='dropped_users_filtered.csv';document.body.appendChild(a);a.click();a.remove();});
draw();})();
"""


def _users_html(users: list[dict], step: str) -> str:
    import json
    cols = USER_COLS + [c for c in users[0] if c not in USER_COLS]
    data = json.dumps({"cols": cols, "rows": [[str(r.get(c, "")) for c in cols] for r in users]}, ensure_ascii=False)
    data = data.replace("</", "<\\/")
    total = f"{len(users):,}".replace(",", " ")
    return (f"<h2>Хто саме відпав</h2><p>Усі, хто дійшов до кроку <b>{html.escape(step)}</b>, але далі не пішов: "
            f"<b>{total}</b> людей. Угорі ті, хто потрапив у групи вище. Клік по заголовку колонки сортує весь список, "
            f"у полі нижче можна шукати по всіх (наприклад, <code>Android</code>, <code>вечір</code>, <code>plus_sign</code>). "
            f"Кнопка «Завантажити CSV» зберігає саме те, що зараз знайдено.</p>"
            f'<input id="uf" class="f" placeholder="Фільтр: введіть слово…"> <span class="dim" id="ui"></span>'
            f'<div class="pager"><button id="up">← Назад</button> <span id="upg" class="dim"></span> <button id="un">Далі →</button> '
            f'<label class="dim">по <select id="us"><option>50</option><option>100</option><option>500</option></select> на сторінці</label> '
            f'<button id="udl">Завантажити CSV</button></div>'
            f'<div class="scroll"><table id="u"><thead></thead><tbody></tbody></table></div>'
            f'<script type="application/json" id="ud">{data}</script>')


def _by_step_html(by_step: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(b['src'])} → {html.escape(b['dst'])}</td><td class=\"n\">{format(b['n'], ',').replace(',', ' ')}</td>"
        f"<td><a href=\"{html.escape(b['file'])}\" download>Завантажити CSV</a></td></tr>" for b in by_step)
    return ("<h2>Завантажити тих, хто відпав на будь-якому кроці</h2>"
            "<p>Для кожного переходу окремий файл: усі, хто дійшов до кроку, але далі не пішов (наприклад, <code>step_2 → step_3</code> "
            "це ті, хто був на кроці 2 і не дійшов до 3). Файли лежать у папці <code>dropped_by_step</code> поруч зі звітом; "
            "якщо переносите звіт, переносьте папку разом з ним.</p>"
            f'<div class="scroll"><table><tr><th>Перехід</th><th>Людей відпало</th><th>Файл</th></tr>{rows}</table></div>')


def build_html(trs: list[Transition], focus: Transition, segs: list[Segment], md_title: str, src: str = "",
               n_sessions: int = 0, users: list[dict] | None = None, by_step: list[dict] | None = None) -> str:
    n0 = trs[0].n_src
    bars = []
    for t in trs[:]:
        w = t.n_src / n0 * 100
        cls = "bar focus" if t.src == focus.src else "bar"
        bars.append(f'<div class="row"><div class="lbl">{html.escape(t.src)}</div>'
                    f'<div class="track"><div class="{cls}" style="width:{w:.1f}%"></div></div>'
                    f'<div class="val">{w:.1f}% <span class="dim">→ {pct(t.rate)}</span></div></div>')
    last = trs[-1]
    bars.append(f'<div class="row"><div class="lbl">{html.escape(last.dst)}</div><div class="track">'
                f'<div class="bar" style="width:{max(last.n_dst / n0 * 100, 0.4):.1f}%"></div></div>'
                f'<div class="val">{last.n_dst / n0 * 100:.1f}%</div></div>')
    rows = "".join(
        f"<tr><td>{i}</td><td><b>{html.escape(human_label(s))}</b><br><code>{html.escape(s.label)}</code></td><td>{s.n}</td><td>{pct(s.rate)}</td>"
        f"<td>{pct(s.rest_rate)}</td><td>−{s.gap_pp:.1f} п.п.</td><td><b>{usd(s.egp_month)}</b></td>"
        f"<td>{html.escape(hint_for(s))}</td></tr>" for i, s in enumerate(segs, 1))
    plain = "<h2>Простими словами</h2><ol>" + "".join(
        f"<li>{html.escape(explain(sg, focus.src).replace('`', ''))}</li>" for sg in segs) + "</ol>" if segs else ""
    users_html = (_by_step_html(by_step) if by_step else "") + (_users_html(users, focus.src) if users else "")
    return f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QuizLeak · {html.escape(src)}</title><style>
:root{{--bg:#fff;--fg:#1d2433;--mut:#667;--bar:#9db6d6;--focus:#d9534f;--line:#e3e7ee}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12161d;--fg:#e8ebf0;--mut:#98a2b3;--bar:#4a6a94;--focus:#e5645f;--line:#2a3140}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}}
main{{max-width:980px;margin:auto}} h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px}}
.row{{display:grid;grid-template-columns:110px 1fr 150px;gap:8px;align-items:center;margin:4px 0}}
.track{{background:var(--line);border-radius:4px;height:18px}} .bar{{background:var(--bar);height:100%;border-radius:4px}} .bar.focus{{background:var(--focus)}}
.dim,.lbl{{color:var(--mut)}} .val{{font-variant-numeric:tabular-nums}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
.scroll{{overflow-x:auto}} code{{font-size:12px}}\ninput.f{{width:100%;max-width:420px;padding:8px 10px;margin:6px 0 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}}\n#u th{{cursor:pointer;white-space:nowrap}} .pager{{margin:6px 0 10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .pager button,.pager select{{padding:5px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit;cursor:pointer}} .pager button:disabled{{opacity:.4;cursor:default}} #u th:hover{{text-decoration:underline}}
</style></head><body><main><h1>QuizLeak</h1>
<p><b>Перевірена таблиця:</b> <code>{html.escape(src)}</code> · сесій: {format(n_sessions, ',').replace(',', ' ')} · перевірено: {datetime.now():%Y-%m-%d %H:%M}</p>
<p class="dim">Червоним — головний витік: <b>{html.escape(focus.src)} → {html.escape(focus.dst)}</b> (проходять {pct(focus.rate)}).</p>
<h2>Воронка (частка від усіх кліків → конверсія кроку)</h2>{''.join(bars)}
<h2>Групи людей, які відвалюються сильніше за решту</h2>
<p>Скрипт порівняв групи людей (за пристроєм, браузером, часом доби тощо) і шукав ті, що крок <b>{html.escape(focus.src)}</b> проходять помітно гірше, ніж усі інші.</p>
<p class="dim"><b>Приклад з цього звіту.</b> {html.escape(example_sentence(segs[0], focus.src)) if segs else ""}</p>
<div class="scroll"><table><tr><th>#</th><th>Група людей</th><th>Скільки людей у групі</th><th>Ця група: пішли далі</th><th>Усі інші люди: пішли далі</th><th>Різниця</th><th>Втрачаємо на місяць (максимум)</th><th>Що перевірити</th></tr>{rows}</table></div>
{plain}
<p class="dim">Групи не перетинаються, суми можна додавати. «Максимум» — це не прогноз, а скільки було б, якби група проходила крок так само, як усі інші. Повні деталі — у report.md.</p>
{users_html}
</main><script>{USERS_JS}</script></body></html>"""
