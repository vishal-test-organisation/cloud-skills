// Frontend analytics integration
// Loads Google Analytics on every page — BEFORE user consent is collected
// GDPR ePrivacy Directive violation + GDPR Art.6 violation

// analytics.js — loaded in <head> unconditionally
(function() {
  // GA4 fires immediately on page load, no consent check
  window.dataLayer = window.dataLayer || [];
  function gtag() { dataLayer.push(arguments); }
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXX', {
    // send_page_view fires before consent banner is shown
    send_page_view: true,
    // user_id set from local storage — includes PII
    user_id: localStorage.getItem('userId'),
  });

  // Hotjar loaded unconditionally — no consent gate
  (function(h, o, t, j, a, r) {
    h.hj = h.hj || function() { (h.hj.q = h.hj.q || []).push(arguments); };
    h._hjSettings = { hjid: 1234567, hjsv: 6 };
    a = o.getElementsByTagName('head')[0];
    r = o.createElement('script'); r.async = 1;
    r.src = t + h._hjSettings.hjid + j + h._hjSettings.hjsv;
    a.appendChild(r);
  })(window, document, 'https://static.hotjar.com/c/hotjar-', '.js?sv=');

  // No consent mode configured for GA4
  // No gtag('consent', 'default', { ... }) call
  // No mechanism to block scripts before consent is given
  // No "Reject All" option presented to the user
})();
