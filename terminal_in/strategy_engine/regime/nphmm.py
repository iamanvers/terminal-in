"""
Pure-NumPy Gaussian HMM — drop-in for the hmmlearn subset this app uses.

Why: hmmlearn ships no wheel for Python 3.14 on Windows and needs MSVC to
build. The classifier only needs fit / predict / predict_proba / score with
Gaussian emissions, which is standard Baum-Welch + Viterbi — implemented
here in log space with full covariances. Picklable (plain numpy attrs), so
hmm_model.pkl keeps working through RegimeClassifier unchanged.

Interface parity with hmmlearn.hmm.GaussianHMM (the parts we call):
  model.fit(X, lengths)           — EM training
  model.predict(X, lengths)       — Viterbi state sequence
  model.predict_proba(X, lengths) — posterior state probabilities (gamma)
  model.score(X)                  — total log-likelihood
  model.means_                    — (K, D) emission means (state naming)
"""

import logging

import numpy as np

log = logging.getLogger(__name__)

_LOG2PI = np.log(2.0 * np.pi)


def _logsumexp(a: np.ndarray, axis: int | None = None) -> np.ndarray:
    m = np.max(a, axis=axis, keepdims=True)
    out = m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True))
    return np.squeeze(out, axis=axis) if axis is not None else float(np.squeeze(out))


