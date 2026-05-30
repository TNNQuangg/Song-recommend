import sqlite3
import pandas as pd
import pickle
import __main__
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
from KNN import recommend_from_recent_songs as recommend_songs
from rs_2 import Recommendation_System

#TẢI DỮ LIỆU & MÔ HÌNH
print("Đang nạp dữ liệu và mô hình... Vui lòng đợi...")
track_df = pd.read_csv("Music Info.csv") 

try:
    __main__.Recommendation_System = Recommendation_System
    with open("als12_model.pkl", 'rb') as f:
        als_model = pickle.load(f)
    print("Nạp mô hình ALS thành công!")
except FileNotFoundError:
    print("CẢNH BÁO: Không tìm thấy file train")
    als_model = None

print("Đang tính toán Top Thịnh Hành...")
TOP_5_POPULAR_TRACKS = []
try:
    temp_conn = sqlite3.connect('music_app.db')
    temp_conn.row_factory = sqlite3.Row
    popular_query = """
        SELECT t.track_id, t.name, t.artist, SUM(lh.playcount) as total_plays
        FROM tracks t
        JOIN listening_history lh ON t.track_id = lh.track_id
        GROUP BY t.track_id
        ORDER BY total_plays DESC
        LIMIT 5
    """
    TOP_5_POPULAR_TRACKS = [dict(row) for row in temp_conn.execute(popular_query).fetchall()]
    temp_conn.close()
    print("Đã lưu Cache Top 5 thành công!")

except Exception as e:
    print(f"CẢNH BÁO: Không thể tải Top Thịnh Hành: {e}")
    TOP_5_POPULAR_TRACKS = []

