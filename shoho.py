import streamlit as st
import requests
import json
import re
from openai import OpenAI
from dotenv import load_dotenv
import os

# === APIキー読み込み ===
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EDAMAM_APP_ID = os.getenv("EDAMAM_APP_ID")
EDAMAM_APP_KEY = os.getenv("EDAMAM_APP_KEY")

if not OPENAI_API_KEY or not EDAMAM_APP_ID or not EDAMAM_APP_KEY:
    st.error(".env から APIキーを読み込めませんでした。設定を確認してください。")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

# --- JSON安全パーサ ---
def safe_json_parse(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text)
        text = text.replace("```", "").strip()
    if not text.endswith("}"):
        text += "}"
    return json.loads(text)

# --- 追加質問生成関数 ---
def run_gpt():
    base_info = f"ユーザは現在「{', '.join(st.session_state.symptoms)}」の症状があり、自由記述では「{st.session_state.free_text}」と述べています。"
    qa_history = ""
    for i, (q, a) in enumerate(zip(st.session_state.questions, st.session_state.answers)):
        qa_history += f"\n質問{i+1}: {q}\n回答{i+1}: {a}"

    prompt = f"""
あなたは優秀な医師です。
{base_info}

これまでの質問と回答:
{qa_history}

病名を診断するために必要な追加質問を**1つだけ**考えてください。
- 出力は質問文のみ
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return res.choices[0].message.content.strip()

# --- 症状 → 栄養素・食べ物診断 ---
def diagnose_food(symptom):
    prompt = f"""
ユーザの症状: {symptom}

