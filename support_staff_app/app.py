import streamlit as st
import datetime
import os
import pandas as pd
from openai import OpenAI
import sys

# .env ファイルから環境変数を読み込み（あれば）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from support_staff_app import db_utils, calendar_utils, whisper_utils
from support_staff_app import scenarios as rp_scenarios
from support_staff_app import company_rules
from support_staff_app import notebooklm_helper
from support_staff_app import models

# Initialize database (creates tables + demo data if not exists)
models.init_db()
models.seed_data()

# Page Config
st.set_page_config(page_title="支援員成長プラットフォーム", layout="wide")

# --- Authentication ---
def check_password():
    """Returns `True` if the user had a correct password."""
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user_info"] = None
        st.session_state["selected_office_id"] = None
        st.session_state["login_role"] = None

    if st.session_state["logged_in"]:
        return True

    st.title("ログイン")
    offices_df = db_utils.get_offices()

    # Role selection
    login_role = st.radio("ログイン種別", ["👷 支援員", "👔 管理者", "🎓 利用者"], horizontal=True, key="login_role_radio")

    col1, col2 = st.columns([1, 2])
    with col1:
        if login_role == "🎓 利用者":
            # --- Client Login ---
            with st.form("client_login_form"):
                st.markdown("### 🎓 利用者ログイン")
                if not offices_df.empty:
                    cl_office_options = [(row['id'], f"📍 {row['name']}") for _, row in offices_df.iterrows()]
                    cl_office = st.selectbox("事業所を選択", options=[o[0] for o in cl_office_options],
                                             format_func=lambda x: dict(cl_office_options).get(x, ''), key="cl_login_office")
                else:
                    cl_office = None

                client_list = db_utils.get_clients_for_login(cl_office)
                if client_list.empty:
                    st.warning("この事業所に利用者が登録されていません")
                    st.form_submit_button("ログイン", disabled=True)
                else:
                    cl_id = st.selectbox("利用者名", client_list['id'],
                                         format_func=lambda x: client_list[client_list['id'] == x]['name'].values[0])
                    cl_pin = st.text_input("PIN", type="password", max_chars=6)
                    cl_submitted = st.form_submit_button("ログイン")
                    if cl_submitted:
                        cl_user = db_utils.get_client_by_id(cl_id)
                        if cl_user is not None:
                            pin = str(cl_user.get('login_pin', '1234'))
                            if cl_pin.strip() == pin:
                                st.session_state["logged_in"] = True
                                st.session_state["user_info"] = {'id': cl_user['id'], 'name': cl_user['name'], 'role': 'client', 'office_id': cl_user.get('office_id')}
                                st.session_state["selected_office_id"] = cl_user.get('office_id')
                                st.session_state["login_role"] = "client"
                                st.session_state["client_id"] = cl_user['id']
                                st.success("ログイン成功 (利用者)")
                                st.rerun()
                            else:
                                st.error("PINが間違っています。")
            st.info("Demo: PIN = 1234")
        else:
            # --- Staff / Manager Login ---
            with st.form("login_form"):
                st.markdown("### ユーザー認証")
                if login_role == "👔 管理者":
                    selected_office = "all"
                    st.info("管理者: 全事業所にアクセス可能")
                else:
                    if not offices_df.empty:
                        office_options = [(row['id'], f"📍 {row['name']}") for _, row in offices_df.iterrows()]
                        selected_office = st.selectbox("事業所を選択", options=[o[0] for o in office_options],
                                                       format_func=lambda x: dict(office_options).get(x, ''), key="login_office")
                    else:
                        selected_office = "all"
                        st.info("事業所が未登録です")

                if selected_office == "all":
                    staff_list = db_utils.get_staff_list()
                else:
                    staff_list = db_utils.get_staff_list(office_id=selected_office)

                if staff_list.empty:
                    st.warning("この事業所にスタッフが登録されていません")
                    st.form_submit_button("ログイン", disabled=True)
                else:
                    user_id = st.selectbox("ユーザー名", staff_list['id'],
                                           format_func=lambda x: staff_list[staff_list['id'] == x]['name'].values[0])
                    password = st.text_input("パスワード", type="password")
                    submitted = st.form_submit_button("ログイン")
                    if submitted:
                        user = staff_list[staff_list['id'] == user_id].iloc[0]
                        password = password.strip()
                        if user['role'] == 'manager' and password == 'admin':
                            st.session_state["logged_in"] = True
                            st.session_state["user_info"] = user
                            st.session_state["selected_office_id"] = None
                            st.session_state["login_role"] = "manager"
                            st.success("ログイン成功 (Manager)")
                            st.rerun()
                        elif user['role'] == 'staff' and password == 'staff':
                            st.session_state["logged_in"] = True
                            st.session_state["user_info"] = user
                            st.session_state["selected_office_id"] = selected_office if selected_office != "all" else None
                            st.session_state["login_role"] = "staff"
                            st.success("ログイン成功 (Staff)")
                            st.rerun()
                        else:
                            st.error("パスワードが間違っています。")
            st.info("Demo: 管理者=admin / スタッフ=staff")
    return False

