import streamlit as st
import sqlite3
import random
import re
import time
import requests
from pathlib import Path
import pypdf
from deep_translator import GoogleTranslator

DB_FILE = "vocab_app.db"
PDF_FILES = ["American_Oxford_3000.pdf", "American_Oxford_5000.pdf"]

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS oxford_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            definition TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_words (
            word TEXT UNIQUE NOT NULL,
            definition TEXT,
            familiarity INTEGER DEFAULT 1
        )
    """)

    cursor.execute("PRAGMA table_info(user_words)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'familiarity' not in columns:
        cursor.execute("ALTER TABLE user_words ADD COLUMN familiarity INTEGER DEFAULT 1")

    conn.commit()
    conn.close()

def extract_words_from_pdf(pdf_path):
    reader = pypdf.PdfReader(pdf_path)
    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    full_text = re.sub(r'Oxford University Press.*', '', full_text)
    full_text = re.sub(r'The Oxford \d+.*', '', full_text)
    full_text = re.sub(r'\d+/\d+', '', full_text)

    pattern = re.compile(r'([a-zA-Z\s\-\'/]+?)\s+((?:adj\.|adv\.|v\.|n\.|prep\.|conj\.|pron\.|exclam\.|det\.|number|modal v\.|auxiliary v\.)?.*?)(A1|A2|B1|B2|C1)')
    matches = pattern.findall(full_text)

    extracted_words = []
    for word_part, pos_part, level in matches:
        word = word_part.strip().lower()
        word = re.sub(r'\d+', '', word).strip()
        pos = pos_part.strip()
        definition = f"[{pos}] ({level})" if pos else f"({level})"
        if word and len(word) > 1:
            extracted_words.append((word, definition))

    return extracted_words

def load_oxford_to_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM oxford_words")
    if cursor.fetchone()[0] == 0:
        for pdf_name in PDF_FILES:
            pdf_path = Path(pdf_name)
            if pdf_path.exists():
                words = extract_words_from_pdf(pdf_path)
                for word, defn in words:
                    try:
                        cursor.execute("INSERT OR IGNORE INTO oxford_words (word, definition) VALUES (?, ?)", (word, defn))
                    except sqlite3.Error:
                        pass
        conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_FILE)

@st.cache_data(show_spinner=False)
def get_translation(word):
    try:
        time.sleep(0.05)
        translated = GoogleTranslator(source='auto', target='zh-TW').translate(word)
        if translated and "<html" not in translated.lower():
            return translated
    except Exception:
        pass
    return "查無翻譯"

def evaluate_sentence_ai(target_word, user_sentence):
    sentence = user_sentence.strip()
    if not sentence:
        return {"passed": False, "score": 0, "feedback": "⚠️ 內容不能為空，請輸入句子！", "delta": 0}
    
    pattern = re.compile(re.escape(target_word) + r'(s|es|d|ed|ing)?', re.IGNORECASE)
    if not pattern.search(sentence):
        return {
            "passed": False,
            "score": 0,
            "feedback": f"❌ 你的句子中沒有包含單字 **{target_word}**（或其變化型），請重新調整！",
            "delta": -1
        }
    
    try:
        response = requests.post(
            "https://api.languagetool.org/v2/check",
            data={"text": sentence, "language": "en-US"},
            timeout=5
        )
        data = response.json()
        matches = data.get("matches", [])
        
        critical_errors = [m for m in matches if m.get("rule", {}).get("issueType") in ["misspelling", "grammar"]]
        
        if len(critical_errors) == 0:
            return {
                "passed": True,
                "score": 100,
                "feedback": f"🎉 **太棒了！造句非常道地且文法完全正確！**\n\n- **句子**：*{sentence}*\n- **評語**：成功靈活運用了單字 `{target_word}`！",
                "delta": 2
            }
        else:
            suggestions = []
            for err in critical_errors[:2]:
                msg = err.get("message", "文法疑慮")
                repl = [r["value"] for r in err.get("replacements", [])[:2]]
                sugg_str = f"👉 **{msg}**" + (f"（建議改為：`{', '.join(repl)}`）" if repl else "")
                suggestions.append(sugg_str)
            
            sugg_text = "\n".join(suggestions)
            return {
                "passed": False,
                "score": 60,
                "feedback": f"⚠️ **單字使用正確，但文法有些小瑕疵：**\n\n{sugg_text}\n\n- 再調整一下句子讓表達更完美吧！",
                "delta": -1
            }
            
    except Exception:
        words_count = len(sentence.split())
        if words_count >= 4:
            return {
                "passed": True,
                "score": 85,
                "feedback": f"✅ **造句成功！** 已成功將 **{target_word}** 融入句子中。",
                "delta": 1
            }
        else:
            return {
                "passed": False,
                "score": 40,
                "feedback": "⚠️ 句子太短了，請試著寫出一個更完整有意義的句子！",
                "delta": -1
            }

st.set_page_config(page_title="英文單字學習助手", page_icon="📖", layout="centered")
st.markdown("""
<style>
.element-container a.anchor-link { display: none !important; }
a[data-testid="stHeaderActionElements"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

init_db()
load_oxford_to_db()

st.title("📖 英文單字學習助手")

menu = st.sidebar.radio("功能選單", [
    "🎯 牛津5000 隨機測驗",
    "✍️ AI 英文造句特訓",
    "🎴 個人單字卡複習",
    "📗 牛津完整字詞庫",
    "➕ 手動新增個人單字",
    "📚 查看個人單字庫"
])

# ================= 1. 牛津5000 隨機測驗 =================
if menu == "🎯 牛津5000 隨機測驗":
    st.subheader("🎯 牛津5000 單字辨識測試")
    st.write("測試你是否認識這些單字。點擊 **「認識」** 會把單字加入你的個人單字庫！")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT word, definition FROM oxford_words")
    all_oxford = cursor.fetchall()
    conn.close()

    if not all_oxford:
        st.warning("⚠️ 尚未找到牛津單字庫資料，請確認 PDF 檔案位置！")
    else:
        if "test_item" not in st.session_state:
            st.session_state.test_item = random.choice(all_oxford)
            st.session_state.show_ans = False

        current_w, current_def = st.session_state.test_item

        st.info(f"### ❓ 你認識這個單字嗎？\n## **{current_w}**")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("✅ 認識 (加入個人庫)", use_container_width=True):
                chinese_meaning = get_translation(current_w)
                full_def = f"{chinese_meaning} {current_def}"
                conn = get_db()
                cursor = conn.cursor()
                try:
                    cursor.execute("INSERT INTO user_words (word, definition, familiarity) VALUES (?, ?, 1)", (current_w, full_def))
                    conn.commit()
                    st.success(f"已將『{current_w} ({chinese_meaning})』加入個人單字庫！")
                except sqlite3.IntegrityError:
                    st.warning(f"『{current_w}』已經在你的個人單字庫中囉！")
                conn.close()
                st.session_state.test_item = random.choice(all_oxford)
                st.session_state.show_ans = False
                st.rerun()

        with col2:
            if st.button("❌ 不認識 (跳過)", use_container_width=True):
                st.session_state.test_item = random.choice(all_oxford)
                st.session_state.show_ans = False
                st.rerun()

        with col3:
            if st.button("👀 看答案", use_container_width=True):
                st.session_state.show_ans = True

        if st.session_state.get("show_ans", False):
            chinese_translation = get_translation(current_w)
            cambridge_url = f"https://dictionary.cambridge.org/dictionary/english/{current_w}"
            st.markdown(f"""
            ---
            💡 **中文翻譯**：`{chinese_translation}`  
            🏷️ **詞性與等級**：`{current_def}`  
            🔗 **線上查字典**：[{current_w} 在 Cambridge Dictionary]({cambridge_url})
            """)

# ================= 2. ✍️ AI 英文造句特訓 =================
elif menu == "✍️ AI 英文造句特訓":
    st.subheader("✍️ AI 英文造句實戰特訓")
    st.write("從你的個人單字庫隨機抽出一個單字，請嘗試用它造一個完整的英文句子！AI 將會即時為你的句子提供建議並調整熟悉度。")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rowid, word, definition, familiarity FROM user_words")
    user_words = cursor.fetchall()
    conn.close()

    if not user_words:
        st.info("💡 你的個人單字庫目前是空的！請先至「🎯 牛津5000 隨機測驗」按下『認識』加入單字。")
    else:
        if "sentence_item" not in st.session_state:
            st.session_state.sentence_item = random.choice(user_words)
            st.session_state.eval_result = None

        w_rowid, target_word, target_def, fam = st.session_state.sentence_item

        st.markdown("---")
        st.markdown(f"### 🎯 請用單字： **`{target_word}`** 造句")
        st.caption(f"📖 單字釋義：{target_def} ｜ ⭐ 目前熟悉度：`{fam}`")

        # 使用乾淨且不具誤導性的提示文字
        clean_placeholder = f"請在此輸入包含 『{target_word}』 的完整英文句子..."

        with st.form(key="sentence_form"):
            user_sentence = st.text_area("請輸入你造的英文句子：", placeholder=clean_placeholder, key="user_sent_input")
            submit_sent_btn = st.form_submit_button("🤖 提交給 AI 批改評價", use_container_width=True)

            if submit_sent_btn:
                with st.spinner("AI 正在審查你的造句與文法..."):
                    eval_data = evaluate_sentence_ai(target_word, user_sentence)
                    st.session_state.eval_result = eval_data
                    
                    delta = eval_data["delta"]
                    new_fam = max(0, fam + delta)
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE user_words SET familiarity = ? WHERE rowid = ?", (new_fam, w_rowid))
                    conn.commit()
                    conn.close()
                    st.session_state.sentence_item = (w_rowid, target_word, target_def, new_fam)

        if st.session_state.get("eval_result"):
            res = st.session_state.eval_result
            st.markdown("---")
            if res["passed"]:
                st.success(res["feedback"])
                st.info(f"📈 熟悉度變動：**+{res['delta']}** （最新熟悉度：`{st.session_state.sentence_item[3]}`）")
            else:
                st.error(res["feedback"])
                st.warning(f"📉 熟悉度變動：**{res['delta']}** （最新熟悉度：`{st.session_state.sentence_item[3]}`）")

        st.markdown("---")
        if st.button("➡️ 下一個單字", use_container_width=True):
            st.session_state.sentence_item = random.choice(user_words)
            st.session_state.eval_result = None
            st.rerun()

# ================= 3. 🎴 個人單字卡複習 =================
elif menu == "🎴 個人單字卡複習":
    st.subheader("🎴 個人單字卡複習")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rowid, word, definition, familiarity FROM user_words ORDER BY familiarity ASC")
    words = cursor.fetchall()
    conn.close()

    if not words:
        st.info("💡 你的個人單字庫目前是空的！請先至「🎯 牛津5000 隨機測驗」按下『認識』加入單字。")
    else:
        if "card_index" not in st.session_state:
            st.session_state.card_index = 0

        if st.session_state.card_index >= len(words):
            st.session_state.card_index = 0

        w_rowid, word, defn, fam = words[st.session_state.card_index]

        st.info(f"### 🎴 單字 ({st.session_state.card_index + 1}/{len(words)})：**{word}**")
        
        with st.expander("👉 點擊翻卡查看解釋 / 熟悉度"):
            st.write(f"**詳細釋義**：{defn}")
            st.write(f"**目前熟悉度**：`{fam}`")
            cambridge_url = f"https://dictionary.cambridge.org/dictionary/english/{word}"
            st.markdown(f"🔗 [查看 Cambridge 字典]({cambridge_url})")

        st.markdown("---")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("✅ 記得 (熟悉度 +1)", use_container_width=True):
                new_fam = fam + 1
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("UPDATE user_words SET familiarity = ? WHERE rowid = ?", (new_fam, w_rowid))
                conn.commit()
                conn.close()
                st.toast(f"『{word}』熟悉度提升至 {new_fam}！", icon="🎉")
                st.session_state.card_index = (st.session_state.card_index + 1) % len(words)
                st.rerun()

        with col2:
            if st.button("❌ 不知道 (熟悉度 -1)", use_container_width=True):
                new_fam = max(0, fam - 1)
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("UPDATE user_words SET familiarity = ? WHERE rowid = ?", (new_fam, w_rowid))
                conn.commit()
                conn.close()
                st.toast(f"『{word}』熟悉度降至 {new_fam}", icon="💪")
                st.session_state.card_index = (st.session_state.card_index + 1) % len(words)
                st.rerun()

        with col3:
            if st.button("🎲 隨機換單字", use_container_width=True):
                st.session_state.card_index = random.randint(0, len(words) - 1)
                st.rerun()

# ================= 4. 牛津完整字詞庫 =================
elif menu == "📗 牛津完整字詞庫":
    st.subheader("📗 牛津 3000 / 5000 完整字詞庫")
    search_kw = st.text_input("🔍 搜尋牛津詞庫")
    conn = get_db()
    cursor = conn.cursor()
    if search_kw:
        cursor.execute("SELECT word, definition FROM oxford_words WHERE word LIKE ? ORDER BY word ASC", (f"%{search_kw.lower()}%",))
    else:
        cursor.execute("SELECT word, definition FROM oxford_words ORDER BY word ASC LIMIT 200")
    rows = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM oxford_words")
    total_count = cursor.fetchone()[0]
    conn.close()
    st.caption(f"牛津總詞庫共收錄 **{total_count}** 個單字：")
    st.dataframe(rows, column_config={"0": "英文單字", "1": "詞性 / 等級"}, use_container_width=True)

# ================= 5. 手動新增個人單字 =================
elif menu == "➕ 手動新增個人單字":
    st.subheader("➕ 手動新增單字至個人庫")
    word = st.text_input("英文單字")
    definition = st.text_input("中文解釋 / 備註")
    if st.button("儲存到個人單字庫"):
        if word and definition:
            conn = get_db()
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO user_words (word, definition, familiarity) VALUES (?, ?, 1)", (word.strip().lower(), definition.strip()))
                conn.commit()
                st.success(f"已成功新增：{word}")
            except sqlite3.IntegrityError:
                st.warning("這個單字已經在個人單字庫中了！")
            conn.close()
        else:
            st.error("請完整輸入單字與解釋！")

# ================= 6. 查看個人單字庫 =================
elif menu == "📚 查看個人單字庫":
    st.subheader("📚 我的個人單字庫")
    search_kw = st.text_input("🔍 搜尋我的單字")
    conn = get_db()
    cursor = conn.cursor()
    if search_kw:
        cursor.execute("SELECT word, definition, familiarity FROM user_words WHERE word LIKE ?", (f"%{search_kw.lower()}%",))
    else:
        cursor.execute("SELECT word, definition, familiarity FROM user_words ORDER BY word ASC")
    rows = cursor.fetchall()
    conn.close()
    if rows:
        st.write(f"你目前已收藏 **{len(rows)}** 個單字：")
        st.dataframe(rows, column_config={"0": "單字", "1": "解釋", "2": "熟悉度"}, use_container_width=True)
        
        st.markdown("---")
        st.caption("🗑️ 若想從個人庫移除單字：")
        del_word = st.text_input("輸入要刪除的英文單字")
        if st.button("刪除此單字"):
            if del_word:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user_words WHERE word = ?", (del_word.strip().lower(),))
                conn.commit()
                conn.close()
                st.success(f"已將『{del_word}』從個人單字庫移除！")
                st.rerun()
    else:
        st.write("目前個人單字庫還沒有資料喔！")
