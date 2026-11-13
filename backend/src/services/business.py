"""专栏续读风险：训练集拟合标准化，独立留出集评估；也可复用已批准试验给未标注批次评分。"""
import math
import time
import numpy as np
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.utils.serialization import checksum

FEATURES = ["sessions_14d", "completion_pct", "days_inactive", "issues_read"]
LABELS = ["14日访问次数", "阅读完成率", "连续未读天数", "已读期数"]
RISK_BINS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
RISK_BIN_LABELS = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]


def metadata():
    return {
        "name": "专栏续读风险试算", "short": "reader-risk",
        "tagline": "用行为窗口解释续读风险，再试算编辑关怀的覆盖边界。",
        "client": "纸岸知识出版社 · 6人内容运营组 · 320名匿名年度专栏读者",
        "workflow": "编辑每周合并阅读日志与到期续读结果，在表格中凭访问次数选择关怀对象。",
        "pains": ["各行为量纲不同，人工排序偏向高频用户", "直接使用到期后的数据会泄漏结果", "风险阈值缺少精确率与召回率依据"],
        "upstream": "到期前14日阅读行为快照 reader_window_202611.csv；新一期未到期读者的行为窗口不含续读结果",
        "downstream": "主编据验证集覆盖人数安排内容回访实验，不自动触达读者；未标注批次只输出复核名单",
        "entities": ["读者行为样本", "续读风险试验", "编辑复核简报"],
        "dataset_name": "纸岸专栏到期前14日匿名样本",
        "columns": [{"key": "reader_id", "label": "匿名读者", "type": "string"}] + [{"key": k, "label": l, "type": "number"} for k, l in zip(FEATURES, LABELS)] + [{"key": "renewed", "label": "实际续读(1/0)", "type": "number", "optional": True, "note": "未标注批次可省略；已标注批次用于训练与独立验证"}],
        "parameters": [{"key": "threshold", "label": "高风险概率阈值", "type": "number", "default": 0.5, "min": 0.1, "max": 0.9}, {"key": "regularization", "label": "模型C（越小正则越强）", "type": "number", "default": 1.0, "min": 0.01, "max": 10}],
        "modes": [
            {"value": "evaluate", "label": "带标签评估（训练并验证）", "note": "需要续读标签；固定分层75/25留出，训练模型并给出AUC、精确率和召回率。"},
            {"value": "score", "label": "复用已批准试验评分（未标注批次）", "note": "不重新训练，沿用试验训练时的标准化与回归参数；只输出概率和阈值名单。"},
        ],
        "scoring": {"title": "给未标注批次评分", "note": "选用已完成、已批准且保存模型快照的带标签试验；评分批次不参与训练，也不显示实际续读结果或验证成绩。", "parameter": "threshold"},
        "workbench_title": "续读风险阈值试验", "action_label": "训练并复核覆盖范围", "score_action_label": "沿用试验生成复核名单", "unit": "位读者",
        "accent": "oklch(53% 0.12 30)", "style": "editorial-press",
        "seed_story": ["08:40 编辑导入 reader_window_202611.csv 的320条匿名样本", "08:45 检查14日访问、完成率、未读天数和已读期数", "09:00 以0.5风险阈值创建一次续读试验", "09:01 系统固定随机种子42，分层保留25%样本做验证", "09:05 编辑比较AUC、召回率与高风险人数", "09:10 将阈值改为0.7，复核误报减少及漏报增加", "09:20 下载验证明细交主编", "10:00 管理员设置周一08:30内部复核简报", "新一期未到期读者尚无续读结果：选用09:00已批准的试验直接评分，不把待评分读者并入训练"],
        "method": "分层75/25留出；仅在训练集拟合StandardScaler和L2 logistic回归；目标为1-renewed；阈值只用于验证集决策。",
        "score_method": "复用已批准试验训练时的StandardScaler均值/标准差与L2 logistic回归系数；不重新拟合，不把评分批次样本并入训练；阈值只改变复核名单，不改变模型概率。",
        "limitations": ["模拟读者行为，不能当作真实留存效果", "相关系数与模型系数不代表因果", "未包含时间外验证或干预效果评估", "未标注批次的评分名单没有实际续读结果可核对，不能计算精确率或召回率"],
    }


