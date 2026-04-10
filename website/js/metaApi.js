// Meta/Facebook Pixel Event Tracking for GlitchExecutor

// Track landing page view
fbq('track', 'ViewContent', {
  content_name: 'GlitchExecutor Landing Page',
  content_category: 'landing'
});

// Track pricing page view
function trackPricingView() {
  fbq('track', 'ViewContent', {
    content_name: 'Pricing Page',
    content_category: 'pricing',
    content_type: 'product'
  });
}

// Track subscription button clicks
function trackLead(label, value) {
  fbq('track', 'Lead', {
    content_name: label || 'Subscription Click',
    value: value || 0,
    currency: 'USD'
  });
}

// Track contact form submissions
function trackContactFormSubmit(formType) {
  fbq('track', 'Lead', {
    content_name: 'Contact Form Submission',
    content_type: formType || 'contact_form',
    value: 0,
    currency: 'USD'
  });
}

// Track login
function trackLogin() {
  fbq('track', 'CompleteRegistration', {
    content_name: 'User Login',
    value: 0,
    currency: 'USD'
  });
}

// Track subscription start (InitiateCheckout)
function trackSubscribeStart(planName, value) {
  fbq('track', 'InitiateCheckout', {
    content_name: planName || 'Subscription',
    content_type: 'product',
    value: value || 0,
    currency: 'USD'
  });
}

// Track successful purchase
function trackPurchase(planName, value) {
  fbq('track', 'Purchase', {
    content_name: planName || 'Subscription',
    content_type: 'product',
    value: value || 0,
    currency: 'USD'
  });
}