app = FastAPI(title="Music Recommendation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def init_db():
    conn = sqlite3.connect('music_app.db', timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO users (user_id, username, password) VALUES ('USER_QUANG_001', 'quang', '123456')")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username, password) VALUES ('USER_ADMIN_002', 'admin', 'admin')")
    conn.commit()
    conn.close()

init_db()

#HÀM KẾT NỐI DB
def get_db_connection():
    conn = sqlite3.connect('music_app.db', timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

SIMILAR_SEARCH_MESSAGE = "Đang tìm bài hát tương đồng..."


def get_recent_listened_tracks(conn, user_id, limit=5):
    query = """
        SELECT t.track_id, t.name, t.artist
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = ?
        ORDER BY lh.updated_at DESC, lh.rowid DESC
        LIMIT ?
    """
    return conn.execute(query, (user_id, limit)).fetchall()


def find_als_clone_user(conn, local_tracks, blocked_user_ids=None, candidate_limit=200):
    if not als_model or not local_tracks:
        return None

    unique_tracks = list(dict.fromkeys(local_tracks))
    blocked_user_ids = list(dict.fromkeys(blocked_user_ids or []))
    track_placeholders = ",".join(["?"] * len(unique_tracks))
    params = unique_tracks[:]
    blocked_clause = ""

    if blocked_user_ids:
        blocked_placeholders = ",".join(["?"] * len(blocked_user_ids))
        blocked_clause = f"AND user_id NOT IN ({blocked_placeholders})"
        params.extend(blocked_user_ids)

    query = f"""
        SELECT user_id, COUNT(track_id) as matching_score
        FROM listening_history
        WHERE track_id IN ({track_placeholders})
          {blocked_clause}
        GROUP BY user_id
        ORDER BY matching_score DESC
        LIMIT ?
    """
    params.append(candidate_limit)

    for row in conn.execute(query, params).fetchall():
        candidate_user_id = row["user_id"]
        if candidate_user_id in als_model.u_map:
            return candidate_user_id

    return None

#API 1: Lấy lịch sử nghe nhạc
@app.get("/api/v1/users/{user_id}/history")
def get_listening_history(user_id: str):
    conn = get_db_connection()
    query = """
        SELECT t.track_id, t.name, t.artist, t.duration_ms 
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = ?
        ORDER BY lh.updated_at DESC -- Đã sửa thành thời gian mới nhất
        LIMIT 10
    """
    history = conn.execute(query, (user_id,)).fetchall()
    conn.close()
    return {"user_id": user_id, "history": [dict(row) for row in history]}

#API 2: Gợi ý theo lịch sử (ALS)
@app.get("/api/v1/recommendations/history/{user_id}")
def get_history_based_recommendations(user_id: str):
    conn = get_db_connection()
    
    # 1. Lấy danh sách track_id mà Local User đã nghe
    local_history = get_recent_listened_tracks(conn, user_id, limit=150)
    
    local_tracks = [row["track_id"] for row in local_history]
    num_tracks = len(local_tracks)

    # 2. XỬ LÝ COLD START
    if num_tracks <= 5:
        conn.close()
        return {
            "message": f"🔥 Top Thịnh Hành (Nghe thêm {6 - num_tracks} bài để cá nhân hóa)",
            "recommendations": TOP_5_POPULAR_TRACKS
        }

    # 3. TÌM USER TƯƠNG ĐỒNG
    clone_user_id = find_als_clone_user(conn, local_tracks, blocked_user_ids=[user_id])
    conn.close()
    
    if not clone_user_id:
        return {"message": SIMILAR_SEARCH_MESSAGE, "recommendations": []}

    result_df = als_model.recommend_user(u_id=clone_user_id, track_df=track_df)

    if isinstance(result_df, str):                        
        return {"message": SIMILAR_SEARCH_MESSAGE, "recommendations": []}

    result_df = result_df.merge(                         
        track_df[['track_id', 'artist']], on='track_id', how='left'
    )

    return {
        "user_id": user_id,
        "mapped_to_clone": clone_user_id, 
        "message": "Gợi ý dành riêng cho bạn",
        "recommendations": result_df.fillna("").to_dict(orient="records")
    }

#API 3: Gợi ý theo giai điệu (KNN)
@app.get("/api/v1/recommendations/melody/{user_id}")
def get_melody_based_recommendations(user_id: str):
    conn = get_db_connection()
    recent_tracks = get_recent_listened_tracks(conn, user_id, limit=5)
    conn.close()
    
    if not recent_tracks:
        return {"recommendations": [], "message": "Chưa có lịch sử nghe nhạc để gợi ý theo giai điệu."}
    
    recent_songs = [(row["name"], row["artist"]) for row in recent_tracks]
    
    result_df = recommend_songs(recent_songs=recent_songs, top_n=5)
    
    if isinstance(result_df, str): 
        return {"recommendations": [], "message": result_df}
    
    return {
        "seed_tracks": recent_songs,
        "recommendations": result_df.fillna("").to_dict(orient="records")
    }
#API 4: Tìm kiếm
@app.get("/api/v1/search")
def search_tracks(q: str):
    conn = get_db_connection()
    query = "SELECT track_id, name, artist FROM tracks WHERE name LIKE ? OR artist LIKE ? LIMIT 10"
    search_term = f"%{q}%"
    results = conn.execute(query, (search_term, search_term)).fetchall()
    conn.close()
    return {"query": q, "results": [dict(row) for row in results]}

#API 5: Thêm bài hát vào lịch sử
@app.post("/api/v1/users/{user_id}/history/{track_id}")
def add_to_history(user_id: str, track_id: str):
    conn = get_db_connection()
    import datetime
    now = datetime.datetime.now()

    check_query = "SELECT playcount FROM listening_history WHERE user_id = ? AND track_id = ?"
    row = conn.execute(check_query, (user_id, track_id)).fetchone()
    
    if row:
        update_query = "UPDATE listening_history SET playcount = playcount + 1, updated_at = ? WHERE user_id = ? AND track_id = ?"
        conn.execute(update_query, (now, user_id, track_id))
    else:
        insert_query = "INSERT INTO listening_history (user_id, track_id, playcount, updated_at) VALUES (?, ?, 1, ?)"
        conn.execute(insert_query, (user_id, track_id, now))
        
    conn.commit()
    conn.close()
    return {"message": "Đã thêm vào lịch sử"}

#API 6: Xóa toàn bộ lịch sử của User
@app.delete("/api/v1/users/{user_id}/history/clear")
def clear_user_history(user_id: str):
    conn = get_db_connection()
    cursor = conn.execute("DELETE FROM listening_history WHERE user_id = ?", (user_id,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return {"message": "Đã xóa toàn bộ lịch sử", "deleted_count": deleted_count}

#API 7: Xóa bài hát khỏi lịch sử
@app.delete("/api/v1/users/{user_id}/history/{track_id}")
def remove_from_history(user_id: str, track_id: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM listening_history WHERE user_id = ? AND track_id = ?", (user_id, track_id))
    conn.commit()
    conn.close()
    return {"message": "Đã xóa khỏi lịch sử"}
class LoginRequest(BaseModel):
    username: str
    password: str

#API 8: Đăng nhập
@app.post("/api/v1/login")
def login(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()
    conn = get_db_connection()
    user = conn.execute(
        "SELECT user_id FROM users WHERE username = ? AND password = ?", 
        (username, password)
    ).fetchone()
    conn.close()
    
    if user:
        return {"success": True, "user_id": user["user_id"]}
    return {"success": False, "message": "Sai tài khoản hoặc mật khẩu!"}

#API 9: Đăng ký
@app.post("/api/v1/register")
def register(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()

    if not username or not password:
        return {"success": False, "message": "Vui lòng nhập đủ thông tin!"}

    conn = get_db_connection()
    try:
        user = conn.execute(
            "SELECT username FROM users WHERE lower(username) = lower(?)",
            (username,),
        ).fetchone()
        if user:
            return {"success": False, "message": "Tên đăng nhập đã tồn tại!"}

        import uuid
        new_user_id = f"USER_{uuid.uuid4().hex[:12].upper()}"

        conn.execute(
            "INSERT INTO users (user_id, username, password) VALUES (?, ?, ?)",
            (new_user_id, username, password)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {"success": False, "message": "Tên đăng nhập đã tồn tại!"}
    finally:
        conn.close()

    return {"success": True, "message": "Đăng ký thành công!"}

#API 10: Gợi ý KẾT HỢP TỰ ĐỘNG
def get_hybrid_recommendations(user_id, manual_alpha=None, exclude_user_ids=None, exclude_track_ids=None, top_n=5, original_num_listened=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT tracks.track_id, name, artist 
    FROM listening_history 
    JOIN tracks ON listening_history.track_id = tracks.track_id
    WHERE user_id = ? 
    ORDER BY updated_at DESC, listening_history.rowid DESC LIMIT 150
    """, (user_id,))
    recent_tracks = cursor.fetchall()

    local_tracks = [row["track_id"] for row in recent_tracks]
    num_listened = len(local_tracks)
    effective_num_listened = original_num_listened if original_num_listened is not None else num_listened
    blocked_track_ids = set(local_tracks)
    if exclude_track_ids:
        blocked_track_ids.update(exclude_track_ids)
    candidate_limit = max(50, min(500, top_n + len(blocked_track_ids)))
    
    #LOGIC TÍNH ALPHA ĐỘNG
    if manual_alpha is not None:
        alpha = manual_alpha
    else:
        # Tự động đọc file cấu hình
        try:
            with open("hybrid_config.json", "r") as f:
                config = json.load(f)
                if effective_num_listened <= 25:
                    alpha = config.get("best_alpha_under_25", 0.2)
                elif effective_num_listened <= 50:
                    alpha = config.get("best_alpha_under_50", 0.6)
                else:
                    alpha = config.get("best_alpha_over_50", 0.8)
        except (FileNotFoundError, json.JSONDecodeError):
            if effective_num_listened <= 25: alpha = 0.2
            elif effective_num_listened <= 50: alpha = 0.6
            else: alpha = 0.8
            
    als_dict = {} 
    clone_user_id = None
    
    blocked_user_ids = [user_id]
    if exclude_user_ids:
        blocked_user_ids.extend(exclude_user_ids)
    blocked_user_ids = list(dict.fromkeys(blocked_user_ids))

    if num_listened > 5:
        clone_user_id = find_als_clone_user(
            conn,
            local_tracks,
            blocked_user_ids=blocked_user_ids,
        )
            
    if clone_user_id and als_model and clone_user_id in als_model.u_map:
        als_df = als_model.recommend_user(u_id=clone_user_id, track_df=track_df, top_k=candidate_limit)
        if not isinstance(als_df, str):
            als_dict = {row["track_id"]: row["Score"] for row in als_df.to_dict('records')}
            
    #LẤY DỮ LIỆU KNN
    knn_dict = {}
    recent_tracks_db = get_recent_listened_tracks(conn, user_id, limit=5)
    conn.close()
    
    if recent_tracks_db:
        recent_songs = [(row["name"], row["artist"]) for row in recent_tracks_db]
        knn_df = recommend_songs(recent_songs=recent_songs, top_n=candidate_limit)
        if not isinstance(knn_df, str):
            knn_dict = {row["track_id"]: row["similarity_score"] for row in knn_df.to_dict('records')}
            
    if not als_dict and not knn_dict:
        return {"message": SIMILAR_SEARCH_MESSAGE, "recommendations": [], "alpha": alpha}
        
    #CHUẨN HÓA VÀ TÍNH ĐIỂM HYBRID
    all_tracks = set(als_dict.keys()).union(set(knn_dict.keys()))
    min_als, max_als = (min(als_dict.values()), max(als_dict.values())) if als_dict else (0, 1)
    min_knn, max_knn = (min(knn_dict.values()), max(knn_dict.values())) if knn_dict else (0, 1)
    
    def norm(val, min_v, max_v): return 0 if max_v == min_v else (val - min_v) / (max_v - min_v)
        
    hybrid_list = []
    for track_id in all_tracks:
        a_score = norm(als_dict.get(track_id, min_als), min_als, max_als)
        k_score = norm(knn_dict.get(track_id, min_knn), min_knn, max_knn)
        h_score = (alpha * a_score) + ((1 - alpha) * k_score)
        
        t_info = track_df[track_df['track_id'] == track_id]
        if not t_info.empty and track_id not in blocked_track_ids:
            hybrid_list.append({
                "track_id": track_id,
                "name": t_info['name'].values[0],
                "artist": t_info['artist'].values[0],
                "hybrid_score": round(h_score, 4)
            })
            
    hybrid_list.sort(key=lambda x: x["hybrid_score"], reverse=True)
    return {"recommendations": hybrid_list[:top_n], "message": "", "alpha": alpha}


@app.get("/api/v1/recommendations/hybrid/{user_id}")
def get_hybrid_recommendations_api(user_id: str):
    return get_hybrid_recommendations(user_id)
