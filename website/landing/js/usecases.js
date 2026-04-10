document.getElementById('usecasesContent').innerHTML = `
  <div class="reveal" style="text-align:center;">
    <span class="section-label">Real usage</span>
    <h2 class="section-heading">How traders actually use Glitch Executor</h2>
    <p class="section-subheading" style="margin-left:auto;margin-right:auto;">Not fake testimonials. Just realistic scenarios of how the engine fits different styles.</p>
  </div>
  <div class="usecases-grid reveal">

    <div class="usecase-card">
      <div class="usecase-icon"><i class="fa-solid fa-bolt"></i></div>
      <div class="usecase-title">The Intraday Scalper</div>
      <div class="usecase-desc">
        Uses Pro tier. Checks the dashboard before sessions. Leans on volatility regimes and key levels. Runs semi-autonomous strategies with tight position sizes. Doesn't need a guru — needs a framework.
      </div>
    </div>

    <div class="usecase-card">
      <div class="usecase-icon"><i class="fa-solid fa-wave-square"></i></div>
      <div class="usecase-title">The Swing Trader</div>
      <div class="usecase-desc">
        Mix of Basic and Pro. Uses the 3x weekly analysis to plan entries and exits over days, not minutes. Relies on scenario probabilities for position sizing and patience. Lets the engine do the pattern-matching.
      </div>
    </div>

    <div class="usecase-card">
      <div class="usecase-icon"><i class="fa-solid fa-couch"></i></div>
      <div class="usecase-title">The "I Don't Have Time" User</div>
      <div class="usecase-desc">
        Full System applicant. Wants the engine plus an account manager to run the show within strict risk limits. Checks in once a week. Sleeps fine at night.
      </div>
    </div>

  </div>
`;
