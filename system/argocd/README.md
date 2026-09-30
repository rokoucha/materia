# Repository authentication

GitHub App credentials are stored once in the materia 1Password vault as
`argocd-github-app`. `resources/github-app-credentials.yaml` references that
item by stable ID; the existing Operator creates the `repo-creds` Secret and
preserves its label. The item fields are `type=git`,
`url=https://github.com/rokoucha/`, `githubAppID`, `githubAppInstallationID`,
and concealed `githubAppPrivateKey`. The trailing slash limits prefix matching
to this account. The GitHub App installation still determines actual repository
access, with Contents read permission.

Repository definitions in `resources/repositories.yaml` contain only type and
URL. Add a URL there after granting the App installation access; do not add
credentials to individual repository Secrets. Key changes happen only in the
1Password item and are synchronized by the Operator.

During adoption, preserve existing repository Secret names. Wait until the
credential template Secret is present and both connections are Successful,
then remove `githubAppID`, `githubAppInstallationID` and `githubAppPrivateKey`
from the two old registrations. Do not delete the whole repository Secrets:
Argo CD now tracks them through this Kustomization. Verify that each registration
has only `type` and `url`, and both connections still succeed. Repository-specific
credentials otherwise override the shared template.