# --- Staff Dashboard ---
def staff_dashboard(user, client):
    office_id = st.session_state.get("selected_office_id")
    offices_df = db_utils.get_offices()
    office_name = "未設定"
    if office_id and not offices_df.empty:
        match = offices_df[offices_df['id'] == office_id]
        if not match.empty:
            office_name = match.iloc[0]['name']

    st.title(f"マイページ: {user['name']} さん 🚀")
    st.info(f"📍 事業所: {office_name} | 役職: {user['role']}")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
        "📊 事業所KPI", "👥 利用者ステータス", "📅 授業カレンダー", "💬 事業所スレッド",
        "📝 日報・成長ログ", "📚 研修資料", "🗣️ ロープレ", "🌱 1on1",
        "🏢 本部への質問"
    ])

    # ================================================================
    # Tab 1: 事業所 KPI
    # ================================================================
    with tab1:
        st.header("📊 事業所KPI")
        if not office_id:
            st.warning("事業所が未設定です。管理者にお問い合わせください。")
        else:
            import sqlite3 as _sq
            _conn = _sq.connect("employment_support.db")
            kpi_df = pd.read_sql("SELECT * FROM office_kpi WHERE office_name LIKE ?",
                                 _conn, params=[f"%{office_name}%"])
            targets_df = pd.read_sql("""SELECT * FROM monthly_office_targets
                WHERE office_name LIKE ? ORDER BY year DESC, month DESC LIMIT 6""",
                                     _conn, params=[f"%{office_name}%"])
            _conn.close()

            if not kpi_df.empty:
                kpi = kpi_df.iloc[0]
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("📞 問合数", int(kpi.get('inquiries', 0)))
                k2.metric("🤝 面談数", int(kpi.get('interviews', 0)))
                k3.metric("🏢 体験数", int(kpi.get('trials', 0)))
                k4.metric("✅ 入所数", int(kpi.get('enrollments', 0)))

                st.divider()
                r1, r2, r3 = st.columns(3)
                r1.metric("問合→面談率", f"{kpi.get('inquiry_to_interview', 0):.1f}%")
                r2.metric("面談→体験率", f"{kpi.get('interview_to_trial', 0):.1f}%")
                r3.metric("体験→入所率", f"{kpi.get('trial_to_enrollment', 0):.1f}%")
            else:
                st.info("KPIデータがまだ登録されていません。")

            if not targets_df.empty:
                st.divider()
                st.subheader("📈 月次目標 vs 実績")
                display_df = targets_df[['year', 'month', 'target', 'actual', 'gap', 'achievement_rate']].rename(columns={
                    'year': '年', 'month': '月', 'target': '目標', 'actual': '実績',
                    'gap': '差分', 'achievement_rate': '達成率(%)'
                })
                st.dataframe(display_df, use_container_width=True, hide_index=True)

            # Capacity utilization
            st.divider()
            st.subheader("🏠 定員稼働率")
            office_info = offices_df[offices_df['id'] == office_id]
            if not office_info.empty:
                capacity = int(office_info.iloc[0].get('capacity', 20))
                _cn2 = _sq.connect("employment_support.db")
                active_count = _cn2.execute("SELECT COUNT(*) FROM clients WHERE office_id = ? AND usage_status = '利用者'",
                                            (office_id,)).fetchone()[0]
                _cn2.close()
                utilization = (active_count / capacity * 100) if capacity > 0 else 0
                uc1, uc2, uc3 = st.columns(3)
                uc1.metric("定員", capacity)
                uc2.metric("現利用者数", active_count)
                uc3.metric("稼働率", f"{utilization:.1f}%")

    # ================================================================
    # Tab 2: 利用者ステータス
    # ================================================================
    with tab2:
        st.header("👥 利用者ステータス")

        # --- Today's expected clients ---
        st.subheader("🕐 本日の来所予定")
        todays = db_utils.get_todays_expected_clients(office_id)
        if not todays.empty:
            for _, tc in todays.iterrows():
                cols = st.columns([2, 1, 1, 1])
                cols[0].write(f"**{tc['name']}**")
                cols[1].write(f"🎂 {tc.get('age', '?')}歳" if tc.get('age') else "")
                cols[2].write(tc.get('disability_type', ''))
                cols[3].write(f"⏰ {tc.get('clock_in', '—')}")
        else:
            st.info("本日の来所記録はまだありません。")

        st.divider()

        # --- Existing clients status ---
        st.subheader("📋 既存利用者一覧")
        import sqlite3 as _sq3
        if office_id:
            _cn3 = _sq3.connect("employment_support.db")
            clients_df = pd.read_sql("""SELECT id, name, usage_status, age, disability_type, disability_detail,
                planned_months, service_start, service_end, graduation_step
                FROM clients WHERE office_id = ? AND usage_status = '利用者'
                ORDER BY name""", _cn3, params=[office_id])
            _cn3.close()
        else:
            clients_df = pd.DataFrame()

        if not clients_df.empty:
            display = clients_df[['name', 'age', 'disability_type', 'disability_detail', 'planned_months',
                                  'service_start', 'service_end']].rename(columns={
                'name': '氏名', 'age': '年齢', 'disability_type': '障害種別',
                'disability_detail': '特性詳細', 'planned_months': '利用予定月数',
                'service_start': '利用開始', 'service_end': '利用終了'
            })
            st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.info("この事業所に利用者が登録されていません。")

        st.divider()

        # --- Sales Pipeline / Kanban ---
        st.subheader("📊 新規利用者パイプライン（看板管理）")
        _cn4 = _sq3.connect("employment_support.db")
        pipeline_query = "SELECT * FROM user_candidates"
        _params4 = []
        if office_id:
            pipeline_query += " WHERE office_id = ?"
            _params4.append(office_id)
        pipeline_query += " ORDER BY contact_date DESC"
        candidates_df = pd.read_sql(pipeline_query, _cn4, params=_params4)
        _cn4.close()

        pipeline_statuses = ["問い合わせ", "見学", "体験", "受給者証申請", "契約", "通所開始"]
        kanban_cols = st.columns(len(pipeline_statuses))
        for i, status in enumerate(pipeline_statuses):
            with kanban_cols[i]:
                st.markdown(f"**{status}**")
                matches = candidates_df[candidates_df['status'] == status] if not candidates_df.empty else pd.DataFrame()
                st.metric("人数", len(matches))
                for _, c in matches.iterrows():
                    st.markdown(f"📌 {c['name']}")
                    if c.get('source'):
                        st.caption(f"紹介元: {c['source']}")

    # ================================================================
    # Tab 3: 授業カレンダー
    # ================================================================
    with tab3:
        st.header("📅 授業カレンダー")
        if not office_id:
            st.warning("事業所が未設定です。")
        else:
            cal_view = st.radio("表示", ["📅 週間", "📆 月間"], horizontal=True, key="cal_view")

            today = datetime.date.today()
            if cal_view == "📅 週間":
                week_start = today - datetime.timedelta(days=today.weekday())
                week_end = week_start + datetime.timedelta(days=6)
                st.subheader(f"📅 {week_start.strftime('%m/%d')} — {week_end.strftime('%m/%d')}")
                schedule = db_utils.get_class_schedule(office_id, week_start, week_end)
            else:
                month_start = today.replace(day=1)
                import calendar as cal_mod
                _, last_day = cal_mod.monthrange(today.year, today.month)
                month_end = today.replace(day=last_day)
                st.subheader(f"📆 {today.year}年{today.month}月")
                schedule = db_utils.get_class_schedule(office_id, month_start, month_end)

            if not schedule.empty:
                for date_str, group in schedule.groupby('date'):
                    weekday_names = ['月', '火', '水', '木', '金', '土', '日']
                    try:
                        d = datetime.datetime.strptime(str(date_str), '%Y-%m-%d').date()
                        wd = weekday_names[d.weekday()]
                        is_today = d == today
                        marker = " 🔵" if is_today else ""
                        st.markdown(f"### {d.strftime('%m/%d')} ({wd}){marker}")
                    except Exception:
                        st.markdown(f"### {date_str}")
                    for _, cls in group.iterrows():
                        st.write(f"⏰ {cls.get('start_time', '')}〜{cls.get('end_time', '')}  **{cls.get('title', '')}**")
                        if cls.get('instructor'):
                            st.caption(f"講師: {cls['instructor']}")
                        if cls.get('description'):
                            st.caption(cls['description'])
                    st.markdown("---")
            else:
                st.info("スケジュールが登録されていません。")

            # Add new schedule (expander)
            with st.expander("➕ 授業を追加"):
                with st.form("add_class"):
                    cc1, cc2 = st.columns(2)
                    cls_date = cc1.date_input("日付", today, key="cls_date")
                    cls_title = cc2.text_input("授業名", key="cls_title")
                    cc3, cc4 = st.columns(2)
                    cls_start = cc3.text_input("開始時間 (例: 10:00)", key="cls_start")
                    cls_end = cc4.text_input("終了時間 (例: 12:00)", key="cls_end")
                    cls_inst = st.text_input("講師名", key="cls_inst")
                    cls_desc = st.text_area("説明", key="cls_desc", height=80)
                    if st.form_submit_button("追加", type="primary"):
                        if cls_title and cls_start:
                            db_utils.add_class_schedule(office_id, cls_date, cls_start, cls_end, cls_title, cls_desc, cls_inst)
                            st.success("授業を追加しました！")
                            st.rerun()

    # ================================================================
    # Tab 4: 事業所スレッド (Notion風)
    # ================================================================
    with tab4:
        st.header("💬 事業所スレッド")
        if not office_id:
            st.warning("事業所が未設定です。")
        else:
            # --- Slack-style 3-channel layout ---
            CHANNELS = [
                {"key": "client_support", "icon": "👥", "label": "利用者対応に関して",
                 "desc": "利用者さんの対応方法・気づき・相談を共有"},
                {"key": "business_comms", "icon": "📢", "label": "業務連絡に関して",
                 "desc": "シフト・会議・事務連絡など"},
                {"key": "daily_reports", "icon": "📝", "label": "日報提出",
                 "desc": "日々の業務報告・振り返り"},
            ]

            # Session state for active channel
            if "thread_channel" not in st.session_state:
                st.session_state["thread_channel"] = "client_support"

            # Two-column layout: sidebar + main
            ch_sidebar, ch_main = st.columns([1, 3])

            with ch_sidebar:
                st.markdown(f"**📍 {office_name}**")
                st.divider()
                for ch in CHANNELS:
                    is_active = st.session_state["thread_channel"] == ch["key"]
                    btn_type = "primary" if is_active else "secondary"
                    if st.button(
                        f"{ch['icon']} {ch['label']}",
                        key=f"ch_btn_{ch['key']}",
                        use_container_width=True,
                        type=btn_type,
                    ):
                        st.session_state["thread_channel"] = ch["key"]
                        st.rerun()

            with ch_main:
                # Find active channel
                active_ch = next(c for c in CHANNELS if c["key"] == st.session_state["thread_channel"])
                st.subheader(f"{active_ch['icon']} {active_ch['label']}")
                st.caption(active_ch["desc"])

                # --- Post form ---
                with st.expander("✏️ 新しく投稿する", expanded=False):
                    with st.form(f"ch_post_{active_ch['key']}"):
                        if active_ch["key"] == "daily_reports":
                            dr_date = st.date_input("日付", datetime.date.today(), key="ch_dr_date")
                            dr_mood = st.slider("今日の調子", 0, 100, 70, key="ch_dr_mood")
                            dr_tasks = st.multiselect("主な業務", ["利用者面談", "企業訪問", "事務作業", "同行", "会議", "外交", "研修"], key="ch_dr_tasks")
                            dr_content = st.text_area("内容", height=100, key="ch_dr_content", placeholder="今日の振り返りを記録…")
                            post_content = f"【日報 {dr_date}】調子: {dr_mood}/100\n業務: {', '.join(dr_tasks)}\n{dr_content}"
                        else:
                            post_content = st.text_area("内容", height=100, key=f"ch_post_content_{active_ch['key']}",
                                                       placeholder="メッセージを入力…")

                        if st.form_submit_button("📤 投稿", type="primary"):
                            if post_content and post_content.strip():
                                # Create thread automatically with channel name as type
                                tid = db_utils.create_thread(office_id, active_ch["label"], user['id'], active_ch["key"])
                                db_utils.add_thread_post(tid, user['id'], post_content)
                                st.success("投稿しました！")
                                st.rerun()

                st.divider()

                # --- Timeline ---
                threads = db_utils.get_threads(office_id)
                # Filter by channel type
                ch_threads = threads[threads['thread_type'] == active_ch["key"]] if not threads.empty else threads

                if not ch_threads.empty:
                    for _, t in ch_threads.iterrows():
                        posts = db_utils.get_thread_posts(t['id'])
                        if not posts.empty:
                            first_post = posts.iloc[0]
                            with st.container(border=True):
                                st.markdown(f"**{first_post.get('author_name', '匿名')}** · {str(first_post.get('created_at', ''))[:16]}")
                                st.markdown(first_post['content'])

                                # Show reply count
                                reply_count = len(posts) - 1
                                if reply_count > 0:
                                    with st.expander(f"💬 {reply_count}件の返信"):
                                        for _, p in posts.iloc[1:].iterrows():
                                            st.markdown(f"**{p.get('author_name', '匿名')}** · {str(p.get('created_at', ''))[:16]}")
                                            st.text(p['content'])
                                            st.markdown("---")

                                # Reply form
                                reply_key = f"ch_reply_{t['id']}"
                                reply = st.text_input("返信…", key=reply_key, label_visibility="collapsed",
                                                     placeholder="返信を入力…")
                                if reply and reply.strip():
                                    rp_btn = st.button("📤", key=f"ch_rp_btn_{t['id']}")
                                    if rp_btn:
                                        db_utils.add_thread_post(t['id'], user['id'], reply)
                                        st.rerun()
                else:
                    st.info(f"まだ「{active_ch['label']}」の投稿がありません。上の「✏️ 新しく投稿する」から始めましょう！")

    # ================================================================
    # Tab 5: 日報・成長ログ (事業所チャンネル)
    # ================================================================
    with tab5:
        st.header("💬 事業所チャンネル")

        office_options = ["川崎", "横浜", "西船橋", "本厚木", "柏", "三鷹", "関内", "川越"]
        selected_ch_office = st.selectbox("事業所", office_options, key="ch_office")

        msg_type = st.radio("投稿タイプ", ["💬 一般", "📝 日報", "📋 利用者対応記録"], horizontal=True)
        type_map = {"💬 一般": "general", "📝 日報": "daily_report", "📋 利用者対応記録": "client_record"}

        if msg_type == "📝 日報":
            col1, col2 = st.columns(2)
            with col1:
                rp_date = st.date_input("日付", datetime.date.today(), key="ch_date")
                sentiment = st.slider("今日の調子", 0, 100, 70, key="ch_sent")
            with col2:
                work_items = st.multiselect("主な業務", ["利用者面談", "企業訪問", "事務作業", "同行", "会議", "外交"], key="ch_work")
            content = st.text_area("業務内容・気付き・学び", height=120, key="ch_report")
            full_content = f"【日報 {rp_date}】調子:{sentiment}/100\n業務: {', '.join(work_items)}\n{content}"
        elif msg_type == "📋 利用者対応記録":
            client_name = st.text_input("利用者名（イニシャル可）", key="ch_client")
            record_type = st.selectbox("対応種別", ["面談", "電話対応", "同行支援", "企業連絡", "家族対応", "その他"], key="ch_rtype")
            content = st.text_area("対応内容", height=120, key="ch_crec")
            full_content = f"【{record_type}】{client_name}さん\n{content}"
        else:
            full_content = st.text_area("メッセージ", height=80, key="ch_general")

        if st.button("📤 投稿", type="primary"):
            if full_content.strip():
                db_utils.post_channel_message(selected_ch_office, user['id'], user['name'], type_map[msg_type], full_content)
                if msg_type == "📝 日報":
                    db_utils.add_daily_report(user['id'], rp_date, sentiment, content, "特になし")
                st.success("投稿しました！")
                st.rerun()

        st.divider()
        st.subheader("📜 タイムライン")
        msgs = db_utils.get_channel_messages(selected_ch_office)
        if not msgs.empty:
            type_icons = {"general": "💬", "daily_report": "📝", "client_record": "📋"}
            for _, m in msgs.iterrows():
                icon = type_icons.get(m['msg_type'], "💬")
                st.markdown(f"**{icon} {m['author_name']}** — {m['created_at']}")
                st.text(m['content'])
                st.markdown("---")
        else:
            st.info("まだ投稿がありません。")

    # ================================================================
    # Tab 6: 研修資料
    # ================================================================
    with tab6:
        st.header("📚 研修資料ライブラリ")
        st.caption("業務に必要な研修資料を確認できます")

        training_category = st.selectbox("カテゴリ選択", [
            "すべて", "🏢 事業所運営", "👥 利用者支援", "🤝 外交・営業",
            "📋 行政・制度", "🧠 障害理解・支援技法"
        ])

        materials = {
            "🏢 事業所運営": [
                {"title": "朝礼・終礼の進め方マニュアル", "desc": "毎日の朝礼・終礼で確認すべき項目と進行手順。", "level": "初級"},
                {"title": "KPI管理と運営数値の見方", "desc": "通所率、定着率、転換率など事業所運営KPIの意味と目標値。", "level": "中級"},
                {"title": "加算の知識（基礎）", "desc": "欠席時対応加算、移行準備体制加算、初期加算等の概要。", "level": "初級"},
                {"title": "knowbe操作マニュアル", "desc": "支援記録入力、実績記録確認、請求書出力。", "level": "初級"},
            ],
            "👥 利用者支援": [
                {"title": "インテーク面談ガイド", "desc": "初回面談の流れ、ヒアリングポイント、アセスメントシート。", "level": "初級"},
                {"title": "個別支援計画の作成方法", "desc": "アセスメント→計画→ケース会議→提示の流れ。", "level": "中級"},
                {"title": "週次面談の進め方", "desc": "定期面談の確認事項、動機づけ面接法の基本。", "level": "初級"},
                {"title": "就労定着支援の基礎", "desc": "就職後の定着支援、企業連携、定着率計算。", "level": "上級"},
            ],
            "🤝 外交・営業": [
                {"title": "ハローワーク訪問マニュアル", "desc": "担当者との関係構築、求人情報収集、連携のポイント。", "level": "初級"},
                {"title": "行政機関への営業ガイド", "desc": "障害福祉課、相談支援事業所へのアプローチ方法。", "level": "中級"},
                {"title": "企業開拓（実習先・就職先）", "desc": "企業研究→アポ→訪問→フォローの流れ。", "level": "上級"},
            ],
            "📋 行政・制度": [
                {"title": "障害福祉サービスの制度概要", "desc": "就労移行支援の法的位置づけ、利用期間、負担額。", "level": "初級"},
                {"title": "受給者証の取得フロー", "desc": "相談支援→計画→申請→決定の流れ。", "level": "初級"},
                {"title": "国保連請求の基礎", "desc": "月次請求の流れ、算定日数、加算の請求方法。", "level": "上級"},
            ],
            "🧠 障害理解・支援技法": [
                {"title": "精神障害の基礎知識", "desc": "うつ、双極性障害、統合失調症、発達障害の特性と配慮。", "level": "初級"},
                {"title": "合理的配慮の考え方", "desc": "障害者差別解消法、配慮の提供義務と具体例。", "level": "中級"},
                {"title": "動機づけ面接法（MI）入門", "desc": "内発的動機づけを引き出す対話技法。", "level": "中級"},
            ],
        }

        for cat, items in materials.items():
            if training_category == "すべて" or training_category == cat:
                st.subheader(cat)
                for m in items:
                    lvl = {"初級": "🟢", "中級": "🟡", "上級": "🔴"}.get(m['level'], "⚪")
                    with st.expander(f"{lvl} {m['title']}  [{m['level']}]"):
                        st.write(m['desc'])
                        st.caption("※詳細はGoogleドライブの研修フォルダをご確認ください")

    # ================================================================
    # Tab 7: ロープレ・ケーススタディ（強化版）
    # ================================================================
    with tab7:
        st.header("🎭 ロープレ練習モード")
        st.caption("AIが相手役を演じ、実践的なロールプレイで支援スキルを磨きます")

        # --- Session state keys ---
        RP_MSGS = "rp_messages"
        RP_SCENARIO = "rp_active_scenario"
        RP_FEEDBACK = "rp_last_feedback"
        RP_ENDED = "rp_session_ended"
        if RP_MSGS not in st.session_state:
            st.session_state[RP_MSGS] = []
        if RP_SCENARIO not in st.session_state:
            st.session_state[RP_SCENARIO] = None
        if RP_ENDED not in st.session_state:
            st.session_state[RP_ENDED] = False

        # --- Scenario Selection Panel ---
        active_scenario = st.session_state[RP_SCENARIO]
        is_in_session = len(st.session_state[RP_MSGS]) > 0

        if not is_in_session:
            # === カテゴリ選択 ===
            sel_cat_label = st.radio(
                "カテゴリ",
                ["🤝 外交活動ロープレ", "👥 利用者獲得ロープレ"],
                horizontal=True,
                key="rp_cat_radio",
            )
            sel_cat = "外交活動" if "外交" in sel_cat_label else "利用者獲得"

            # === 難易度フィルター ===
            diff_cols = st.columns(3)
            difficulties = rp_scenarios.get_difficulties()
            sel_diff = None
            for i, d in enumerate(difficulties):
                icon = rp_scenarios.get_difficulty_icon(d)
                with diff_cols[i]:
                    if st.button(f"{icon} {d}", key=f"rp_diff_{d}", use_container_width=True):
                        st.session_state["rp_sel_difficulty"] = d
            sel_diff = st.session_state.get("rp_sel_difficulty", "初級")

            # === シナリオカード一覧 ===
            filtered = rp_scenarios.get_scenarios_by_difficulty(sel_diff, category=sel_cat)

            st.divider()
            st.subheader(f"{rp_scenarios.get_difficulty_icon(sel_diff)} {sel_diff}レベル — {sel_cat}")

            for sc in filtered:
                with st.container(border=True):
                    sc_col1, sc_col2 = st.columns([3, 1])
                    with sc_col1:
                        st.markdown(f"#### {sc['title']}")
                        st.markdown(f"**相手:** {sc['character_name']} — {sc['character_summary']}")
                        st.caption(sc["situation"])
                    with sc_col2:
                        if st.button("🎬 開始", key=f"rp_start_{sc['id']}", type="primary", use_container_width=True):
                            st.session_state[RP_SCENARIO] = sc
                            st.session_state[RP_MSGS] = [
                                {"role": "system", "content": sc["system_prompt"]},
                                {"role": "assistant", "content": sc["opening_line"]},
                            ]
                            st.session_state[RP_ENDED] = False
                            st.session_state[RP_FEEDBACK] = None
                            st.rerun()

        # --- Active Roleplay Session ---
        else:
            sc = active_scenario
            if sc is None:
                st.warning("シナリオ情報が見つかりません。リセットしてください。")
                if st.button("🔄 リセット"):
                    st.session_state[RP_MSGS] = []
                    st.session_state[RP_SCENARIO] = None
                    st.session_state[RP_ENDED] = False
                    st.rerun()
            else:
                # --- Info bar + Controls ---
                info_col, ctrl_col = st.columns([3, 1])
                with info_col:
                    diff_icon = rp_scenarios.get_difficulty_icon(sc["difficulty"])
                    st.markdown(
                        f"**{diff_icon} {sc['difficulty']}** | 🏷️ {sc['category']} | "
                        f"🎭 {sc['character_name']}（{sc['character_summary']}）"
                    )
                    st.caption(f"📋 {sc['title']}")
                with ctrl_col:
                    if st.button("🔄 リセット", use_container_width=True, key="rp_reset_active"):
                        st.session_state[RP_MSGS] = []
                        st.session_state[RP_SCENARIO] = None
                        st.session_state[RP_ENDED] = False
                        st.session_state[RP_FEEDBACK] = None
                        st.rerun()

                # --- Scenario detail expander ---
                with st.expander("📖 シナリオ詳細・評価基準", expanded=False):
                    st.markdown(f"**状況設定:** {sc['situation']}")
                    st.markdown("**評価基準（各10点）:**")
                    for cr in sc["evaluation_criteria"]:
                        st.markdown(f"- **{cr['name']}**: {cr['description']}")

                st.divider()

                # --- Chat history ---
                chat_container = st.container(height=450)
                with chat_container:
                    for msg in st.session_state[RP_MSGS]:
                        if msg["role"] == "system":
                            continue
                        if msg["role"] == "assistant":
                            with st.chat_message("assistant", avatar="🎭"):
                                st.markdown(msg["content"])
                        else:
                            with st.chat_message("user", avatar="👷"):
                                st.markdown(msg["content"])

                # --- Chat input (only if session not ended) ---
                if not st.session_state[RP_ENDED]:
                    rp_input = st.chat_input("あなたの対応を入力してください…", key="rp_chat_input")
                    if rp_input and client:
                        st.session_state[RP_MSGS].append({"role": "user", "content": rp_input})
                        with chat_container:
                            with st.chat_message("user", avatar="👷"):
                                st.markdown(rp_input)
                            with st.chat_message("assistant", avatar="🎭"):
                                stream = client.chat.completions.create(
                                    model="gpt-4o",
                                    messages=st.session_state[RP_MSGS],
                                    stream=True,
                                )
                                response = st.write_stream(stream)
                        st.session_state[RP_MSGS].append({"role": "assistant", "content": response})
                    elif rp_input and not client:
                        st.warning("サイドバーから OpenAI API Key を入力してください。")

                # --- Feedback & Save (at least 2 user messages) ---
                user_msg_count = sum(1 for m in st.session_state[RP_MSGS] if m["role"] == "user")
                if user_msg_count >= 2:
                    st.divider()
                    fb_col1, fb_col2, fb_col3 = st.columns(3)

                    # End session button
                    with fb_col1:
                        if not st.session_state[RP_ENDED]:
                            if st.button("🏁 ロープレ終了", use_container_width=True, type="secondary"):
                                st.session_state[RP_ENDED] = True
                                st.rerun()

                    # Evaluation button
                    with fb_col2:
                        if st.button("📊 AI評価をもらう", use_container_width=True, type="primary"):
                            if client:
                                eval_prompt = rp_scenarios.build_evaluation_prompt(sc)
                                eval_msgs = st.session_state[RP_MSGS] + [
                                    {"role": "user", "content": eval_prompt}
                                ]
                                with st.spinner("AIが評価を作成中..."):
                                    fb_resp = client.chat.completions.create(
                                        model="gpt-4o", messages=eval_msgs
                                    )
                                    fb_text = fb_resp.choices[0].message.content
                                    st.session_state[RP_FEEDBACK] = fb_text
                                    st.session_state[RP_ENDED] = True
                                    st.rerun()
                            else:
                                st.warning("サイドバーから OpenAI API Key を入力してください。")

                    # Save button
                    with fb_col3:
                        if st.button("💾 記録を保存", use_container_width=True):
                            cat = sc["category"]
                            fb_saved = st.session_state.get(RP_FEEDBACK, "")
                            conv = [m for m in st.session_state[RP_MSGS] if m["role"] != "system"]
                            learning = st.session_state.get("rp_learning_note", "")
                            db_utils.save_roleplay_record(
                                user["id"], user["name"], sc["title"], cat, conv,
                                fb_saved if fb_saved else "", learning,
                            )
                            st.success("✅ ロープレ記録を保存しました！")

                    # Show feedback if available
                    if st.session_state.get(RP_FEEDBACK):
                        st.divider()
                        st.subheader("📊 評価結果")
                        st.markdown(st.session_state[RP_FEEDBACK])

                    # Learning notes
                    st.text_area(
                        "📖 学んだこと・気付きメモ",
                        key="rp_learning_note",
                        placeholder="このロープレで学んだことを記録してください…",
                    )

        # --- Roleplay History ---
        st.divider()
        st.subheader("📚 過去のロープレ記録")
        rp_history = db_utils.get_roleplay_records(user["id"])
        if not rp_history.empty:
            for _, rec in rp_history.iterrows():
                with st.expander(f"🗓 {rec['created_at']} — {rec['scenario']}"):
                    st.write(f"**カテゴリ:** {rec['category']}")
                    if rec.get("learning_notes"):
                        st.info(f"📖 学んだこと: {rec['learning_notes']}")
                    if rec.get("ai_feedback"):
                        st.markdown(f"**AIフィードバック:**")
                        st.markdown(rec["ai_feedback"])
        else:
            st.info("まだロープレ記録がありません。シナリオを選んで練習してみましょう！")

    # ================================================================
    # Tab 8: 1on1 メンタリング
    # ================================================================
    with tab8:
        st.header("🌱 1on1")

        # Top-level: choose between supervisor 1on1 vs client 1on1 vs action mgmt vs AI mentor
        oo_mode = st.radio(
            "モード",
            ["👔 上司との1on1", "🧑‍🦱 利用者さんとの1on1", "✅ アクション管理", "💬 AIメンター"],
            horizontal=True, key="oo_mode_radio"
        )

        # ========================================
        # Supervisor 1on1
        # ========================================
        if oo_mode == "👔 上司との1on1":
            st.subheader("👔 上司との1on1 議事録")

            s_col1, s_col2 = st.columns(2)
            with s_col1:
                oo_date = st.date_input("面談日", datetime.date.today(), key="oo_sup_date")
                staff_list = db_utils.get_staff_list()
                managers = staff_list[staff_list['role'] == 'manager']
                mgr_options = {f"{r['name']}": r['id'] for _, r in managers.iterrows()} if not managers.empty else {"管理者未登録": 0}
                mgr_name = st.selectbox("面談相手（上司）", list(mgr_options.keys()), key="oo_sup_mgr")
            with s_col2:
                next_date = st.date_input("次回1on1予定日", key="oo_sup_next")

            minutes = st.text_area("議事録（話した内容）", height=180, key="oo_sup_min",
                                   placeholder="・相談した内容\n・上司からのフィードバック\n・今後の目標")

            st.markdown("**アクションアイテム（任意）**")
            ac1, ac2 = st.columns(2)
            with ac1:
                action1 = st.text_input("アクション①", key="oo_sup_a1")
                action1_due = st.date_input("期限①", key="oo_sup_a1d")
            with ac2:
                action2 = st.text_input("アクション②", key="oo_sup_a2")
                action2_due = st.date_input("期限②", key="oo_sup_a2d")

            if st.button("💾 議事録を保存", type="primary", key="oo_sup_save"):
                mgr_id = mgr_options.get(mgr_name, 0)
                rec_id = db_utils.save_oneonone_record(
                    mgr_id, mgr_name, user['id'], user['name'],
                    str(oo_date), minutes, str(next_date),
                    meeting_type='supervisor'
                )
                if action1.strip():
                    db_utils.add_oneonone_action(rec_id, user['id'], action1, str(action1_due))
                if action2.strip():
                    db_utils.add_oneonone_action(rec_id, user['id'], action2, str(action2_due))
                st.success("上司との1on1 議事録を保存しました！")
                st.rerun()

            st.divider()
            st.subheader("📜 上司との1on1 履歴")
            sup_history = db_utils.get_oneonone_records(staff_id=user['id'], meeting_type='supervisor')
            if not sup_history.empty:
                for _, rec in sup_history.iterrows():
                    with st.expander(f"🗓 {rec['meeting_date']} — 👔 {rec['manager_name']}"):
                        st.markdown(rec['minutes'])
                        if rec.get('next_meeting_date'):
                            st.caption(f"次回: {rec['next_meeting_date']}")
                        actions = db_utils.get_oneonone_actions(record_id=rec['id'])
                        if not actions.empty:
                            st.markdown("**アクションアイテム:**")
                            for _, a in actions.iterrows():
                                status_icon = "✅" if a['status'] == 'done' else "⬜"
                                st.write(f"{status_icon} {a['action_text']} (期限: {a['due_date']})")
            else:
                st.info("まだ上司との1on1記録がありません。")

        # ========================================
        # Client 1on1
        # ========================================
        elif oo_mode == "🧑‍🦱 利用者さんとの1on1":
            st.subheader("🧑‍🦱 利用者さんとの1on1 議事録")

            c_col1, c_col2 = st.columns(2)
            with c_col1:
                oo_c_date = st.date_input("面談日", datetime.date.today(), key="oo_cli_date")
                # Get clients for this office
                clients_df = db_utils.get_clients(office_id=office_id)
                if not clients_df.empty:
                    cli_options = {f"{r['name']}": r['id'] for _, r in clients_df.iterrows()}
                else:
                    cli_options = {"利用者未登録": 0}
                cli_name = st.selectbox("面談相手（利用者さん）", list(cli_options.keys()), key="oo_cli_name")
            with c_col2:
                oo_c_next = st.date_input("次回面談予定日", key="oo_cli_next")
                oo_c_topic = st.selectbox("面談種別", [
                    "定期面談", "個別相談", "就労準備アセスメント",
                    "目標設定", "振り返り", "その他"
                ], key="oo_cli_topic")

            c_minutes = st.text_area("面談記録", height=180, key="oo_cli_min",
                                     placeholder="・利用者さんの様子\n・話した内容\n・今後のサポート方針")

            st.markdown("**フォローアップ項目（任意）**")
            fc1, fc2 = st.columns(2)
            with fc1:
                c_action1 = st.text_input("フォロー①", key="oo_cli_a1")
                c_action1_due = st.date_input("期限①", key="oo_cli_a1d")
            with fc2:
                c_action2 = st.text_input("フォロー②", key="oo_cli_a2")
                c_action2_due = st.date_input("期限②", key="oo_cli_a2d")

            if st.button("💾 面談記録を保存", type="primary", key="oo_cli_save"):
                cli_id = cli_options.get(cli_name, 0)
                full_minutes = f"【{oo_c_topic}】\n{c_minutes}"
                rec_id = db_utils.save_oneonone_record(
                    0, '', user['id'], user['name'],
                    str(oo_c_date), full_minutes, str(oo_c_next),
                    meeting_type='client', client_id=cli_id, client_name=cli_name
                )
                if c_action1.strip():
                    db_utils.add_oneonone_action(rec_id, user['id'], c_action1, str(c_action1_due))
                if c_action2.strip():
                    db_utils.add_oneonone_action(rec_id, user['id'], c_action2, str(c_action2_due))
                st.success("利用者さんとの面談記録を保存しました！")
                st.rerun()

            st.divider()
            st.subheader("📜 利用者さんとの1on1 履歴")
            cli_history = db_utils.get_oneonone_records(staff_id=user['id'], meeting_type='client')
            if not cli_history.empty:
                for _, rec in cli_history.iterrows():
                    label = rec.get('client_name') or '利用者'
                    with st.expander(f"🗓 {rec['meeting_date']} — 🧑‍🦱 {label}"):
                        st.markdown(rec['minutes'])
                        if rec.get('next_meeting_date'):
                            st.caption(f"次回: {rec['next_meeting_date']}")
                        actions = db_utils.get_oneonone_actions(record_id=rec['id'])
                        if not actions.empty:
                            st.markdown("**フォローアップ:**")
                            for _, a in actions.iterrows():
                                status_icon = "✅" if a['status'] == 'done' else "⬜"
                                st.write(f"{status_icon} {a['action_text']} (期限: {a['due_date']})")
            else:
                st.info("まだ利用者さんとの1on1記録がありません。")

        # ========================================
        # Action Management (shared)
        # ========================================
        elif oo_mode == "✅ アクション管理":
            st.subheader("アクションアイテム管理")
            actions = db_utils.get_oneonone_actions(staff_id=user['id'])
            if not actions.empty:
                pending = actions[actions['status'] == 'pending']
                done = actions[actions['status'] == 'done']

                if not pending.empty:
                    st.markdown("### ⬜ 未完了")
                    for _, a in pending.iterrows():
                        st.write(f"📌 **{a['action_text']}** (期限: {a['due_date']})")
                        comp_note = st.text_input("完了メモ", key=f"comp_{a['id']}")
                        if st.button("✅ 完了にする", key=f"done_{a['id']}"):
                            db_utils.complete_oneonone_action(a['id'], comp_note)
                            st.success("完了しました！")
                            st.rerun()
                        st.markdown("---")

                if not done.empty:
                    st.markdown("### ✅ 完了済み")
                    for _, a in done.iterrows():
                        st.write(f"✅ ~~{a['action_text']}~~ — {a['completion_notes'] or ''}")
            else:
                st.info("アクションアイテムはありません。")

        # ========================================
        # AI Mentor (shared)
        # ========================================
        else:
            st.subheader("AIメンター相談室")
            if "mentor_messages" not in st.session_state:
                st.session_state.mentor_messages = [{"role": "system", "content": "あなたは経験豊富なキャリアカウンセラー兼メンタルコーチです。"}]
                st.session_state.mentor_messages.append({"role": "assistant", "content": "お疲れ様です。今日は何か気になることや、モヤモヤしていることはありますか？"})

            for msg in st.session_state.mentor_messages:
                if msg["role"] != "system":
                    with st.chat_message(msg["role"], avatar="🌱" if msg["role"] == "assistant" else None):
                        st.write(msg["content"])

            mentor_input = st.chat_input("相談内容を入力...", key="mentor_chat")
            if mentor_input and client:
                st.session_state.mentor_messages.append({"role": "user", "content": mentor_input})
                with st.chat_message("user"):
                    st.write(mentor_input)
                with st.chat_message("assistant", avatar="🌱"):
                    stream = client.chat.completions.create(
                        model="gpt-4o",
                        messages=st.session_state.mentor_messages,
                        stream=True,
                    )
                    response = st.write_stream(stream)
                st.session_state.mentor_messages.append({"role": "assistant", "content": response})

    # ================================================================
    # Tab 9: 本部への質問（AI一次対応）
    # ================================================================
    with tab9:
        st.header("🏢 本部への質問")
        st.caption("就業規則・社内制度について、AIアシスタントが一次対応します。深刻な相談は専門窓口をご案内します。")

        # NotebookLM (Gemini) status
        nlm_ok = notebooklm_helper.is_authenticated()
        nlm_status = notebooklm_helper.get_status()

        if nlm_ok and nlm_status["uploaded_files_count"] > 0:
            st.success(
                f"📚 NotebookLM連携中 — {nlm_status['uploaded_files_count']}件の社内資料を元に回答します",
                icon="✅"
            )
        elif nlm_ok:
            st.info("📚 Gemini API接続済み。右の「📎 資料管理」から社内資料をアップロードすると、それを元に回答できます。")
        else:
            st.info("💡 サイドバーから Gemini API Key を入力すると、社内資料を元にAIが回答できます。")

        # --- Session state ---
        HQ_MSGS = "hq_messages"
        if HQ_MSGS not in st.session_state:
            st.session_state[HQ_MSGS] = []

        # --- FAQ Quick Buttons ---
        st.markdown("#### 💡 よくある質問")
        faq_cols = st.columns(4)
        faqs = company_rules.get_faq_suggestions()
        for i, faq in enumerate(faqs):
            with faq_cols[i % 4]:
                if st.button(faq, key=f"hq_faq_{i}", use_container_width=True):
                    st.session_state["hq_pending_question"] = faq

        st.divider()

        # --- Chat UI ---
        hq_col1, hq_col2 = st.columns([3, 1])

        with hq_col2:
            st.markdown("#### 📞 直接相談窓口")
            with st.container(border=True):
                st.markdown("**人事部**: 03-XXXX-XXXX")
                st.markdown("**総務部**: 03-XXXX-XXXX")
                st.markdown("**EAP相談**: 0120-XXX-XXX")
                st.caption("24時間対応・匿名OK")

            # Document upload for NotebookLM/Gemini
            if nlm_ok:
                st.markdown("#### 📎 社内資料管理")
                uploaded_files = st.file_uploader(
                    "資料をアップロード",
                    type=["pdf", "txt", "md", "docx", "csv"],
                    accept_multiple_files=True,
                    key="hq_doc_upload",
                    label_visibility="collapsed",
                )
                if uploaded_files:
                    import tempfile
                    for uf in uploaded_files:
                        # Save temp and upload to Gemini
                        tmp_path = os.path.join(tempfile.gettempdir(), uf.name)
                        with open(tmp_path, "wb") as f:
                            f.write(uf.getbuffer())
                        with st.spinner(f"📤 {uf.name} をアップロード中…"):
                            result = notebooklm_helper.upload_documents([tmp_path])
                            if result:
                                st.success(f"✅ {uf.name}")

                # Show uploaded files count
                if nlm_status["uploaded_files_count"] > 0:
                    with st.expander(f"📂 登録済み資料 ({nlm_status['uploaded_files_count']}件)"):
                        for fname in nlm_status["uploaded_files"]:
                            st.caption(f"📄 {fname}")

            if st.button("🔄 チャットリセット", use_container_width=True):
                st.session_state[HQ_MSGS] = []
                st.session_state.pop("hq_pending_question", None)
                st.rerun()

        with hq_col1:
            # Chat container
            chat_box = st.container(height=420)
            with chat_box:
                if not st.session_state[HQ_MSGS]:
                    st.info("👋 こんにちは！就業規則や社内制度について、何でもお気軽にご質問ください。")

                for msg in st.session_state[HQ_MSGS]:
                    if msg["role"] == "system":
                        continue
                    if msg["role"] == "assistant":
                        with st.chat_message("assistant", avatar="🏢"):
                            st.markdown(msg["content"])
                    else:
                        with st.chat_message("user", avatar="👷"):
                            st.markdown(msg["content"])

            # Chat input
            pending_q = st.session_state.pop("hq_pending_question", None)
            hq_input = st.chat_input("質問を入力してください…", key="hq_chat_input")
            question = pending_q or hq_input

            if question:
                # 1) Escalation check
                needs_escalation, matched_kw, esc_category = company_rules.check_escalation(question)

                # 2) Query NotebookLM for relevant knowledge
                nlm_context = ""
                nlm_result = None
                if nlm_ok:
                    with st.spinner("📚 社内資料を検索中…"):
                        nlm_result = notebooklm_helper.query_notebooklm(question)
                        if nlm_result["success"] and nlm_result["answer"]:
                            nlm_context = nlm_result["answer"]

                # 3) Initialize system prompt (refresh each time with NLM context)
                system_prompt = company_rules.build_system_prompt(notebooklm_context=nlm_context)
                # Update or insert system prompt
                if st.session_state[HQ_MSGS] and st.session_state[HQ_MSGS][0]["role"] == "system":
                    st.session_state[HQ_MSGS][0]["content"] = system_prompt
                else:
                    st.session_state[HQ_MSGS].insert(0, {
                        "role": "system",
                        "content": system_prompt
                    })

                # 4) Add user message
                st.session_state[HQ_MSGS].append({"role": "user", "content": question})

                # 5) Show escalation warning if needed
                if needs_escalation:
                    with chat_box:
                        with st.chat_message("user", avatar="👷"):
                            st.markdown(question)
                        with st.chat_message("assistant", avatar="🚨"):
                            esc_contact = company_rules.ESCALATION_CONTACTS.get(
                                esc_category, "📞 本部: 03-XXXX-XXXX"
                            )
                            escalation_msg = f"""⚠️ **この内容は専門の窓口へのご相談をお勧めします。**

**相談カテゴリ:** {esc_category}

**連絡先:**
{esc_contact}

---
*AIでの回答も行いますが、必ず上記の窓口にもご連絡ください。
あなたのことを大切に思っています。一人で抱え込まないでくださいね。* 🤝"""
                            st.markdown(escalation_msg)
                    st.session_state[HQ_MSGS].append({
                        "role": "assistant", "content": escalation_msg
                    })

                # 6) Get AI response (GPT-4o with NotebookLM knowledge)
                if client:
                    with chat_box:
                        if not needs_escalation:
                            with st.chat_message("user", avatar="👷"):
                                st.markdown(question)
                        with st.chat_message("assistant", avatar="🏢"):
                            # Show NLM source badge if context was used
                            if nlm_context:
                                st.caption("📚 NotebookLM の社内資料を参照して回答しています")
                            stream = client.chat.completions.create(
                                model="gpt-4o",
                                messages=st.session_state[HQ_MSGS],
                                stream=True,
                            )
                            ai_response = st.write_stream(stream)
                    st.session_state[HQ_MSGS].append({
                        "role": "assistant", "content": ai_response
                    })

                    # 7) Save to DB
                    db_utils.save_hq_question(
                        staff_id=user["id"],
                        staff_name=user["name"],
                        office_id=office_id,
                        question=question,
                        ai_answer=ai_response,
                        is_escalated=needs_escalation,
                        escalation_category=esc_category,
                    )
                else:
                    st.warning("サイドバーから OpenAI API Key を入力してください。")

        # --- Question History ---
        st.divider()
        st.subheader("📜 質問履歴")
        hq_history = db_utils.get_hq_questions(staff_id=user["id"])
        if not hq_history.empty:
            for _, rec in hq_history.head(20).iterrows():
                esc_badge = "🚨 エスカレーション" if rec.get("is_escalated") else ""
                with st.expander(f"🗓 {rec['created_at']} — {rec['question'][:50]}… {esc_badge}"):
                    st.markdown(f"**質問:** {rec['question']}")
                    st.markdown(f"**AI回答:** {rec['ai_answer']}")
                    if rec.get("is_escalated"):
                        st.warning(f"エスカレーション: {rec.get('escalation_category', '未分類')}")
        else:
            st.info("まだ質問履歴がありません。")


