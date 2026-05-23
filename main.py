import sqlite3
import pandas as pd
import pickle
import __main__
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json

# Import các thuật toán từ file của bạn
from KNN import recommend_from_recent_songs as recommend_songs
from rs_2 import Recommendation_System

# --- TẢI DỮ LIỆU & MÔ HÌNH (Chỉ chạy 1 lần khi start server) ---
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

# --- BỔ SUNG: Tính toán và lưu Cache Top 5 bài hát thịnh hành ---
print("Đang tính toán Top Thịnh Hành...")
TOP_5_POPULAR_TRACKS = []
try:
    # Mở một kết nối tạm thời chỉ để lấy dữ liệu 1 lần
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
    TOP_5_POPULAR_TRACKS = []   # Không động vào als_model
# ----------------------------------------------------------------

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

# Gọi hàm khởi tạo ngay lập tức
init_db()

# 2. HÀM KẾT NỐI DB (Chỉ làm nhiệm vụ kết nối để đọc/ghi, không tạo bảng nữa)
def get_db_connection():
    conn = sqlite3.connect('music_app.db', timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn
# ==============================================================

# --- API 1: Lấy lịch sử nghe nhạc ---
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

# --- API 2: Gợi ý theo lịch sử (ALS + Popularity Fallback) ---
@app.get("/api/v1/recommendations/history/{user_id}")
def get_history_based_recommendations(user_id: str):
    conn = get_db_connection()
    
    # 1. Lấy danh sách track_id mà Local User đã nghe
    local_history = conn.execute(
        "SELECT track_id FROM listening_history WHERE user_id = ?", 
        (user_id,)
    ).fetchall()
    
    local_tracks = [row["track_id"] for row in local_history]
    num_tracks = len(local_tracks)

    # 2. XỬ LÝ COLD START: Thay vì báo lỗi, trả về TOP 5 THỊNH HÀNH
    if num_tracks <= 5:
        return {
            "message": f"🔥 Top Thịnh Hành (Nghe thêm {6 - num_tracks} bài để cá nhân hóa)",
            "recommendations": TOP_5_POPULAR_TRACKS
        }

    # 3. TÌM USER TƯƠNG ĐỒNG (Khi đã nghe đủ 6 bài)
    placeholders = ','.join(['?'] * num_tracks)
    query = f"""
        SELECT user_id, COUNT(track_id) as matching_score
        FROM listening_history
        WHERE track_id IN ({placeholders}) AND user_id != ?
        GROUP BY user_id
        ORDER BY matching_score DESC
        LIMIT 1
    """
    params = local_tracks + [user_id]
    best_match = conn.execute(query, params).fetchone()
    conn.close()

    if not best_match:
        return {"message": "Gu âm nhạc của bạn quá độc đáo, chưa tìm thấy ai giống!", "recommendations": []}

    clone_user_id = best_match["user_id"]
    
    # 4. CHẠY ALS
    if not als_model or clone_user_id not in als_model.u_map:
        return {"message": "Đang cập nhật ma trận hệ thống...", "recommendations": []}
        
    result_df = als_model.recommend_user(u_id=clone_user_id, track_df=track_df)

    if isinstance(result_df, str):                          # ← Kiểm tra TRƯỚC
        return {"message": "Lỗi dữ liệu từ ALS", "recommendations": []}

    result_df = result_df.merge(                            # ← Merge SAU, chắc chắn là DataFrame
        track_df[['track_id', 'artist']], on='track_id', how='left'
    )

    return {
        "user_id": user_id,
        "mapped_to_clone": clone_user_id, 
        "message": "Gợi ý dành riêng cho bạn", # Đổi thông báo khi đã cá nhân hóa thành công
        "recommendations": result_df.fillna("").to_dict(orient="records")
    }

# --- API 3: Gợi ý theo giai điệu (KNN) dùng 5 bài gần nhất ---
@app.get("/api/v1/recommendations/melody/{user_id}")
def get_melody_based_recommendations(user_id: str):
    conn = get_db_connection()
    # Lấy tối đa 5 bài nghe gần nhất của user
    query = """
        SELECT t.name, t.artist 
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = ?
        ORDER BY lh.updated_at DESC, lh.rowid DESC
        LIMIT 5
    """
    recent_tracks = conn.execute(query, (user_id,)).fetchall()
    conn.close()
    
    if not recent_tracks:
        return {"recommendations": [], "message": "Chưa có lịch sử nghe nhạc để gợi ý theo giai điệu."}
    
    # Định dạng lại thành list of tuples cho KNN.py
    recent_songs = [(row["name"], row["artist"]) for row in recent_tracks]
    
    # Gọi hàm từ KNN.py với danh sách bài hát
    result_df = recommend_songs(recent_songs=recent_songs, top_n=5)
    
    if isinstance(result_df, str): 
        return {"recommendations": [], "message": result_df}
    
    return {
        "seed_tracks": recent_songs,
        "recommendations": result_df.fillna("").to_dict(orient="records")
    }
# --- API 4: Tìm kiếm ---
@app.get("/api/v1/search")
def search_tracks(q: str):
    conn = get_db_connection()
    query = "SELECT track_id, name, artist FROM tracks WHERE name LIKE ? OR artist LIKE ? LIMIT 10"
    search_term = f"%{q}%"
    results = conn.execute(query, (search_term, search_term)).fetchall()
    conn.close()
    return {"query": q, "results": [dict(row) for row in results]}

# --- API 5: Thêm bài hát vào lịch sử ---
@app.post("/api/v1/users/{user_id}/history/{track_id}")
def add_to_history(user_id: str, track_id: str):
    conn = get_db_connection()
    import datetime
    now = datetime.datetime.now()

    # Kiểm tra xem bài hát đã có trong lịch sử chưa
    check_query = "SELECT playcount FROM listening_history WHERE user_id = ? AND track_id = ?"
    row = conn.execute(check_query, (user_id, track_id)).fetchone()
    
    if row:
        # Nếu đã có: Tăng lượt nghe và cập nhật thời gian mới nhất
        update_query = "UPDATE listening_history SET playcount = playcount + 1, updated_at = ? WHERE user_id = ? AND track_id = ?"
        conn.execute(update_query, (now, user_id, track_id))
    else:
        # Nếu chưa có: Thêm mới hoàn toàn
        insert_query = "INSERT INTO listening_history (user_id, track_id, playcount, updated_at) VALUES (?, ?, 1, ?)"
        conn.execute(insert_query, (user_id, track_id, now))
        
    conn.commit()
    conn.close()
    return {"message": "Đã thêm vào lịch sử"}

# --- API 6: Xóa toàn bộ lịch sử của User ---
@app.delete("/api/v1/users/{user_id}/history/clear")
def clear_user_history(user_id: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM listening_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"message": "Đã xóa toàn bộ lịch sử"}

# --- API 7: Xóa bài hát khỏi lịch sử ---
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

# --- API 8: Đăng nhập ---
@app.post("/api/v1/login")
def login(req: LoginRequest):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT user_id FROM users WHERE username = ? AND password = ?", 
        (req.username, req.password)
    ).fetchone()
    conn.close()
    
    if user:
        return {"success": True, "user_id": user["user_id"]}
    return {"success": False, "message": "Sai tài khoản hoặc mật khẩu!"}

