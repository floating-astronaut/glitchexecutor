document.getElementById('pricingContent').innerHTML = `
  <div class="reveal" style="text-align:center;">
    <span class="section-label">Plans</span>
    <h2 class="section-heading">Pricing</h2>
    <p class="section-subheading" style="margin-left:auto;margin-right:auto;">Pick the level that matches how you trade. No lock-in. Upgrade or downgrade anytime.</p>
    
    <!-- Billing Toggle -->
    <div class="pricing-toggle-wrapper">
      <span class="toggle-label active" id="toggleMonthly">Monthly</span>
      <label class="pricing-toggle">
        <input type="checkbox" id="billingToggle">
        <span class="toggle-slider"></span>
      </label>
      <span class="toggle-label" id="toggleYearly">Yearly <span class="toggle-discount">-40%</span></span>
    </div>
  </div>
  
  <div class="pricing-grid reveal">

    <!-- Basic -->
    <div class="pricing-card">
      <span class="pricing-badge launch">Launch offer</span>
      <div class="pricing-tier">Basic</div>
      <div class="pricing-name">Starter access</div>
      <div class="pricing-amount-wrapper">
        <span class="original-price" style="display:none;text-decoration:line-through !important;color:#64748b;font-size:1.5rem;">$100</span>
        <span class="current-price" style="font-size:3.5rem;font-weight:900;" data-monthly="100" data-yearly="60">$100</span>
        <span class="period">/mo</span>
      </div>
      <span class="pricing-billing yearly-billing" style="display:none;">Billed $720/year (save $480)</span>
      <span class="pricing-launch monthly-billing">→ Limited launch: $10/mo for first 2 months</span>
      <div class="pricing-divider"></div>
      <ul class="pricing-features">
        <li>Basic access to the AI analysis engine</li>
        <li>3 BTC analysis updates per week</li>
        <li>Coverage of 1 main BTC pair</li>
        <li>Access to core dashboard views</li>
      </ul>
      <a href="/login" class="btn btn-secondary">Start for $10</a>
    </div>

    <!-- Pro -->
    <div class="pricing-card featured">
      <span class="pricing-badge popular">Most popular</span>
      <div class="pricing-tier">Pro</div>
      <div class="pricing-name">Trader workspace</div>
      <div class="pricing-amount-wrapper">
        <span class="original-price" style="display:none;text-decoration:line-through !important;color:#64748b;font-size:1.5rem;">$350</span>
        <span class="current-price" style="font-size:3.5rem;font-weight:900;" data-monthly="350" data-yearly="210">$350</span>
        <span class="period">/mo</span>
      </div>
      <span class="pricing-billing yearly-billing" style="display:none;">Billed $2,520/year (save $1,680)</span>
      <span class="pricing-period monthly-billing">&nbsp;</span>
      <div class="pricing-divider"></div>
      <ul class="pricing-features">
        <li>Full dashboard and advanced features</li>
        <li>Full engine access with deeper signals</li>
        <li>Analysis of 5 major BTC markets</li>
        <li>Detailed scenario breakdowns & volatility regimes</li>
        <li>Priority support</li>
      </ul>
      <a href="/login" class="btn btn-primary">Upgrade to Pro</a>
    </div>

    <!-- Full System -->
    <div class="pricing-card">
      <div class="pricing-tier">Full System</div>
      <div class="pricing-name">Talk to us</div>
      <div class="pricing-amount-wrapper">
        <span class="current-price" style="font-size:1.5rem;color:var(--text-secondary);">Custom pricing</span>
      </div>
      <p class="pricing-note-custom">Everything in Pro, plus a dedicated account manager, full autonomous trading setup, custom strategy tuning, and 24/7 monitoring.</p>
      <div class="pricing-divider"></div>
      <ul class="pricing-features">
        <li>Everything in Pro</li>
        <li>Dedicated account manager</li>
        <li>Full feature setup for your account(s)</li>
        <li>24/7 autonomous trading configuration</li>
        <li>Custom strategy tuning & onboarding</li>
      </ul>
      <a href="#apply" class="btn btn-outline">Talk to us</a>
    </div>

  </div>
`;
