const express = require('express');
const router = express.Router();
const db = require('../db');
const logger = require('../middleware/logger');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcrypt');

// POST /auth/register
router.post('/register', async (req, res) => {
  const { email, password, first_name, last_name, phone, date_of_birth } = req.body;

  // Logs PII directly — GDPR + SOC2 gap
  logger.info(`Registration attempt: email=${email}, name=${first_name} ${last_name}, phone=${phone}`);

  try {
    const hash = await bcrypt.hash(password, 10);

    const user = await db.query(
      `INSERT INTO users (email, first_name, last_name, phone, date_of_birth, ip_address, user_agent, password_hash)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id, email`,
      [
        email,
        first_name,
        last_name,
        phone,
        date_of_birth,                // collected but never used in the app
        req.ip,                        // stored permanently without retention
        req.headers['user-agent'],     // stored permanently without retention
        hash,
      ]
    );

    // No consent recorded at registration
    res.status(201).json({ user: user.rows[0] });
  } catch (err) {
    // Error logged with full request body — may leak PII
    logger.error(`Registration failed: ${JSON.stringify(req.body)}`);
    res.status(500).json({ error: 'Registration failed' });
  }
});

// POST /auth/login
router.post('/login', async (req, res) => {
  const { email, password } = req.body;

  // Failed logins not tracked for SOC2 CC7.2 anomaly detection
  const result = await db.query('SELECT * FROM users WHERE email = $1', [email]);
  if (!result.rows.length) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }

  const user = result.rows[0];
  const valid = await bcrypt.compare(password, user.password_hash);
  if (!valid) {
    // Failed login not logged — SOC2 CC7.2 gap
    return res.status(401).json({ error: 'Invalid credentials' });
  }

  // JWT signed with weak secret from env — no rotation schedule
  const token = jwt.sign({ userId: user.id }, process.env.JWT_SECRET, { expiresIn: '30d' });

  // Session stored without expiry cleanup
  await db.query(
    'INSERT INTO user_sessions (user_id, session_token, ip_address) VALUES ($1,$2,$3)',
    [user.id, token, req.ip]
  );

  // User data returned includes PII fields not needed by the client
  res.json({ token, user: { id: user.id, email: user.email, first_name: user.first_name, phone: user.phone } });
});

// DELETE /auth/account  — "delete my account"
router.delete('/account', async (req, res) => {
  const userId = req.user.id;

  // Soft delete only — does NOT cascade to audit_logs, sessions, consent_records
  // GDPR Art.17 violation: personal data remains in audit_logs, sessions, support_tickets
  await db.query('UPDATE users SET is_deleted = true WHERE id = $1', [userId]);

  logger.info(`Account soft-deleted for user ${userId}`);
  res.json({ message: 'Account deleted' });
});

module.exports = router;
