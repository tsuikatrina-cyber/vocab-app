import streamlit as st
import sqlite3
import random
import re
from pathlib import Path
import pypdf
from deep_translator import GoogleTranslator

DB_FILE = "vocab_app.db"
PDF_FILES = ["American_Oxford_3000.pdf", "American_Oxford_5000.pdf"]

def init_db():
    """初始化資料表，自動補齊舊資料庫缺少的欄位"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 牛津總詞庫
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS oxford_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            definition TEXT
        )
    """)
    
    # 個人單字庫
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_words (
            word TEXT UNIQUE NOT NULL,
            definition TEXT,
            familiarity INTEGER DEFAULT 1
        )
    """)

    # 檢查並補齊 familiarity 欄位
    cursor.execute("PRAGMA table_info(user_words)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'familiarity' not in columns:
        cursor.execute("ALTER TABLE user_words ADD COLUMN familiarity INTEGER DEFAULT 1")

    conn.commit()
    conn.close()

def extract_words_from_pdf(pdf_path):
    """PDF 單字解析器"""
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

@st.cache_data
def get_translation(word):
    """即時線上中文翻譯"""
    try:
        translated = GoogleTranslator(source='auto', target='zh-TW').translate(word)
        return translated
    except Exception:
        return "暫無翻譯"

# 頁面配置與隱藏錨點圖示
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

# 側邊欄選單
menu = st.sidebar.radio("功能選單", [
    "🎯 牛津5000 隨機測驗",
    "📗 牛津完整字詞庫",
    "🎴 個人單字卡複習",
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

# ================= 2. 牛津完整字詞庫 =================
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

# ================= 3. 個人單字卡複習 (改用 rowid，徹底解決報錯) =================
elif menu == "🎴 個人單字卡複習":
    st.subheader("🎴 個人單字卡複習")
    
    conn = get_db()
    cursor = conn.cursor()
    # 使用 SQLite 的隱藏內建主鍵 rowid，不論有沒有 id 欄位都 100% 支援
    cursor.execute("SELECT rowid, word, definition, familiarity FROM user_words ORDER BY familiarity ASC")
    words = cursor.fetchall()
    conn.close()

    if not words:
        st.info("💡 你的個人單字庫目前是空的！請先至「🎯 牛津5000 隨機測驗」按下『認識』，或透過「➕ 手動新增個人單字」加入單字。")
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

# ================= 4. 手動新增個人單字 =================
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

# ================= 5. 查看個人單字庫 =================
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
    else:
        st.write("目前個人單字庫還沒有資料喔！")