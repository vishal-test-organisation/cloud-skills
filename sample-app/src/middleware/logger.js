const winston = require('winston');

// Logs are shipped to CloudWatch — no PII scrubbing before export
// SOC2 CC4.1: logs retained 30 days only (below audit period minimum)
// GDPR Art.5(1)(e): no retention limit enforced on log content

const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()   // full JSON — PII not stripped before logging
  ),
  transports: [
    new winston.transports.Console(),
    new winston.transports.File({ filename: 'app.log', maxsize: 10485760 }),
    // CloudWatch transport added but retention set to 30 days — SOC2 gap
  ],
});

// No PII scrubbing middleware — email, phone, name can appear in log lines
// Example violation: logger.info(`User ${email} logged in`) is called in auth.js

module.exports = logger;
