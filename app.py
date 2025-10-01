import os
import sqlite3
import json
import re
import concurrent.futures
import time
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from googleapiclient.discovery import build
import yt_dlp
import openai
from dotenv import load_dotenv
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# .env 파일 로드
load_dotenv()

# --- 설정 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "recipes.db")

# API 키 검증
if not OPENAI_API_KEY or not YOUTUBE_API_KEY:
    logger.error("API 키가 설정되지 않았습니다. .env 파일을 확인하세요.")
    raise ValueError("API keys not configured")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

# --- 데이터베이스 함수 ---
def get_db_connection():
    """데이터베이스 연결"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """데이터베이스 초기화"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            ingredients TEXT,
            dish_name TEXT,
            url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 인덱스 추가로 검색 속도 향상
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ingredients 
        ON recipes(ingredients)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_video_id 
        ON recipes(video_id)
    """)
    conn.commit()
    conn.close()
    logger.info("데이터베이스 초기화 완료")

def check_if_video_exists(video_id):
    """비디오 중복 체크"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipes WHERE video_id = ?", (video_id,))
    exists = cursor.fetchone()[0] > 0
    conn.close()
    return exists

# --- YouTube 함수 ---
def get_playlist_items(playlist_id):
    """플레이리스트의 모든 비디오 ID 가져오기"""
    video_ids = []
    next_page_token = None
    
    try:
        while True:
            request = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()
            
            for item in response["items"]:
                if 'contentDetails' in item and 'videoId' in item['contentDetails']:
                    video_ids.append(item["contentDetails"]["videoId"])
            
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
                
        logger.info(f"플레이리스트 {playlist_id}에서 {len(video_ids)}개의 영상 발견")
        return video_ids
    except Exception as e:
        logger.error(f"플레이리스트 가져오기 실패: {e}")
        return []

def get_video_info(video_id):
    """비디오 정보 가져오기"""
    try:
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()
        
        if not response["items"]:
            logger.warning(f"비디오 {video_id} 정보를 찾을 수 없음")
            return None
        
        video = response["items"][0]
        return {
            'title': video["snippet"]["title"],
            'description': video["snippet"]["description"],
            'url': f"https://www.youtube.com/watch?v={video_id}"
        }
    except Exception as e:
        logger.error(f"비디오 정보 가져오기 실패 ({video_id}): {e}")
        return None

# --- 오디오 처리 함수 ---
def download_audio(video_url, video_id, max_retries=3):
    """YouTube 오디오 다운로드"""
    retries = 0
    
    while retries < max_retries:
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{video_id}.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',  # 품질 낮춰서 속도 향상
                }],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                audio_file = downloaded_file.rsplit('.', 1)[0] + '.mp3'
                return audio_file
                
        except Exception as e:
            retries += 1
            if retries < max_retries:
                logger.warning(f"다운로드 재시도 {retries}/{max_retries}: {e}")
                time.sleep(5)
            else:
                logger.error(f"다운로드 실패: {e}")
                raise
    
    return None

def transcribe_audio(file_path):
    """Whisper API로 오디오 변환"""
    try:
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ko"
            )
        return transcript.text
    except Exception as e:
        logger.error(f"Whisper 변환 실패: {e}")
        raise

