# Contributing

This repository implements candidate OpenRGD cognition, not the normative Core.

1. Use a feature branch and a reviewed pull request. Preserve granular commits.
2. Keep source/profile/identity/Chronon authority outside this host. Do not modify
   `OpenRGD/openrgd`, other repositories or physical services implicitly.
3. Run `python -m unittest discover -s tests -v` and the 1000-event demo. Add negative
   fixtures when changing contracts; schema validity alone is not interoperability.
4. Never commit `.env`, keys, personal transcripts, raw media, local databases,
   private RGD instance material, hardware mappings or generated build products.
5. Update maturity, limitations, compatibility and evidence scope. Local CI is not
   a robot test, and a merged candidate is not normative acceptance or a release.

Schema breaking changes require a new explicit candidate version and migration.
Normative acceptance, releases, main protection and Paky-01 deployment are separate
maintainer decisions. This PR does not configure GitHub branch protection.