def seed_records():
    rng = np.random.default_rng(1008)
    rows = []
    for i in range(320):
        sessions = int(rng.poisson(6))
        completion = float(np.clip(rng.normal(62, 21), 4, 99))
        inactive = int(rng.integers(0, 15))
        issues = int(rng.integers(1, 25))
        logit = -0.5 - 0.20 * sessions - 0.025 * (completion - 50) + 0.27 * inactive - 0.035 * issues
        risk = 1 / (1 + math.exp(-logit))
        rows.append({"reader_id": f"RD-{i+1:04}", "sessions_14d": sessions, "completion_pct": round(completion, 1), "days_inactive": inactive, "issues_read": issues, "renewed": int(rng.random() >= risk)})
    return rows


def seed_unlabeled_records(count=40, offset=320):
    rng = np.random.default_rng(202611)
    rows = []
    for i in range(count):
        rows.append({
            "reader_id": f"RD-{offset+i+1:04}",
            "sessions_14d": int(rng.poisson(6)),
            "completion_pct": round(float(np.clip(rng.normal(62, 21), 4, 99)), 1),
            "days_inactive": int(rng.integers(0, 15)),
            "issues_read": int(rng.integers(1, 25)),
        })
    return rows


def _parse_parameters(params):
    try:
        threshold = float(params.get("threshold", 0.5))
        c_value = float(params.get("regularization", 1.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("风险阈值与模型C须为有效数值。") from exc
    if not 0.1 <= threshold <= 0.9 or not 0.01 <= c_value <= 10:
        raise ValueError("风险阈值须为0.1~0.9，模型C须为0.01~10。")
    return threshold, c_value


def _feature_matrix(records, note="行为字段与续读标签必须完整且为数值。"):
    try:
        x = np.asarray([[float(row[k]) for k in FEATURES] for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(note) from exc
    if not np.isfinite(x).all() or (x < 0).any() or (x[:, 1] > 100).any():
        raise ValueError("行为值必须非负且有限，完成率0~100。")
    return x


def evaluate(records, params):
    """训练并评估带标签批次。返回兼容旧接口的结果和可复用模型快照。"""
    threshold, c_value = _parse_parameters(params)
    if len(records) < 40:
        raise ValueError("至少需要40条完整样本，以保留独立验证集。")
    x = _feature_matrix(records)
    try:
        renewed = np.asarray([float(row["renewed"]) for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("行为字段与续读标签必须完整且为数值。未标注批次请选用已批准试验评分。") from exc
    if not np.isin(renewed, [0, 1]).all():
        raise ValueError("续读标签只能为0/1。")
    y = 1 - renewed.astype(int)
    counts = np.bincount(y, minlength=2)
    if counts.min() < 8:
        raise ValueError("续读与未续读两类各至少8条样本。")
    indices = np.arange(len(records))
    train, valid = train_test_split(indices, test_size=0.25, stratify=y, random_state=42)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=c_value, max_iter=1000, random_state=42))
    model.fit(x[train], y[train])
    probability = model.predict_proba(x[valid])[:, 1]
    prediction = (probability >= threshold).astype(int)
    auc = float(roc_auc_score(y[valid], probability))
    precision = float(precision_score(y[valid], prediction, zero_division=0))
    recall = float(recall_score(y[valid], prediction, zero_division=0))
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(y[valid], prediction, labels=[0, 1]).ravel()]
    coefficients = model[-1].coef_[0]
    order = np.argsort(-probability)
    rows = [{"reader_id": str(records[int(valid[j])].get("reader_id", f"row-{int(valid[j])+1}")), "risk_pct": round(float(probability[j]) * 100, 2), "decision": "建议编辑复核" if prediction[j] else "维持观察", "actual": "未续读" if y[valid[j]] else "已续读"} for j in order]
    strongest = int(np.argmax(np.abs(coefficients)))
    scaler = model.named_steps["standardscaler"]
    classifier = model.named_steps["logisticregression"]
    snapshot = {
        "algorithm": "StandardScaler + LogisticRegression",
        "features": list(FEATURES), "labels": list(LABELS),
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scaler.scale_],
        "coef": [float(v) for v in classifier.coef_[0]],
        "intercept": float(classifier.intercept_[0]),
        "C": c_value, "threshold": threshold, "random_state": 42,
        "train_rows": int(len(train)), "validation_rows": int(len(valid)),
        "validation_checksum": checksum([records[int(i)] for i in valid]),
        "trained_at": time.time(), "dataset": None,
    }
    return {
        "result": {
            "mode": "evaluate",
            "summary": f"训练{len(train)}条、独立验证{len(valid)}条；阈值{threshold:.2f}下有{int(prediction.sum())}位进入编辑复核。",
            "metrics": [{"label": "验证AUC", "value": round(auc, 4)}, {"label": "风险召回率", "value": round(recall * 100, 2), "unit": "%"}, {"label": "风险精确率", "value": round(precision * 100, 2), "unit": "%"}, {"label": "验证集高风险", "value": int(prediction.sum()), "unit": "人"}],
            "table": {"columns": [{"key": "reader_id", "label": "匿名读者"}, {"key": "risk_pct", "label": "风险概率(%)"}, {"key": "decision", "label": "阈值决策"}, {"key": "actual", "label": "留出集实际结果"}], "rows": rows},
            "chart": {"type": "bar", "labels": LABELS, "series": [{"name": "标准化log-odds系数", "values": [round(float(v), 4) for v in coefficients]}]},
            "findings": [f"验证混淆矩阵：命中未续读{tp}、误报{fp}、漏报{fn}、正确排除{tn}。", f"绝对系数最大的特征为{LABELS[strongest]}（{float(coefficients[strongest]):.3f}）；正值意味着更高未续读风险。", f"验证准确率{accuracy_score(y[valid], prediction)*100:.1f}%；阈值变更影响覆盖边界，不改变AUC。"],
            "method": metadata()["method"], "warnings": ["风险排序供编辑复核使用，不能据此断言某项行为导致未续读。"],
        },
        "model": snapshot,
    }


def analyze(records, params):
    """原有带标签评估入口：保持原有返回结构，继续可用。"""
    return evaluate(records, params)["result"]


def score(records, model_snapshot, params, scoring_dataset, source_job):
    """用试验训练时的模型给未标注批次评分；不拟合、不使用任何续读标签。"""
    try:
        threshold = float(params.get("threshold", 0.5))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("风险阈值须为有效数值。") from exc
    if not 0.1 <= threshold <= 0.9:
        raise ValueError("风险阈值须为0.1~0.9。")
    if not model_snapshot:
        raise ValueError("所选试验没有保存可复用的模型快照，无法评分；请重新运行一次带标签评估。")
    if list(model_snapshot.get("features") or []) != list(FEATURES):
        raise ValueError("试验模型的特征口径与当前评分字段不一致，无法复用；请重新训练。")
    if len(records) < 1:
        raise ValueError("评分批次至少需要1条样本。")
    x = _feature_matrix(records, "评分批次行为字段必须完整且为数值；评分不需要续读标签。")
    try:
        mean = np.asarray(model_snapshot["mean"], dtype=float)
        scale = np.asarray(model_snapshot["scale"], dtype=float)
        coef = np.asarray(model_snapshot["coef"], dtype=float)
        intercept = float(model_snapshot["intercept"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("试验模型快照不完整，无法评分；请重新训练。") from exc
    if not (mean.size == scale.size == coef.size == len(FEATURES)):
        raise ValueError("试验模型快照维度不正确，无法评分；请重新训练。")
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.isfinite(coef).all():
        raise ValueError("试验模型快照包含非有限数值，无法评分；请重新训练。")
    scale = np.where(scale == 0, 1.0, scale)
    probability = expit(((x - mean) / scale) @ coef + intercept)
    prediction = (probability >= threshold).astype(int)
    order = np.argsort(-probability)
    rows = [{
        "reader_id": str(records[int(i)].get("reader_id", f"row-{int(i)+1}")),
        "risk_pct": round(float(probability[int(i)]) * 100, 2),
        "decision": "建议编辑复核" if prediction[int(i)] else "维持观察",
    } for i in order]
    bins = [0] * len(RISK_BINS)
    for value in probability:
        for b, (low, high) in enumerate(RISK_BINS):
            if low <= value * 100 < high or (b == len(RISK_BINS) - 1 and value * 100 >= high):
                bins[b] += 1
                break
    selected = int(prediction.sum())
    coverage = selected / len(records) * 100
    source = source_job or {}
    training_dataset = model_snapshot.get("dataset") or {}
    provenance = {
        "mode": "score",
        "scoring_scope": "unlabeled_batch",
        "model_reused": True,
        "training_job_id": source.get("id"),
        "training_job_name": source.get("name"),
        "training_dataset_id": training_dataset.get("id"),
        "training_dataset_name": training_dataset.get("name"),
        "training_dataset_checksum": training_dataset.get("checksum"),
        "training_rows": model_snapshot.get("train_rows"),
        "validation_rows": model_snapshot.get("validation_rows"),
        "model_trained_at": model_snapshot.get("trained_at"),
        "scoring_dataset_id": (scoring_dataset or {}).get("id"),
        "scoring_dataset_name": (scoring_dataset or {}).get("name"),
        "scoring_dataset_checksum": (scoring_dataset or {}).get("checksum"),
        "scored_rows": len(records),
        "threshold": threshold,
        "regularization": model_snapshot.get("C"),
        "features": list(FEATURES),
    }
    return {
        "mode": "score",
        "summary": f"已沿用试验「{source.get('name') or '未命名试验'}」训练时的模型，对未标注批次「{(scoring_dataset or {}).get('name') or '未命名批次'}」评分：{len(records)}位读者中，阈值{threshold:.2f}下{selected}位进入编辑复核。",
        "metrics": [{"label": "评分批次样本", "value": len(records), "unit": "人"}, {"label": "进入编辑复核", "value": selected, "unit": "人"}, {"label": "复核覆盖率", "value": round(coverage, 2), "unit": "%"}],
        "table": {"columns": [{"key": "reader_id", "label": "匿名读者"}, {"key": "risk_pct", "label": "风险概率(%)"}, {"key": "decision", "label": "阈值决策"}], "rows": rows},
        "chart": {"type": "bar", "labels": RISK_BIN_LABELS, "series": [{"name": "本批次评分人数", "values": bins}]},
        "findings": [f"本批次未提供续读标签，仅输出风险概率与复核名单，不计算AUC、精确率或召回率。", f"阈值{threshold:.2f}只决定进入复核的名单边界；同一试验模型的风险概率不随阈值改变。", f"评分批次共{len(records)}位读者，其中{selected}位建议编辑复核、{len(records)-selected}位维持观察。"],
        "method": metadata()["score_method"],
        "warnings": ["未标注批次无法核对实际续读结果，本名单不能当作模型准确率证据。", "风险排序供编辑复核使用，不能据此断言某项行为导致未续读。"],
        "provenance": provenance,
    }


def evaluation_provenance(job_id, job_name, dataset_meta, params, model_snapshot):
    """新训练的带标签评估也保存来源、批次与阈值，便于结果页和下载核对。

    验证成绩只来自训练集之外的分层留出子集；评分批次即训练来源批次，不外推。
    """
    dataset_meta = dataset_meta or {}
    return {
        "mode": "evaluate",
        "model_reused": False,
        "training_job_id": job_id,
        "training_job_name": job_name,
        "training_dataset_id": dataset_meta.get("id"),
        "training_dataset_name": dataset_meta.get("name"),
        "training_dataset_checksum": dataset_meta.get("checksum"),
        "training_rows": model_snapshot.get("train_rows"),
        "validation_rows": model_snapshot.get("validation_rows"),
        "model_trained_at": model_snapshot.get("trained_at"),
        "scoring_dataset_id": dataset_meta.get("id"),
        "scoring_dataset_name": dataset_meta.get("name"),
        "scoring_dataset_checksum": model_snapshot.get("validation_checksum") or dataset_meta.get("checksum"),
        "scored_rows": model_snapshot.get("validation_rows"),
        "scoring_scope": "validation_split",
        "scoring_dataset_label": "训练批次的分层验证子集",
        "threshold": float(params.get("threshold", 0.5)),
        "regularization": model_snapshot.get("C"),
        "features": list(FEATURES),
    }
