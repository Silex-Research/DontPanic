// ── JARVIS Dashboard — Firebase realtime opt-in TEMPLATE ──
//
// Copy this file to `firebase-config.local.js` (gitignored), fill in the
// REPLACE_* placeholders with values from the Firebase console for the
// jarvis-a6ee1 project, and load it from your HTML BEFORE config-firebase.js:
//
//   <script>
//     window.__JARVIS_FIREBASE_CONFIG__ = {
//       projectId:         'jarvis-a6ee1',
//       authDomain:        'jarvis-a6ee1.firebaseapp.com',
//       storageBucket:     'jarvis-a6ee1.appspot.com',
//       apiKey:            '<paste from firebase console>',
//       appId:             '<paste from firebase console>',
//       messagingSenderId: '<paste from firebase console>',
//     };
//   </script>
//
// See dashboard/index-firebase.html for the full opt-in entry point.
//
// IMPORTANT — credential gate:
// Real values for the placeholders below are deferred to plan
// 2026-05-09-004 F003+ per parent_acceptance_item / D007. The bundled
// static dashboard (index.html) works without any of this configuration.

window.__JARVIS_FIREBASE_CONFIG__ = {
  projectId: 'jarvis-a6ee1',
  authDomain: 'jarvis-a6ee1.firebaseapp.com',
  storageBucket: 'jarvis-a6ee1.appspot.com',
  apiKey: 'REPLACE_WITH_OPERATOR_API_KEY',
  appId: 'REPLACE_WITH_OPERATOR_APP_ID',
  messagingSenderId: 'REPLACE_WITH_OPERATOR_SENDER_ID',
};
