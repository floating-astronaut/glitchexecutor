document.getElementById('applyContent').innerHTML = `
  <div class="reveal" style="text-align:center;">
    <span class="section-label">Full System</span>
    <h2 class="section-heading">Apply for Full System access</h2>
    <p class="section-subheading" style="margin-left:auto;margin-right:auto;">We take on a limited number of Full System clients. Tell us what you're trading and what you want the engine to do for you.</p>
  </div>
  <div class="lead-form-wrapper reveal">
    <form id="leadForm">
      <div class="form-group">
        <label class="form-label">Name</label>
        <input type="text" class="form-input" placeholder="Your full name" required>
      </div>
      <div class="form-group">
        <label class="form-label">Email</label>
        <input type="email" class="form-input" placeholder="you@email.com" required>
      </div>
      <div class="form-group">
        <label class="form-label">Preferred contact (Telegram / WhatsApp / Signal)</label>
        <input type="text" class="form-input" placeholder="@handle or phone number">
      </div>
      <div class="form-group">
        <label class="form-label">Trading experience level</label>
        <select class="form-select" required>
          <option value="" disabled selected>Select your level</option>
          <option value="beginner">Beginner — less than 1 year</option>
          <option value="intermediate">Intermediate — 1 to 3 years</option>
          <option value="advanced">Advanced — 3+ years</option>
          <option value="professional">Professional / institutional</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Approximate account size</label>
        <select class="form-select" required>
          <option value="" disabled selected>Select a range</option>
          <option value="under-10k">Under $10,000</option>
          <option value="10k-50k">$10,000 – $50,000</option>
          <option value="50k-250k">$50,000 – $250,000</option>
          <option value="250k-1m">$250,000 – $1,000,000</option>
          <option value="over-1m">Over $1,000,000</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">What are you looking for?</label>
        <textarea class="form-textarea" placeholder="Tell us what you're trading and what you want the engine to handle for you." required></textarea>
      </div>
      <button type="submit" class="btn btn-primary" style="width:100%;">Submit application</button>
      <p class="form-privacy">
        <i class="fa-solid fa-lock" style="margin-right:6px;font-size:0.7rem;"></i>
        Your data is confidential. We never sell or share it. It's only used to respond to your request and set up your account.
      </p>
    </form>
    <div class="form-success" id="formSuccess">
      <i class="fa-solid fa-circle-check"></i>
      <h3>Application received</h3>
      <p>We'll review your details and get back to you within 48 hours. Watch your inbox.</p>
    </div>
  </div>
`;
