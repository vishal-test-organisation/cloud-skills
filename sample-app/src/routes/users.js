const express = require('express');
const router = express.Router();
const db = require('../db');
const logger = require('../middleware/logger');

// GET /users/me  — data access (Art.15 GDPR)
router.get('/me', async (req, res) => {
  const user = await db.query(
    'SELECT id, email, first_name, last_name, phone, date_of_birth, created_at FROM users WHERE id = $1',
    [req.user.id]
  );
  // Missing: does not include audit_logs, sessions, or consent_records in the export
  // GDPR Art.15 gap: access response is incomplete
  res.json(user.rows[0]);
});

// GET /users/export  — data portability (Art.20 GDPR)
// This endpoint is MISSING entirely — no data portability implementation
// router.get('/export', ...) — not implemented

// PUT /users/me  — rectification (Art.16 GDPR)
router.put('/me', async (req, res) => {
  const { first_name, last_name, phone } = req.body;
  await db.query(
    'UPDATE users SET first_name=$1, last_name=$2, phone=$3 WHERE id=$4',
    [first_name, last_name, phone, req.user.id]
  );
  // Correction NOT propagated to third parties (SendGrid contacts, analytics)
  // GDPR Art.19 gap
  res.json({ message: 'Profile updated' });
});

// GET /admin/users  — admin route with no access logging
// Missing: no audit trail for who accessed which user record
// SOC2 CC6.1 gap: data access not logged
router.get('/admin/users', async (req, res) => {
  // No role check — any authenticated user can hit this
  // SOC2 CC6.3 gap: least privilege not enforced
  const users = await db.query('SELECT * FROM users WHERE is_deleted = false');
  res.json(users.rows);
});

// POST /users/restrict  — restriction of processing (Art.18 GDPR)
// NOT IMPLEMENTED — no restriction flag in the database
// GDPR Art.18 gap

// POST /users/object  — right to object (Art.21 GDPR)
// NOT IMPLEMENTED
// GDPR Art.21 gap

module.exports = router;