# --- LLM 함수 ---
def extract_recipe_info(transcript, title):
    """LLM으로 레시피 정보 추출"""
    prompt = f"""다음은 요리 영상 대본입니다. 요리 이름과 재료를 추출하세요.

규칙:
1. 요리 이름은 간단명료하게
2. 재료는 쉼표로만 구분, 공백 없이
3. 기본 조미료(소금,후추,식용유 등)도 포함

대본: {transcript[:1500]}

다음 형식으로만 응답:
{{"dish_name": "요리이름", "ingredients": "재료1,재료2,재료3"}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a recipe extraction assistant. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.1
        )
        
        result = response.choices[0].message.content.strip()
        
        # JSON 정리
        result = re.sub(r'^```json?\s*', '', result)
        result = re.sub(r'\s*```$', '', result)
        
        data = json.loads(result)
        dish_name = data.get('dish_name', title)
        ingredients = data.get('ingredients', '')
        
        if isinstance(ingredients, list):
            ingredients = ','.join(ingredients)
        
        # 재료 정리
        ingredients = re.sub(r'\s+', '', ingredients)
        ingredients = re.sub(r',+', ',', ingredients)
        
        return dish_name, ingredients
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패: {e}, 응답: {result[:200]}")
        return title, ""
    except Exception as e:
        logger.error(f"LLM 추출 실패: {e}")
        return title, ""

def extract_from_description(description, title):
    """설명에서 재료 추출 (폴백 방법)"""
    if "재료" in description:
        start_idx = description.find("재료") + len("재료")
        end_idx = description.find("만드는", start_idx)
        if end_idx == -1:
            end_idx = start_idx + 500
        
        ingredients = description[start_idx:end_idx].strip()
        ingredients = re.sub(r'[-\s\n]+', ',', ingredients)
        ingredients = re.sub(r'[^\w가-힣,]', '', ingredients)
        return title, ingredients
    
    return title, ""

# --- 메인 처리 함수 ---
def process_single_video(video_id):
    """단일 비디오 처리"""
    
    # 중복 체크
    if check_if_video_exists(video_id):
        logger.info(f"[{video_id}] 이미 처리됨, 건너뜀")
        return {"status": "skipped", "video_id": video_id}
    
    try:
        # 1. 비디오 정보 가져오기
        video_info = get_video_info(video_id)
        if not video_info:
            return {"status": "error", "video_id": video_id, "message": "비디오 정보 없음"}
        
        title = video_info['title']
        description = video_info['description']
        video_url = video_info['url']
        
        logger.info(f"처리 시작: {title}")
        
        # 2. 오디오 다운로드 및 변환
        try:
            audio_file = download_audio(video_url, video_id)
            transcript = transcribe_audio(audio_file)
            
            # 3. LLM으로 정보 추출
            dish_name, ingredients = extract_recipe_info(transcript, title)
            
            # 임시 파일 삭제
            if os.path.exists(audio_file):
                os.remove(audio_file)
            original_file = audio_file.rsplit('.', 1)[0]
            for ext in ['.webm', '.m4a', '.opus']:
                if os.path.exists(original_file + ext):
                    os.remove(original_file + ext)
                    
        except Exception as e:
            logger.warning(f"오디오 처리 실패, 설명에서 추출 시도: {e}")
            dish_name, ingredients = extract_from_description(description, title)
        
        # 4. DB 저장
        if not ingredients:
            logger.warning(f"재료 추출 실패: {title}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO recipes (video_id, title, description, ingredients, dish_name, url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (video_id, title, description, ingredients, dish_name, video_url))
        conn.commit()
        conn.close()
        
        logger.info(f"저장 완료: {title} | 재료: {ingredients[:50]}...")
        return {
            "status": "success",
            "video_id": video_id,
            "title": title,
            "dish_name": dish_name
        }
        
    except Exception as e:
        logger.error(f"비디오 처리 실패 ({video_id}): {e}")
        return {"status": "error", "video_id": video_id, "message": str(e)}

# --- Flask 라우트 ---
@app.route('/')
def index():
    """메인 페이지"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipes")
    count = cursor.fetchone()[0]
    conn.close()
    
    return f'''
        <!DOCTYPE html>
        <html lang="ko">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>레시피 추출 시스템</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                h1 {{
                    color: #333;
                    text-align: center;
                }}
                .stats {{
                    background: #e3f2fd;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                    text-align: center;
                }}
                input[type="text"] {{
                    width: 100%;
                    padding: 12px;
                    margin: 10px 0;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    box-sizing: border-box;
                }}
                button {{
                    width: 100%;
                    padding: 12px;
                    background: #1976d2;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 16px;
                }}
                button:hover {{
                    background: #1565c0;
                }}
                .link {{
                    display: block;
                    text-align: center;
                    margin-top: 20px;
                    color: #1976d2;
                    text-decoration: none;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🍳 유튜브 레시피 추출 시스템</h1>
                <div class="stats">
                    <strong>현재 데이터베이스: {count}개의 레시피</strong>
                </div>
                <form method="post" action="/process">
                    <label for="playlist_url">플레이리스트 URL:</label>
                    <input type="text" id="playlist_url" name="playlist_url" 
                           placeholder="https://www.youtube.com/playlist?list=..." required>
                    <button type="submit">영상 처리 시작</button>
                </form>
                <a href="/recommend" class="link">📋 레시피 추천받기</a>
            </div>
        </body>
        </html>
    '''

