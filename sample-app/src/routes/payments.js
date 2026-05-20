const express = require('express');
const router = express.Router();
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const db = require('../db');
const logger = require('../middleware/logger');

// POST /payments/charge
router.post('/charge', async (req, res) => {
  const { amount, currency, card_number, expiry, cvv } = req.body;

  // CRITICAL: accepting raw card data — PCI DSS Req 3 violation
  // Card number, CVV, and expiry are passing through the server
  // This puts the entire system in PCI DSS scope
  logger.info(`Payment attempt: card=${card_number}, amount=${amount}`);  // PAN in logs!

  try {
    // Should use Stripe Elements / tokenisation — not raw card data
    const paymentMethod = await stripe.paymentMethods.create({
      type: 'card',
      card: { number: card_number, exp_month: expiry.split('/')[0], exp_year: expiry.split('/')[1], cvc: cvv },
    });

    const charge = await stripe.paymentIntents.create({
      amount,
      currency: currency || 'usd',
      payment_method: paymentMethod.id,
      confirm: true,
    });

    // Storing card details in DB — PCI DSS Req 3.2 critical violation
    await db.query(
      'INSERT INTO payments (user_id, card_last4, card_number_encrypted, amount, status) VALUES ($1,$2,$3,$4,$5)',
      [req.user.id, card_number.slice(-4), card_number, amount, charge.status]
      // card_number_encrypted column stores the RAW card number — not encrypted
    );

    logger.info(`Payment successful: user=${req.user.id}, amount=${amount}, card=${card_number}`);

    res.json({ success: true, charge_id: charge.id });
  } catch (err) {
    // Error includes card data in the message — leaks PAN to error logs
    logger.error(`Payment failed for card ${card_number}: ${err.message}`);
    res.status(500).json({ error: 'Payment failed' });
  }
});

// GET /payments/history
router.get('/history', async (req, res) => {
  // Returns full payment records including partial card data
  // No pagination — full history dump, potential data minimisation issue
  const payments = await db.query(
    'SELECT * FROM payments WHERE user_id = $1',
    [req.user.id]
  );
  res.json(payments.rows);
});

module.exports = router;
