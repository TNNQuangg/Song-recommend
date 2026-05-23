import datetime
import sqlite3

import pandas as pd


DATASET_MODE_ALS_FILTERED = "als_filtered"
MAX_PROFILE_TRACKS = 150


def load_als_filtered_history(csv_file):
    """Load listening history with the same preprocessing used by rs_2.py."""
    raw_df = pd.read_csv(csv_file)
    required_columns = {"user_id", "track_id", "playcount"}
    missing_columns = required_columns - set(raw_df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required columns: {missing}")

    play_grouped = (
        raw_df.groupby(["user_id", "track_id"], sort=False)["playcount"]
        .sum()
        .reset_index()
    )
    play_grouped = play_grouped[play_grouped["playcount"] >= 2].copy()
    play_grouped["playcount"] = play_grouped["playcount"].clip(upper=50)

    track_counts = play_grouped["track_id"].value_counts()
    valid_tracks = track_counts[track_counts >= 15].index
    play_grouped = play_grouped[play_grouped["track_id"].isin(valid_tracks)].copy()

    user_counts = play_grouped["user_id"].value_counts()
    valid_users = user_counts[(user_counts >= 15) & (user_counts <= 300)].index
    play_grouped = play_grouped[play_grouped["user_id"].isin(valid_users)].copy()

    return play_grouped.reset_index(drop=True)


def build_user_track_map(history_df):
    return (
        history_df.groupby("user_id", sort=False)["track_id"]
        .apply(list)
        .to_dict()
    )


def bucket_users_by_count(history_df):
    user_counts = history_df["user_id"].value_counts()
    return {
        "under_25": user_counts[(user_counts >= 15) & (user_counts <= 25)].index.tolist(),
        "under_50": user_counts[(user_counts >= 26) & (user_counts <= 50)].index.tolist(),
        "over_50": user_counts[user_counts > 50].index.tolist(),
    }


def limit_profile_tracks(track_ids, max_tracks=MAX_PROFILE_TRACKS):
    tracks = list(track_ids)
    if max_tracks and len(tracks) > max_tracks:
        return tracks[-max_tracks:]
    return tracks


def build_profile_split(track_ids, holdout_size=5, seed=42):
    # seed is kept for API compatibility; split is deterministic by track order.
    del seed
    deduped_tracks = list(dict.fromkeys(track_ids))
    if len(deduped_tracks) <= holdout_size:
        return [], set()

    ground_truth_list = deduped_tracks[-holdout_size:]
    ground_truth = set(ground_truth_list)
    train_tracks = deduped_tracks[:-holdout_size]

    return train_tracks, ground_truth


def load_history_into_user(db_path, user_id, track_ids):
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM listening_history WHERE user_id = ?", (user_id,))

    now = datetime.datetime.now()
    records = [
        (
            user_id,
            track_id,
            1,
            (now + datetime.timedelta(seconds=idx)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        for idx, track_id in enumerate(track_ids)
    ]

    if records:
        conn.executemany(
            """
            INSERT INTO listening_history (user_id, track_id, playcount, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            records,
        )

    conn.commit()
    conn.close()