@app.route('/process', methods=['POST'])
def process_playlist():
    """플레이리스트 처리"""
    playlist_url = request.form.get('playlist_url')
    
    if not playlist_url:
        return "플레이리스트 URL을 입력하세요.", 400
    
    match = re.search(r'list=([a-zA-Z0-9_-]+)', playlist_url)
    if not match:
        return "유효하지 않은 플레이리스트 URL입니다.", 400
    
    playlist_id = match.group(1)
    return redirect(url_for('process_playlist_manual', playlist_id=playlist_id))

@app.route('/process_playlist/<playlist_id>')
def process_playlist_manual(playlist_id):
    """플레이리스트 처리 실행"""
    video_ids = get_playlist_items(playlist_id)
    
    if not video_ids:
        return "플레이리스트를 불러올 수 없습니다.", 400
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_single_video, vid) for vid in video_ids]
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"처리 중 예외: {e}")
    
    success_count = sum(1 for r in results if r.get('status') == 'success')
    skipped_count = sum(1 for r in results if r.get('status') == 'skipped')
    error_count = sum(1 for r in results if r.get('status') == 'error')
    
    return f'''
        <h1>처리 완료!</h1>
        <p>성공: {success_count}개</p>
        <p>건너뜀: {skipped_count}개</p>
        <p>실패: {error_count}개</p>
        <br>
        <a href="/recommend">레시피 추천받기</a> | <a href="/">홈으로</a>
    '''

@app.route('/recommend')
def recommend_page():
    """추천 페이지"""
    return render_template('recommend.html')

@app.route('/recommend', methods=['POST'])
def recommend_recipe():
    """레시피 추천"""
    user_ingredients_input = request.form.get('ingredients', '')
    
    if not user_ingredients_input:
        return render_template('recommend.html', message="재료를 입력해주세요.")
    
    # 재료 파싱
    user_ingredients = set(i.strip() for i in user_ingredients_input.split(',') if i.strip())
    
    # DB 검색
    conn = get_db_connection()
    cursor = conn.cursor()
    
    conditions = " OR ".join(["ingredients LIKE ?" for _ in user_ingredients])
    values = [f"%{ing}%" for ing in user_ingredients]
    
    query = f"SELECT * FROM recipes WHERE {conditions}"
    cursor.execute(query, values)
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        return render_template('recommend.html', 
                             message="해당 재료로 만들 수 있는 레시피를 찾을 수 없습니다.")
    
    # 매칭률 계산
    recipes = []
    for row in results:
        recipe_ings = set(i.strip() for i in row['ingredients'].split(',') if i.strip())
        matched = user_ingredients & recipe_ings
        missing = recipe_ings - user_ingredients
        
        match_rate = (len(matched) / len(recipe_ings) * 100) if recipe_ings else 0
        
        recipes.append({
            'title': row['title'],
            'url': row['url'],
            'dish_name': row['dish_name'],
            'match_rate': f"{match_rate:.1f}",
            'matched': ', '.join(matched),
            'missing': ', '.join(missing),
            'all_ingredients': ', '.join(recipe_ings)
        })
    
    recipes.sort(key=lambda x: float(x['match_rate']), reverse=True)
    
    return render_template('recommend.html', 
                         recipes=recipes, 
                         user_ingredients=user_ingredients_input)

@app.route('/api/stats')
def api_stats():
    """통계 API"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM recipes")
    total = cursor.fetchone()[0]
    conn.close()
    
    return jsonify({"total_recipes": total})

# --- 메인 실행 ---
if __name__ == '__main__':
    init_database()
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "True").lower() == "true"
    app.run(host='0.0.0.0', port=port, debug=debug)