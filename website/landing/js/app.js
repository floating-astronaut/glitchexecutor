/* ============================================
   Glitch Executor — App Interactivity
   ============================================ */

// --- Navigation Links ---
const navLinksContainer = document.getElementById('navLinks');
const navMobile = document.getElementById('navMobile');

const links = [
  { label: 'Product', href: '#engine' },
  { label: 'Pricing', href: '#pricing' },
];

navLinksContainer.innerHTML = links.map(l =>
  `<li><a href="${l.href}">${l.label}</a></li>`
).join('') + `<li><a href="/login" class="btn btn-primary btn-sm">Login</a></li>`;

navMobile.innerHTML = links.map(l =>
  `<a href="${l.href}">${l.label}</a>`
).join('') + `<a href="/login">Login</a>`;

// --- Hamburger Toggle ---
const hamburger = document.getElementById('navHamburger');
hamburger.addEventListener('click', () => {
  hamburger.classList.toggle('active');
  navMobile.classList.toggle('open');
});

// Close mobile nav on link click
navMobile.querySelectorAll('a').forEach(a => {
  a.addEventListener('click', () => {
    hamburger.classList.remove('active');
    navMobile.classList.remove('open');
  });
});

// --- Nav Scroll Effect ---
const nav = document.getElementById('nav');
window.addEventListener('scroll', () => {
  nav.classList.toggle('scrolled', window.scrollY > 40);
});

// --- Scroll Reveal ---
const revealElements = document.querySelectorAll('.reveal');
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
    }
  });
}, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

revealElements.forEach(el => revealObserver.observe(el));

// --- Lead Form ---
const leadForm = document.getElementById('leadForm');
if (leadForm) {
  leadForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const formEl = leadForm;
    const successEl = document.getElementById('formSuccess');
    if (formEl && successEl) {
      formEl.style.display = 'none';
      successEl.style.display = 'block';
    }
  });
}

// Pricing toggle functionality
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    var toggle = document.getElementById('billingToggle');
    if (toggle) {
      toggle.addEventListener('change', function() {
        var isYearly = this.checked;
        
        // Update toggle labels
        var monthlyLabel = document.getElementById('toggleMonthly');
        var yearlyLabel = document.getElementById('toggleYearly');
        if (monthlyLabel && yearlyLabel) {
          monthlyLabel.classList.toggle('active', !isYearly);
          yearlyLabel.classList.toggle('active', isYearly);
        }
        
        // Update prices
        document.querySelectorAll('.current-price').forEach(function(el) {
          var monthly = el.dataset.monthly;
          var yearly = el.dataset.yearly;
          if (monthly && yearly && monthly !== 'custom') {
            el.textContent = isYearly ? '$' + yearly : '$' + monthly;
          }
        });
        
        // Show/hide original price (strikethrough)
        document.querySelectorAll('.original-price').forEach(function(el) {
          el.style.display = isYearly ? 'inline' : 'none';
        });
        
        // Show/hide billing text
        document.querySelectorAll('.monthly-billing').forEach(function(el) {
          el.style.display = isYearly ? 'none' : 'inline';
        });
        document.querySelectorAll('.yearly-billing').forEach(function(el) {
          el.style.display = isYearly ? 'inline' : 'none';
        });
      });
      
      // Initialize: hide yearly elements on load (monthly mode)
      document.querySelectorAll('.original-price').forEach(function(el) {
        el.style.display = 'none';
      });
      document.querySelectorAll('.yearly-billing').forEach(function(el) {
        el.style.display = 'none';
      });
      document.querySelectorAll('.monthly-billing').forEach(function(el) {
        el.style.display = 'inline';
      });
    }
  }, 500);
});

// ============================================
// Meta & TikTok Event Tracking
// ============================================

// Track pricing page view
if (document.getElementById('pricingContent')) {
  if (typeof trackPricingView === 'function') trackPricingView();
  if (typeof ttq !== 'undefined') {
    ttq.track('ViewContent', {
      content_name: 'Pricing Page',
      content_type: 'product'
    });
  }
}

// Track pricing button clicks
document.addEventListener('click', function(e) {
  var btn = e.target.closest('.btn');
  if (!btn) return;
  
  var href = btn.getAttribute('href') || '';
  var text = btn.textContent.trim().toLowerCase();
  
  // Pricing buttons
  if (href === '/login' || text.includes('start') || text.includes('upgrade') || text.includes('pro')) {
    var planName = 'Basic';
    var planValue = 10;
    
    if (text.includes('pro') || text.includes('upgrade')) {
      planName = 'Pro';
      planValue = 350;
    }
    
    // Meta tracking
    if (typeof trackLead === 'function') {
      trackLead(planName + ' Plan Click', planValue);
    }
    
    // TikTok tracking
    if (typeof ttq !== 'undefined') {
      ttq.track('InitiateCheckout', {
        content_id: 'pricing_' + planName.toLowerCase(),
        content_type: 'product',
        content_name: planName + ' Plan',
        value: planValue,
        currency: 'USD'
      });
    }
  }
  
  // Contact form "Talk to us" button
  if (href === '#apply' || text.includes('talk to us')) {
    if (typeof trackLead === 'function') {
      trackLead('Talk to Us Click', 0);
    }
    if (typeof ttq !== 'undefined') {
      ttq.track('Contact', {
        content_name: 'Talk to Us',
        content_type: 'lead'
      });
    }
  }
});

// Track contact form submission
document.addEventListener('submit', function(e) {
  var form = e.target;
  if (!form) return;
  
  if (form.id === 'leadForm' || form.classList.contains('lead-form')) {
    e.preventDefault();
    
    // Meta tracking
    if (typeof trackContactFormSubmit === 'function') {
      trackContactFormSubmit('Full System Application');
    }
    
    // TikTok tracking
    if (typeof ttq !== 'undefined') {
      ttq.track('SubmitApplication', {
        content_name: 'Full System Application',
        content_type: 'lead'
      });
    }
    
    // Allow form to submit after tracking
    setTimeout(function() {
      form.submit();
    }, 100);
  }
});
