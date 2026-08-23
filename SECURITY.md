# Security policy

## Supported version

Security fixes are applied to the latest release and the `main` branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do
not open a public issue with exploit details, credentials, personal data, or
proof-of-concept code that could harm users.

Include the affected version, reproduction steps, impact, and any suggested
mitigation. Reports are reviewed before a public advisory or release note is
published.

## Security boundaries

C DL serves its interface only on `127.0.0.1`. API requests require a random
same-site session cookie and same-origin JSON requests. Downloaded files remain
on the user's computer; the application does not upload them to this project.
