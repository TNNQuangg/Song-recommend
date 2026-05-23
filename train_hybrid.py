import json
import random
import sys

from tqdm import tqdm

from hybrid_eval_utils import (
    DATASET_MODE_ALS_FILTERED,
    MAX_PROFILE_TRACKS,
    bucket_users_by_count,
    build_profile_split,
    build_user_track_map,
    limit_profile_tracks,
    load_als_filtered_history,
    load_history_into_user,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from main import get_hybrid_recommendations


CSV_FILE = "Cleaned_User_Listening_History.csv"
DB_FILE = "music_app.db"
CONFIG_FILE = "hybrid_config.json"
TRAIN_USER = "TRAIN_BOT"
RANDOM_SEED = 42
TEST_USERS_LIMIT_PER_BUCKET = 15
HOLDOUT_SIZE = 10
ALPHA_CANDIDATES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
DEFAULT_ALPHAS = {"under_25": 0.3, "under_50": 0.6, "over_50": 0.8}


def train_and_save_best_alpha():
    print("Starting hybrid alpha training on ALS-filtered data...")

    try:
        user_input = input(
            f"Users per bucket for tuning (Enter = {TEST_USERS_LIMIT_PER_BUCKET}): "
        ).strip()
        test_limit = int(user_input) if user_input else TEST_USERS_LIMIT_PER_BUCKET
    except ValueError:
        print(f"Invalid input, using default {TEST_USERS_LIMIT_PER_BUCKET}.")
        test_limit = TEST_USERS_LIMIT_PER_BUCKET

    try:
        history_df = load_als_filtered_history(CSV_FILE)
    except FileNotFoundError:
        print(f"Missing dataset: {CSV_FILE}")
        return

    user_tracks_by_user = build_user_track_map(history_df)
    buckets_users = bucket_users_by_count(history_df)
    rng = random.Random(RANDOM_SEED)

    tuning_users_by_bucket = {}
    total_tuning_users = 0
    for bucket_name, bucket_users in buckets_users.items():
        sampled = rng.sample(bucket_users, min(test_limit, len(bucket_users)))
        tuning_users_by_bucket[bucket_name] = sampled
        total_tuning_users += len(sampled)
        print(f"Bucket {bucket_name}: {len(sampled)} users")

    print(f"Training alpha on {total_tuning_users} sampled users.")

    config_results = {
        "dataset_mode": DATASET_MODE_ALS_FILTERED,
        "random_seed": RANDOM_SEED,
        "holdout_size": HOLDOUT_SIZE,
        "max_profile_tracks": MAX_PROFILE_TRACKS,
        "tuning_users_limit_per_bucket": test_limit,
        "alpha_candidates": ALPHA_CANDIDATES,
        "filtered_users": int(history_df["user_id"].nunique()),
        "filtered_tracks": int(history_df["track_id"].nunique()),
        "filtered_interactions": int(len(history_df)),
        "tuning_user_counts_by_bucket": {
            bucket_name: len(users)
            for bucket_name, users in tuning_users_by_bucket.items()
        },
    }

    for bucket_name, bucket_users in tuning_users_by_bucket.items():
        if not bucket_users:
            print(f"Skipping bucket {bucket_name} due to no users.")
            config_results[f"best_alpha_{bucket_name}"] = DEFAULT_ALPHAS[bucket_name]
            config_results[f"max_hit_rate_percent_{bucket_name}"] = 0.0
            config_results[f"training_history_{bucket_name}"] = []
            continue

        print(f"\n--- Training for bucket {bucket_name} ---")
        best_alpha = DEFAULT_ALPHAS[bucket_name]
        max_hit_rate = -1.0
        history_log = []

        for alpha in ALPHA_CANDIDATES:
            hit_count = 0
            total_tested = 0

            for user_id in tqdm(bucket_users, desc=f"Checking alpha={alpha} ({bucket_name})"):
                train_tracks, ground_truth = build_profile_split(
                    user_tracks_by_user[user_id],
                    holdout_size=HOLDOUT_SIZE,
                    seed=f"{user_id}-{RANDOM_SEED}",
                )

                if not train_tracks or not ground_truth:
                    continue

                profile_tracks = limit_profile_tracks(train_tracks)
                load_history_into_user(DB_FILE, TRAIN_USER, profile_tracks)

                try:
                    response = get_hybrid_recommendations(
                        TRAIN_USER,
                        manual_alpha=alpha,
                        exclude_user_ids=[user_id],
                        exclude_track_ids=train_tracks,
                        top_n=10,
                    )
                except Exception as exc:
                    print(f"Skip user {user_id}: {exc}")
                    continue

                recommendations = {
                    track["track_id"]
                    for track in response.get("recommendations", [])
                    if "track_id" in track
                }

                if recommendations & ground_truth:
                    hit_count += 1
                total_tested += 1

            current_hr = (hit_count / total_tested) if total_tested else 0.0
            print(f"alpha={alpha} -> hit rate: {current_hr * 100:.2f}%")
            history_log.append(
                {
                    "alpha": alpha,
                    "hit_rate_percent": round(current_hr * 100, 2),
                    "hit_count": hit_count,
                    "tested_users": total_tested,
                }
            )

            if current_hr > max_hit_rate:
                max_hit_rate = current_hr
                best_alpha = alpha

        print(f"Best alpha for {bucket_name}: {best_alpha}")
        config_results[f"best_alpha_{bucket_name}"] = best_alpha
        config_results[f"max_hit_rate_percent_{bucket_name}"] = round(max_hit_rate * 100, 2)
        config_results[f"training_history_{bucket_name}"] = history_log

    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(config_results, file, ensure_ascii=False, indent=4)

    print(f"\nSaved config to {CONFIG_FILE}")
    print(json.dumps({k: v for k, v in config_results.items() if "best_alpha" in k}, indent=2))


if __name__ == "__main__":
    train_and_save_best_alpha()
