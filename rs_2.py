import numpy as np
import pandas as pd
import pickle
from scipy.sparse import csr_matrix


# ============================================================
#  SPLIT — train / valid / test
# ============================================================
def train_valid_test_split_by_user(data, valid_ratio=0.1, test_ratio=0.2, random_state=42):
    # Khởi tạo DataFrame
    df = pd.DataFrame(data, columns=["user", "item", "playcount"])
    
    # 1. Xáo trộn ngẫu nhiên toàn bộ dữ liệu 1 lần duy nhất để chống bias
    df = df.sample(frac=1, random_state=random_state).reset_index(drop=True)
    
    # 2. Đếm tổng số lượng item của mỗi user
    user_counts = df.groupby('user')['item'].transform('count')
    
    # 3. Đánh số thứ tự ngẫu nhiên (rank) cho từng bài hát của mỗi user (từ 0 đến count - 1)
    df['rank'] = df.groupby('user').cumcount()
    
    # 4. Tính toán số lượng mẫu cho test và valid của từng user
    n_test = np.maximum(1, (user_counts * test_ratio).astype(int))
    n_valid = np.maximum(1, (user_counts * valid_ratio).astype(int))
    
    # 5. Phân tách điều kiện (Chỉ user có >= 5 tương tác mới được cắt ra làm valid/test)
    is_valid_user = user_counts >= 5
    
    # - Test set: Các item có rank nằm ở cuối cùng
    is_test = is_valid_user & (df['rank'] >= (user_counts - n_test))
    
    # - Valid set: Các item nằm kế cuối (không thuộc test set)
    is_valid = is_valid_user & (~is_test) & (df['rank'] >= (user_counts - n_test - n_valid))
    
    # - Train set: Phần còn lại
    is_train = ~(is_test | is_valid)
    
    # 6. Trích xuất ra numpy array
    train_data = df[is_train][["user", "item", "playcount"]].values
    valid_data = df[is_valid][["user", "item", "playcount"]].values
    test_data = df[is_test][["user", "item", "playcount"]].values
    
    return train_data, valid_data, test_data


# ============================================================
#  HELPER
# ============================================================
def build_matrix(model, data):
    r, c = [], []
    for u, i, _ in data:
        if u in model.u_map and i in model.i_map:
            r.append(model.u_map[u])
            c.append(model.i_map[i])
    v = np.ones(len(r))
    return csr_matrix((v, (r, c)), shape=(model.n_users, model.n_items))


def popularity_baseline(train_data, test_data, K=10):
    df_train  = pd.DataFrame(train_data, columns=["user", "item", "play"])
    top_items = set(df_train["item"].value_counts().index[:K])

    df_test    = pd.DataFrame(test_data, columns=["user", "item", "play"])
    user_true  = df_test.groupby("user")["item"].apply(set).to_dict()

    precisions = []
    for u, true_items in user_true.items():
        precisions.append(len(top_items & true_items) / K)

    p = np.mean(precisions)
    print(f"Popularity Baseline | P@{K}={p*100:.2f}%")
    return p