ユーザの症状から最もユーザがかかっている可能性の高い病気を診断してください。
必要な栄養素とそれらの栄養素が含まれている代表的な食材を下記の条件に従って1つ特定してください。
**条件:**
- 必ず有効なJSON形式のみで返してください
- 食材(foods)は必ず英語で記述してください
- 診断（diagnosis）と栄養素（nutrient）は日本語で記述してください
- 日本で手に入れやすい食材を優先してください
- フォーマット例:
{{
  "diagnosis": "片頭痛",
  "nutrient": "マグネシウム",
  "foods": ["Almonds", "Spinach"]
}}
"""
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return safe_json_parse(res.choices[0].message.content.strip())

# --- 食材 → レシピ検索 ---
def get_recipes(foods):
    if isinstance(foods, str):
        foods = [foods]
    query = " ".join(foods)
    url = "https://api.edamam.com/api/recipes/v2"
    params = {
        "type": "public",
        "q": query,
        "app_id": EDAMAM_APP_ID,
        "app_key": EDAMAM_APP_KEY,
        "to": 3
    }
    res = requests.get(url, params=params)
    if res.status_code != 200:
        raise ValueError(f"Edamam API Error: {res.status_code}\n{res.text}")
    return res.json().get("hits", [])

# --- 翻訳関数 ---
def translate(text):
    prompt = f"あなたは優秀な翻訳家です。自然な日本語に翻訳してください。翻訳結果のみを返してください:\n{text}"
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return res.choices[0].message.content.strip()

def init_session():
    for key, default in {
    "step": 0,
    "symptoms": [],
    "free_text": "",
    "questions": [],
    "answers": [],
    "user_answers": {}
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

# === セッション初期化 ===
for key, default in {
    "step": 0,
    "symptoms": [],
    "free_text": "",
    "questions": [],
    "answers": [],
    "user_answers": {}
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# === メインタイトル ===
st.markdown(
    """
    <h1 style="font-size:2.5rem; font-weight:700; text-align:center; margin-bottom:1rem;">
        おいしい処方箋
    </h1>
    <p style="text-align:center; font-size:1.1rem; color:gray;">
        症状から原因を分析し、最適な栄養素とレシピをご提案します
    </p>
    """,
    unsafe_allow_html=True
)

symptom_kind_of_to_gpt = [
    "頭痛",
    "腹痛",
    "発熱",
    "咳",
    "倦怠感",
    "吐き気",
    "下痢",
    "めまい",
    "関節痛",
    "筋肉痛",
]

# --- サイドバー: 初期症状入力 ---
if st.session_state.step == 0:
  with st.sidebar:
    st.markdown("### 症状を入力してください")
    st.session_state.symptoms = st.sidebar.pills("症状の種類を選択してください", symptom_kind_of_to_gpt, selection_mode="multi")
    st.session_state.free_text = st.text_area("その他の症状（自由記述）")

    if st.button("診断を開始", use_container_width=True):
        if not st.session_state.symptoms and not st.session_state.free_text:
            st.warning("症状を入力してください。")
        else:
            st.session_state.step = 1
else:
    st.sidebar.header("あなたの申告した症状")
    st.sidebar.write("選択した症状:")
    st.sidebar.write(", ".join(st.session_state.symptoms) if st.session_state.symptoms else "なし")
    st.sidebar.write("その他の症状:")
    st.sidebar.write(st.session_state.free_text if st.session_state.free_text else "なし")


# === 質問フェーズ ===
if 1 <= st.session_state.step <= 3:
    st.markdown("## 診断のための追加質問")

    for q, a in zip(st.session_state.questions, st.session_state.answers):
        st.markdown(f"**医師:** {q}")
        st.markdown(f"**あなた:** {a}")

    if len(st.session_state.questions) < st.session_state.step:
        st.session_state.questions.append(run_gpt())

    current_q = st.session_state.questions[-1]
    st.markdown(f"#### {current_q}")

    # 入力値を session_state に保存して、再実行でも消えないようにする
    user_key = f"answer_{st.session_state.step}"
    st.session_state.user_answers[user_key] = st.text_input("あなたの回答", key=user_key, value=st.session_state.user_answers.get(user_key, ""))

    if st.button("送信", key=f"send_{st.session_state.step}"):
        user_answer = st.session_state.user_answers[user_key].strip()
        if not user_answer:
            st.warning("回答を入力してください。")
        else:
            st.session_state.answers.append(user_answer)
            st.session_state.step += 1

# === 診断結果フェーズ ===
if st.session_state.step == 4:
    st.markdown("## 診断結果")

    combined_symptom = (
        "、".join(st.session_state.symptoms)
        + "。自由記述: "
        + st.session_state.free_text
        + "。追加情報: "
        + " ".join(st.session_state.answers)
    )

    try:
        result = diagnose_food(combined_symptom)
        jp_foods = [translate(f) for f in result["foods"]]

        st.markdown("### 推定病名")
        st.markdown(f"<div style='font-size:1.4rem; font-weight:bold; color:#333;'>{result['diagnosis']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='color:gray;'>※これは医療診断ではありません。あくまで参考情報としてください</div>", unsafe_allow_html=True)        

        st.markdown("### 必要な栄養素")
        st.markdown(f"<div style='font-size:1.2rem;'>{result['nutrient']}</div>", unsafe_allow_html=True)

        st.markdown("### おすすめ食材")
        st.markdown(", ".join(jp_foods))

        #リセットボタン
        # if st.button("再診断する。"):
        #   print("デバック00")
        #   init_session()
        #   print("デバック01")
        #   #ページを再実行
        #   st.rerun()
        #   print("デバック02")

        # レシピ検索処理
        st.markdown("---")
        st.markdown("## レシピ提案")

        recipes = get_recipes(result["foods"])
        if not recipes:
            st.info("該当するレシピが見つかりませんでした。")
        else:
            for i, r in enumerate(recipes[:5]):
                recipe = r["recipe"]
                title = translate(recipe["label"])
                ingredients = translate(", ".join(recipe["ingredientLines"]))
                with st.container():
                    st.markdown(f"### {title}")
                    st.image(recipe["image"], width=300)
                    st.markdown(f"**材料:** {ingredients}")
                    st.markdown(f"[レシピを見る]({recipe['url']})")

    except ValueError as e:
        st.error(str(e))