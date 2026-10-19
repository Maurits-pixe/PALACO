# Temporary RIO preview on Render

`palaco-rio-temporary` is configured as a Render static site in the repository
root [`render.yaml`](../../render.yaml). It publishes the existing
`website/` files and rewrites the service root to `studio.html`, so the
generated `https://<service-name>.onrender.com/` address opens PALACO Studio's
RIO panel.

This is **not a live RIO platform**. The page provides the deterministic local
guide already present in PALACO Studio. It has no RIO backend, live AI
provider, shared conversations, account service or server-side persistence.
Studio documents remain in the visitor's browser storage and are separate per
origin. The preview uses no production data or secrets.

## Create the temporary address

1. Sign in to Render and connect the `Maurits-pixe/PALACO` GitHub repository.
2. Create a new **Blueprint** using the branch that contains `render.yaml`.
3. Review the Blueprint diff and create the `palaco-rio-temporary` static site.
   Keep the free plan and do not add environment secrets or a database.
4. Wait for the static deployment to finish. Render will show the generated
   `onrender.com` URL in the service page; verify the root opens the Studio
   workspace and the RIO panel is labeled as local/offline.
5. Configure the response security headers in the Render service dashboard.
   Static-site custom headers are not configured by this Blueprint. At minimum
   apply the current contract in
   [`website/security-headers.conf`](../../website/security-headers.conf), then
   inspect the deployed response. Do not weaken the CSP; the page needs no
   network connection.
6. When the preview is no longer needed, delete the Render static site and its
   Blueprint-managed resource. The generated URL is not available until the
   service is created in the Render account.

Render's Blueprint format and static-site behavior are documented in the
[Blueprint YAML reference](https://render.com/docs/blueprint-spec) and
[static-site documentation](https://render.com/docs/static-sites). This
repository configures the build and route only; successful deployment and
actual response headers must be verified in Render.
