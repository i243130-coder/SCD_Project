# 0002 — The "learning" dimension is scored by the Feasibility scorer

- **Status:** Accepted
- **Context:** The PDF has 6 dimensions but 4 scorer agents. `learning` (portfolio/CV value) depends on the student's skills, interests and goal — the same inputs the Feasibility scorer already loads.
- **Options:** (1) a 5th scorer, (2) score learning inside the Risk scorer, (3) score it inside the Feasibility scorer.
- **Decision:** (3). The Feasibility scorer returns two `DimensionScore`s: `feasibility` and `learning`. Likewise Competition returns `competition` and `differentiation`.
- **Why:** keeps the required 4 parallel scorers; one retrieval and one profile load serve both dimensions; fewer model calls.
- **Cost:** the feasibility scorer's rubric prompt is longer; a feasibility timeout makes both dimensions abstain.
- **AI use:** Drafted by AI (Claude via Claude Code); TODO(human): review and confirm.
