/**
 * PyForgeLabs Exam Integrity Monitor & Heartbeat Service
 * -------------------------------------------------------
 * Captures browser-observable visibility changes, fullscreen exits,
 * network connectivity events, and sends periodic authenticated heartbeats.
 * 
 * Note: Operational indicators only — not proof of cheating. All events are
 * queued for invigilator/administrator review.
 */
(function() {
  const INTEGRITY_ENDPOINT = '/recruitment/integrity/event/';
  const HEARTBEAT_ENDPOINT = '/recruitment/heartbeat/';
  const HEARTBEAT_INTERVAL_MS = 15000; // 15 seconds
  let lastReportTime = 0;
  const REPORT_COOLDOWN_MS = 2000;
  let eventCounters = {};
  const examStartTime = Date.now();

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function sendIntegrityEvent(eventType, extraContext) {
    const now = Date.now();
    if (now - lastReportTime < REPORT_COOLDOWN_MS) {
      return;
    }
    lastReportTime = now;

    eventCounters[eventType] = (eventCounters[eventType] || 0) + 1;

    const payload = {
      event_type: eventType,
      client_ts: new Date().toISOString(),
      elapsed_seconds: Math.floor((now - examStartTime) / 1000),
      event_count: eventCounters[eventType],
      ...(extraContext || {})
    };

    const csrftoken = getCookie('csrftoken');

    try {
      fetch(INTEGRITY_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrftoken || ''
        },
        body: JSON.stringify(payload)
      }).then(function(res) {
        if (res.ok) {
          return res.json();
        }
      }).then(function(data) {
        if (data && data.flagged) {
          console.warn('[PyForgeLabs] Session flagged for invigilator review.');
        }
      }).catch(function(err) {
        // Silently continue during standalone CBT exams
      });
    } catch (e) {
      // Ignore network errors during page unload
    }
  }

  // Periodic Heartbeat
  function sendHeartbeat() {
    const csrftoken = getCookie('csrftoken');
    try {
      fetch(HEARTBEAT_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrftoken || ''
        },
        body: JSON.stringify({
          client_ts: new Date().toISOString()
        })
      }).then(function(res) {
        if (res.ok) return res.json();
      }).catch(function() {
        // Suppress network errors during offline testing
      });
    } catch (e) {}
  }

  // 1. Start heartbeat interval
  sendHeartbeat(); // Immediate first ping
  setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);

  // 2. Visibility change listener (Tab hidden)
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
      sendIntegrityEvent('TAB_HIDDEN', {
        reason: 'browser_tab_hidden'
      });
    }
  });

  // 3. Fullscreen exit listener
  document.addEventListener('fullscreenchange', function() {
    if (!document.fullscreenElement) {
      sendIntegrityEvent('FULLSCREEN_EXIT', {
        reason: 'user_exited_fullscreen'
      });
    }
  });

  // 4. Online / Offline network detection
  window.addEventListener('offline', function() {
    sendIntegrityEvent('DISCONNECT', { reason: 'browser_went_offline' });
  });

  window.addEventListener('online', function() {
    sendIntegrityEvent('RECONNECT', { reason: 'browser_came_online' });
  });

  // 5. Paste detection in inputs
  document.addEventListener('paste', function(e) {
    const activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
      sendIntegrityEvent('PASTE_DETECTED', {
        target: activeEl.name || activeEl.id || 'text_input'
      });
    }
  }, true);

})();