# ============================================================
#  MODEL
# ============================================================
class Recommendation_System:
    def __init__(self, data_array=None, k=32, lamda=30.0, alpha=10, iterations=15):
        if data_array is not None:
            self.k          = k
            self.lamda      = lamda
            self.alpha      = alpha
            self.iterations = iterations

            self.users   = np.unique(data_array[:, 0])
            self.items   = np.unique(data_array[:, 1])
            self.n_users = len(self.users)
            self.n_items = len(self.items)

            self.u_map     = {u: i for i, u in enumerate(self.users)}
            self.i_map     = {i: j for j, i in enumerate(self.items)}
            self.i_idx_map = {j: i for i, j in self.i_map.items()}

            rows = np.array([self.u_map[u] for u in data_array[:, 0]])
            cols = np.array([self.i_map[i] for i in data_array[:, 1]])
            vals = np.log1p(data_array[:, 2].astype(float))

            self.R     = csr_matrix((vals, (rows, cols)),
                                    shape=(self.n_users, self.n_items))
            self.R_csc = self.R.tocsc()

    def update_X(self):
        YTY = self.Y.T @ self.Y
        I   = np.eye(self.k)
        for u in range(self.n_users):
            s, t = self.R.indptr[u], self.R.indptr[u+1]
            if s == t:
                continue
            idx = self.R.indices[s:t]
            c   = self.R.data[s:t]
            Y_u = self.Y[idx]
            A   = YTY + (Y_u.T * (self.alpha * c)) @ Y_u + self.lamda * I
            b   = Y_u.T @ (1 + self.alpha * c)
            self.X[u] = np.linalg.solve(A, b)

    def update_Y(self):
        XTX = self.X.T @ self.X
        I   = np.eye(self.k)
        for i in range(self.n_items):
            s, t = self.R_csc.indptr[i], self.R_csc.indptr[i+1]
            if s == t:
                continue
            idx = self.R_csc.indices[s:t]
            c   = self.R_csc.data[s:t]
            X_i = self.X[idx]
            A   = XTX + (X_i.T * (self.alpha * c)) @ X_i + self.lamda * I
            b   = X_i.T @ (1 + self.alpha * c)
            self.Y[i] = np.linalg.solve(A, b)

    def _compute_loss(self):
        loss = 0.0
        for u in range(self.n_users):
            s, t = self.R.indptr[u], self.R.indptr[u+1]
            if s == t:
                continue
            idx  = self.R.indices[s:t]
            r    = self.R.data[s:t]
            c    = 1 + self.alpha * r
            pred = self.X[u] @ self.Y[idx].T
            p    = np.ones(len(idx))
            loss += np.sum(c * (p - pred) ** 2)
        loss += self.lamda * (np.sum(self.X ** 2) + np.sum(self.Y ** 2))
        return loss

    def fit(self, verbose=True):
        np.random.seed(42)
        scale  = 1.0 / np.sqrt(self.k)
        self.X = np.random.normal(0, scale, (self.n_users, self.k))
        self.Y = np.random.normal(0, scale, (self.n_items, self.k))
        for it in range(self.iterations):
            self.update_X()
            self.update_Y()
            if verbose and ((it + 1) % 5 == 0 or it == 0):
                loss = self._compute_loss()
                print(f"  Iter {it+1:2d}/{self.iterations} | Loss = {loss:,.0f}")

    def _get_scores(self, u, mask_train=True):
        scores = self.X[u] @ self.Y.T
        if mask_train:
            scores[self.R.indices[self.R.indptr[u]:self.R.indptr[u+1]]] = -1e9
        return scores

    def precision(self, matrix, K=10, mask_train=True):
        res = []
        for u in range(self.n_users):
            true_items = matrix.indices[matrix.indptr[u]:matrix.indptr[u+1]]
            if len(true_items) == 0:
                continue
            top_k = np.argsort(self._get_scores(u, mask_train))[::-1][:K]
            res.append(len(set(top_k) & set(true_items)) / K)
        return np.mean(res)

    def recall(self, matrix, K=10, mask_train=True):
        res = []
        for u in range(self.n_users):
            true_items = matrix.indices[matrix.indptr[u]:matrix.indptr[u+1]]
            if len(true_items) == 0:
                continue
            top_k = np.argsort(self._get_scores(u, mask_train))[::-1][:K]
            res.append(len(set(top_k) & set(true_items)) / len(true_items))
        return np.mean(res)

    def ndcg(self, matrix, K=10, mask_train=True):
        res      = []
        discount = 1.0 / np.log2(np.arange(2, K+2))
        for u in range(self.n_users):
            true_items = set(matrix.indices[matrix.indptr[u]:matrix.indptr[u+1]])
            if not true_items:
                continue
            top_k = np.argsort(self._get_scores(u, mask_train))[::-1][:K]
            hits  = np.array([1.0 if i in true_items else 0.0 for i in top_k])
            dcg   = (hits * discount).sum()
            ideal = discount[:min(len(true_items), K)].sum()
            res.append(dcg / ideal if ideal > 0 else 0.0)
        return np.mean(res)

    def hit_rate(self, matrix, K=10, mask_train=True):
        res = []
        for u in range(self.n_users):
            true_items = set(matrix.indices[matrix.indptr[u]:matrix.indptr[u+1]])
            if not true_items:
                continue
            top_k = np.argsort(self._get_scores(u, mask_train))[::-1][:K]
            hits = set(top_k) & true_items
            res.append(1.0 if len(hits) > 0 else 0.0)
        return np.mean(res)

    def recommend_user(self, u_id, track_df, top_k=10):
        u_idx = self.u_map.get(u_id)
        if u_idx is None:
            return "User không tồn tại"
        scores  = self._get_scores(u_idx, mask_train=True)
        top_idx = np.argsort(scores)[::-1][:top_k]
        res = []
        for idx in top_idx:
            track_id = self.i_idx_map[idx]
            row      = track_df[track_df['track_id'] == track_id]
            name     = row['name'].values[0] if len(row) > 0 else "Unknown"
            res.append({"track_id": track_id,
                        "Tên bài hát": name,
                        "Score": round(float(scores[idx]), 4)})
        return pd.DataFrame(res)

    def recommend_track(self, i_id, track_df, top_n=10):
        i_idx = self.i_map.get(i_id)
        if i_idx is None:
            return "Track không tồn tại"
        vec   = self.Y[i_idx]
        norms = np.linalg.norm(self.Y, axis=1)
        norms[norms == 0] = 1e-10
        sims  = self.Y @ vec / (norms * (np.linalg.norm(vec) + 1e-10))
        sims[i_idx] = -1
        top_idx = np.argsort(sims)[::-1][:top_n]
        res = []
        for idx in top_idx:
            track_id = self.i_idx_map[idx]
            row      = track_df[track_df['track_id'] == track_id]
            name     = row['name'].values[0] if len(row) > 0 else "Unknown"
            res.append({"track_id": track_id,
                        "Tên bài hát": name,
                        "Similarity": round(float(sims[idx]), 4)})
        return pd.DataFrame(res)


# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":

    # ── Load data ──────────────────────────────────────────
    play_count = pd.read_csv("Cleaned_User_Listening_History.csv")
    track_df   = pd.read_csv("Music Info.csv")

    play_grouped = play_count.groupby(["user_id", "track_id"])["playcount"].sum().reset_index()
    play_grouped = play_grouped[play_grouped["playcount"] >= 2]
    play_grouped['playcount'] = play_grouped['playcount'].clip(upper=50)

    track_counts = play_grouped['track_id'].value_counts()
    valid_tracks = track_counts[track_counts >= 15].index
    play_grouped = play_grouped[play_grouped['track_id'].isin(valid_tracks)]

    user_counts  = play_grouped['user_id'].value_counts()
    valid_users  = user_counts[(user_counts >= 15) & (user_counts <= 300)].index
    play_grouped = play_grouped[play_grouped['user_id'].isin(valid_users)]

    print(f"Users       : {play_grouped['user_id'].nunique():,}")
    print(f"Tracks      : {play_grouped['track_id'].nunique():,}")
    print(f"Interactions: {len(play_grouped):,}")

    Y = play_grouped[["user_id", "track_id", "playcount"]].values

    # ── Split train / valid / test ───────────────
    train_data, valid_data, test_data = train_valid_test_split_by_user(
        Y, valid_ratio=0.15, test_ratio=0.15
    )
    print(f"\nTrain: {len(train_data):,} | Valid: {len(valid_data):,} | Test: {len(test_data):,}")

    best_params = {'k': 256, 'lamda': 2.0, 'alpha': 40}
    print(f"\nSử dụng best params: {best_params}")

    train_valid_data = np.vstack([train_data, valid_data])
    final_model = Recommendation_System(train_valid_data, iterations=15, **best_params)
    final_model.fit(verbose=True)

    test_matrix = build_matrix(final_model, test_data)
    test_p  = final_model.precision(test_matrix, K=10, mask_train=True)
    test_r  = final_model.recall(test_matrix,    K=10, mask_train=True)
    test_n  = final_model.ndcg(test_matrix,      K=10, mask_train=True)
    test_hr = final_model.hit_rate(test_matrix,  K=10, mask_train=True)

    print(f"\n{'='*45}")
    print(f"FINAL TEST RESULTS")
    print(f"{'='*45}")
    print(f"Test P@10   : {test_p*100:.2f}%")
    print(f"Test R@10   : {test_r*100:.2f}%")
    print(f"Test NDCG@10: {test_n*100:.2f}%")
    print(f"Test HR@10  : {test_hr*100:.2f}%")
    print(f"{'='*45}")

    print()
    pop_p = popularity_baseline(train_data, test_data, K=10)
    print(f"ALS Lift vs Baseline: {((test_p - pop_p)/(pop_p+1e-9)*100):.1f}%")




    # ── Save model ─────────────────────────────────────────
    with open("als12_model.pkl", "wb") as f:
        pickle.dump(final_model, f)
    print("\nSaved als_model.pkl")

    # ── Demo ───────────────────────────────────────────────
    user_test  = train_data[0][0]
    track_test = train_data[0][1]

    print(f"\nRecommend cho user: {user_test}")
    print(final_model.recommend_user(user_test, track_df))

    print(f"\nTương tự track: {track_test}")
    print(final_model.recommend_track(track_test, track_df))