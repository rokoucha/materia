Status: operational configuration for new-image OCR; workload authentication and synthetic-image recognition verified.

Last reviewed: 2026-09-10.

# Sophie Cloud Vision OCR

Sophie uses project `sophie-503913` (number `227166113239`) and service account
`sophie-ocr@sophie-503913.iam.gserviceaccount.com`. Billing and Cloud Vision API
are enabled. The account has `roles/serviceusage.serviceUsageConsumer`; no
service-account key or Cloud Storage access is required for inline images.

Workload Identity Federation pool `sophie-kubernetes`, provider `materia-cluster`,
trusts the Kubernetes issuer `https://materia-cluster.ggrel.net:6443`. Its subject
condition and service-account impersonation binding restrict access to
`system:serviceaccount:sophie:sophie-ocr`. The server projects a one-hour token
with the provider audience and mounts a non-secret ADC configuration.

Set `GOOGLE_CLOUD_PROJECT=sophie-503913` alongside `GOOGLE_APPLICATION_CREDENTIALS`.
Without an explicit project, GoogleAuth attempts Resource Manager project
discovery, which fails with `ACCESS_TOKEN_SCOPE_INSUFFICIENT` under Sophie's
Cloud Vision scope before an image request is made. Do not broaden the scope or
grant additional Resource Manager permissions to work around that discovery.

The provider uses uploaded Kubernetes JWKS because the discovery document's
JWKS URL is private. When Kubernetes signing keys rotate, upload the current
public JWKS to the provider before removing old signing keys. This is a public
key set, never a projected token or private key.

`OCR_ENABLED=true` admits eligible new images; the extractor body limit is 280
characters and non-blank image alt text excludes admission. Existing images
are not backfilled, and OCR search projection remains separate Sophie work.
The verified request and document-text quotas are each 1,800 calls per minute
per project. Google charges for eligible API calls, including possible retries. Sophie has
shared concurrency control and bounded retries, but no daily spend cap; review
project quotas and billing before increasing admission or starting backfill.
Pause OCR by setting `OCR_ENABLED=false` through a materia pull request.

Verification uses a synthetic raster containing `SOPHIE` and the same
`cloud-vision` scope as the application. Require both HTTP 200 and the expected
recognized text; HTTP 200 alone can contain a per-image error or an empty result.
Never print access tokens, provider responses, or library image contents.

References:

- [Kubernetes federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-kubernetes)
- [Vision authentication](https://docs.cloud.google.com/vision/docs/authentication)
