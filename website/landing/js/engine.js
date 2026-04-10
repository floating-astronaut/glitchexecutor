document.getElementById('engineContent').innerHTML = `
  <div class="reveal">
    <span class="section-label">Under the hood</span>
    <h2 class="section-heading">Inside the engine</h2>
    <p class="section-subheading">Five layers of analysis, zero guesswork. Here's how Glitch Executor reads BTC — conceptually, not the secret sauce.</p>
  </div>
  <div class="engine-steps">
    <div class="engine-step reveal">
      <div class="engine-step-num">01</div>
      <div>
        <div class="engine-step-title">Data Intake</div>
        <div class="engine-step-desc">
          <p>Pulls BTC price history, on-chain metrics, market depth and liquidity data, and macro sentiment inputs from text and feeds.</p>
          <p>Cleans and normalizes everything. Removes noise, outliers, and junk signals before anything touches a model.</p>
        </div>
      </div>
    </div>
    <div class="engine-step reveal">
      <div class="engine-step-num">02</div>
      <div>
        <div class="engine-step-title">LLM Ensemble</div>
        <div class="engine-step-desc">
          <p>Multiple premium LLM models analyze the same BTC context from different angles: trend, momentum, narrative, sentiment, and risk.</p>
          <p>Models contribute to a combined view — not a single black-box verdict. Think of it as a panel of analysts that never sleep and never get emotional.</p>
        </div>
      </div>
    </div>
    <div class="engine-step reveal">
      <div class="engine-step-num">03</div>
      <div>
        <div class="engine-step-title">Quant & Pattern Recognition</div>
        <div class="engine-step-desc">
          <p>Detects recurring structures across volatility regimes, trend shifts, mean-reversion zones, breakout conditions, and liquidity pockets.</p>
          <p>Runs scenario simulations: What if volatility spikes? What if volume dries up? What if we see the same pattern as three cycles ago?</p>
        </div>
      </div>
    </div>
    <div class="engine-step reveal">
      <div class="engine-step-num">04</div>
      <div>
        <div class="engine-step-title">Risk & Scenario Scoring</div>
        <div class="engine-step-desc">
          <p>Converts raw analysis into scenario probabilities — bullish, neutral, bearish — with likely ranges, time windows, and risk-reward bands.</p>
          <p>Flags asymmetric setups. Also flags when doing nothing is better than forcing a trade.</p>
        </div>
      </div>
    </div>
    <div class="engine-step reveal">
      <div class="engine-step-num">05</div>
      <div>
        <div class="engine-step-title">Signal & Automation</div>
        <div class="engine-step-desc">
          <p>Outputs clear, structured insights: key levels, bias, confidence, and what to watch next.</p>
          <p>For users who connect automation, translates views into machine-executable rules within their risk preferences.</p>
        </div>
      </div>
    </div>
  </div>
`;