# --- Manager Dashboard ---
def manager_dashboard(user, client):
    st.title("事業所管理ダッシュボード 🏢")

    # --- Sidebar: Office Filter ---
    offices_df = db_utils.get_offices()
    if not offices_df.empty:
        office_options = [(None, "🌐 全事業所")] + [
            (row['id'], f"📍 {row['name']}") for _, row in offices_df.iterrows()
        ]
        selected = st.sidebar.selectbox(
            "📍 表示事業所",
            options=[o[0] for o in office_options],
            format_func=lambda x: dict(office_options).get(x, "全事業所"),
            key="office_filter"
        )
        st.session_state["selected_office_id"] = selected
    else:
        st.session_state["selected_office_id"] = None

    current_office_id = st.session_state.get("selected_office_id")
    office_label = "全事業所"
    if current_office_id and not offices_df.empty:
        match = offices_df[offices_df['id'] == current_office_id]
        if not match.empty:
            office_label = match.iloc[0]['name']

    st.info(f"ログイン: {user['name']} (Manager) | 📍 {office_label}")

    tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
        "🏢 全事業所", "📋 朝礼・終礼", "📊 営業KPI", "📒 利用者台帳", "🏢 事業所運営",
        "👥 支援員・KPI", "👤 支援員管理", "📑 行政申請",
        "📋 利用実績", "📝 支援記録", "💰 請求・CSV"
    ])

    # --- Tab 0: 全事業所サマリー (NEW) ---
    with tab0:
        st.header("🏢 全事業所サマリー")
        sum_col1, sum_col2 = st.columns(2)
        sum_year = sum_col1.number_input("年", value=datetime.date.today().year, key="sum_y")
        sum_month = sum_col2.number_input("月", value=datetime.date.today().month,
                                          min_value=1, max_value=12, key="sum_m")

        office_summary = db_utils.get_office_summary(int(sum_year), int(sum_month))

        if not office_summary.empty:
            # Metric cards per office
            cols = st.columns(min(3, len(office_summary)))
            for idx, (_, row) in enumerate(office_summary.iterrows()):
                col = cols[idx % 3]
                active = int(row.get('active_clients', 0))
                capacity = int(row.get('capacity', 20))
                rate = round(active / capacity * 100) if capacity > 0 else 0
                attend = int(row.get('attend_count', 0))

                with col:
                    st.markdown(f"### 📍 {row['office_name']}")
                    m1, m2 = st.columns(2)
                    m1.metric("利用者数", f"{active}名 / {capacity}名")
                    m2.metric("稼働率", f"{rate}%")
                    st.metric("通所延べ日数", f"{attend}日")

                    if st.button(f"{row['office_name']}を詳しく見る →", key=f"goto_{row['office_id']}"):
                        st.session_state["selected_office_id"] = int(row['office_id'])
                        st.rerun()
                    st.divider()

            # All-office summary table
            st.subheader("📊 一覧テーブル")
            display_df = office_summary[['office_name', 'active_clients', 'capacity', 'attend_count']].copy()
            display_df.columns = ['事業所', '利用者数', '定員', '通所延べ日数']
            display_df['稼働率'] = display_df.apply(
                lambda r: f"{round(r['利用者数'] / r['定員'] * 100)}%" if r['定員'] > 0 else "0%", axis=1
            )
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info("事業所データがありません。")

    # --- Tab 2: Sales KPI Dashboard ---
    with tab2:
        st.header("事業所別 営業KPI ダッシュボード")
        st.caption("直近120日間（INDEED除く）")
        
        kpi_df = db_utils.get_office_kpi()
        
        if not kpi_df.empty:
            # Target rates
            targets = {
                '問合→面談': 60.0, '面談→体験': 75.0, '体験→入所': 40.0,
                '問合→入所': 18.0, '面談→入所': 30.0
            }
            
            st.subheader("🎯 目標レート")
            tc1, tc2, tc3, tc4, tc5 = st.columns(5)
            tc1.metric("問合→面談", "60%")
            tc2.metric("面談→体験", "75%")
            tc3.metric("体験→入所", "40%")
            tc4.metric("問合→入所率", "18%")
            tc5.metric("面談→入所率", "30%")
            
            # Overall summary
            total = kpi_df[kpi_df['office_name'] == '全体'].iloc[0]
            st.divider()
            st.subheader("📈 全体サマリー")
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("問合数", f"{int(total['inquiries'])}件")
            sc2.metric("面談数", f"{int(total['interviews'])}件")
            sc3.metric("体験数", f"{int(total['trials'])}件")
            sc4.metric("入所数", f"{int(total['enrollments'])}件")
            
            # Conversion rates with delta
            cc1, cc2, cc3, cc4, cc5 = st.columns(5)
            cc1.metric("問合→面談", f"{total['inquiry_to_interview']}%", 
                       f"{total['inquiry_to_interview'] - targets['問合→面談']:.1f}%")
            cc2.metric("面談→体験", f"{total['interview_to_trial']}%",
                       f"{total['interview_to_trial'] - targets['面談→体験']:.1f}%")
            cc3.metric("体験→入所", f"{total['trial_to_enrollment']}%",
                       f"{total['trial_to_enrollment'] - targets['体験→入所']:.1f}%")
            cc4.metric("問合→入所率", f"{total['inquiry_to_enrollment']}%",
                       f"{total['inquiry_to_enrollment'] - targets['問合→入所']:.1f}%")
            cc5.metric("面談→入所率", f"{total['interview_to_enrollment']}%",
                       f"{total['interview_to_enrollment'] - targets['面談→入所']:.1f}%")
            
            st.divider()
            st.subheader("🏢 事業所別 詳細")
            
            # Prepare display dataframe
            offices = kpi_df[kpi_df['office_name'] != '全体'].copy()
            display = offices[['office_name', 'inquiries', 'interviews', 'trials', 'enrollments',
                              'inquiry_to_interview', 'interview_to_trial', 'trial_to_enrollment',
                              'inquiry_to_enrollment', 'interview_to_enrollment',
                              'interview_cancel_rate', 'trial_cancel_rate']].copy()
            display.columns = ['事業所', '問合数', '面談数', '体験数', '入所数',
                              '問合→面談%', '面談→体験%', '体験→入所%',
                              '問合→入所%', '面談→入所%', '面談Cancel%', '体験Cancel%']
            
            def color_rate(val, target, reverse=False):
                import pandas as _pd
                if _pd.isna(val): return ''
                if reverse:
                    return 'background-color: #ffcccc' if val > 30 else ''
                return 'background-color: #ffcccc' if val < target * 0.8 else ('background-color: #ccffcc' if val >= target else '')
            
            styled = display.style.apply(lambda x: [
                '', '', '', '', '',
                color_rate(x['問合→面談%'], 60), color_rate(x['面談→体験%'], 75),
                color_rate(x['体験→入所%'], 40), color_rate(x['問合→入所%'], 18),
                color_rate(x['面談→入所%'], 30), color_rate(x['面談Cancel%'], 30, True),
                color_rate(x['体験Cancel%'], 30, True)
            ], axis=1)
            
            st.dataframe(styled, use_container_width=True, hide_index=True)
            
            st.caption("🔴 赤: 目標達成率80%未満 | 🟢 緑: 目標達成 | キャンセル率: 30%超で赤")
            
            # Monthly Target vs Actual
            st.divider()
            st.subheader("📅 月次 目標 vs 実績")
            
            monthly_df = db_utils.get_monthly_targets()
            if not monthly_df.empty:
                offices_list = ['全体', '川崎', '横浜', '西船橋', '本厚木', '柏', '三鷹', '関内', '川越']
                months = monthly_df[['year', 'month']].drop_duplicates().sort_values(['year', 'month'])
                
                for _, m_row in months.iterrows():
                    yr, mn = int(m_row['year']), int(m_row['month'])
                    st.markdown(f"**{yr}年{mn}月**")
                    m_data = monthly_df[(monthly_df['year'] == yr) & (monthly_df['month'] == mn)]
                    
                    # Build per-office columns
                    rows = []
                    for _, r in m_data.iterrows():
                        rows.append({
                            '事業所': r['office_name'],
                            '目標': int(r['target']),
                            '実績': int(r['actual']),
                            'ギャップ': int(r['gap']),
                            '達成率': f"{r['achievement_rate']:.1f}%"
                        })
                    display_monthly = pd.DataFrame(rows)
                    
                    def color_achievement(val):
                        if isinstance(val, str) and '%' in val:
                            rate = float(val.replace('%', ''))
                            if rate >= 100: return 'background-color: #ccffcc'
                            if rate < 80: return 'background-color: #ffcccc'
                        return ''
                    
                    def color_gap(val):
                        if isinstance(val, (int, float)):
                            if val < 0: return 'color: green; font-weight: bold'
                            if val > 0: return 'color: red'
                        return ''
                    
                    styled_m = display_monthly.style.map(color_achievement, subset=['達成率']).map(color_gap, subset=['ギャップ'])
                    st.dataframe(styled_m, use_container_width=True, hide_index=True)
        else:
            st.info("KPIデータがありません。")

    # --- Tab 1: Morning/Evening Meeting ---
    with tab1:
        st.header("朝礼・終礼 デイリーチェック")
        
        today = datetime.date.today()
        meeting_date = st.date_input("日付", value=today, key="meeting_date")
        
        meeting_mode = st.radio("会議種別", ["🌅 朝礼", "🌆 終礼"], horizontal=True)
        m_type = "morning" if "朝礼" in meeting_mode else "evening"
        
        # Load existing check state
        checked_ids = db_utils.get_checklist_log(meeting_date)
        existing_notes = db_utils.get_meeting_notes(meeting_date, m_type)
        
        if m_type == "morning":
            # --- 朝礼 ---
            st.subheader("📊 通所状況")
            mc1, mc2, mc3, mc4 = st.columns(4)
            att_total = mc1.number_input("通所人数（予定）", min_value=0, value=int(existing_notes['attendance_total']) if existing_notes is not None else 0, key="att_t")
            att_full = mc2.number_input("終日通所", min_value=0, value=int(existing_notes['attendance_fullday']) if existing_notes is not None else 0, key="att_f")
            att_am = mc3.number_input("午前のみ", min_value=0, value=int(existing_notes['attendance_am']) if existing_notes is not None else 0, key="att_am")
            att_pm = mc4.number_input("午後のみ", min_value=0, value=int(existing_notes['attendance_pm']) if existing_notes is not None else 0, key="att_pm")

            st.subheader("✅ 出勤後、すぐに確認しよう！")
            items = db_utils.get_checklist_items("morning", "daily")
            new_checked = []
            for _, item in items.iterrows():
                val = st.checkbox(item['item_text'], value=(item['id'] in checked_ids), key=f"m_{item['id']}")
                if val:
                    new_checked.append(item['id'])
            
            st.subheader("📝 本日の予定・行動・共有事項")
            schedule_notes = st.text_area("予定を入力", value=existing_notes['schedule_notes'] if existing_notes is not None and existing_notes['schedule_notes'] else "", key="sched_notes", height=100)

            st.subheader("📣 業務連絡")
            biz_notes = st.text_area("業務連絡を入力", value=existing_notes['business_notes'] if existing_notes is not None and existing_notes['business_notes'] else "", key="biz_notes", height=100)

            st.subheader("📅 週次面談")
            interviews = db_utils.get_weekly_interviews(str(meeting_date))
            if not interviews.empty:
                st.dataframe(interviews[['client_name', 'content', 'staff_name']], use_container_width=True)
            with st.expander("週次面談を追加"):
                with st.form("add_interview"):
                    iv_client = st.text_input("利用者氏名")
                    iv_content = st.text_area("面談内容（事前確認）")
                    iv_staff = st.text_input("担当スタッフ")
                    if st.form_submit_button("追加"):
                        db_utils.add_weekly_interview(str(meeting_date), iv_client, iv_content, iv_staff)
                        st.success("追加しました")
                        st.rerun()

            if st.button("朝礼内容を保存", type="primary"):
                db_utils.save_checklist_log(str(meeting_date), new_checked)
                db_utils.save_meeting_notes(str(meeting_date), "morning", {
                    'attendance_total': att_total, 'attendance_fullday': att_full,
                    'attendance_am': att_am, 'attendance_pm': att_pm,
                    'schedule_notes': schedule_notes, 'business_notes': biz_notes
                })
                st.success("朝礼内容を保存しました！")

        else:
            # --- 終礼 ---
            st.subheader("📊 通所実績")
            ec1, ec2, ec3, ec4 = st.columns(4)
            att_total = ec1.number_input("通所人数", min_value=0, value=int(existing_notes['attendance_total']) if existing_notes is not None else 0, key="e_att_t")
            abs_bonus = ec2.number_input("欠席時対応加算", min_value=0, value=int(existing_notes['absence_with_bonus']) if existing_notes is not None else 0, key="e_abs_b")
            abs_no = ec3.number_input("欠席（非加算）", min_value=0, value=int(existing_notes['absence_no_bonus']) if existing_notes is not None else 0, key="e_abs_n")
            late = ec4.number_input("遅刻・早退", min_value=0, value=int(existing_notes['late_early']) if existing_notes is not None else 0, key="e_late")

            st.subheader("✅ 毎日確認する（事業所の全員で確認しましょう）")
            items_daily = db_utils.get_checklist_items("evening", "daily")
            new_checked = []
            for _, item in items_daily.iterrows():
                val = st.checkbox(item['item_text'], value=(item['id'] in checked_ids), key=f"e_{item['id']}")
                if val:
                    new_checked.append(item['id'])

            st.subheader("✅ 週末に行う事")
            items_weekly = db_utils.get_checklist_items("evening", "weekly")
            for _, item in items_weekly.iterrows():
                val = st.checkbox(item['item_text'], value=(item['id'] in checked_ids), key=f"ew_{item['id']}")
                if val:
                    new_checked.append(item['id'])

            st.subheader("✅ 月末・月初に確認する")
            items_monthly = db_utils.get_checklist_items("evening", "monthly")
            for _, item in items_monthly.iterrows():
                val = st.checkbox(item['item_text'], value=(item['id'] in checked_ids), key=f"em_{item['id']}")
                if val:
                    new_checked.append(item['id'])

            st.subheader("📝 ご利用者共有事項・振り返り")
            client_notes = st.text_area("利用者共有事項", value=existing_notes['client_notes'] if existing_notes is not None and existing_notes['client_notes'] else "", key="cl_notes", height=100)

            st.subheader("📣 業務連絡")
            biz_notes = st.text_area("業務連絡を入力", value=existing_notes['business_notes'] if existing_notes is not None and existing_notes['business_notes'] else "", key="e_biz", height=100)

            st.subheader("📌 その他（備考欄）")
            other_notes = st.text_area("その他", value=existing_notes['other_notes'] if existing_notes is not None and existing_notes['other_notes'] else "", key="e_other", height=80)

            if st.button("終礼内容を保存", type="primary"):
                db_utils.save_checklist_log(str(meeting_date), new_checked)
                db_utils.save_meeting_notes(str(meeting_date), "evening", {
                    'attendance_total': att_total,
                    'absence_with_bonus': abs_bonus, 'absence_no_bonus': abs_no, 'late_early': late,
                    'client_notes': client_notes, 'business_notes': biz_notes, 'other_notes': other_notes
                })
                st.success("終礼内容を保存しました！")

        # 就労定着率 × 基本報酬 Reference Table (always visible)
        st.divider()
        st.subheader("📈 就労定着率 × 基本報酬 単位テーブル")
        rates = db_utils.get_reward_rates()
        if not rates.empty:
            st.dataframe(rates[['retention_label', 'units']].rename(columns={
                'retention_label': '就労定着率', 'units': '単位数（1日あたり）'
            }), use_container_width=True, hide_index=True)

    # --- Tab 3: Client Registry ---
    with tab3:
        st.header("利用者台帳")
        clients_df = db_utils.get_clients()
        
        if not clients_df.empty:
            # Key columns for overview
            display_cols = ['name', 'usage_status', 'recipient_number', 'city', 
                           'payment_period_start', 'payment_period_end', 'max_copay',
                           'certificate_acquired', 'contract_date', 'service_start', 'service_end',
                           'desired_employment_date']
            available_cols = [c for c in display_cols if c in clients_df.columns]
            
            col_labels = {
                'name': '氏名', 'usage_status': '利用状態', 'recipient_number': '受給者番号',
                'city': '市区町村', 'payment_period_start': '支給決定開始', 'payment_period_end': '支給決定終了',
                'max_copay': '負担上限額', 'certificate_acquired': '取得有無',
                'contract_date': '契約日', 'service_start': '利用開始', 'service_end': '利用終了',
                'desired_employment_date': '就職希望時期'
            }
            
            st.dataframe(
                clients_df[available_cols].rename(columns=col_labels),
                use_container_width=True
            )
            
            # Expiry Alerts
            st.subheader("⚠️ 期限アラート")
            import pandas as _pd
            today = _pd.Timestamp.now()
            for _, row in clients_df.iterrows():
                if row.get('payment_period_end'):
                    try:
                        end = _pd.Timestamp(row['payment_period_end'])
                        days_left = (end - today).days
                        if 0 < days_left <= 60:
                            st.warning(f"**{row['name']}**: 支給決定期間が残り{days_left}日です（{row['payment_period_end']}まで）。更新手続きを確認してください。")
                    except Exception:
                        pass
        else:
            st.info("利用者データがまだありません。")
        
        with st.expander("➕ 新規利用者登録"):
            with st.form("new_client"):
                nc1, nc2 = st.columns(2)
                with nc1:
                    cl_name = st.text_input("氏名")
                    cl_status = st.selectbox("利用状態", ["利用者", "体験", "見学", "卒業", "退所"])
                    cl_number = st.text_input("受給者番号")
                    cl_city = st.text_input("市区町村")
                    cl_copay = st.selectbox("負担上限額", ["0円", "4600円", "9300円", "37200円"])
                with nc2:
                    cl_start = st.date_input("支給決定期間 開始日")
                    cl_end = st.date_input("支給決定期間 最終日")
                    cl_contract = st.date_input("契約日")
                    cl_cert = st.selectbox("受給者証 取得有無", ["有", "無", "申請中"])
                    cl_desire = st.text_input("就職希望時期 (例: 2026/4)")
                
                if st.form_submit_button("利用者を登録"):
                    db_utils.add_client({
                        'name': cl_name, 'usage_status': cl_status,
                        'recipient_number': cl_number, 'city': cl_city,
                        'max_copay': cl_copay, 'payment_period_start': cl_start,
                        'payment_period_end': cl_end, 'contract_date': cl_contract,
                        'certificate_acquired': cl_cert, 'desired_employment_date': cl_desire
                    })
                    st.success(f"{cl_name} さんを登録しました！")
                    st.rerun()

    # --- Tab 4: Office Management ---
    with tab4:
        st.header("事業所運営状況")
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("利用者候補パイプライン")
            candidates = db_utils.get_user_candidates()
            st.dataframe(candidates[['name', 'status', 'source', 'expected_revenue', 'staff_name', 'note']], use_container_width=True)
            
            # (New Candidate Form - Simplified for View)
            with st.expander("新規候補登録"):
               with st.form("new_candidate_mgr"):
                    staff_list = db_utils.get_staff_list()
                    c_name = st.text_input("氏名")
                    c_source = st.selectbox("紹介元", ["HP", "相談支援", "クリニック", "その他"])
                    c_status = st.selectbox("ステータス", ["問い合わせ", "見学", "体験", "受給者証申請", "契約"])
                    c_rev = st.number_input("見込み月商", value=150000)
                    c_staff = st.selectbox("担当支援員", staff_list['id'], format_func=lambda x: staff_list[staff_list['id'] == x]['name'].values[0])
                    if st.form_submit_button("登録"):
                        db_utils.add_user_candidate(c_name, c_source, c_status, c_staff, c_rev, "")
                        st.success("登録しました")
                        st.rerun()

        with col2:
            st.subheader("売上予測")
            if not candidates.empty:
                total_rev = candidates[candidates['status'].isin(['体験', '契約'])]['expected_revenue'].sum()
                st.metric("当月見込", f"¥{total_rev:,}")
            
            st.subheader("本日の通所者")
            st.info("15名 通所中")
            st.text_area("スタッフへの連絡事項", "本日15時より避難訓練を行います。")

        st.divider()
        st.subheader("議事録管理 (Whisper)")
        uploaded_file = st.file_uploader("会議録音アップロード", type=["mp3", "m4a", "wav"])
        if uploaded_file and st.button("議事録作成"):
            if client:
                with st.spinner("AIが分析中..."):
                    with open("temp_mgr.mp3", "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    transcript = whisper_utils.transcribe_audio(client, "temp_mgr.mp3")
                    summary = whisper_utils.summarize_text(client, transcript, type="meeting")
                    st.markdown(summary)
            else:
                st.error("API Key Missing")

    # --- Tab 5: Staff Management ---
    with tab5:
        st.header("チームマネジメント")
        st.dataframe(db_utils.get_staff_list())
        
        col1, col2 = st.columns(2)
        with col1: 
             st.subheader("KPI概況")
             st.metric("チーム全体 外交件数", "45件")
             st.metric("新規契約数", "5件")
        
        with col2:
             st.subheader("1on1 スケジューリング")
             st.write("2週間に1回の定期面談を設定")
             if st.button("全スタッフの次回1on1を一括設定 (カレンダー連携)"):
                 st.success("Google Calendarに招待を送信しました")
    
    # --- Tab 6: 支援員管理 (Staff Management) ---
    with tab6:
        st.header("👤 支援員管理")

        staff_list = db_utils.get_staff_list(office_id=current_office_id)
        if staff_list.empty:
            st.info("支援員が登録されていません。")
        else:
            # --- Staff overview table ---
            st.subheader("📋 支援員一覧")
            overview_rows = []
            for _, s in staff_list.iterrows():
                details = db_utils.get_staff_details(s['id'])
                age_str = ""
                tenure_str = ""
                quals = ""
                if s.get('age'):
                    age_str = f"{s['age']}歳"
                if s.get('joined_date'):
                    try:
                        jd = datetime.datetime.strptime(str(s['joined_date']), '%Y-%m-%d').date()
                        delta = datetime.date.today() - jd
                        years = delta.days // 365
                        months = (delta.days % 365) // 30
                        tenure_str = f"{years}年{months}ヶ月"
                    except:
                        tenure_str = ""
                if details is not None and details.get('qualifications'):
                    quals = str(details['qualifications'])
                overview_rows.append({
                    'ID': s['id'],
                    '名前': s['name'],
                    '年齢': age_str,
                    '役職': s.get('role', ''),
                    '入社日': str(s.get('joined_date', '')),
                    '勤続年数': tenure_str,
                    '保有資格': quals,
                })

            overview_df = pd.DataFrame(overview_rows)
            st.dataframe(overview_df, use_container_width=True, hide_index=True)

            st.divider()

            # --- Individual staff profile card ---
            st.subheader("📝 支援員プロフィール 詳細 / 編集")
            sel_staff = st.selectbox(
                "支援員を選択",
                staff_list['id'],
                format_func=lambda x: staff_list[staff_list['id'] == x]['name'].values[0],
                key="staff_mgmt_select"
            )

            sel_row = staff_list[staff_list['id'] == sel_staff].iloc[0]
            existing = db_utils.get_staff_details(sel_staff)

            # Show current profile card
            pc1, pc2 = st.columns([1, 2])
            with pc1:
                st.markdown(f"### {sel_row['name']}")
                if sel_row.get('age'):
                    st.write(f"🎂 年齢: **{sel_row['age']}歳**")
                if sel_row.get('joined_date'):
                    st.write(f"📅 入社日: **{sel_row['joined_date']}**")
                    try:
                        jd = datetime.datetime.strptime(str(sel_row['joined_date']), '%Y-%m-%d').date()
                        delta = datetime.date.today() - jd
                        y = delta.days // 365
                        m = (delta.days % 365) // 30
                        st.write(f"📆 勤続: **{y}年{m}ヶ月**")
                    except:
                        pass
                st.write(f"🏷️ 役職: **{sel_row.get('role', 'staff')}**")
            with pc2:
                if existing is not None:
                    quals_val = str(existing.get('qualifications', '')) if existing.get('qualifications') else '未登録'
                    st.write(f"📜 保有資格: **{quals_val}**")
                    st.write(f"📞 電話: {existing.get('phone', '未登録')}")
                    st.write(f"🏠 住所: {existing.get('address', '未登録')}")
                    if existing.get('resume_file_path'):
                        st.write(f"📄 履歴書: `{existing['resume_file_path']}`")
                    else:
                        st.write("📄 履歴書: 未アップロード")
                else:
                    st.info("詳細情報はまだ登録されていません。以下のフォームから登録してください。")

            # Edit form
            with st.expander("✏️ プロフィールを編集", expanded=False):
                with st.form("staff_details_form"):
                    ed_c1, ed_c2 = st.columns(2)
                    with ed_c1:
                        address = st.text_input("現住所", value=str(existing['address']) if existing is not None and existing.get('address') else "")
                        birthday = st.date_input("生年月日", value=datetime.datetime.strptime(str(existing['birthday']), '%Y-%m-%d').date() if existing is not None and existing.get('birthday') else datetime.date(1990, 1, 1))
                        phone = st.text_input("電話番号", value=str(existing['phone']) if existing is not None and existing.get('phone') else "")
                        bank = st.text_area("振込口座情報", value=str(existing['bank_info']) if existing is not None and existing.get('bank_info') else "")
                    with ed_c2:
                        qualifications = st.text_area(
                            "保有資格（改行区切り）",
                            value=str(existing['qualifications']) if existing is not None and existing.get('qualifications') else "",
                            height=100,
                            placeholder="例:\n社会福祉士\n精神保健福祉士\nサービス管理責任者"
                        )
                        dependents = st.number_input("扶養親族数", min_value=0, value=int(existing['dependents_count']) if existing is not None and existing.get('dependents_count') else 0)
                        salary = st.number_input("基本給 (円)", value=int(existing['base_salary']) if existing is not None and existing.get('base_salary') else 250000, step=10000)
                        commute = st.number_input("通勤手当 (円)", value=int(existing['commuter_allowance']) if existing is not None and existing.get('commuter_allowance') else 15000, step=100)

                    notes = st.text_area("メモ・備考", value=str(existing['notes']) if existing is not None and existing.get('notes') else "")
                    resume_file = st.file_uploader("📄 履歴書アップロード（PDF/画像）", type=["pdf", "png", "jpg", "jpeg"], key="resume_upload")

                    if st.form_submit_button("💾 保存/更新", type="primary"):
                        resume_path = None
                        if existing is not None and existing.get('resume_file_path'):
                            resume_path = existing['resume_file_path']
                        if resume_file:
                            import os
                            resume_dir = os.path.join(os.path.dirname(__file__), "uploads", "resumes")
                            os.makedirs(resume_dir, exist_ok=True)
                            resume_path = os.path.join(resume_dir, f"staff_{sel_staff}_{resume_file.name}")
                            with open(resume_path, "wb") as f:
                                f.write(resume_file.getbuffer())

                        db_utils.upsert_staff_details(
                            sel_staff, address, birthday, phone, bank, dependents, commute, salary,
                            qualifications=qualifications, resume_file_path=resume_path, notes=notes
                        )
                        st.success("✅ 支援員情報を更新しました。")
                        st.rerun()

        # --- 勤怠サマリー (collapsible) ---
        with st.expander("📊 勤怠レポート", expanded=False):
            att_col1, att_col2 = st.columns(2)
            with att_col1:
                att_from = st.date_input("開始日", datetime.date.today().replace(day=1), key="att_from")
            with att_col2:
                att_to = st.date_input("終了日", datetime.date.today(), key="att_to")
            att_report = db_utils.get_attendance_report(str(att_from), str(att_to))
            if not att_report.empty:
                st.dataframe(att_report[['date', 'staff_name', 'role', 'clock_in', 'clock_out', 'break_start', 'break_end', 'status']].rename(columns={
                    'date': '日付', 'staff_name': 'スタッフ名', 'role': '役職',
                    'clock_in': '出勤', 'clock_out': '退勤', 'break_start': '休憩開始',
                    'break_end': '休憩終了', 'status': 'ステータス'
                }), use_container_width=True, hide_index=True)
            else:
                st.info("指定期間の勤怠データはありません。")

        # --- 手続きToDo (collapsible) ---
        with st.expander("📋 労務手続き進捗 (ToDo)", expanded=False):
            procedures = db_utils.get_labor_procedures()
            if not procedures.empty:
                st.dataframe(procedures[['staff_name', 'category', 'item_name', 'status', 'due_date']], use_container_width=True)
            else:
                st.info("現在進行中の手続きはありません。")
            with st.form("new_proc"):
                p_staff_list = db_utils.get_staff_list()
                p_staff = st.selectbox("対象スタッフ", p_staff_list['id'], format_func=lambda x: p_staff_list[p_staff_list['id'] == x]['name'].values[0], key="proc_staff")
                p_cat = st.selectbox("カテゴリ", ["入社手続き", "退社手続き", "社会保険", "労災申請", "その他"], key="proc_cat")
                p_item = st.text_input("項目名 (例: 雇用保険資格取得届)", key="proc_item")
                p_due = st.date_input("期限", key="proc_due")
                if st.form_submit_button("タスク追加"):
                    db_utils.add_labor_procedure(p_staff, p_cat, p_item, p_due)
                    st.success("追加しました")
                    st.rerun()

    # --- Tab 7: 行政申請 (Admin/Government) ---
    with tab7:
        st.header("📑 行政申請・対応履歴")
        
        # --- Section 1: 処遇改善加算 ---
        st.subheader("🏢 福祉・処遇改善加算管理")
        st.write("今年度の処遇改善加算計画と実績")
        
        check1 = st.checkbox("キャリアパス要件1 (職位・職責・任用要件の整備)")
        check2 = st.checkbox("キャリアパス要件2 (研修計画の策定と実施)")
        check3 = st.checkbox("キャリアパス要件3 (昇給の仕組みの整備)")
        check4 = st.checkbox("職場環境等要件 (賃金改善以外の取り組み)")
        
        if check1 and check2 and check3 and check4:
            st.success("要件は概ね満たされています。実績報告書の作成準備を進めてください。")
        else:
            st.warning("未達成の要件があります。")

        st.divider()

        # --- Section 2: 行政対応履歴 (CRM) ---
        st.subheader("📞 行政対応履歴")
        st.caption("市区町村・県庁・国保連等との対応記録を管理します")

        # Filter
        admin_filter_col1, admin_filter_col2 = st.columns(2)
        with admin_filter_col1:
            admin_offices = db_utils.get_offices()
            admin_office_opts = [(None, "全事業所")] + [(r['id'], r['name']) for _, r in admin_offices.iterrows()]
            admin_office_filter = st.selectbox(
                "事業所",
                options=[o[0] for o in admin_office_opts],
                format_func=lambda x: dict(admin_office_opts).get(x, "全事業所"),
                key="admin_office_filter"
            )
        with admin_filter_col2:
            admin_cat_filter = st.selectbox(
                "カテゴリ",
                [None, "指定更新", "実地指導", "加算届出", "処遇改善", "その他"],
                format_func=lambda x: x if x else "全て",
                key="admin_cat_filter"
            )

        interactions = db_utils.get_admin_interactions(
            office_id=admin_office_filter,
            category=admin_cat_filter
        )

        if not interactions.empty:
            display_cols = ['interaction_date', 'office_name', 'category', 'counterpart_org',
                          'counterpart_person', 'channel', 'summary', 'status', 'next_action', 'next_action_date']
            available_cols = [c for c in display_cols if c in interactions.columns]
            col_names = {
                'interaction_date': '日付', 'office_name': '事業所', 'category': 'カテゴリ',
                'counterpart_org': '相手先機関', 'counterpart_person': '担当者',
                'channel': '手段', 'summary': '内容', 'status': 'ステータス',
                'next_action': '次回アクション', 'next_action_date': '次回期日'
            }
            st.dataframe(
                interactions[available_cols].rename(columns=col_names),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("行政対応履歴がありません。新規登録してください。")

        # New interaction form
        with st.expander("📝 新規対応記録を登録", expanded=False):
            with st.form("new_admin_interaction"):
                ai_col1, ai_col2 = st.columns(2)
                with ai_col1:
                    ai_office = st.selectbox(
                        "事業所",
                        options=[r['id'] for _, r in admin_offices.iterrows()],
                        format_func=lambda x: admin_offices[admin_offices['id'] == x]['name'].values[0],
                        key="ai_office"
                    )
                    ai_date = st.date_input("対応日", key="ai_date")
                    ai_category = st.selectbox("カテゴリ", ["指定更新", "実地指導", "加算届出", "処遇改善", "その他"], key="ai_cat")
                    ai_channel = st.selectbox("手段", ["電話", "訪問", "メール", "書面", "オンライン"], key="ai_channel")
                with ai_col2:
                    ai_org = st.text_input("相手先機関（例: 川崎市役所 障害福祉課）", key="ai_org")
                    ai_person = st.text_input("担当者名", key="ai_person")
                    ai_next = st.text_input("次回アクション", key="ai_next")
                    ai_next_date = st.date_input("次回期日", key="ai_next_date")

                ai_summary = st.text_area("対応内容・議事録", height=150, key="ai_summary")
                ai_audio = st.file_uploader("録音データ（任意）", type=["mp3", "wav", "m4a"], key="ai_audio")

                if st.form_submit_button("対応記録を保存", type="primary"):
                    audio_path = None
                    if ai_audio:
                        import os
                        audio_dir = os.path.join(os.path.dirname(__file__), "uploads", "admin_audio")
                        os.makedirs(audio_dir, exist_ok=True)
                        audio_path = os.path.join(audio_dir, ai_audio.name)
                        with open(audio_path, "wb") as f:
                            f.write(ai_audio.getbuffer())

                    db_utils.add_admin_interaction(
                        office_id=ai_office,
                        interaction_date=str(ai_date),
                        category=ai_category,
                        counterpart_org=ai_org,
                        counterpart_person=ai_person,
                        channel=ai_channel,
                        summary=ai_summary,
                        audio_file_path=audio_path,
                        next_action=ai_next,
                        next_action_date=str(ai_next_date) if ai_next else None,
                        staff_id=user['id']
                    )
                    st.success("✅ 行政対応記録を保存しました")
                    st.rerun()

    # --- Tab 8: 利用実績 (Client Usage Tracking) ---
    with tab8:
        st.header("📋 利用実績管理")
        
        # Alerts at the top
        db_utils.seed_addition_defaults()
        alerts = db_utils.get_client_alerts()
        if alerts:
            st.subheader("⚠️ アラート")
            for a in alerts:
                if a['type'] == 'danger':
                    st.error(f"**{a['client']}**: {a['msg']}")
                else:
                    st.warning(f"**{a['client']}**: {a['msg']}")
            st.divider()
        
        # Daily record entry
        st.subheader("📅 日次通所実績の登録")
        clients_df = db_utils.get_clients()
        active_clients = clients_df[clients_df['usage_status'] == '利用者'] if not clients_df.empty else pd.DataFrame()
        
        if not active_clients.empty:
            cdr_col1, cdr_col2 = st.columns(2)
            with cdr_col1:
                sel_client = st.selectbox("利用者", active_clients['id'].tolist(),
                    format_func=lambda x: active_clients[active_clients['id']==x]['name'].values[0],
                    key="cdr_client")
                cdr_date = st.date_input("日付", datetime.date.today(), key="cdr_date")
                service_type = st.selectbox("サービス種別", ["通所", "欠席", "施設外支援", "体験"], key="cdr_svc")
            with cdr_col2:
                cdr_in = st.time_input("到着", datetime.time(9, 0), key="cdr_in")
                cdr_out = st.time_input("退所", datetime.time(16, 0), key="cdr_out")
                cdr_memo = st.text_input("メモ", key="cdr_memo")
            
            add_col1, add_col2, add_col3 = st.columns(3)
            pickup = add_col1.checkbox("🚗 迎え送迎", key="cdr_pickup")
            dropoff = add_col1.checkbox("🚗 送り送迎", key="cdr_dropoff")
            meal = add_col2.checkbox("🍱 食事提供", key="cdr_meal")
            absence_contact = add_col3.checkbox("📞 欠席連絡あり", key="cdr_abs_c")
            absence_support = add_col3.checkbox("📝 欠席時対応あり", key="cdr_abs_s")
            outside_support = add_col2.checkbox("🏢 施設外支援", key="cdr_outs")
            
            if st.button("✅ 実績を登録", type="primary"):
                db_utils.add_client_daily_record(
                    sel_client, str(cdr_date), service_type,
                    str(cdr_in), str(cdr_out),
                    int(pickup), int(dropoff), int(meal),
                    int(absence_contact), int(absence_support),
                    int(outside_support), cdr_memo, user['id'])
                st.success("通所実績を登録しました！")
                st.rerun()
        else:
            st.info("利用者が登録されていません。「利用者台帳」タブで登録してください。")
        
        # Monthly summary
        st.divider()
        st.subheader("📊 月次実績サマリー")
        sum_col1, sum_col2 = st.columns(2)
        sum_year = sum_col1.number_input("年", value=datetime.date.today().year, key="usage_sum_y")
        sum_month = sum_col2.number_input("月", value=datetime.date.today().month, min_value=1, max_value=12, key="usage_sum_m")
        
        summary = db_utils.get_monthly_usage_summary(int(sum_year), int(sum_month))
        if not summary.empty:
            display_cols = {
                'client_name': '利用者名', 'recipient_number': '受給者証番号',
                'total_days': '利用日数', 'attend_days': '通所日数',
                'pickup_count': '迎え', 'dropoff_count': '送り',
                'meal_count': '食事', 'absence_support_count': '欠席対応',
                'outside_support_count': '施設外', 'contracted_days': '契約日数'
            }
            st.dataframe(summary.rename(columns=display_cols)[list(display_cols.values())],
                        use_container_width=True, hide_index=True)
        else:
            st.info("指定月のデータはありません。")
        
        # Recent records
        st.divider()
        st.subheader("📜 直近の通所記録")
        recent = db_utils.get_client_daily_records(date_from=str(datetime.date.today() - datetime.timedelta(days=7)))
        if not recent.empty:
            st.dataframe(recent[['record_date', 'client_name', 'service_type', 'clock_in', 'clock_out',
                                 'pickup_flag', 'dropoff_flag', 'meal_flag']].rename(columns={
                'record_date': '日付', 'client_name': '利用者', 'service_type': '種別',
                'clock_in': '到着', 'clock_out': '退所', 'pickup_flag': '迎え',
                'dropoff_flag': '送り', 'meal_flag': '食事'
            }), use_container_width=True, hide_index=True)
        else:
            st.info("直近の記録はありません。")

    # --- Tab 8: 支援記録 (Support Records) ---
    with tab9:
        st.header("📝 支援記録（ケース記録）")
        st.caption("通所実績と連動したサービス提供記録")
        
        clients_df2 = db_utils.get_clients()
        active_clients2 = clients_df2[clients_df2['usage_status'] == '利用者'] if not clients_df2.empty else pd.DataFrame()
        
        if not active_clients2.empty:
            sr_col1, sr_col2 = st.columns(2)
            with sr_col1:
                sr_client = st.selectbox("利用者", active_clients2['id'].tolist(),
                    format_func=lambda x: active_clients2[active_clients2['id']==x]['name'].values[0],
                    key="sr_client")
                sr_date = st.date_input("記録日", datetime.date.today(), key="sr_date")
            with sr_col2:
                sr_svc = st.selectbox("サービス種別", ["通所", "欠席時対応", "施設外支援", "体験"], key="sr_svc")
                sr_condition = st.selectbox("体調", ["良好", "やや不調", "不調", "休憩あり"], key="sr_cond")
            
            sr_content = st.text_area("支援内容", height=150, key="sr_content",
                placeholder="・本日のプログラム参加状況\n・面談内容\n・行動観察\n・特記事項")
            sr_goal = st.text_area("目標に対する進捗", height=80, key="sr_goal",
                placeholder="個別支援計画の目標に対する進捗状況")
            
            if st.button("📝 支援記録を保存", type="primary"):
                db_utils.add_support_record(sr_client, str(sr_date), sr_svc,
                    sr_content, sr_condition, sr_goal, user['id'], user['name'])
                st.success("支援記録を保存しました！")
                st.rerun()
        else:
            st.info("利用者が登録されていません。")
        
        # Record history
        st.divider()
        st.subheader("📜 支援記録一覧")
        sr_filter_col1, sr_filter_col2 = st.columns(2)
        sr_from = sr_filter_col1.date_input("開始日", datetime.date.today() - datetime.timedelta(days=30), key="sr_from")
        sr_to = sr_filter_col2.date_input("終了日", datetime.date.today(), key="sr_to")
        
        records = db_utils.get_support_records(date_from=str(sr_from), date_to=str(sr_to))
        if not records.empty:
            for _, rec in records.iterrows():
                with st.expander(f"📄 {rec['record_date']} — {rec['client_name']} [{rec['service_type']}]"):
                    st.write(f"**体調:** {rec['client_condition']}")
                    st.write(f"**支援内容:** {rec['support_content']}")
                    if rec['goal_progress']:
                        st.write(f"**目標進捗:** {rec['goal_progress']}")
                    st.caption(f"記録者: {rec['staff_name']}")
        else:
            st.info("指定期間の記録はありません。")

    # --- Tab 9: 請求・CSV ウィザード (Billing Wizard) ---
    with tab10:
        st.header("💰 国保連請求CSV ウィザード")
        st.caption("ステップに従って操作するだけで、正確なCSVを生成できます")

        # Import billing module
        from billing import config as bill_config
        from billing.main import process_billing, validate_records, parse_jisseki_csv

        # ============================================================
        # Step 1: 対象年月を選択
        # ============================================================
        st.subheader("📅 Step 1: 対象年月")
        bill_col1, bill_col2 = st.columns(2)
        bill_year = bill_col1.number_input("年", value=datetime.date.today().year, key="bill_y")
        bill_month = bill_col2.number_input("月", value=datetime.date.today().month,
                                            min_value=1, max_value=12, key="bill_m")

        st.divider()

        # ============================================================
        # Step 2: 事業所情報の確認
        # ============================================================
        st.subheader("🏢 Step 2: 事業所情報")
        st.info("� この情報はCSVのヘッダーに使用されます。初回設定後は自動入力されます。")

        oi_col1, oi_col2 = st.columns(2)
        office_id = oi_col1.text_input("事業所番号（10桁）",
            value=bill_config.OFFICE_INFO["office_id"], key="w_oid")
        office_name = oi_col2.text_input("事業所名",
            value=bill_config.OFFICE_INFO["office_name"], key="w_oname")
        corp_name = oi_col1.text_input("法人名",
            value=bill_config.OFFICE_INFO["corporation_name"], key="w_corp")

        base_code = oi_col2.selectbox("基本サービスコード", options=[
            "432025 — 就労移行(I) 定員20人以下 (1,020単位)",
            "432011 — 就労移行(I) 定員21~40人 (871単位)",
            "432015 — 就労移行(I) 定員41~60人 (804単位)",
        ], key="w_bcode")
        selected_base_code = base_code.split(" — ")[0].strip()

        st.divider()

        # ============================================================
        # Step 3: 入力データ選択
        # ============================================================
        st.subheader("📂 Step 3: データ入力方法")

        input_method = st.radio("データの取得元を選択してください", [
            "📊 DBから取得（利用実績タブで登録済みデータ）",
            "📄 CSVファイルをアップロード（knowbe等からエクスポート）",
        ], key="w_input")

        billing_result = None
        csv_uploaded = None

        if "CSVファイル" in input_method:
            csv_uploaded = st.file_uploader("実績記録票CSV", type=["csv"], key="w_csv")
            if csv_uploaded:
                csv_content = csv_uploaded.read().decode("utf-8", errors="replace")
                try:
                    billing_result = process_billing(
                        csv_content=csv_content,
                        addition_codes=[],
                    )
                    st.success(f"✅ CSVを読み込みました（{billing_result['summary']['total_users']}名分）")
                except Exception as e:
                    st.error(f"CSV読み込みエラー: {e}")
        else:
            # DB から取得
            try:
                summary_df = db_utils.get_monthly_usage_summary(int(bill_year), int(bill_month))
                records_df = db_utils.get_client_daily_records(
                    date_from=f"{int(bill_year)}-{int(bill_month):02d}-01",
                    date_to=f"{int(bill_year)}-{int(bill_month):02d}-31"
                )

                if not records_df.empty:
                    # クライアント情報を結合
                    clients_df = db_utils.get_clients()
                    if not clients_df.empty:
                        merge_cols = ['id', 'recipient_number', 'name']
                        if 'municipality_code' in clients_df.columns:
                            merge_cols.append('municipality_code')
                        merged = records_df.merge(
                            clients_df[merge_cols].rename(
                                columns={'id': 'client_id'}),
                            on='client_id', how='left', suffixes=('', '_client')
                        )
                    else:
                        merged = records_df

                    billing_result = process_billing(
                        records_df=merged,
                        year=int(bill_year),
                        month=int(bill_month),
                        office_id=office_id,
                        addition_codes=[],
                    )
                    st.success(f"✅ DBから{billing_result['summary']['total_users']}名分のデータを取得しました")
                else:
                    st.warning("📭 指定月のデータがDBにありません。利用実績タブで日次記録を登録するか、CSVをアップロードしてください。")
            except Exception as e:
                st.error(f"DB読み込みエラー: {e}")

        st.divider()

        # ============================================================
        # Step 4: バリデーション（エラーチェック）
        # ============================================================
        st.subheader("✅ Step 4: 提出前エラーチェック")

        if billing_result:
            validation = billing_result["validation"]

            if validation.errors:
                st.error(f"🔴 **{len(validation.errors)}件のエラーがあります。修正するまでCSVをダウンロードできません。**")
                for err in validation.errors:
                    st.markdown(f"- {err}")

            if validation.warnings:
                st.warning(f"⚠️ **{len(validation.warnings)}件の警告があります（要確認）**")
                for warn in validation.warnings:
                    st.markdown(f"- {warn}")

            if validation.is_valid and not validation.warnings:
                st.success("🎉 すべてのチェックに合格しました！")
            elif validation.is_valid:
                st.info("⚠️ 警告はありますが、CSVの生成は可能です。内容を確認してください。")

            st.divider()

            # ============================================================
            # Step 5: プレビュー
            # ============================================================
            st.subheader("📊 Step 5: 請求プレビュー")

            items = billing_result["billing_items"]
            summary = billing_result["summary"]

            # サマリーカード
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("👥 対象人数", f"{summary['total_users']}名")
            m2.metric("📊 合計単位数", f"{summary['total_units']:,}")
            m3.metric("💰 給付費請求額", f"¥{summary['total_billing']:,}")
            m4.metric("👤 利用者負担額", f"¥{summary['total_copay']:,}")

            # 利用者別明細
            with st.expander("📋 利用者別明細", expanded=True):
                detail_data = []
                for item in items:
                    detail_data.append({
                        '受給者証番号': item.user_id,
                        '市町村番号': item.city_code,
                        '利用日数': item.days_used,
                        '基本単位数': item.base_total_units,
                        '加算単位数': item.addition_total_units + item.monthly_addition_units,
                        '合計単位数': item.final_units,
                        '地域単価': f"{item.unit_price:.2f}",
                        '総費用額': f"¥{item.total_cost:,}",
                        '給付費': f"¥{item.billing_amount:,}",
                        '自己負担': f"¥{item.user_copay:,}",
                    })
                st.dataframe(pd.DataFrame(detail_data), use_container_width=True, hide_index=True)

            # J611 プレビュー
            with st.expander("📄 J611 CSV プレビュー（国保連伝送フォーマット）"):
                j611_lines = billing_result["j611_csv"].strip().split("\r\n")
                if j611_lines:
                    preview_count = min(10, len(j611_lines))
                    st.code("\n".join(j611_lines[:preview_count]), language="csv")
                    if len(j611_lines) > preview_count:
                        st.caption(f"...他 {len(j611_lines) - preview_count} 行")

            st.divider()

            # ============================================================
            # Step 6: CSVダウンロード
            # ============================================================
            st.subheader("📥 Step 6: CSVダウンロード")

            if validation.has_errors:
                st.error("🔴 エラーを修正してからダウンロードしてください。")
                st.button("📄 ダウンロード不可（エラーあり）", disabled=True, key="w_dl_disabled")
            else:
                ym = f"{int(bill_year)}{int(bill_month):02d}"

                dl1, dl2, dl3 = st.columns(3)

                with dl1:
                    st.markdown("#### 📄 様式第一")
                    st.caption("請求書鑑（自治体別集計）")
                    st.download_button(
                        "⬇️ 様式第一.csv",
                        billing_result["yoshiki_1_csv"],
                        file_name=f"yoshiki1_{ym}.csv",
                        mime="text/csv",
                        type="primary",
                        key="w_dl1"
                    )

                with dl2:
                    st.markdown("#### 📄 様式第二")
                    st.caption("明細書（利用者別）")
                    st.download_button(
                        "⬇️ 様式第二.csv",
                        billing_result["yoshiki_2_csv"],
                        file_name=f"yoshiki2_{ym}.csv",
                        mime="text/csv",
                        type="primary",
                        key="w_dl2"
                    )

                with dl3:
                    st.markdown("#### 📄 J611実績記録票")
                    st.caption("国保連伝送フォーマット")
                    st.download_button(
                        "⬇️ J611.csv",
                        billing_result["j611_csv"],
                        file_name=f"j611_{ym}.csv",
                        mime="text/csv",
                        type="primary",
                        key="w_dl3"
                    )

                st.success("✅ ダウンロード準備完了！ボタンをクリックしてCSVを取得してください。")

        else:
            st.info("📝 Step 3 でデータを入力するとバリデーション結果が表示されます。")

        # ============================================================
        # マスタ設定（折りたたみ）
        # ============================================================
        st.divider()
        with st.expander("⚙️ マスタ設定（サービスコード・地域単価）"):
            st.markdown("#### サービスコードマスタ")
            sc_data = []
            for code, info in bill_config.SERVICE_CODE_MASTER.items():
                sc_data.append({
                    'コード': code,
                    '名称': info['name'],
                    '単位数': info['units'],
                    '計算種別': info['calc_type'],
                    '加算率': f"{info.get('rate', 0) * 100:.1f}%" if info.get('rate') else '-',
                })
            st.dataframe(pd.DataFrame(sc_data), use_container_width=True, hide_index=True)

            st.markdown("#### 地域単価マスタ")
            gp_data = []
            for grade, prices in bill_config.GRADE_UNIT_PRICES.items():
                gp_data.append({
                    '級地': grade,
                    '就労移行': f"{prices['就労移行支援']:.2f}円",
                    '就労定着': f"{prices['就労定着支援']:.2f}円",
                })
            st.dataframe(pd.DataFrame(gp_data), use_container_width=True, hide_index=True)

# ================================================================
# Client Dashboard (利用者ポータル)
# ================================================================
def client_dashboard():
    client_id = st.session_state.get("client_id")
    if client_id is None:
        st.error("利用者情報が見つかりません。ログインし直してください。")
        if st.button("ログインへ戻る"):
            st.session_state["logged_in"] = False
            st.rerun()
        return
    cl = db_utils.get_client_by_id(client_id)
    if cl is None:
        st.error("利用者情報が見つかりません。ログインし直してください。")
        if st.button("ログインへ戻る"):
            st.session_state["logged_in"] = False
            st.rerun()
        return

    st.title(f"🎓 マイページ: {cl['name']} さん")

    # Graduation steps
    GRAD_STEPS = [
        ("onboarding", "🏁 通所開始"),
        ("training_basic", "📚 基礎訓練"),
        ("training_advanced", "📖 応用訓練"),
        ("internship", "🏢 実習"),
        ("job_hunting", "🔍 就職活動"),
        ("job_offer", "🎉 内定"),
        ("graduation", "🎓 卒業"),
    ]
    current_step = cl.get('graduation_step', 'training_basic')
    step_keys = [s[0] for s in GRAD_STEPS]
    current_idx = step_keys.index(current_step) if current_step in step_keys else 1

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🎯 卒業ステップ", "📖 学習記録", "🌱 1on1 記録",
        "📅 出勤スケジュール", "🏥 体調チェックイン", "📊 マイ成長グラフ"
    ])

    # ================================================================
    # Tab 1: 卒業ステップ
    # ================================================================
    with tab1:
        st.header("🎯 卒業までのステップ")
        progress = (current_idx) / (len(GRAD_STEPS) - 1) * 100
        st.progress(min(progress / 100, 1.0), text=f"進捗: {progress:.0f}%")

        cols = st.columns(len(GRAD_STEPS))
        for i, (key, label) in enumerate(GRAD_STEPS):
            with cols[i]:
                if i < current_idx:
                    st.success(f"✅\n{label}")
                elif i == current_idx:
                    st.info(f"🔵\n{label}")
                else:
                    st.markdown(f"⬜\n{label}")

        st.divider()
        # Current step details
        st.subheader(f"現在のステップ: {GRAD_STEPS[current_idx][1]}")

        step_details = {
            "onboarding": "通所を開始しました！まずは事業所の雰囲気に慣れ、基本的な生活リズムを整えましょう。",
            "training_basic": "ビジネスマナー、PC操作、コミュニケーション等の基礎スキルを学んでいます。",
            "training_advanced": "専門スキルや資格取得に向けた応用訓練を行っています。",
            "internship": "企業での実習に参加しています。実際の職場環境を体験中です。",
            "job_hunting": "履歴書作成、面接練習など就職活動に取り組んでいます。",
            "job_offer": "おめでとうございます！内定を獲得しました。入社準備を進めましょう。",
            "graduation": "🎊 卒業おめでとうございます！定着支援に移行します。",
        }
        st.write(step_details.get(current_step, ""))

        if cl.get('service_start'):
            st.caption(f"利用開始日: {cl['service_start']}")
        if cl.get('planned_months'):
            st.caption(f"利用予定期間: {cl['planned_months']}ヶ月")

    # ================================================================
    # Tab 2: 学習記録
    # ================================================================
    with tab2:
        st.header("📖 学習記録")

        with st.expander("✏️ 新しい記録を追加"):
            with st.form("add_learning"):
                l_date = st.date_input("日付", datetime.date.today(), key="learn_date")
                l_cat = st.selectbox("種類", ["授業", "自習", "実習", "グループワーク", "その他"], key="learn_cat")
                l_title = st.text_input("タイトル", key="learn_title", placeholder="例: PC基礎 — Excel入門")
                l_content = st.text_area("学んだこと・気づき", key="learn_content", height=150,
                                         placeholder="今日学んだことを自分の言葉で記録しましょう。\n成長を実感するための大切な記録です。")
                if st.form_submit_button("📝 記録する", type="primary"):
                    if l_title.strip():
                        db_utils.add_client_learning_log(client_id, l_date, l_cat, l_title, l_content)
                        st.success("学習記録を追加しました！")
                        st.rerun()

        st.divider()
        logs = db_utils.get_client_learning_log(client_id)
        if not logs.empty:
            cat_icons = {"授業": "📚", "自習": "📖", "実習": "🏢", "グループワーク": "👥", "その他": "📝"}
            for _, log in logs.iterrows():
                icon = cat_icons.get(log.get('category', ''), '📝')
                with st.expander(f"{icon} {log.get('date', '')} — {log.get('title', '')}"):
                    st.write(f"**カテゴリ:** {log.get('category', '')}")
                    st.write(log.get('content', ''))
        else:
            st.info("まだ学習記録がありません。最初の記録を追加してみましょう！")

        # Stats
        if not logs.empty:
            st.divider()
            st.subheader("📊 学習の統計")
            st.metric("総記録数", len(logs))
            cat_counts = logs['category'].value_counts()
            for cat, count in cat_counts.items():
                st.write(f"  {cat}: {count}件")

    # ================================================================
    # Tab 3: 1on1 記録
    # ================================================================
    with tab3:
        st.header("🌱 1on1 面談記録")
        records = db_utils.get_client_oneonone_records(client_id)
        if not records.empty:
            for _, rec in records.iterrows():
                with st.expander(f"🗓 {rec.get('date', '')} — {rec.get('staff_name', '支援員')}"):
                    st.write(rec.get('content', ''))
                    if rec.get('completed'):
                        st.success("✅ 完了")
        else:
            st.info("まだ1on1の記録がありません。支援員との面談後に記録が追加されます。")

    # ================================================================
    # Tab 4: 出勤スケジュール
    # ================================================================
    with tab4:
        st.header("📅 出勤スケジュール")
        today = datetime.date.today()
        month_start = today.replace(day=1)
        import calendar as cal_mod
        _, last_day = cal_mod.monthrange(today.year, today.month)
        month_end = today.replace(day=last_day)

        st.subheader(f"📆 {today.year}年{today.month}月")

        # Get attendance records
        import sqlite3 as _sq
        _cn = _sq.connect("employment_support.db")
        att_df = pd.read_sql("""SELECT record_date, clock_in, clock_out, service_type, memo
            FROM client_daily_records WHERE client_id = ?
            AND record_date >= ? AND record_date <= ?
            ORDER BY record_date""", _cn, params=[client_id, str(month_start), str(month_end)])
        _cn.close()

        if not att_df.empty:
            st.dataframe(att_df.rename(columns={
                'record_date': '日付', 'clock_in': '出所', 'clock_out': '退所',
                'service_type': 'サービス種別', 'memo': 'メモ'
            }), use_container_width=True, hide_index=True)
            attended_days = len(att_df)
            weekday_count = sum(1 for d in range((month_end - month_start).days + 1)
                               if (month_start + datetime.timedelta(days=d)).weekday() < 5)
            st.metric("今月の出席日数", f"{attended_days}日 / {weekday_count}営業日")
        else:
            st.info("今月の出勤記録はまだありません。")

        # Calendar grid
        st.divider()
        st.subheader("📅 カレンダービュー")
        weekday_names = ['月', '火', '水', '木', '金', '土', '日']
        hdr_cols = st.columns(7)
        for i, wd in enumerate(weekday_names):
            hdr_cols[i].markdown(f"**{wd}**")

        first_weekday = month_start.weekday()
        day = 1
        attended_dates = set(att_df['record_date'].tolist()) if not att_df.empty else set()

        for week in range(6):
            week_cols = st.columns(7)
            for dow in range(7):
                if week == 0 and dow < first_weekday:
                    week_cols[dow].write("")
                elif day > last_day:
                    week_cols[dow].write("")
                else:
                    d = today.replace(day=day)
                    date_str = d.isoformat()
                    if date_str in attended_dates:
                        week_cols[dow].markdown(f"🟢 **{day}**")
                    elif d == today:
                        week_cols[dow].markdown(f"🔵 {day}")
                    elif d.weekday() >= 5:
                        week_cols[dow].markdown(f"🔘 {day}")
                    else:
                        week_cols[dow].write(f"{day}")
                    day += 1

    # ================================================================
    # Tab 5: 体調チェックイン
    # ================================================================
    with tab5:
        st.header("🏥 体調チェックイン")

        todays_checkin = db_utils.get_todays_health_checkin(client_id)
        if todays_checkin is not None:
            st.success("✅ 本日のチェックイン済みです！")
            st.write(f"💤 睡眠: {todays_checkin.get('sleep_hours', '?')}時間")
            st.write(f"😊 体調: {'⭐' * int(todays_checkin.get('condition_score', 3))}")
            st.write(f"🍽️ 食事: {todays_checkin.get('meal_record', '')}")
            st.write(f"🏃 運動: {todays_checkin.get('exercise_record', '')}")
            if todays_checkin.get('notes'):
                st.write(f"📝 メモ: {todays_checkin['notes']}")
        else:
            st.info("今日のチェックインがまだです。下記のフォームから入力してください。")
            with st.form("health_checkin"):
                st.markdown("### 今日の体調を記録しましょう")
                h_sleep = st.slider("💤 睡眠時間 (時間)", 0.0, 12.0, 7.0, 0.5, key="h_sleep")

                h_cond = st.select_slider("😊 今日の体調",
                                          options=[1, 2, 3, 4, 5],
                                          format_func=lambda x: {1: "😢 悪い", 2: "😕 やや悪い", 3: "😐 普通", 4: "😊 良い", 5: "😄 とても良い"}[x],
                                          value=3, key="h_cond")

                h_meal = st.text_area("🍽️ 食事記録", key="h_meal", height=80,
                                      placeholder="朝: パン、コーヒー\n昼: お弁当\n夜: まだ")

                h_exercise = st.selectbox("🏃 運動", ["なし", "ウォーキング", "ストレッチ", "ジョギング", "筋トレ", "その他"], key="h_exercise")

                h_notes = st.text_area("📝 今日の一言（任意）", key="h_notes", height=60,
                                       placeholder="体調で気になること、今日の目標など")

                if st.form_submit_button("✅ チェックイン", type="primary"):
                    db_utils.add_client_health_checkin(
                        client_id, datetime.date.today().isoformat(),
                        h_sleep, h_cond, h_meal, h_exercise, h_notes
                    )
                    st.success("チェックイン完了！今日も頑張りましょう！")
                    st.rerun()

    # ================================================================
    # Tab 6: マイ成長グラフ
    # ================================================================
    with tab6:
        st.header("📊 マイ成長グラフ")

        checkins = db_utils.get_client_health_checkins(client_id, limit=60)
        if not checkins.empty and len(checkins) >= 2:
            checkins['date'] = pd.to_datetime(checkins['date'])
            checkins = checkins.sort_values('date')

            st.subheader("💤 睡眠時間の推移")
            st.line_chart(checkins.set_index('date')['sleep_hours'])

            st.subheader("😊 体調スコアの推移")
            st.line_chart(checkins.set_index('date')['condition_score'])

            st.divider()
            st.subheader("📊 統計サマリー")
            sm1, sm2 = st.columns(2)
            avg_sleep = checkins['sleep_hours'].mean()
            avg_cond = checkins['condition_score'].mean()
            sm1.metric("平均睡眠時間", f"{avg_sleep:.1f}時間")
            sm2.metric("平均体調スコア", f"{avg_cond:.1f} / 5.0")

            checkin_count = len(checkins)
            sm1.metric("チェックイン回数", f"{checkin_count}回")

            # Learning count
            logs = db_utils.get_client_learning_log(client_id)
            sm2.metric("学習記録数", f"{len(logs)}件")
        else:
            st.info("チェックインデータが2日分以上たまるとグラフが表示されます。毎日チェックインしましょう！")

            # Show summary stats even with limited data
            logs = db_utils.get_client_learning_log(client_id)
            st.subheader("📋 活動サマリー")
            st.metric("学習記録数", f"{len(logs)}件")
            st.metric("チェックイン回数", f"{len(checkins)}回")

# --- Main App Entry ---
if check_password():
    user = st.session_state["user_info"]
    
    # API Keys: 環境変数から自動読み込み（社員には非表示）
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    client = OpenAI(api_key=openai_key) if openai_key else None
    # Gemini API Key は notebooklm_helper 内で os.environ から自動取得
    
    if st.sidebar.button("ログアウト"):
        st.session_state["logged_in"] = False
        st.rerun()
    
    # Routing based on Role
    login_role = st.session_state.get("login_role", "staff")
    if login_role == "client":
        client_dashboard()
    elif login_role == "manager":
        manager_dashboard(user, client)
    else:
        staff_dashboard(user, client)


