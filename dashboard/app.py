# Интерфейс дашборда. Запуск: streamlit run app.py
# Здесь только отрисовка. Расчёты лежат в core/metrics.py, разбор комментариев в core/comments.py.
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import comments, db, effect, ingest, llm, mail, metrics, playbook
from core.config import RED, YELLOW, demo_dir

st.set_page_config(page_title="МГТС · Дашборд стажировок", layout="wide")

BLUE, ORANGE = "#0098EA", "#003B73"
SCALE = [[0, "#DC2626"], [0.5, "#F59E0B"], [1, "#0098EA"]]  # 1 критично, 3 внимание, 5 отлично
# Светофор по ТЗ: критичный сигнал / зона внимания / положительная оценка
ZONE = {"высокий": "Критичный сигнал", "средний": "Зона внимания", "низкий": "Всё хорошо"}
ZONE_EMOJI = {"высокий": "🔴 Критичный сигнал", "средний": "🟡 Зона внимания", "низкий": "🟢 Всё хорошо"}
ZONE_COLOR = {"высокий": "red", "средний": "orange", "низкий": "green"}

st.markdown(
    """<style>
    .mgts-bar {background: linear-gradient(95deg, #001C3D 0%, #004E98 60%, #0098EA 100%);
               color: white; padding: 14px 20px; border-radius: 12px; margin-bottom: 16px;
               display: flex; align-items: center; justify-content: space-between;
               box-shadow: 0 2px 10px rgba(0,28,61,0.12);}
    .mgts-sq {background: #0098EA; color: white; font-weight: 800; width: 42px; height: 42px;
              border-radius: 6px; display: inline-flex; align-items: center; justify-content: center;
              font-size: 13px; letter-spacing: 0.4px; margin-right: 12px; flex-shrink: 0;}
    .mgts-side-brand {display: flex; align-items: center; gap: 10px; padding: 6px 2px 14px 2px;
                      border-bottom: 1px solid #D9E6F2; margin-bottom: 12px;}
    .mgts-tl-grid {display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 10px 0 18px 0;}
    .mgts-tl-card {background: #FFFFFF; border-radius: 10px; padding: 14px 16px;
                   border: 1px solid #E2ECF5; display: flex; align-items: center; gap: 14px;
                   box-shadow: 0 1px 4px rgba(0,28,61,0.05);}
    .mgts-dot {width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0;}
    .mgts-tl-num {font-size: 26px; font-weight: 700; line-height: 1.1; color: #0A1F38;}
    .mgts-tl-lbl {font-size: 13px; color: #5A6E85; margin-top: 2px;}
    .score-tbl {width: 100%; border-collapse: separate; border-spacing: 4px; font-size: 13.5px; margin-top: 6px;}
    .score-tbl th {text-align: center; color: #5A6E85; font-weight: 600; padding: 6px 8px; font-size: 12px;}
    .score-tbl th:first-child {text-align: left;}
    .score-tbl td {text-align: center; padding: 7px 10px; border-radius: 6px; font-weight: 600;}
    .score-tbl td:first-child {text-align: left; font-weight: 500; color: #0A1F38; background: #F6FAFE; padding-left: 10px;}
    .sc-hi {background: #DCFCE7; color: #166534;}
    .sc-mid {background: #FEF3C7; color: #92400E;}
    .sc-lo {background: #FEE2E2; color: #991B1B;}
    .sc-na {background: #F1F5F9; color: #94A3B8; font-weight: 400;}
    </style>""",
    unsafe_allow_html=True,
)


def render_score_table(table):
    # Читаемая корпоративная таблица оценок вместо сжатой тепловой карты
    headers = "".join(f"<th>Мес. {m}</th>" for m in table.columns)
    rows_html = []
    for label, row in table.iterrows():
        cells = [f"<td>{label}</td>"]
        for val in row:
            if pd.isna(val):
                cells.append('<td class="sc-na">—</td>')
            elif val >= 4.0:
                cells.append(f'<td class="sc-hi">{val:.1f}</td>')
            elif val >= 3.0:
                cells.append(f'<td class="sc-mid">{val:.1f}</td>')
            else:
                cells.append(f'<td class="sc-lo">{val:.1f}</td>')
        rows_html.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="score-tbl"><thead><tr><th>Показатель</th>{headers}</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'


def badge(level):
    return f":{ZONE_COLOR[level]}-background[{ZONE_EMOJI[level]}]"
PAGES = ["Обзор", "Стажёр", "Эффект", "Анкета", "Данные"]


@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()


def load_all(target_month=None):
    a = metrics.load(conn)
    # ответы на вопросы, которых нет в текущем файле сопоставления, не считаем (например, остались от старой анкеты)
    known = a[a["kind"].notna()]
    st.session_state["stale"] = len(a) > 0 and known.empty
    if known.empty:
        return None
    a = known
    mon = metrics.monthly(a)
    if mon.empty:
        return None
    com = metrics.comments(conn, a)
    risk = metrics.risk_table(mon, com, a, last_month=target_month).merge(metrics.people(a), on="intern")
    return a, mon, com, risk


def load_demo():
    db.clear(conn)
    for name, role in [("otvety_stazhery", "intern"), ("otvety_nastavniki", "mentor")]:
        ingest.ingest(conn, next(demo_dir().glob(name + ".*")), role)
    return comments.run(conn)


def ensure_initial_data():
    # При первом открытии в облаке (Streamlit Cloud / Amvera) сразу подгружаем историю МГТС,
    # чтобы эксперт видел готовый дашборд без лишних кликов (в автотестах не вмешиваемся).
    if os.getenv("PYTEST_CURRENT_TEST") or st.session_state.get("bootstrapped"):
        return
    st.session_state["bootstrapped"] = True
    if metrics.load(conn).empty and (demo_dir() / "otvety_stazhery.csv").exists():
        load_demo()


