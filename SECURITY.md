# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest (`main`) | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability in Odit, please **do not open a public issue**. Instead:

1. Open a [GitHub Security Advisory](https://github.com/venk-hub/Odit/security/advisories/new) (private disclosure)
2. Or email the maintainer directly via the GitHub profile

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix if you have one

You'll receive a response within 5 business days. We'll work with you to understand the issue and coordinate a fix before any public disclosure.

## Scope

Odit is a **local-only tool** — it runs entirely on your machine via Docker and makes no outbound connections except:

- Browser traffic to the site you are auditing
- Anthropic API calls (only if you configure an API key)

There is no Odit cloud service, no user accounts, and no data sent to any third party by Odit itself.

## Responsible Use

Only audit websites you own or have **explicit written permission** to test. Unauthorised automated crawling may violate the Computer Fraud and Abuse Act (US), the Computer Misuse Act (UK), GDPR (EU), and equivalent laws in other jurisdictions.