class GaussianHMM:
    def __init__(self, n_components: int = 6, n_iter: int = 200, tol: float = 1e-4,
                 random_state: int = 42, reg_covar: float = 1e-6):
        self.n_components = n_components
        self.n_iter = n_iter
        self.tol = tol
        self.random_state = random_state
        self.reg_covar = reg_covar
        self.means_: np.ndarray | None = None        # (K, D)
        self.covars_: np.ndarray | None = None       # (K, D, D)
        self.startprob_: np.ndarray | None = None    # (K,)
        self.transmat_: np.ndarray | None = None     # (K, K)

    # ── emission log-densities ────────────────────────────────────────────────
    def _log_density(self, X: np.ndarray) -> np.ndarray:
        """(n, K) log N(x | mean_k, cov_k) via Cholesky."""
        n, d = X.shape
        out = np.empty((n, self.n_components))
        for k in range(self.n_components):
            cov = self.covars_[k] + np.eye(d) * self.reg_covar
            chol = np.linalg.cholesky(cov)            # lower-triangular L, cov = L Lᵀ
            diff = X - self.means_[k]
            sol = np.linalg.solve(chol, diff.T)       # L⁻¹ diffᵀ  → Mahalanobis
            maha = np.sum(sol ** 2, axis=0)
            logdet = 2.0 * np.sum(np.log(np.diag(chol)))
            out[:, k] = -0.5 * (d * _LOG2PI + logdet + maha)
        return out

    # ── forward-backward in log space ─────────────────────────────────────────
    def _forward(self, logb: np.ndarray) -> np.ndarray:
        n, k = logb.shape
        la = np.empty((n, k))
        la[0] = np.log(self.startprob_ + 1e-300) + logb[0]
        logt = np.log(self.transmat_ + 1e-300)
        for t in range(1, n):
            la[t] = logb[t] + _logsumexp(la[t - 1][:, None] + logt, axis=0)
        return la

    def _backward(self, logb: np.ndarray) -> np.ndarray:
        n, k = logb.shape
        lb = np.zeros((n, k))
        logt = np.log(self.transmat_ + 1e-300)
        for t in range(n - 2, -1, -1):
            lb[t] = _logsumexp(logt + (logb[t + 1] + lb[t + 1])[None, :], axis=1)
        return lb

    @staticmethod
    def _split(X: np.ndarray, lengths) -> list[np.ndarray]:
        if not lengths:
            return [X]
        seqs, i = [], 0
        for ln in lengths:
            seqs.append(X[i:i + ln])
            i += ln
        return seqs

    # ── EM (Baum-Welch) ──────────────────────────────────────────────────────
    def fit(self, X: np.ndarray, lengths: list[int] | None = None) -> 'GaussianHMM':
        X = np.asarray(X, dtype=float)
        n, d = X.shape
        K = self.n_components
        rng = np.random.default_rng(self.random_state)

        # init: k-means means (sklearn has py3.14 wheels), sticky transitions —
        # regimes persist, so a sticky prior converges to sensible dynamics
        try:
            from sklearn.cluster import KMeans
            km = KMeans(n_clusters=K, n_init=10, random_state=self.random_state).fit(X)
            self.means_ = km.cluster_centers_.copy()
            labels = km.labels_
        except Exception:
            idx = rng.choice(n, size=K, replace=False)
            self.means_ = X[idx].copy()
            labels = rng.integers(0, K, size=n)
        base_cov = np.cov(X.T) + np.eye(d) * self.reg_covar
        self.covars_ = np.array([
            (np.cov(X[labels == k].T) + np.eye(d) * self.reg_covar)
            if np.sum(labels == k) > d + 1 else base_cov.copy()
            for k in range(K)
        ])
        self.startprob_ = np.full(K, 1.0 / K)
        self.transmat_ = np.full((K, K), 0.10 / max(K - 1, 1))
        np.fill_diagonal(self.transmat_, 0.90)

        seqs = self._split(X, lengths)
        prev_ll = -np.inf
        for it in range(self.n_iter):
            ll_total = 0.0
            g_sum = np.zeros(K)                 # sum of gamma over all t
            g_first = np.zeros(K)               # gamma at t=0 (per sequence)
            xi_sum = np.zeros((K, K))
            mean_num = np.zeros((K, d))         # Σ gamma·x          (1st moment)
            sec_num = np.zeros((K, d, d))       # Σ gamma·x·xᵀ       (2nd moment)
            logt = np.log(self.transmat_ + 1e-300)

            for seq in seqs:
                logb = self._log_density(seq)
                la = self._forward(logb)
                lb = self._backward(logb)
                ll = _logsumexp(la[-1], axis=None)
                ll_total += ll
                gamma = np.exp(la + lb - ll)   # (n, K)

                g_first += gamma[0]
                g_sum += gamma.sum(axis=0)
                mean_num += gamma.T @ seq
                for t in range(len(seq) - 1):
                    lxi = la[t][:, None] + logt + (logb[t + 1] + lb[t + 1])[None, :] - ll
                    xi_sum += np.exp(lxi)
                for k in range(K):
                    sec_num[k] += (gamma[:, k, None] * seq).T @ seq

            # M-step
            self.startprob_ = g_first / max(len(seqs), 1)
            self.startprob_ /= self.startprob_.sum()
            denom = xi_sum.sum(axis=1, keepdims=True)
            self.transmat_ = np.where(denom > 0, xi_sum / np.maximum(denom, 1e-300),
                                      self.transmat_)
            self.transmat_ /= self.transmat_.sum(axis=1, keepdims=True)
            # cov = E[xxᵀ] − μμᵀ — computed around the UPDATED means (standard EM)
            new_means = mean_num / np.maximum(g_sum[:, None], 1e-300)
            self.covars_ = np.empty((K, d, d))
            for k in range(K):
                exx = sec_num[k] / max(g_sum[k], 1e-300)
                self.covars_[k] = exx - np.outer(new_means[k], new_means[k]) \
                    + np.eye(d) * self.reg_covar
            self.means_ = new_means

            if abs(ll_total - prev_ll) < self.tol * max(abs(prev_ll), 1.0):
                log.info('nphmm EM converged at iter %d (loglik %.2f)', it, ll_total)
                break
            prev_ll = ll_total
        else:
            log.info('nphmm EM hit n_iter=%d (loglik %.2f)', self.n_iter, prev_ll)
        return self

    # ── inference ─────────────────────────────────────────────────────────────
    def predict(self, X: np.ndarray, lengths: list[int] | None = None) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        out = []
        logt = np.log(self.transmat_ + 1e-300)
        for seq in self._split(X, lengths):
            logb = self._log_density(seq)
            n, K = logb.shape
            delta = np.empty((n, K))
            psi = np.zeros((n, K), dtype=int)
            delta[0] = np.log(self.startprob_ + 1e-300) + logb[0]
            for t in range(1, n):
                cand = delta[t - 1][:, None] + logt
                psi[t] = np.argmax(cand, axis=0)
                delta[t] = np.max(cand, axis=0) + logb[t]
            path = np.empty(n, dtype=int)
            path[-1] = int(np.argmax(delta[-1]))
            for t in range(n - 2, -1, -1):
                path[t] = psi[t + 1][path[t + 1]]
            out.append(path)
        return np.concatenate(out)

    def predict_proba(self, X: np.ndarray, lengths: list[int] | None = None) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        out = []
        for seq in self._split(X, lengths):
            logb = self._log_density(seq)
            la = self._forward(logb)
            lb = self._backward(logb)
            ll = _logsumexp(la[-1], axis=None)
            out.append(np.exp(la + lb - ll))
        return np.vstack(out)

    def score(self, X: np.ndarray, lengths: list[int] | None = None) -> float:
        X = np.asarray(X, dtype=float)
        total = 0.0
        for seq in self._split(X, lengths):
            la = self._forward(self._log_density(seq))
            total += _logsumexp(la[-1], axis=None)
        return float(total)