ensure_initial_data()


def style(fig, height=320):
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="white", font=dict(size=13),
        legend=dict(orientation="h", y=1.12, x=0),
        hoverlabel=dict(bgcolor="white"),
    )
    fig.update_xaxes(gridcolor="#eeeeee", zeroline=False)
    fig.update_yaxes(gridcolor="#eeeeee", zeroline=False)
    return fig


def delta(now, before):
    if pd.isna(now) or pd.isna(before):
        return None
    return f"{now - before:+.1f}"


def heatmap(table, height):
    fig = go.Figure(go.Heatmap(
        z=table.values, x=[f"{m} мес." for m in table.columns], y=list(table.index),
        zmin=1, zmax=5, colorscale=SCALE, xgap=2, ygap=2,
        text=table.round(1).astype(str).replace("nan", "нет").values, texttemplate="%{text}",
        hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
        colorbar=dict(title="оценка", thickness=12),
    ))
    fig.update_yaxes(autorange="reversed")
    return style(fig, height)


def open_card():
    # вызывается при клике на строку в таблице "Кому нужно внимание"
    rows = st.session_state["attention"]["selection"]["rows"]
    if rows:
        st.session_state["intern"] = st.session_state["attention_names"][rows[0]]
        st.session_state["page"] = "Стажёр"


# ---------- боковая панель ----------
st.sidebar.markdown(
    '<div class="mgts-side-brand">'
    '<div class="mgts-sq">МГТС</div>'
    '<div><div style="font-weight:700;font-size:15px;color:#001C3D;line-height:1.2;">Стажировки</div>'
    '<div style="font-size:12px;color:#5A6E85;">HR-аналитика</div></div></div>',
    unsafe_allow_html=True,
)
page = st.sidebar.radio("Раздел", PAGES, key="page")
base_data = load_all()
if base_data:
    months_avail = sorted(int(m) for m in base_data[1]["month"].dropna().unique())
    selected_month = st.sidebar.selectbox(
        "Контрольный период",
        months_avail,
        index=len(months_avail) - 1,
        format_func=lambda m: f"Месяц {m}",
        key="period_month",
    )
    data = base_data if selected_month == months_avail[-1] else load_all(target_month=selected_month)
    depts = sorted(data[3]["dept"].unique())
    chosen = st.sidebar.multiselect("Подразделение", depts, placeholder="Все")
else:
    selected_month = None
    data = None
    chosen = []
model = llm.name()
st.sidebar.caption(f"ИИ-анализ: {model}" if model else "Офлайн-режим: словарь сигналов")


# Раз в минуту забираем новые ответы из почты (форма шлёт письмо после каждого заполнения).
# Если что-то пришло, перерисовываем весь дашборд, чтобы новый ответ сразу попал в ленту и графики.
@st.fragment(run_every="60s")
def mail_watch():
    if not mail.configured():
        return
    # фрагмент выполняется и при каждом клике в дашборде, а заходить в почту нужно не чаще раза в минуту
    last = st.session_state.get("mail_last")
    if last is None or time.time() - last[0] >= 50:
        stats = mail.fetch(conn)
        last = (time.time(), stats)
        st.session_state["mail_last"] = last
        if stats["ответов"]:
            st.rerun(scope="app")
    _, stats = last
    if stats["ошибки"]:
        st.caption(f"Почта: {stats['ошибки'][0]}")


with st.sidebar:
    mail_watch()


