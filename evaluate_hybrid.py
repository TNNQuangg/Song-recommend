import json
import random
import sys
from collections import Counter

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
RESULT_FILE = "ket_qua_danh_gia.txt"
TEST_USER = "EVALUATOR_BOT"
EVAL_USERS_LIMIT = 1000
EVAL_RANDOM_SEED = 43
HOLDOUT_SIZE = 10


def load_hybrid_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_tuning_user_ids(config, history_df):
    seed = config.get("random_seed")
    counts_by_bucket = config.get("tuning_user_counts_by_bucket", {})
    default_limit = config.get("tuning_users_limit_per_bucket", 0)
    if seed is None or not isinstance(counts_by_bucket, dict):
        return set()

    rng = random.Random(seed)
    tuning_user_ids = set()
    for bucket_name, bucket_users in bucket_users_by_count(history_df).items():
        count = counts_by_bucket.get(bucket_name, default_limit)
        sampled = rng.sample(bucket_users, min(int(count), len(bucket_users)))
        tuning_user_ids.update(sampled)
    return tuning_user_ids


def main():
    try:
        user_input = input(
            f"Total users to evaluate (Enter = {EVAL_USERS_LIMIT}): "
        ).strip()
        eval_limit = int(user_input) if user_input else EVAL_USERS_LIMIT
    except ValueError:
        print(f"Invalid input, using default {EVAL_USERS_LIMIT}.")
        eval_limit = EVAL_USERS_LIMIT

    print("Loading ALS-filtered dataset...")
    history_df = load_als_filtered_history(CSV_FILE)
    user_tracks_by_user = build_user_track_map(history_df)

    config = load_hybrid_config()
    tuning_user_ids = get_tuning_user_ids(config, history_df)
    if config.get("dataset_mode") != DATASET_MODE_ALS_FILTERED:
        print("Warning: hybrid_config.json was not generated with ALS-filtered metadata.")

    candidate_users = [
        user_id
        for user_id in user_tracks_by_user
        if user_id not in tuning_user_ids
    ]

    rng = random.Random(EVAL_RANDOM_SEED)
    test_users = rng.sample(candidate_users, min(eval_limit, len(candidate_users)))

    print(f"Found {len(candidate_users)} candidate eval users.")
    print(f"Excluded {len(tuning_user_ids)} tuning users from evaluation.")
    print("Starting hybrid offline evaluation...\n")

    total_tested = 0
    hit_count = 0
    total_precision = 0.0
    alpha_usage = Counter()
    leaked_seen_slots = 0
    total_recommendation_slots = 0

    for user_id in tqdm(test_users, desc="Evaluation progress", unit="user"):
        train_tracks, ground_truth = build_profile_split(
            user_tracks_by_user[user_id],
            holdout_size=HOLDOUT_SIZE,
            seed=f"{user_id}-evaluate-{EVAL_RANDOM_SEED}",
        )

        if not train_tracks or not ground_truth:
            continue

        profile_tracks = limit_profile_tracks(train_tracks)
        load_history_into_user(DB_FILE, TEST_USER, profile_tracks)

        try:
            response = get_hybrid_recommendations(
                TEST_USER,
                exclude_user_ids=[user_id],
                exclude_track_ids=train_tracks,
                top_n=10,
            )
        except Exception as exc:
            print(f"Error for {user_id}: {exc}")
            continue

        recommendations = [
            track["track_id"]
            for track in response.get("recommendations", [])
            if "track_id" in track
        ]

        hits = set(recommendations) & ground_truth
        seen_recs = set(recommendations) & set(train_tracks)
        leaked_seen_slots += len(seen_recs)
        total_recommendation_slots += len(recommendations)
        alpha_usage[str(response.get("alpha", "unknown"))] += 1

        total_tested += 1
        if hits:
            hit_count += 1
        total_precision += len(hits) / 10

    hit_rate = (hit_count / total_tested) * 100 if total_tested else 0.0
    avg_precision = (total_precision / total_tested) * 100 if total_tested else 0.0

    with open(RESULT_FILE, "w", encoding="utf-8") as file:
        file.write("=== HYBRID OFFLINE EVALUATION ===\n")
        file.write(f"Dataset mode: {DATASET_MODE_ALS_FILTERED}\n")
        file.write(f"Config dataset mode: {config.get('dataset_mode', 'unknown')}\n")
        file.write(f"Eval random seed: {EVAL_RANDOM_SEED}\n")
        file.write(f"Holdout size: {HOLDOUT_SIZE}\n")
        file.write(f"Max profile tracks: {MAX_PROFILE_TRACKS}\n")
        file.write(f"Candidate eval users: {len(candidate_users)}\n")
        file.write(f"Excluded tuning users: {len(tuning_user_ids)}\n")
        file.write(f"Tested users: {total_tested}\n")
        file.write("-" * 45 + "\n\n")
        file.write(f"1. Hybrid Hit Rate @ 10: {hit_rate:.2f}%\n")
        file.write(f"2. Hybrid Precision @ 10: {avg_precision:.2f}%\n")
        file.write(f"3. Seen-history leaks in recommendations: {leaked_seen_slots}\n")
        file.write(f"4. Recommendation slots returned: {total_recommendation_slots}\n\n")
        file.write("Alpha usage:\n")
        for alpha, count in sorted(alpha_usage.items(), key=lambda item: item[0]):
            file.write(f"- alpha={alpha}: {count} users\n")

    print("\nEvaluation finished.")
    print(f"Results saved to {RESULT_FILE}")


if __name__ == "__main__":
    main()
