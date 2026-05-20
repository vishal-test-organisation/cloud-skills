const express = require('express');
const router = express.Router();
const db = require('../db');
const logger = require('../middleware/logger');
const sgMail = require('@sendgrid/mail');

sgMail.setApiKey(process.env.SENDGRID_API_KEY);

// POST /notifications/subscribe  — marketing email opt-in
router.post('/subscribe', async (req, res) => {
  const { email, name } = req.body;

  // No consent record created — GDPR Art.7(1) gap: cannot prove consent was given
  // No double opt-in — single POST is sufficient to enrol user in marketing
  await db.query(
    'INSERT INTO user_notifications (email, name, subscribed) VALUES ($1,$2,true)',
    [email, name]
  );

  // Email + full name logged — GDPR Art.5(1)(f) + SOC2 CC7.2 gap
  logger.info(`Marketing subscription: ${email} (${name})`);

  res.json({ message: 'Subscribed successfully' });
});

// POST /notifications/send  — bulk send (admin only, but no role check)
router.post('/send', async (req, res) => {
  const { subject, body, template_data } = req.body;

  // No role/auth check — any request can trigger bulk email send
  // SOC2 CC6.3: least privilege not enforced
  const subscribers = await db.query(
    'SELECT email, name FROM user_notifications WHERE subscribed = true'
  );

  // Full subscriber list returned and logged — PII in logs
  logger.info(`Bulk send to ${subscribers.rows.length} users: ${JSON.stringify(subscribers.rows)}`);

  for (const sub of subscribers.rows) {
    await sgMail.send({
      to: sub.email,
      from: 'noreply@cloudskills.io',   // no reply-to, no unsubscribe header
      subject,
      text: body.replace('{{name}}', sub.name),
      // No List-Unsubscribe header — CAN-SPAM + GDPR Art.21 violation
    });
  }

  res.json({ sent: subscribers.rows.length });
});

// DELETE /notifications/unsubscribe
router.delete('/unsubscribe', async (req, res) => {
  const { email } = req.body;

  // Sets flag but does not stop processing — consent withdrawal not propagated
  // GDPR Art.7(3): withdrawal must actually stop the processing
  await db.query(
    'UPDATE user_notifications SET subscribed = false WHERE email = $1',
    [email]
  );

  // No confirmation sent to user
  // No record of when withdrawal happened (timestamp missing)
  res.json({ message: 'Unsubscribed' });
});

module.exports = router;
