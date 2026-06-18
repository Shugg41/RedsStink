"""
lock.py — league-wide strikeout "Lock of the Day" selection (pure logic).

No Streamlit / no network. Given pitcher candidates (each with a K projection,
the DraftKings line, and prices), this models the over/under probability with a
Poisson distribution (strikeouts are count data, so Poisson is the natural fit),
computes expected value against the posted price, applies confidence guardrails,
and ranks to find the single best play.
"""
import math

from engine import american_to_decimal, american_to_implied_prob

# Tunables
K_PROP_MIN_EDGE = 0.5    # min projected-K edge vs the line to qualify
CONF_HIGH       = 0.66   # model win prob for a HIGH-confidence label
CONF_MED        = 0.58   # ...and MEDIUM (also the guardrail floor for a lock)


# ------------------------------------------------------------
# Poisson model for strikeouts
# ------------------------------------------------------------
def _poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def poisson_cdf(k, lam):
    """P(X <= k) for X ~ Poisson(lam)."""
    k = int(math.floor(k))
    if k < 0:
        return 0.0
    return min(1.0, sum(_poisson_pmf(i, lam) for i in range(0, k + 1)))

def prob_over(line, lam):
    """P(strikeouts clear the line) under Poisson(lam). For a standard x.5 line
    this is exact; for an integer line the push is treated as not-cleared
    (need >= line+1)."""
    thresh = math.floor(line)            # must record >= thresh+1 to win the over
    return max(0.0, min(1.0, 1.0 - poisson_cdf(thresh, lam)))


# ------------------------------------------------------------
# EV / confidence
# ------------------------------------------------------------
def ev_per_unit(prob, decimal_odds):
    """Expected profit on a 1-unit bet. None if odds missing/invalid."""
    if not decimal_odds or decimal_odds <= 1.0:
        return None
    return prob * (decimal_odds - 1.0) - (1.0 - prob)

def confidence_label(prob):
    if prob >= CONF_HIGH:
        return "HIGH"
    if prob >= CONF_MED:
        return "MEDIUM"
    return "LOW"


# ------------------------------------------------------------
# Candidate scoring + selection
# ------------------------------------------------------------
def score_candidate(c, sides="both"):
    """Score one pitcher candidate. `c` needs at least `projection` and `line`;
    optional `over_price`, `under_price`, `opener`, `data_ok`, plus passthrough
    metadata. Returns an augmented copy, or None if unscoreable."""
    try:
        proj = float(c["projection"])
        line = float(c["line"])
    except (TypeError, ValueError, KeyError):
        return None

    p_over = prob_over(line, proj)
    p_under = 1.0 - p_over

    over_dec  = american_to_decimal(c["over_price"])  if c.get("over_price")  is not None else None
    under_dec = american_to_decimal(c["under_price"]) if c.get("under_price") is not None else None
    over_ev   = ev_per_unit(p_over, over_dec)
    under_ev  = ev_per_unit(p_under, under_dec)

    options = []
    if sides in ("both", "over"):
        options.append(("Over",  p_over,  c.get("over_price"),  over_ev))
    if sides in ("both", "under"):
        options.append(("Under", p_under, c.get("under_price"), under_ev))
    if not options:
        return None

    # Pick the side by EV when priced, else by how far the model sits from a coin flip.
    def keyfn(o):
        _, prob, _, evv = o
        return evv if evv is not None else (prob - 0.5)
    side, prob, price, evv = max(options, key=keyfn)

    implied  = american_to_implied_prob(price) if price is not None else None
    edge_k   = (proj - line) if side == "Over" else (line - proj)
    edge_prob = (prob - implied) if implied is not None else None

    out = dict(c)
    out.update({
        "side": side,
        "model_prob": round(prob, 4),
        "implied_prob": round(implied, 4) if implied is not None else None,
        "edge_k": round(edge_k, 2),
        "edge_prob": round(edge_prob, 4) if edge_prob is not None else None,
        "ev": round(evv, 4) if evv is not None else None,
        "confidence": confidence_label(prob),
        "price": price,
        # rank by EV when we have a price, else by model edge over a coin flip
        "rank_score": evv if evv is not None else (prob - 0.5),
    })
    return out

def select_locks(candidates, sides="both", guardrails=True, top_n=5,
                 min_prob=CONF_MED, min_edge=K_PROP_MIN_EDGE):
    """Score, filter, and rank candidates. Returns (lock, shortlist)."""
    scored = []
    for c in candidates:
        s = score_candidate(c, sides=sides)
        if s is None:
            continue
        if guardrails:
            if s.get("opener"):
                continue
            if not s.get("data_ok", True):
                continue
            if abs(s["edge_k"]) < min_edge:
                continue
            if s["model_prob"] < min_prob:
                continue
        scored.append(s)
    scored.sort(key=lambda x: (x["rank_score"] if x["rank_score"] is not None else -1e9),
                reverse=True)
    lock = scored[0] if scored else None
    return lock, scored[:top_n]
