document.getElementById('trustContent').innerHTML = `
  <div class="reveal">
    <span class="section-label">No fine print tricks</span>
    <h2 class="section-heading">Built on transparency, not trust-me-bro</h2>
    <p class="section-subheading">We'd rather under-promise and over-deliver than the other way around.</p>
  </div>
  <div class="trust-grid reveal">
    <ul class="trust-bullets">
      <li>
        <i class="fa-solid fa-eye"></i>
        <span><strong>No secret guru.</strong> The engine and process are documented conceptually. You know what's running and why.</span>
      </li>
      <li>
        <i class="fa-solid fa-sliders"></i>
        <span><strong>You stay in control.</strong> Stop, change, or go fully manual at any point. No lock-in, no guilt trips.</span>
      </li>
      <li>
        <i class="fa-solid fa-ban"></i>
        <span><strong>No performance promises.</strong> No guaranteed returns. No cherry-picked backtests. We show the process, not fantasy curves.</span>
      </li>
      <li>
        <i class="fa-solid fa-wrench"></i>
        <span><strong>Analysis tool, not a money printer.</strong> We give you reads — you make the decisions.</span>
      </li>
    </ul>
    <div class="risk-box">
      <div class="risk-box-title">
        <i class="fa-solid fa-triangle-exclamation"></i> Risk disclaimer
      </div>
      <p>
        Crypto trading involves significant risk. You can lose money, including your entire principal. Nothing on this platform constitutes financial advice. All trading decisions are ultimately yours. Past patterns and analysis do not guarantee future results. Only trade with capital you can afford to lose.
      </p>
    </div>
  </div>
`;

document.getElementById('footerContent').innerHTML = `
  <div class="footer-inner">
    <div class="footer-logo">glitch<span class="logo-accent">_executor</span></div>
    <div class="footer-links">
      <a href="#engine">Product</a>
      <a href="#pricing">Pricing</a>
      <a href="#trust">Risk Disclaimer</a>
      <a href="#">Terms</a>
      <a href="#">Privacy</a>
      <a href="mailto:contact@glitchexecutor.com">Contact</a>
    </div>
    <div class="footer-copy">&copy; ${new Date().getFullYear()} Glitch Executor. All rights reserved. This platform does not provide financial advice.</div>
  </div>
`;
