"""
FinBERT sentiment scorer.
Model: ProsusAI/finbert — fine-tuned BERT for financial text.
Loads once on first call; ~440MB download on first use.
"""

import logging
import time
from threading import Lock
from typing import Optional

from terminal_in.news import macro as _macro

log = logging.getLogger(__name__)

_model = None
_tokenizer = None
_lock = Lock()
_available = True  # set False if torch/transformers not installed

_WARN_INTERVAL_S = 300
_last_warn = 0.0


def _warn_degraded():
    """Rate-limited WARN so a disabled FinBERT is visible in logs during use,
    not just once at import time."""
    global _last_warn
    now = time.monotonic()
    if now - _last_warn >= _WARN_INTERVAL_S:
        _last_warn = now
        log.warning('FinBERT unavailable — sentiment scores defaulting to neutral/0.0 '
                    '(signals using the NEWS lens are degraded)')


def status() -> dict:
    """Current sentiment engine status for /api/health."""
    return {
        'mode': 'finbert' if (_available and _model is not None) else
                ('finbert_lazy' if _available else 'disabled'),
        'available': _available,
        'loaded': _model is not None,
    }


def _load():
    global _model, _tokenizer, _available
    if _model is not None:
        return
    try:
        from transformers import BertForSequenceClassification, BertTokenizer
        import torch  # noqa: F401

        log.info('Loading FinBERT model (first run downloads ~440MB)...')
        _tokenizer = BertTokenizer.from_pretrained('ProsusAI/finbert')
        _model = BertForSequenceClassification.from_pretrained('ProsusAI/finbert')
        _model.eval()
        log.info('FinBERT loaded.')
    except ImportError:
        log.warning('transformers/torch not installed — news sentiment disabled')
        _available = False
    except Exception:
        log.exception('Failed to load FinBERT')
        _available = False


LABEL_MAP = {0: 'positive', 1: 'negative', 2: 'neutral'}


def _finbert_score(text: str) -> dict:
    """Raw FinBERT label+confidence; neutral/0.0 when the model is unavailable."""
    if not _available:
        _warn_degraded()
        return {'sentiment': 'neutral', 'score': 0.0}

    with _lock:
        _load()

    if not _available or _model is None:
        _warn_degraded()
        return {'sentiment': 'neutral', 'score': 0.0}

    try:
        import torch

        inputs = _tokenizer(
            text, return_tensors='pt', truncation=True,
            max_length=512, padding=True,
        )
        with torch.no_grad():
            logits = _model(**inputs).logits
        probs = torch.softmax(logits, dim=1)[0]
        label_idx = int(probs.argmax())
        return {
            'sentiment': LABEL_MAP[label_idx],
            'score': float(probs[label_idx]),
        }
    except Exception:
        log.exception('FinBERT inference failed for text: %.80s', text)
        return {'sentiment': 'neutral', 'score': 0.0}


def score(text: str) -> dict:
    """Sentiment for a headline+body, India-context aware.

    Returns {'sentiment': 'positive'|'negative'|'neutral', 'score': float} plus, when an
    India-macro prior overrides FinBERT, 'macro_rule' (the rule name) and 'finbert' (what
    FinBERT alone said) — so the override is transparent (data honesty), never silent.

    FinBERT alone misreads macro direction for Indian equities (a weaker rupee or a fuel-
    price drop carry the OPPOSITE sign of their surface verb). The macro layer corrects
    those well-established cases and runs even when FinBERT is offline (pure rules)."""
    base = _finbert_score(text)
    macro = _macro.adjust(text)
    if macro is not None:
        return {'sentiment': macro['sentiment'], 'score': macro['score'],
                'macro_rule': macro['rule'], 'finbert': base['sentiment']}
    return base