# --- API 9: Gợi ý KẾT HỢP TỰ ĐỘNG (Dynamic Weighted Hybrid) ---
def get_hybrid_recommendations(user_id, manual_alpha=None, exclude_user_ids=None, exclude_track_ids=None, top_n=5):
    # 1. Lấy lịch sử nghe nhạc của User
    conn = get_db_connection() # Dùng hàm helper đã có để có timeout và WAL
    cursor = conn.cursor()
    cursor.execute("""
    SELECT tracks.track_id, name, artist 
    FROM listening_history 
    JOIN tracks ON listening_history.track_id = tracks.track_id
    WHERE user_id = ? 
    ORDER BY updated_at DESC LIMIT 150
    """, (user_id,))
    recent_tracks = cursor.fetchall()

    # KHẮC PHỤC LỖI 1: Định nghĩa local_tracks và num_tracks
    local_tracks = [row["track_id"] for row in recent_tracks]
    num_listened = len(local_tracks)
    blocked_track_ids = set(local_tracks)
    if exclude_track_ids:
        blocked_track_ids.update(exclude_track_ids)
    candidate_limit = max(50, min(500, top_n + len(blocked_track_ids)))
    
    # --- LOGIC TÍNH ALPHA ĐỘNG ---
    if manual_alpha is not None:
        alpha = manual_alpha
    else:
        # Tự động đọc file cấu hình nếu có
        try:
            with open("hybrid_config.json", "r") as f:
                config = json.load(f)
                if num_listened <= 25:
                    alpha = config.get("best_alpha_under_25", 0.3)
                elif num_listened <= 50:
                    alpha = config.get("best_alpha_under_50", 0.6)
                else:
                    alpha = config.get("best_alpha_over_50", 0.8)
        except (FileNotFoundError, json.JSONDecodeError):
            if num_listened <= 25: alpha = 0.3
            elif num_listened <= 50: alpha = 0.6
            else: alpha = 0.8
            
    # KHẮC PHỤC LỖI 2: Khởi tạo biến trước khi gọi
    als_dict = {} 
    clone_user_id = None
    
    blocked_user_ids = [user_id]
    if exclude_user_ids:
        blocked_user_ids.extend(exclude_user_ids)
    blocked_user_ids = list(dict.fromkeys(blocked_user_ids))

    if num_listened > 5:
        placeholders = ','.join(['?'] * num_listened)
        blocked_placeholders = ','.join(['?'] * len(blocked_user_ids))
        query = f"""
            SELECT user_id, COUNT(track_id) as matching_score
            FROM listening_history
            WHERE track_id IN ({placeholders})
              AND user_id NOT IN ({blocked_placeholders})
            GROUP BY user_id
            ORDER BY matching_score DESC
            LIMIT 1
        """
        best_match = conn.execute(query, local_tracks + blocked_user_ids).fetchone()
        if best_match: 
            clone_user_id = best_match["user_id"]
            
    if clone_user_id and als_model and clone_user_id in als_model.u_map:
        als_df = als_model.recommend_user(u_id=clone_user_id, track_df=track_df, top_k=candidate_limit)
        if not isinstance(als_df, str):
            # KHẮC PHỤC LỖI 3: Đồng bộ key thành "name"
            # Cố gắng lấy "name" trước, nếu không có thì lấy "Tên bài hát"
            als_dict = {row["track_id"]: row["Score"] for row in als_df.to_dict('records')}
            
    # --- 2. LẤY DỮ LIỆU KNN ---
    knn_dict = {}
    knn_query = """
        SELECT t.name, t.artist, lh.track_id
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = ?
        ORDER BY lh.updated_at DESC, lh.rowid DESC
        LIMIT 5
    """
    recent_tracks_db = conn.execute(knn_query, (user_id,)).fetchall()
    conn.close() # Đóng DB một lần ở đây
    
    if recent_tracks_db:
        recent_songs = [(row["name"], row["artist"]) for row in recent_tracks_db]
        knn_df = recommend_songs(recent_songs=recent_songs, top_n=candidate_limit)
        if not isinstance(knn_df, str):
            knn_dict = {row["track_id"]: row["similarity_score"] for row in knn_df.to_dict('records')}
            
    if not als_dict and not knn_dict:
        return {"message": "Chưa có đủ dữ liệu để kết hợp.", "recommendations": [], "alpha": alpha}
        
    # --- 3. CHUẨN HÓA VÀ TÍNH ĐIỂM HYBRID ---
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
