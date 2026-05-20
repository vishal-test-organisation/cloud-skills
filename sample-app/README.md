# CloudSkills Sample Application

A Node.js/Express SaaS platform used as the target codebase for SOC 2 and GDPR compliance audits.

## Stack

- **Backend**: Node.js + Express
- **Database**: PostgreSQL 14 (AWS RDS)
- **Storage**: AWS S3
- **Auth**: JWT (jsonwebtoken)
- **Email**: SendGrid
- **Payments**: Stripe
- **Analytics**: GA4 + Hotjar
- **Error tracking**: Sentry
- **Infrastructure**: Terraform on AWS

## Structure

```
sample-app/
├── migrations/
│   └── 001_initial_schema.sql   # DB schema
├── src/
│   ├── routes/
│   │   ├── auth.js              # Registration, login, account deletion
│   │   └── users.js             # Profile, data export, admin
│   └── middleware/
│       ├── logger.js            # Winston logger
│       └── analytics.js         # Frontend tracking scripts
├── terraform/
│   └── main.tf                  # AWS infrastructure
└── .env.example                 # Environment variable reference
```

## Running the SOC 2 and GDPR Skill Audits

The `compliance/soc2-audit/SKILL.md` and `compliance/gdpr-audit/SKILL.md` skills in this repo
provide structured audit frameworks. Load either skill and point it at this codebase to produce
a full compliance report.

### Third-Party Services (GDPR sub-processors)

| Service    | Country | Data Shared          | DPA Status  |
|------------|---------|----------------------|-------------|
| AWS        | US/IE   | All application data | Signed      |
| SendGrid   | US      | Email + name         | Pending     |
| Stripe     | US      | Payment + email      | Signed      |
| Sentry     | US      | Error context + IP   | Not started |
| GA4        | US      | Usage + IP           | Not started |
| Hotjar     | US      | Session recordings   | Not started |
