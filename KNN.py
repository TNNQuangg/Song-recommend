import pandas as pd
import numpy as np
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.feature_extraction.text import TfidfVectorizer

# 1. Đọc dữ liệu
df = pd.read_csv(r"Music Info.csv")

#  Loại bỏ trùng lặp
if "spotify_id" in df.columns:
    df = df.drop_duplicates(subset=["spotify_id"]).reset_index(drop=True)
else:
    df = df.drop_duplicates(subset=["name", "artist"]).reset_index(drop=True)

#  Chọn đặc trưng số
feature_cols = [
    "danceability",
    "energy",
    "key",
    "loudness",
    "mode",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
    "time_signature"

]

feature_cols = [col for col in feature_cols if col in df.columns]
# bỏ dòng thiếu dữ liệu ở numeric
df = df.dropna(subset=feature_cols).reset_index(drop=True)

#  Chuẩn hóa numeric features
X_numeric = df[feature_cols].values.astype(np.float32)

mean = X_numeric.mean(axis=0)
std = X_numeric.std(axis=0)
std[std == 0] = 1.0

X_numeric = (X_numeric - mean) / std
#  Year feature
if "year" in df.columns:
    X_year = df[["year"]].values.astype(np.float32)

    mean_year = X_year.mean(axis=0)
    std_year = X_year.std(axis=0)
    std_year[std_year == 0] = 1.0
    X_year = (X_year - mean_year) / std_year
else:
    X_year = np.empty((len(df), 0), dtype=np.float32)

#  Xử lý TAGS bằng one-hot encoding
df["tags"] = df["tags"].fillna("").astype(str).str.lower().str.strip()

df["tags_list"] = df["tags"].apply(
    lambda x: [tag.strip() for tag in x.split(",") if tag.strip() != ""]
)

mlb = MultiLabelBinarizer()
X_tags = mlb.fit_transform(df["tags_list"]).astype(np.float32)

#  Gán trọng số cho từng nhóm feature
numeric_weight = 1.0
tags_weight = 0.8
year_weight = 0.3
X = np.hstack([
    X_numeric * numeric_weight,
    X_tags * tags_weight,
    X_year * year_weight
]).astype(np.float32)

# Hàm cosine similarity
def cosine_similarity(vec1, vec2):
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return np.dot(vec1, vec2) / (norm1 * norm2)

#  Hàm cosine distance
def cosine_distance(vec1, vec2):
    return 1 - cosine_similarity(vec1, vec2)

def find_song_index(song_name, artist_name=None):
    temp = df[df["name"].str.lower() == song_name.lower()]

    if artist_name is not None and "artist" in df.columns:
        temp = temp[temp["artist"].str.lower() == artist_name.lower()]

    if temp.empty:
        return None

    return temp.index[0]


def top_k_nearest_neighbors_multiple_exclude(query_vector, data_matrix, k, exclude_indices=None):
    if exclude_indices is None:
        exclude_indices = []

    norm_query = np.linalg.norm(query_vector)
    if norm_query == 0:
        return []

    # Vectorized cosine similarity
    norm_data = np.linalg.norm(data_matrix, axis=1)
    safe_norm_data = np.where(norm_data == 0, 1.0, norm_data)
    dot_products = data_matrix @ query_vector
    
    similarities = dot_products / (safe_norm_data * norm_query)
    distances = 1 - similarities

    # Ignore excluded indices by setting their distance to infinity
    if exclude_indices:
        distances[list(exclude_indices)] = np.inf

    # Get top k indices efficiently
    k = min(k, len(distances))
    if k == 0: return []
    
    top_k_idx = np.argpartition(distances, k - 1)[:k]
    top_k_idx_sorted = top_k_idx[np.argsort(distances[top_k_idx])]
    
    return [(idx, distances[idx]) for idx in top_k_idx_sorted if distances[idx] != np.inf]
def recommend_from_recent_songs(recent_songs, top_n=5):
    """
    recent_songs: danh sách các bài hát đã nghe gần nhất.
    Mỗi phần tử có dạng:
        ("song_name", "artist_name")
    hoặc:
        ("song_name", None)
    """

    song_indices = []

    for song_name, artist_name in recent_songs:
        idx = find_song_index(song_name, artist_name)

        if idx is not None:
            song_indices.append(idx)

    if len(song_indices) == 0:
        return "Không tìm thấy bài hát nào trong danh sách đã nghe."

    # Lấy vector của các bài đã nghe
    recent_vectors = X[song_indices]
    query_vector = np.mean(recent_vectors, axis=0)

    # Tìm top bài gần nhất, loại bỏ các bài đã nghe
    neighbors = top_k_nearest_neighbors_multiple_exclude(
        query_vector=query_vector,
        data_matrix=X,
        k=top_n,
        exclude_indices=song_indices
    )

    neighbor_indices = [idx for idx, dist in neighbors]
    neighbor_distances = [dist for idx, dist in neighbors]
    similarity_scores = [1 - dist for dist in neighbor_distances]

    result_cols = [col for col in ["track_id", "name", "artist", "genre", "tags"] if col in df.columns]
    results = df.loc[neighbor_indices, result_cols].copy()
    results["distance"] = neighbor_distances
    results["similarity_score"] = similarity_scores

    return results.reset_index(drop=True)