# ---------- обзор ----------
def page_overview():
    a, mon, com, risk = data
    all_answers = data[0]
    people_names = set(all_answers["intern"].dropna().astype(str)) | set(all_answers["mentor"].dropna().astype(str))
    if chosen:
        risk = risk[risk["dept"].isin(chosen)]
    names = set(risk["intern"])
    last = int(selected_month) if selected_month is not None else int(data[1]["month"].max())
    a = a[a["intern"].isin(names) & (a["month"] <= last)]
    mon = mon[mon["intern"].isin(names) & (mon["month"] <= last)]
    com = com[com["intern"].isin(names) & (com["month"] <= last)]
    cur, prev = mon[mon["month"] == last], mon[mon["month"] == last - 1]

    s_ans = a.loc[(a["month"] == last) & (a["role"] == "intern") & a["kind"].ne("time"), "intern"].nunique()
    m_ans = a.loc[(a["month"] == last) & (a["role"] == "mentor") & a["kind"].ne("time"), "intern"].nunique()
    high = int((risk["level"] == "высокий").sum())
    mid = int((risk["level"] == "средний").sum())
    low = int((risk["level"] == "низкий").sum())

    st.markdown(
        f'<div class="mgts-bar"><div style="display:flex;align-items:center;">'
        f'<div class="mgts-sq">МГТС</div>'
        f'<div><div style="font-weight:700;font-size:18px;">Аналитика программы стажировок · Месяц {last} из 6</div>'
        f'<div style="font-size:12.5px;opacity:0.85;">Статус прохождения, динамика и сигналы для HR</div></div></div>'
        f'<div style="font-size:13px;font-weight:600;">Опросы: стажёры {s_ans}/{len(names)} · наставники {m_ans}/{len(names)}</div></div>',
        unsafe_allow_html=True,
    )

    has_nps = a["kind"].eq("nps").any()
    k = st.columns(5 if has_nps else 4)
    k[0].metric("Стажёров в программе", len(names))
    s_mean, s_prev = cur["s_avg"].mean(), prev["s_avg"].mean()
    m_mean, m_prev = cur["m_avg"].mean(), prev["m_avg"].mean()
    k[1].metric("Средняя стажёров", "нет данных" if pd.isna(s_mean) else f"{s_mean:.1f} / 5", delta(s_mean, s_prev))
    k[2].metric("Средняя наставников", "нет данных" if pd.isna(m_mean) else f"{m_mean:.1f} / 5", delta(m_mean, m_prev))
    if has_nps:
        e_now, e_prev = metrics.enps(mon, last), metrics.enps(mon, last - 1)
        k[3].metric("eNPS", e_now, None if e_now is None or e_prev is None else f"{e_now - e_prev:+d}")
        k[4].metric("Сдали анкеты (С / Н)", f"{s_ans}/{len(names)} · {m_ans}/{len(names)}")
    else:
        k[3].metric("Сдали анкеты (С / Н)", f"{s_ans}/{len(names)} · {m_ans}/{len(names)}")

    st.markdown(
        f'<div class="mgts-tl-grid">'
        f'<div class="mgts-tl-card" style="border-left:4px solid #DC2626;">'
        f'<div class="mgts-dot" style="background:#DC2626;"></div>'
        f'<div><div class="mgts-tl-num">{high}</div><div class="mgts-tl-lbl">Критичный сигнал — нужен разговор</div></div></div>'
        f'<div class="mgts-tl-card" style="border-left:4px solid #D97706;">'
        f'<div class="mgts-dot" style="background:#D97706;"></div>'
        f'<div><div class="mgts-tl-num">{mid}</div><div class="mgts-tl-lbl">Зона внимания — проверить детали</div></div></div>'
        f'<div class="mgts-tl-card" style="border-left:4px solid #16A34A;">'
        f'<div class="mgts-dot" style="background:#16A34A;"></div>'
        f'<div><div class="mgts-tl-num">{low}</div><div class="mgts-tl-lbl">Положительная оценка — всё стабильно</div></div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.subheader(f"Статус прохождения опросов и светофор · Месяц {last}")
    st.session_state["attention_names"] = list(risk["intern"])
    status_df = metrics.survey_status(a, last).merge(
        risk[["intern", "level", "score", "why"]], left_on="ID стажёра", right_on="intern", how="right"
    )
    status_df["Статус"] = status_df["level"].map(ZONE_EMOJI)
    status_df["Причины"] = status_df["why"].map(lambda w: "; ".join(w[:2]) if w else "Отклонений нет")
    status_show = status_df[[
        "Статус", "ID стажёра", "Подразделение", "Наставник",
        "Опрос стажёра", "Опрос наставника", "Оценка стажёра", "Оценка наставника",
        "Расхождение (С−Н)", "Балл" if "Балл" in status_df else "score", "Причины",
    ]].rename(columns={"score": "Приоритет"})
    st.dataframe(
        status_show, hide_index=True, width="stretch", key="attention",
        on_select=open_card, selection_mode="single-row",
        column_config={
            "Приоритет": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d", width="small"),
            "Причины": st.column_config.TextColumn(width="large"),
        },
    )
    st.caption("Нажмите на строку, чтобы открыть карточку стажёра с полной динамикой, цитатами и рекомендациями.")

    st.subheader("Кому нужно внимание HR")
    done = db.actions(conn)
    done_now = set(done[done["month"] == last]["intern"])
    att = risk[risk["level"] != "низкий"]
    todo = att[~att["intern"].isin(done_now)]
    if att.empty:
        st.success("Поговорить или присмотреться не нужно ни к кому.")
    elif todo.empty:
        st.success("Все действия на этот месяц отмечены как сделанные.")
    for r in todo.head(7).itertuples():
        act = playbook.action(r.intern, r.mentor, r.codes, r.level, last)
        quote = playbook.best_quote(com[com["intern"] == r.intern], last)
        with st.container(border=True):
            st.markdown(f"{badge(r.level)} **{r.intern}** · {r.dept} · наставник {r.mentor} · {r.score} баллов из 100")
            st.markdown(f"**Почему:** {'; '.join(r.why[:2])}")
            if quote:
                safe_quote = comments.mask(quote["quote"], people_names)
                st.markdown(f"**Цитата** ({quote['who']}, {quote['month']} мес.): «{safe_quote}»")
            st.markdown(f"**Что сделать:** {act['title']}. {act['why']}")
            with st.expander("Готовое сообщение"):
                for whom, text in act["messages"]:
                    st.caption(f"Кому: {whom}")
                    st.code(text, language=None, wrap_lines=True)
            b1, b2, _ = st.columns([1, 1, 5])
            b1.button("Сделано", key=f"done_{r.intern}", on_click=db.add_action,
                      args=(conn, r.intern, last, act["title"]))
            b2.button("Карточка", key=f"card_{r.intern}", on_click=go_to_card, args=(r.intern,))
    if len(todo) > 7:
        st.caption(f"Показаны 7 самых срочных. Ещё {len(todo) - 7} в таблице ниже.")
    if done_now:
        with st.expander(f"Сделано в этом месяце: {len(done_now)}"):
            d = done[done["month"] == last]
            st.dataframe(pd.DataFrame({"Стажёр": d["intern"], "Действие": d["title"], "Когда": d["done_at"]}),
                         hide_index=True, width="stretch")

    ql = metrics.quality(a)
    formal = ql[(ql["month"] == last) & ql["formal"]]
    if len(formal):
        with st.expander(f"Формальные анкеты за {last} мес.: {len(formal)}. По ним нельзя сказать, что всё хорошо"):
            st.caption("Одинаковые оценки, пустой комментарий или заполнение за секунды. "
                       "Это не тревога, а пробел в данных: с этими стажёрами стоит коротко поговорить лично.")
            st.dataframe(pd.DataFrame({"Стажёр": formal["intern"], "Что не так": formal["notes"].map(", ".join)}),
                         hide_index=True, width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("##### Динамика по месяцам")
        st.caption("Показывает, как меняются оценки стажёров и наставников; каждая линия усредняет ответы за месяц.")
        g = mon.groupby("month")[["s_avg", "m_avg"]].mean().reindex(range(1, last + 1))
        fig = go.Figure()
        fig.add_scatter(x=g.index, y=g["s_avg"], name="Стажёры о стажировке", mode="lines+markers",
                        line=dict(color=BLUE, width=2), marker=dict(size=8))
        fig.add_scatter(x=g.index, y=g["m_avg"], name="Наставники о стажёрах", mode="lines+markers",
                        line=dict(color=ORANGE, width=2), marker=dict(size=8))
        fig.update_traces(hovertemplate="%{x} мес.: %{y:.2f}")
        fig.update_xaxes(title="месяц стажировки", dtick=1)
        fig.update_yaxes(range=[1, 5.1], title="средняя оценка")
        st.plotly_chart(style(fig), width="stretch")
    with right:
        st.markdown(f"##### Оценки стажёров по вопросам, {last} мес.")
        st.caption("Помогает увидеть, какой именно аспект стажировки просел; число в скобках — изменение к прошлому месяцу.")
        q = a[(a["role"] == "intern") & (a["avg"] == 1)]
        now_q = q[q["month"] == last].groupby("short")["score"].mean().sort_values(ascending=False)
        was_q = q[q["month"] == last - 1].groupby("short")["score"].mean()
        labels = [f"{v:.1f} ({v - was_q[i]:+.1f})" if i in was_q else f"{v:.1f}" for i, v in now_q.items()]
        fig = go.Figure(go.Bar(x=now_q.values, y=now_q.index, orientation="h", marker_color=BLUE,
                               text=labels, textposition="outside", hovertemplate="%{y}: %{x:.2f}<extra></extra>"))
        fig.update_xaxes(range=[0, 6], title="средняя оценка, в скобках изменение к прошлому месяцу")
        st.plotly_chart(style(fig), width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("##### Сигналы в комментариях")
        st.caption("Число стажёров с таким сигналом в комментариях за два последних месяца; это подсказка для проверки, не диагноз.")
        recent = com[com["month"] >= last - 1].explode("signals").dropna(subset=["signals"])
        if recent.empty:
            st.info("Тревожных сигналов в комментариях за два месяца нет.")
        else:
            cnt = recent.groupby("signals")["intern"].nunique().sort_values()
            fig = go.Figure(go.Bar(x=cnt.values, y=cnt.index, orientation="h", marker_color=BLUE,
                                   text=cnt.values, textposition="outside",
                                   hovertemplate="%{y}: %{x} чел.<extra></extra>"))
            fig.update_xaxes(title="сколько стажёров с таким сигналом за последние 2 месяца", dtick=1,
                             range=[0, cnt.max() + 0.6])
            st.plotly_chart(style(fig, 300), width="stretch")
    with right:
        m_df = metrics.mentors(a, mon)
        if m_df["хватает времени"].notna().any():
            st.markdown("##### Нагрузка наставников")
            st.dataframe(m_df.round(1), hide_index=True, width="stretch", height=300)
            st.caption("Число стажёров и обе стороны оценки помощи.")
        else:
            st.markdown(f"##### Стажёр vs наставник · Месяц {last}")
            cmp = mon[mon["month"] == last][["intern", "s_avg", "m_avg"]].dropna(how="all").sort_values("intern")
            fig = go.Figure()
            fig.add_bar(x=cmp["intern"], y=cmp["s_avg"], name="Стажёр", marker_color=BLUE)
            fig.add_bar(x=cmp["intern"], y=cmp["m_avg"], name="Наставник", marker_color=ORANGE)
            fig.update_layout(barmode="group")
            fig.update_yaxes(range=[0, 5.2], title="средняя оценка")
            st.plotly_chart(style(fig, 300), width="stretch")
            st.caption("Прямое сравнение средних оценок стажёра и наставника в выбранном периоде.")

    st.subheader("Динамика оценок по стажёрам (по месяцам)")
    table = mon.pivot(index="intern", columns="month", values="s_avg").reindex(index=risk["intern"], columns=range(1, last + 1))
    st.markdown(render_score_table(table), unsafe_allow_html=True)
    st.caption("Зелёный: 4.0–5.0 · Жёлтый: 3.0–3.9 · Красный: ниже 3.0 · «—»: нет ответа за месяц.")


# ---------- карточка стажёра ----------
def page_intern():
    a, mon, com, risk = data
    all_answers = data[0]
    people_names = set(all_answers["intern"].dropna().astype(str)) | set(all_answers["mentor"].dropna().astype(str))
    names = list(risk["intern"])
    if st.session_state.get("intern") not in names:
        st.session_state["intern"] = names[0]
    lv = dict(zip(risk["intern"], risk["level"]))
    name = st.selectbox("Стажёр", names, key="intern", format_func=lambda n: f"{n} · {ZONE[lv[n]].lower()}")
    r = risk[risk["intern"] == name].iloc[0]
    last = int(selected_month) if selected_month is not None else int(mon["month"].max())
    m = mon[(mon["intern"] == name) & (mon["month"] <= last)].sort_values("month")
    c = com[(com["intern"] == name) & (com["month"] <= last)]
    timeline = m.set_index("month").reindex(range(1, last + 1))
    answers = a[(a["intern"] == name) & (a["month"] <= last) & a["kind"].ne("time")]

    st.title(name)
    st.markdown(f"{badge(r['level'])} {r['dept']} · наставник {r['mentor']}")
    st.caption(f"Показатели за {last}-й месяц. Изменение видно, если у роли есть оценки за оба месяца.")
    k = st.columns(4)
    k[0].metric("Балл", f"{r['score']} из 100",
                help="Сумма объяснимых правил; зона зависит также от числа независимых источников сигналов.")
    s = m.dropna(subset=["s_avg"])
    mm = m.dropna(subset=["m_avg"])
    missing = []
    for column, role, label, key in [
        (k[1], "intern", "Оценка стажёра", "s_avg"),
        (k[2], "mentor", "Оценка наставника", "m_avg"),
    ]:
        received = set(answers.loc[answers["role"] == role, "month"])
        value = timeline.at[last, key]
        shown = "Нет оценки" if last in received else "Нет ответа"
        if pd.notna(value):
            shown = f"{value:.1f} / 5"
        column.metric(label, shown, delta(value, timeline.at[last - 1, key]) if last > 1 else None)
        missing.append(", ".join(map(str, sorted(set(timeline.index) - received))) or "нет пропусков")
    answered = answers.loc[answers["role"] == "intern", "month"].nunique()
    k[3].metric("Анкет стажёра", f"{answered} из {last}",
                help="Число месяцев, в которых стажёр дал хотя бы один ответ.")
    st.caption(f"Месяцы без ответа. Стажёр — {missing[0]}. Наставник — {missing[1]}.")

    left, right = st.columns([2, 3])
    with left:
        st.subheader("Из чего сложился балл")
        if r["parts"]:
            st.markdown("\n".join(f"- {t} **(+{p})**" for p, t in r["parts"]))
            total = sum(points for points, _ in r["parts"])
            cap = " В карточке действует предел 100 баллов." if total > 100 else ""
            st.caption(f"Сумма по правилам — {total} баллов.{cap} Источники признаков: {', '.join(r['sources'])}. "
                       "Таблица правил есть на странице «Обзор».")
            if r["score"] >= RED and r["level"] != "высокий":
                st.info(f"Балл высокий, но все признаки из одного источника ({r['sources'][0]}). "
                        "Поэтому «присмотреться», а не разговор на этой неделе.")
        else:
            st.success("Тревожных признаков нет.")

        evidence = playbook.best_quote(c, last)
        if evidence:
            quote = comments.mask(evidence["quote"], people_names)
            signals = ", ".join(evidence["signals"])
            st.markdown(f"**Цитата** ({evidence['who']}, {evidence['month']} мес., {signals}) «{quote}»")
            with st.expander("Исходный комментарий"):
                st.write(comments.mask(evidence["text"], people_names))

        st.subheader("Что сделать")
        act = playbook.action(name, r["mentor"], r["codes"], r["level"], last)
        if act:
            st.markdown(f"**{act['title']}.** {act['why']}")
            with st.expander("Готовое сообщение"):
                for whom, text in act["messages"]:
                    st.caption(f"Кому: {whom}")
                    st.code(text, language=None, wrap_lines=True)
        else:
            st.write("Отдельных действий не нужно, достаточно обычного контакта раз в месяц.")
        hist = db.actions(conn)
        hist = hist[hist["intern"] == name]
        if len(hist):
            st.markdown("**Что уже сделано:**")
            st.markdown("\n".join(f"- {x.month} мес.: {x.title} ({x.done_at[:10]})" for x in hist.itertuples()))
        if model:
            if st.button("Сводка от нейросети"):
                facts = [f"Подразделение: {r['dept']}. Идёт {last}-й месяц из 6."]
                facts.append("Оценка стажёра по месяцам: " + ", ".join(f"{int(x.month)}: {x.s_avg:.1f}" for x in s.itertuples()))
                facts.append("Оценка наставника по месяцам: " + ", ".join(f"{int(x.month)}: {x.m_avg:.1f}" for x in mm.itertuples()))
                facts.append("Почему нужен разговор: " + ("; ".join(r["why"]) or "нет"))
                quotes = [f"{'стажёр' if x.role == 'intern' else 'наставник'}, {x.month} мес.: {x.text}"
                          for x in c.itertuples() if x.signals]
                facts.append("Комментарии с сигналами: " + (" | ".join(quotes) or "нет"))
                people = list(risk["intern"]) + list(risk["mentor"])
                with st.spinner("Нейросеть пишет сводку"):
                    try:
                        st.info(comments.hr_summary(comments.mask("\n".join(facts), people)))
                    except Exception as e:
                        st.warning(f"Нейросеть не ответила: {e}")
        else:
            st.caption("Подключите нейросеть в файле .env, и здесь появится короткая сводка с советом для HR.")
    with right:
        st.subheader("Стажёр и наставник по месяцам")
        st.caption("Две линии показывают динамику и расхождение взглядов. Пробел означает отсутствие средней оценки.")
        fig = go.Figure()
        fig.add_scatter(x=list(timeline.index), y=timeline["s_avg"].tolist(), name="Стажёр о стажировке", mode="lines+markers",
                        line=dict(color=BLUE, width=2), marker=dict(size=8))
        fig.add_scatter(x=list(timeline.index), y=timeline["m_avg"].tolist(), name="Наставник о стажёре", mode="lines+markers",
                        line=dict(color=ORANGE, width=2), marker=dict(size=8))
        fig.update_traces(hovertemplate="%{x} мес.: %{y:.2f}")
        fig.update_xaxes(title="месяц стажировки", dtick=1, range=[0.8, last + 0.2])
        fig.update_yaxes(range=[1, 5.1], title="средняя оценка")
        st.plotly_chart(style(fig, 280), width="stretch")

        pg = metrics.paired_gaps(answers, name, last)
        big_pg = pg[pg["Разница"].abs() >= 1.5]
        for pr in big_pg.itertuples():
            st.warning(f"Расхождение по блоку «{pr.Аспект}» в {last}-м месяце: стажёр {pr.Стажёр:.1f} vs наставник {pr.Наставник:.1f} ({pr.Разница:+.1f}).")

    sc = a[(a["intern"] == name) & (a["month"] <= last) & (a["kind"] == "scale")]
    t_intern = sc[sc["role"] == "intern"].pivot_table(index="short", columns="month", values="score")
    t_mentor = sc[sc["role"] == "mentor"].pivot_table(index="short", columns="month", values="score")
    if not t_intern.empty and not t_mentor.empty:
        left, right = st.columns(2)
        with left:
            st.subheader("Оценки стажёра по месяцам")
            st.markdown(render_score_table(t_intern.reindex(columns=range(1, last + 1))), unsafe_allow_html=True)
        with right:
            st.subheader("Оценки наставника по месяцам")
            st.markdown(render_score_table(t_mentor.reindex(columns=range(1, last + 1))), unsafe_allow_html=True)
    elif not t_intern.empty:
        st.subheader("Оценки стажёра по месяцам")
        st.markdown(render_score_table(t_intern.reindex(columns=range(1, last + 1))), unsafe_allow_html=True)
        st.caption("Ответы наставника за этот период пока не поступали.")
    elif not t_mentor.empty:
        st.subheader("Оценки наставника по месяцам")
        st.markdown(render_score_table(t_mentor.reindex(columns=range(1, last + 1))), unsafe_allow_html=True)
        st.caption("Ответы стажёра за этот период пока не поступали.")

    c = c[c["text"].notna() & c["text"].ne("")].sort_values(["month", "role"], ascending=[False, True])
    if not c.empty:
        st.subheader("Комментарии")
        st.caption("Имена других людей скрыты. Цитата совпадает с показанным текстом комментария.")
        for x in c.itertuples():
            who = "Стажёр" if x.role == "intern" else "Наставник"
            shown_text = comments.mask(x.text, people_names)
            shown_quote = comments.mask(x.quote, people_names)
            with st.container(border=True):
                st.markdown(f"**{x.month} мес. · {who} · {x.short}**")
                st.write(shown_text)
                if x.signals:
                    tags = " ".join(f":red-background[{s}]" for s in x.signals)
                    st.markdown(tags + (f"  \nЦитата: «{shown_quote}»" if shown_quote else ""))
                st.caption(f"тон {x.sentiment:+.1f} · разобрал: {x.source}" if pd.notna(x.sentiment) else "ещё не разобран")


# ---------- эффект ----------
def rub(x):
    return f"{x:,.0f} ₽".replace(",", " ")


def page_effect():
    a, mon, com, risk = data
    last = int(mon["month"].max())

    st.markdown(
        '<div class="mgts-bar"><div style="display:flex;align-items:center;">'
        '<div class="mgts-sq">МГТС</div>'
        '<div><div style="font-weight:700;font-size:18px;">Калькулятор окупаемости решения</div>'
        '<div style="font-size:12.5px;opacity:0.85;">Подставьте реальные ставки компании — расчёт пересчитается автоматически</div></div></div></div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([2, 3])
    with left:
        st.subheader("Параметры потока")
        pay = st.number_input("Выплата стажёру в месяц, ₽", 0, 500000, 45000, step=5000, key="e_pay")
        months = st.number_input("На каком месяце обычно уходит стажёр", 1, 6, 4, key="e_months")
        hours = st.number_input("Часов наставника в неделю на стажёра", 0, 40, 4, key="e_hours")
        rate = st.number_input("Стоимость часа наставника, ₽", 0, 20000, 1500, step=100, key="e_rate")
        rehire = st.number_input("Стоимость повторного подбора, ₽", 0, 1000000, 60000, step=5000, key="e_rehire")
        kept_n = st.slider("Сколько стажёров помог удержать дашборд за поток", 1, 10, 1, key="e_kept")
        server = st.number_input("Сервер и ИИ-модель в месяц, ₽", 0, 1000000, 4000, step=500, key="e_server")

    parts, loss = effect.loss_per_intern(pay, months, hours, rate, rehire)
    texts = com[com["text"].str.len() > 0]
    scale = 6 / max(1, last)
    ai = effect.ai_cost(len(texts) * scale, texts["text"].str.len().sum() * scale, 0.8)
    total_cost = server * 6 + ai
    saved = kept_n * loss
    ratio = saved / total_cost if total_cost else None

    with right:
        st.subheader("Экономика на один 6-месячный поток")
        k = st.columns(3)
        k[0].metric("Потеря на 1 ушедшем", rub(loss))
        k[1].metric("Сохранено за поток", rub(saved))
        k[2].metric("Затраты за 6 мес.", rub(total_cost))
        ratio_txt = f" — это окупаемость примерно **{ratio:.0f}×**" if ratio and ratio >= 1 else ""
        st.success(
            f"Если вовремя заметить риск и удержать **{kept_n} стажёра**, компания сохраняет **{rub(saved)}** "
            f"при расходах **{rub(total_cost)}** за весь полугодовой цикл{ratio_txt}."
        )
        st.markdown("##### Из чего складывается потеря при уходе 1 стажёра")
        st.dataframe(pd.DataFrame({"Статья": list(parts), "Сумма": [rub(v) for v in parts.values()]}),
                     hide_index=True, width="stretch")
        st.caption("Стартовые значения — ориентировочные. Все суммы пересчитываются под реальные ставки МГТС.")


# ---------- пробная анкета ----------
def go_to_card(name):
    st.session_state["intern"] = name
    st.session_state["page"] = "Стажёр"


def page_form():
    st.title("Пробная анкета")
    st.caption("Форма для проверки: пройдите анкету сами и посмотрите, что покажет дашборд. "
               "В работе ответы приходят из внешнего сервиса анкет, вопросы те же.")
    q = ingest.load_questions()
    col = dict(zip(q["id"], q["column"]))
    role = st.radio("Кто заполняет", ["intern", "mentor"], horizontal=True, key="f_role",
                    format_func=lambda r: "Стажёр" if r == "intern" else "Наставник")
    st.session_state.setdefault("f_start", time.time())  # засекаем время заполнения

    with st.form("anketa"):
        c = st.columns(4)
        name = c[0].text_input(col["intern"], "СТ-006", key="f_name")
        dept = c[1].text_input(col["dept"], "IT", key="f_dept")
        mentor = c[2].text_input(col["mentor"], "Н-005", key="f_mentor")
        month = c[3].number_input(col["month"], 1, 6, int(data[1]["month"].max()) if data else 1, key="f_month",
                                  help="Выберите контрольный период (1–6)")
        answers = {}
        for r in q[q["role"] == role].itertuples():
            if r.kind == "scale":
                answers[r.column] = st.radio(r.column, list(range(int(r.min), int(r.max) + 1)), index=None,
                                             horizontal=True, key=f"f_{r.id}",
                                             help=f"{int(r.min)} совсем не согласен, {int(r.max)} полностью согласен")
            elif r.kind == "nps":
                answers[r.column] = st.radio(r.column, list(range(11)), index=None, horizontal=True, key=f"f_{r.id}")
            else:
                answers[r.column] = st.text_area(r.column, key=f"f_{r.id}", height=80)
        sent = st.form_submit_button("Отправить", type="primary")

    if not sent:
        return
    if not name.strip() or any(v is None for v in answers.values()):
        st.error("Ответьте на все вопросы со шкалой и укажите ФИО.")
        return
    seconds = round(time.time() - st.session_state.pop("f_start"))
    row = {col["intern"]: name.strip(), col["dept"]: dept, col["mentor"]: mentor, col["month"]: month,
           col["ts"]: time.strftime("%Y-%m-%d %H:%M:%S"), col["sec"]: seconds, **answers}
    rows, _ = ingest.to_rows(pd.DataFrame([row]), role)
    try:
        ingest.save(conn, rows)
    except ValueError as e:
        st.error(str(e))
        return
    comments.run(conn)

    a, mon, com, risk = load_all()
    person = ingest.clean_name(name)
    r = risk[risk["intern"] == person].iloc[0]
    st.success(f"Анкета сохранена. Заполнение заняло {seconds} сек.")
    st.markdown(badge(r["level"]))
    k = st.columns(2)
    k[0].metric("Балл", f"{r['score']} из 100")
    k[1].metric("Время заполнения", f"{seconds} сек")
    st.markdown("**Что увидел дашборд:**")
    st.markdown("\n".join(f"- {w}" for w in r["why"]) if r["why"] else "- тревожных признаков нет")
    mine = com[(com["intern"] == person) & (com["month"] == month) & (com["role"] == role)
               & com["text"].notna() & com["text"].ne("")]
    for x in mine.itertuples():
        tags = ", ".join(x.signals) if x.signals else "сигналов нет"
        st.markdown(f"- комментарий «{x.text}»: тон {x.sentiment:+.1f}, {tags} (разобрал: {x.source})")
    st.button("Открыть карточку стажёра", on_click=go_to_card, args=(person,))


# ---------- данные ----------
def page_data():
    st.title("Данные")
    a = metrics.load(conn)
    n_ai = int(metrics.comments(conn, a)["source"].notna().sum()) if len(a) else 0
    k = st.columns(4)
    k[0].metric("Анкет стажёров", a[a["role"] == "intern"].groupby(["intern", "month"]).ngroups)
    k[1].metric("Анкет наставников", a[a["role"] == "mentor"].groupby(["intern", "month"]).ngroups)
    k[2].metric("Комментариев", int(a["text"].notna().sum()))
    k[3].metric("Из них разобрано", n_ai)

    st.subheader("Ответы из Яндекс Форм")
    st.caption("Форма после каждого заполнения шлёт письмо с ответом. Дашборд проверяет почту раз в минуту сам, "
               "кнопка ниже проверяет сразу.")
    if mail.configured():
        if st.button("Проверить почту сейчас"):
            with st.spinner("Проверяю почту"):
                stats = mail.fetch(conn)
            if stats["ошибки"]:
                st.error(stats["ошибки"][0])
            else:
                st.success(f"Новых писем: {stats['писем']}, ответов загружено: {stats['ответов']}, "
                           f"пропущено: {stats['пропущено']}.")
    else:
        st.info("Почта не подключена. Впишите YANDEX_MAIL и YANDEX_APP_PASSWORD в файл .env и перезапустите дашборд.")

    st.subheader("Загрузить ответы файлом")
    st.caption("Подходит выгрузка из любого сервиса анкет: CSV, XLSX или JSON. Можно дать ссылку на CSV, "
               "например на опубликованную Google Таблицу с ответами формы. Повторная загрузка не создаёт дублей.")
    role = st.radio("Чьи это ответы", ["intern", "mentor"], horizontal=True,
                    format_func=lambda r: "Стажёры" if r == "intern" else "Наставники")
    file = st.file_uploader("Файл с ответами", type=["csv", "xlsx", "json"])
    sheet = 0
    file_ready = False
    if file is not None:
        try:
            if file.name.lower().endswith(".xlsx"):
                with pd.ExcelFile(file) as excel:
                    sheets = excel.sheet_names
                if len(sheets) > 1:
                    sheet = st.selectbox("В файле несколько листов. Какой загрузить?", sheets)
            file.seek(0)
            preview = ingest.read_export(file, sheet)
            file.seek(0)
            preview_stats = {}
            preview_rows, preview_unknown = ingest.to_rows(
                preview, role, stats=preview_stats, require_average=True
            )
            file_ready = True
            st.caption(f"Предварительная проверка без записи в базу: {len(preview)} строк, "
                       f"{len(preview_rows)} ответов распознано.")
            if preview_unknown:
                st.warning("Неузнанные колонки: " + ", ".join(map(str, preview_unknown)))
            dropped = sum(preview_stats.values())
            if dropped:
                st.info("При загрузке некорректные данные будут пропущены: "
                        f"{preview_stats['строк без ФИО или месяца']} строк без ФИО/месяца, "
                        f"{preview_stats['строк с месяцем вне диапазона 1–6']} строк с месяцем вне 1–6, "
                        f"{preview_stats['ответов с неверным значением']} нечисловых ответов, "
                        f"{preview_stats['ответов вне шкалы']} оценок за пределами шкалы.")
        except Exception as e:
            file.seek(0)
            st.warning(f"Предварительная проверка не пройдена: {e}")
    url = st.text_input("или ссылка на CSV")
    if st.button("Загрузить", type="primary", disabled=not (file_ready if file is not None else url)):
        try:
            if file is not None:
                file.seek(0)
            res = ingest.ingest(conn, file or url, role, sheet)
            stats = comments.run(conn)
            st.success(f"Загружено анкет: {res['анкет принято']}, ответов: {res['ответов']}. "
                       f"Строк в источнике: {res['анкет']}. "
                       f"Комментариев разобрано: {stats['всего']} (нейросеть {stats['нейросеть']}, словарь {stats['словарь']}).")
            if res["нераспознанные колонки"]:
                st.warning("Эти колонки не узнал и пропустил. Если они нужны, добавьте их в файл сопоставления: "
                           + ", ".join(res["нераспознанные колонки"]))
            if any(res[key] for key in ["строк без ФИО или месяца", "ответов с неверным значением",
                                        "ответов вне шкалы", "строк с месяцем вне диапазона 1–6"]):
                st.warning("При импорте были пропуски или исправления: "
                           f"строк без ФИО/месяца — {res['строк без ФИО или месяца']}, "
                           f"месяцев вне 1–6 — {res['строк с месяцем вне диапазона 1–6']}, "
                           f"нечисловых ответов — {res['ответов с неверным значением']}, "
                           f"оценок вне шкалы — {res['ответов вне шкалы']}.")
            for err in stats["ошибки"][:1]:
                st.warning(f"Нейросеть не ответила, сработал словарь. Ошибка: {err}")
        except Exception as e:
            st.error(f"Не получилось загрузить: {e}")

    st.subheader("Служебное")
    b = st.columns(3)
    if b[0].button("Загрузить демо-данные"):
        stats = load_demo()
        st.success(f"Демо-данные загружены. Комментариев разобрано: {stats['всего']}.")
    if b[1].button("Разобрать комментарии заново"):
        conn.execute("delete from comment_ai")
        bar = st.progress(0.0)
        stats = comments.run(conn, progress=bar.progress)
        st.success(f"Готово: нейросеть {stats['нейросеть']}, словарь {stats['словарь']}.")
        for err in stats["ошибки"][:1]:
            st.warning(f"Ошибка нейросети: {err}")
    if b[2].button("Очистить базу"):
        db.clear(conn)
        st.success("База пустая.")

    with st.expander("Какие вопросы знает дашборд"):
        q = ingest.load_questions()[["column", "role", "kind", "block", "min", "max", "reverse", "avg", "short"]]
        st.dataframe(q, hide_index=True, width="stretch")

    with st.expander("Методика расчёта баллов и светофора"):
        st.markdown(f"""
Балл (0–100) — сумма открытых правил. **🟢 0–24** всё хорошо · **🟡 {YELLOW}–{RED - 1}** зона внимания · **🔴 {RED}–100** критичный сигнал (требуется совпадение ≥2 источников: оценки, текст, поведение; прямой сигнал об уходе поднимает 🔴 сразу).

| Признак | Баллы |
|---|---|
| В комментарии есть намерение уйти | +50 |
| Средняя оценка ниже 3.0 (ниже 3.5) | +30 (+15) |
| Падение на ≥0.8 к прошлым месяцам (≥0.5) | +25 (+12) |
| Пропущена анкета за контрольный период | +20 |
| Средняя наставника ниже 3.0 | +20 |
| Расхождение стажёра и наставника (общее ≥1.2 или по блоку ≥1.5) | +15 |
| Оценки 1–2 по отдельным вопросам (2 мес. подряд) | +15 (+10) |
| Спад 3 месяца подряд / низко 2 месяца подряд | +15 |
| Сигналы в комментариях (перегруз, нет поддержки и др.) | +10 (макс. 20) |
| Негативный тон комментариев | +10 |
| Формальная анкета (отписка) / резкое сжатие комментариев | +8 / +6 |
""")


if page == "Данные":
    page_data()
elif page == "Анкета":
    page_form()
elif data is None:
    st.title("Данных пока нет")
    if st.session_state.get("stale"):
        st.warning("В базе лежат ответы от другой анкеты: их вопросов нет в текущем файле сопоставления. "
                   "Очистите базу в разделе «Данные» и загрузите ответы заново.")
    st.write("Загрузите выгрузку опросов в разделе «Данные» или начните с демо-набора.")
    if st.button("Загрузить демо-данные", type="primary"):
        load_demo()
        st.rerun()
elif page == "Обзор":
    page_overview()
elif page == "Эффект":
    page_effect()
else:
    page_intern()
