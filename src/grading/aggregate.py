"""Aggregate sub-scores into final 0-100 score per README rubric."""
# Weights from README:
# Claim Verification 40%: verified-claim ratio 20%, logical soundness 20%
# Ground Truth 40%: file recall 10%, precision 10%, LLM GT judge 20%
# Quality 20%: conciseness 5%, precision 5%, tone 5%, formatting 5%


def aggregate_scores(
    verified_and_unknown_claim_ratio: float,
    logical_soundness: float,
    file_recall: float,
    file_precision: float,
    gt_judge: float,
    conciseness: float,
    precision: float,
    tone: float,
    formatting: float,
) -> float:
    """
    Weights:
    - Claim Verification 40%: verified_and_unknown_claim_ratio 20%, logical_soundness 20%
    - Ground Truth 40%: file_recall 10%, file_precision 10%, gt_judge 20%
    - Quality 20%: conciseness 5%, precision 5%, tone 5%, formatting 5%
    """
    claim_part = 0.20 * verified_and_unknown_claim_ratio + 0.20 * logical_soundness
    gt_part = 0.10 * file_recall + 0.10 * file_precision + 0.20 * gt_judge
    quality_part = 0.05 * conciseness + 0.05 * precision + 0.05 * tone + 0.05 * formatting
    return 100.0 * (claim_part + gt_part + quality_part)


def aggregate_task_result(
    verified_and_unknown_claim_ratio: float,
    unknown_claim_ratio: float,
    logical_soundness: float,
    gt_metrics: dict,
    quality_scores: dict,
) -> tuple[float, dict]:
    """
    gt_metrics: file_recall, file_precision, gt_judge
    quality_scores: conciseness, precision, tone, formatting
    Returns (final_score_0_100, breakdown_dict).
    """
    score = aggregate_scores(
        verified_and_unknown_claim_ratio=verified_and_unknown_claim_ratio,
        logical_soundness=logical_soundness,
        file_recall=gt_metrics.get("file_recall", 0),
        file_precision=gt_metrics.get("file_precision", 0),
        gt_judge=gt_metrics.get("gt_judge", 0),
        conciseness=quality_scores.get("conciseness", 0),
        precision=quality_scores.get("precision", 0),
        tone=quality_scores.get("tone", 0),
        formatting=quality_scores.get("formatting", 0),
    )
    breakdown = {
        "verified_and_unknown_claim_ratio": verified_and_unknown_claim_ratio,
        "unknown_claim_ratio": unknown_claim_ratio,
        "logical_soundness": logical_soundness,
        "file_recall": gt_metrics.get("file_recall", 0),
        "file_precision": gt_metrics.get("file_precision", 0),
        "gt_judge": gt_metrics.get("gt_judge", 0),
        "conciseness": quality_scores.get("conciseness", 0),
        "precision": quality_scores.get("precision", 0),
        "tone": quality_scores.get("tone", 0),
        "formatting": quality_scores.get("formatting", 0),
    }
    return score, breakdown
