// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// Haptic Feedback & Web Push Subscription Utility (WFM)

export function triggerHaptic(type = 'success') {
  // Physical vibration for Android Chrome / compatible PWA
  try {
    if (typeof navigator !== 'undefined' && navigator.vibrate) {
      if (type === 'tap' || type === 'micro' || type === 'tick') {
        navigator.vibrate(12);
      } else if (type === 'success') {
        navigator.vibrate([12, 35]);
      } else if (type === 'error') {
        navigator.vibrate([120, 60, 120]);
      } else if (type === 'urgent' || type === 'alert') {
        navigator.vibrate([150, 80, 150, 80, 250]);
      } else if (type === 'hold_success') {
        navigator.vibrate([40, 60, 40]);
      }
    }
  } catch (e) {}

  // Web Audio chime / tick fallback for iOS Safari
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      const ctx = new AudioContext();
      if (ctx.state === 'suspended') {
        ctx.resume();
      }
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      if (type === 'urgent' || type === 'alert') {
        // High attention alert chime (G5 -> C6 -> E6)
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(783.99, ctx.currentTime);
        osc.frequency.setValueAtTime(1046.50, ctx.currentTime + 0.1);
        osc.frequency.setValueAtTime(1318.51, ctx.currentTime + 0.22);
        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
        osc.start();
        osc.stop(ctx.currentTime + 0.45);
      } else if (type === 'success' || type === 'hold_success') {
        // High pleasant dual-tone chime (D5 -> A5)
        osc.frequency.setValueAtTime(587.33, ctx.currentTime);
        osc.frequency.setValueAtTime(880.00, ctx.currentTime + 0.08);
        gain.gain.setValueAtTime(0.12, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.28);
        osc.start();
        osc.stop(ctx.currentTime + 0.28);
      } else if (type === 'error') {
        // Low error buzz (A3)
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(220.00, ctx.currentTime);
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
        osc.start();
        osc.stop(ctx.currentTime + 0.25);
      } else if (type === 'tick') {
        // Subtle tick sound
        osc.frequency.setValueAtTime(1000, ctx.currentTime);
        gain.gain.setValueAtTime(0.05, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.04);
        osc.start();
        osc.stop(ctx.currentTime + 0.04);
      }
    }
  } catch (e) {}
}

export function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export async function setupPushNotifications(username) {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return { supported: false };
  }

  try {
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();

    if (!sub) {
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        const res = await fetch('/api/v1/cc/notifications/push/public-key');
        const data = await res.json();
        if (data.public_key) {
          sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(data.public_key)
          });
        }
      }
    }

    if (sub && username) {
      await fetch('/api/v1/cc/notifications/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: username,
          subscription: sub.toJSON(),
          user_agent: navigator.userAgent
        })
      });
      return { supported: true, subscribed: true };
    }

    return { supported: true, subscribed: !!sub };
  } catch (err) {
    console.warn('Push registration notification error:', err);
    return { supported: true, error: err.message };
  }
}

export async function requestPushPermission(username) {
  if (typeof Notification === 'undefined') return false;
  const permission = await Notification.requestPermission();
  if (permission === 'granted' && username) {
    await setupPushNotifications(username);
    return true;
  }
  return false;
}
