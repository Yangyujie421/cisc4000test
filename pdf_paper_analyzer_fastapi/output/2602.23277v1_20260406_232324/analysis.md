# Analysis Report for 2602.23277v1_20260406_232324
_Generated at 20260406_232623_

## Introduction
- motivation1【In many networked systems the decision maker (leader) must tune parameters while followers choose discrete combinatorial strategies, so Stackelberg control in combinatorial congestion games needs to be addressed.】
- motivation2【The leader’s system-level objective evaluated at the follower equilibrium is typically nonsmooth because small parameter changes can abruptly change which combinatorial strategies are used, making differentiation through equilibria unrealistic.】
- motivation3【Prior approaches that differentiate through approximate equilibrium solvers can fail to provide guarantees for the true nonsmooth hyper-objective and require careful control of equilibrium approximation error and bias.】
- motivation4【Strategy sets in combinatorial games can be exponentially large and imbalanced, so scalable optimization and sampling approaches are needed to avoid vanishing probability of including the strategies that determine equilibria.】

## Method
**Overall Framework**: [An inner Frank–Wolfe loop computes Wardrop equilibria via a combinatorial linear-minimization oracle (exact or subsampled using ZDDs), and an outer zeroth-order randomized-smoothing loop optimizes the leader parameter using two-point finite-difference estimates of the smoothed hyper-objective.]

**Key Steps**:
    1.  **Inner Equilibrium Solver (Frank–Wolfe)**: [Run T iterations of projection-free Frank–Wolfe on the Beckmann potential f(θ, ·) to approximate the Wardrop equilibrium y⋆(θ), using short-step or exact line-search updates and reporting the FW duality gap gt.]
    2.  **Combinatorial Linear Minimization Oracle (LMO)**: [Implement the LMO required by Frank–Wolfe either exactly (poly-time cases via shortest-path; NP-hard cases via a prebuilt ZDD and a bottom-up DP to find the min-cost root-to-⊤ path) or approximately by sampling m feasible strategies from the ZDD and returning the best sample.]
    3.  **ZDD-based Sampling (if subsampling LMO used)**: [Construct a zero-suppressed decision diagram once and use it for (i) uniform-strategy sampling, or (ii) length-stratified sampling (Uniform Length or Harmonic Length) by computing node counts or length-refined counts and performing randomized root-to-⊤ traversals to produce m candidate strategies per FW step.]
    4.  **Outer Zeroth-Order Optimization (ZOS)**: [Apply randomized-ball smoothing to the hyper-objective Φ, estimate ∇Φρ using a mini-batched two-point finite-difference estimator (direction batch size B, smoothing radius ρ) with symmetric queries bΦT(θ±ρu), and perform projected gradient-type updates θ ← ΠΘ(θ − η bgt) with step-size η.]
    5.  **Error control and practical deployment**: [Control inner approximation error via mean-square bounds on ∥yT(θ) − y⋆(θ)∥2 (depending on κm, Lf,2, α, etc.), choose m, B, ρ, η, and T to balance subsampling variance and inner accuracy, and parallelize function evaluations and ZDD sampling in implementation.]

**Technical Innovations**: [Keep the equilibrium solver as a nondifferentiable black box and handle resulting kinks in the hyper-objective via a zeroth-order randomized-smoothing outer loop (two-point estimator), avoiding differentiating through equilibria; and introduce a ZDD-based subsampled LMO with length-stratified sampling and an optimizer-hit probability κm to obtain explicit convergence rates for the inner Frank–Wolfe and propagate its error into outer Goldstein-stationarity guarantees.]

## Results
**Results Overview**: Across all tested scenarios, ZOS achieves low Frank–Wolfe (FW) gaps and low social cost while being roughly 20–1000× faster per outer iteration and using at most 1.7 GiB peak RSS, compared with Diff which uses 10–194 GiB and is often far slower or infeasible.

**Key Metrics**:
1. Overall: ZOS attains low FW gaps and low social cost; speedups ≈20–1000× per outer iteration; peak RSS ≤1.7 GiB vs Diff’s 10–194 GiB.
2. Scenario 1 (polynomial-time, exact shortest-path oracle): FW gap ≈2×10−2 (Diff-level) with comparable social cost; ≈23× speedup; peak RSS reduced from 10.2 GiB (Diff) to 0.28 GiB (ZOS).
3. Scenario 2 (NP-hard but tractable ZDD): FW gap ≈10−2 (matching Diff) with comparable social cost; ≈61× speedup; peak RSS 0.37 GiB (ZOS) vs 15.9 GiB (Diff). Subsampling variants obtain similar social cost but their FW gaps plateau around 100 and they give little speedup over exact ZOS–ZDD.
4. Scenario 3 (NP-hard, massive ZDD): Stratified sampling schemes (UL/HL) reach FW gap ≈10−3 at m = 1000 and match exact ZOS–ZDD in social cost; UL/HL at m=1000 are ≈6–7× faster than exact ZOS–ZDD and add <1 GiB memory, whereas exact ZOS–ZDD costs ≈37 s per outer iteration. Diff is impractical here: peak RSS ≈194 GiB and failed to complete more than five outer iterations within 10 hours.
5. Methodological note: social-cost comparisons are considered meaningful only at small FW gaps (so reported social-cost parity is tied to cases with sufficiently small FW gaps).

**Evidence & Analysis**: The results are supported by reported FW gaps, social-cost comparisons, per-iteration runtimes, and peak RSS values (referenced Figures 1–2). The reported performance gains for ZOS are explained by two implementation/design factors: (a) treating the equilibrium computation as a black box (avoiding backprop through T = 3000 inner steps) and (b) parallelizing independent equilibrium solves and sampled-strategy evaluations—both of which plausibly reduce runtime and memory compared with Diff, which backpropagates through inner iterations and the ZDD. Scenario-specific analyses further support the claims: when an exact shortest-path oracle is available (Scenario 1) or the ZDD is small (Scenario 2, e.g., <10^5 nodes), exact ZOS–ZDD matches Diff in FW gap and social cost while being far cheaper; when the ZDD is massive (Scenario 3), stratified sampling (UL/HL) effectively concentrates on low-cardinality strata (justified by nonnegative weights) and substantially improves optimizer hit-rate versus uniform sampling. Weaknesses in the presented evidence include lack of reported variance/confidence intervals, limited reporting of absolute runtimes across all settings (only some values given), and no hardware/specification details in the excerpt to contextualize runtime/memory numbers. Results also depend on problem structure (e.g., nonnegative weights, ZDD tractability) and chosen sampling sizes (m); performance degrades or requires large m in some regimes (subsampling plateaus or exact solves become expensive).

**Limitations**:
- Subsampling variants can plateau in FW gap (e.g., around 100 in Scenario 2) and may offer little speedup unless conditions are favorable.
- Stratified sampling requires sufficiently large sample size (e.g., m ≈1000) to match exact ZOS–ZDD accuracy.
- Exact ZOS–ZDD remains expensive when the ZDD is massive (≈37 s per outer iteration reported).
- Diff can be impractical due to very high memory use (10–194 GiB) and long runtimes (failed to progress in Scenario 3).
- Results depend on problem structure (nonnegative weights, ZDD size) and specifics not detailed here (hardware, variance measures, broader baselines).
